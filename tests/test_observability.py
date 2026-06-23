"""Tests for the optional Sentry instrumentation.

A fake ``sentry_sdk`` module is injected so we exercise our wiring (PII flags,
before_send, tag scoping) without installing or contacting Sentry.
"""
import sys
from types import SimpleNamespace

import pytest

from src import observability


class _FakeScope:
    def __init__(self):
        self.tags = {}

    def set_tag(self, key, value):
        self.tags[key] = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeSentry:
    def __init__(self):
        self.init_kwargs = None
        self.captured = []
        self.scope = _FakeScope()

    def init(self, **kwargs):
        self.init_kwargs = kwargs

    def new_scope(self):
        return self.scope

    def capture_exception(self, exc):
        self.captured.append(exc)


@pytest.fixture
def fake_sentry(monkeypatch):
    fake = _FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setattr(observability, "_initialized", False)
    return fake


def test_init_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(observability, "_initialized", False)
    assert observability.init_sentry() is False


def test_init_with_dsn_sets_pii_safe_options(fake_sentry, monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://k@o0.ingest.sentry.io/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")

    assert observability.init_sentry() is True
    kwargs = fake_sentry.init_kwargs
    assert kwargs["send_default_pii"] is False
    assert kwargs["include_local_variables"] is False
    assert kwargs["max_request_body_size"] == "never"
    assert kwargs["environment"] == "staging"
    assert callable(kwargs["before_send"])


def test_before_send_strips_user_and_request():
    event = {
        "user": {"email": "noah@example.com"},
        "request": {"data": "secret"},
        "contexts": {"request": {"body": "x"}, "runtime": {"name": "py"}},
        "message": "kept",
    }
    cleaned = observability._before_send(event, {})
    assert "user" not in cleaned
    assert "request" not in cleaned
    assert "request" not in cleaned["contexts"]
    assert cleaned["contexts"]["runtime"] == {"name": "py"}
    assert cleaned["message"] == "kept"


def test_capture_exception_noop_when_uninitialized(fake_sentry, monkeypatch):
    monkeypatch.setattr(observability, "_initialized", False)
    observability.capture_exception(ValueError("x"), stage="ranking")
    assert fake_sentry.captured == []


def test_capture_exception_tags_and_reports_when_initialized(fake_sentry, monkeypatch):
    monkeypatch.setattr(observability, "_initialized", True)
    exc = ValueError("boom")
    observability.capture_exception(exc, stage="ranking", task_id="abc", skip=None)
    assert fake_sentry.captured == [exc]
    assert fake_sentry.scope.tags == {"stage": "ranking", "task_id": "abc"}
