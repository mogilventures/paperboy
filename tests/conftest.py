"""Shared pytest fixtures and environment bootstrap.

``src.config`` instantiates a ``Settings()`` singleton at import time and
requires ``OPENAI_API_KEY``. Set synthetic env vars BEFORE any src import so
collection never touches real credentials or external services.
"""
import os

# Synthetic, non-secret defaults. Never real keys.
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("NEWS_ENABLED", "false")
