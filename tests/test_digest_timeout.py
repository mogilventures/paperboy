"""Regression tests for digest background-task timeout handling.

Incident on 2026-06-25: 27/50 digests failed with "Task timeout" at ~300s
because safe_background_task used settings.task_timeout, which was a stale Fly
secret (300) overriding fly.toml. Digest generation now uses a dedicated
settings.digest_task_timeout (default 900) and, on timeout, notifies the caller
via a failed webhook callback instead of leaving n8n waiting.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.main as main
from src.config import settings
from src.models import TaskStatus


@pytest.fixture
def app_state(monkeypatch):
    state = SimpleNamespace(
        digest_service=SimpleNamespace(generate_digest=AsyncMock()),
        state_manager=SimpleNamespace(update_task=AsyncMock()),
    )
    monkeypatch.setattr(main.app, "state", state)
    return state


def test_digest_timeout_uses_dedicated_setting_not_task_timeout(app_state, monkeypatch):
    """Capture the timeout value passed to asyncio.timeout; it must be the
    dedicated digest_task_timeout, not the (stale) task_timeout."""
    monkeypatch.setattr(settings, "task_timeout", 300)
    monkeypatch.setattr(settings, "digest_task_timeout", 900)

    captured = {}
    real_timeout = asyncio.timeout
    monkeypatch.setattr(
        main.asyncio, "timeout",
        lambda value: captured.__setitem__("value", value) or real_timeout(value),
    )

    asyncio.run(main.safe_background_task("task-1", {"name": "x"}, None))

    assert captured["value"] == 900


def test_timeout_marks_failed_and_sends_callback(app_state, monkeypatch):
    """On timeout: task marked FAILED with timeout-seconds message + failed callback."""
    monkeypatch.setattr(settings, "digest_task_timeout", 900)
    app_state.digest_service.generate_digest = AsyncMock(side_effect=asyncio.TimeoutError())

    sent = AsyncMock()
    monkeypatch.setattr(main, "send_webhook_callback", sent)

    callback_url = "https://n8n.example.com/hook"
    asyncio.run(main.safe_background_task("task-2", {"name": "x"}, callback_url))

    # Task updated as failed with the configured timeout in the message.
    app_state.state_manager.update_task.assert_awaited_once()
    _, status = app_state.state_manager.update_task.await_args.args
    assert status.status == TaskStatus.FAILED
    assert "900 seconds" in status.message

    # Caller notified of the failure.
    sent.assert_awaited_once()
    args = sent.await_args.args
    assert args[0] == callback_url
    assert args[1] == "task-2"
    assert args[2] == "failed"


def test_timeout_without_callback_url_does_not_send(app_state, monkeypatch):
    monkeypatch.setattr(settings, "digest_task_timeout", 900)
    app_state.digest_service.generate_digest = AsyncMock(side_effect=asyncio.TimeoutError())

    sent = AsyncMock()
    monkeypatch.setattr(main, "send_webhook_callback", sent)

    asyncio.run(main.safe_background_task("task-3", {"name": "x"}, None))

    app_state.state_manager.update_task.assert_awaited_once()
    sent.assert_not_awaited()
