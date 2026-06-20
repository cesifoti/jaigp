#!/usr/bin/env python3
"""Recover submissions stranded in `pending_verification` by the old
verify-link 500 bug. Regenerates each paper's verification token and emails the
author a fresh, working link so they can push the paper into the pipeline.

Duplicate submissions (same title from the same author) are collapsed to the
lowest id; the extras are reported, not emailed and not deleted.

USAGE:
    venv/bin/python scripts/rescue_pending_verification.py --dry-run
    sudo venv/bin/python scripts/rescue_pending_verification.py --send
"""
import argparse
import sys
import time
import uuid
import re
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models.database import SessionLocal
from models.paper import Paper, PaperHumanAuthor
from models.user import User
from services.email import email_service

THROTTLE_SECONDS = 1.5


_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def _clean_name(name):
    """Reject empty or ORCID-iD-as-name placeholders."""
    name = (name or "").strip()
    if not name or _ORCID_RE.match(name):
        return None
    return name


def author_name(paper, db):
    a = (
        db.query(PaperHumanAuthor)
        .filter(PaperHumanAuthor.paper_id == paper.id, PaperHumanAuthor.user_id.isnot(None))
        .order_by(PaperHumanAuthor.author_order)
        .first()
    )
    if a:
        u = db.query(User).filter(User.id == a.user_id).first()
        if u and _clean_name(u.name):
            return _clean_name(u.name)
    u = db.query(User).filter(User.email == paper.submitter_email).first()
    if u and _clean_name(u.name):
        return _clean_name(u.name)
    return "there"


def build_plan(db):
    papers = (
        db.query(Paper)
        .filter(Paper.status == "pending_verification")
        .order_by(Paper.submitter_email, Paper.id)
        .all()
    )
    groups = OrderedDict()
    for p in papers:
        if not p.submitter_email or "@" not in p.submitter_email:
            continue
        groups.setdefault(p.submitter_email, []).append(p)

    plan = []
    for email, ps in groups.items():
        seen, keep, skipped = {}, [], []
        for p in sorted(ps, key=lambda x: x.id):
            key = (p.title or "").strip().lower()
            if key in seen:
                skipped.append(p)
            else:
                seen[key] = p
                keep.append(p)
        plan.append((email, author_name(keep[0], db), keep, skipped))
    return plan


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--send", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    plan = build_plan(db)
    print(f"link base (config.BASE_URL): {config.BASE_URL}")
    print(f"authors to contact: {len(plan)}\n")
    for email, name, keep, skipped in plan:
        print(f"  {email}  ({name})")
        for p in keep:
            print(f"      rescue  paper {p.id}: {p.title[:55]}")
        for p in skipped:
            print(f"      DUP-skip paper {p.id}: {p.title[:55]}  (duplicate title)")

    if args.dry_run:
        print("\n(dry run — no tokens regenerated, no email sent)")
        db.close()
        return

    print()
    sent, failed = 0, []
    for email, name, keep, skipped in plan:
        items = []
        for p in keep:
            tok = uuid.uuid4().hex
            p.verification_token = tok
            items.append((p.title, f"{config.BASE_URL}/submit/verify/{tok}"))
        db.commit()
        try:
            email_service.send_submission_recovery(email, name, items)
            sent += 1
            print(f"  sent → {email} ({len(items)} paper(s))")
        except Exception as e:
            failed.append((email, str(e)))
            print(f"  FAIL → {email}: {e}")
        time.sleep(THROTTLE_SECONDS)
    print(f"\ndone: {sent} sent, {len(failed)} failed")
    db.close()


if __name__ == "__main__":
    main()
