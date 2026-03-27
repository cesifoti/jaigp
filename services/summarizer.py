"""AI summarization service using Claude Haiku with Redis caching."""
import asyncio
import hashlib

import config
from services.cache import CacheService


def _call_claude_sync(system_prompt: str, user_content: str) -> str:
    """Call Claude Haiku synchronously and return the response text."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text.strip()


def _content_hash(text: str) -> str:
    """Return first 16 chars of SHA-256 for cache key invalidation."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def summarize_archive_prompts(prompts_text: str, count: int) -> str:
    """Summarize the most recent archive prompts.

    TTL: 24 hours.  The cache key includes a content hash, so it
    auto-invalidates whenever the archive content changes.  If no new
    prompts have appeared, the cached summary is returned instantly
    without calling the API.
    """
    h = _content_hash(prompts_text)
    cache_key = f"summary:archive:{h}"

    cached = CacheService.get(cache_key)
    if cached:
        return cached

    system = (
        "You are a concise summarizer for JAIGP, a journal for AI-generated papers. "
        f"You are summarizing the last {count} building prompts from the archive. "
        "These prompts are instructions from the journal's creators to an AI assistant, "
        "directing what features, rules, and procedures the journal should implement. "
        "They are NOT prompts for generating papers — they govern the journal's development. "
        "Summarize in 2-3 sentences what was built and the main themes. Be matter-of-fact."
    )
    result = await asyncio.to_thread(_call_claude_sync, system, prompts_text)
    CacheService.set(cache_key, result, timeout=86400)  # 24h — hash handles invalidation
    return result


async def summarize_community_prompts(prompts_text: str, count: int) -> str:
    """Summarize the community suggestions feed. TTL: 10 min."""
    h = _content_hash(prompts_text)
    cache_key = f"summary:community:{h}"

    cached = CacheService.get(cache_key)
    if cached:
        return cached

    system = (
        "You are a concise summarizer for JAIGP, a journal for AI-generated papers. "
        f"You are summarizing the last {count} community thread{'s' if count != 1 else ''}, "
        "each containing a post and its replies. "
        "Posts are tagged as [Prompt], [Rule], or [Comment]. "
        "Summarize the main topics, themes, and any emerging consensus in 2-3 sentences. Be matter-of-fact. "
        "Never complain about insufficient content — just summarize whatever is provided."
    )
    result = await asyncio.to_thread(_call_claude_sync, system, prompts_text)
    CacheService.set(cache_key, result, timeout=600)
    return result


async def summarize_discussion(posts_text: str, count: int) -> str:
    """Summarize the discussion feed. TTL: 10 min."""
    h = _content_hash(posts_text)
    cache_key = f"summary:discussion:{h}"

    cached = CacheService.get(cache_key)
    if cached:
        return cached

    system = (
        "You are a concise summarizer for JAIGP, a journal for AI-generated papers. "
        f"You are summarizing {'the only discussion post so far' if count == 1 else f'the last {count} discussion posts'}. "
        "Summarize the main topics in 2-3 sentences. Be matter-of-fact. "
        "Never complain about insufficient content — just summarize whatever is provided."
    )
    result = await asyncio.to_thread(_call_claude_sync, system, posts_text)
    CacheService.set(cache_key, result, timeout=600)
    return result
