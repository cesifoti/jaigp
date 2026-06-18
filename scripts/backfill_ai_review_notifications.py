#!/usr/bin/env python3
"""One-time backfill: drop a 'ready for AI review' in-app notification for the
authors of already-endorsed (Stage 2) papers that we cannot reach by email.

Going forward this fires automatically when a paper reaches Stage 2 (see
services/stage_transition.advance_to_endorsed). This script only catches the
papers that advanced BEFORE that hook existed. Idempotent — re-running it
won't create duplicates (ensure_ai_review_ready_notification skips users who
already have an unread one).

USAGE:
    venv/bin/python scripts/backfill_ai_review_notifications.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.database import SessionLocal
from models.paper import Paper
from services.notification import notify_unreachable_authors_ready


def main():
    db = SessionLocal()
    try:
        papers = (
            db.query(Paper)
            .filter(
                Paper.review_stage == 2,
                Paper.status == "published",
                Paper.reviewer3_tracking_id.is_(None),
            )
            .order_by(Paper.id)
            .all()
        )
        total = 0
        for p in papers:
            n = notify_unreachable_authors_ready(p.id, db)
            if n:
                print(f"  paper {p.id}: notified {n} unreachable author(s)")
                total += n
        db.commit()
        print(f"\ndone: {total} notification(s) created across {len(papers)} Stage-2 paper(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
