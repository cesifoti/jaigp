"""Admin console routes."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, desc, distinct
from sqlalchemy.orm import Session
from datetime import datetime
import secrets
from models.database import get_db
from models.user import User
from models.user_email import UserEmail
from models.paper import Paper, PaperHumanAuthor, STAGE_NAMES
from models.editorial import EditorialBoardMember, EditorialDecision
from models.review import HumanReview, AIReview
from models.extension import ExtensionRequest
from services.stage_transition import stage_transition_service
from services.email import email_service
from services.file_storage import file_storage
import config

router = APIRouter()


def require_admin(request: Request, db: Session = Depends(get_db)):
    """Check if user is admin (ADMIN_ORCIDS or active editorial board member)."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    orcid_id = user.get("orcid_id")

    # Check 1: Hardcoded ADMIN_ORCIDS
    if orcid_id in config.ADMIN_ORCIDS:
        return user

    # Check 2: Active editorial board member (any role)
    user_id = user.get("id")
    if user_id:
        board_member = db.query(EditorialBoardMember).filter(
            EditorialBoardMember.user_id == user_id,
            EditorialBoardMember.is_active == True,
        ).first()
        if board_member:
            return user

    raise HTTPException(status_code=403, detail="Admin access required")


def get_admin_role(user: dict, db: Session) -> str:
    """Get the editorial role of an admin user. Returns 'super', 'editor-in-chief', 'editor', or 'associate_editor'."""
    if user.get("orcid_id") in config.ADMIN_ORCIDS:
        return "super"
    board = db.query(EditorialBoardMember).filter(
        EditorialBoardMember.user_id == user["id"],
        EditorialBoardMember.is_active == True,
    ).first()
    return board.role if board else "associate_editor"



def is_editor_check(user_id: int, db: Session) -> bool:
    """Check if user is on the editorial board."""
    return db.query(EditorialBoardMember).filter(
        EditorialBoardMember.user_id == user_id,
        EditorialBoardMember.is_active == True,
    ).first() is not None


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    page: int = 1,
    per_page: int = 25,
    sort_by: str = "papers",
    sort_order: str = "desc",
    search: str = "",
    badge_filter: str = "",
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin)
):
    """Admin dashboard with user and paper statistics."""
    from main import templates

    # Calculate offset
    offset = (page - 1) * per_page

    # Base query with paper count
    users_query = db.query(
        User,
        func.count(PaperHumanAuthor.paper_id).label('paper_count')
    ).outerjoin(
        PaperHumanAuthor, User.id == PaperHumanAuthor.user_id
    )

    # Apply search filter if provided
    if search:
        search_term = f"%{search}%"
        # Subquery: find user IDs matching email in user_emails table
        email_user_ids = db.query(UserEmail.user_id).filter(
            UserEmail.email.ilike(search_term)
        ).subquery()

        users_query = users_query.filter(
            (User.name.ilike(search_term)) |
            (User.orcid_id.ilike(search_term)) |
            (User.email.ilike(search_term)) |
            (User.affiliation.ilike(search_term)) |
            (User.id.in_(email_user_ids))
        )

    # Apply badge filter
    if badge_filter:
        if badge_filter == "none":
            users_query = users_query.filter(User.badge.is_(None))
        else:
            users_query = users_query.filter(User.badge == badge_filter)

    # Group by user
    users_query = users_query.group_by(User.id)

    # Apply sorting
    if sort_by == "name":
        sort_column = User.name
    elif sort_by == "orcid":
        sort_column = User.orcid_id
    elif sort_by == "badge":
        sort_column = User.badge
    elif sort_by == "papers":
        sort_column = func.count(PaperHumanAuthor.paper_id)
    elif sort_by == "email":
        sort_column = User.email
    elif sort_by == "joined":
        sort_column = User.created_at
    else:
        sort_column = func.count(PaperHumanAuthor.paper_id)

    # Apply sort order
    if sort_order == "asc":
        users_query = users_query.order_by(sort_column.asc())
    else:
        users_query = users_query.order_by(sort_column.desc())

    # Get total count for pagination (before limit/offset)
    total_users = users_query.count()
    total_pages = (total_users + per_page - 1) // per_page

    # Apply pagination
    users_query = users_query.limit(per_page).offset(offset)

    # Execute query
    users_data = []
    for user, paper_count in users_query:
        users_data.append({
            'user': user,
            'paper_count': paper_count
        })

    # Get overall statistics (unfiltered)
    total_users_all = db.query(func.count(User.id)).scalar()
    total_papers = db.query(func.count(Paper.id)).scalar()
    users_with_papers = db.query(func.count(func.distinct(PaperHumanAuthor.user_id))).scalar()

    # Get stage counts for quick dashboard (stages 0–5, including rejected)
    stage_counts = {}
    for s in range(0, 6):
        stage_counts[s] = db.query(func.count(Paper.id)).filter(
            Paper.status.in_(["published", "pending_screening", "ai_screen_rejected"]),
            Paper.review_stage == s,
        ).scalar()

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": admin_user,
        "users_data": users_data,
        "total_users": total_users,
        "total_users_all": total_users_all,
        "total_papers": total_papers,
        "users_with_papers": users_with_papers,
        "stage_counts": stage_counts,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "search": search,
        "badge_filter": badge_filter,
    })


@router.get("/user/{orcid_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    orcid_id: str,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin)
):
    """View detailed information about a specific user."""
    from main import templates

    # Get user
    user = db.query(User).filter(User.orcid_id == orcid_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get user's papers
    papers = db.query(Paper).join(
        PaperHumanAuthor, Paper.id == PaperHumanAuthor.paper_id
    ).filter(
        PaperHumanAuthor.user_id == user.id
    ).order_by(Paper.published_date.desc()).all()

    return templates.TemplateResponse("admin/user_detail.html", {
        "request": request,
        "user": admin_user,
        "profile_user": user,
        "papers": papers,
    })


# --- Pipeline Management ---

@router.get("/papers-pipeline", response_class=HTMLResponse)
async def papers_pipeline(
    request: Request,
    stage: int = None,
    pending: int = 0,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Dashboard: papers by stage with counts, stale papers highlighted."""
    from main import templates

    # Get stage counts (stages 0–5, including rejected at stage 0)
    stage_counts = {}
    for s in range(0, 6):
        stage_counts[s] = db.query(func.count(Paper.id)).filter(
            Paper.status.in_(["published", "pending_screening", "ai_screen_rejected"]),
            Paper.review_stage == s,
        ).scalar()

    # Get papers for selected stage (or all)
    query = db.query(Paper).filter(
        Paper.status.in_(["published", "pending_screening", "ai_screen_rejected"])
    )
    if stage is not None:
        query = query.filter(Paper.review_stage == stage)

    papers = query.order_by(Paper.review_stage, Paper.stage_entered_at.desc()).all()

    # Get stale papers
    stale_papers = stage_transition_service.check_staleness(db)
    stale_ids = {p.id for p in stale_papers}

    # Pending extension requests count
    pending_extensions = db.query(func.count(ExtensionRequest.id)).filter(
        ExtensionRequest.status == "pending"
    ).scalar()

    # Pending verification papers
    pending_verification = db.query(Paper).filter(
        Paper.status == "pending_verification"
    ).order_by(Paper.created_at.desc()).all()

    return templates.TemplateResponse("admin/pipeline.html", {
        "request": request,
        "user": admin_user,
        "papers": papers,
        "stage_counts": stage_counts,
        "stage_names": STAGE_NAMES,
        "selected_stage": stage,
        "stale_ids": stale_ids,
        "pending_extensions": pending_extensions,
        "pending_verification": pending_verification,
        "show_pending": bool(pending),
    })


# --- Editorial Board ---

@router.get("/editorial-board", response_class=HTMLResponse)
async def editorial_board(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """List/manage editorial board members."""
    from main import templates

    members = db.query(EditorialBoardMember).filter(
        EditorialBoardMember.is_active == True
    ).all()

    caller_role = get_admin_role(admin_user, db)

    return templates.TemplateResponse("admin/editorial_board.html", {
        "request": request,
        "user": admin_user,
        "members": members,
        "caller_role": caller_role,
    })


@router.post("/editorial-board/add")
async def add_editorial_member(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
    orcid_id: str = Form(...),
    role: str = Form("editor"),
    specialty: str = Form(""),
):
    """Add editorial board member by ORCID. Permission hierarchy:
    - Super admin / Editor-in-chief: can appoint editors and associate editors
    - Editor: can appoint associate editors only
    - Associate editor: cannot appoint anyone
    """
    caller_role = get_admin_role(admin_user, db)

    if role not in ("editor-in-chief", "editor", "associate_editor"):
        raise HTTPException(status_code=400, detail="Invalid role")

    # Permission checks
    if caller_role == "associate_editor":
        raise HTTPException(status_code=403, detail="Associate editors cannot appoint board members")
    if caller_role == "editor" and role != "associate_editor":
        raise HTTPException(status_code=403, detail="Editors can only appoint associate editors")
    if caller_role not in ("super",) and role == "editor-in-chief":
        raise HTTPException(status_code=403, detail="Only the site administrator can appoint editors-in-chief")

    user = db.query(User).filter(User.orcid_id == orcid_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found with that ORCID")

    # Check if already a member
    existing = db.query(EditorialBoardMember).filter(
        EditorialBoardMember.user_id == user.id,
    ).first()

    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.role = role
            existing.specialty = specialty
            existing.removed_at = None
            db.commit()
        else:
            raise HTTPException(status_code=400, detail="User is already an editorial board member")
    else:
        member = EditorialBoardMember(
            user_id=user.id,
            role=role,
            specialty=specialty,
        )
        db.add(member)
        db.commit()

    return RedirectResponse(url="/admin/editorial-board", status_code=303)


@router.post("/editorial-board/{member_id}/remove")
async def remove_editorial_member(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Remove editorial board member. Permission hierarchy applies."""
    member = db.query(EditorialBoardMember).filter(
        EditorialBoardMember.id == member_id,
    ).first()

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Permission check: can only remove members at or below your level
    caller_role = get_admin_role(admin_user, db)
    role_rank = {"super": 4, "editor-in-chief": 3, "editor": 2, "associate_editor": 1}
    caller_rank = role_rank.get(caller_role, 0)
    member_rank = role_rank.get(member.role, 0)

    if caller_rank <= member_rank and caller_role != "super":
        raise HTTPException(status_code=403, detail="You cannot remove a board member of equal or higher rank")

    member.is_active = False
    member.removed_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url="/admin/editorial-board", status_code=303)


# --- Paper Review Management ---

@router.get("/paper/{paper_id}/review", response_class=HTMLResponse)
async def admin_paper_review(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Per-paper review management: assign reviewers, view all reviews."""
    from main import templates

    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    ai_reviews = db.query(AIReview).filter(
        AIReview.paper_id == paper_id
    ).order_by(AIReview.review_cycle.asc(), AIReview.review_round.asc()).all()
    human_reviews = db.query(HumanReview).filter(HumanReview.paper_id == paper_id).all()
    decisions = db.query(EditorialDecision).filter(EditorialDecision.paper_id == paper_id).all()

    return templates.TemplateResponse("admin/paper_review.html", {
        "request": request,
        "user": admin_user,
        "paper": paper,
        "ai_reviews": ai_reviews,
        "human_reviews": human_reviews,
        "decisions": decisions,
        "stage_names": STAGE_NAMES,
        "current_cycle": paper.review_cycle,
    })


@router.post("/paper/{paper_id}/update-metadata", response_class=HTMLResponse)
async def update_paper_metadata(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
    title: str = Form(...),
    abstract: str = Form(...),
):
    """Admin update paper title and abstract."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    paper.title = title.strip()
    paper.abstract = abstract.strip()
    paper.updated_at = datetime.utcnow()
    db.commit()
    return HTMLResponse(
        '<div id="metadata-status" class="mt-3 px-4 py-2 bg-green-50 border border-green-200 rounded-md text-sm text-green-800">'
        'Metadata updated successfully.</div>'
    )


@router.post("/paper/{paper_id}/assign-reviewer")
async def assign_reviewer(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
    reviewer_name: str = Form(...),
    reviewer_email: str = Form(...),
    reviewer_affiliation: str = Form(""),
    reviewer_type: str = Form("author_suggested"),
):
    """Assign a human reviewer and send invitation email."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Generate invitation token
    token = secrets.token_urlsafe(32)

    review = HumanReview(
        paper_id=paper_id,
        reviewer_type=reviewer_type,
        reviewer_name=reviewer_name,
        reviewer_email=reviewer_email,
        reviewer_affiliation=reviewer_affiliation,
        invitation_token=token,
        invited_at=datetime.utcnow(),
        assigned_by_user_id=admin_user["id"],
        assigned_at=datetime.utcnow(),
    )
    db.add(review)
    db.commit()

    # Send invitation email
    invitation_url = f"{config.BASE_URL}/review/{token}"
    email_service.send_review_invitation(
        to_email=reviewer_email,
        reviewer_name=reviewer_name,
        paper_title=paper.title,
        invitation_url=invitation_url,
        reviewer_type=reviewer_type,
    )

    return RedirectResponse(url=f"/admin/paper/{paper_id}/review", status_code=303)


@router.post("/paper/{paper_id}/editorial-decision")
async def make_editorial_decision(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
    decision: str = Form(...),
    reasoning: str = Form(""),
):
    """Record editorial decision (if accept, advance to stage 5)."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    if decision not in ("accept", "reject", "revisions_needed"):
        raise HTTPException(status_code=400, detail="Invalid decision")

    ed_decision = EditorialDecision(
        paper_id=paper_id,
        editor_user_id=admin_user["id"],
        decision=decision,
        reasoning=reasoning,
    )
    db.add(ed_decision)
    db.commit()

    # If accept, advance to stage 5
    if decision == "accept":
        stage_transition_service.advance_to_accepted(paper_id, admin_user["id"], db)

    # Notify paper authors
    for author in paper.human_authors:
        if author.user and author.user.email:
            email_service.send_editorial_decision(
                to_email=author.user.email,
                paper_title=paper.title,
                decision=decision,
                reasoning=reasoning,
            )

    return RedirectResponse(url=f"/admin/paper/{paper_id}/review", status_code=303)


@router.post("/paper/{paper_id}/force-advance")
async def force_advance_paper(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
    to_stage: int = Form(...),
    notes: str = Form(""),
):
    """Admin force-advance a paper to a higher stage."""
    success = stage_transition_service.force_advance(
        paper_id=paper_id,
        to_stage=to_stage,
        admin_user_id=admin_user["id"],
        db=db,
        notes=notes,
    )

    if not success:
        raise HTTPException(status_code=400, detail="Cannot advance to that stage")

    return RedirectResponse(url=f"/admin/paper/{paper_id}/review", status_code=303)


@router.post("/paper/{paper_id}/rewind")
async def rewind_paper(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
    to_stage: int = Form(...),
    notes: str = Form(""),
):
    """Admin rewind a paper to a lower stage."""
    success = stage_transition_service.rewind(
        paper_id=paper_id,
        to_stage=to_stage,
        admin_user_id=admin_user["id"],
        db=db,
        notes=notes,
    )

    if not success:
        raise HTTPException(status_code=400, detail="Cannot rewind to that stage")

    return RedirectResponse(url=f"/admin/paper/{paper_id}/review", status_code=303)


# --- Extension Requests ---

@router.get("/extension-requests", response_class=HTMLResponse)
async def extension_requests(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """List pending extension requests."""
    from main import templates

    pending = db.query(ExtensionRequest).filter(
        ExtensionRequest.status == "pending"
    ).order_by(ExtensionRequest.created_at).all()

    processed = db.query(ExtensionRequest).filter(
        ExtensionRequest.status != "pending"
    ).order_by(ExtensionRequest.reviewed_at.desc()).limit(20).all()

    return templates.TemplateResponse("admin/extension_requests.html", {
        "request": request,
        "user": admin_user,
        "pending": pending,
        "processed": processed,
    })


@router.post("/extension/{extension_id}/approve")
async def approve_extension(
    extension_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Approve an extension request."""
    success = stage_transition_service.approve_extension(
        extension_id=extension_id,
        reviewer_user_id=admin_user["id"],
        db=db,
    )

    if not success:
        raise HTTPException(status_code=400, detail="Extension request not found or already processed")

    # Notify author
    ext = db.query(ExtensionRequest).filter(ExtensionRequest.id == extension_id).first()
    if ext:
        paper = db.query(Paper).filter(Paper.id == ext.paper_id).first()
        if paper:
            for author in paper.human_authors:
                if author.user and author.user.email:
                    email_service.send_extension_decision(
                        to_email=author.user.email,
                        paper_title=paper.title,
                        approved=True,
                        paper_url=f"/paper/{paper.id}",
                    )

    return RedirectResponse(url="/admin/extension-requests", status_code=303)


@router.post("/extension/{extension_id}/deny")
async def deny_extension(
    extension_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Deny an extension request."""
    success = stage_transition_service.deny_extension(
        extension_id=extension_id,
        reviewer_user_id=admin_user["id"],
        db=db,
    )

    if not success:
        raise HTTPException(status_code=400, detail="Extension request not found or already processed")

    # Notify author
    ext = db.query(ExtensionRequest).filter(ExtensionRequest.id == extension_id).first()
    if ext:
        paper = db.query(Paper).filter(Paper.id == ext.paper_id).first()
        if paper:
            for author in paper.human_authors:
                if author.user and author.user.email:
                    email_service.send_extension_decision(
                        to_email=author.user.email,
                        paper_title=paper.title,
                        approved=False,
                        paper_url=f"/paper/{paper.id}",
                    )

    return RedirectResponse(url="/admin/extension-requests", status_code=303)


# --- Pending Verification Management ---

@router.post("/paper/{paper_id}/nudge", response_class=HTMLResponse)
async def nudge_verification(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Resend verification reminder email for a pending_verification paper."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.status != "pending_verification":
        raise HTTPException(status_code=400, detail="Paper is not pending verification")

    if not paper.submitter_email:
        return HTMLResponse(
            '<span class="text-xs text-red-600 font-medium">No submitter email on file</span>'
        )

    # Regenerate token if missing
    if not paper.verification_token:
        paper.verification_token = secrets.token_urlsafe(32)
        db.commit()

    verification_url = f"{config.BASE_URL}/submit/verify/{paper.verification_token}"
    email_service.send_nudge_verification(
        to_email=paper.submitter_email,
        paper_title=paper.title,
        verification_url=verification_url,
    )

    return HTMLResponse(
        '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium '
        'bg-green-100 text-green-800">Reminder sent</span>'
    )


@router.post("/paper/{paper_id}/admin-delete", response_class=HTMLResponse)
async def admin_delete_paper(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Admin delete a paper (primarily for unverified papers)."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Delete associated files
    for version in paper.versions:
        try:
            file_path = file_storage.get_file_path(version.pdf_filename, paper.published_date)
            file_storage.delete_file(file_path)
        except Exception:
            pass  # File may already be gone

    if paper.image_filename:
        try:
            image_path = file_storage.get_file_path(paper.image_filename, paper.published_date)
            file_storage.delete_file(image_path)
        except Exception:
            pass

    try:
        db.delete(paper)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"ERROR: Admin failed to delete paper {paper_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete paper.")

    return HTMLResponse(
        '<tr><td colspan="6" class="px-6 py-3 text-center text-sm text-red-600">Paper deleted.</td></tr>'
    )


# --- Bulk Email ---

@router.get("/email", response_class=HTMLResponse)
async def admin_email_page(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Page for composing and sending bulk emails to authors."""
    from main import templates

    # Count recipients per stage for the UI
    stage_counts = {}
    for s in range(0, 6):
        stage_counts[s] = db.query(func.count(distinct(User.id))).join(
            PaperHumanAuthor, User.id == PaperHumanAuthor.user_id
        ).join(
            Paper, Paper.id == PaperHumanAuthor.paper_id
        ).filter(
            Paper.status.in_(["published", "pending_screening", "ai_screen_rejected"]),
            Paper.review_stage == s,
            User.email.isnot(None),
        ).scalar()

    total_with_email = db.query(func.count(User.id)).filter(
        User.email.isnot(None),
        User.email != "",
    ).scalar()

    return templates.TemplateResponse("admin/email.html", {
        "request": request,
        "user": admin_user,
        "stage_counts": stage_counts,
        "stage_names": STAGE_NAMES,
        "total_with_email": total_with_email,
        "from_email": config.SMTP_FROM_EMAIL,
    })


@router.post("/email/send", response_class=HTMLResponse)
async def admin_send_email(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
    subject: str = Form(...),
    body: str = Form(...),
    audience: str = Form("all"),
):
    """Send bulk email to selected audience."""
    from html import escape as html_escape

    # Build recipient list
    if audience == "all":
        recipients = db.query(User.email).filter(
            User.email.isnot(None),
            User.email != "",
        ).distinct().all()
    else:
        # audience is a stage number like "stage_0", "stage_1", etc.
        try:
            stage_num = int(audience.replace("stage_", ""))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid audience")

        recipients = db.query(distinct(User.email)).join(
            PaperHumanAuthor, User.id == PaperHumanAuthor.user_id
        ).join(
            Paper, Paper.id == PaperHumanAuthor.paper_id
        ).filter(
            Paper.status.in_(["published", "pending_screening", "ai_screen_rejected"]),
            Paper.review_stage == stage_num,
            User.email.isnot(None),
            User.email != "",
        ).all()

    emails = list(set(r[0] for r in recipients if r[0]))

    if not emails:
        return HTMLResponse(
            '<div class="mt-4 px-4 py-3 bg-amber-50 border border-amber-200 rounded-md text-sm text-amber-800">'
            'No recipients found for the selected audience.</div>'
        )

    # Send emails
    sent = 0
    failed = 0
    body_stripped = body.strip()
    body_escaped = html_escape(body_stripped).replace("\n", "<br>")

    for email_addr in emails:
        text_content = f"""{body_stripped}

--
JAIGP - Journal for AI Generated Papers
https://jaigp.org
To manage your notifications, visit your profile at https://jaigp.org/auth/profile"""

        html_body = f"""
            <div style="white-space: pre-line;">{body_escaped}</div>
            <hr style="border:none;border-top:1px solid #e2e8f0;margin:30px 0 15px 0;">
            <p style="font-size:12px;color:#94a3b8;">
                To manage your notifications, visit your
                <a href="https://jaigp.org/auth/profile" style="color:#2563eb;">profile</a>.
            </p>"""

        html_content = email_service._email_wrapper(html_body, text_content)
        if email_service._send_email(email_addr, subject, text_content, html_content):
            sent += 1
        else:
            failed += 1

    result_class = "bg-green-50 border-green-200 text-green-800" if failed == 0 else "bg-amber-50 border-amber-200 text-amber-800"
    return HTMLResponse(
        f'<div id="send-result" class="mt-4 px-4 py-3 {result_class} border rounded-md text-sm">'
        f'Email sent to {sent} recipient{"s" if sent != 1 else ""}.'
        f'{f" {failed} failed." if failed else ""}'
        f'</div>'
    )


# --- Site Activity ---

@router.get("/site-activity", response_class=HTMLResponse)
async def admin_site_activity(
    request: Request,
    filter: str = Query("all", regex="^(all|paper_comments|posts|post_replies|stage_changes|new_users)$"),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin),
):
    """Site-wide activity feed for editors."""
    from main import templates
    from models.comment import Comment
    from models.prompt import CommunityPrompt, PromptComment
    from models.stage_history import StageHistory

    per_page = 40
    events = []

    # Paper comments
    if filter in ("all", "paper_comments"):
        paper_comments = (
            db.query(Comment)
            .order_by(Comment.created_at.desc())
            .limit(200)
            .all()
        )
        for c in paper_comments:
            events.append({
                "type": "paper_comment",
                "time": c.created_at,
                "user": c.user,
                "paper": c.paper,
                "content": c.content,
                "link": f"/paper/{c.paper_id}#comment-{c.id}",
            })

    # Community posts
    if filter in ("all", "posts"):
        posts = (
            db.query(CommunityPrompt)
            .order_by(CommunityPrompt.created_at.desc())
            .limit(200)
            .all()
        )
        for p in posts:
            events.append({
                "type": "post",
                "time": p.created_at,
                "user": p.user,
                "post_type": p.post_type,
                "content": p.prompt_text,
                "votes": p.net_votes,
                "comment_count": p.comment_count,
                "link": f"/prompts/{p.id}",
            })

    # Community post replies
    if filter in ("all", "post_replies"):
        replies = (
            db.query(PromptComment)
            .order_by(PromptComment.created_at.desc())
            .limit(200)
            .all()
        )
        for r in replies:
            events.append({
                "type": "post_reply",
                "time": r.created_at,
                "user": r.user,
                "content": r.content,
                "prompt_id": r.prompt_id,
                "link": f"/prompts/{r.prompt_id}#pcomment-{r.id}",
            })

    # Stage changes
    if filter in ("all", "stage_changes"):
        transitions = (
            db.query(StageHistory)
            .order_by(StageHistory.created_at.desc())
            .limit(200)
            .all()
        )
        for t in transitions:
            events.append({
                "type": "stage_change",
                "time": t.created_at,
                "user": t.triggered_by,
                "paper": t.paper,
                "from_stage": t.from_stage,
                "to_stage": t.to_stage,
                "trigger_type": t.trigger_type,
                "notes": t.notes,
                "link": f"/admin/paper/{t.paper_id}/review",
            })

    # New users
    if filter in ("all", "new_users"):
        users = (
            db.query(User)
            .order_by(User.created_at.desc())
            .limit(200)
            .all()
        )
        for u in users:
            events.append({
                "type": "new_user",
                "time": u.created_at,
                "user": u,
                "link": f"/admin/user/{u.orcid_id}",
            })

    # Sort all by time descending
    events.sort(key=lambda e: e["time"], reverse=True)

    # Paginate
    total = len(events)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    events_page = events[(page - 1) * per_page : page * per_page]

    # Counts per type for filter badges
    type_counts = {}
    if filter == "all":
        for e in events:
            type_counts[e["type"]] = type_counts.get(e["type"], 0) + 1

    return templates.TemplateResponse(
        "admin/site_activity.html",
        {
            "request": request,
            "user": admin_user,
            "events": events_page,
            "filter": filter,
            "page": page,
            "total_pages": total_pages,
            "total_events": total,
            "type_counts": type_counts,
            "stage_names": STAGE_NAMES,
        },
    )
