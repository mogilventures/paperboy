"""Supabase persistence for durable daily digest orchestration."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from supabase import Client

from .orchestration import DeliveryRecord, DeliveryStatus, Profile, RunSummary


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SupabaseOrchestrationRepository:
    """Persist run claims and per-user delivery checkpoints in Supabase."""

    def __init__(
        self,
        client: Client,
        *,
        stale_after_minutes: int = 120,
    ) -> None:
        self._client = client
        self._stale_after = timedelta(minutes=stale_after_minutes)
        self._run_ids: dict[date, str] = {}

    async def claim_run(self, source_date: date, *, retry_failed: bool) -> bool:
        run_id = str(uuid.uuid4())
        stale_before = (_utc_now() - self._stale_after).isoformat()
        response = self._client.rpc(
            "claim_orchestration_run",
            {
                "p_source_date": source_date.isoformat(),
                "p_run_id": run_id,
                "p_stale_before": stale_before,
                "p_retry_failed": retry_failed,
            },
        ).execute()
        claimed = response.data is True or response.data == [True]
        if claimed:
            self._run_ids[source_date] = run_id
        return claimed

    async def list_eligible_profiles(self) -> list[Profile]:
        response = (
            self._client.table("profiles")
            .select("id,user_id,email,name,title,goals,interests")
            .not_.is_("goals", "null")
            .is_("remove", "null")
            .execute()
        )
        profiles = []
        for row in response.data or []:
            goals = row.get("goals")
            if not goals:
                continue
            profiles.append(
                Profile(
                    id=str(row["id"]),
                    user_id=str(row["user_id"]),
                    email=row.get("email"),
                    name=row.get("name"),
                    title=row.get("title"),
                    goals=str(goals),
                    interests=row.get("interests"),
                )
            )
        return profiles

    async def get_or_create_delivery(
        self, source_date: date, profile: Profile
    ) -> DeliveryRecord:
        run_id = self._active_run_id(source_date)
        response = self._client.rpc(
            "claim_orchestration_delivery",
            {
                "p_source_date": source_date.isoformat(),
                "p_run_id": run_id,
                "p_profile_id": profile.id,
                "p_user_id": profile.user_id,
                "p_profile_snapshot": {
                    "id": profile.id,
                    "user_id": profile.user_id,
                    "email": profile.email,
                    "name": profile.name,
                    "title": profile.title,
                    "goals": profile.goals,
                    "interests": profile.interests,
                },
            },
        ).execute()
        if not response.data:
            raise RuntimeError("Daily orchestration run claim was lost")
        return self._delivery_from_row(source_date, response.data[0])

    async def mark_delivery_generating(
        self, source_date: date, user_id: str, task_id: str
    ) -> None:
        self._update_delivery(
            source_date,
            user_id,
            {
                "status": DeliveryStatus.GENERATING.value,
                "task_id": task_id,
                "last_error": None,
            },
        )

    async def mark_delivery_generated(
        self, source_date: date, user_id: str, task_id: str
    ) -> None:
        self._update_delivery(
            source_date,
            user_id,
            {
                "status": DeliveryStatus.GENERATED.value,
                "task_id": task_id,
                "last_error": None,
            },
        )

    async def mark_delivery_sending(
        self, source_date: date, user_id: str
    ) -> None:
        self._update_delivery(
            source_date,
            user_id,
            {
                "status": DeliveryStatus.SENDING.value,
                "email_attempted_at": _utc_now().isoformat(),
                "last_error": None,
            },
        )

    async def mark_delivery_sent(
        self, source_date: date, user_id: str, email_id: str
    ) -> None:
        now = _utc_now().isoformat()
        self._update_delivery(
            source_date,
            user_id,
            {
                "status": DeliveryStatus.SENT.value,
                "email_id": email_id,
                "email_sent_at": now,
                "last_error": None,
            },
        )

    async def mark_delivery_ambiguous(
        self, source_date: date, user_id: str, error: str
    ) -> None:
        self._update_delivery(
            source_date,
            user_id,
            {
                "status": DeliveryStatus.AMBIGUOUS.value,
                "last_error": error[:2000],
            },
        )

    async def mark_delivery_failed(
        self, source_date: date, user_id: str, error: str
    ) -> None:
        self._update_delivery(
            source_date,
            user_id,
            {
                "status": DeliveryStatus.FAILED.value,
                "last_error": error[:2000],
            },
        )

    async def start_profile(
        self, source_date: date, profile_id: str, task_id: str
    ) -> None:
        self._update_profile_with_claim(
            source_date=source_date,
            profile_id=profile_id,
            task_id=task_id,
            html=None,
        )

    async def complete_profile(
        self, source_date: date, profile_id: str, task_id: str, html: str
    ) -> None:
        self._update_profile_with_claim(
            source_date=source_date,
            profile_id=profile_id,
            task_id=task_id,
            html=html,
        )

    async def heartbeat_run(self, source_date: date) -> None:
        self._update_active_run(
            source_date, {"heartbeat_at": _utc_now().isoformat()}
        )

    async def finish_run(self, summary: RunSummary) -> None:
        now = _utc_now().isoformat()
        self._update_active_run(
            summary.source_date,
            {
                "status": summary.status,
                "total_profiles": summary.total_profiles,
                "sent_count": summary.sent_count,
                "failed_count": summary.failed_count,
                "skipped_count": summary.skipped_count,
                "heartbeat_at": now,
                "completed_at": now,
                "last_error": None,
            },
        )

    async def fail_run(self, source_date: date, error: str) -> None:
        now = _utc_now().isoformat()
        self._update_active_run(
            source_date,
            {
                "status": "failed",
                "heartbeat_at": now,
                "completed_at": now,
                "last_error": error[:2000],
            },
        )

    async def get_run(self, source_date: date) -> dict[str, Any] | None:
        response = (
            self._client.table("orchestration_runs")
            .select("*")
            .eq("source_date", source_date.isoformat())
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    @staticmethod
    def _delivery_from_row(
        source_date: date, row: dict[str, Any]
    ) -> DeliveryRecord:
        snapshot = row.get("profile_snapshot")
        return DeliveryRecord(
            source_date=source_date,
            profile_id=str(row["profile_id"]),
            user_id=str(row["user_id"]),
            status=DeliveryStatus(row["status"]),
            task_id=row.get("task_id"),
            email_id=row.get("email_id"),
            email_attempted_at=(
                datetime.fromisoformat(
                    row["email_attempted_at"].replace("Z", "+00:00")
                )
                if row.get("email_attempted_at")
                else None
            ),
            profile_snapshot=(Profile(**snapshot) if snapshot else None),
            error=row.get("last_error"),
        )

    def _update_delivery(
        self, source_date: date, user_id: str, fields: dict[str, Any]
    ) -> None:
        payload = {**fields, "updated_at": _utc_now().isoformat()}
        response = (
            self._client.table("orchestration_deliveries")
            .update(payload)
            .eq("source_date", source_date.isoformat())
            .eq("user_id", user_id)
            .eq("run_id", self._active_run_id(source_date))
            .execute()
        )
        if response.data == []:
            raise RuntimeError("Daily orchestration delivery claim was lost")

    def _update_profile_with_claim(
        self,
        *,
        source_date: date,
        profile_id: str,
        task_id: str,
        html: str | None,
    ) -> None:
        run_id = self._active_run_id(source_date)
        response = self._client.rpc(
            "update_orchestration_profile",
            {
                "p_source_date": source_date.isoformat(),
                "p_run_id": run_id,
                "p_profile_id": profile_id,
                "p_task_id": task_id,
                "p_html": html,
            },
        ).execute()
        updated = response.data is True or response.data == [True]
        if not updated:
            raise RuntimeError("Daily orchestration run claim was lost")

    def _active_run_id(self, source_date: date) -> str:
        run_id = self._run_ids.get(source_date)
        if not run_id:
            raise RuntimeError(f"No active claim for {source_date.isoformat()}")
        return run_id

    def _update_active_run(
        self, source_date: date, fields: dict[str, Any]
    ) -> None:
        run_id = self._active_run_id(source_date)
        response = (
            self._client.table("orchestration_runs")
            .update(fields)
            .eq("source_date", source_date.isoformat())
            .eq("run_id", run_id)
            .execute()
        )
        if response.data == []:
            raise RuntimeError("Daily orchestration run claim was lost")
