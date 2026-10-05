#!/usr/bin/env python3
"""Nudge authors whose paper is at Stage 3 (AI Reviewed) with a "needs revision"
outcome that they haven't resubmitted — and tell them the resubmission bug
(NameError, live Jul 11 - Oct 5 2026, fixed in commit 9a0f5ca) is fixed.

USAGE:
    sudo venv/bin/python scripts/send_resubmission_fixed.py --dry-run
    sudo venv/bin/python scripts/send_resubmission_fixed.py --send \
         [--limit N] [--only EMAIL]

--dry-run   render the email + recipient list to stdout, NO sends
--send      actually send via SMTP
--limit N   only process the first N recipients
--only X    only send to address X (case-insensitive; useful for self-test)

Audience: the human author of every paper whose LATEST AI review (in the
paper's current review_cycle) is completed, not approved, not desk-rejected,
and hasn't exhausted all revision rounds — i.e. the author owes a revision.
One email per paper, to the lowest-order author with a reachable email.

Paces sends at 1.5s/email so the Gmail relay doesn't trip rate limits.
Reply-To is contact@jaigp.org so replies reach the shared inbox.
"""
import argparse
import re
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models.database import SessionLocal
from services.governance import get_rule_value_int
from sqlalchemy import text

REPLY_TO = "contact@jaigp.org"
THROTTLE_SECONDS = 1.5

SUBJECT = "Your JAIGP revision can now be submitted"

BODY_TEXT = """Hi {name},

Your paper "{title}" received AI review feedback that requires some revision
before it can move forward in JAIGP's pipeline.

If you tried to submit your revised manuscript and ran into an error, that's
now fixed — we found and resolved a bug in our resubmission system that was
blocking every revision upload.

To continue: open your paper, go to the AI Review tab, and upload your
revised manuscript along with a short response letter addressing the
reviewers' comments.

  {paper_url}

(You'll be asked to sign in with ORCID if you aren't already.)

Sorry for the trouble, and thank you for your patience — we're looking
forward to seeing your paper move forward.

— The JAIGP team
https://jaigp.org

(Prefer not to get these? Just reply and we'll leave you be.)
"""

BODY_HTML = """\
<!doctype html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #1e293b; max-width: 620px; margin: 0 auto; padding: 20px;">

<p>Hi {name},</p>

<p>Your paper received AI review feedback that requires some revision before
it can move forward in JAIGP's pipeline.</p>

<p style="background:#f1f5f9; border-left:4px solid #7c3aed; padding:12px 15px; margin:18px 0;">
{title}</p>

<p><strong>If you tried to submit your revised manuscript and ran into an
error, that's now fixed</strong> &mdash; we found and resolved a bug in our
resubmission system that was blocking every revision upload.</p>

<p>To continue: open your paper, go to the AI Review tab, and upload your
revised manuscript along with a short response letter addressing the
reviewers&rsquo; comments.</p>

<p style="text-align:center; margin: 26px 0;">
  <a href="{paper_url}" style="display:inline-block; padding:12px 24px; background:#7c3aed; color:#ffffff; text-decoration:none; border-radius:6px; font-weight:600;">View Your Paper &rarr;</a>
</p>

<p style="font-size:13px; color:#64748b;">You'll be asked to sign in with ORCID
if you aren't already. Direct link:
<a href="{paper_url}" style="color:#2563eb;">{paper_url}</a></p>

<p>Sorry for the trouble, and thank you for your patience &mdash; we're
looking forward to seeing your paper move forward.</p>

<p>&mdash; The JAIGP team<br/>
<a href="https://jaigp.org" style="color:#2563eb;">https://jaigp.org</a></p>

<p style="color:#64748b; font-size: 13px;">Prefer not to get these? Just reply
and we'll leave you be.</p>

</body></html>
"""

_ORCID_RE = re.compile(r'^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$')


def get_recipients(db, limit=None, only=None):
    """One row per Stage-3 paper whose latest review (this cycle) needs a
    revision that hasn't been resubmitted, sent to its lowest-order author
    with a reachable email. Returns (paper_id, title, name, to_addr)."""
    sql = text("""
        SELECT p.id, p.title, u.name, pha.author_order,
               COALESCE(u.email, ue.email, p.submitter_email) AS to_addr,
               r.review_round
        FROM papers p
        JOIN ai_reviews r ON r.paper_id = p.id AND r.review_cycle = p.review_cycle
        JOIN paper_human_authors pha ON pha.paper_id = p.id
        JOIN users u ON u.id = pha.user_id
        LEFT JOIN LATERAL (
            SELECT email FROM user_emails
            WHERE user_id = u.id
            ORDER BY is_primary DESC, verified_at DESC NULLS LAST
            LIMIT 1
        ) ue ON true
        WHERE p.review_stage = 3
          AND p.status = 'published'
          AND r.status = 'completed'
          AND r.approved = false
          AND r.desk_rejected = false
          AND r.id = (
              SELECT id FROM ai_reviews r2
              WHERE r2.paper_id = p.id AND r2.review_cycle = p.review_cycle
              ORDER BY r2.created_at DESC LIMIT 1
          )
          AND COALESCE(u.email, ue.email, p.submitter_email) IS NOT NULL
        ORDER BY p.id, pha.author_order
    """)
    max_rounds = get_rule_value_int("ai_review_max_revisions", db) + 1
    rows = db.execute(sql).fetchall()
    seen = set()
    recips = []
    for pid, title, name, _order, to_addr, review_round in rows:
        if pid in seen:
            continue  # keep only the first reachable author per paper
        if review_round >= max_rounds:
            continue  # exhausted — desk_reject_to_stage1 should have moved these already, but don't nudge if not
        if not to_addr or "@" not in to_addr:
            continue
        seen.add(pid)
        recips.append((pid, title, name or "there", to_addr.strip()))
    if only:
        recips = [r for r in recips if r[3].lower() == only.lower()]
    if limit:
        recips = recips[:limit]
    return recips


def render(name, title, paper_url):
    # Some users never set a display name, leaving their ORCID ID stored as
    # name — don't greet them with "Hi 0009-0003-9316-9939,".
    usable = name and name != "there" and not _ORCID_RE.match(name)
    first = name.split()[0] if usable else "there"
    ctx = dict(name=first, title=title, paper_url=paper_url)
    return BODY_TEXT.format(**ctx), BODY_HTML.format(**ctx)


def send_one(server, to_addr, name, text_body, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = SUBJECT
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>"
    usable_name = name and name != "there" and not _ORCID_RE.match(name)
    msg["To"] = f"{name} <{to_addr}>" if usable_name else to_addr
    msg["Reply-To"] = REPLY_TO
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    server.sendmail(config.SMTP_FROM_EMAIL, [to_addr], msg.as_string())


def main():
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--dry-run", action="store_true")
    grp.add_argument("--send", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", type=str, default=None)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        recips = get_recipients(db, limit=args.limit, only=args.only)
    finally:
        db.close()

    print(f"recipients:  {len(recips)}")
    if not recips:
        print("nothing to do")
        return

    if args.dry_run:
        for pid, title, name, to_addr in recips:
            paper_url = f"https://jaigp.org/paper/{pid}"
            text_body, _ = render(name, title, paper_url)
            print(f"\n=== preview for {to_addr} (paper {pid}) ===\n")
            print(f"From:     {config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>")
            print(f"Reply-To: {REPLY_TO}")
            print(f"Subject:  {SUBJECT}")
            print(f"\n{text_body}")
        print(f"\n--- recipient list ({len(recips)} total) ---")
        for pid, title, name, to_addr in recips:
            print(f"  paper {pid:>4}  {to_addr:<32}  {name:<20}  {title[:45]}")
        return

    # --send
    if not config.SMTP_USER or not config.SMTP_PASSWORD:
        sys.exit("ERROR: SMTP_USER / SMTP_PASSWORD not set in .env")
    print(f"\nconnecting to {config.SMTP_HOST}:{config.SMTP_PORT}…")
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        print(f"  authenticated as {config.SMTP_USER}\n")
        sent = 0
        failed = []
        for i, (pid, title, name, to_addr) in enumerate(recips, 1):
            paper_url = f"https://jaigp.org/paper/{pid}"
            text_body, html_body = render(name, title, paper_url)
            try:
                send_one(server, to_addr, name, text_body, html_body)
                sent += 1
                print(f"  [{i}/{len(recips)}] sent  →  {to_addr} (paper {pid})")
            except Exception as e:
                failed.append((to_addr, str(e)))
                print(f"  [{i}/{len(recips)}] FAIL  →  {to_addr}: {e}")
            if i < len(recips):
                time.sleep(THROTTLE_SECONDS)

    print(f"\ndone: {sent} sent, {len(failed)} failed")
    if failed:
        print("failures:")
        for addr, err in failed:
            print(f"  {addr}: {err}")


if __name__ == "__main__":
    main()
