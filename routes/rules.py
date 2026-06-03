"""Rules page with community governance voting."""
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.database import get_db
from template_helpers import register_filters
from services import governance as gov

router = APIRouter(tags=["rules"])
templates = Jinja2Templates(directory="templates")
templates.env = register_filters(templates.env)


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(request: Request, db: Session = Depends(get_db)):
    """Display the journal rules with governance voting widgets."""
    user = request.session.get("user")

    # Auto-tally if a period ended without being tallied
    if gov.should_auto_tally(db):
        gov.tally_votes(db, triggered_by="auto")

    rules_by_section = gov.get_rules_by_section(db)

    # Build vote distributions and user votes
    distributions = {}
    total_voters = {}
    user_votes = {}
    if user:
        user_votes = gov.get_user_votes(user["id"], db)

    for section_rules in rules_by_section.values():
        for rule in section_rules:
            if rule.is_votable:
                distributions[rule.id] = gov.get_vote_distribution(rule.id, db)
                total_voters[rule.id] = sum(distributions[rule.id].values())

    period_start, period_end, period_label = gov.get_current_period(db)
    days_left = gov.days_remaining_in_period(db)

    # Read screening prompt for display
    screening_prompt = _get_screening_prompt()

    return templates.TemplateResponse("rules.html", {
        "request": request,
        "user": user,
        "rules_by_section": rules_by_section,
        "section_titles": gov.SECTION_TITLES,
        "distributions": distributions,
        "total_voters": total_voters,
        "user_votes": user_votes,
        "period_label": period_label,
        "days_left": days_left,
        "screening_prompt": screening_prompt,
    })


@router.post("/rules/{rule_id}/vote", response_class=HTMLResponse)
async def vote_on_rule(
    rule_id: int,
    request: Request,
    chosen_option: str = Form(...),
    db: Session = Depends(get_db),
):
    """HTMX endpoint: cast/update vote, return updated widget."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Login required to vote")

    from models.governance import GovernanceRule
    rule = db.query(GovernanceRule).filter(GovernanceRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if not rule.is_votable:
        raise HTTPException(status_code=403, detail="This rule is not open for voting")
    if chosen_option not in (rule.options_json or []):
        raise HTTPException(status_code=400, detail="Invalid option for this rule")

    # Extract audit info
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    ua = (request.headers.get("user-agent") or "")[:500]
    ok = gov.cast_vote(
        rule_id, user["id"], chosen_option, db,
        user_orcid=user.get("orcid_id"),
        ip_address=ip,
        user_agent=ua,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Vote could not be recorded")

    # Read back the persisted vote so the widget reflects DB truth, not the request input
    current_votes = gov.get_user_votes(user["id"], db)
    user_vote = current_votes.get(rule_id)

    dist = gov.get_vote_distribution(rule_id, db)
    total = sum(dist.values())

    return templates.TemplateResponse("components/governance_vote_widget.html", {
        "request": request,
        "user": user,
        "rule": rule,
        "distribution": dist,
        "total_voters": total,
        "user_vote": user_vote,
    })


@router.post("/rules/tally", response_class=HTMLResponse)
async def manual_tally(request: Request, db: Session = Depends(get_db)):
    """Admin-only: manually trigger a vote tally."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401)

    from routes.admin import get_admin_role
    role = get_admin_role(user.get("orcid_id", ""), db)
    if not role:
        raise HTTPException(status_code=403, detail="Admin access required")

    results = gov.tally_votes(db, triggered_by="admin")
    changed = [r for r in results if r["changed"]]
    return HTMLResponse(
        f"<div class='p-4 bg-green-50 rounded-lg text-sm'>"
        f"Tally complete. {len(results)} rules processed, {len(changed)} changed.</div>"
    )


@router.get("/rules/{slug}/card", response_class=HTMLResponse)
async def rule_card(slug: str, request: Request, db: Session = Depends(get_db)):
    """Return a small HTML card for link unfurling in community posts."""
    rule = gov.get_rule_by_slug(slug, db)
    if not rule:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("components/governance_rule_preview.html", {
        "request": request,
        "rule": rule,
    })


def _get_screening_prompt() -> str:
    """Read the screening prompt text from the screening service."""
    try:
        from services.screening import _SCREENING_PROMPT
        return _SCREENING_PROMPT
    except Exception:
        return "(Screening prompt not available)"
