"""Small UTC scheduler for the always-on Fly.io application process."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


class DailyOrchestrationScheduler:
    """Check for the daily due date; database claiming supplies uniqueness."""

    def __init__(
        self,
        orchestrator: Any,
        *,
        hour_utc: int = 13,
        poll_seconds: float = 60,
        catchup_hours: float = 24,
    ) -> None:
        if not 0 <= hour_utc <= 23:
            raise ValueError("hour_utc must be between 0 and 23")
        self._orchestrator = orchestrator
        if catchup_hours <= 0:
            raise ValueError("catchup_hours must be positive")
        self._hour_utc = hour_utc
        self._poll_seconds = poll_seconds
        self._catchup_window = timedelta(hours=catchup_hours)
        self._stop = asyncio.Event()

    async def tick(self, now: datetime | None = None) -> Any | None:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("Scheduler requires a timezone-aware datetime")
        current = current.astimezone(timezone.utc)
        scheduled_today = current.replace(
            hour=self._hour_utc, minute=0, second=0, microsecond=0
        )
        latest_slot = scheduled_today
        if current < scheduled_today:
            latest_slot -= timedelta(days=1)
        if current - latest_slot > self._catchup_window:
            return None
        source_date = (latest_slot - timedelta(days=1)).date()
        return await self._orchestrator.run(source_date, retry_failed=False)

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Daily orchestration scheduler tick failed")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
