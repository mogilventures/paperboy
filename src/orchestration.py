"""Durable, backend-hosted orchestration for Paperboy's daily digest run.

The orchestrator owns business sequencing while persistence, digest generation,
source fetching, and email delivery are injected adapters. This keeps the daily
workflow independently testable and avoids making HTTP calls back into the same
FastAPI process.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


class AmbiguousEmailDelivery(RuntimeError):
    """The provider may have accepted an email but no receipt was observed."""


@dataclass(frozen=True)
class Profile:
    id: str
    user_id: str
    email: str | None
    name: str | None
    title: str | None
    goals: str
    interests: str | None


@dataclass(frozen=True)
class DeliveryRecord:
    source_date: date
    profile_id: str
    user_id: str
    status: DeliveryStatus
    task_id: str | None = None
    email_id: str | None = None
    email_attempted_at: datetime | None = None
    profile_snapshot: Profile | None = None
    error: str | None = None


@dataclass(frozen=True)
class GeneratedDigest:
    task_id: str
    html: str


@dataclass(frozen=True)
class RunSummary:
    source_date: date
    status: str
    total_profiles: int
    sent_count: int
    failed_count: int
    skipped_count: int


class OrchestrationRepository(Protocol):
    async def claim_run(self, source_date: date, *, retry_failed: bool) -> bool: ...

    async def list_eligible_profiles(self) -> list[Profile]: ...

    async def get_or_create_delivery(
        self, source_date: date, profile: Profile
    ) -> DeliveryRecord: ...

    async def mark_delivery_generating(
        self, source_date: date, user_id: str, task_id: str
    ) -> None: ...

    async def mark_delivery_generated(
        self, source_date: date, user_id: str, task_id: str
    ) -> None: ...

    async def mark_delivery_sending(
        self, source_date: date, user_id: str
    ) -> None: ...

    async def mark_delivery_sent(
        self, source_date: date, user_id: str, email_id: str
    ) -> None: ...

    async def mark_delivery_ambiguous(
        self, source_date: date, user_id: str, error: str
    ) -> None: ...

    async def mark_delivery_failed(
        self, source_date: date, user_id: str, error: str
    ) -> None: ...

    async def start_profile(
        self, source_date: date, profile_id: str, task_id: str
    ) -> None: ...

    async def complete_profile(
        self, source_date: date, profile_id: str, task_id: str, html: str
    ) -> None: ...

    async def heartbeat_run(self, source_date: date) -> None: ...

    async def finish_run(self, summary: RunSummary) -> None: ...

    async def fail_run(self, source_date: date, error: str) -> None: ...


class SourceFetcher(Protocol):
    async def fetch(self, source_date: date) -> dict[str, int]: ...


class DigestGenerator(Protocol):
    async def prepare(
        self, profile: Profile, source_date: date, task_id: str
    ) -> None: ...

    async def generate(
        self, profile: Profile, source_date: date, task_id: str
    ) -> GeneratedDigest: ...

    async def recover(self, task_id: str) -> GeneratedDigest | None: ...


class DigestEmailSender(Protocol):
    async def send_digest(
        self, *, profile: Profile, source_date: date, task_id: str, html: str
    ) -> str: ...


class DailyDigestOrchestrator:
    """Run one idempotent source-date batch and isolate per-profile failures."""

    def __init__(
        self,
        *,
        repository: OrchestrationRepository,
        source_fetcher: SourceFetcher,
        digest_generator: DigestGenerator,
        email_sender: DigestEmailSender,
        profile_start_interval_seconds: float = 60,
        task_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        email_idempotency_window: timedelta = timedelta(hours=23),
        max_concurrent_profiles: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repository = repository
        self._source_fetcher = source_fetcher
        self._digest_generator = digest_generator
        self._email_sender = email_sender
        self._profile_start_interval_seconds = profile_start_interval_seconds
        self._task_id_factory = task_id_factory
        if max_concurrent_profiles < 1:
            raise ValueError("max_concurrent_profiles must be at least one")
        self._now = now
        self._email_idempotency_window = email_idempotency_window
        self._max_concurrent_profiles = max_concurrent_profiles
        self._sleep = sleep

    async def run(
        self, source_date: date, *, retry_failed: bool = False
    ) -> RunSummary:
        if not await self._repository.claim_run(
            source_date, retry_failed=retry_failed
        ):
            return RunSummary(source_date, "already_claimed", 0, 0, 0, 0)

        try:
            source_counts = await self._source_fetcher.fetch(source_date)
            if sum(source_counts.values()) <= 0:
                raise RuntimeError(f"No sources available for {source_date.isoformat()}")

            profiles = await self._repository.list_eligible_profiles()
            semaphore = asyncio.Semaphore(self._max_concurrent_profiles)
            profile_tasks = []
            try:
                for index, profile in enumerate(profiles):
                    profile_tasks.append(
                        asyncio.create_task(
                            self._process_profile(source_date, profile, semaphore),
                            name=(
                                f"digest-{source_date.isoformat()}-"
                                f"{profile.user_id}"
                            ),
                        )
                    )
                    await self._repository.heartbeat_run(source_date)
                    if (
                        index < len(profiles) - 1
                        and self._profile_start_interval_seconds > 0
                    ):
                        await self._sleep(
                            self._profile_start_interval_seconds
                        )

                outcomes = (
                    await asyncio.gather(*profile_tasks)
                    if profile_tasks
                    else []
                )
            except BaseException:
                for task in profile_tasks:
                    task.cancel()
                if profile_tasks:
                    await asyncio.gather(*profile_tasks, return_exceptions=True)
                raise
            sent_count = outcomes.count("sent")
            failed_count = outcomes.count("failed")
            skipped_count = outcomes.count("skipped")
            status = "completed" if failed_count == 0 else "completed_with_errors"
            summary = RunSummary(
                source_date=source_date,
                status=status,
                total_profiles=len(profiles),
                sent_count=sent_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
            )
            await self._repository.finish_run(summary)
            return summary
        except Exception as exc:
            await self._repository.fail_run(source_date, str(exc))
            raise

    async def _process_profile(
        self,
        source_date: date,
        profile: Profile,
        semaphore: asyncio.Semaphore,
    ) -> str:
        async with semaphore:
            try:
                delivery = await self._repository.get_or_create_delivery(
                    source_date, profile
                )
                delivery_profile = delivery.profile_snapshot or profile
                if delivery.status is DeliveryStatus.SENT:
                    return "skipped"
                if (
                    delivery.status
                    in (DeliveryStatus.SENDING, DeliveryStatus.AMBIGUOUS)
                    and delivery.email_attempted_at is not None
                    and self._now() - delivery.email_attempted_at
                    >= self._email_idempotency_window
                ):
                    # Resend's key expires after 24 hours. An older unknown
                    # receipt requires operator reconciliation rather than a
                    # potentially duplicated customer email.
                    return "failed"

                digest = None
                if delivery.task_id:
                    digest = await self._digest_generator.recover(delivery.task_id)

                if digest is None:
                    task_id = self._task_id_factory()
                    await self._repository.mark_delivery_generating(
                        source_date, profile.user_id, task_id
                    )
                    await self._digest_generator.prepare(
                        delivery_profile, source_date, task_id
                    )
                    await self._repository.start_profile(
                        source_date, delivery_profile.id, task_id
                    )
                    digest = await self._digest_generator.generate(
                        delivery_profile, source_date, task_id
                    )

                await self._repository.mark_delivery_generated(
                    source_date, profile.user_id, digest.task_id
                )
                await self._repository.complete_profile(
                    source_date,
                    delivery_profile.id,
                    digest.task_id,
                    digest.html,
                )
                # Renew and validate the fenced run claim immediately before
                # the only irreversible side effect.
                await self._repository.heartbeat_run(source_date)
                await self._repository.mark_delivery_sending(
                    source_date, profile.user_id
                )
                email_id = await self._email_sender.send_digest(
                    profile=delivery_profile,
                    source_date=source_date,
                    task_id=digest.task_id,
                    html=digest.html,
                )
                try:
                    await self._repository.mark_delivery_sent(
                        source_date, profile.user_id, email_id
                    )
                except Exception as exc:
                    # Resend returned a provider receipt, so never downgrade
                    # this to FAILED. Preserve ambiguity if the sent checkpoint
                    # could not be committed; a later operator can reconcile it.
                    logger.exception(
                        "Email accepted but sent checkpoint failed",
                        extra={
                            "source_date": source_date.isoformat(),
                            "user_id": profile.user_id,
                        },
                    )
                    try:
                        await self._repository.mark_delivery_ambiguous(
                            source_date, profile.user_id, str(exc)
                        )
                    except Exception:
                        logger.exception(
                            "Could not persist ambiguous email state",
                            extra={
                                "source_date": source_date.isoformat(),
                                "user_id": profile.user_id,
                            },
                        )
                    return "failed"
                return "sent"
            except AmbiguousEmailDelivery as exc:
                await self._repository.mark_delivery_ambiguous(
                    source_date, profile.user_id, str(exc)
                )
                return "failed"
            except Exception as exc:
                logger.exception(
                    "Daily digest delivery failed",
                    extra={
                        "source_date": source_date.isoformat(),
                        "user_id": profile.user_id,
                    },
                )
                await self._repository.mark_delivery_failed(
                    source_date, profile.user_id, str(exc)
                )
                return "failed"
            finally:
                await self._repository.heartbeat_run(source_date)
