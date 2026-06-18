#!/usr/bin/env python3
"""Nudge authors whose paper is Endorsed (Stage 2) and ready for AI review.

USAGE:
    sudo venv/bin/python scripts/send_ai_review_ready.py --dry-run
    sudo venv/bin/python scripts/send_ai_review_ready.py --send \
         [--limit N] [--only EMAIL]

--dry-run   render the email + recipient list to stdout, NO sends
--send      actually send via SMTP
--limit N   only process the first N recipients
--only X    only send to address X (case-insensitive; useful for self-test)

Audience: the human author of every paper at review_stage 2 (Endorsed) that
has NOT yet been submitted to Reviewer3 (reviewer3_tracking_id IS NULL). Each
recipient gets a link to THEIR paper, where the "Submit for AI Review" button
lives. One email per paper, to the lowest-order author with a reachable email.

Paces sends at 1.5s/email so the Gmail relay doesn't trip rate limits.
Reply-To is contact@jaigp.org so replies reach the shared inbox.
"""
import argparse
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models.database import SessionLocal
from sqlalchemy import text

REPLY_TO = "contact@jaigp.org"
THROTTLE_SECONDS = 1.5

SUBJECT = "Your Paper is Ready for AI review!"

BODY_TEXT = """Hi {name},

Good news — your paper "{title}" has been endorsed and is now ready for AI
review, the next step in the JAIGP pipeline.

This is the stage where your work gets read closely: a panel of AI reviewers
reads the full paper and returns detailed, structured feedback you can use to
strengthen it before it moves on to human peer review.

You're one click away. Open your paper and press "Submit for AI Review":

  {paper_url}

(You'll be asked to sign in with ORCID if you aren't already.)

We're glad to have your work in the journal, and we're looking forward to
seeing it advance.

— The JAIGP team
https://jaigp.org

(Prefer not to get these? Just reply and we'll leave you be.)
"""

BODY_HTML = """\
<!doctype html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #1e293b; max-width: 620px; margin: 0 auto; padding: 20px;">

<p>Hi {name},</p>

<p><strong>Good news &mdash; your paper has been endorsed and is now ready for
AI review</strong>, the next step in the JAIGP pipeline.</p>

<p style="background:#f1f5f9; border-left:4px solid #7c3aed; padding:12px 15px; margin:18px 0;">
{title}</p>

<p>This is the stage where your work gets read closely: a panel of AI reviewers
reads the full paper and returns detailed, structured feedback you can use to
strengthen it before it moves on to human peer review.</p>

<p><strong>You're one click away.</strong> Open your paper and press
&ldquo;Submit for AI Review&rdquo;:</p>

<p style="text-align:center; margin: 26px 0;">
  <a href="{paper_url}" style="display:inline-block; padding:12px 24px; background:#7c3aed; color:#ffffff; text-decoration:none; border-radius:6px; font-weight:600;">View Your Paper &rarr;</a>
</p>

<p style="font-size:13px; color:#64748b;">You'll be asked to sign in with ORCID
if you aren't already. Direct link:
<a href="{paper_url}" style="color:#2563eb;">{paper_url}</a></p>

<p>We're glad to have your work in the journal, and we're looking forward to
seeing it advance.</p>

<p>&mdash; The JAIGP team<br/>
<a href="https://jaigp.org" style="color:#2563eb;">https://jaigp.org</a></p>

<p style="color:#64748b; font-size: 13px;">Prefer not to get these? Just reply
and we'll leave you be.</p>

</body></html>
"""


def get_recipients(db, limit=None, only=None):
    """One row per Stage-2, not-yet-AI-reviewed paper, sent to its lowest-order
    author with a reachable email. Returns (paper_id, title, name, to_addr)."""
    sql = text("""
        SELECT p.id, p.title, u.name, pha.author_order,
               COALESCE(u.email, ue.email, p.submitter_email) AS to_addr
        FROM papers p
        JOIN paper_human_authors pha ON pha.paper_id = p.id
        JOIN users u ON u.id = pha.user_id
        LEFT JOIN LATERAL (
            SELECT email FROM user_emails
            WHERE user_id = u.id
            ORDER BY is_primary DESC, verified_at DESC NULLS LAST
            LIMIT 1
        ) ue ON true
        WHERE p.review_stage = 2
          AND p.status = 'published'
          AND p.reviewer3_tracking_id IS NULL
          AND COALESCE(u.email, ue.email, p.submitter_email) IS NOT NULL
        ORDER BY p.id, pha.author_order
    """)
    rows = db.execute(sql).fetchall()
    seen = set()
    recips = []
    for pid, title, name, _order, to_addr in rows:
        if pid in seen:
            continue  # keep only the first reachable author per paper
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
    first = name.split()[0] if name and name != "there" else "there"
    ctx = dict(name=first, title=title, paper_url=paper_url)
    return BODY_TEXT.format(**ctx), BODY_HTML.format(**ctx)


def send_one(server, to_addr, name, text_body, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = SUBJECT
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>"
    msg["To"] = f"{name} <{to_addr}>" if name and name != "there" else to_addr
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
        pid, title, name, to_addr = recips[0]
        paper_url = f"https://jaigp.org/paper/{pid}"
        text_body, _ = render(name, title, paper_url)
        print(f"\n--- preview for {to_addr} (paper {pid}) ---\n")
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
