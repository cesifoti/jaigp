"""Issues navigation routes for browsing papers by date."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from models.database import get_db
from models.paper import Paper
from datetime import datetime
from collections import defaultdict

router = APIRouter(prefix="/issues", tags=["issues"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

@router.get("", response_class=HTMLResponse)
async def browse_years(request: Request, db: Session = Depends(get_db)):
    """Browse papers by year."""
    # Get all unique years with paper counts
    years_data = db.query(
        extract('year', Paper.published_date).label('year'),
        func.count(Paper.id).label('count')
    ).filter(
        Paper.status == "published"
    ).group_by(
        extract('year', Paper.published_date)
    ).order_by(
        extract('year', Paper.published_date).desc()
    ).all()

    years = [{"year": int(y.year), "count": y.count} for y in years_data]

    user = request.session.get("user")

    return templates.TemplateResponse(
        "issues.html",
        {
            "request": request,
            "user": user,
            "view": "years",
            "years": years
        }
    )

@router.get("/{year}", response_class=HTMLResponse)
async def browse_months(year: int, request: Request, db: Session = Depends(get_db)):
    """Browse papers by month within a year."""
    # Get all papers for this year
    papers = db.query(Paper).filter(
        extract('year', Paper.published_date) == year,
        Paper.status == "published"
    ).all()

    # Group by month
    months = defaultdict(int)
    for paper in papers:
        month_name = paper.published_date.strftime("%B")
        month_num = paper.published_date.month
        months[(month_num, month_name)] += 1

    # Sort by month number
    months_list = [
        {"month": name, "month_num": num, "count": count}
        for (num, name), count in sorted(months.items())
    ]

    user = request.session.get("user")

    return templates.TemplateResponse(
        "issues.html",
        {
            "request": request,
            "user": user,
            "view": "months",
            "year": year,
            "months": months_list
        }
    )

@router.get("/{year}/{month}", response_class=HTMLResponse)
async def browse_days(
    year: int,
    month: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Browse papers by day within a month."""
    # Convert month name to number
    month_num = datetime.strptime(month, "%B").month

    # Get all papers for this year/month
    papers = db.query(Paper).filter(
        extract('year', Paper.published_date) == year,
        extract('month', Paper.published_date) == month_num,
        Paper.status == "published"
    ).all()

    # Group by day
    days = defaultdict(int)
    for paper in papers:
        day = paper.published_date.day
        days[day] += 1

    # Sort by day
    days_list = [
        {"day": day, "count": count}
        for day, count in sorted(days.items())
    ]

    user = request.session.get("user")

    return templates.TemplateResponse(
        "issues.html",
        {
            "request": request,
            "user": user,
            "view": "days",
            "year": year,
            "month": month,
            "days": days_list
        }
    )

@router.get("/{year}/{month}/{day}", response_class=HTMLResponse)
async def browse_papers(
    year: int,
    month: str,
    day: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """View all papers for a specific date."""
    # Convert month name to number
    month_num = datetime.strptime(month, "%B").month

    # Get all papers for this specific date
    papers = db.query(Paper).filter(
        extract('year', Paper.published_date) == year,
        extract('month', Paper.published_date) == month_num,
        extract('day', Paper.published_date) == day,
        Paper.status == "published"
    ).order_by(
        Paper.published_date.desc()
    ).all()

    user = request.session.get("user")

    return templates.TemplateResponse(
        "issues.html",
        {
            "request": request,
            "user": user,
            "view": "papers",
            "year": year,
            "month": month,
            "day": day,
            "papers": papers
        }
    )
