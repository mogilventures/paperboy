"""Tests for provider selection and API-surface handling in LLMClient.

These tests never call a real API: ``AsyncOpenAI`` is replaced with a fake that
records constructor kwargs and returns canned responses. They cover:

- OpenAI default behavior (Responses API) is preserved.
- Fireworks selection wires api_key/base_url/model and defaults to
  chat_completions.
- Fireworks without a key fails fast with a clear error.
- chat_completions extraction reads ``choices[0].message.content``.
- LLM_API_MODE override is honored.
"""
import asyncio
from types import SimpleNamespace

import pytest

import src.config as config_module
from src import llm_client as llm_module
from src.llm_client import LLMClient


# --------------------------------------------------------------------------
# Fakes for the OpenAI-compatible async client
# --------------------------------------------------------------------------
class _FakeResponses:
    def __init__(self, recorder):
        self._recorder = recorder

    async def create(self, **kwargs):
        self._recorder["responses_calls"].append(kwargs)
        return SimpleNamespace(output_text='{"articles": []}')


class _FakeChatCompletions:
    def __init__(self, recorder):
        self._recorder = recorder

    async def create(self, **kwargs):
        self._recorder["chat_calls"].append(kwargs)
        message = SimpleNamespace(content='{"articles": []}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeAsyncOpenAI:
    """Records constructor kwargs and exposes fake responses/chat endpoints."""

    last_init_kwargs = None

    def __init__(self, **kwargs):
        FakeAsyncOpenAI.last_init_kwargs = kwargs
        self.recorder = {"responses_calls": [], "chat_calls": []}
        self.responses = _FakeResponses(self.recorder)
        self.chat = SimpleNamespace(completions=_FakeChatCompletions(self.recorder))


@pytest.fixture
def fake_openai(monkeypatch):
    """Patch AsyncOpenAI in the llm_client module with the recording fake."""
    FakeAsyncOpenAI.last_init_kwargs = None
    monkeypatch.setattr(llm_module, "AsyncOpenAI", FakeAsyncOpenAI)
    return FakeAsyncOpenAI


def _set_provider(monkeypatch, **overrides):
    """Override fields on the live settings singleton for the duration of a test."""
    for name, value in overrides.items():
        monkeypatch.setattr(config_module.settings, name, value, raising=False)


# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------
def test_openai_provider_defaults(fake_openai, monkeypatch):
    _set_provider(
        monkeypatch,
        llm_provider="openai",
        llm_api_mode=None,
        openai_api_key="sk-openai",
        openai_model="gpt-4o",
    )

    client = LLMClient()

    assert client.provider == "openai"
    assert client.model == "gpt-4o"
    assert client.api_mode == "responses"  # OpenAI default surface
    assert fake_openai.last_init_kwargs == {"api_key": "sk-openai"}
    # No base_url override for OpenAI.
    assert "base_url" not in fake_openai.last_init_kwargs


def test_fireworks_provider_wires_base_url_and_model(fake_openai, monkeypatch):
    _set_provider(
        monkeypatch,
        llm_provider="fireworks",
        llm_api_mode=None,
        fireworks_api_key="fw-secret",
        fireworks_model="accounts/fireworks/models/llama-v3p1-70b-instruct",
        fireworks_base_url="https://api.fireworks.ai/inference/v1",
    )

    client = LLMClient()

    assert client.provider == "fireworks"
    assert client.model == "accounts/fireworks/models/llama-v3p1-70b-instruct"
    assert client.api_mode == "chat_completions"  # Fireworks default surface
    assert fake_openai.last_init_kwargs["api_key"] == "fw-secret"
    assert fake_openai.last_init_kwargs["base_url"] == "https://api.fireworks.ai/inference/v1"


def test_fireworks_without_key_fails_fast(fake_openai, monkeypatch):
    _set_provider(
        monkeypatch,
        llm_provider="fireworks",
        llm_api_mode=None,
        fireworks_api_key=None,
    )

    with pytest.raises(ValueError) as excinfo:
        LLMClient()

    assert "FIREWORKS_API_KEY" in str(excinfo.value)


def test_openai_without_key_fails_fast(fake_openai, monkeypatch):
    _set_provider(
        monkeypatch,
        llm_provider="openai",
        llm_api_mode=None,
        openai_api_key=None,
    )

    with pytest.raises(ValueError) as excinfo:
        LLMClient()

    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_unsupported_provider_raises(fake_openai, monkeypatch):
    _set_provider(monkeypatch, llm_provider="anthropic", llm_api_mode=None)
    with pytest.raises(ValueError):
        LLMClient()


def test_api_mode_override_honored(fake_openai, monkeypatch):
    # Force OpenAI to use chat_completions explicitly.
    _set_provider(
        monkeypatch,
        llm_provider="openai",
        llm_api_mode="chat_completions",
        openai_api_key="sk-openai",
        openai_model="gpt-4o",
    )
    client = LLMClient()
    assert client.api_mode == "chat_completions"


def test_invalid_api_mode_raises(fake_openai, monkeypatch):
    _set_provider(
        monkeypatch,
        llm_provider="openai",
        llm_api_mode="grpc",
        openai_api_key="sk-openai",
    )
    with pytest.raises(ValueError):
        LLMClient()


# --------------------------------------------------------------------------
# Extraction paths
# --------------------------------------------------------------------------
def test_chat_completions_extraction(fake_openai, monkeypatch):
    _set_provider(
        monkeypatch,
        llm_provider="fireworks",
        llm_api_mode=None,
        fireworks_api_key="fw-secret",
    )
    client = LLMClient()

    async def fake_create(**kwargs):
        message = SimpleNamespace(content="hello from fireworks")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(client.client.chat.completions, "create", fake_create)

    result = asyncio.run(client._raw_completion("sys", "user", 0.3))
    assert result == "hello from fireworks"


def test_responses_extraction(fake_openai, monkeypatch):
    _set_provider(
        monkeypatch,
        llm_provider="openai",
        llm_api_mode=None,
        openai_api_key="sk-openai",
    )
    client = LLMClient()

    async def fake_create(**kwargs):
        # Responses API combines system+user into a single input string.
        assert "sys" in kwargs["input"] and "user" in kwargs["input"]
        return SimpleNamespace(output_text="hello from openai")

    monkeypatch.setattr(client.client.responses, "create", fake_create)

    result = asyncio.run(client._raw_completion("sys", "user", 0.3))
    assert result == "hello from openai"


def test_strip_code_fences():
    assert LLMClient._strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert LLMClient._strip_code_fences('```\nplain\n```') == "plain"
    assert LLMClient._strip_code_fences('{"a": 1}') == '{"a": 1}'
    assert LLMClient._strip_code_fences("") == ""
