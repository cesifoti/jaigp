#!/usr/bin/env python3
"""Seed governance rules into the database. Idempotent — safe to run multiple times."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.database import SessionLocal
from models.governance import GovernanceRule

# ── Rule definitions ────────────────────────────────────────────────────────

RULES = [
    # ── NON-VOTABLE (display only) ──────────────────────────────────────
    {
        "slug": "orcid_required",
        "section": "submission",
        "title": "ORCID Required",
        "description": "All users must authenticate via ORCID iD. This links your real academic identity to all activity on JAIGP.",
        "options_json": None,
        "default_value": "yes",
        "is_votable": False,
        "display_order": 0,
    },
    {
        "slug": "email_verification",
        "section": "submission",
        "title": "Email Verification",
        "description": "After submitting a paper, you must verify your email address before the paper becomes publicly visible and enters screening.",
        "options_json": None,
        "default_value": "yes",
        "is_votable": False,
        "display_order": 1,
    },
    {
        "slug": "paper_details",
        "section": "submission",
        "title": "Paper Details",
        "description": "Submissions require a title, abstract, PDF, at least one AI author and one human prompter, and 1–5 subject categories.",
        "options_json": None,
        "default_value": "yes",
        "is_votable": False,
        "display_order": 2,
    },

    # ── SUBMISSION section ──────────────────────────────────────────────
    {
        "slug": "cover_image_required",
        "section": "submission",
        "title": "Cover Image",
        "description": "Whether a cover image (JPG/PNG) is required or optional when submitting a paper.",
        "options_json": ["optional", "required"],
        "default_value": "optional",
        "is_votable": True,
        "display_order": 3,
    },
    {
        "slug": "concurrent_limit_new",
        "section": "submission",
        "title": "Concurrent Papers (New badge)",
        "description": "Maximum active papers in the pipeline for authors with a New badge (0 ORCID works).",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "1",
        "is_votable": True,
        "display_group": "concurrent_limit",
        "display_order": 10,
    },
    {
        "slug": "concurrent_limit_copper",
        "section": "submission",
        "title": "Concurrent Papers (Copper badge)",
        "description": "Maximum active papers in the pipeline for authors with a Copper badge (1–5 ORCID works).",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "1",
        "is_votable": True,
        "display_group": "concurrent_limit",
        "display_order": 11,
    },
    {
        "slug": "concurrent_limit_bronze",
        "section": "submission",
        "title": "Concurrent Papers (Bronze badge)",
        "description": "Maximum active papers in the pipeline for authors with a Bronze badge (6–24 ORCID works).",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "2",
        "is_votable": True,
        "display_group": "concurrent_limit",
        "display_order": 12,
    },
    {
        "slug": "concurrent_limit_silver",
        "section": "submission",
        "title": "Concurrent Papers (Silver badge)",
        "description": "Maximum active papers in the pipeline for authors with a Silver badge (25–49 ORCID works).",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "3",
        "is_votable": True,
        "display_group": "concurrent_limit",
        "display_order": 13,
    },
    {
        "slug": "concurrent_limit_gold",
        "section": "submission",
        "title": "Concurrent Papers (Gold badge)",
        "description": "Maximum active papers in the pipeline for authors with a Gold badge (50+ ORCID works).",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "5",
        "is_votable": True,
        "display_group": "concurrent_limit",
        "display_order": 14,
    },

    # ── SCREENING section ───────────────────────────────────────────────
    {
        "slug": "screening_cooldown_borderline",
        "section": "screening",
        "title": "Cooldown After Borderline Strike",
        "description": "How long a submitter must wait after 3 consecutive borderline screening results.",
        "options_json": ["24h", "48h", "72h", "1wk", "30d", "90d"],
        "default_value": "90d",
        "is_votable": True,
        "display_order": 0,
    },
    {
        "slug": "screening_cooldown_rejection",
        "section": "screening",
        "title": "Cooldown After Hard Rejection",
        "description": "How long a submitter must wait after a hard screening rejection (1st or 2nd offense).",
        "options_json": ["24h", "48h", "72h", "1wk", "30d", "90d"],
        "default_value": "90d",
        "is_votable": True,
        "display_order": 1,
    },
    {
        "slug": "screening_block_3rd_rejection",
        "section": "screening",
        "title": "Block After Repeated Rejections",
        "description": "How long a submitter is blocked after reaching the maximum number of hard rejections.",
        "options_json": ["30d", "90d", "180d", "1yr", "5yr"],
        "default_value": "180d",
        "is_votable": True,
        "display_order": 2,
    },
    {
        "slug": "screening_borderline_streak",
        "section": "screening",
        "title": "Borderline Streak Threshold",
        "description": "How many consecutive borderline results trigger a cooldown strike.",
        "options_json": ["2", "3", "4", "5"],
        "default_value": "3",
        "is_votable": True,
        "display_order": 3,
    },
    {
        "slug": "screening_max_rejections",
        "section": "screening",
        "title": "Max Rejections Before Long Block",
        "description": "How many lifetime hard rejections trigger the long block period.",
        "options_json": ["2", "3", "4", "5"],
        "default_value": "3",
        "is_votable": True,
        "display_order": 4,
    },

    # ── ENDORSEMENT section ─────────────────────────────────────────────
    # Who can endorse (per author badge)
    {
        "slug": "endorser_min_badge_new",
        "section": "endorsement",
        "title": "Min Endorser Badge (New authors)",
        "description": "Minimum badge required to endorse papers by New badge authors.",
        "options_json": ["any", "copper", "bronze", "silver", "gold"],
        "default_value": "bronze",
        "is_votable": True,
        "display_group": "endorser_min_badge",
        "display_order": 0,
    },
    {
        "slug": "endorser_min_badge_copper",
        "section": "endorsement",
        "title": "Min Endorser Badge (Copper authors)",
        "description": "Minimum badge required to endorse papers by Copper badge authors.",
        "options_json": ["any", "copper", "bronze", "silver", "gold"],
        "default_value": "bronze",
        "is_votable": True,
        "display_group": "endorser_min_badge",
        "display_order": 1,
    },
    {
        "slug": "endorser_min_badge_bronze",
        "section": "endorsement",
        "title": "Min Endorser Badge (Bronze authors)",
        "description": "Minimum badge required to endorse papers by Bronze badge authors.",
        "options_json": ["any", "copper", "bronze", "silver", "gold"],
        "default_value": "bronze",
        "is_votable": True,
        "display_group": "endorser_min_badge",
        "display_order": 2,
    },
    {
        "slug": "endorser_min_badge_silver",
        "section": "endorsement",
        "title": "Min Endorser Badge (Silver authors)",
        "description": "Minimum badge required to endorse papers by Silver badge authors.",
        "options_json": ["any", "copper", "bronze", "silver", "gold"],
        "default_value": "bronze",
        "is_votable": True,
        "display_group": "endorser_min_badge",
        "display_order": 3,
    },
    {
        "slug": "endorser_min_badge_gold",
        "section": "endorsement",
        "title": "Min Endorser Badge (Gold authors)",
        "description": "Minimum badge required to endorse papers by Gold badge authors.",
        "options_json": ["any", "copper", "bronze", "silver", "gold"],
        "default_value": "bronze",
        "is_votable": True,
        "display_group": "endorser_min_badge",
        "display_order": 4,
    },
    # How many endorsements (per author badge)
    {
        "slug": "endorsements_required_new",
        "section": "endorsement",
        "title": "Endorsements Required (New authors)",
        "description": "Number of endorsements needed for papers by New badge authors.",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "2",
        "is_votable": True,
        "display_group": "endorsements_required",
        "display_order": 10,
    },
    {
        "slug": "endorsements_required_copper",
        "section": "endorsement",
        "title": "Endorsements Required (Copper authors)",
        "description": "Number of endorsements needed for papers by Copper badge authors.",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "1",
        "is_votable": True,
        "display_group": "endorsements_required",
        "display_order": 11,
    },
    {
        "slug": "endorsements_required_bronze",
        "section": "endorsement",
        "title": "Endorsements Required (Bronze authors)",
        "description": "Number of endorsements needed for papers by Bronze badge authors.",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "1",
        "is_votable": True,
        "display_group": "endorsements_required",
        "display_order": 12,
    },
    {
        "slug": "endorsements_required_silver",
        "section": "endorsement",
        "title": "Endorsements Required (Silver authors)",
        "description": "Number of endorsements needed for papers by Silver badge authors.",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "1",
        "is_votable": True,
        "display_group": "endorsements_required",
        "display_order": 13,
    },
    {
        "slug": "endorsements_required_gold",
        "section": "endorsement",
        "title": "Endorsements Required (Gold authors)",
        "description": "Number of endorsements needed for papers by Gold badge authors.",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "1",
        "is_votable": True,
        "display_group": "endorsements_required",
        "display_order": 14,
    },

    # ── AI REVIEW section ───────────────────────────────────────────────
    {
        "slug": "ai_review_max_revisions",
        "section": "ai_review",
        "title": "Max AI Review Revision Attempts",
        "description": "How many revision attempts an author gets during AI review before the paper is desk-rejected back to Stage 1.",
        "options_json": ["0", "1", "2", "3", "4", "5"],
        "default_value": "3",
        "is_votable": True,
        "display_order": 0,
    },

    # ── DEADLINES section ───────────────────────────────────────────────
    {
        "slug": "stage_deadline_days",
        "section": "deadlines",
        "title": "Stage Deadline",
        "description": "How many days a paper can remain at a single pipeline stage before being flagged as stale.",
        "options_json": ["90", "180", "365"],
        "default_value": "180",
        "is_votable": True,
        "display_order": 0,
    },
    {
        "slug": "extension_days",
        "section": "deadlines",
        "title": "Extension Duration",
        "description": "How many additional days are granted when an extension request is approved.",
        "options_json": ["10", "20", "30", "60"],
        "default_value": "20",
        "is_votable": True,
        "display_order": 1,
    },

    # ── GOVERNANCE section (meta-rules) ─────────────────────────────────
    {
        "slug": "voting_frequency",
        "section": "governance",
        "title": "Voting Tally Frequency",
        "description": "How often votes are tallied and rule changes take effect.",
        "options_json": ["weekly", "monthly", "biannual", "annual"],
        "default_value": "monthly",
        "is_votable": True,
        "display_order": 0,
    },
    {
        "slug": "voting_quorum",
        "section": "governance",
        "title": "Minimum Quorum",
        "description": "Minimum number of voters required for a tally to change a rule's active value.",
        "options_json": ["5", "10", "15", "20", "25", "30", "35", "40", "45", "50"],
        "default_value": "10",
        "is_votable": True,
        "display_order": 1,
    },
]


def seed_governance_rules(db=None):
    """Insert governance rules if the table is empty. Idempotent."""
    close_after = False
    if db is None:
        db = SessionLocal()
        close_after = True

    try:
        existing = db.query(GovernanceRule).count()
        if existing > 0:
            print(f"Governance rules already seeded ({existing} rows). Skipping.")
            return

        for rule_data in RULES:
            rule = GovernanceRule(
                slug=rule_data["slug"],
                section=rule_data["section"],
                title=rule_data["title"],
                description=rule_data.get("description", ""),
                options_json=rule_data.get("options_json"),
                default_value=rule_data["default_value"],
                active_value=rule_data["default_value"],
                is_votable=rule_data.get("is_votable", True),
                display_group=rule_data.get("display_group"),
                display_order=rule_data.get("display_order", 0),
            )
            db.add(rule)

        db.commit()
        print(f"Seeded {len(RULES)} governance rules.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding governance rules: {e}")
        raise
    finally:
        if close_after:
            db.close()


if __name__ == "__main__":
    seed_governance_rules()
