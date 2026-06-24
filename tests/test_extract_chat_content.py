"""Focused tests for the reasoning_content fallback in _extract_chat_content.

Fireworks reasoning models (e.g. gpt-oss-120b) may return message.content as
None or empty while putting the actual answer in message.reasoning_content.
_extract_chat_content must fall back to reasoning_content instead of failing
(which previously opened the circuit breaker and degraded every digest).

These exercise _extract_chat_content directly with SimpleNamespace stubs; no
network or AsyncOpenAI mocking is needed since the method only reads
self.provider and the response shape.
"""
from types import SimpleNamespace

import pytest

from src.llm_client import LLMClient


def _client():
    """Build an LLMClient without running __init__ (only self.provider is used)."""
    client = LLMClient.__new__(LLMClient)
    client.provider = "fireworks"
    return client


def _response(content, reasoning_content=None):
    if reasoning_content is None:
        message = SimpleNamespace(content=content)
    else:
        message = SimpleNamespace(content=content, reasoning_content=reasoning_content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_content_none_falls_back_to_reasoning_content():
    resp = _response(None, reasoning_content="the answer")
    assert _client()._extract_chat_content(resp) == "the answer"


def test_empty_content_falls_back_to_reasoning_content():
    resp = _response("   ", reasoning_content="the answer")
    assert _client()._extract_chat_content(resp) == "the answer"


def test_both_empty_raises_valueerror():
    resp = _response(None, reasoning_content="")
    with pytest.raises(ValueError):
        _client()._extract_chat_content(resp)


def test_normal_content_returned_unchanged():
    resp = _response("normal text")
    assert _client()._extract_chat_content(resp) == "normal text"
