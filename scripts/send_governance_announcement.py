#!/usr/bin/env python3
"""One-time announcement to all users with email about the new governance vote.

USAGE:
    sudo venv/bin/python scripts/send_governance_announcement.py --dry-run
    sudo venv/bin/python scripts/send_governance_announcement.py --send \
         [--limit N] [--only EMAIL]

--dry-run   render every email and print to stdout, NO sends, NO db writes
--send      actually send via SMTP
--limit N   only process the first N recipients (useful for partial test sends)
--only X    only send to address X (case-insensitive; useful for self-test)

The script paces sends at 1.5s/email so a Gmail SMTP relay doesn't trip
rate-limit / spam thresholds. With 66 recipients that's ~100 seconds.

Reply-To is set to cesifoti@gmail.com so the "just reply" unsubscribe path
actually reaches a human.
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

SUBJECT = "You can now vote on JAIGP's rules"

BODY_TEXT = """Hi {name},

When JAIGP launched, we said we wanted humans and AIs to co-create scholarly
knowledge openly. We're taking the next step on the "openly" part: starting
today, the rules that govern the journal — how many endorsements a paper
needs, how long the cooldown is after a screening rejection, how long each
stage can run, even how often the votes themselves are tallied — are decided
by the community of registered users. You are one of them.

There are 26 votable rules open right now at {rules_url}. Log in with ORCID,
click any option, and your vote is recorded instantly. You can change it any
time before the period ends. The current voting period closes on {period_end}
({days_left} days from today). The option with the most votes wins, with a
10-voter minimum quorum; ties keep the status quo.

A few examples of what's open:
  • How many papers each badge level can have active in the pipeline at once
  • The waiting period after a borderline or hard screening rejection
  • How many endorsements are needed at each author badge level
  • The maximum number of AI-review revision attempts
  • The frequency of voting itself — weekly, monthly, twice a year, or once a year

The full list, with each rule's current value and the options on offer, is at
{rules_url}.

Three rules stay hard-coded — ORCID authentication, email verification after
submission, and the minimum required paper details — because they protect the
journal's basic integrity. Everything else is up for community decision.

If you have thoughts on the rules themselves, on options we should add, or on
anything else about JAIGP, the Social tab at https://jaigp.org/prompts is the
place to share them — feedback there is visible to the whole community and
helps shape what comes next.

If you'd prefer not to receive announcements like this in the future, just
reply to this message and we'll drop you from the list.

Thanks for being part of this open exploration.

— Cesar
JAIGP — Journal for AI Generated Papers
https://jaigp.org
"""

BODY_HTML = """\
<!doctype html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #1e293b; max-width: 620px; margin: 0 auto; padding: 20px;">

<p>Hi {name},</p>

<p>When JAIGP launched, we said we wanted humans and AIs to co-create scholarly
knowledge openly. We're taking the next step on the &ldquo;openly&rdquo; part: starting
today, <strong>the rules that govern the journal</strong> &mdash; how many endorsements a paper
needs, how long the cooldown is after a screening rejection, how long each
stage can run, even how often the votes themselves are tallied &mdash; are decided
by the community of registered users. You are one of them.</p>

<p>There are <strong>26 votable rules</strong> open right now at
<a href="{rules_url}" style="color:#2563eb;">{rules_url}</a>.
Log in with ORCID, click any option, and your vote is recorded instantly. You
can change it any time before the period ends. The current voting period
closes on <strong>{period_end}</strong> ({days_left} days from today). The
option with the most votes wins, with a 10-voter minimum quorum; ties keep
the status quo.</p>

<p>A few examples of what's open:</p>
<ul style="padding-left: 22px;">
  <li>How many papers each badge level can have active in the pipeline at once</li>
  <li>The waiting period after a borderline or hard screening rejection</li>
  <li>How many endorsements are needed at each author badge level</li>
  <li>The maximum number of AI-review revision attempts</li>
  <li>The frequency of voting itself &mdash; weekly, monthly, twice a year, or once a year</li>
</ul>

<p>The full list, with each rule's current value and the options on offer, is at
<a href="{rules_url}" style="color:#2563eb;">{rules_url}</a>.</p>

<p>Three rules stay hard-coded &mdash; ORCID authentication, email verification
after submission, and the minimum required paper details &mdash; because they
protect the journal's basic integrity. Everything else is up for community
decision.</p>

<p>If you have thoughts on the rules themselves, on options we should add, or
on anything else about JAIGP, the
<a href="https://jaigp.org/prompts" style="color:#2563eb;">Social tab</a>
is the place to share them &mdash; feedback there is visible to the whole
community and helps shape what comes next.</p>

<p style="color:#64748b; font-size: 13px;">If you'd prefer not to receive
announcements like this in the future, just reply to this message and we'll
drop you from the list.</p>

<p>Thanks for being part of this open exploration.</p>

<p>&mdash; Cesar<br/>
<span style="color:#64748b;">JAIGP &mdash; Journal for AI Generated Papers</span><br/>
<a href="https://jaigp.org" style="color:#2563eb;">https://jaigp.org</a></p>

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


def render(name, period_end_str, days_left):
    first = name.split()[0] if name and name != "there" else "there"
    ctx = dict(name=first, rules_url=RULES_URL,
               period_end=period_end_str, days_left=days_left)
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
        period_end_str = period_end.strftime("%B %-d, %Y")  # e.g. "June 1, 2026"
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
        text_body, _ = render(sample[1], period_end_str, days_left)
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
            text_body, html_body = render(name, period_end_str, days_left)
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
