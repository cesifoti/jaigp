"""Paper voting routes - thumbs up/down for papers."""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from models.database import get_db
from models.paper import Paper
from models.paper_vote import PaperVote
from datetime import datetime

router = APIRouter(tags=["paper_votes"])


def require_auth(request: Request):
    """Dependency to require authentication."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("/paper/{paper_id}/vote")
async def vote_paper(
    paper_id: int,
    request: Request,
    vote_type: str = Form(...),
    db: Session = Depends(get_db)
):
    """Vote on a paper (upvote or downvote)."""
    user_data = require_auth(request)

    # Verify paper exists
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Validate vote type
    if vote_type not in ["upvote", "downvote"]:
        raise HTTPException(status_code=400, detail="Invalid vote type")

    # Check if user already voted
    existing_vote = db.query(PaperVote).filter(
        PaperVote.paper_id == paper_id,
        PaperVote.user_id == user_data["id"]
    ).first()

    if existing_vote:
        if existing_vote.vote_type == vote_type:
            # Remove vote if clicking same type (toggle off)
            db.delete(existing_vote)
        else:
            # Change vote type
            existing_vote.vote_type = vote_type
    else:
        # Create new vote
        vote = PaperVote(
            paper_id=paper_id,
            user_id=user_data["id"],
            vote_type=vote_type,
            created_at=datetime.utcnow()
        )
        db.add(vote)

    db.commit()
    db.refresh(paper)

    # Return updated vote counts as JSON
    return JSONResponse({
        "success": True,
        "upvotes": paper.upvote_count,
        "downvotes": paper.downvote_count,
        "net_votes": paper.net_votes
    })


@router.get("/paper/{paper_id}/vote-status")
async def get_vote_status(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get current user's vote status for a paper."""
    user_data = request.session.get("user")

    if not user_data:
        return JSONResponse({
            "voted": False,
            "vote_type": None
        })

    # Check if user has voted
    existing_vote = db.query(PaperVote).filter(
        PaperVote.paper_id == paper_id,
        PaperVote.user_id == user_data["id"]
    ).first()

    return JSONResponse({
        "voted": existing_vote is not None,
        "vote_type": existing_vote.vote_type if existing_vote else None
    })
