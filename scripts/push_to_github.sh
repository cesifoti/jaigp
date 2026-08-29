#!/bin/bash
# Push committed work on main to github.com/cesifoti/jaigp when local is ahead.
# Runs from cron as a safety net; harmless no-op when in sync or offline.
set -u
cd /var/www/ai_journal || exit 0

git fetch origin main --quiet 2>/dev/null || { echo "$(date -Is) fetch failed (offline or key not authorized)"; exit 0; }

AHEAD=$(git rev-list --count origin/main..main 2>/dev/null || echo 0)
BEHIND=$(git rev-list --count main..origin/main 2>/dev/null || echo 0)

if [ "$BEHIND" -gt 0 ]; then
    echo "$(date -Is) WARNING: local main is $BEHIND commits behind origin — not pushing, reconcile manually"
    exit 0
fi

if [ "$AHEAD" -gt 0 ]; then
    if ! /var/www/ai_journal/scripts/check_secrets.sh --range origin/main..main; then
        echo "$(date -Is) BLOCKED: possible secret in the $AHEAD unpushed commit(s) — not pushing"
        exit 1
    fi
    if git push origin main --quiet 2>&1; then
        echo "$(date -Is) pushed $AHEAD commit(s) to github"
    else
        echo "$(date -Is) push failed (deploy key not authorized yet?)"
    fi
fi
