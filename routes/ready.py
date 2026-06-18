"""Per-user 'your paper is ready for AI review' explainer page.

Linked from the in-app notification we drop for authors we can't reach by
email (see services/notification.py). Lists the signed-in user's endorsed
papers that still need to be submitted for AI review, and — if we have no
email on file for them — explains that they must add one first.
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from template_helpers import register_filters
from models.database import get_db
from models.user import User
from models.paper import Paper, PaperHumanAuthor
from services.notification import user_is_email_reachable

router = APIRouter(tags=["ready"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


@router.get("/ready-for-ai-review", response_class=HTMLResponse)
async def ready_for_ai_review(request: Request, db: Session = Depends(get_db)):
    """Show the signed-in user their papers that are ready for AI review."""
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse(url="/auth/login", status_code=303)

    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user:
        return RedirectResponse(url="/auth/login", status_code=303)

    papers = (
        db.query(Paper)
        .join(PaperHumanAuthor, PaperHumanAuthor.paper_id == Paper.id)
        .filter(
            PaperHumanAuthor.user_id == user.id,
            Paper.review_stage == 2,
            Paper.status == "published",
            Paper.reviewer3_tracking_id.is_(None),
        )
        .order_by(Paper.stage_entered_at.desc().nulls_last(), Paper.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "ready_for_ai_review.html",
        {
            "request": request,
            "user": session_user,
            "papers": papers,
            "needs_email": not user_is_email_reachable(user.id, db),
        },
    )
