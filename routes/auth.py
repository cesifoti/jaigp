"""Authentication routes for ORCID OAuth."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from models.database import get_db
from models.user import User
from services.orcid import orcid_service
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
        user.email = user_info.get("email")
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

    # Redirect to homepage
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
        user_papers = db.query(Paper).join(
            PaperHumanAuthor
        ).filter(
            PaperHumanAuthor.user_id == user_id,
            Paper.status.in_(["submitted", "under-review", "published"])
        ).order_by(
            Paper.published_date.desc()
        ).all()

        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "user": session_user,  # Current logged-in user (may be None)
                "profile_user": profile_user,  # User whose profile is being viewed
                "papers": user_papers,
                "is_own_profile": session_user and session_user["id"] == user_id
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
    user_papers = db.query(Paper).join(
        PaperHumanAuthor
    ).filter(
        PaperHumanAuthor.user_id == user.id
    ).order_by(
        Paper.published_date.desc()
    ).all()

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": session_user,
            "profile_user": user,
            "papers": user_papers,
            "is_own_profile": True
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

    return templates.TemplateResponse(
        "profile_edit.html",
        {
            "request": request,
            "user": session_user,
            "profile_user": user
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
    rankless_url: str = Form(None)
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
    user.email = email.strip() if email else None
    user.affiliation = affiliation.strip() if affiliation else None
    user.google_scholar_url = google_scholar_url.strip() if google_scholar_url else None
    user.rankless_url = rankless_url.strip() if rankless_url else None

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

    # Compile user data
    export_data = {
        "export_date": datetime.utcnow().isoformat(),
        "user_profile": {
            "orcid_id": user.orcid_id,
            "name": user.name,
            "email": user.email,
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
async def delete_account_confirm(request: Request, db: Session = Depends(get_db)):
    """GDPR Right to Erasure: Delete user account and personal data."""
    # Check if user is logged in
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login")

    # Get user from database
    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/auth/login")

    # Anonymize or delete user data
    from models.paper import PaperHumanAuthor
    from models.comment import Comment, CommentVote
    
    # Option 1: Anonymize papers (keep papers but remove personal attribution)
    # This maintains academic integrity while respecting privacy
    paper_authors = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.user_id == user.id
    ).all()
    
    for author in paper_authors:
        db.delete(author)
    
    # Delete comments
    comments = db.query(Comment).filter(Comment.user_id == user.id).all()
    for comment in comments:
        # Delete associated votes
        db.query(CommentVote).filter(CommentVote.comment_id == comment.id).delete()
        db.delete(comment)
    
    # Delete user's votes on other comments
    db.query(CommentVote).filter(CommentVote.user_id == user.id).delete()
    
    # Delete user account
    db.delete(user)
    db.commit()

    # Clear session
    request.session.clear()

    return RedirectResponse(url="/?deleted=true", status_code=303)

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
