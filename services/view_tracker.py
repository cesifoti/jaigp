"""First-party, privacy-preserving paper view counting.

No third-party analytics. A "view" is one unique visitor per paper per UTC day:
we hash (day | ip | user-agent | server secret) — the salted hash lives only in
Redis for 48h to deduplicate; raw IPs are never stored and hashes are not
linkable across days. Bots are filtered by user-agent.
"""
import hashlib
import re
from datetime import datetime

from sqlalchemy import text

import config

# Common crawlers, previews, and programmatic clients
_BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|'
    r'skype|discord|embedly|quora|pinterest|vkshare|curl|wget|python|httpx|'
    r'aiohttp|go-http|okhttp|java(?!script)|libwww|perl|ruby|scrapy|headless|'
    r'phantom|selenium|lighthouse|pagespeed|pingdom|uptime|monitor|checkly|'
    r'feed|rss|validator|archive|wayback|semrush|ahrefs|mj12|dotbot|petalbot|'
    r'bytespider|gptbot|claudebot|ccbot|anthropic|openai|perplexity|amazonbot|'
    r'applebot|yandex|baidu|duckduck|sogou|exabot',
    re.IGNORECASE,
)

_VIEW_TTL = 48 * 3600  # dedup window; > 1 UTC day with margin


def record_paper_view(paper_id: int, request, db) -> None:
    """Count a paper page visit if it's a new (visitor, day) pair. Never raises."""
    try:
        ua = request.headers.get("user-agent", "")
        if not ua or _BOT_RE.search(ua):
            return
        ip = request.client.host if request.client else ""
        if not ip:
            return

        day = datetime.utcnow().strftime("%Y%m%d")
        visitor = hashlib.sha256(
            f"{day}|{ip}|{ua}|{config.SECRET_KEY}".encode()
        ).hexdigest()[:16]

        from services.cache import redis_client
        key = f"{config.REDIS_KEY_PREFIX}pv:{paper_id}:{day}"
        # SADD returns 1 only for a first-time member -> exactly-once per day,
        # atomic across all workers
        if redis_client.sadd(key, visitor) == 1:
            redis_client.expire(key, _VIEW_TTL)
            db.execute(
                text("UPDATE papers SET view_count = view_count + 1 WHERE id = :pid"),
                {"pid": paper_id},
            )
            db.commit()
    except Exception as e:
        # Analytics must never break the page (Redis down, etc.)
        print(f"[views] skipped view record for paper {paper_id}: {e!r}")
