"""One-shot backfill of papers.view_count from server logs.

Counts unique (paper, ip, day) triples — the same definition the live tracker
uses — from two sources:

1. nginx /var/log/nginx/jaip_access.log* (~14 days): has user-agents, so bot
   traffic is filtered directly.
2. systemd journal for jaip@800{2,3,4} (back to service start, ~Apr 26): no
   user-agents; we exclude IPs that identified as bots anywhere in the nginx
   window. Older bot IPs outside that window can't be identified, so journal-
   era counts are a slight overestimate — acceptable for an estimate.

Prints per-paper counts; pass --write to store them in papers.view_count.
Overlapping days between sources dedupe naturally via the shared triple set.
"""
import argparse
import glob
import gzip
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.view_tracker import _BOT_RE  # same bot definition as live tracking

NGINX_GLOB = "/var/log/nginx/jaip_access.log*"
JOURNAL_UNITS = ["jaip@8002.service", "jaip@8003.service", "jaip@8004.service"]

# combined log format: ip - - [dd/Mon/yyyy:...] "METHOD path proto" status bytes "ref" "ua"
NGINX_RE = re.compile(
    r'^(\S+) \S+ \S+ \[(\d{2})/(\w{3})/(\d{4}):[^\]]*\] "GET /paper/(\d+) HTTP[^"]*" 200 \d+ "[^"]*" "([^"]*)"'
)
# journal short-iso: 2026-07-06T00:26:11+0000 host jaip-8002[pid]: INFO: ip:0 - "GET /paper/88 HTTP/1.1" 200 OK
JOURNAL_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2})T\S+ \S+ \S+: INFO:\s+([\d a-fA-F.:]+?):\d+ - "GET /paper/(\d+) HTTP[^"]*" 200'
)
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def read_nginx():
    triples, bot_ips = set(), set()
    for path in sorted(glob.glob(NGINX_GLOB)):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", errors="replace") as f:
            for line in f:
                # learn bot IPs from every request, not just paper hits
                parts = line.split('"')
                if len(parts) >= 6 and _BOT_RE.search(parts[-2]):
                    bot_ips.add(line.split(" ", 1)[0])
                    continue
                m = NGINX_RE.match(line)
                if not m:
                    continue
                ip, dd, mon, yyyy, pid, ua = m.groups()
                if not ua or _BOT_RE.search(ua):
                    bot_ips.add(ip)
                    continue
                triples.add((int(pid), ip, f"{yyyy}{MONTHS[mon]:02d}{dd}"))
    return triples, bot_ips


def read_journal(bot_ips):
    triples = set()
    for unit in JOURNAL_UNITS:
        out = subprocess.run(
            ["journalctl", "-u", unit, "-o", "short-iso", "--no-pager"],
            capture_output=True, text=True,
        ).stdout
        for line in out.splitlines():
            m = JOURNAL_RE.match(line)
            if not m:
                continue
            day, ip, pid = m.group(1), m.group(2), int(m.group(3))
            if ip in bot_ips:
                continue
            triples.add((pid, ip, day.replace("-", "")))
    return triples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write counts to the DB")
    args = parser.parse_args()

    nginx_triples, bot_ips = read_nginx()
    print(f"nginx: {len(nginx_triples)} unique (paper, ip, day); {len(bot_ips)} bot IPs learned")
    journal_triples = read_journal(bot_ips)
    print(f"journal: {len(journal_triples)} unique triples")

    all_triples = nginx_triples | journal_triples
    counts = {}
    for pid, _ip, _day in all_triples:
        counts[pid] = counts.get(pid, 0) + 1

    for pid in sorted(counts, key=counts.get, reverse=True)[:15]:
        print(f"  paper {pid}: {counts[pid]}")
    print(f"  ... {len(counts)} papers total, {sum(counts.values())} total views")

    if args.write:
        from models.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            updated = 0
            for pid, n in counts.items():
                r = db.execute(
                    text("UPDATE papers SET view_count = :n WHERE id = :pid"),
                    {"n": n, "pid": pid},
                )
                updated += r.rowcount
            db.commit()
            print(f"wrote view_count for {updated} papers")
        finally:
            db.close()


if __name__ == "__main__":
    main()
