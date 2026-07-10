"""Behavioral tests for the UTC daily orchestration scheduler."""

import asyncio
from datetime import datetime, timezone

from src.orchestration_scheduler import DailyOrchestrationScheduler


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, source_date, *, retry_failed=False):
        self.calls.append((source_date, retry_failed))
        return "claimed"


def test_scheduler_runs_latest_slot_and_catches_up_within_24_hours() -> None:
    orchestrator = RecordingOrchestrator()
    scheduler = DailyOrchestrationScheduler(
        orchestrator, hour_utc=13, catchup_hours=24
    )

    catchup = asyncio.run(
        scheduler.tick(datetime(2026, 7, 10, 12, 59, tzinfo=timezone.utc))
    )
    current = asyncio.run(
        scheduler.tick(datetime(2026, 7, 10, 13, 0, tzinfo=timezone.utc))
    )

    assert catchup == "claimed"
    assert current == "claimed"
    assert orchestrator.calls == [
        (datetime(2026, 7, 8).date(), False),
        (datetime(2026, 7, 9).date(), False),
    ]


def test_scheduler_does_not_backfill_beyond_catchup_window() -> None:
    orchestrator = RecordingOrchestrator()
    scheduler = DailyOrchestrationScheduler(
        orchestrator, hour_utc=13, catchup_hours=12
    )

    result = asyncio.run(
        scheduler.tick(datetime(2026, 7, 10, 12, 59, tzinfo=timezone.utc))
    )

    assert result is None
    assert orchestrator.calls == []
