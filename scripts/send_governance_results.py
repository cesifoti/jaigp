#!/usr/bin/env python3
"""Results announcement for JAIGP's first governance vote (period 2026-05).

USAGE:
    sudo venv/bin/python scripts/send_governance_results.py --dry-run
    sudo venv/bin/python scripts/send_governance_results.py --send \
         [--limit N] [--only EMAIL]

--dry-run   render the email + recipient list to stdout, NO sends
--send      actually send via SMTP
--limit N   only process the first N recipients
--only X    only send to address X (case-insensitive; useful for self-test)

Paces sends at 1.5s/email so the Gmail relay doesn't trip rate limits.
Reply-To is contact@jaigp.org so replies reach the shared inbox.

The numbers below are the final, immutable results of the 2026-05 tally
(see governance_tallies), so they're baked into the body as constants.
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
RULES_URL = "https://jaigp.org/rules"
SOCIAL_URL = "https://jaigp.org/prompts"
THROTTLE_SECONDS = 1.5

SUBJECT = "JAIGP's first vote: what changed, what didn't"

BODY_TEXT = """Hi {name},

Last month the rules of JAIGP went to a community vote for the first time,
and 14 of you cast 293 votes. Thank you. The period closed June 1 and the
results are now live for June.

Two rules changed:

  • Borderline-strike cooldown: 90 -> 30 days. A paper flagged borderline now
    waits one month, not three, before returning.
  • Deadline extension: 20 -> 30 days. Extension requests now buy 30 days
    instead of 20.

The endorsement rules held — but barely, and that surprised us too. This was
the most contested part of the ballot. Keeping 2 endorsements for new authors
won by a single vote (5–4 over dropping to 1), and the Bronze+ minimum for
endorsers edged out Copper+ by a similar margin. The current bar survived, but
the community is clearly split on how hard it should be to get a paper
endorsed — so this is one to watch (and vote on) next month.

Everything else stayed put — AI-review attempts, the 180-day stage deadline,
rejection cooldowns, voting cadence — because the status quo won each vote. The
five per-badge pipeline limits didn't reach the 10-voter quorum, so they're
unchanged by default until more of you weigh in.

One thing worth remembering: the vote never closes. Go to {rules_url} any time
and change your mind on any rule — your new choice registers instantly. Votes
only lock in at month's end, and whatever's leading then becomes the next
month's rule. It's a living tally, not a one-time ballot. The next one closes
July 1.

If you haven't voted yet, the endorsement rules and the five quorum-short
limits are wide open. Thoughts on the rules, or options we should add? The
Social tab at {social_url} is the place.

Thanks for being part of this open exploration.

— The JAIGP team
https://jaigp.org

(Prefer not to get these? Just reply and we'll drop you from the list.)
"""

BODY_HTML = """\
<!doctype html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #1e293b; max-width: 620px; margin: 0 auto; padding: 20px;">

<p>Hi {name},</p>

<p>Last month the rules of JAIGP went to a community vote for the first time,
and <strong>14 of you cast 293 votes.</strong> Thank you. The period closed
June 1 and the results are now live for June.</p>

<p><strong>Two rules changed:</strong></p>
<ul style="padding-left: 22px;">
  <li><strong>Borderline-strike cooldown: 90 &rarr; 30 days.</strong> A paper
  flagged borderline now waits one month, not three, before returning.</li>
  <li><strong>Deadline extension: 20 &rarr; 30 days.</strong> Extension
  requests now buy 30 days instead of 20.</li>
</ul>

<p><strong>The endorsement rules held &mdash; but barely, and that surprised
us too.</strong> This was the most contested part of the ballot. Keeping
<strong>2 endorsements</strong> for new authors won by a single vote (5&ndash;4
over dropping to 1), and the <strong>Bronze+</strong> minimum for endorsers
edged out Copper+ by a similar margin. The current bar survived, but the
community is clearly split on how hard it should be to get a paper endorsed
&mdash; so this is one to watch (and vote on) next month.</p>

<p><strong>Everything else stayed put</strong> &mdash; AI-review attempts, the
180-day stage deadline, rejection cooldowns, voting cadence &mdash; because the
status quo won each vote. The five per-badge pipeline limits didn't reach the
10-voter quorum, so they're unchanged by default until more of you weigh in.</p>

<p><strong>One thing worth remembering: the vote never closes.</strong> Go to
<a href="{rules_url}" style="color:#2563eb;">{rules_url}</a> any time and change
your mind on any rule &mdash; your new choice registers instantly. Votes only
<em>lock in</em> at month's end, and whatever's leading then becomes the next
month's rule. It's a living tally, not a one-time ballot. <strong>The next one
closes July 1.</strong></p>

<p>If you haven't voted yet, the endorsement rules and the five quorum-short
limits are wide open. Thoughts on the rules, or options we should add? The
<a href="{social_url}" style="color:#2563eb;">Social tab</a> is the place.</p>

<p>Thanks for being part of this open exploration.</p>

<p>&mdash; The JAIGP team<br/>
<a href="https://jaigp.org" style="color:#2563eb;">https://jaigp.org</a></p>

<p style="color:#64748b; font-size: 13px;">Prefer not to get these? Just reply
and we'll drop you from the list.</p>

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
    ctx = dict(name=first, rules_url=RULES_URL, social_url=SOCIAL_URL)
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
