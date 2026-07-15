"""Tests for the signup welcome email (migrated off Pipedream to Fly + Resend)."""

import asyncio
import json

import httpx

from src import main
from src.resend_email import ResendEmailSender
from src.welcome_email import WELCOME_SUBJECT, render_welcome_email


API_HEADERS = {"X-API-Key": "test-api-key"}


class RecordingWelcomeSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_welcome(self, *, to: str, idempotency_key: str, name=None) -> str:
        self.calls.append(
            {"to": to, "idempotency_key": idempotency_key, "name": name}
        )
        return "email-welcome-1"

    async def close(self) -> None:  # pragma: no cover - parity with real sender
        pass


def test_send_welcome_builds_expected_resend_request() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "email-welcome-1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    sender = ResendEmailSender(
        api_key="test-resend-key",
        from_address="Welcome <hello@paper-boy.app>",
        client=client,
    )

    email_id = asyncio.run(
        sender.send_welcome(
            to="new-user@example.com", idempotency_key="welcome:user-42"
        )
    )
    asyncio.run(client.aclose())

    assert email_id == "email-welcome-1"
    assert len(requests) == 1
    request = requests[0]
    assert request.url == "https://api.resend.com/emails"
    assert request.headers["authorization"] == "Bearer test-resend-key"
    assert request.headers["idempotency-key"] == "welcome:user-42"
    body = json.loads(request.content)
    assert body["from"] == "Welcome <hello@paper-boy.app>"
    assert body["to"] == ["new-user@example.com"]
    assert body["subject"] == WELCOME_SUBJECT
    assert body["html"] == render_welcome_email()
    assert body["tags"] == [{"name": "type", "value": "welcome"}]


def test_welcome_hook_schedules_send_for_new_profile() -> None:
    async def run():
        sender = RecordingWelcomeSender()
        main.app.state.welcome_email_sender = sender
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/hooks/welcome",
                headers=API_HEADERS,
                json={
                    "type": "INSERT",
                    "table": "profiles",
                    "record": {
                        "user_id": "user-42",
                        "email": "new-user@example.com",
                        "name": "Ada",
                    },
                },
            )
        return response, sender

    response, sender = asyncio.run(run())

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert sender.calls == [
        {
            "to": "new-user@example.com",
            "idempotency_key": "welcome:user-42",
            "name": None,
        }
    ]


def test_welcome_hook_skips_when_record_has_no_email() -> None:
    async def run():
        sender = RecordingWelcomeSender()
        main.app.state.welcome_email_sender = sender
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/hooks/welcome",
                headers=API_HEADERS,
                json={"type": "INSERT", "table": "profiles", "record": {}},
            )
        return response, sender

    response, sender = asyncio.run(run())

    assert response.status_code == 202
    assert response.json()["status"] == "skipped"
    assert sender.calls == []


def test_welcome_hook_requires_api_key() -> None:
    async def run():
        sender = RecordingWelcomeSender()
        main.app.state.welcome_email_sender = sender
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/hooks/welcome",
                json={"record": {"email": "x@example.com"}},
            )
        return response, sender

    response, sender = asyncio.run(run())

    assert response.status_code == 403
    assert sender.calls == []


def test_welcome_hook_unavailable_without_resend_config() -> None:
    async def run():
        main.app.state.welcome_email_sender = None
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/hooks/welcome",
                headers=API_HEADERS,
                json={"record": {"email": "x@example.com", "user_id": "u1"}},
            )

    response = asyncio.run(run())

    assert response.status_code == 503
