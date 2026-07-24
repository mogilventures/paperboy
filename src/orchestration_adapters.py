"""Adapters connecting orchestration to Paperboy's existing backend services."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from typing import Any

from .models import DigestStatus, TaskStatus
from .orchestration import GeneratedDigest, Profile

logger = logging.getLogger(__name__)


class BackendSourceFetcher:
    """Fetch daily sources through the existing service without self-HTTP."""

    def __init__(self, *, state_manager: Any, fetch_service: Any, timeout_seconds: int):
        self._state_manager = state_manager
        self._fetch_service = fetch_service
        self._timeout_seconds = timeout_seconds

    async def fetch(self, source_date: date) -> dict[str, int]:
        task_id = str(uuid.uuid4())
        source_date_text = source_date.isoformat()
        await self._state_manager.create_fetch_task(
            task_id, source_date_text, callback_url=None
        )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._fetch_service.fetch_and_store_sources(
                    source_date_text, task_id, callback_url=None
                )
        except Exception as exc:
            await self._state_manager.update_fetch_task(
                task_id, "failed", error=str(exc)
            )
            raise

        counts = {
            "arxiv_count": int(result.get("arxiv_count", 0)),
            "news_count": int(result.get("news_count", 0)),
        }
        # The existing-source fast path returns before FetchSourcesService
        # updates its task record, so make completion explicit and idempotent.
        # This tracking checkpoint is nonessential once valid source counts
        # have been returned; a transient database failure must not discard a
        # successful fetch and abort every digest in the batch.
        try:
            await self._state_manager.update_fetch_task(
                task_id, "completed", result=counts
            )
        except Exception:
            logger.warning(
                "Could not checkpoint completed source fetch; continuing with fetched sources",
                exc_info=True,
                extra={"task_id": task_id, "source_date": source_date_text},
            )
        return counts


class BackendDigestGenerator:
    """Create and run a user-linked digest through the existing service."""

    def __init__(
        self, *, state_manager: Any, digest_service: Any, timeout_seconds: int
    ) -> None:
        self._state_manager = state_manager
        self._digest_service = digest_service
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _user_info(profile: Profile) -> dict[str, Any]:
        return {
            "name": profile.name or "Reader",
            "title": profile.title,
            "goals": profile.goals,
            "news_interest": profile.interests,
            "research_interests": [profile.goals],
            "categories": ["cs.AI", "cs.LG"],
            "affiliation": profile.title,
            "recent_focus": profile.goals,
        }

    async def prepare(
        self, profile: Profile, source_date: date, task_id: str
    ) -> None:
        await self._state_manager.create_task_with_source_date(
            task_id,
            DigestStatus(status=TaskStatus.PENDING, message="Task created"),
            user_info=self._user_info(profile),
            source_date=source_date.isoformat(),
            digest_type="mixed",
            callback_url=None,
            user_id=profile.user_id,
        )

    async def generate(
        self, profile: Profile, source_date: date, task_id: str
    ) -> GeneratedDigest:
        user_info = self._user_info(profile)
        source_date_text = source_date.isoformat()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await self._digest_service.generate_digest(
                    task_id,
                    user_info,
                    callback_url=None,
                    top_n_articles=5,
                    top_n_news=5,
                    source_date=source_date_text,
                )
        except Exception as exc:
            await self._state_manager.update_task(
                task_id,
                DigestStatus(status=TaskStatus.FAILED, message=str(exc)),
            )
            raise

        result = await self.recover(task_id)
        if result is None:
            status = await self._state_manager.get_task(task_id)
            message = status.message if status else "Digest task disappeared"
            raise RuntimeError(f"Digest task {task_id} did not complete: {message}")
        return result

    async def recover(self, task_id: str) -> GeneratedDigest | None:
        status = await self._state_manager.get_task(task_id)
        if (
            status is None
            or status.status is not TaskStatus.COMPLETED
            or not status.result
            or "<html" not in status.result[:1000].lower()
        ):
            return None
        return GeneratedDigest(task_id=task_id, html=status.result)
