"""Homepage and about page routes."""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.database import get_db
from models.paper import Paper
from models.paper_vote import PaperVote
from services.cache import cache, cache_result
import random

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

def get_homepage_papers(db: Session):
    """Get latest papers for homepage (cached)."""
    return db.query(Paper).filter(
        Paper.status == "published"
    ).order_by(
        Paper.published_date.desc()
    ).limit(10).all()

@router.get("/", response_class=HTMLResponse)
async def homepage(
    request: Request,
    db: Session = Depends(get_db),
    status: str = Query("submitted", regex="^(submitted|under-review)$"),
    page: int = Query(1, ge=1)
):
    """Homepage with papers filtered by submission status."""
    # Pagination settings
    per_page = 18
    offset = (page - 1) * per_page

    # Base query for papers based on status
    if status == "under-review":
        query = db.query(Paper).filter(Paper.status == "under-review")
    else:  # submitted
        query = db.query(Paper).filter(Paper.status == "published")

    # Get total count for pagination
    total_papers = query.count()
    total_pages = (total_papers + per_page - 1) // per_page

    # Get papers for current page
    papers = query.order_by(
        Paper.published_date.desc()
    ).limit(per_page).offset(offset).all()

    # Group papers by date
    from collections import defaultdict
    papers_by_date = defaultdict(list)
    for paper in papers:
        date_key = paper.published_date.strftime("%B %d, %Y")
        papers_by_date[date_key].append(paper)

    # Get user from session
    user = request.session.get("user")

    # Random motto selection
    mottos = [
        "Exploring ideas at the edge of authorship.",
        "A journal for thinking out loud with machines.",
        "Rigorous enough to learn, humble enough to laugh.",
        "Where experiments count as contributions.",
        "Proceedings of productive uncertainty.",
        "All models are wrong; some papers are interesting.",
        "In curiosity we trust.",
        "Footnotes from the frontier.",
        "Taking ideas seriously, not ourselves.",
        "We're not entirely sure these papers are good — after all, we're only human.",
        "We might be wrong. That's why we publish."
    ]
    motto = random.choice(mottos)

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "papers": papers,
            "papers_by_date": dict(papers_by_date),
            "user": user,
            "motto": motto,
            "status": status,
            "page": page,
            "total_pages": total_pages,
            "total_papers": total_papers,
            "per_page": per_page
        }
    )

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    """About page."""
    user = request.session.get("user")

    return templates.TemplateResponse(
        "about.html",
        {
            "request": request,
            "user": user
        }
    )

@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    """Terms of Service page."""
    user = request.session.get("user")

    return templates.TemplateResponse(
        "terms.html",
        {
            "request": request,
            "user": user
        }
    )

@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    """Privacy Policy page."""
    user = request.session.get("user")

    return templates.TemplateResponse(
        "privacy.html",
        {
            "request": request,
            "user": user
        }
    )
