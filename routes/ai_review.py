"""AI Review routes for Stage 2 -> 3 transition.

Integrates with the Reviewer3.com API for AI-powered manuscript review.
Flow: ensure R3 user -> upload PDF -> poll for results -> display comments.
Authors upload revised manuscript + response letter PDF for synchronous re-scoring via /revise.
Auto-advances to stage 4 when all revision scores >= 3. Desk rejects after 3 failed attempts.
"""
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from datetime import datetime
from html import escape as html_escape
import json
from models.database import get_db
from models.paper import Paper, PaperVersion, PaperHumanAuthor
from models.review import AIReview
from models.user import User
from services.reviewer3 import reviewer3_service
from services.stage_transition import stage_transition_service
from services.file_storage import file_storage
from services.user_email import add_email_if_new

router = APIRouter(prefix="/paper", tags=["ai_review"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


def _is_paper_author(paper_id: int, user_id: int, db: Session) -> bool:
    """Check if user is an author of the paper."""
    return db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id == user_id,
    ).first() is not None


def _get_pdf_path(paper: Paper, db: Session, version_number: int = None) -> str:
    """Get the filesystem path to a paper's PDF (current version by default)."""
    v = version_number or paper.current_version
    paper_version = db.query(PaperVersion).filter(
        PaperVersion.paper_id == paper.id,
        PaperVersion.version_number == v,
    ).first()

    if not paper_version:
        return None

    file_path = file_storage.get_file_path(
        paper_version.pdf_filename,
        paper.published_date,
    )

    if not file_path.exists():
        return None

    return str(file_path)


def _complete_review(ai_review: AIReview, r3_data: dict, db: Session):
    """Mark an AI review as completed from Reviewer3 data. Auto-approve if 0 comments."""
    ai_review.status = "completed"
    ai_review.completed_at = datetime.utcnow()
    comments = r3_data.get("comments", [])
    ai_review.review_content = "\n\n".join(
        f"**{c.get('reviewerId', 'Reviewer')}**: {c.get('comment', '')}"
        for c in comments
    )
    ai_review.review_data = {
        **(ai_review.review_data or {}),
        **r3_data,
    }
    # Preserve full unmodified API response
    ai_review.raw_api_response = r3_data
    # Auto-approve if zero comments
    if len(comments) == 0:
        ai_review.approved = True
    db.commit()

    # If approved, auto-advance to stage 4
    if ai_review.approved:
        paper = ai_review.paper
        if paper.review_stage == 3:
            stage_transition_service.advance_to_human_review(
                paper.id, paper.human_authors[0].user_id if paper.human_authors else 0, db
            )


def _build_review_markdown(paper: Paper, all_reviews: list[AIReview]) -> str:
    """Build a markdown document from all AI review rounds."""
    lines = []
    lines.append(f"# AI Review Report")
    lines.append(f"")
    lines.append(f"**Paper:** {paper.title}")
    lines.append(f"**Paper ID:** {paper.id}")

    # Determine review service
    service = "AI Review Service"
    for r in all_reviews:
        if r.reviewer3_tracking_id:
            service = "Reviewer3.com"
            break
    lines.append(f"**Review Service:** {service}")
    lines.append(f"**Generated:** {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}")
    lines.append(f"")
    lines.append(f"---")

    for review in all_reviews:
        lines.append(f"")
        status_label = "Approved" if review.approved else review.status.capitalize()
        lines.append(f"## Round {review.review_round} — {status_label}")
        if review.paper_version:
            lines.append(f"*Paper version: v{review.paper_version}*")
        if review.submitted_at:
            lines.append(f"*Submitted: {review.submitted_at.strftime('%B %d, %Y at %H:%M UTC')}*")
        if review.completed_at:
            lines.append(f"*Completed: {review.completed_at.strftime('%B %d, %Y at %H:%M UTC')}*")
        lines.append(f"")

        if review.status != "completed":
            lines.append(f"*Review status: {review.status}*")
            lines.append(f"")
            continue

        # Revision rounds (2+): show scored evaluations from revision_scores
        if review.review_round > 1 and review.revision_scores:
            score_labels = {1: "Ignored", 2: "Weakly acknowledged", 3: "Well acknowledged", 4: "Fully addressed"}
            if review.desk_rejected:
                lines.append(f"**Desk Rejected**")
                lines.append(f"")
            for i, ev in enumerate(review.revision_scores, 1):
                score = ev.get("score", 0)
                label = score_labels.get(score, "Unknown")
                lines.append(f"### Comment {i} — {score}/4 ({label})")
                lines.append(f"")
                if ev.get("originalComment"):
                    lines.append(f"**Original comment:** {ev['originalComment']}")
                    lines.append(f"")
                if ev.get("authorResponse"):
                    lines.append(f"> **Author response:** {ev['authorResponse']}")
                    lines.append(f"")
                if ev.get("reviewerResponse"):
                    lines.append(f"**Reviewer assessment:** {ev['reviewerResponse']}")
                    lines.append(f"")
            lines.append(f"---")
            continue

        # Round 1: show original comments from review_data
        comments = []
        if review.review_data and isinstance(review.review_data, dict):
            comments = review.review_data.get("comments", [])

        if not comments:
            lines.append(f"No comments returned (auto-approved).")
            lines.append(f"")
            lines.append(f"---")
            continue

        for i, c in enumerate(comments, 1):
            reviewer_id = c.get("reviewerId", f"Reviewer {i}")
            comment_text = c.get("comment", "")
            lines.append(f"### {reviewer_id}")
            lines.append(f"")
            lines.append(comment_text)
            lines.append(f"")

        lines.append(f"---")

    return "\n".join(lines)


@router.get("/{paper_id}/ai-review/summary", response_class=HTMLResponse)
async def ai_review_summary(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Public AI review summary page — viewable by anyone once review is completed."""
    from main import templates as main_templates

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Only show once AI review has completed (stage 4+, or stage 3 with completed reviews)
    all_reviews = db.query(AIReview).filter(
        AIReview.paper_id == paper_id,
        AIReview.review_cycle == paper.review_cycle,
        AIReview.status == "completed",
    ).order_by(AIReview.review_round.asc()).all()

    if not all_reviews:
        raise HTTPException(status_code=404, detail="No completed AI reviews found for this paper")

    session_user = request.session.get("user")
    is_author = False
    if session_user:
        is_author = _is_paper_author(paper_id, session_user["id"], db)

    score_labels = {1: "Ignored", 2: "Weakly acknowledged", 3: "Well acknowledged", 4: "Fully addressed"}
    score_colors = {1: "red", 2: "amber", 3: "emerald", 4: "green"}

    return main_templates.TemplateResponse(
        "ai_review_summary.html",
        {
            "request": request,
            "paper": paper,
            "user": session_user,
            "all_reviews": all_reviews,
            "is_author": is_author,
            "score_labels": score_labels,
            "score_colors": score_colors,
        },
    )


@router.get("/{paper_id}/ai-review/export/markdown")
async def export_review_markdown(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Download AI review as markdown."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Allow export for papers that passed AI review (stage 4+), require auth otherwise
    if paper.review_stage < 4:
        session_user = request.session.get("user")
        if not session_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not _is_paper_author(paper_id, session_user["id"], db):
            raise HTTPException(status_code=403, detail="Only paper authors can export reviews")

    all_reviews = db.query(AIReview).filter(
        AIReview.paper_id == paper_id,
        AIReview.review_cycle == paper.review_cycle,
    ).order_by(AIReview.review_round.asc()).all()

    if not all_reviews:
        raise HTTPException(status_code=404, detail="No AI reviews found")

    md_content = _build_review_markdown(paper, all_reviews)

    return Response(
        content=md_content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ai-review-paper-{paper_id}.md"',
        },
    )


@router.get("/{paper_id}/ai-review/export/pdf")
async def export_review_pdf(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Download AI review as PDF."""
    from fpdf import FPDF

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Allow export for papers that passed AI review (stage 4+), require auth otherwise
    if paper.review_stage < 4:
        session_user = request.session.get("user")
        if not session_user:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not _is_paper_author(paper_id, session_user["id"], db):
            raise HTTPException(status_code=403, detail="Only paper authors can export reviews")

    all_reviews = db.query(AIReview).filter(
        AIReview.paper_id == paper_id,
        AIReview.review_cycle == paper.review_cycle,
    ).order_by(AIReview.review_round.asc()).all()

    if not all_reviews:
        raise HTTPException(status_code=404, detail="No AI reviews found")

    # Determine review service
    service = "AI Review Service"
    for r in all_reviews:
        if r.reviewer3_tracking_id:
            service = "Reviewer3.com"
            break

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "AI Review Report", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Metadata
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, f"Paper: {paper.title}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Paper ID: {paper.id}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Review Service: {service}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Generated: {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)

    for review in all_reviews:
        # Round heading
        status_label = "Approved" if review.approved else review.status.capitalize()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, f"Round {review.review_round} - {status_label}", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        if review.paper_version:
            pdf.cell(0, 5, f"Paper version: v{review.paper_version}", new_x="LMARGIN", new_y="NEXT")
        if review.submitted_at:
            pdf.cell(0, 5, f"Submitted: {review.submitted_at.strftime('%B %d, %Y at %H:%M UTC')}", new_x="LMARGIN", new_y="NEXT")
        if review.completed_at:
            pdf.cell(0, 5, f"Completed: {review.completed_at.strftime('%B %d, %Y at %H:%M UTC')}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        if review.status != "completed":
            pdf.set_font("Helvetica", "I", 10)
            pdf.cell(0, 6, f"Review status: {review.status}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(4)
            continue

        # Revision rounds (2+): show scored evaluations
        if review.review_round > 1 and review.revision_scores:
            score_labels = {1: "Ignored", 2: "Weakly acknowledged", 3: "Well acknowledged", 4: "Fully addressed"}
            score_colors = {1: (220, 38, 38), 2: (217, 119, 6), 3: (5, 150, 105), 4: (22, 163, 74)}

            if review.desk_rejected:
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(220, 38, 38)
                pdf.cell(0, 7, "DESK REJECTED", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)

            for i, ev in enumerate(review.revision_scores, 1):
                score = ev.get("score", 0)
                label = score_labels.get(score, "Unknown")
                color = score_colors.get(score, (100, 100, 100))

                # Evaluation heading with score
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_fill_color(243, 232, 255)
                pdf.cell(0, 7, f"  Comment {i}", new_x="LMARGIN", new_y="NEXT", fill=True)

                # Score badge
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(*color)
                pdf.cell(0, 6, f"Score: {score}/4 - {label}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1)

                # Original comment
                original = ev.get("originalComment", "")
                if original:
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.cell(0, 6, "Original comment:", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 10)
                    safe_text = original.encode("latin-1", "replace").decode("latin-1")
                    pdf.multi_cell(0, 5, safe_text)
                    pdf.ln(1)

                # Author response
                author_resp = ev.get("authorResponse", "")
                if author_resp:
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.set_text_color(37, 99, 235)
                    pdf.cell(0, 6, "Author response:", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font("Helvetica", "", 10)
                    safe_text = author_resp.encode("latin-1", "replace").decode("latin-1")
                    pdf.multi_cell(0, 5, safe_text)
                    pdf.ln(1)

                # Reviewer assessment
                reviewer_resp = ev.get("reviewerResponse", "")
                if reviewer_resp:
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.set_text_color(*color)
                    pdf.cell(0, 6, "Reviewer assessment:", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font("Helvetica", "", 10)
                    safe_text = reviewer_resp.encode("latin-1", "replace").decode("latin-1")
                    pdf.multi_cell(0, 5, safe_text)
                    pdf.ln(1)

                pdf.ln(2)
        else:
            # Round 1: show original comments from review_data
            comments = []
            if review.review_data and isinstance(review.review_data, dict):
                comments = review.review_data.get("comments", [])

            if not comments:
                pdf.set_font("Helvetica", "I", 10)
                pdf.cell(0, 6, "No comments returned (auto-approved).", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(4)
            else:
                for i, c in enumerate(comments, 1):
                    reviewer_id = c.get("reviewerId", f"Reviewer {i}")
                    comment_text = c.get("comment", "")

                    # Reviewer heading
                    pdf.set_font("Helvetica", "B", 11)
                    pdf.set_fill_color(243, 232, 255)
                    pdf.cell(0, 7, f"  {reviewer_id}", new_x="LMARGIN", new_y="NEXT", fill=True)
                    pdf.ln(2)

                    # Comment text
                    pdf.set_font("Helvetica", "", 10)
                    safe_text = comment_text.encode("latin-1", "replace").decode("latin-1")
                    pdf.multi_cell(0, 5, safe_text)
                    pdf.ln(2)

        # Divider between rounds
        pdf.ln(2)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

    pdf_bytes = pdf.output()

    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="ai-review-paper-{paper_id}.pdf"',
        },
    )


@router.get("/{paper_id}/ai-review", response_class=HTMLResponse)
async def ai_review_page(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """AI review submission/status page (author only)."""
    session_user = request.session.get("user")
    if not session_user:
        return HTMLResponse('<script>window.location.href="/auth/login";</script>')

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if not _is_paper_author(paper_id, session_user["id"], db):
        raise HTTPException(status_code=403, detail="Only paper authors can access AI review")

    # Get AI reviews for this paper's current cycle, ordered by round
    all_reviews = db.query(AIReview).filter(
        AIReview.paper_id == paper_id,
        AIReview.review_cycle == paper.review_cycle,
    ).order_by(AIReview.review_round.asc()).all()

    # Latest review is the most recent one in this cycle
    latest_review = all_reviews[-1] if all_reviews else None

    # If latest review is pending, poll Reviewer3
    if latest_review and latest_review.status in ("submitted", "in_progress") and latest_review.reviewer3_tracking_id:
        try:
            r3_data = await reviewer3_service.check_status(latest_review.reviewer3_tracking_id)
            if r3_data.get("status") == "completed" and latest_review.status != "completed":
                _complete_review(latest_review, r3_data, db)
        except Exception as e:
            print(f"[Reviewer3] Error polling status: {e}")

    # Get author's email for Reviewer3 user creation
    # Try: user profile → paper submitter_email → session
    user_db = db.query(User).filter(User.id == session_user["id"]).first()
    author_email = (
        (user_db.email if user_db else None)
        or paper.submitter_email
        or session_user.get("email")
    )
    # Capture into multi-email table if found from fallback sources
    if author_email and user_db:
        add_email_if_new(
            user_id=user_db.id,
            email=author_email,
            source="submission",
            db=db,
        )
        db.commit()

    # Count reviews from previous cycles for UI indicator
    previous_cycle_count = 0
    if paper.review_cycle > 1:
        previous_cycle_count = db.query(AIReview).filter(
            AIReview.paper_id == paper_id,
            AIReview.review_cycle < paper.review_cycle,
        ).count()

    return templates.TemplateResponse(
        "ai_review.html",
        {
            "request": request,
            "paper": paper,
            "user": session_user,
            "all_reviews": all_reviews,
            "latest_review": latest_review,
            "author_email": author_email,
            "previous_cycle_count": previous_cycle_count,
        },
    )


@router.post("/{paper_id}/ai-review/submit", response_class=HTMLResponse)
async def submit_ai_review(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Submit paper to Reviewer3.com for AI review (initial submission)."""
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.review_stage != 2:
        raise HTTPException(status_code=400, detail="Paper must be at stage 2 (Endorsed) for AI review submission")

    if not _is_paper_author(paper_id, session_user["id"], db):
        raise HTTPException(status_code=403, detail="Only paper authors can submit for AI review")

    user_db = db.query(User).filter(User.id == session_user["id"]).first()
    # Try user profile, then paper submitter_email
    author_email = (user_db.email if user_db else None) or paper.submitter_email
    if not author_email:
        return HTMLResponse(
            '<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-center">'
            '<p class="text-red-800 font-medium">Email address required</p>'
            '<p class="text-sm text-red-600 mt-1">Please add an email to your '
            '<a href="/auth/profile/edit" class="underline">profile</a> before submitting for AI review.</p>'
            '</div>'
        )
    # Capture into multi-email table
    if user_db and author_email:
        add_email_if_new(
            user_id=user_db.id,
            email=author_email,
            source="submission",
            db=db,
        )

    pdf_path = _get_pdf_path(paper, db)
    if not pdf_path:
        return HTMLResponse(
            '<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-center">'
            '<p class="text-red-800 font-medium">PDF file not found</p>'
            '<p class="text-sm text-red-600 mt-1">Could not locate the paper PDF on disk.</p>'
            '</div>'
        )

    try:
        r3_user_id = await reviewer3_service.ensure_user(
            email=author_email,
            name=user_db.name or session_user.get("name", "JAIGP Author"),
        )

        pdf_filename = f"paper-{paper_id}-v{paper.current_version}.pdf"
        r3_result = await reviewer3_service.submit_paper(
            pdf_path=pdf_path,
            reviewer3_user_id=r3_user_id,
            title=paper.title,
            filename=pdf_filename,
        )

        session_id = r3_result.get("sessionId")
        if not session_id:
            raise ValueError("No sessionId returned from Reviewer3")

        ai_review = AIReview(
            paper_id=paper_id,
            reviewer3_tracking_id=session_id,
            status="submitted",
            submitted_at=datetime.utcnow(),
            review_round=1,
            paper_version=paper.current_version,
            review_data={"reviewer3_user_id": r3_user_id},
            review_cycle=paper.review_cycle,
        )
        db.add(ai_review)

        paper.reviewer3_tracking_id = session_id
        paper.reviewer3_submission_date = datetime.utcnow()
        db.commit()

        stage_transition_service.advance_to_ai_review(paper_id, session_user["id"], db)

        return HTMLResponse(
            '<div class="bg-green-50 border border-green-200 rounded-lg p-4 text-center">'
            '<p class="text-green-800 font-medium">Paper submitted for AI review!</p>'
            '<p class="text-sm text-slate-600 mt-2">Your paper is being analyzed by multiple AI reviewers. '
            'This typically takes 2-5 minutes.</p>'
            f'<a href="/paper/{paper_id}/ai-review" class="text-primary hover:underline text-sm mt-3 inline-block">'
            'Refresh to check status</a>'
            '</div>'
        )

    except Exception as e:
        print(f"[Reviewer3] Submission error: {e}")
        from html import escape as html_escape
        return HTMLResponse(
            '<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-center">'
            '<p class="text-red-800 font-medium">Submission failed</p>'
            f'<p class="text-sm text-red-600 mt-1">{html_escape(str(e))}</p>'
            '<p class="text-sm text-slate-500 mt-2">Please try again or contact support.</p>'
            '</div>'
        )


@router.get("/{paper_id}/ai-review/status")
async def ai_review_status(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """HTMX poll for AI review status."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        return HTMLResponse('<div class="bg-slate-50 border border-slate-200 rounded-lg p-4"><p class="text-slate-600">Paper not found.</p></div>')

    ai_review = db.query(AIReview).filter(
        AIReview.paper_id == paper_id,
        AIReview.review_cycle == paper.review_cycle,
    ).order_by(AIReview.created_at.desc()).first()

    if not ai_review:
        return HTMLResponse(
            '<div class="bg-slate-50 border border-slate-200 rounded-lg p-4">'
            '<p class="text-slate-600">No AI review found.</p>'
            '</div>'
        )

    if ai_review.status == "completed":
        return HTMLResponse("", headers={"HX-Refresh": "true"})

    if ai_review.reviewer3_tracking_id:
        try:
            r3_data = await reviewer3_service.check_status(ai_review.reviewer3_tracking_id)

            if r3_data.get("status") == "completed":
                _complete_review(ai_review, r3_data, db)
                return HTMLResponse("", headers={"HX-Refresh": "true"})
            else:
                return HTMLResponse(
                    '<div class="bg-amber-50 border border-amber-200 rounded-lg p-6"'
                    f' hx-get="/paper/{paper_id}/ai-review/status"'
                    ' hx-trigger="every 30s"'
                    ' hx-swap="outerHTML">'
                    '<div class="flex items-center gap-3">'
                    '<svg class="animate-spin h-6 w-6 text-amber-600 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">'
                    '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>'
                    '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>'
                    '</svg>'
                    '<div>'
                    '<p class="text-amber-800 font-medium">AI review in progress...</p>'
                    '<p class="text-sm text-amber-700 mt-1">This typically takes 2-5 minutes. '
                    'This page will automatically update when results are ready &mdash; no need to refresh.</p>'
                    '</div>'
                    '</div>'
                    '</div>'
                )
        except Exception as e:
            print(f"[Reviewer3] Status poll error: {e}")

    return HTMLResponse(
        '<div class="bg-amber-50 border border-amber-200 rounded-lg p-6"'
        f' hx-get="/paper/{paper_id}/ai-review/status"'
        ' hx-trigger="every 30s"'
        ' hx-swap="outerHTML">'
        '<div class="flex items-center gap-3">'
        '<svg class="animate-spin h-6 w-6 text-amber-600 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">'
        '<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>'
        '<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>'
        '</svg>'
        '<div>'
        '<p class="text-amber-800 font-medium">Waiting for AI review...</p>'
        '<p class="text-sm text-amber-700 mt-1">This page will automatically update when results are ready &mdash; no need to refresh.</p>'
        '</div>'
        '</div>'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Revision scoring helpers
# ---------------------------------------------------------------------------

_SCORE_LABELS = {
    1: "Ignored",
    2: "Weakly acknowledged",
    3: "Well acknowledged",
    4: "Fully addressed",
}

_SCORE_COLORS = {1: "red", 2: "amber", 3: "emerald", 4: "green"}

MAX_REVISION_ROUNDS = 4  # round 1 = initial; rounds 2-4 = revision attempts 1-3


def _err(title: str, detail: str) -> HTMLResponse:
    # Return 200 so HTMX swaps the response into the DOM (non-2xx responses are ignored)
    return HTMLResponse(
        f'<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-center">'
        f'<p class="text-red-800 font-medium">{html_escape(title)}</p>'
        f'<p class="text-sm text-red-600 mt-1">{html_escape(detail)}</p>'
        f'</div>'
    )


def _build_evaluations_html(evaluations: list) -> str:
    if not evaluations:
        return '<p class="text-sm text-slate-500 italic">No evaluations returned.</p>'
    parts = []
    for ev in evaluations:
        score = ev.get("score", 0)
        color = _SCORE_COLORS.get(score, "slate")
        label = _SCORE_LABELS.get(score, f"Score {score}")
        orig = html_escape(str(ev.get("originalComment", "")))
        a_resp = html_escape(str(ev.get("authorResponse", "")))
        r_resp = html_escape(str(ev.get("reviewerResponse", "")))
        part = (
            f'<div class="bg-white rounded-lg p-4 border border-slate-200">'
            f'<div class="flex items-start justify-between gap-3 mb-2">'
            f'<p class="text-sm text-slate-700 flex-1 whitespace-pre-line">{orig}</p>'
            f'<span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium '
            f'bg-{color}-100 text-{color}-800 whitespace-nowrap flex-shrink-0">'
            f'{score}/4 \u2014 {label}</span>'
            f'</div>'
        )
        if a_resp:
            part += (
                f'<div class="mt-2 pl-3 border-l-2 border-blue-300">'
                f'<span class="text-xs font-medium text-blue-700">Your response:</span>'
                f'<p class="text-sm text-slate-600 mt-0.5 whitespace-pre-line">{a_resp}</p>'
                f'</div>'
            )
        if r_resp:
            part += (
                f'<div class="mt-2 pl-3 border-l-2 border-{color}-300">'
                f'<span class="text-xs font-medium text-{color}-700">Reviewer assessment:</span>'
                f'<p class="text-sm text-slate-600 mt-0.5 whitespace-pre-line">{r_resp}</p>'
                f'</div>'
            )
        part += '</div>'
        parts.append(part)
    return '\n'.join(parts)


def _approved_result_html(paper_id: int, evaluations: list) -> str:
    evals = _build_evaluations_html(evaluations)
    return (
        '<div class="space-y-6">'
        '<div class="bg-green-50 border border-green-200 rounded-lg p-6">'
        '<div class="flex items-center gap-3">'
        '<svg class="h-8 w-8 text-green-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        'd="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
        '<div>'
        '<p class="text-green-800 font-bold text-lg">All comments addressed \u2014 AI review passed!</p>'
        '<p class="text-sm text-green-700 mt-1">Your paper is now eligible for Stage\u00a04: Human Peer Review. The editorial board will assign reviewers when ready.</p>'
        '</div></div></div>'
        '<h4 class="text-md font-semibold text-secondary">Evaluation Summary</h4>'
        f'<div class="space-y-3">{evals}</div>'
        f'<a href="/paper/{paper_id}" class="inline-block mt-2 px-4 py-2 bg-primary text-white '
        f'rounded-md hover:bg-blue-700 transition text-sm font-medium">View Paper</a>'
        '</div>'
    )


def _desk_reject_result_html(paper_id: int, evaluations: list) -> str:
    evals = _build_evaluations_html(evaluations)
    return (
        '<div class="space-y-6">'
        '<div class="bg-red-50 border border-red-200 rounded-lg p-6">'
        '<div class="flex items-start gap-3">'
        '<svg class="h-8 w-8 text-red-600 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        'd="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
        '<div>'
        '<p class="text-red-800 font-bold text-lg">Paper Desk Rejected</p>'
        '<p class="text-sm text-red-700 mt-1">The AI reviewers determined this revision does not adequately '
        'address the feedback. Your paper has been returned to Stage\u00a01 and must receive a new '
        'endorsement to re-enter the review pipeline.</p>'
        '</div></div></div>'
        '<h4 class="text-md font-semibold text-secondary">Evaluation Summary</h4>'
        f'<div class="space-y-3">{evals}</div>'
        f'<a href="/paper/{paper_id}" class="inline-block mt-2 px-4 py-2 bg-primary text-white '
        f'rounded-md hover:bg-blue-700 transition text-sm font-medium">View Paper</a>'
        '</div>'
    )


def _exhausted_result_html(paper_id: int, evaluations: list) -> str:
    evals = _build_evaluations_html(evaluations)
    return (
        '<div class="space-y-6">'
        '<div class="bg-red-50 border border-red-200 rounded-lg p-6">'
        '<div class="flex items-start gap-3">'
        '<svg class="h-8 w-8 text-red-600 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        'd="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>'
        '<div>'
        '<p class="text-red-800 font-bold text-lg">All 3 revision attempts used \u2014 paper returned to Stage\u00a01</p>'
        '<p class="text-sm text-red-700 mt-1">You have exhausted all revision attempts for this review cycle. '
        'Your paper must receive a new endorsement to re-enter the review pipeline with a fresh submission.</p>'
        '</div></div></div>'
        '<h4 class="text-md font-semibold text-secondary">Final Evaluation</h4>'
        f'<div class="space-y-3">{evals}</div>'
        f'<a href="/paper/{paper_id}" class="inline-block mt-2 px-4 py-2 bg-primary text-white '
        f'rounded-md hover:bg-blue-700 transition text-sm font-medium">View Paper</a>'
        '</div>'
    )


def _needs_revision_result_html(paper_id: int, evaluations: list, attempt_number: int, attempts_remaining: int) -> str:
    evals = _build_evaluations_html(evaluations)
    final_warning = ""
    if attempts_remaining == 1:
        final_warning = (
            '<div class="bg-red-50 border border-red-200 rounded-lg p-4">'
            '<p class="text-red-800 font-semibold">\u26a0\ufe0f Final revision attempt remaining</p>'
            '<p class="text-sm text-red-700 mt-1">This is your last chance. If the next revision '
            'does not pass, your paper will be returned to Stage\u00a01.</p>'
            '</div>'
        )
    remaining_text = f'{attempts_remaining} revision attempt{"s" if attempts_remaining != 1 else ""} remaining'
    return (
        '<div class="space-y-6">'
        '<div class="bg-amber-50 border border-amber-200 rounded-lg p-4">'
        f'<p class="text-amber-800 font-semibold">Revision\u00a0{attempt_number} scored \u2014 some comments need stronger addressing</p>'
        f'<p class="text-sm text-amber-700 mt-1">{remaining_text}. Scores below 3 indicate comments that were not sufficiently addressed.</p>'
        '</div>'
        f'{final_warning}'
        f'<h4 class="text-md font-semibold text-secondary">Scores for Revision\u00a0{attempt_number}</h4>'
        f'<div class="space-y-3">{evals}</div>'
        f'<a href="/paper/{paper_id}/ai-review" class="inline-block mt-2 px-4 py-2 bg-primary text-white '
        f'rounded-md hover:bg-blue-700 transition text-sm font-medium">Submit Another Revision</a>'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Resubmit endpoint (synchronous /revise flow)
# ---------------------------------------------------------------------------

@router.post("/{paper_id}/ai-review/resubmit", response_class=HTMLResponse)
async def resubmit_ai_review(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Author uploads revised manuscript + response letter PDF for synchronous AI re-scoring."""
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper or paper.review_stage != 3:
        raise HTTPException(status_code=400, detail="Paper must be at stage 3")

    if not _is_paper_author(paper_id, session_user["id"], db):
        raise HTTPException(status_code=403, detail="Only paper authors can resubmit")

    # Get the latest completed review that is NOT approved (current cycle only)
    latest_review = db.query(AIReview).filter(
        AIReview.paper_id == paper_id,
        AIReview.review_cycle == paper.review_cycle,
        AIReview.status == "completed",
        AIReview.approved == False,
    ).order_by(AIReview.created_at.desc()).first()

    if not latest_review:
        raise HTTPException(status_code=400, detail="No completed AI review awaiting response")

    new_round = latest_review.review_round + 1
    if new_round > MAX_REVISION_ROUNDS:
        return _err(
            "Maximum revision attempts reached",
            "You have used all 3 revision attempts for this review cycle.",
        )

    attempt_number = new_round - 1  # 1, 2, or 3
    is_final_attempt = (new_round == MAX_REVISION_ROUNDS)

    form = await request.form()
    updated_title = form.get("updated_title", "").strip()
    updated_abstract = form.get("updated_abstract", "").strip()
    revised_pdf: UploadFile = form.get("revised_pdf")
    author_response_pdf: UploadFile = form.get("author_response_pdf")

    if not revised_pdf or not revised_pdf.filename:
        return _err("Revised manuscript required", "Please upload your revised manuscript PDF.")
    if not revised_pdf.filename.lower().endswith(".pdf"):
        return _err("Invalid file type", "Revised manuscript must be a PDF file.")
    if not author_response_pdf or not author_response_pdf.filename:
        return _err("Author response letter required", "Please upload your author response letter as a PDF.")
    if not author_response_pdf.filename.lower().endswith(".pdf"):
        return _err("Invalid file type", "Author response letter must be a PDF file.")

    try:
        revised_pdf_content = await revised_pdf.read()
        response_pdf_content = await author_response_pdf.read()

        # Save revised manuscript as new paper version
        new_version = paper.current_version + 1
        saved_filename, saved_path = await file_storage.save_pdf(
            file_content=revised_pdf_content,
            paper_id=paper.id,
            version=new_version,
            date=paper.published_date,
            paper_title=paper.title,
            paper_abstract=paper.abstract,
        )
        paper_version = PaperVersion(
            paper_id=paper.id,
            version_number=new_version,
            pdf_filename=saved_filename,
            change_log=f"Revised after AI review (attempt {attempt_number})",
        )
        db.add(paper_version)
        paper.current_version = new_version
        if updated_title and updated_title != paper.title:
            paper.title = updated_title
        if updated_abstract and updated_abstract != paper.abstract:
            paper.abstract = updated_abstract
        paper.updated_at = datetime.utcnow()
        db.flush()

        # Save author response letter PDF
        response_filename, _ = await file_storage.save_response_pdf(
            file_content=response_pdf_content,
            paper_id=paper.id,
            version=new_version,
            date=paper.published_date,
        )

        # Extract text from response letter via PyMuPDF
        import fitz
        author_response_text = ""
        try:
            with fitz.open(stream=response_pdf_content, filetype="pdf") as doc:
                for page in doc:
                    author_response_text += page.get_text()
        except Exception as e:
            print(f"[Reviewer3] Warning: could not extract text from response PDF: {e}")
            author_response_text = "(author response text extraction failed)"

        # Call /revise synchronously against the original session ID
        r3_result = await reviewer3_service.revise_paper(
            session_id=paper.reviewer3_tracking_id,
            revised_pdf_path=str(saved_path),
            author_response_text=author_response_text,
        )

        desk_rejected = r3_result.get("deskReject", False)
        evaluations = r3_result.get("evaluations", [])
        approved = (
            not desk_rejected
            and bool(evaluations)
            and all(e.get("score", 0) >= 3 for e in evaluations)
        )

        # Record revision AIReview (status=completed immediately; no polling needed)
        new_review = AIReview(
            paper_id=paper_id,
            reviewer3_tracking_id=None,
            status="completed",
            submitted_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            review_round=new_round,
            parent_review_id=latest_review.id,
            paper_version=new_version,
            review_cycle=paper.review_cycle,
            revision_scores=evaluations,
            desk_rejected=desk_rejected,
            author_response_path=response_filename,
            approved=approved,
        )
        db.add(new_review)
        paper.draft_responses = None
        db.flush()

        # Branch on outcome; each service call commits internally
        if desk_rejected:
            stage_transition_service.desk_reject_to_stage1(
                paper_id=paper_id,
                triggered_by_user_id=session_user["id"],
                db=db,
                reason=f"Desk rejected at revision attempt {attempt_number}",
            )
            return HTMLResponse(_desk_reject_result_html(paper_id, evaluations))

        if approved:
            stage_transition_service.advance_to_human_review(
                paper_id=paper_id,
                user_id=session_user["id"],
                db=db,
            )
            return HTMLResponse(_approved_result_html(paper_id, evaluations))

        if is_final_attempt:
            stage_transition_service.desk_reject_to_stage1(
                paper_id=paper_id,
                triggered_by_user_id=session_user["id"],
                db=db,
                reason="Desk rejected after exhausting all 3 revision attempts",
            )
            return HTMLResponse(_exhausted_result_html(paper_id, evaluations))

        # Still has attempts remaining — commit and show scores
        db.commit()
        attempts_remaining = MAX_REVISION_ROUNDS - new_round
        return HTMLResponse(_needs_revision_result_html(paper_id, evaluations, attempt_number, attempts_remaining))

    except Exception as e:
        print(f"[Reviewer3] Resubmission error: {e}")
        # Return 200 so HTMX swaps the error into the DOM
        return HTMLResponse(
            '<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-center">'
            '<p class="text-red-800 font-medium">Resubmission failed</p>'
            f'<p class="text-sm text-red-600 mt-1">{html_escape(str(e))}</p>'
            '<p class="text-sm text-slate-500 mt-2">Please try again or contact support.</p>'
            '</div>'
        )
