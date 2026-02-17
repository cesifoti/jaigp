"""Paper deletion routes."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from models.database import get_db
from models.paper import Paper, PaperHumanAuthor
from services.file_storage import file_storage

router = APIRouter(prefix="/paper", tags=["delete"])

def require_auth(request: Request):
    """Dependency to require authentication."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

@router.post("/{paper_id}/delete")
async def delete_paper(
    paper_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete a paper (only by authors)."""
    user_data = require_auth(request)

    # Get paper
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Check if user is an author
    is_author = db.query(PaperHumanAuthor).filter(
        PaperHumanAuthor.paper_id == paper_id,
        PaperHumanAuthor.user_id == user_data["id"]
    ).first() is not None

    if not is_author:
        raise HTTPException(status_code=403, detail="Only authors can delete this paper")

    # Delete associated files
    for version in paper.versions:
        file_path = file_storage.get_file_path(version.pdf_filename, paper.published_date)
        file_storage.delete_file(file_path)

    if paper.image_filename:
        image_path = file_storage.get_file_path(paper.image_filename, paper.published_date)
        file_storage.delete_file(image_path)

    # Delete paper (cascade will handle related records)
    db.delete(paper)
    db.commit()

    # Redirect to profile
    return RedirectResponse(url="/auth/profile", status_code=303)
