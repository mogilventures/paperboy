"""Behavioral tests for daily source fetching and persistence."""

import asyncio
from typing import Any

import pytest

from src.fetch_service import FetchSourcesService


class Response:
    def __init__(self, data: list[dict[str, Any]] | None = None) -> None:
        self.data = data or []


class FakeQuery:
    def __init__(self, client: "TransientTimeoutClient", table: str) -> None:
        self.client = client
        self.table = table
        self.operation = ""
        self.data: dict[str, Any] | None = None
        self.returning: Any = None

    def select(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        self.operation = "select"
        return self

    def update(
        self,
        data: dict[str, Any],
        *,
        returning: Any = None,
        **_kwargs: Any,
    ) -> "FakeQuery":
        self.operation = "update"
        self.data = data
        self.returning = returning
        return self

    def insert(self, data: dict[str, Any], **_kwargs: Any) -> "FakeQuery":
        self.operation = "insert"
        self.data = data
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "FakeQuery":
        return self

    def execute(self) -> Response:
        return self.client.execute(self)


class TransientTimeoutClient:
    def __init__(
        self,
        *,
        failure_message: str | None = (
            "{'code': '57014', 'message': "
            "'canceling statement due to statement timeout'}"
        ),
    ) -> None:
        self.failure_message = failure_message
        self.source_storage_attempts = 0
        self.completed_source_write_returning: list[Any] = []

    def table(self, table: str) -> FakeQuery:
        return FakeQuery(self, table)

    def execute(self, query: FakeQuery) -> Response:
        if query.operation == "select":
            return Response()
        if (
            query.table == "daily_sources"
            and query.operation == "update"
            and query.data is not None
            and "arxiv_papers" in query.data
        ):
            self.source_storage_attempts += 1
            self.completed_source_write_returning.append(query.returning)
            if self.failure_message and self.source_storage_attempts == 1:
                raise RuntimeError(self.failure_message)
        return Response()


class StaticBreaker:
    async def call(
        self, _operation: Any, *_args: Any, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        return [
            {
                "title": "Reliable persistence",
                "primary_subject": "cs.AI",
                "authors": ["Researcher"],
            }
        ]


class StaticBreakers:
    def get(self, _name: str) -> StaticBreaker:
        return StaticBreaker()


def test_fetch_retries_a_transient_source_storage_timeout() -> None:
    client = TransientTimeoutClient()
    service = FetchSourcesService(client, StaticBreakers())

    result = asyncio.run(
        service.fetch_and_store_sources("2026-07-30", "fetch-task-1")
    )

    assert result["status"] == "completed"
    assert result["arxiv_count"] == 1
    assert client.source_storage_attempts == 2


def test_fetch_does_not_request_the_large_source_row_after_storage() -> None:
    client = TransientTimeoutClient(failure_message=None)
    service = FetchSourcesService(client, StaticBreakers())

    result = asyncio.run(
        service.fetch_and_store_sources("2026-07-30", "fetch-task-1")
    )

    assert result["status"] == "completed"
    assert client.completed_source_write_returning == ["minimal"]


def test_fetch_does_not_retry_a_permanent_source_storage_error() -> None:
    client = TransientTimeoutClient(
        failure_message="{'code': '23505', 'message': 'duplicate key'}"
    )
    service = FetchSourcesService(client, StaticBreakers())

    with pytest.raises(RuntimeError, match="23505"):
        asyncio.run(
            service.fetch_and_store_sources("2026-07-30", "fetch-task-1")
        )

    assert client.source_storage_attempts == 1
