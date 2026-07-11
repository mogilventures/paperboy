"""Behavioral tests for backend-hosted daily digest orchestration."""

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from src.orchestration import (
    DailyDigestOrchestrator,
    DeliveryRecord,
    DeliveryStatus,
    GeneratedDigest,
    Profile,
)


class RecordingRepository:
    def __init__(self, profiles: list[Profile]) -> None:
        self.profiles = profiles
        self.claimed = True
        self.deliveries: dict[str, DeliveryRecord] = {}
        self.started_profiles: list[tuple[str, str]] = []
        self.completed_profiles: list[tuple[str, str, str]] = []
        self.finished_runs = []

    async def claim_run(self, source_date: date, *, retry_failed: bool) -> bool:
        return self.claimed

    async def list_eligible_profiles(self) -> list[Profile]:
        return self.profiles

    async def get_or_create_delivery(
        self, source_date: date, profile: Profile
    ) -> DeliveryRecord:
        return self.deliveries.setdefault(
            profile.user_id,
            DeliveryRecord(
                source_date=source_date,
                profile_id=profile.id,
                user_id=profile.user_id,
                status=DeliveryStatus.PENDING,
            ),
        )

    async def mark_delivery_generating(
        self, source_date: date, user_id: str, task_id: str
    ) -> None:
        self.deliveries[user_id] = replace(
            self.deliveries[user_id],
            status=DeliveryStatus.GENERATING,
            task_id=task_id,
        )

    async def mark_delivery_generated(
        self, source_date: date, user_id: str, task_id: str
    ) -> None:
        self.deliveries[user_id] = replace(
            self.deliveries[user_id],
            status=DeliveryStatus.GENERATED,
            task_id=task_id,
        )

    async def mark_delivery_sending(
        self, source_date: date, user_id: str
    ) -> None:
        self.deliveries[user_id] = replace(
            self.deliveries[user_id],
            status=DeliveryStatus.SENDING,
        )

    async def mark_delivery_sent(
        self, source_date: date, user_id: str, email_id: str
    ) -> None:
        self.deliveries[user_id] = replace(
            self.deliveries[user_id],
            status=DeliveryStatus.SENT,
            email_id=email_id,
        )

    async def mark_delivery_ambiguous(
        self, source_date: date, user_id: str, error: str
    ) -> None:
        self.deliveries[user_id] = replace(
            self.deliveries[user_id],
            status=DeliveryStatus.AMBIGUOUS,
            error=error,
        )

    async def mark_delivery_failed(
        self, source_date: date, user_id: str, error: str
    ) -> None:
        self.deliveries[user_id] = replace(
            self.deliveries[user_id],
            status=DeliveryStatus.FAILED,
            error=error,
        )

    async def start_profile(
        self, source_date: date, profile_id: str, task_id: str
    ) -> None:
        self.started_profiles.append((profile_id, task_id))

    async def complete_profile(
        self, source_date: date, profile_id: str, task_id: str, html: str
    ) -> None:
        self.completed_profiles.append((profile_id, task_id, html))

    async def heartbeat_run(self, source_date: date) -> None:
        pass

    async def finish_run(self, summary) -> None:
        self.finished_runs.append(summary)

    async def fail_run(self, source_date: date, error: str) -> None:
        raise AssertionError(f"run unexpectedly failed: {error}")


class RecordingSourceFetcher:
    def __init__(self) -> None:
        self.dates: list[date] = []

    async def fetch(self, source_date: date) -> dict[str, int]:
        self.dates.append(source_date)
        return {"arxiv_count": 10, "news_count": 5}


class RecordingDigestGenerator:
    def __init__(self) -> None:
        self.prepared: list[tuple[Profile, date, str]] = []
        self.calls: list[tuple[Profile, date, str]] = []

    async def prepare(
        self, profile: Profile, source_date: date, task_id: str
    ) -> None:
        self.prepared.append((profile, source_date, task_id))

    async def generate(
        self, profile: Profile, source_date: date, task_id: str
    ) -> GeneratedDigest:
        self.calls.append((profile, source_date, task_id))
        return GeneratedDigest(task_id=task_id, html="<html>digest</html>")

    async def recover(self, task_id: str) -> GeneratedDigest | None:
        return None


class RecordingEmailSender:
    def __init__(self) -> None:
        self.calls = []

    async def send_digest(
        self, *, profile: Profile, source_date: date, task_id: str, html: str
    ) -> str:
        self.calls.append((profile, source_date, task_id, html))
        return "email-1"


def test_daily_run_fetches_generates_links_and_emails_each_profile() -> None:
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Reader",
        title="Researcher",
        goals="Track AI research",
        interests="AI policy",
    )
    repository = RecordingRepository([profile])
    fetcher = RecordingSourceFetcher()
    generator = RecordingDigestGenerator()
    email_sender = RecordingEmailSender()
    orchestrator = DailyDigestOrchestrator(
        repository=repository,
        source_fetcher=fetcher,
        digest_generator=generator,
        email_sender=email_sender,
        profile_start_interval_seconds=0,
        task_id_factory=lambda: "task-1",
    )

    summary = asyncio.run(orchestrator.run(date(2026, 7, 9)))

    assert summary.status == "completed"
    assert summary.total_profiles == 1
    assert summary.sent_count == 1
    assert summary.failed_count == 0
    assert fetcher.dates == [date(2026, 7, 9)]
    assert generator.prepared == [(profile, date(2026, 7, 9), "task-1")]
    assert generator.calls == [(profile, date(2026, 7, 9), "task-1")]
    assert repository.started_profiles == [("profile-1", "task-1")]
    assert repository.completed_profiles == [
        ("profile-1", "task-1", "<html>digest</html>")
    ]
    assert email_sender.calls == [
        (profile, date(2026, 7, 9), "task-1", "<html>digest</html>")
    ]
    assert repository.deliveries["user-1"].status is DeliveryStatus.SENT


def test_profiles_launch_at_configured_cadence_with_bounded_overlap() -> None:
    first = Profile(
        id="profile-1",
        user_id="user-1",
        email="one@example.com",
        name="One",
        title=None,
        goals="AI",
        interests=None,
    )
    second = replace(
        first,
        id="profile-2",
        user_id="user-2",
        email="two@example.com",
        name="Two",
    )
    repository = RecordingRepository([first, second])
    started_two = asyncio.Event()
    active = 0
    max_active = 0

    class OverlapGenerator(RecordingDigestGenerator):
        async def generate(
            self, profile: Profile, source_date: date, task_id: str
        ) -> GeneratedDigest:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            if profile.user_id == "user-1":
                await started_two.wait()
            else:
                started_two.set()
            result = await super().generate(profile, source_date, task_id)
            active -= 1
            return result

    sleeps = []

    async def release_cadence(seconds: float) -> None:
        sleeps.append(seconds)
        await asyncio.sleep(0)

    task_ids = iter(["task-1", "task-2"])
    orchestrator = DailyDigestOrchestrator(
        repository=repository,
        source_fetcher=RecordingSourceFetcher(),
        digest_generator=OverlapGenerator(),
        email_sender=RecordingEmailSender(),
        profile_start_interval_seconds=60,
        max_concurrent_profiles=2,
        sleep=release_cadence,
        task_id_factory=lambda: next(task_ids),
    )

    summary = asyncio.run(orchestrator.run(date(2026, 7, 9)))

    assert summary.sent_count == 2
    assert sleeps == [60]
    assert max_active == 2


def test_profile_failure_is_recorded_without_blocking_later_profiles() -> None:
    first = Profile(
        id="profile-1",
        user_id="user-1",
        email="one@example.com",
        name="One",
        title=None,
        goals="AI",
        interests=None,
    )
    second = replace(
        first,
        id="profile-2",
        user_id="user-2",
        email="two@example.com",
        name="Two",
    )
    repository = RecordingRepository([first, second])
    fetcher = RecordingSourceFetcher()

    class FailFirstGenerator(RecordingDigestGenerator):
        async def generate(
            self, profile: Profile, source_date: date, task_id: str
        ) -> GeneratedDigest:
            if profile.user_id == "user-1":
                raise RuntimeError("provider unavailable")
            return await super().generate(profile, source_date, task_id)

    generator = FailFirstGenerator()
    email_sender = RecordingEmailSender()
    task_ids = iter(["task-1", "task-2"])
    orchestrator = DailyDigestOrchestrator(
        repository=repository,
        source_fetcher=fetcher,
        digest_generator=generator,
        email_sender=email_sender,
        profile_start_interval_seconds=0,
        task_id_factory=lambda: next(task_ids),
    )

    summary = asyncio.run(orchestrator.run(date(2026, 7, 9)))

    assert summary.status == "completed_with_errors"
    assert summary.failed_count == 1
    assert summary.sent_count == 1
    assert repository.deliveries["user-1"].status is DeliveryStatus.FAILED
    assert repository.deliveries["user-1"].task_id == "task-1"
    assert repository.deliveries["user-2"].status is DeliveryStatus.SENT
    assert email_sender.calls[0][0].user_id == "user-2"


def test_retry_resumes_completed_task_without_regenerating_digest() -> None:
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Reader",
        title=None,
        goals="AI",
        interests=None,
    )
    repository = RecordingRepository([profile])
    repository.deliveries[profile.user_id] = DeliveryRecord(
        source_date=date(2026, 7, 9),
        profile_id=profile.id,
        user_id=profile.user_id,
        status=DeliveryStatus.GENERATED,
        task_id="existing-task",
        profile_snapshot=replace(profile, email="original@example.com"),
    )

    class RecoveringGenerator(RecordingDigestGenerator):
        async def recover(self, task_id: str) -> GeneratedDigest | None:
            return GeneratedDigest(task_id=task_id, html="<html>recovered</html>")

    generator = RecoveringGenerator()
    email_sender = RecordingEmailSender()
    orchestrator = DailyDigestOrchestrator(
        repository=repository,
        source_fetcher=RecordingSourceFetcher(),
        digest_generator=generator,
        email_sender=email_sender,
        profile_start_interval_seconds=0,
        task_id_factory=lambda: (_ for _ in ()).throw(
            AssertionError("new task should not be created")
        ),
    )

    summary = asyncio.run(
        orchestrator.run(date(2026, 7, 9), retry_failed=True)
    )

    assert summary.sent_count == 1
    assert generator.prepared == []
    assert generator.calls == []
    assert repository.started_profiles == []
    assert repository.completed_profiles == [
        ("profile-1", "existing-task", "<html>recovered</html>")
    ]
    assert email_sender.calls[0][0].email == "original@example.com"
    assert email_sender.calls[0][2] == "existing-task"


def test_email_receipt_checkpoint_failure_never_downgrades_to_resendable_failed() -> None:
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Reader",
        title=None,
        goals="AI",
        interests=None,
    )

    class SentCheckpointFailureRepository(RecordingRepository):
        async def mark_delivery_sent(
            self, source_date: date, user_id: str, email_id: str
        ) -> None:
            raise RuntimeError("database unavailable after provider receipt")

    repository = SentCheckpointFailureRepository([profile])
    orchestrator = DailyDigestOrchestrator(
        repository=repository,
        source_fetcher=RecordingSourceFetcher(),
        digest_generator=RecordingDigestGenerator(),
        email_sender=RecordingEmailSender(),
        profile_start_interval_seconds=0,
        task_id_factory=lambda: "task-1",
    )

    summary = asyncio.run(orchestrator.run(date(2026, 7, 9)))

    assert summary.failed_count == 1
    assert repository.deliveries[profile.user_id].status is DeliveryStatus.AMBIGUOUS
    assert "database unavailable" in repository.deliveries[profile.user_id].error


def test_ambiguous_email_older_than_provider_window_is_not_resent() -> None:
    profile = Profile(
        id="profile-1",
        user_id="user-1",
        email="reader@example.com",
        name="Reader",
        title=None,
        goals="AI",
        interests=None,
    )
    now = datetime(2026, 7, 10, 13, tzinfo=timezone.utc)
    repository = RecordingRepository([profile])
    repository.deliveries[profile.user_id] = DeliveryRecord(
        source_date=date(2026, 7, 9),
        profile_id=profile.id,
        user_id=profile.user_id,
        status=DeliveryStatus.AMBIGUOUS,
        task_id="existing-task",
        email_attempted_at=now - timedelta(hours=23),
    )
    generator = RecordingDigestGenerator()
    email_sender = RecordingEmailSender()
    orchestrator = DailyDigestOrchestrator(
        repository=repository,
        source_fetcher=RecordingSourceFetcher(),
        digest_generator=generator,
        email_sender=email_sender,
        profile_start_interval_seconds=0,
        now=lambda: now,
    )

    summary = asyncio.run(
        orchestrator.run(date(2026, 7, 9), retry_failed=True)
    )

    assert summary.status == "completed_with_errors"
    assert summary.failed_count == 1
    assert generator.calls == []
    assert email_sender.calls == []
    assert repository.deliveries[profile.user_id].status is DeliveryStatus.AMBIGUOUS


def test_already_claimed_run_does_not_repeat_external_work() -> None:
    repository = RecordingRepository([])
    repository.claimed = False
    fetcher = RecordingSourceFetcher()
    generator = RecordingDigestGenerator()
    email_sender = RecordingEmailSender()
    orchestrator = DailyDigestOrchestrator(
        repository=repository,
        source_fetcher=fetcher,
        digest_generator=generator,
        email_sender=email_sender,
        profile_start_interval_seconds=0,
    )

    summary = asyncio.run(orchestrator.run(date(2026, 7, 9)))

    assert summary.status == "already_claimed"
    assert fetcher.dates == []
    assert generator.calls == []
    assert email_sender.calls == []
