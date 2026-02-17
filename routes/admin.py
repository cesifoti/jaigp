"""Admin console routes."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, desc
from sqlalchemy.orm import Session
from models.database import get_db
from models.user import User
from models.paper import Paper, PaperHumanAuthor
from jinja2 import Template
import config

router = APIRouter()


def require_admin(request: Request):
    """Check if user is admin."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    orcid_id = user.get("orcid_id")
    if orcid_id not in config.ADMIN_ORCIDS:
        raise HTTPException(status_code=403, detail="Admin access required")

    return user


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    page: int = 1,
    per_page: int = 25,
    sort_by: str = "papers",
    sort_order: str = "desc",
    search: str = "",
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin)
):
    """Admin dashboard with user and paper statistics."""
    from main import templates

    # Calculate offset
    offset = (page - 1) * per_page

    # Base query with paper count
    users_query = db.query(
        User,
        func.count(PaperHumanAuthor.paper_id).label('paper_count')
    ).outerjoin(
        PaperHumanAuthor, User.id == PaperHumanAuthor.user_id
    )

    # Apply search filter if provided
    if search:
        search_term = f"%{search}%"
        users_query = users_query.filter(
            (User.name.ilike(search_term)) |
            (User.orcid_id.ilike(search_term)) |
            (User.email.ilike(search_term)) |
            (User.affiliation.ilike(search_term))
        )

    # Group by user
    users_query = users_query.group_by(User.id)

    # Apply sorting
    if sort_by == "name":
        sort_column = User.name
    elif sort_by == "orcid":
        sort_column = User.orcid_id
    elif sort_by == "badge":
        sort_column = User.badge
    elif sort_by == "papers":
        sort_column = func.count(PaperHumanAuthor.paper_id)
    elif sort_by == "email":
        sort_column = User.email
    elif sort_by == "joined":
        sort_column = User.created_at
    else:
        sort_column = func.count(PaperHumanAuthor.paper_id)

    # Apply sort order
    if sort_order == "asc":
        users_query = users_query.order_by(sort_column.asc())
    else:
        users_query = users_query.order_by(sort_column.desc())

    # Get total count for pagination (before limit/offset)
    total_users = users_query.count()
    total_pages = (total_users + per_page - 1) // per_page

    # Apply pagination
    users_query = users_query.limit(per_page).offset(offset)

    # Execute query
    users_data = []
    for user, paper_count in users_query:
        users_data.append({
            'user': user,
            'paper_count': paper_count
        })

    # Get overall statistics (unfiltered)
    total_users_all = db.query(func.count(User.id)).scalar()
    total_papers = db.query(func.count(Paper.id)).scalar()
    users_with_papers = db.query(func.count(func.distinct(PaperHumanAuthor.user_id))).scalar()

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": admin_user,
        "users_data": users_data,
        "total_users": total_users,  # Filtered count
        "total_users_all": total_users_all,  # Total count
        "total_papers": total_papers,
        "users_with_papers": users_with_papers,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "search": search,
    })


@router.get("/user/{orcid_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    orcid_id: str,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(require_admin)
):
    """View detailed information about a specific user."""
    from main import templates

    # Get user
    user = db.query(User).filter(User.orcid_id == orcid_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get user's papers
    papers = db.query(Paper).join(
        PaperHumanAuthor, Paper.id == PaperHumanAuthor.paper_id
    ).filter(
        PaperHumanAuthor.user_id == user.id
    ).order_by(Paper.published_date.desc()).all()

    return templates.TemplateResponse("admin/user_detail.html", {
        "request": request,
        "user": admin_user,
        "profile_user": user,
        "papers": papers,
    })
