#!/usr/bin/env bash
# Rotate ONLY the JAIGP Anthropic API key.
#
# Touches exactly one line (ANTHROPIC_API_KEY=...) in exactly these files:
#   /var/www/ai_journal/.env            (production, jaip@8002-8004)
#   /var/www/ai_journal_dev/.env.dev    (dev, jaip-dev)
# Every other variable in those files, and every other project's .env on this
# server, is left untouched. Backups are written next to each file.
#
# Usage (run in your own terminal, as root/sudo):
#   sudo scripts/rotate_anthropic_key.sh            # prompts silently for the key
#   sudo scripts/rotate_anthropic_key.sh --from-file /root/new_key.txt
#
# Options:
#   --from-file PATH   read the key from PATH (first line) instead of prompting
#   --no-restart       update the files only; don't restart services
#   --no-verify        skip the one-token test call
#   --files a,b        (testing) operate on these files instead of the real ones
set -euo pipefail

FILES=(/var/www/ai_journal/.env /var/www/ai_journal_dev/.env.dev)
SERVICES=(jaip@8002 jaip@8003 jaip@8004 jaip-dev)
FROM_FILE=""; RESTART=1; VERIFY=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from-file) FROM_FILE="$2"; shift 2 ;;
        --no-restart) RESTART=0; shift ;;
        --no-verify) VERIFY=0; shift ;;
        --files) IFS=, read -r -a FILES <<< "$2"; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then echo "run with sudo (the env files are root/www-data only)" >&2; exit 1; fi

# --- obtain the new key without echoing it or leaving it in shell history ---
if [[ -n "$FROM_FILE" ]]; then
    NEW_KEY=$(head -n1 "$FROM_FILE" | tr -d '[:space:]')
else
    read -r -s -p "Paste the NEW Anthropic API key (input hidden): " NEW_KEY; echo
    read -r -s -p "Paste it again to confirm: " NEW_KEY2; echo
    [[ "$NEW_KEY" == "$NEW_KEY2" ]] || { echo "keys do not match" >&2; exit 1; }
fi
[[ "$NEW_KEY" =~ ^sk-ant-api[0-9]+-[A-Za-z0-9_-]{40,}$ ]] || { echo "that does not look like an Anthropic API key (sk-ant-api03-...)" >&2; exit 1; }

for f in "${FILES[@]}"; do
    [[ -f "$f" ]] || { echo "missing: $f" >&2; exit 1; }
    n=$(grep -cE '^ANTHROPIC_API_KEY=' "$f" || true)
    [[ "$n" -eq 1 ]] || { echo "$f has $n ANTHROPIC_API_KEY lines (expected exactly 1) — not touching anything" >&2; exit 1; }
done

stamp=$(date +%Y%m%d-%H%M%S)
for f in "${FILES[@]}"; do
    old_hash=$(grep -E '^ANTHROPIC_API_KEY=' "$f" | sha256sum | cut -c1-8)
    cp -p "$f" "$f.bak-$stamp"                    # same owner/mode as the original
    # Replace only the value of that one line; preserve everything else byte-for-byte.
    # Using awk with -v keeps the key out of the process list (no sed 's|...|KEY|').
    awk -v k="$NEW_KEY" '/^ANTHROPIC_API_KEY=/{print "ANTHROPIC_API_KEY=" k; next}{print}' "$f" > "$f.tmp-$stamp"
    chown --reference="$f" "$f.tmp-$stamp"; chmod --reference="$f" "$f.tmp-$stamp"
    mv "$f.tmp-$stamp" "$f"
    changed=$(diff <(grep -v '^ANTHROPIC_API_KEY=' "$f.bak-$stamp") <(grep -v '^ANTHROPIC_API_KEY=' "$f") | wc -l)
    [[ "$changed" -eq 0 ]] || { echo "unexpected change outside the key line in $f — restoring backup" >&2; cp -p "$f.bak-$stamp" "$f"; exit 1; }
    echo "updated $f  (old key line hash $old_hash -> $(grep -E '^ANTHROPIC_API_KEY=' "$f" | sha256sum | cut -c1-8); backup $f.bak-$stamp)"
done

if [[ $RESTART -eq 1 ]]; then
    systemctl restart "${SERVICES[@]}"
    sleep 2
    for s in "${SERVICES[@]}"; do printf "%-11s %s\n" "$s" "$(systemctl is-active "$s")"; done
fi

if [[ $VERIFY -eq 1 ]]; then
    echo "verifying with a 1-token Haiku call using the production env file..."
    ANTHROPIC_API_KEY="$NEW_KEY" /var/www/ai_journal/venv/bin/python - <<'PY'
import os, anthropic
c = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
m = c.messages.create(model="claude-haiku-4-5-20251001", max_tokens=1, messages=[{"role": "user", "content": "hi"}])
print("OK: new key accepted (model", m.model + ")")
PY
fi

echo
echo "Done. Now DISABLE the old key in the Anthropic console (Settings -> API keys)."
echo "Backups contain the old key; delete them once you're happy:  rm ${FILES[*]/%/.bak-$stamp}"
