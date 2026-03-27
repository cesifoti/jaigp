#!/usr/bin/env python3
"""Classify archive prompts as 'key' or 'procedural' using Claude Haiku.

Key prompts embody ideas, introduce concepts, propose features with purpose,
or represent starting points for significant work.

Procedural prompts are about debugging, minor tweaks, deployment mechanics,
error reports, or executing details of an already-established idea.

Results are cached in data/prompt_classifications.json so the LLM is only
called for new/changed prompts.
"""
import json
import os
import hashlib
import sys

# Add parent dir to path and load .env from project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

import config

ARCHIVE_PATH = "/var/www/ai_journal/data/prompts_archive.json"
CACHE_PATH = "/var/www/ai_journal/data/prompt_classifications.json"

SYSTEM_PROMPT = """You classify prompts used to build a journal (JAIGP) as either "key" or "procedural".

Be EXTREMELY selective with "key". Out of ~250 prompts, only about 8-12 should be key. A key prompt is a FOUNDING MOMENT — the first time a major concept or feature is introduced. Everything else is procedural, including:

KEY prompts (very rare — only the birth of a major idea):
- The FIRST prompt that introduces a brand new concept or major feature
- Prompts that fundamentally change the direction or architecture of the project
- A prompt is NOT key just because it's long, detailed, or proposes something useful

PROCEDURAL prompts (the vast majority):
- Bug reports, error fixing, debugging
- UI tweaks, styling changes, font/color/layout adjustments
- Deployment, infrastructure, server management
- Follow-up refinement of an already-introduced feature
- Adding details to an existing concept (even if substantial)
- Security fixes, legal updates, copy changes
- Improvements, optimizations, cleanup
- Social media, communication, promotional content
- Adding a license, updating a readme, organizing navigation

Examples of KEY (founding moments):
- "I would like to create a feature called Open Prompt..." → key (birth of the Open Prompt concept)
- "Can we do a couple of more things. One is that I want to have an admin console..." → key (birth of admin system)
- "let's continue to working on the dev branch. We should now introduce a multistage peer review system..." → key (birth of the review pipeline)
- "Let's discuss about the prompt and the discussion pages. Do we need both?" → key (architectural decision to merge feeds)

Examples of PROCEDURAL (everything else):
- "We want to do a few things to make sure the site is not spammed..." → procedural (detail work on an existing system)
- "Let's add load balancing now..." → procedural (infrastructure)
- "I would like us to now move the development server to production..." → procedural (deployment)
- "Let's now change the homepage display for papers..." → procedural (UI reorganization)
- "Now we need to add a comprehensive notification logic..." → procedural (feature detail, not founding concept)
- "The broken heart icon is unclear..." → procedural (visual tweak)
- "We have made the repository public..." → procedural (admin task)
- "I think this is mostly good. For the hero, I would prefer..." → procedural (feedback/refinement)
- "Let's make sure the site satisfies security standards..." → procedural (compliance work)
- "The summarize feed feature needs to incorporate both..." → procedural (refinement of existing feature)

For each prompt, respond with ONLY "key" or "procedural", one per line, matching the input order."""


def get_prompt_hash(text):
    """Hash a prompt for cache invalidation."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_cache():
    """Load cached classifications."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    """Save classifications cache."""
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def classify_batch(prompts_batch):
    """Classify a batch of prompts using Claude Haiku."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # Build numbered list
    lines = []
    for i, p in enumerate(prompts_batch):
        # Truncate to first 300 chars for classification
        text = p["text"][:300].replace("\n", " ")
        lines.append(f"{i+1}. {text}")

    user_msg = "Classify each prompt as 'key' or 'procedural':\n\n" + "\n".join(lines)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=len(prompts_batch) * 15,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    result_text = response.content[0].text.strip()
    classifications = []
    for line in result_text.split("\n"):
        line = line.strip().lower()
        # Extract just key/procedural from lines like "1. key" or "key"
        if "key" in line:
            classifications.append("key")
        elif "procedural" in line:
            classifications.append("procedural")

    return classifications


def main():
    # Load archive
    with open(ARCHIVE_PATH) as f:
        archive = json.load(f)

    all_prompts = []
    for session in archive["sessions"]:
        for p in session["prompts"]:
            all_prompts.append(p)
    all_prompts.sort(key=lambda p: p["global_index"])

    print(f"Total prompts: {len(all_prompts)}")

    # Load cache
    cache = load_cache()

    # Find prompts that need classification
    to_classify = []
    for p in all_prompts:
        h = get_prompt_hash(p["text"])
        if h not in cache:
            to_classify.append(p)

    print(f"Already classified: {len(all_prompts) - len(to_classify)}")
    print(f"Need classification: {len(to_classify)}")

    if not to_classify:
        print("All prompts already classified.")
    else:
        # Classify in batches of 30
        batch_size = 30
        for i in range(0, len(to_classify), batch_size):
            batch = to_classify[i:i + batch_size]
            print(f"  Classifying batch {i//batch_size + 1} ({len(batch)} prompts)...")
            try:
                results = classify_batch(batch)
                for j, p in enumerate(batch):
                    if j < len(results):
                        h = get_prompt_hash(p["text"])
                        cache[h] = results[j]
                    else:
                        # Fallback if LLM returned fewer results
                        h = get_prompt_hash(p["text"])
                        cache[h] = "procedural"
            except Exception as e:
                print(f"  Error: {e}")
                # Fallback: classify remaining as procedural
                for p in batch:
                    h = get_prompt_hash(p["text"])
                    if h not in cache:
                        cache[h] = "procedural"

        save_cache(cache)

    # Print summary
    key_count = sum(1 for p in all_prompts if cache.get(get_prompt_hash(p["text"])) == "key")
    proc_count = sum(1 for p in all_prompts if cache.get(get_prompt_hash(p["text"])) == "procedural")
    print(f"\nResults: {key_count} key, {proc_count} procedural")

    # Print sample
    print("\nSample classifications:")
    for p in all_prompts:
        idx = p["global_index"]
        if idx in [4, 19, 20, 22, 58, 60, 78, 100, 120, 160, 164, 166, 196, 220, 233, 242]:
            t = cache.get(get_prompt_hash(p["text"]), "?")
            text = p["text"][:80].replace("\n", " ")
            print(f"  #{idx:3d} [{t:10s}]: {text}...")


if __name__ == "__main__":
    main()
