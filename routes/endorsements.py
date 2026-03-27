"""Endorsement routes for paper endorsement system (Stage 1 -> 2)."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from models.database import get_db
from models.paper import Paper
from models.user import User
from models.endorsement import Endorsement
from models.paper import PaperHumanAuthor
from services.stage_transition import stage_transition_service
from services.email import email_service

router = APIRouter(prefix="/paper", tags=["endorsements"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


def get_current_user(request: Request, db: Session):
    """Get current authenticated user from session."""
    session_user = request.session.get("user")
    if not session_user:
        return None
    return db.query(User).filter(User.id == session_user["id"]).first()


@router.post("/{paper_id}/endorse", response_class=HTMLResponse)
async def endorse_paper(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Endorse a paper (requires auth, badge >= bronze, not an author)."""
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Check badge eligibility
    if not user.can_endorse:
        raise HTTPException(status_code=403, detail="Bronze badge or higher required to endorse")

    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Must be at stage 1
    if paper.review_stage != 1:
        raise HTTPException(status_code=400, detail="Paper is not at the submission stage")

    # Cannot endorse own paper
    is_author = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id == user.id,
    ).first()
    if is_author:
        return HTMLResponse(
            '<div id="endorsement-section" class="bg-white rounded-lg shadow-sm border border-slate-200 p-6">'
            '<h3 class="text-lg font-bold text-secondary mb-3">Endorsements</h3>'
            '<div class="bg-blue-50 border border-blue-200 rounded-lg p-4">'
            '<p class="text-sm text-blue-800 font-medium mb-2">Authors cannot endorse their own papers</p>'
            '<p class="text-xs text-blue-700 leading-relaxed">'
            'Endorsement is an independent eligibility check: another ORCID-verified scholar '
            'with a Bronze badge or higher must endorse your paper before it can proceed to AI review. '
            'Share your paper with colleagues who have an ORCID profile and ask them to endorse it here.'
            '</p></div></div>'
        )

    # Check for existing endorsement
    existing = db.query(Endorsement).filter(
        Endorsement.paper_id == paper_id,
        Endorsement.user_id == user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Already endorsed this paper")

    # Create endorsement
    endorsement = Endorsement(
        paper_id=paper_id,
        user_id=user.id,
    )
    db.add(endorsement)
    db.commit()

    # Notify paper authors
    from services.notification import create_notification
    for author in paper.human_authors:
        if author.user_id:
            create_notification(
                user_id=author.user_id, notification_type="endorsement",
                link=f"/paper/{paper_id}", db=db,
                source_user_id=user.id,
                content_preview=f"endorsed your paper \"{paper.title[:100]}\"",
            )
    db.commit()

    # Try to advance to stage 2
    advanced = stage_transition_service.advance_to_endorsed(paper_id, user.id, db)

    # Send email notification to authors
    if advanced:
        for author in paper.human_authors:
            if author.user and author.user.email:
                email_service.send_endorsement_notification(
                    to_email=author.user.email,
                    paper_title=paper.title,
                    endorser_name=user.name,
                    paper_url=f"/paper/{paper_id}",
                )

    # Refresh paper for updated template
    db.refresh(paper)

    # Return updated endorsement button component
    return templates.TemplateResponse(
        "components/endorsement_button.html",
        {
            "request": request,
            "paper": paper,
            "user": session_user,
            "user_db": user,
            "endorsements": paper.endorsements,
            "has_endorsed": True,
            "can_endorse": False,
        },
    )


@router.delete("/{paper_id}/endorse", response_class=HTMLResponse)
async def withdraw_endorsement(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Withdraw endorsement (only if paper still at stage 1)."""
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if paper.review_stage != 1:
        raise HTTPException(status_code=400, detail="Cannot withdraw endorsement after paper advanced")

    endorsement = db.query(Endorsement).filter(
        Endorsement.paper_id == paper_id,
        Endorsement.user_id == session_user["id"],
    ).first()

    if not endorsement:
        raise HTTPException(status_code=404, detail="No endorsement found")

    try:
        db.delete(endorsement)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"ERROR: Failed to withdraw endorsement {endorsement.id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to withdraw endorsement.")

    user = db.query(User).filter(User.id == session_user["id"]).first()
    db.refresh(paper)

    return templates.TemplateResponse(
        "components/endorsement_button.html",
        {
            "request": request,
            "paper": paper,
            "user": session_user,
            "user_db": user,
            "endorsements": paper.endorsements,
            "has_endorsed": False,
            "can_endorse": user.can_endorse if user else False,
        },
    )


@router.get("/{paper_id}/endorsements", response_class=HTMLResponse)
async def list_endorsements(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """List endorsements for a paper (HTMX partial)."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    session_user = request.session.get("user")

    return templates.TemplateResponse(
        "components/endorsement_button.html",
        {
            "request": request,
            "paper": paper,
            "user": session_user,
            "user_db": db.query(User).filter(User.id == session_user["id"]).first() if session_user else None,
            "endorsements": paper.endorsements,
            "has_endorsed": any(e.user_id == session_user["id"] for e in paper.endorsements) if session_user else False,
            "can_endorse": False,  # Computed in template
        },
    )
