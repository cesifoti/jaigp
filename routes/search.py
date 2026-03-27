"""Site-wide search for papers and authors."""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, case
from models.database import get_db
from models.paper import Paper, PaperHumanAuthor, PaperCategory, PaperField
from models.user import User

router = APIRouter(tags=["search"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = Query(""),
    tab: str = Query("papers", regex="^(papers|authors)$"),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """Unified search across papers and authors."""
    user = request.session.get("user")
    query = q.strip()
    per_page = 20

    paper_results = []
    author_results = []
    paper_count = 0
    author_count = 0
    total_pages = 1

    if query:
        search_term = f"%{query}%"

        # --- Paper search ---
        # Find paper IDs matching title, abstract, categories, fields, or author names
        title_match = Paper.title.ilike(search_term)
        abstract_match = Paper.abstract.ilike(search_term)

        # Papers matching by category
        cat_paper_ids = db.query(PaperCategory.paper_id).filter(
            PaperCategory.leaf_category.ilike(search_term)
        ).subquery()

        # Papers matching by field
        field_paper_ids = db.query(PaperField.paper_id).filter(
            PaperField.display_name.ilike(search_term)
        ).subquery()

        # Papers matching by author name
        author_paper_ids = db.query(PaperHumanAuthor.paper_id).join(
            User, PaperHumanAuthor.user_id == User.id
        ).filter(
            User.name.ilike(search_term)
        ).subquery()

        visible_statuses = ["published", "ai_screen_rejected"]

        paper_query = db.query(Paper).filter(
            Paper.status.in_(visible_statuses),
            or_(
                title_match,
                abstract_match,
                Paper.id.in_(cat_paper_ids),
                Paper.id.in_(field_paper_ids),
                Paper.id.in_(author_paper_ids),
            )
        )

        paper_count = paper_query.count()

        if tab == "papers":
            total_pages = max(1, (paper_count + per_page - 1) // per_page)
            offset = (min(page, total_pages) - 1) * per_page

            # Sort: title matches first, then by date
            paper_results = paper_query.order_by(
                case((Paper.title.ilike(search_term), 0), else_=1),
                Paper.published_date.desc().nulls_last(),
            ).limit(per_page).offset(offset).all()

        # --- Author search ---
        author_query = db.query(User).filter(
            or_(
                User.name.ilike(search_term),
                User.affiliation.ilike(search_term),
                User.orcid_id.ilike(search_term),
            )
        )

        author_count = author_query.count()

        if tab == "authors":
            total_pages = max(1, (author_count + per_page - 1) // per_page)
            offset = (min(page, total_pages) - 1) * per_page

            author_results = author_query.order_by(
                case((User.name.ilike(search_term), 0), else_=1),
                User.works_count.desc().nulls_last(),
            ).limit(per_page).offset(offset).all()

            # Get paper counts for each author
            author_ids = [a.id for a in author_results]
            paper_counts = {}
            if author_ids:
                counts = db.query(
                    PaperHumanAuthor.user_id,
                    func.count(PaperHumanAuthor.paper_id).label("cnt"),
                ).filter(
                    PaperHumanAuthor.user_id.in_(author_ids)
                ).group_by(PaperHumanAuthor.user_id).all()
                paper_counts = {uid: cnt for uid, cnt in counts}

            for author in author_results:
                author._paper_count = paper_counts.get(author.id, 0)

    current_count = paper_count if tab == "papers" else author_count

    return templates.TemplateResponse("search.html", {
        "request": request,
        "user": user,
        "query": query,
        "tab": tab,
        "page": page,
        "total_pages": total_pages,
        "paper_results": paper_results,
        "author_results": author_results,
        "paper_count": paper_count,
        "author_count": author_count,
        "current_count": current_count,
    })
