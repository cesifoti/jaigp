"""Homepage and about page routes."""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from template_helpers import register_filters
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from models.database import get_db
from models.paper import Paper, STAGE_NAMES
from models.paper_vote import PaperVote
from models.user import User
from services.cache import cache, cache_result
import random
import json
from datetime import date

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)

# Tabs represent the LAST CLEARED milestone, not the next stage.
# Tab 0: Screened Out (review_stage=0, status=ai_screen_rejected)
# Tab 1: Screened (review_stage=1 — passed screening, awaiting endorsement)
# Tab 2: Endorsed (review_stage IN 2,3 — endorsed, possibly in AI review)
# Tab 3: AI Reviewed (review_stage=4 — cleared AI review)
# Tab 4: Peer Reviewed (review_stage=5 — cleared human peer review, future)
# Tab 5: Accepted (future)
TAB_LABELS = {
    0: "Screened Out",
    1: "Screened",
    2: "Endorsed",
    3: "AI Reviewed",
    4: "Peer Reviewed",
    5: "Accepted",
}

# Map tab number → review_stage values to query
TAB_TO_STAGES = {
    0: [0],
    1: [1],
    2: [2, 3],
    3: [4],
    4: [5],
    5: [],  # future
}

@router.get("/", response_class=HTMLResponse)
async def homepage(
    request: Request,
    db: Session = Depends(get_db),
    stage: int = Query(None, ge=-2, le=5),
    page: int = Query(1, ge=1),
    # Keep backward compat with old status param
    status: str = Query(None),
):
    """Homepage with papers filtered by review stage tabs (0-5).

    Tabs represent the last cleared milestone. Papers are sorted by
    stage_entered_at (most recent first) within each tab.
    """
    # Backward compatibility: map old status to tab
    if status == "under-review":
        stage = 3
    elif status == "submitted":
        stage = 1

    # Compute tab counts first (needed for default tab)
    tab_counts = {}
    tab_counts[0] = db.query(func.count(Paper.id)).filter(
        Paper.status == "ai_screen_rejected",
        Paper.review_stage == 0,
    ).scalar()
    for tab in range(1, 6):
        review_stages = TAB_TO_STAGES[tab]
        if review_stages:
            tab_counts[tab] = db.query(func.count(Paper.id)).filter(
                Paper.status == "published",
                Paper.review_stage.in_(review_stages),
            ).scalar()
        else:
            tab_counts[tab] = 0

    # Default to "All" tab
    if stage is None:
        stage = -2

    # Handle "All" tab (stage=-2) — all papers sorted by most advanced first
    if stage == -2:
        all_per_page = 9
        all_query = db.query(Paper).filter(Paper.status.in_(["published", "ai_screen_rejected"]))
        total_all = all_query.count()
        total_all_pages = max(1, (total_all + all_per_page - 1) // all_per_page)
        all_offset = (min(page, total_all_pages) - 1) * all_per_page

        papers = (
            all_query.order_by(
                Paper.review_stage.desc(),
                Paper.stage_entered_at.desc().nulls_last(),
                Paper.published_date.desc(),
            )
            .limit(all_per_page)
            .offset(all_offset)
            .all()
        )

        user = request.session.get("user")
        mottos = [
            "Exploring ideas at the edge of authorship.",
            "A journal for thinking out loud with machines.",
            "Rigorous enough to learn, humble enough to laugh.",
            "Where experiments count as contributions.",
            "All models are wrong; some papers are interesting.",
            "In curiosity we trust.",
            "Taking ideas seriously, not ourselves.",
            "We might be wrong. That's why we publish."
        ]
        import random
        motto = random.choice(mottos)

        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "papers": papers,
                "user": user,
                "motto": motto,
                "stage": -2,
                "stage_name": "All",
                "stage_counts": tab_counts,
                "tab_labels": TAB_LABELS,
                "page": min(page, total_all_pages),
                "total_pages": total_all_pages,
                "total_papers": total_all,
                "per_page": all_per_page
            }
        )

    # Handle "Recent Movements" tab (stage=-1)
    if stage == -1:
        from models.stage_history import StageHistory
        latest = (
            db.query(
                StageHistory.paper_id,
                func.max(StageHistory.created_at).label("last_action"),
            )
            .group_by(StageHistory.paper_id)
            .subquery()
        )
        papers = (
            db.query(Paper)
            .join(latest, Paper.id == latest.c.paper_id)
            .filter(Paper.status.in_(["published", "ai_screen_rejected"]))
            .order_by(latest.c.last_action.desc())
            .limit(9)
            .all()
        )

        user = request.session.get("user")
        mottos = [
            "Exploring ideas at the edge of authorship.",
            "A journal for thinking out loud with machines.",
            "Rigorous enough to learn, humble enough to laugh.",
            "Where experiments count as contributions.",
            "All models are wrong; some papers are interesting.",
            "In curiosity we trust.",
            "Taking ideas seriously, not ourselves.",
            "We might be wrong. That's why we publish."
        ]
        import random
        motto = random.choice(mottos)

        return templates.TemplateResponse(
            "home.html",
            {
                "request": request,
                "papers": papers,
                "user": user,
                "motto": motto,
                "stage": -1,
                "stage_name": "Recent Movements",
                "stage_counts": tab_counts,
                "tab_labels": TAB_LABELS,
                "page": 1,
                "total_pages": 1,
                "total_papers": len(papers),
                "per_page": 9
            }
        )

    # Handle stage=-2 (All) in the HTMX tab endpoint too
    if stage == -2:
        all_per_page = 9
        all_query = db.query(Paper).filter(Paper.status.in_(["published", "ai_screen_rejected"]))
        total_all = all_query.count()
        total_all_pages = max(1, (total_all + all_per_page - 1) // all_per_page)
        all_offset = (min(page, total_all_pages) - 1) * all_per_page
        papers = (
            all_query.order_by(Paper.review_stage.desc(), Paper.stage_entered_at.desc().nulls_last(), Paper.published_date.desc())
            .limit(all_per_page).offset(all_offset).all()
        )
        user = request.session.get("user")
        tab_counts = {}
        tab_counts[0] = db.query(func.count(Paper.id)).filter(
            Paper.status == "ai_screen_rejected", Paper.review_stage == 0).scalar()
        for tab in range(1, 6):
            rs = TAB_TO_STAGES[tab]
            tab_counts[tab] = db.query(func.count(Paper.id)).filter(
                Paper.status == "published", Paper.review_stage.in_(rs)).scalar() if rs else 0
        return templates.TemplateResponse("components/papers_tab_content.html", {
            "request": request, "papers": papers, "user": user,
            "stage": -2, "stage_name": "All", "stage_counts": tab_counts,
            "page": min(page, total_all_pages), "total_pages": total_all_pages, "total_papers": total_all,
        })

    stage = max(0, min(stage, 5))

    # Pagination settings
    per_page = 18
    offset = (page - 1) * per_page

    # Build query based on tab
    review_stages = TAB_TO_STAGES.get(stage, [])
    if stage == 0:
        query = db.query(Paper).filter(
            Paper.status == "ai_screen_rejected",
            Paper.review_stage == 0,
        )
    elif review_stages:
        query = db.query(Paper).filter(
            Paper.status == "published",
            Paper.review_stage.in_(review_stages),
        )
    else:
        # Empty future tab
        query = db.query(Paper).filter(Paper.id < 0)

    # Get total count for pagination
    total_papers = query.count()
    total_pages = max(1, (total_papers + per_page - 1) // per_page)

    # Sort by stage_entered_at desc (when they reached their current stage)
    # Fallback to published_date for papers without stage_entered_at
    papers = query.order_by(
        Paper.stage_entered_at.desc().nulls_last(),
        Paper.published_date.desc(),
    ).limit(per_page).offset(offset).all()

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
            "user": user,
            "motto": motto,
            "stage": stage,
            "stage_name": TAB_LABELS.get(stage, "Unknown"),
            "stage_counts": tab_counts,
            "tab_labels": TAB_LABELS,
            "page": page,
            "total_pages": total_pages,
            "total_papers": total_papers,
            "per_page": per_page
        }
    )

@router.get("/papers-tab", response_class=HTMLResponse)
async def papers_tab(
    request: Request,
    db: Session = Depends(get_db),
    stage: int = Query(1, ge=-2, le=5),
    page: int = Query(1, ge=1),
):
    """HTMX endpoint: returns just the papers content (banner + grid + pagination) for a tab."""
    per_page = 18
    offset = (page - 1) * per_page

    review_stages = TAB_TO_STAGES.get(stage, [])
    if stage == 0:
        query = db.query(Paper).filter(Paper.status == "ai_screen_rejected", Paper.review_stage == 0)
    elif review_stages:
        query = db.query(Paper).filter(Paper.status == "published", Paper.review_stage.in_(review_stages))
    else:
        query = db.query(Paper).filter(Paper.id < 0)

    total_papers = query.count()
    total_pages = max(1, (total_papers + per_page - 1) // per_page)

    papers = query.order_by(
        Paper.stage_entered_at.desc().nulls_last(),
        Paper.published_date.desc(),
    ).limit(per_page).offset(offset).all()

    user = request.session.get("user")

    # Compute tab counts for updating the active tab styling
    tab_counts = {}
    tab_counts[0] = db.query(func.count(Paper.id)).filter(
        Paper.status == "ai_screen_rejected", Paper.review_stage == 0).scalar()
    for tab in range(1, 6):
        rs = TAB_TO_STAGES[tab]
        tab_counts[tab] = db.query(func.count(Paper.id)).filter(
            Paper.status == "published", Paper.review_stage.in_(rs)).scalar() if rs else 0

    return templates.TemplateResponse(
        "components/papers_tab_content.html",
        {
            "request": request,
            "papers": papers,
            "user": user,
            "stage": stage,
            "stage_name": TAB_LABELS.get(stage, "Unknown"),
            "stage_counts": tab_counts,
            "page": page,
            "total_pages": total_pages,
            "total_papers": total_papers,
        }
    )


@router.get("/papers-tab/recent", response_class=HTMLResponse)
async def papers_tab_recent(
    request: Request,
    db: Session = Depends(get_db),
):
    """HTMX endpoint: returns papers with the most recent stage transitions."""
    from models.stage_history import StageHistory
    from sqlalchemy import distinct

    # Get the latest transition per paper (most recent action)
    # Subquery: for each paper, get the max created_at from stage_history
    from sqlalchemy.orm import aliased
    latest = (
        db.query(
            StageHistory.paper_id,
            func.max(StageHistory.created_at).label("last_action"),
        )
        .group_by(StageHistory.paper_id)
        .subquery()
    )

    # Join papers with their latest action, sorted by most recent
    papers = (
        db.query(Paper)
        .join(latest, Paper.id == latest.c.paper_id)
        .filter(Paper.status.in_(["published", "ai_screen_rejected"]))
        .order_by(latest.c.last_action.desc())
        .limit(9)
        .all()
    )

    user = request.session.get("user")

    return templates.TemplateResponse(
        "components/papers_tab_content.html",
        {
            "request": request,
            "papers": papers,
            "user": user,
            "stage": -1,  # special value for "recent"
            "stage_name": "Recent Movements",
            "stage_counts": {},
            "page": 1,
            "total_pages": 1,
            "total_papers": len(papers),
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

@router.get("/about/history", response_class=HTMLResponse)
async def history_page(request: Request, db: Session = Depends(get_db)):
    """History of JAIGP."""
    user = request.session.get("user")

    # Dynamic stats
    days_since_launch = (date.today() - date(2026, 2, 14)).days
    total_users = db.query(func.count(User.id)).scalar()
    total_papers = db.query(func.count(Paper.id)).filter(
        Paper.status.in_(["published", "ai_screen_rejected"])
    ).scalar()
    ai_reviewed_papers = db.query(func.count(Paper.id)).filter(
        Paper.review_stage >= 4,
        Paper.status == "published",
    ).scalar()

    # Total prompts from archive
    total_prompts = 0
    try:
        with open("/var/www/ai_journal/data/prompts_archive.json") as f:
            archive = json.load(f)
            total_prompts = archive.get("total_prompts", 0)
    except Exception:
        total_prompts = 0

    return templates.TemplateResponse("history.html", {
        "request": request,
        "user": user,
        "days_since_launch": days_since_launch,
        "total_users": total_users,
        "total_papers": total_papers,
        "ai_reviewed_papers": ai_reviewed_papers,
        "total_prompts": total_prompts,
    })


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
