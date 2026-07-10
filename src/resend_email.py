"""Resend adapter for idempotent digest email delivery."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Awaitable, Callable

import httpx

from .orchestration import AmbiguousEmailDelivery, Profile


class ResendEmailSender:
    """Send digest HTML through Resend without duplicating retry attempts."""

    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 3,
        retry_delay_seconds: float = 5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ValueError("Resend API key is required")
        self._api_key = api_key
        self._from_address = from_address
        self._client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    async def send_digest(
        self,
        *,
        profile: Profile,
        source_date: date,
        task_id: str,
        html: str,
    ) -> str:
        if not profile.email:
            raise ValueError("Profile has no delivery email")

        subject = (
            f"Paperboy | {profile.name}'s Daily Digest"
            if profile.name
            else "Paperboy | Your Daily Digest"
        )
        payload = {
            "from": self._from_address,
            "to": [profile.email],
            "html": html,
            "subject": subject,
            "tags": [{"name": "task_id", "value": task_id}],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": (
                f"paperboy:{source_date.isoformat()}:{profile.user_id}"
            ),
        }

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.post(
                    "https://api.resend.com/emails",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                email_id = response.json().get("id")
                if not email_id:
                    raise AmbiguousEmailDelivery(
                        "Resend accepted the request without returning an email id"
                    )
                return str(email_id)
            except httpx.TransportError as exc:
                if attempt >= self._max_attempts:
                    raise AmbiguousEmailDelivery(
                        "Resend delivery receipt was not observed"
                    ) from exc
            except AmbiguousEmailDelivery:
                if attempt >= self._max_attempts:
                    raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status == 429 or status >= 500
                if not retryable:
                    raise
                if attempt >= self._max_attempts:
                    raise AmbiguousEmailDelivery(
                        f"Resend returned repeated retryable status {status}"
                    ) from exc

            await self._sleep(self._retry_delay_seconds)

        raise AmbiguousEmailDelivery(
            "Resend delivery exhausted without a receipt"
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
