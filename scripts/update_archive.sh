#!/bin/bash
# Lightweight archive updater — runs via cron every minute.
# Only does work if any conversation JSONL is newer than the archive.
#
# Cron entry (installed by setup):
#   * * * * * /var/www/ai_journal/scripts/update_archive.sh >> /var/log/jaigp-archive.log 2>&1

set -euo pipefail

ARCHIVE="/var/www/ai_journal/data/prompts_archive.json"
SRC_DIR="/root/.claude/projects/-var-www-ai-journal"
SCRIPT="/var/www/ai_journal/scripts/extract_prompts.py"
VENV="/var/www/ai_journal/venv/bin/python"
LOCKFILE="/tmp/jaigp-archive-update.lock"

# Avoid overlapping runs
if [ -f "$LOCKFILE" ]; then
    # Check if the lock is stale (older than 2 minutes)
    if [ "$(find "$LOCKFILE" -mmin +2 2>/dev/null)" ]; then
        rm -f "$LOCKFILE"
    else
        exit 0
    fi
fi

# Check if any source file is newer than the archive
NEEDS_UPDATE=0
if [ ! -f "$ARCHIVE" ]; then
    NEEDS_UPDATE=1
else
    for f in "$SRC_DIR"/*.jsonl; do
        if [ "$f" -nt "$ARCHIVE" ]; then
            NEEDS_UPDATE=1
            break
        fi
    done
fi

if [ "$NEEDS_UPDATE" -eq 0 ]; then
    exit 0
fi

# Run the extraction
touch "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

$VENV "$SCRIPT" 2>&1 | tail -1
