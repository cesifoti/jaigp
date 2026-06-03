#!/usr/bin/env python3
"""End-of-May reminder to all users: vote on the rules before the period closes.

The current voting period (2026-05) closes June 1 00:00; whatever wins sets the
rules for June. Many rules are one voter short of the 10-voter quorum, so this
nudge leans on "your single vote tips it over the line."

USAGE:
    sudo venv/bin/python scripts/send_june_rules_vote.py --dry-run
    sudo venv/bin/python scripts/send_june_rules_vote.py --send \
         [--limit N] [--only EMAIL]

--dry-run   render preview + recipient list, NO sends
--send      actually send via SMTP
--limit N   only process the first N recipients
--only X    only send to address X (case-insensitive; useful for self-test)

Paced at 1.5s/email so the Gmail SMTP relay doesn't trip rate limits.
Reply-To is cesifoti@gmail.com so the "just reply" unsubscribe path reaches a human.
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
from services import governance as gov

REPLY_TO = "cesifoti@gmail.com"
RULES_URL = "https://jaigp.org/rules"
THROTTLE_SECONDS = 1.5

SUBJECT = "One vote away — help set JAIGP's rules for June"

BODY_TEXT = """Hi {name},

The community votes on JAIGP's rules every month — and this month's voting
closes at the end of May. Whatever wins by then becomes the rule for June.

Here's the exciting part: we're incredibly close. Right now, ten rules are
sitting at 9 votes — just one vote short of the 10-voter quorum they need to
count. That means your single vote could be the one that pushes them over the
line and actually changes how the journal runs.

It takes about a minute:

  1. Go to {rules_url}
  2. Log in with ORCID
  3. Click an option on any rule — your vote saves instantly

You can vote on as many or as few as you like, and change your mind any time
before the month ends.

A few of the rules one vote away from being decided:
  • How many endorsements a paper needs (at each author level)
  • The cooldown after a screening rejection
  • When a submitter gets blocked after repeated rejections

If you've been meaning to have a say in how JAIGP works, this is the moment —
and you'd be joining a group small enough that your vote genuinely tips the
balance.

Vote before May 31 ends → {rules_url}

Thanks for being part of this,

— The JAIGP Team
JAIGP — Journal for AI Generated Papers
https://jaigp.org

Prefer not to get these? Just reply and we'll take you off the list.
"""

BODY_HTML = """\
<!doctype html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #1e293b; max-width: 620px; margin: 0 auto; padding: 20px;">

<p>Hi {name},</p>

<p>The community votes on JAIGP's rules every month &mdash; and
<strong>this month's voting closes at the end of May.</strong> Whatever wins by
then becomes the rule for June.</p>

<p>Here's the exciting part: <strong>we're incredibly close.</strong> Right now,
<em>ten</em> rules are sitting at 9 votes &mdash; just <strong>one vote
short</strong> of the 10-voter quorum they need to count. That means your single
vote could be the one that pushes them over the line and actually changes how
the journal runs.</p>

<p>It takes about a minute:</p>
<ol style="padding-left: 22px;">
  <li>Go to <a href="{rules_url}" style="color:#2563eb;">{rules_url}</a></li>
  <li>Log in with ORCID</li>
  <li>Click an option on any rule &mdash; your vote saves instantly</li>
</ol>

<p>You can vote on as many or as few as you like, and change your mind any time
before the month ends.</p>

<p>A few of the rules one vote away from being decided:</p>
<ul style="padding-left: 22px;">
  <li>How many endorsements a paper needs (at each author level)</li>
  <li>The cooldown after a screening rejection</li>
  <li>When a submitter gets blocked after repeated rejections</li>
</ul>

<p>If you've been meaning to have a say in how JAIGP works, <strong>this is the
moment</strong> &mdash; and you'd be joining a group small enough that your vote
genuinely tips the balance.</p>

<p style="font-size: 16px;"><strong>Vote before May 31 ends &rarr;
<a href="{rules_url}" style="color:#2563eb;">{rules_url}</a></strong></p>

<p>Thanks for being part of this,</p>

<p>&mdash; The JAIGP Team<br/>
<span style="color:#64748b;">JAIGP &mdash; Journal for AI Generated Papers</span><br/>
<a href="https://jaigp.org" style="color:#2563eb;">https://jaigp.org</a></p>

<p style="color:#64748b; font-size: 13px;">Prefer not to get these? Just reply
and we'll take you off the list.</p>

</body></html>
"""


def get_recipients(db, limit=None, only=None):
    """One row per user with the best available email (primary > verified > any).
    Returns list of (user_id, name, to_addr) tuples."""
    sql = text("""
        SELECT u.id, u.name, COALESCE(u.email, ue.email) AS to_addr
        FROM users u
        LEFT JOIN LATERAL (
            SELECT email FROM user_emails
            WHERE user_id = u.id
            ORDER BY is_primary DESC, verified_at DESC NULLS LAST
            LIMIT 1
        ) ue ON true
        WHERE COALESCE(u.email, ue.email) IS NOT NULL
        ORDER BY u.id
    """)
    rows = db.execute(sql).fetchall()
    recips = [(r[0], r[1] or "there", r[2].strip()) for r in rows if r[2] and "@" in r[2]]
    if only:
        recips = [r for r in recips if r[2].lower() == only.lower()]
    if limit:
        recips = recips[:limit]
    return recips


def render(name):
    first = name.split()[0] if name and name != "there" else "there"
    ctx = dict(name=first, rules_url=RULES_URL)
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
        _, period_end, _ = gov.get_current_period(db)
        days_left = gov.days_remaining_in_period(db)
        period_end_str = period_end.strftime("%B %-d, %Y")
        recips = get_recipients(db, limit=args.limit, only=args.only)
    finally:
        db.close()

    print(f"period ends: {period_end_str} ({days_left} days remaining)")
    print(f"recipients:  {len(recips)}")
    if not recips:
        print("nothing to do")
        return

    if args.dry_run:
        sample = recips[0]
        text_body, _ = render(sample[1])
        print(f"\n--- preview for {sample[2]} ---\n")
        print(f"From:     {config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>")
        print(f"Reply-To: {REPLY_TO}")
        print(f"Subject:  {SUBJECT}")
        print(f"\n{text_body}")
        print(f"\n--- recipient list ({len(recips)} total) ---")
        for r in recips[:20]:
            print(f"  {r[0]:>4}  {r[2]:<40}  {r[1]}")
        if len(recips) > 20:
            print(f"  ... and {len(recips)-20} more")
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
        for i, (uid, name, to_addr) in enumerate(recips, 1):
            text_body, html_body = render(name)
            try:
                send_one(server, to_addr, name, text_body, html_body)
                sent += 1
                print(f"  [{i}/{len(recips)}] sent  →  {to_addr}")
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
