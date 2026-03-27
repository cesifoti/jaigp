"""Comment and voting routes."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import distinct
from models.database import get_db
from models.comment import Comment, CommentVote
from models.paper import Paper
from datetime import datetime

router = APIRouter(tags=["comments"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

def require_auth(request: Request):
    """Dependency to require authentication."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

@router.post("/paper/{paper_id}/comment", response_class=HTMLResponse)
async def add_comment(
    paper_id: int,
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db)
):
    """Add a comment to a paper (HTMX endpoint)."""
    user_data = require_auth(request)

    # Verify paper exists
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Create comment
    comment = Comment(
        paper_id=paper_id,
        user_id=user_data["id"],
        content=content,
        created_at=datetime.utcnow()
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Notify paper authors
    from services.notification import create_notification
    notified_user_ids = set()
    for author in paper.human_authors:
        if author.user_id:
            create_notification(
                user_id=author.user_id, notification_type="paper_comment",
                link=f"/paper/{paper_id}#comment-{comment.id}", db=db,
                source_user_id=user_data["id"], content_preview=content[:150],
            )
            notified_user_ids.add(author.user_id)

    # Notify users who previously commented on this paper (thread subscription)
    prior_commenter_ids = db.query(distinct(Comment.user_id)).filter(
        Comment.paper_id == paper_id,
        Comment.id != comment.id,
    ).all()
    for (uid,) in prior_commenter_ids:
        if uid not in notified_user_ids:
            create_notification(
                user_id=uid, notification_type="paper_comment",
                link=f"/paper/{paper_id}#comment-{comment.id}", db=db,
                source_user_id=user_data["id"],
                content_preview=content[:150],
            )
    db.commit()

    # Return rendered comment component
    return templates.TemplateResponse(
        "components/comment.html",
        {
            "request": request,
            "comment": comment,
            "user": user_data
        }
    )


@router.post("/comment/{comment_id}/delete")
async def delete_comment(
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a paper comment (author only)."""
    user_data = require_auth(request)
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user_data["id"]:
        raise HTTPException(status_code=403, detail="Only the author can delete this comment")
    db.delete(comment)
    db.commit()
    return JSONResponse({"success": True})

@router.post("/comment/{comment_id}/vote")
async def vote_comment(
    comment_id: int,
    request: Request,
    vote_type: str = Form(...),
    db: Session = Depends(get_db)
):
    """Vote on a comment (HTMX endpoint)."""
    user_data = require_auth(request)

    # Verify comment exists
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Validate vote type
    if vote_type not in ["upvote", "downvote"]:
        raise HTTPException(status_code=400, detail="Invalid vote type")

    # Check if user already voted
    existing_vote = db.query(CommentVote).filter(
        CommentVote.comment_id == comment_id,
        CommentVote.user_id == user_data["id"]
    ).first()

    if existing_vote:
        if existing_vote.vote_type == vote_type:
            # Remove vote if clicking same type
            db.delete(existing_vote)
        else:
            # Change vote type
            existing_vote.vote_type = vote_type
    else:
        # Create new vote
        vote = CommentVote(
            comment_id=comment_id,
            user_id=user_data["id"],
            vote_type=vote_type,
            created_at=datetime.utcnow()
        )
        db.add(vote)

    db.commit()
    db.refresh(comment)

    # Return updated vote count
    return f'<span id="vote-count-{comment_id}" class="text-sm font-medium text-slate-700">{comment.vote_count}</span>'

@router.get("/paper/{paper_id}/comments", response_class=HTMLResponse)
async def load_comments(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Load comments for a paper (HTMX endpoint)."""
    # Get comments
    comments = db.query(Comment).filter(
        Comment.paper_id == paper_id
    ).order_by(
        Comment.created_at.desc()
    ).all()

    user = request.session.get("user")

    # Render comments list
    html = ""
    for comment in comments:
        rendered = templates.TemplateResponse(
            "components/comment.html",
            {
                "request": request,
                "comment": comment,
                "user": user
            }
        )
        html += rendered.body.decode()

    return html
