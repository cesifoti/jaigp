"""Governance service — community-driven rule voting and enforcement.

All enforcement code reads rule values through get_rule_value() which
uses Redis caching for cross-worker coherence (5-min TTL).
"""
from datetime import datetime, timedelta
from collections import OrderedDict

from sqlalchemy import func
from sqlalchemy.orm import Session

from services.cache import CacheService

_CACHE_PREFIX = "gov:"
_CACHE_TTL = 300  # 5 minutes

# ── Badge helpers ───────────────────────────────────────────────────────────

BADGE_ORDER = ["new", "copper", "bronze", "silver", "gold"]


def badges_at_or_above(min_badge: str) -> list[str]:
    """Return all badges at or above the given minimum.

    >>> badges_at_or_above("bronze")
    ['bronze', 'silver', 'gold']
    >>> badges_at_or_above("any")
    ['new', 'copper', 'bronze', 'silver', 'gold']
    """
    if min_badge == "any":
        return list(BADGE_ORDER)
    try:
        idx = BADGE_ORDER.index(min_badge)
    except ValueError:
        return list(BADGE_ORDER)
    return BADGE_ORDER[idx:]


def _badge_rank(badge: str) -> int:
    """Rank a badge within BADGE_ORDER; unknown/None ranks as 'new' (lowest)."""
    try:
        return BADGE_ORDER.index(badge)
    except ValueError:
        return 0


def lowest_author_badge(paper_id: int, db: Session) -> str:
    """Return the lowest badge among a paper's human authors.

    The endorsement requirement is keyed to the *weakest* author: a paper is
    only as credentialed as its least-credentialed author. A missing/None or
    unrecognized badge counts as 'new' (most conservative), and a paper with
    no linked human authors also defaults to 'new'.

    NOTE: callers previously initialized the running minimum to 'new' and only
    lowered it — but 'new' is already the global minimum, so the result was
    pinned to 'new' for every paper (every paper wrongly required the
    'new author' endorsement count). This helper computes the true minimum.
    """
    from models.user import User
    from models.paper import PaperHumanAuthor
    authors = db.query(PaperHumanAuthor).join(
        User, User.id == PaperHumanAuthor.user_id
    ).filter(PaperHumanAuthor.paper_id == paper_id).all()
    lowest = None
    for a in authors:
        badge = a.user.badge if (a.user and a.user.badge in BADGE_ORDER) else "new"
        if lowest is None or _badge_rank(badge) < _badge_rank(lowest):
            lowest = badge
    return lowest or "new"


# ── Duration parser ─────────────────────────────────────────────────────────

_DURATION_MAP = {
    "24h": timedelta(hours=24),
    "48h": timedelta(hours=48),
    "72h": timedelta(hours=72),
    "1wk": timedelta(weeks=1),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "180d": timedelta(days=180),
    "1yr": timedelta(days=365),
    "5yr": timedelta(days=1825),
}


def _parse_duration(s: str) -> timedelta:
    """Convert a duration string like '48h' or '90d' to a timedelta."""
    if s in _DURATION_MAP:
        return _DURATION_MAP[s]
    # Fallback: try interpreting as days
    try:
        return timedelta(days=int(s))
    except (ValueError, TypeError):
        return timedelta(days=180)  # safe default


# ── Hardcoded defaults (fallback if DB is empty) ───────────────────────────

_DEFAULTS = {
    "cover_image_required": "optional",
    "concurrent_limit_new": "1",
    "concurrent_limit_copper": "1",
    "concurrent_limit_bronze": "2",
    "concurrent_limit_silver": "3",
    "concurrent_limit_gold": "5",
    "screening_cooldown_borderline": "90d",
    "screening_cooldown_rejection": "90d",
    "screening_block_3rd_rejection": "180d",
    "screening_borderline_streak": "3",
    "screening_max_rejections": "3",
    "endorser_min_badge_new": "bronze",
    "endorser_min_badge_copper": "bronze",
    "endorser_min_badge_bronze": "bronze",
    "endorser_min_badge_silver": "bronze",
    "endorser_min_badge_gold": "bronze",
    "endorsements_required_new": "2",
    "endorsements_required_copper": "1",
    "endorsements_required_bronze": "1",
    "endorsements_required_silver": "1",
    "endorsements_required_gold": "1",
    "ai_review_max_revisions": "3",
    "stage_deadline_days": "180",
    "extension_days": "20",
    "voting_frequency": "monthly",
    "voting_quorum": "10",
}


# ── Core value lookups ──────────────────────────────────────────────────────

def get_rule_value(slug: str, db: Session = None) -> str:
    """Get the current active value for a governance rule.

    Uses Redis cache with 5-min TTL for cross-worker coherence.
    Falls back to hardcoded defaults if DB is unavailable.
    """
    cache_key = f"{_CACHE_PREFIX}{slug}"
    cached = CacheService.get(cache_key)
    if cached is not None:
        return cached

    # Cache miss — query DB
    if db is None:
        from models.database import SessionLocal
        db = SessionLocal()
        try:
            return _fetch_and_cache(slug, db)
        finally:
            db.close()
    else:
        return _fetch_and_cache(slug, db)


def _fetch_and_cache(slug: str, db: Session) -> str:
    from models.governance import GovernanceRule
    rule = db.query(GovernanceRule).filter(GovernanceRule.slug == slug).first()
    value = rule.active_value if rule else _DEFAULTS.get(slug, "")
    CacheService.set(f"{_CACHE_PREFIX}{slug}", value, _CACHE_TTL)
    return value


def get_rule_value_int(slug: str, db: Session = None) -> int:
    """Get rule value as an integer."""
    return int(get_rule_value(slug, db) or 0)


def get_rule_value_timedelta(slug: str, db: Session = None) -> timedelta:
    """Get rule value as a timedelta."""
    return _parse_duration(get_rule_value(slug, db))


def invalidate_cache():
    """Clear all governance cache entries."""
    CacheService.clear_pattern(f"{_CACHE_PREFIX}*")


# ── Voting ──────────────────────────────────────────────────────────────────

def cast_vote(
    rule_id: int,
    user_id: int,
    chosen_option: str,
    db: Session,
    user_orcid: str = None,
    ip_address: str = None,
    user_agent: str = None,
) -> bool:
    """Cast or update a user's vote on a rule.

    Every action is logged to governance_vote_history for a full audit trail.
    """
    from models.governance import GovernanceRule, GovernanceVote, GovernanceVoteHistory

    rule = db.query(GovernanceRule).filter(GovernanceRule.id == rule_id).first()
    if not rule or not rule.is_votable:
        return False
    if chosen_option not in (rule.options_json or []):
        return False

    existing = db.query(GovernanceVote).filter(
        GovernanceVote.rule_id == rule_id,
        GovernanceVote.user_id == user_id,
    ).first()

    previous_option = None
    if existing:
        previous_option = existing.chosen_option
        if previous_option == chosen_option:
            return True  # no change
        existing.chosen_option = chosen_option
        existing.updated_at = datetime.utcnow()
        action = "changed"
    else:
        vote = GovernanceVote(
            rule_id=rule_id,
            user_id=user_id,
            chosen_option=chosen_option,
        )
        db.add(vote)
        action = "cast"

    # Write immutable audit record
    _, _, period_label = get_current_period(db)
    history = GovernanceVoteHistory(
        rule_id=rule_id,
        user_id=user_id,
        rule_slug=rule.slug,
        user_orcid=user_orcid,
        previous_option=previous_option,
        new_option=chosen_option,
        action=action,
        voting_period=period_label,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(history)

    db.commit()
    return True


def get_vote_distribution(rule_id: int, db: Session) -> dict[str, int]:
    """Count votes by option for a given rule. Returns {option: count}."""
    from models.governance import GovernanceVote
    rows = (
        db.query(GovernanceVote.chosen_option, func.count(GovernanceVote.id))
        .filter(GovernanceVote.rule_id == rule_id)
        .group_by(GovernanceVote.chosen_option)
        .all()
    )
    return {option: count for option, count in rows}


def get_user_votes(user_id: int, db: Session) -> dict[int, str]:
    """Return {rule_id: chosen_option} for a user's current votes."""
    from models.governance import GovernanceVote
    votes = db.query(GovernanceVote).filter(GovernanceVote.user_id == user_id).all()
    return {v.rule_id: v.chosen_option for v in votes}


def get_total_voters(rule_id: int, db: Session) -> int:
    """Total distinct voters for a rule."""
    from models.governance import GovernanceVote
    return db.query(GovernanceVote).filter(GovernanceVote.rule_id == rule_id).count()


# ── Rule catalog queries ────────────────────────────────────────────────────

SECTION_ORDER = ["submission", "screening", "endorsement", "ai_review", "deadlines", "governance"]
SECTION_TITLES = {
    "submission": "Submitting a Paper",
    "screening": "AI Screening (Stage 0 → 1)",
    "endorsement": "Endorsement (Stage 1 → 2)",
    "ai_review": "AI Review (Stage 2 → 3)",
    "deadlines": "Deadlines & Extensions",
    "governance": "Governance & Voting",
}


def get_all_rules(db: Session) -> list:
    """Return all rules ordered by section and display_order."""
    from models.governance import GovernanceRule
    return (
        db.query(GovernanceRule)
        .order_by(GovernanceRule.section, GovernanceRule.display_order)
        .all()
    )


def get_rules_by_section(db: Session) -> OrderedDict:
    """Return rules grouped by section in display order."""
    rules = get_all_rules(db)
    by_section = OrderedDict()
    for sec in SECTION_ORDER:
        section_rules = [r for r in rules if r.section == sec]
        if section_rules:
            by_section[sec] = section_rules
    return by_section


def get_rule_by_slug(slug: str, db: Session):
    """Fetch a single rule by slug."""
    from models.governance import GovernanceRule
    return db.query(GovernanceRule).filter(GovernanceRule.slug == slug).first()


# ── Voting period helpers ───────────────────────────────────────────────────

def get_current_period(db: Session = None) -> tuple[datetime, datetime, str]:
    """Return (period_start, period_end, period_label) for the current voting period."""
    freq = get_rule_value("voting_frequency", db) or "monthly"
    now = datetime.utcnow()

    if freq == "weekly":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        label = f"{start.strftime('%Y-W%W')}"
    elif freq == "biannual":
        half = 1 if now.month <= 6 else 2
        start = datetime(now.year, 1 if half == 1 else 7, 1)
        end = datetime(now.year, 7 if half == 1 else 1, 1) if half == 1 else datetime(now.year + 1, 1, 1)
        label = f"{now.year}-H{half}"
    elif freq == "annual":
        start = datetime(now.year, 1, 1)
        end = datetime(now.year + 1, 1, 1)
        label = f"{now.year}"
    else:  # monthly (default)
        start = datetime(now.year, now.month, 1)
        if now.month == 12:
            end = datetime(now.year + 1, 1, 1)
        else:
            end = datetime(now.year, now.month + 1, 1)
        label = now.strftime("%Y-%m")

    return start, end, label


def days_remaining_in_period(db: Session = None) -> int:
    """Days until the current voting period ends."""
    _, end, _ = get_current_period(db)
    delta = end - datetime.utcnow()
    return max(0, delta.days)


# ── Tally ───────────────────────────────────────────────────────────────────

def should_auto_tally(db: Session) -> bool:
    """Check if the previous period ended without a tally."""
    from models.governance import GovernanceTally
    _, _, current_label = get_current_period(db)

    # Check if there's a tally for the PREVIOUS period
    # If the current period just started and the previous one has no tally, we should tally
    freq = get_rule_value("voting_frequency", db) or "monthly"
    now = datetime.utcnow()

    if freq == "monthly":
        if now.month == 1:
            prev_label = f"{now.year - 1}-12"
        else:
            prev_label = f"{now.year}-{now.month - 1:02d}"
    elif freq == "weekly":
        prev_start = now - timedelta(days=now.weekday() + 7)
        prev_label = f"{prev_start.strftime('%Y-W%W')}"
    elif freq == "biannual":
        half = 1 if now.month <= 6 else 2
        prev_label = f"{now.year}-H{2 if half == 1 else 1}" if half == 2 else f"{now.year - 1}-H2"
    else:  # annual
        prev_label = f"{now.year - 1}"

    existing = db.query(GovernanceTally).filter(
        GovernanceTally.period_label == prev_label
    ).first()
    return existing is None


def tally_votes(db: Session, triggered_by: str = "auto") -> list[dict]:
    """Tally votes for the previous period. Returns summary of results."""
    from models.governance import GovernanceRule, GovernanceVote, GovernanceTally

    _, _, current_label = get_current_period(db)
    freq = get_rule_value("voting_frequency", db) or "monthly"
    now = datetime.utcnow()

    # Determine the period we're tallying (the one that just ended)
    if freq == "monthly":
        if now.month == 1:
            tally_label = f"{now.year - 1}-12"
        else:
            tally_label = f"{now.year}-{now.month - 1:02d}"
    elif freq == "weekly":
        prev_start = now - timedelta(days=now.weekday() + 7)
        tally_label = f"{prev_start.strftime('%Y-W%W')}"
    elif freq == "biannual":
        half = 1 if now.month <= 6 else 2
        tally_label = f"{now.year}-H{2 if half == 1 else 1}" if half == 2 else f"{now.year - 1}-H2"
    else:
        tally_label = f"{now.year - 1}"

    # Check if already tallied
    existing = db.query(GovernanceTally).filter(
        GovernanceTally.period_label == tally_label
    ).first()
    if existing:
        return []  # Already tallied

    quorum = get_rule_value_int("voting_quorum", db)
    votable_rules = db.query(GovernanceRule).filter(GovernanceRule.is_votable == True).all()
    results = []

    for rule in votable_rules:
        dist = get_vote_distribution(rule.id, db)
        total = sum(dist.values())
        met = total >= quorum

        winning = None
        if met and dist:
            # Winner = option with most votes. Ties: keep current value.
            max_count = max(dist.values())
            candidates = [opt for opt, cnt in dist.items() if cnt == max_count]
            if len(candidates) == 1:
                winning = candidates[0]
            elif rule.active_value in candidates:
                winning = rule.active_value  # tie goes to status quo
            else:
                winning = candidates[0]  # arbitrary tiebreak

        previous = rule.active_value
        new_val = winning if (met and winning) else previous

        # Update active value
        if new_val != previous:
            rule.active_value = new_val
            rule.updated_at = datetime.utcnow()

        # Record tally
        tally = GovernanceTally(
            rule_id=rule.id,
            period_label=tally_label,
            total_voters=total,
            quorum_required=quorum,
            quorum_met=met,
            results_json=dist,
            winning_option=winning,
            previous_value=previous,
            new_value=new_val,
        )
        db.add(tally)

        results.append({
            "slug": rule.slug,
            "title": rule.title,
            "total_voters": total,
            "quorum_met": met,
            "previous": previous,
            "new": new_val,
            "changed": new_val != previous,
        })

    db.commit()
    invalidate_cache()
    return results
