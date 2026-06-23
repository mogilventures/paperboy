"""Regression tests for the 2026-06-23 ranking shortfall.

The incident produced callbacks reading
``Ranking failed: RetryError[<Future ... raised AttributeError>]``. Root cause:
a malformed chat-completions response (``message.content`` was None / a list of
parts) hit ``.strip()``/``.startswith()`` and raised AttributeError, which
tenacity then buried inside a RetryError. These tests pin the defensive
behavior: clear ValueErrors or normalized strings, and an unwrapped, actionable
message at the ranking layer.
"""
import asyncio
from types import SimpleNamespace

import pytest

import src.config as config_module
from src import llm_client as llm_module
from src.llm_client import LLMClient, summarize_exception
from tenacity import RetryError, Future


class _FakeAsyncOpenAI:
    def __init__(self, **kwargs):
        self.responses = SimpleNamespace(create=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=None))


@pytest.fixture
def chat_client(monkeypatch):
    """An LLMClient wired to chat_completions with a no-op fake transport."""
    monkeypatch.setattr(llm_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(config_module.settings, "llm_provider", "fireworks", raising=False)
    monkeypatch.setattr(config_module.settings, "llm_api_mode", None, raising=False)
    monkeypatch.setattr(config_module.settings, "fireworks_api_key", "fw-test", raising=False)
    return LLMClient()


def _chat_response(content):
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


# --------------------------------------------------------------------------
# _extract_chat_content: the exact shapes that caused the incident
# --------------------------------------------------------------------------
def test_content_none_raises_clear_valueerror(chat_client):
    with pytest.raises(ValueError) as excinfo:
        chat_client._extract_chat_content(_chat_response(None))
    assert "content=None" in str(excinfo.value)
    assert not isinstance(excinfo.value, AttributeError)


def test_content_list_of_strings_is_normalized(chat_client):
    result = chat_client._extract_chat_content(_chat_response(["foo", "bar"]))
    assert result == "foobar"


def test_content_list_of_part_dicts_is_normalized(chat_client):
    parts = [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]
    result = chat_client._extract_chat_content(_chat_response(parts))
    assert result == "hello world"


def test_content_empty_list_raises_valueerror(chat_client):
    with pytest.raises(ValueError):
        chat_client._extract_chat_content(_chat_response([]))


def test_missing_choices_raises_valueerror(chat_client):
    with pytest.raises(ValueError) as excinfo:
        chat_client._extract_chat_content(SimpleNamespace(choices=[]))
    assert "no choices" in str(excinfo.value)


def test_missing_message_raises_valueerror(chat_client):
    resp = SimpleNamespace(choices=[SimpleNamespace(message=None)])
    with pytest.raises(ValueError) as excinfo:
        chat_client._extract_chat_content(resp)
    assert "no message" in str(excinfo.value)


def test_unexpected_content_type_raises_valueerror(chat_client):
    with pytest.raises(ValueError) as excinfo:
        chat_client._extract_chat_content(_chat_response(12345))
    assert "unexpected type" in str(excinfo.value)


def test_string_content_passthrough(chat_client):
    assert chat_client._extract_chat_content(_chat_response("plain text")) == "plain text"


def test_raw_completion_chat_none_content_raises_valueerror(chat_client):
    async def fake_create(**kwargs):
        return _chat_response(None)

    chat_client.client.chat.completions.create = fake_create
    with pytest.raises(ValueError):
        asyncio.run(chat_client._raw_completion("sys", "user", 0.3))


# --------------------------------------------------------------------------
# RetryError unwrapping
# --------------------------------------------------------------------------
def _retry_error(exc):
    fut = Future(1)
    fut.set_exception(exc)
    return RetryError(fut)


def test_summarize_unwraps_retry_error():
    inner = AttributeError("'NoneType' object has no attribute 'strip'")
    summary = summarize_exception(_retry_error(inner))
    assert "AttributeError" in summary
    assert "strip" in summary
    assert "Future" not in summary  # the opaque RetryError repr is gone


def test_summarize_plain_exception():
    summary = summarize_exception(ValueError("boom"))
    assert summary == "ValueError: boom"


def test_process_ranking_response_surfaces_underlying_cause(chat_client, monkeypatch):
    """A RetryError-wrapped AttributeError becomes an actionable callback error."""
    inner = AttributeError("'NoneType' object has no attribute 'strip'")

    async def boom(*args, **kwargs):
        raise _retry_error(inner)

    monkeypatch.setattr(chat_client, "_call_llm_structured", boom)

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(chat_client._process_ranking_response("sys", "user", 5, "paper"))

    msg = str(excinfo.value)
    assert msg.startswith("Ranking failed:")
    assert "AttributeError" in msg and "strip" in msg
    assert "Future" not in msg
