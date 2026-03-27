"""Authentication routes for ORCID OAuth."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from models.database import get_db
from models.user import User
from services.orcid import orcid_service
from services.user_email import add_email_if_new
from models.user_email import UserEmail
import config
import json
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

@router.get("/login")
async def login(request: Request):
    """Initiate ORCID OAuth flow."""
    # Generate state for CSRF protection
    state = orcid_service.generate_state()

    # Store state in session
    request.session["oauth_state"] = state

    # Get authorization URL
    auth_url = orcid_service.get_authorization_url(state)

    return RedirectResponse(url=auth_url)

@router.get("/callback")
async def callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    db: Session = Depends(get_db)
):
    """Handle ORCID OAuth callback."""
    # Check for errors
    if error:
        return RedirectResponse(url="/?error=oauth_failed")

    # Validate required parameters
    if not code or not state:
        return RedirectResponse(url="/?error=missing_params")

    # Verify state (CSRF protection)
    session_state = request.session.get("oauth_state")
    if not session_state or session_state != state:
        return RedirectResponse(url="/?error=invalid_state")

    # Clear state from session
    request.session.pop("oauth_state", None)

    # Exchange code for token
    token_data = await orcid_service.exchange_code_for_token(code)
    if not token_data:
        return RedirectResponse(url="/?error=token_exchange_failed")

    # Extract ORCID ID and access token
    orcid_id = token_data.get("orcid")
    access_token = token_data.get("access_token")

    if not orcid_id:
        return RedirectResponse(url="/?error=no_orcid_id")

    # Fetch user information from ORCID
    user_info = await orcid_service.get_user_info(orcid_id, access_token)
    if not user_info:
        # Use minimal info if fetch fails
        user_info = {
            "orcid_id": orcid_id,
            "name": orcid_id,
            "email": None,
            "affiliation": None
        }

    # Find or create user in database
    user = db.query(User).filter(User.orcid_id == orcid_id).first()

    if user:
        # Update existing user
        user.name = user_info["name"]
        user.affiliation = user_info.get("affiliation")
    else:
        # Create new user
        user = User(
            orcid_id=orcid_id,
            name=user_info["name"],
            email=user_info.get("email"),
            affiliation=user_info.get("affiliation")
        )
        db.add(user)
        db.flush()  # Get user.id for email capture

    # Capture all ORCID emails into user_emails table
    for orcid_email in user_info.get("emails_list", []):
        add_email_if_new(
            user_id=user.id,
            email=orcid_email["email"],
            source="orcid",
            db=db,
            verified=orcid_email.get("verified", False),
        )
    # Also capture the single best email if emails_list was empty but email exists
    if not user_info.get("emails_list") and user_info.get("email"):
        add_email_if_new(
            user_id=user.id,
            email=user_info["email"],
            source="orcid",
            db=db,
        )

    # Fetch and update badge data (only if not updated recently or first login)
    should_update_badge = (
        not user.badge_updated_at or
        (datetime.utcnow() - user.badge_updated_at).days > 7  # Update weekly
    )

    if should_update_badge:
        try:
            badge_data = await orcid_service.update_user_badge(orcid_id)
            user.works_count = badge_data["works_count"]
            user.badge = badge_data["badge"]
            user.orcid_works = badge_data["journal_articles"]
            user.badge_updated_at = datetime.utcnow()
        except Exception as e:
            print(f"Error updating badge: {e}")
            # Continue even if badge update fails

    db.commit()
    db.refresh(user)

    # Store user in session
    request.session["user"] = {
        "id": user.id,
        "orcid_id": user.orcid_id,
        "name": user.name,
        "email": user.email
    }

    # If user hasn't accepted terms, redirect to acceptance page
    if not user.terms_accepted_at:
        # Store pending redirect in session
        review_token = request.session.get("review_token")
        if review_token:
            request.session["pending_redirect"] = f"/review/{review_token}/form"
        return RedirectResponse(url="/auth/accept-terms", status_code=303)

    # Check if there's a pending review to redirect to
    review_token = request.session.pop("review_token", None)
    if review_token:
        return RedirectResponse(url=f"/review/{review_token}/form", status_code=303)

    # Redirect to homepage
    return RedirectResponse(url="/", status_code=303)

@router.get("/accept-terms", response_class=HTMLResponse)
async def accept_terms_page(request: Request):
    """Show terms acceptance page for new users."""
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url="/auth/login")
    return templates.TemplateResponse("accept_terms.html", {"request": request, "user": user})


@router.post("/accept-terms")
async def accept_terms(request: Request, db: Session = Depends(get_db)):
    """Record terms acceptance and redirect."""
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    user = db.query(User).filter(User.id == session_user["id"]).first()
    if user:
        user.terms_accepted_at = datetime.utcnow()
        db.commit()

    # Check for pending redirect
    pending = request.session.pop("pending_redirect", None)
    if pending:
        return RedirectResponse(url=pending, status_code=303)

    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Logout user and clear session."""
    request.session.clear()
    return RedirectResponse(url="/")

@router.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, user_id: int = None, db: Session = Depends(get_db)):
    """User profile page - shows own profile or another user's public profile."""
    session_user = request.session.get("user")

    # If user_id is provided, show that user's profile (public view)
    if user_id:
        profile_user = db.query(User).filter(User.id == user_id).first()
        if not profile_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get user's papers
        from models.paper import Paper, PaperHumanAuthor
        from models.endorsement import Endorsement
        user_papers = db.query(Paper).join(
            PaperHumanAuthor
        ).filter(
            PaperHumanAuthor.user_id == user_id,
            Paper.status.in_(["submitted", "under-review", "published", "ai_screen_rejected"])
        ).order_by(
            Paper.published_date.desc()
        ).all()

        # Papers this user has endorsed, newest endorsement first
        endorsed_papers = db.query(Paper).join(
            Endorsement, Endorsement.paper_id == Paper.id
        ).filter(
            Endorsement.user_id == user_id
        ).order_by(Endorsement.created_at.desc()).all()

        # Follow data
        from models.discussion import UserFollow
        follower_count = db.query(UserFollow).filter(UserFollow.followed_id == user_id).count()
        following_count = db.query(UserFollow).filter(UserFollow.follower_id == user_id).count()
        is_following = False
        if session_user and session_user["id"] != user_id:
            is_following = db.query(UserFollow).filter(
                UserFollow.follower_id == session_user["id"],
                UserFollow.followed_id == user_id,
            ).first() is not None

        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "user": session_user,
                "profile_user": profile_user,
                "papers": user_papers,
                "endorsed_papers": endorsed_papers,
                "is_own_profile": session_user and session_user["id"] == user_id,
                "follower_count": follower_count,
                "following_count": following_count,
                "is_following": is_following,
            }
        )

    # No user_id provided - show logged-in user's own profile
    if not session_user:
        return RedirectResponse(url="/auth/login")

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        # User not found, clear session
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    # Get user's papers (including drafts for own profile)
    from models.paper import Paper, PaperHumanAuthor
    from models.review import AIReview
    user_papers = db.query(Paper).join(
        PaperHumanAuthor
    ).filter(
        PaperHumanAuthor.user_id == user.id
    ).order_by(
        Paper.published_date.desc()
    ).all()

    # Build map of paper_id -> latest AI review for action indicators (current cycle only)
    paper_ids = [p.id for p in user_papers]
    paper_cycle_map = {p.id: p.review_cycle for p in user_papers}
    paper_reviews = {}
    if paper_ids:
        from sqlalchemy import func
        # Subquery for max review_round per paper per cycle
        latest_round = db.query(
            AIReview.paper_id,
            AIReview.review_cycle,
            func.max(AIReview.review_round).label("max_round"),
        ).filter(
            AIReview.paper_id.in_(paper_ids)
        ).group_by(AIReview.paper_id, AIReview.review_cycle).subquery()

        reviews = db.query(AIReview).join(
            latest_round,
            (AIReview.paper_id == latest_round.c.paper_id) &
            (AIReview.review_cycle == latest_round.c.review_cycle) &
            (AIReview.review_round == latest_round.c.max_round),
        ).all()
        for r in reviews:
            # Only keep reviews from the paper's current cycle
            if r.review_cycle == paper_cycle_map.get(r.paper_id, 1):
                paper_reviews[r.paper_id] = r

    # Papers this user has endorsed, newest endorsement first
    from models.endorsement import Endorsement
    endorsed_papers = db.query(Paper).join(
        Endorsement, Endorsement.paper_id == Paper.id
    ).filter(
        Endorsement.user_id == user.id
    ).order_by(Endorsement.created_at.desc()).all()

    # Follow data for own profile
    from models.discussion import UserFollow
    follower_count = db.query(UserFollow).filter(UserFollow.followed_id == user.id).count()
    following_count = db.query(UserFollow).filter(UserFollow.follower_id == user.id).count()

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": session_user,
            "profile_user": user,
            "papers": user_papers,
            "endorsed_papers": endorsed_papers,
            "is_own_profile": True,
            "paper_reviews": paper_reviews,
            "follower_count": follower_count,
            "following_count": following_count,
            "is_following": False,
        }
    )

@router.get("/profile/edit", response_class=HTMLResponse)
async def edit_profile_form(request: Request, db: Session = Depends(get_db)):
    """Show profile edit form."""
    # Check if user is logged in
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    # Get all emails for this user
    user_emails = db.query(UserEmail).filter(
        UserEmail.user_id == user.id
    ).order_by(UserEmail.is_primary.desc(), UserEmail.created_at).all()

    return templates.TemplateResponse(
        "profile_edit.html",
        {
            "request": request,
            "user": session_user,
            "profile_user": user,
            "user_emails": user_emails,
        }
    )

@router.post("/profile/edit")
async def edit_profile_submit(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    email: str = Form(None),
    affiliation: str = Form(None),
    google_scholar_url: str = Form(None),
    rankless_url: str = Form(None),
    open_to_messaging: str = Form(None),
):
    """Handle profile edit form submission."""
    # Check if user is logged in
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    # Update user information
    user.name = name.strip() if name else user.name
    # Add new email via multi-email service instead of overwriting
    if email and email.strip():
        added = add_email_if_new(
            user_id=user.id,
            email=email.strip(),
            source="profile_edit",
            db=db,
        )
        # If this is the user's first email, it becomes primary automatically
    # Don't clear user.email when blank — keep existing primary
    user.affiliation = affiliation.strip() if affiliation else None
    user.google_scholar_url = google_scholar_url.strip() if google_scholar_url else None
    user.rankless_url = rankless_url.strip() if rankless_url else None
    user.open_to_messaging = bool(open_to_messaging)

    db.commit()
    db.refresh(user)

    # Update session
    request.session["user"] = {
        "id": user.id,
        "orcid_id": user.orcid_id,
        "name": user.name,
        "email": user.email
    }

    return RedirectResponse(url="/auth/profile", status_code=303)

@router.post("/profile/email/add")
async def add_email(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
):
    """Add a new email address to user's profile."""
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    if email and email.strip():
        result = add_email_if_new(
            user_id=user.id,
            email=email.strip(),
            source="profile_edit",
            db=db,
        )
        db.commit()

    return RedirectResponse(url="/auth/profile/edit", status_code=303)


@router.post("/profile/email/set-primary")
async def set_primary(
    request: Request,
    db: Session = Depends(get_db),
    email_id: int = Form(...),
):
    """Set an email as primary."""
    from services.user_email import set_primary_email

    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    set_primary_email(session_user["id"], email_id, db)
    db.commit()

    # Refresh session email cache
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if user:
        request.session["user"] = {
            "id": user.id,
            "orcid_id": user.orcid_id,
            "name": user.name,
            "email": user.email,
        }

    return RedirectResponse(url="/auth/profile/edit", status_code=303)


@router.post("/profile/email/remove")
async def remove_email_route(
    request: Request,
    db: Session = Depends(get_db),
    email_id: int = Form(...),
):
    """Remove a non-primary email."""
    from services.user_email import remove_email

    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    remove_email(session_user["id"], email_id, db)
    db.commit()

    return RedirectResponse(url="/auth/profile/edit", status_code=303)


@router.get("/profile/export")
async def export_user_data(request: Request, db: Session = Depends(get_db)):
    """GDPR Data Portability: Export user data as JSON."""
    # Check if user is logged in
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    # Get user's papers
    from models.paper import Paper, PaperHumanAuthor, PaperVersion
    from models.comment import Comment
    
    user_papers = db.query(Paper).join(
        PaperHumanAuthor
    ).filter(
        PaperHumanAuthor.user_id == user.id
    ).all()

    user_comments = db.query(Comment).filter(
        Comment.user_id == user.id
    ).all()

    # Get all emails for export
    all_emails = db.query(UserEmail).filter(
        UserEmail.user_id == user.id
    ).all()

    # Compile user data
    export_data = {
        "export_date": datetime.utcnow().isoformat(),
        "user_profile": {
            "orcid_id": user.orcid_id,
            "name": user.name,
            "email": user.email,
            "emails": [
                {
                    "email": ue.email,
                    "is_primary": ue.is_primary,
                    "source": ue.source,
                    "verified_at": ue.verified_at.isoformat() if ue.verified_at else None,
                    "created_at": ue.created_at.isoformat() if ue.created_at else None,
                }
                for ue in all_emails
            ],
            "affiliation": user.affiliation,
            "google_scholar_url": user.google_scholar_url,
            "rankless_url": user.rankless_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None
        },
        "papers": [
            {
                "id": paper.id,
                "title": paper.title,
                "abstract": paper.abstract,
                "current_version": paper.current_version,
                "published_date": paper.published_date.isoformat() if paper.published_date else None,
                "status": paper.status
            }
            for paper in user_papers
        ],
        "comments": [
            {
                "id": comment.id,
                "paper_id": comment.paper_id,
                "content": comment.content,
                "created_at": comment.created_at.isoformat() if comment.created_at else None
            }
            for comment in user_comments
        ]
    }

    # Return as JSON download
    return JSONResponse(
        content=export_data,
        headers={
            "Content-Disposition": f"attachment; filename=jaigp_data_export_{user.orcid_id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
        }
    )

@router.get("/profile/delete", response_class=HTMLResponse)
async def delete_account_confirmation(request: Request, db: Session = Depends(get_db)):
    """Show account deletion confirmation page."""
    # Check if user is logged in
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    # Get count of user's papers
    from models.paper import PaperHumanAuthor
    paper_count = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.user_id == user.id
    ).count()

    return templates.TemplateResponse(
        "delete_account.html",
        {
            "request": request,
            "user": session_user,
            "profile_user": user,
            "paper_count": paper_count
        }
    )

@router.post("/profile/delete")
async def delete_account_confirm(
    request: Request,
    db: Session = Depends(get_db),
    confirmation: str = Form(""),
):
    """GDPR Right to Erasure: Permanently delete user account and ALL data."""
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    if confirmation != "DELETE":
        raise HTTPException(status_code=400, detail="You must type DELETE to confirm")

    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    uid = user.id

    try:
        from models.paper import Paper, PaperHumanAuthor, PaperVersion
        from models.comment import Comment, CommentVote
        from models.endorsement import Endorsement
        from models.editorial import EditorialBoardMember, EditorialDecision
        from models.review import HumanReview
        from models.stage_history import StageHistory
        from models.extension import ExtensionRequest
        from models.submission_screening import SubmissionScreening
        from models.message import DirectMessage
        import shutil

        # === 1. Delete papers where user is the SOLE author ===
        author_links = db.query(PaperHumanAuthor).filter(PaperHumanAuthor.user_id == uid).all()
        for link in author_links:
            # Count authors on this paper
            author_count = db.query(PaperHumanAuthor).filter(
                PaperHumanAuthor.paper_id == link.paper_id
            ).count()
            if author_count == 1:
                # Sole author — delete the entire paper + files
                paper = db.query(Paper).filter(Paper.id == link.paper_id).first()
                if paper:
                    # Delete PDF files from disk
                    try:
                        from services.file_storage import file_storage
                        if paper.published_date:
                            paper_dir = file_storage.get_date_path(paper.published_date)
                            for v in paper.versions:
                                pdf_path = paper_dir / v.pdf_filename
                                if pdf_path.exists():
                                    pdf_path.unlink()
                            # Delete images
                            if paper.image_filename:
                                img_path = paper_dir / paper.image_filename
                                if img_path.exists():
                                    img_path.unlink()
                    except Exception as e:
                        print(f"[delete-account] File cleanup error for paper {paper.id}: {e}")
                    db.delete(paper)  # CASCADE removes versions, fields, categories, comments, votes, etc.
            else:
                # Multiple authors — just remove this user's link
                db.delete(link)

        # === 2. Delete paper comments and votes by this user ===
        db.query(CommentVote).filter(CommentVote.user_id == uid).delete()
        comments = db.query(Comment).filter(Comment.user_id == uid).all()
        for c in comments:
            db.query(CommentVote).filter(CommentVote.comment_id == c.id).delete()
            db.delete(c)

        # === 3. Delete direct messages (both sent and received) ===
        db.query(DirectMessage).filter(
            (DirectMessage.sender_id == uid) | (DirectMessage.recipient_id == uid)
        ).delete(synchronize_session='fetch')

        # === 4. Anonymize audit trail records (set user_id to NULL) ===
        db.query(Endorsement).filter(Endorsement.user_id == uid).update(
            {"user_id": None}, synchronize_session='fetch')
        db.query(EditorialBoardMember).filter(EditorialBoardMember.user_id == uid).update(
            {"user_id": None, "is_active": False}, synchronize_session='fetch')
        db.query(EditorialDecision).filter(EditorialDecision.editor_user_id == uid).update(
            {"editor_user_id": None}, synchronize_session='fetch')
        db.query(HumanReview).filter(HumanReview.reviewer_user_id == uid).update(
            {"reviewer_user_id": None}, synchronize_session='fetch')
        db.query(HumanReview).filter(HumanReview.assigned_by_user_id == uid).update(
            {"assigned_by_user_id": None}, synchronize_session='fetch')
        db.query(StageHistory).filter(StageHistory.triggered_by_user_id == uid).update(
            {"triggered_by_user_id": None}, synchronize_session='fetch')
        db.query(ExtensionRequest).filter(ExtensionRequest.requested_by_user_id == uid).update(
            {"requested_by_user_id": None}, synchronize_session='fetch')
        db.query(ExtensionRequest).filter(ExtensionRequest.reviewed_by_user_id == uid).update(
            {"reviewed_by_user_id": None}, synchronize_session='fetch')
        db.query(SubmissionScreening).filter(SubmissionScreening.user_id == uid).update(
            {"user_id": None}, synchronize_session='fetch')

        # === 5. Delete the user record ===
        # CASCADE handles: UserEmail, CommunityPrompt (+votes/comments), DiscussionPost (+votes/comments),
        # Notification, UserFollow, PaperVote
        db.delete(user)
        db.commit()

        print(f"[delete-account] User {uid} ({session_user.get('name', '?')}) fully deleted")

    except Exception as e:
        db.rollback()
        print(f"ERROR: Failed to delete user {uid}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to delete account. Please contact support.")

    # Clear session
    request.session.clear()

    return RedirectResponse(url="/?deleted=true", status_code=303)

@router.post("/profile/toggle-messaging")
async def toggle_messaging(request: Request, db: Session = Depends(get_db)):
    """Toggle open_to_messaging setting."""
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=401)
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404)
    user.open_to_messaging = not user.open_to_messaging
    db.commit()
    return JSONResponse({"success": True, "open_to_messaging": user.open_to_messaging})


@router.post("/profile/refresh-badge")
async def refresh_badge(request: Request, db: Session = Depends(get_db)):
    """Manually refresh ORCID badge and publication data."""
    # Check if user is logged in
    session_user = request.session.get("user")
    if not session_user:
        return JSONResponse(
            {"error": "Not authenticated"},
            status_code=401
        )

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        return JSONResponse(
            {"error": "User not found"},
            status_code=404
        )

    try:
        # Fetch updated badge data from ORCID
        badge_data = await orcid_service.update_user_badge(user.orcid_id)

        # Update user record
        user.works_count = badge_data["works_count"]
        user.badge = badge_data["badge"]
        user.orcid_works = badge_data["journal_articles"]
        user.badge_updated_at = datetime.utcnow()

        db.commit()
        db.refresh(user)

        return JSONResponse({
            "success": True,
            "badge": user.badge,
            "works_count": user.works_count,
            "updated_at": user.badge_updated_at.isoformat()
        })

    except Exception as e:
        print(f"Error refreshing badge: {e}")
        return JSONResponse(
            {"error": "Failed to refresh badge data"},
            status_code=500
        )

@router.post("/profile/update-scholar")
async def update_scholar_data(
    request: Request,
    db: Session = Depends(get_db),
    citations: int = Form(None),
    h_index: int = Form(None),
    i10_index: int = Form(None)
):
    """Update Google Scholar metrics (fetched client-side to distribute IP load)."""
    # Check if user is logged in
    session_user = request.session.get("user")
    if not session_user:
        return JSONResponse(
            {"error": "Not authenticated"},
            status_code=401
        )

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        return JSONResponse(
            {"error": "User not found"},
            status_code=404
        )

    # Update Scholar metrics
    user.scholar_citations = citations
    user.scholar_h_index = h_index
    user.scholar_i10_index = i10_index
    user.scholar_updated_at = datetime.utcnow()

    db.commit()

    return JSONResponse({
        "success": True,
        "updated_at": user.scholar_updated_at.isoformat()
    })
