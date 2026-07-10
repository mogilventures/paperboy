"""Tests for provider-specific startup validation in ``validate_environment``.

These never start the app or touch a real service; they only exercise the
environment-variable checks. ``API_KEY`` is always required; the LLM key
requirement depends on ``LLM_PROVIDER`` (default ``openai``).
"""
import pytest

from src.main import validate_environment


def _clear_llm_env(monkeypatch):
    """Start from a clean slate for the vars this function inspects."""
    for var in (
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "FIREWORKS_API_KEY",
        "API_KEY",
        "ORCHESTRATION_ENABLED",
        "RESEND_API_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    # Supabase disabled so the function doesn't wander into that branch.
    monkeypatch.setenv("USE_SUPABASE", "false")


def test_openai_default_requires_openai_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k")
    # LLM_PROVIDER unset -> defaults to openai, OPENAI_API_KEY missing.
    with pytest.raises(RuntimeError) as excinfo:
        validate_environment()
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_openai_default_passes_with_openai_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    validate_environment()  # should not raise


def test_fireworks_requires_fireworks_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    # No FIREWORKS_API_KEY set.
    with pytest.raises(RuntimeError) as excinfo:
        validate_environment()
    assert "FIREWORKS_API_KEY" in str(excinfo.value)


def test_fireworks_passes_without_openai_key(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fw-secret")
    # Notably OPENAI_API_KEY is absent and this must still pass.
    validate_environment()  # should not raise


def test_unknown_provider_raises(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError) as excinfo:
        validate_environment()
    assert "anthropic" in str(excinfo.value)


def test_enabled_orchestration_requires_backend_only_credentials(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ORCHESTRATION_ENABLED", "true")

    with pytest.raises(RuntimeError) as excinfo:
        validate_environment()

    message = str(excinfo.value)
    assert "RESEND_API_KEY" in message
    assert "SUPABASE_SERVICE_ROLE_KEY" in message


def test_missing_api_key_reported(monkeypatch):
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    # API_KEY missing.
    with pytest.raises(RuntimeError) as excinfo:
        validate_environment()
    assert "API_KEY" in str(excinfo.value)
