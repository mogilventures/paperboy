"""Shutdown behavior needed by Uvicorn-hosted background orchestration."""

import asyncio

from src.graceful_shutdown import GracefulShutdown


def test_lifespan_can_initiate_shutdown_without_replacing_uvicorn_signals() -> None:
    handler = GracefulShutdown(timeout=1)

    handler.initiate_shutdown()
    asyncio.run(handler.wait_for_shutdown())

    assert handler.is_shutting_down()
