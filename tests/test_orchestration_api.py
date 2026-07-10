"""Behavioral tests for protected orchestration operations."""

import asyncio
from datetime import date

import httpx
import pytest
from fastapi import HTTPException

from src import main
from src.api_models import OrchestrationRunRequest


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, source_date, *, retry_failed):
        self.calls.append((source_date, retry_failed))


async def _request_manual_run():
    orchestrator = RecordingOrchestrator()
    main.app.state.orchestrator = orchestrator
    main.app.state.orchestration_manual_tasks = set()
    response = await main.run_daily_orchestration(
        OrchestrationRunRequest(
            source_date=date(2026, 7, 9), retry_failed=True
        )
    )
    await asyncio.gather(*main.app.state.orchestration_manual_tasks)
    return response, orchestrator


def test_admin_route_requires_api_key_through_the_real_asgi_app() -> None:
    async def request_without_key():
        orchestrator = RecordingOrchestrator()
        main.app.state.orchestrator = orchestrator
        main.app.state.orchestration_manual_tasks = set()
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/admin/orchestration/run",
                json={"source_date": "2026-07-09"},
            )
        return response, orchestrator

    response, orchestrator = asyncio.run(request_without_key())

    assert response.status_code == 403
    assert orchestrator.calls == []


def test_manual_run_returns_immediately_and_executes_durable_coordinator() -> None:
    response, orchestrator = asyncio.run(_request_manual_run())

    assert response.status == "accepted"
    assert response.source_date == date(2026, 7, 9)
    assert orchestrator.calls == [(date(2026, 7, 9), True)]


def test_manual_run_is_unavailable_until_orchestration_is_enabled() -> None:
    main.app.state.orchestrator = None

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            main.run_daily_orchestration(OrchestrationRunRequest())
        )

    assert excinfo.value.status_code == 503
