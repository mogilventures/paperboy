"""Contract tests for Resend digest delivery."""

import asyncio
import json
from datetime import date

import httpx

from src.orchestration import AmbiguousEmailDelivery, Profile
from src.resend_email import ResendEmailSender


def test_resend_sender_uses_stable_idempotency_key_and_digest_metadata() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "email-123"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    sender = ResendEmailSender(
        api_key="test-resend-key",
        from_address="Paperboy Digest <digest@paper-boy.app>",
        client=client,
    )
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Ada",
        title="Researcher",
        goals="AI",
        interests=None,
    )

    email_id = asyncio.run(
        sender.send_digest(
            profile=profile,
            source_date=date(2026, 7, 9),
            task_id="task-1",
            html="<html>digest</html>",
        )
    )
    asyncio.run(client.aclose())

    assert email_id == "email-123"
    assert len(requests) == 1
    request = requests[0]
    assert request.url == "https://api.resend.com/emails"
    assert request.headers["authorization"] == "Bearer test-resend-key"
    assert request.headers["idempotency-key"] == "paperboy:2026-07-09:user-1"
    assert json.loads(request.content) == {
        "from": "Paperboy Digest <digest@paper-boy.app>",
        "to": ["reader@example.com"],
        "html": "<html>digest</html>",
        "subject": "Paperboy | Ada's Daily Digest",
        "tags": [{"name": "task_id", "value": "task-1"}],
    }


def test_transport_failure_is_reported_as_ambiguous_delivery() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection lost", request=request)

    async def no_wait(seconds: float) -> None:
        pass

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    sender = ResendEmailSender(
        api_key="test-resend-key",
        from_address="Paperboy <digest@paper-boy.app>",
        client=client,
        max_attempts=2,
        sleep=no_wait,
    )
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Ada",
        title=None,
        goals="AI",
        interests=None,
    )

    try:
        asyncio.run(
            sender.send_digest(
                profile=profile,
                source_date=date(2026, 7, 9),
                task_id="task-1",
                html="<html>digest</html>",
            )
        )
    except AmbiguousEmailDelivery:
        pass
    else:
        raise AssertionError("a lost provider receipt must remain ambiguous")
    asyncio.run(client.aclose())


def test_repeated_server_errors_remain_ambiguous_after_retries() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "try again"})

    async def no_wait(seconds: float) -> None:
        pass

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    sender = ResendEmailSender(
        api_key="test-resend-key",
        from_address="Paperboy <digest@paper-boy.app>",
        client=client,
        max_attempts=2,
        sleep=no_wait,
    )
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Ada",
        title=None,
        goals="AI",
        interests=None,
    )

    try:
        asyncio.run(
            sender.send_digest(
                profile=profile,
                source_date=date(2026, 7, 9),
                task_id="task-1",
                html="<html>digest</html>",
            )
        )
    except AmbiguousEmailDelivery:
        pass
    else:
        raise AssertionError("repeated provider errors must remain ambiguous")
    asyncio.run(client.aclose())


def test_resend_retry_reuses_the_same_idempotency_key() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"message": "try again"})
        return httpx.Response(200, json={"id": "email-123"})

    async def no_wait(seconds: float) -> None:
        sleeps.append(seconds)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    sender = ResendEmailSender(
        api_key="test-resend-key",
        from_address="Paperboy <digest@paper-boy.app>",
        client=client,
        retry_delay_seconds=5,
        sleep=no_wait,
    )
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Ada",
        title=None,
        goals="AI",
        interests=None,
    )

    email_id = asyncio.run(
        sender.send_digest(
            profile=profile,
            source_date=date(2026, 7, 9),
            task_id="task-1",
            html="<html>digest</html>",
        )
    )
    asyncio.run(client.aclose())

    assert email_id == "email-123"
    assert sleeps == [5]
    assert [r.headers["idempotency-key"] for r in requests] == [
        "paperboy:2026-07-09:user-1",
        "paperboy:2026-07-09:user-1",
    ]
