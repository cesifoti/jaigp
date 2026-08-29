#!/usr/bin/env bash
# Block secrets from reaching the PUBLIC GitHub repo (github.com/cesifoti/jaigp).
#
# Two layers:
#   1. Pattern scan  - well-known key shapes (Anthropic, AWS, GitHub, Slack, private keys,
#                      DSNs with passwords, KEY/SECRET/PASSWORD assignments).
#   2. Literal scan  - the ACTUAL values currently in the server's env files, if readable.
#                      Catches a secret of any shape, e.g. pasted into a comment or a test.
#
# Usage:
#   scripts/check_secrets.sh --staged            # what `git commit` is about to record (pre-commit hook)
#   scripts/check_secrets.sh --range A..B        # added lines in the commits about to be pushed (pre-push)
#   scripts/check_secrets.sh --tree              # every tracked file (baseline audit)
#   scripts/check_secrets.sh FILE...             # specific files
# Exit 1 and print the offending locations (values masked) if anything matches.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 2

SELF="scripts/check_secrets.sh"
ENV_FILES=(/var/www/ai_journal/.env /var/www/ai_journal_dev/.env.dev)

PATTERNS=(
    'sk-ant-[A-Za-z0-9_-]{20,}'                                  # Anthropic API / admin keys
    'sk_(live|test)?_?[A-Za-z0-9]{24,}'                          # Reviewer3 / Stripe-style keys
    'AKIA[0-9A-Z]{16}'                                           # AWS access key id
    'gh[pousr]_[A-Za-z0-9]{30,}'                                 # GitHub tokens
    'xox[baprs]-[A-Za-z0-9-]{10,}'                               # Slack tokens
    '-----BEGIN [A-Z ]*PRIVATE KEY-----'                         # private keys
    '(postgres(ql)?|mysql|redis|amqp)://[^:/@ ]+:[^@ ]{4,}@'     # DSN carrying a password
    '^\+?[[:space:]]*(ANTHROPIC_API_KEY|SECRET_KEY|ORCID_CLIENT_SECRET|SMTP_PASSWORD|REVIEWER3_API_KEY)[[:space:]]*=[[:space:]]*["'"'"']?[^"'"'"'[:space:]]{8,}'   # hard-coded assignment
)
# Placeholder values that are fine to commit (.env.example etc.)
ALLOW='your[-_]|example|changeme|placeholder|<[^>]+>|xxx|\.\.\.|os\.getenv|os\.environ|=[[:space:]]*"?\$|user:pass(word)?@|sqlite:|REDACTED'

mask() { sed -E 's/([A-Za-z0-9_-]{5})[A-Za-z0-9_+\/-]{7,}/\1********/g'; }

TMP=$(mktemp); chmod 600 "$TMP"; trap 'rm -f "$TMP"' EXIT
# Layer 2: literal values of sensitive variables from the live env files (never printed)
for f in "${ENV_FILES[@]}"; do
    [[ -r "$f" ]] || continue
    grep -E '^[A-Z_]*(KEY|SECRET|PASSWORD|PASS|TOKEN)=' "$f" | cut -d= -f2- | tr -d '"'"'" | awk 'length($0) >= 8' >> "$TMP"
    grep -E '^[A-Z_]*URL=.*://[^:/@]+:[^@]+@' "$f" | sed -E 's#.*://[^:/@]+:([^@]+)@.*#\1#' | awk 'length($0) >= 6' >> "$TMP"
done

scan_file_content() {  # $1: label, stdin content
    # pattern grep needs the same input for every pattern -> buffer once
    local label="$1" buf hits=0 out
    buf=$(cat)
    for p in "${PATTERNS[@]}"; do
        out=$(printf '%s\n' "$buf" | grep -nE -e "$p" | grep -vE "$ALLOW" || true)
        [[ -n "$out" ]] && { hits=1; echo "$label: matches '$p'"; printf '%s\n' "$out" | mask | head -5; }
    done
    if [[ -s "$TMP" ]]; then
        out=$(printf '%s\n' "$buf" | grep -nF -f "$TMP" || true)
        [[ -n "$out" ]] && { hits=1; echo "$label: contains a LIVE secret value from the server's env files"; printf '%s\n' "$out" | mask | head -5; }
    fi
    return $hits
}

status=0
mode="${1:---staged}"
case "$mode" in
    --staged)
        while IFS= read -r f; do
            [[ "$f" == "$SELF" ]] && continue
            git show ":$f" | grep -qI . || continue          # skip binary
            git show ":$f" | scan_file_content "$f" || status=1
        done < <(git diff --cached --name-only --diff-filter=ACMR)
        ;;
    --range)
        range="${2:?usage: --range A..B}"
        # every ADDED line in every commit of the range - a secret added then removed
        # in a later commit would still be published with the history
        git log -p --no-color --format='commit %h' "$range" -- . ":(exclude)$SELF" \
            | grep -E '^(commit |\+)' | grep -vE '^\+\+\+ ' \
            | scan_file_content "commits $range" || status=1
        ;;
    --tree)
        while IFS= read -r f; do
            [[ "$f" == "$SELF" ]] && continue
            [[ -f "$f" ]] || continue
            grep -qI . "$f" || continue
            scan_file_content "$f" < "$f" || status=1
        done < <(git ls-files)
        ;;
    *)
        for f in "$@"; do scan_file_content "$f" < "$f" || status=1; done
        ;;
esac

if [[ $status -ne 0 ]]; then
    echo
    echo "BLOCKED: possible secret detected. The repo is PUBLIC - remove the value (and rotate it if real)."
    echo "If this is a false positive, extend ALLOW in $SELF rather than bypassing the hook."
fi
exit $status
