"""Integration tests for adapters around the existing digest services."""

import asyncio
from datetime import date

from src.models import DigestStatus, TaskStatus
from src.orchestration import Profile
from src.orchestration_adapters import BackendDigestGenerator, BackendSourceFetcher


class RecordingStateManager:
    def __init__(self) -> None:
        self.created = []
        self.status = DigestStatus(
            status=TaskStatus.COMPLETED,
            message="done",
            result="<html>generated</html>",
        )

    async def create_task_with_source_date(self, *args, **kwargs) -> None:
        self.created.append((args, kwargs))

    async def get_task(self, task_id: str) -> DigestStatus:
        return self.status


class RecordingFetchStateManager:
    def __init__(self) -> None:
        self.created = []
        self.updated = []

    async def create_fetch_task(self, *args, **kwargs) -> None:
        self.created.append((args, kwargs))

    async def update_fetch_task(self, *args, **kwargs) -> None:
        self.updated.append((args, kwargs))


class ExistingSourceService:
    async def fetch_and_store_sources(self, *args, **kwargs):
        return {
            "status": "completed",
            "arxiv_count": 8,
            "news_count": 3,
        }


def test_backend_source_fetcher_completes_tracking_for_cached_sources() -> None:
    state_manager = RecordingFetchStateManager()
    fetcher = BackendSourceFetcher(
        state_manager=state_manager,
        fetch_service=ExistingSourceService(),
        timeout_seconds=30,
    )

    counts = asyncio.run(fetcher.fetch(date(2026, 7, 9)))

    assert counts == {"arxiv_count": 8, "news_count": 3}
    task_id = state_manager.created[0][0][0]
    assert state_manager.updated[-1] == (
        (task_id, "completed"),
        {"result": counts},
    )


class RecordingDigestService:
    def __init__(self) -> None:
        self.calls = []

    async def generate_digest(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


def test_backend_generator_rejects_completed_error_text_as_an_email_digest() -> None:
    state_manager = RecordingStateManager()
    state_manager.status = DigestStatus(
        status=TaskStatus.COMPLETED,
        message="Digest generated successfully",
        result="No pre-fetched sources available for date",
    )
    generator = BackendDigestGenerator(
        state_manager=state_manager,
        digest_service=RecordingDigestService(),
        timeout_seconds=30,
    )
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Reader",
        title=None,
        goals="AI",
        interests=None,
    )

    asyncio.run(generator.prepare(profile, date(2026, 7, 9), "task-1"))
    try:
        asyncio.run(generator.generate(profile, date(2026, 7, 9), "task-1"))
    except RuntimeError as exc:
        assert "did not complete" in str(exc)
    else:
        raise AssertionError("plain error text must not be sent as HTML email")


def test_backend_generator_creates_user_linked_task_and_calls_service_directly() -> None:
    state_manager = RecordingStateManager()
    digest_service = RecordingDigestService()
    generator = BackendDigestGenerator(
        state_manager=state_manager,
        digest_service=digest_service,
        timeout_seconds=30,
    )
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Reader",
        title="Researcher",
        goals="Track AI",
        interests="AI policy",
    )

    asyncio.run(generator.prepare(profile, date(2026, 7, 9), "task-1"))
    result = asyncio.run(
        generator.generate(profile, date(2026, 7, 9), "task-1")
    )

    assert result.task_id == "task-1"
    assert result.html == "<html>generated</html>"
    _, create_kwargs = state_manager.created[0]
    assert create_kwargs["user_id"] == "user-1"
    assert create_kwargs["source_date"] == "2026-07-09"
    assert create_kwargs["callback_url"] is None
    service_args, service_kwargs = digest_service.calls[0]
    assert service_args[0] == "task-1"
    assert service_args[1]["news_interest"] == "AI policy"
    assert service_kwargs == {
        "callback_url": None,
        "top_n_articles": 5,
        "top_n_news": 5,
        "source_date": "2026-07-09",
    }
