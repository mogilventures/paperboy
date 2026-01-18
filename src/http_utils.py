"""
Shared HTTP client utilities for Paperboy.

Provides pre-configured httpx AsyncClient instances optimized for Cloud Run.
"""
from datetime import datetime, timezone
from typing import Any
import httpx
import logfire


def create_http_client(read_timeout: float = 25.0) -> httpx.AsyncClient:
    """
    Create a pre-configured async HTTP client optimized for Cloud Run.

    Args:
        read_timeout: Read timeout in seconds. Default 25.0 allows time for large responses.

    Returns:
        Configured httpx.AsyncClient instance.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=5.0,
            read=read_timeout,
            write=10.0,
            pool=2.0
        ),
        limits=httpx.Limits(
            max_keepalive_connections=20,
            max_connections=40,
            keepalive_expiry=30.0
        ),
        http2=True,
    )


async def send_webhook_callback(
    callback_url: str,
    task_id: str,
    status: str,
    result: Any
) -> None:
    """
    Send a callback notification to a webhook URL.

    Args:
        callback_url: The URL to send the callback to.
        task_id: The task identifier.
        status: The task status ("completed" or "failed").
        result: The result data (used as result on success, error message on failure).
    """
    payload = {
        "task_id": task_id,
        "status": status,
        "result": result if status == "completed" else None,
        "error": result if status == "failed" else None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(callback_url, json=payload)
            response.raise_for_status()
        logfire.info("Callback sent successfully", extra={"callback_url": callback_url, "task_id": task_id})
    except Exception as e:
        logfire.error("Failed to send callback", extra={"error": str(e), "callback_url": callback_url, "task_id": task_id})
