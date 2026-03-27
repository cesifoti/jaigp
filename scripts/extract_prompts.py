#!/usr/bin/env python3
"""Extract user prompts from Claude Code conversation JSONL files.

Produces a sanitized JSON archive of all prompts used to build JAIGP, organized by session.
Sensitive information (paths, tokens, keys, hostnames, IPs) is stripped before output.
Output: data/prompts_archive.json
"""
import json
import os
import re
from datetime import datetime


# Patterns for stripping sensitive information from prompt text.
# Order matters: more specific patterns must come before general ones.
SANITIZE_PATTERNS = [
    # ===== API KEYS & TOKENS (highest priority — specific before generic) =====
    # Anthropic API keys (sk-ant-api03-...)
    (re.compile(r'sk-ant-[A-Za-z0-9_\-]{20,}'), '[REDACTED]'),
    # OpenAI API keys (sk-proj-..., sk-...)
    (re.compile(r'sk-proj-[A-Za-z0-9_\-]{20,}'), '[REDACTED]'),
    # Generic sk- / sk_ secret keys (Reviewer3, Stripe, etc.)
    (re.compile(r'\bsk[-_][A-Za-z0-9_\-]{15,}'), '[REDACTED]'),
    # OpenAI org keys (org-...)
    (re.compile(r'\borg-[A-Za-z0-9]{20,}'), '[REDACTED]'),
    # Google API keys (AIza...)
    (re.compile(r'\bAIza[A-Za-z0-9_\-]{30,}'), '[REDACTED]'),
    # Google OAuth client secrets
    (re.compile(r'GOCSPX-[A-Za-z0-9_\-]{20,}'), '[REDACTED]'),
    # AWS access keys (AKIA...)
    (re.compile(r'\bAKIA[A-Z0-9]{16,}'), '[REDACTED]'),
    # AWS secret keys (in key=value format)
    (re.compile(r'(?i)aws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+=]{30,}'), 'aws_secret_access_key=[REDACTED]'),
    # Stripe keys (pk_live_, pk_test_, sk_live_, sk_test_, rk_live_, rk_test_)
    (re.compile(r'\b[psr]k_(live|test)_[A-Za-z0-9]{20,}'), '[REDACTED]'),
    # Twilio keys (SK...)
    (re.compile(r'\bSK[a-f0-9]{32}\b'), '[REDACTED]'),
    # SendGrid keys (SG....)
    (re.compile(r'\bSG\.[A-Za-z0-9_\-]{20,}'), '[REDACTED]'),
    # Slack tokens (xoxb-, xoxp-, xoxs-, xoxa-)
    (re.compile(r'\bxox[bpsa]-[A-Za-z0-9\-]{20,}'), '[REDACTED]'),
    # GitHub personal access tokens (ghp_...)
    (re.compile(r'ghp_[A-Za-z0-9]{30,}'), '[REDACTED]'),
    # GitHub fine-grained tokens (github_pat_...)
    (re.compile(r'github_pat_[A-Za-z0-9_]{30,}'), '[REDACTED]'),
    # GitLab tokens (glpat-...)
    (re.compile(r'glpat-[A-Za-z0-9_\-]{20,}'), '[REDACTED]'),
    # npm tokens (npm_...)
    (re.compile(r'\bnpm_[A-Za-z0-9]{30,}'), '[REDACTED]'),
    # Bearer tokens in headers
    (re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]{20,}'), '[REDACTED]'),
    # x-api-key header values (common in prompts about API calls)
    (re.compile(r'(?i)(x-api-key|api[_-]?key|authorization)["\s:=]+[A-Za-z0-9_\-\.]{20,}'), '[REDACTED]'),
    # Environment variable assignments with secrets
    (re.compile(r'(?i)(API_KEY|SECRET_KEY|CLIENT_SECRET|ACCESS_TOKEN|PRIVATE_KEY|AUTH_TOKEN|WEBHOOK_SECRET)\s*=\s*["\']?[A-Za-z0-9_\-\.\/+=]{15,}["\']?'), r'\1=[REDACTED]'),
    # Generic long hex secrets (64+ chars)
    (re.compile(r'\b[A-Fa-f0-9]{64,}\b'), '[REDACTED]'),
    # Generic long base64 strings (40+ chars, no spaces — likely tokens)
    (re.compile(r'(?<![A-Za-z0-9])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9])'), '[REDACTED]'),
    # ORCID App IDs
    (re.compile(r'APP-[A-Z0-9]{16}'), '[REDACTED]'),
    # Gmail app passwords (4 groups of 4 lowercase letters)
    (re.compile(r'\b[a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}\b'), '[REDACTED]'),
    # Passwords in key=value format
    (re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?[^\s"\']{8,}["\']?'), r'\1=[REDACTED]'),
    # Phrases that imply key sharing (the key itself may be redacted but the context is sensitive)
    (re.compile(r'(?i)use this\s+\w+\s+api\s*key.*', re.DOTALL), '[Key reference redacted]'),
    (re.compile(r'(?i)the\s+\w+\s+api\s*key\s+that\s+I\s+gave\s+you[^.]*'), 'the API key provided'),

    # ===== URLs WITH SENSITIVE CONTENT =====
    # Dropbox shared links (contain access keys in rlkey param)
    (re.compile(r'https?://[^\s]*dropbox\.com/[^\s"]*'), '[REDACTED]'),
    # Google Drive shared links
    (re.compile(r'https?://drive\.google\.com/[^\s"]*'), '[REDACTED]'),
    # Any URL with token/key/secret/password query params
    (re.compile(r'https?://[^\s]*[?&](token|key|secret|password|access_token|api_key|apikey)=[^\s"&]*'), '[REDACTED]'),

    # ===== CONNECTION STRINGS & CREDENTIALS =====
    # PostgreSQL connection strings
    (re.compile(r'postgresql://[^\s]+'), '[REDACTED]'),
    # MySQL connection strings
    (re.compile(r'mysql://[^\s]+'), '[REDACTED]'),
    # Redis connection strings
    (re.compile(r'redis://[^\s]+'), '[REDACTED]'),
    # Database credentials
    (re.compile(r'jaigp_secure_pass_\w+'), '[REDACTED]'),
    (re.compile(r'\bjaigp_user\b'), '[db_user]'),

    # ===== SERVER & INFRASTRUCTURE =====
    # Server terminal: root@hostname:/path#
    (re.compile(r'root@[\w\-]+:[/\w\-\.#~]+'), '[server]'),
    # root@hostname
    (re.compile(r'root@[\w\-]+'), '[server]'),
    # Hetzner-style server hostnames
    (re.compile(r'ubuntu-\d+gb-[\w\-]+'), '[server]'),
    # Full URLs with dev.jaigp.org
    (re.compile(r'https?://dev\.jaigp\.org[^\s]*'), '[dev_url]'),
    # Bare dev.jaigp.org
    (re.compile(r'dev\.jaigp\.org'), '[dev_server]'),
    # localhost URLs
    (re.compile(r'https?://localhost:\d+[^\s]*'), '[local_url]'),
    (re.compile(r'localhost:\d+'), '[local_server]'),
    # 0.0.0.0 URLs
    (re.compile(r'https?://0\.0\.0\.0:\d+[^\s]*'), '[local_url]'),
    # File paths
    (re.compile(r'/var/www/[\w\-\./_]+'), '[server_path]'),
    (re.compile(r'/root/[\w\-\./_]+'), '[server_path]'),
    (re.compile(r'/home/[\w\-\./_]+'), '[server_path]'),
    # System user
    (re.compile(r'\bwww-data\b'), '[service_user]'),
    # IP addresses (with optional port)
    (re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?\b'), '[REDACTED]'),
]


def sanitize_text(text):
    """Strip sensitive information (paths, tokens, keys, hostnames, IPs) from text."""
    for pattern, replacement in SANITIZE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# Patterns that strongly indicate a procedural/debugging prompt
_PROCEDURAL_PATTERNS = [
    re.compile(r'(?i)^(resume|redeploy|restart|enter plan mode|exit plan mode|claude\s*/)', re.MULTILINE),
    re.compile(r'(?i)(500\s*(server\s*)?error|internal server error|traceback|ModuleNotFoundError|ImportError|TypeError|AttributeError|KeyError|NameError|SyntaxError)'),
    re.compile(r'(?i)^(do i need to redeploy|show me the names|give me text|gmail app password)'),
    re.compile(r'(?i)(not working|fails|broken|refused to connect|status\s*\d{3}|error\s*when|error\s*at|error\s*on|error\s*message)'),
    re.compile(r'\[REDACTED\]'),
]


def classify_prompt(text):
    """Classify a prompt as 'key' (embodies ideas/purpose) or 'procedural' (debugging/execution).

    Heuristics:
    - Very short prompts (<15 words) are procedural unless they state a clear idea
    - Error reports, stack traces, credentials are procedural
    - Prompts that introduce concepts, propose features, discuss policy, or express
      philosophy are key prompts
    - Longer prompts (50+ words) are presumed key unless they contain error markers
    """
    words = text.split()
    word_count = len(words)

    # Very short = procedural (e.g., "resume work", "redeploy", "Do i need to redeploy?")
    if word_count < 15:
        return "procedural"

    # Check for strong procedural signals
    for pattern in _PROCEDURAL_PATTERNS:
        if pattern.search(text):
            return "procedural"

    # Short prompts (15-40 words) without procedural signals: check for idea content
    if word_count < 40:
        # If it has idea-laden language, it's key
        idea_signals = re.compile(
            r'(?i)(we (want|need|should)|let\'?s (add|change|make|think|discuss|explore|improve|create|implement|build)|'
            r'i (think|believe|would like|am thinking)|'
            r'the (idea|concept|philosophy|approach|strategy|plan|goal|vision|mission)|'
            r'instead of|rather than|how (should|do|can) we|what if|'
            r'for the (announcement|communication|video|launch))'
        )
        if idea_signals.search(text):
            return "key"
        return "procedural"

    # 40+ words: check if it's primarily a bug report / error log
    bug_report = re.compile(
        r'(?i)(issues?\s+to\s+fix|bug|there are a few issues|'
        r'page\s+(is\s+)?(not\s+)?(display|show|load|work)|'
        r'getting\s+(a|an)\s+(error|500)|when\s+(I|we)\s+(click|try|go).*error)'
    )
    # Count how many error/fix indicators vs idea indicators
    error_signals = len(re.findall(r'(?i)(not (working|showing|display)|error|broken|fix|issue|bug|fails|wrong)', text))
    idea_signals_count = len(re.findall(r'(?i)(we (want|need|should)|let\'?s|i (think|believe|would like)|the idea|instead of|how should|what if)', text))

    if error_signals > idea_signals_count and bug_report.search(text):
        return "procedural"

    return "key"

import hashlib as _hashlib

_LLM_CLASSIFICATIONS = None

def _load_llm_classifications():
    """Load LLM-generated classifications from cache file."""
    global _LLM_CLASSIFICATIONS
    if _LLM_CLASSIFICATIONS is None:
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "prompt_classifications.json")
        cache_path = os.path.normpath(cache_path)
        try:
            with open(cache_path) as f:
                _LLM_CLASSIFICATIONS = json.load(f)
        except FileNotFoundError:
            _LLM_CLASSIFICATIONS = {}
    return _LLM_CLASSIFICATIONS


def _classify_with_cache(text):
    """Use LLM classification if available, fall back to regex heuristic."""
    cache = _load_llm_classifications()
    h = _hashlib.sha256(text.encode()).hexdigest()[:12]
    if h in cache:
        return cache[h]
    return classify_prompt(text)


CONVERSATIONS_SRC = "/root/.claude/projects/-var-www-ai-journal"
CONVERSATIONS_COPY = "/var/www/ai_journal/data/conversations"
OUTPUT_FILE = "/var/www/ai_journal/data/prompts_archive.json"

# Map conversation UUIDs to human-readable session titles (in chronological order)
SESSION_TITLES = {
    "7895f77d-badc-49ce-ad62-8e832e5e36ed": "Building JAIGP from Scratch",
    "e7f4d1dc-1e31-4178-8695-ae6931f021fa": "5-Stage Peer Review Pipeline",
    "76b63ae0-b90d-42c1-83fe-45e95abe07e1": "AI Review Flow Redesign",
    "5c8e90e5-3b93-49bd-88f9-c1d4d1f8cd2e": "Paper Presentation & UI Improvements",
    "e7f02f13-1656-4e0c-827b-87057625d3db": "Multi-Email User Support",
    "f3d8adb2-45f0-4dc6-a177-2e46150f3a71": "AI Review Response Form & Draft Saving",
    "706d3c3a-b89b-478a-ae8c-1bf06478906a": "Development Session Continuation",
    "ed922c8d-25fb-4ce2-a7b9-9f50b0cb3be9": "Quick Fixes & Patches",
    "5c5d3acd-542a-4cdd-8ea0-d23c36dc0524": "Paper Presentation Refinements",
    "c1752ce3-0d0b-4016-8c57-e3e03bf1f00b": "Paper Locking & Review Stages",
    "0bc06c4e-44d4-417d-acab-eb88be20f6e2": "Admin Editing, Production Deploy & Open Prompt",
    "8a23eb0f-b0a2-4c0f-9b1e-eae06af3efc5": "Session Initialization",
    "d235d863-d710-47b2-aa62-bff0d1d5e638": "Archive Sanitization, Social Feed & Rules Page",
    "7faa5956-c251-4c0a-ae05-a9e2c6e3ae61": "Session Initialization (2)",
    "91f51b23-55c0-4337-b57c-591cb390505a": "Typography, Summarization & Browse Improvements",
    "a0d0b515-1d28-4092-8708-98a8eff0d91d": "Notifications, Feed Merge & Security Audit",
}


# Prefixes that indicate system-generated messages, not human input
SYSTEM_PREFIXES = (
    "<task-notification>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<command-name>",
    "<user-prompt-submit-hook>",
    "[Request interrupted",
    "This session is being continued from a previous conversation",
    "Implement the following plan",  # Auto-generated when approving a Claude plan
)


def extract_prompts_from_file(filepath):
    """Extract only genuine human-typed prompts from a JSONL conversation file.

    Human input is stored as string-type content in user messages.
    Tool results (file reads, command output, etc.) are stored as list-type
    content with tool_result blocks — these are skipped entirely.
    """
    prompts = []
    with open(filepath) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "user":
                continue

            msg = obj.get("message", {})
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue

            content = msg.get("content")
            timestamp = obj.get("timestamp", "")

            # Only string-type content is actual human input.
            # List-type content contains tool_result blocks (file contents,
            # command output, etc.) — skip entirely.
            if not isinstance(content, str):
                continue

            full_text = content.strip()

            # Skip empty or very short messages
            if not full_text or len(full_text) < 10:
                continue

            # Skip system-generated messages (commands, context restoration, etc.)
            if any(full_text.startswith(prefix) for prefix in SYSTEM_PREFIXES):
                continue

            sanitized = sanitize_text(full_text)
            prompts.append({
                "text": sanitized,
                "timestamp": timestamp,
                "prompt_type": _classify_with_cache(sanitized),
            })

    return prompts


def get_file_date(filepath):
    """Get earliest timestamp from the file's prompts, or file mtime."""
    with open(filepath) as f:
        for line in f:
            try:
                obj = json.loads(line)
                if obj.get("type") == "user" and obj.get("timestamp"):
                    return obj["timestamp"]
            except (json.JSONDecodeError, KeyError):
                continue
    return datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()


def sync_conversations():
    """Copy JSONL files from source to the web-readable conversations directory."""
    import shutil
    os.makedirs(CONVERSATIONS_COPY, exist_ok=True)
    copied = 0
    for fname in os.listdir(CONVERSATIONS_SRC):
        if not fname.endswith(".jsonl"):
            continue
        src = os.path.join(CONVERSATIONS_SRC, fname)
        dst = os.path.join(CONVERSATIONS_COPY, fname)
        src_mtime = os.path.getmtime(src)
        dst_mtime = os.path.getmtime(dst) if os.path.exists(dst) else 0
        if src_mtime > dst_mtime:
            shutil.copy2(src, dst)
            copied += 1
    if copied:
        print(f"Synced {copied} conversation files to {CONVERSATIONS_COPY}")
    # Make readable by www-data
    for fname in os.listdir(CONVERSATIONS_COPY):
        fpath = os.path.join(CONVERSATIONS_COPY, fname)
        os.chmod(fpath, 0o644)


def main():
    # Sync conversations first so the web app can read them
    sync_conversations()

    sessions = []

    for filename in os.listdir(CONVERSATIONS_SRC):
        if not filename.endswith(".jsonl"):
            continue

        uuid = filename.replace(".jsonl", "")
        filepath = os.path.join(CONVERSATIONS_SRC, filename)

        prompts = extract_prompts_from_file(filepath)
        if not prompts:
            continue

        title = SESSION_TITLES.get(uuid, f"Session {uuid[:8]}")
        first_ts = prompts[0]["timestamp"] if prompts else get_file_date(filepath)

        sessions.append({
            "id": uuid,
            "title": title,
            "started_at": first_ts,
            "prompt_count": len(prompts),
            "prompts": prompts,
        })

    # Sort sessions chronologically
    sessions.sort(key=lambda s: s["started_at"])

    # Number per-session indices
    for session in sessions:
        for i, prompt in enumerate(session["prompts"]):
            prompt["session_index"] = i + 1
            prompt["_session_id"] = session["id"]

    # Assign global_index by timestamp across ALL sessions so the most
    # recent prompt is always last, regardless of which session it belongs to.
    all_prompts = []
    for session in sessions:
        for prompt in session["prompts"]:
            all_prompts.append(prompt)
    all_prompts.sort(key=lambda p: p.get("timestamp", ""))

    for i, prompt in enumerate(all_prompts):
        prompt["global_index"] = i + 1

    global_num = len(all_prompts)

    # Clean up temp key
    for session in sessions:
        for prompt in session["prompts"]:
            prompt.pop("_session_id", None)

    archive = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_prompts": global_num,
        "total_sessions": len(sessions),
        "sessions": sessions,
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(archive, f, indent=2, ensure_ascii=False)

    print(f"Extracted {global_num} prompts from {len(sessions)} sessions")
    print(f"Output: {OUTPUT_FILE}")
    for s in sessions:
        print(f"  {s['title']}: {s['prompt_count']} prompts (started {s['started_at'][:10]})")


if __name__ == "__main__":
    main()
