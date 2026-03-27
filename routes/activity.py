"""Activity profile routes — user's posts and comments."""
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from models.database import get_db
from models.user import User
from models.prompt import CommunityPrompt, PromptComment
from models.discussion import UserFollow

router = APIRouter(tags=["activity"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


@router.get("/activity/{user_id}", response_class=HTMLResponse)
async def activity_profile(
    user_id: int,
    request: Request,
    tab: str = Query("posts", regex="^(posts|comments)$"),
    db: Session = Depends(get_db),
):
    """Activity profile — shows a user's posts and comments."""
    profile_user = db.query(User).filter(User.id == user_id).first()
    if not profile_user:
        raise HTTPException(status_code=404, detail="User not found")

    session_user = request.session.get("user")
    is_own = session_user and session_user["id"] == user_id

    # Counts for tab badges
    post_count = db.query(CommunityPrompt).filter(CommunityPrompt.user_id == user_id).count()
    comment_count = db.query(PromptComment).filter(PromptComment.user_id == user_id).count()

    # Follower / following counts
    follower_count = db.query(UserFollow).filter(UserFollow.followed_id == user_id).count()
    following_count = db.query(UserFollow).filter(UserFollow.follower_id == user_id).count()
    is_following = False
    if session_user and not is_own:
        is_following = db.query(UserFollow).filter(
            UserFollow.follower_id == session_user["id"],
            UserFollow.followed_id == user_id,
        ).first() is not None

    # Tab data
    items = []
    if tab == "posts":
        items = (
            db.query(CommunityPrompt)
            .filter(CommunityPrompt.user_id == user_id)
            .order_by(CommunityPrompt.created_at.desc())
            .all()
        )
    elif tab == "comments":
        items = (
            db.query(PromptComment)
            .filter(PromptComment.user_id == user_id)
            .order_by(PromptComment.created_at.desc())
            .all()
        )

    return templates.TemplateResponse(
        "activity.html",
        {
            "request": request,
            "user": session_user,
            "profile_user": profile_user,
            "is_own": is_own,
            "tab": tab,
            "items": items,
            "post_count": post_count,
            "comment_count": comment_count,
            "follower_count": follower_count,
            "following_count": following_count,
            "is_following": is_following,
        },
    )
