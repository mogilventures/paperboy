#!/usr/bin/env python3
"""Tiny, fixture-only smoke harness for the configured LLM provider.

Exercises ``LLMClient.rank_articles`` against a small SYNTHETIC ranking task so
you can sanity-check a provider swap (OpenAI <-> Fireworks) end to end.

Safety guardrails:
- Uses only synthetic, public-shaped fixture data. No customer data, ever.
- Skips cleanly (exit 0) when the selected provider has no API key configured,
  so it is safe to run in CI or locally without credentials.
- Performs a real API call ONLY when a key is present. It does not hardcode any
  secret; credentials come from the environment / config.

Usage:
    # OpenAI (default)
    python3 scripts/eval_provider_smoke.py

    # Fireworks
    LLM_PROVIDER=fireworks FIREWORKS_API_KEY=... \
        FIREWORKS_MODEL=accounts/fireworks/models/llama-v3p1-70b-instruct \
        python3 scripts/eval_provider_smoke.py
"""
import asyncio
import os
import sys
import time

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Synthetic fixtures — entirely fabricated, no real users or sources.
SYNTHETIC_ARTICLES = [
    {
        "title": "Efficient Attention Mechanisms for Long-Context Transformers",
        "authors": ["A. Researcher", "B. Scientist"],
        "subject": "cs.LG",
        "abstract_url": "https://arxiv.org/abs/0000.00001",
        "type": "paper",
    },
    {
        "title": "A Survey of Vector Databases for Retrieval-Augmented Generation",
        "authors": ["C. Author"],
        "subject": "cs.IR",
        "abstract_url": "https://arxiv.org/abs/0000.00002",
        "type": "paper",
    },
    {
        "title": "Open-Source LLM Inference Gets 3x Cheaper",
        "authors": ["Synthetic Newsroom"],
        "subject": "news",
        "abstract_url": "https://example.com/news/llm-inference",
        "type": "news",
    },
]

SYNTHETIC_USER = {
    "name": "Test User",
    "title": "ML Engineer",
    "goals": "retrieval-augmented generation and efficient LLM inference",
}


def _provider_has_credentials() -> bool:
    from src.config import settings

    provider = (settings.llm_provider or "openai").lower()
    if provider == "fireworks":
        return bool(settings.fireworks_api_key)
    if provider == "openai":
        return bool(settings.openai_api_key and settings.openai_api_key != "test-openai-key")
    return False


async def _run() -> int:
    from src.config import settings
    from src.llm_client import LLMClient

    provider = (settings.llm_provider or "openai").lower()

    if not _provider_has_credentials():
        print(f"[skip] No usable credentials for provider '{provider}'. "
              "Set the provider API key to run a live smoke test.")
        return 0

    client = LLMClient()
    print(f"[info] provider={client.provider} model={client.model} "
          f"api_mode={client.api_mode}")

    start = time.time()
    try:
        ranked = await client.rank_articles(
            list(SYNTHETIC_ARTICLES), dict(SYNTHETIC_USER), top_n=2
        )
    except Exception as exc:  # noqa: BLE001 - smoke harness reports any failure
        print(f"[fail] ranking call raised: {type(exc).__name__}: {exc}")
        return 1
    elapsed = time.time() - start

    if not ranked:
        print(f"[fail] ranking returned no articles ({elapsed:.2f}s)")
        return 1

    print(f"[ok] ranked {len(ranked)} articles in {elapsed:.2f}s")
    for art in ranked:
        print(f"  - {art.relevance_score:>3}  {art.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
