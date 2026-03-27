"""Issues navigation routes for browsing papers by date."""
import calendar
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from models.database import get_db
from models.paper import Paper
from models.stage_history import StageHistory
from datetime import datetime
from collections import defaultdict

router = APIRouter(prefix="/issues", tags=["issues"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

@router.get("", response_class=HTMLResponse)
async def browse_years(request: Request, db: Session = Depends(get_db)):
    """Browse papers by year."""
    # Get all unique years with paper counts
    visible_statuses = ["published", "ai_screen_rejected"]
    years_data = db.query(
        extract('year', Paper.published_date).label('year'),
        func.count(Paper.id).label('count')
    ).filter(
        Paper.status.in_(visible_statuses)
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
    visible_statuses = ["published", "ai_screen_rejected"]
    papers = db.query(Paper).filter(
        extract('year', Paper.published_date) == year,
        Paper.status.in_(visible_statuses)
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

def _effective_stage_for_month(paper_id: int, year: int, month_num: int, db: Session) -> int:
    """Compute the highest stage a paper reached by the end of a given month.

    Uses the stage_history table.  If no transitions happened on or before
    the last day of the month, the paper was at stage 0 (Submitted).
    """
    last_day = calendar.monthrange(year, month_num)[1]
    month_end = datetime(year, month_num, last_day, 23, 59, 59)

    row = (
        db.query(func.max(StageHistory.to_stage))
        .filter(
            StageHistory.paper_id == paper_id,
            StageHistory.created_at <= month_end,
        )
        .scalar()
    )
    return row if row is not None else 0


@router.get("/{year}/{month}", response_class=HTMLResponse)
async def browse_days(
    year: int,
    month: str,
    request: Request,
    stage: int = Query(None),
    db: Session = Depends(get_db)
):
    """Browse papers for a month.

    Shows two groups:
    1. Papers submitted (published_date) during this month
    2. Papers that advanced stages during this month (even if submitted earlier)

    Each paper shows its effective stage as of the end of the month.
    """
    month_num = datetime.strptime(month, "%B").month
    last_day = calendar.monthrange(year, month_num)[1]
    month_start = datetime(year, month_num, 1)
    month_end = datetime(year, month_num, last_day, 23, 59, 59)

    visible_statuses = ["published", "ai_screen_rejected"]

    # Papers submitted during this month
    submitted_this_month = db.query(Paper).filter(
        extract('year', Paper.published_date) == year,
        extract('month', Paper.published_date) == month_num,
        Paper.status.in_(visible_statuses)
    ).all()
    submitted_ids = {p.id for p in submitted_this_month}

    # Papers that had stage transitions during this month (even if submitted earlier)
    transitioning_ids = set(
        row[0] for row in db.query(StageHistory.paper_id).filter(
            StageHistory.created_at >= month_start,
            StageHistory.created_at <= month_end,
        ).distinct().all()
    )
    # Load any papers that transitioned but weren't submitted this month
    extra_ids = transitioning_ids - submitted_ids
    extra_papers = []
    if extra_ids:
        extra_papers = db.query(Paper).filter(
            Paper.id.in_(extra_ids),
            Paper.status.in_(visible_statuses)
        ).all()

    all_papers = submitted_this_month + extra_papers

    # Compute effective stage for each paper as of this month
    paper_effective_stages = {}
    for p in all_papers:
        paper_effective_stages[p.id] = _effective_stage_for_month(
            p.id, year, month_num, db
        )

    # Count papers per effective stage for tab display
    stage_counts = defaultdict(int)
    for eff in paper_effective_stages.values():
        stage_counts[eff] += 1

    # Filter if a specific stage tab is selected
    if stage is not None:
        papers = [p for p in all_papers if paper_effective_stages[p.id] == stage]
    else:
        papers = list(all_papers)

    # Sort: highest effective stage first, then net_votes desc, then newest first
    papers.sort(key=lambda p: (
        -paper_effective_stages[p.id],
        -p.net_votes,
        -(p.published_date.timestamp() if p.published_date else 0),
    ))

    # Attach effective stage to each paper object so the template can use it
    for p in papers:
        p._effective_stage = paper_effective_stages[p.id]

    user = request.session.get("user")

    return templates.TemplateResponse(
        "issues.html",
        {
            "request": request,
            "user": user,
            "view": "month_papers",
            "year": year,
            "month": month,
            "papers": papers,
            "stage": stage,
            "stage_counts": stage_counts,
            "total_month_papers": len(all_papers),
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
        Paper.status.in_(["published", "ai_screen_rejected"])
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
