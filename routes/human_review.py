"""Human peer review routes for Stage 3 -> 4 transition."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from datetime import datetime
from models.database import get_db
from models.paper import Paper
from models.review import HumanReview
from models.user import User
from services.email import email_service

router = APIRouter(tags=["human_review"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


@router.get("/review/{token}", response_class=HTMLResponse)
async def review_landing(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Invitation landing page. Shows paper details + Accept/Decline buttons."""
    review = db.query(HumanReview).filter(HumanReview.invitation_token == token).first()
    if not review:
        raise HTTPException(status_code=404, detail="Invalid or expired review invitation")

    paper = db.query(Paper).filter(Paper.id == review.paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    session_user = request.session.get("user")

    # If already submitted, show confirmation
    if review.review_submitted_at:
        return templates.TemplateResponse(
            "review_landing.html",
            {
                "request": request,
                "paper": paper,
                "review": review,
                "user": session_user,
                "already_submitted": True,
            },
        )

    # If declined, show message
    if review.invitation_declined_at:
        return templates.TemplateResponse(
            "review_landing.html",
            {
                "request": request,
                "paper": paper,
                "review": review,
                "user": session_user,
                "declined": True,
            },
        )

    return templates.TemplateResponse(
        "review_landing.html",
        {
            "request": request,
            "paper": paper,
            "review": review,
            "user": session_user,
            "already_submitted": False,
            "declined": False,
        },
    )


@router.get("/review/{token}/accept", response_class=HTMLResponse)
async def accept_review(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Accept review invitation - redirects to ORCID login if not authenticated."""
    review = db.query(HumanReview).filter(HumanReview.invitation_token == token).first()
    if not review:
        raise HTTPException(status_code=404, detail="Invalid review invitation")

    session_user = request.session.get("user")

    if not session_user:
        # Store review token in session and redirect to ORCID login
        request.session["review_token"] = token
        return RedirectResponse(url="/auth/login")

    # User is authenticated - mark accepted and redirect to form
    if not review.invitation_accepted_at:
        review.invitation_accepted_at = datetime.utcnow()
        review.reviewer_user_id = session_user["id"]
        db.commit()

    return RedirectResponse(url=f"/review/{token}/form")


@router.get("/review/{token}/form", response_class=HTMLResponse)
async def review_form(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Review form (requires ORCID auth)."""
    session_user = request.session.get("user")
    if not session_user:
        request.session["review_token"] = token
        return RedirectResponse(url="/auth/login")

    review = db.query(HumanReview).filter(HumanReview.invitation_token == token).first()
    if not review:
        raise HTTPException(status_code=404, detail="Invalid review invitation")

    if review.review_submitted_at:
        return RedirectResponse(url=f"/review/{token}")

    paper = db.query(Paper).filter(Paper.id == review.paper_id).first()

    # Link reviewer to their user account
    if not review.reviewer_user_id:
        review.reviewer_user_id = session_user["id"]
        review.invitation_accepted_at = datetime.utcnow()
        db.commit()

    return templates.TemplateResponse(
        "review_submit.html",
        {
            "request": request,
            "paper": paper,
            "review": review,
            "user": session_user,
        },
    )


@router.post("/review/{token}/submit", response_class=HTMLResponse)
async def submit_review(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    review_content: str = Form(...),
    recommendation: str = Form(...),
):
    """Submit review (requires ORCID auth)."""
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=401, detail="ORCID authentication required to submit a review")

    review = db.query(HumanReview).filter(HumanReview.invitation_token == token).first()
    if not review:
        raise HTTPException(status_code=404, detail="Invalid review invitation")

    if review.review_submitted_at:
        raise HTTPException(status_code=400, detail="Review already submitted")

    # Validate recommendation
    valid_recommendations = ["accept", "minor_revisions", "major_revisions", "reject"]
    if recommendation not in valid_recommendations:
        raise HTTPException(status_code=400, detail="Invalid recommendation")

    # Get user for name
    user = db.query(User).filter(User.id == session_user["id"]).first()

    # Submit the review
    review.review_content = review_content
    review.recommendation = recommendation
    review.review_submitted_at = datetime.utcnow()
    review.reviewer_user_id = session_user["id"]
    review.reviewer_name = user.name if user else session_user.get("name", "Reviewer")

    db.commit()

    # Notify paper authors
    paper = db.query(Paper).filter(Paper.id == review.paper_id).first()
    if paper:
        for author in paper.human_authors:
            if author.user and author.user.email:
                email_service.send_review_received(
                    to_email=author.user.email,
                    paper_title=paper.title,
                    reviewer_name=review.reviewer_name,
                )

    return RedirectResponse(url=f"/review/{token}", status_code=303)


@router.post("/review/{token}/decline")
async def decline_review(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Decline invitation (no auth needed)."""
    review = db.query(HumanReview).filter(HumanReview.invitation_token == token).first()
    if not review:
        raise HTTPException(status_code=404, detail="Invalid review invitation")

    review.invitation_declined_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=f"/review/{token}", status_code=303)
