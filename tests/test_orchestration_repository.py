"""Boundary tests for Supabase orchestration persistence."""

import asyncio
from datetime import date
from types import SimpleNamespace

from src.orchestration_repository import SupabaseOrchestrationRepository


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.operations = []
        self.not_ = self

    def select(self, fields):
        self.operations.append(("select", fields))
        return self

    def is_(self, field, value):
        self.operations.append(("is", field, value))
        return self

    def eq(self, field, value):
        self.operations.append(("eq", field, value))
        return self

    def limit(self, value):
        self.operations.append(("limit", value))
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class RecordingClient:
    def __init__(self, *, rpc_result=True, profile_rows=None):
        self.rpc_result = rpc_result
        self.profile_query = Query(profile_rows or [])
        self.rpc_calls = []

    def rpc(self, name, parameters):
        self.rpc_calls.append((name, parameters))
        return Query([True] if self.rpc_result else [False])

    def table(self, name):
        assert name == "profiles"
        return self.profile_query


def test_repository_claim_uses_atomic_rpc_and_records_retry_intent() -> None:
    client = RecordingClient(rpc_result=True)
    repository = SupabaseOrchestrationRepository(client, stale_after_minutes=90)

    claimed = asyncio.run(
        repository.claim_run(date(2026, 7, 9), retry_failed=True)
    )

    assert claimed is True
    name, parameters = client.rpc_calls[0]
    assert name == "claim_orchestration_run"
    assert parameters["p_source_date"] == "2026-07-09"
    assert parameters["p_retry_failed"] is True
    assert parameters["p_run_id"]
    assert parameters["p_stale_before"].endswith("+00:00")


def test_repository_maps_only_profiles_with_nonempty_goals() -> None:
    rows = [
        {
            "id": "profile-1",
            "user_id": "user-1",
            "email": "reader@example.com",
            "name": "Reader",
            "title": "Researcher",
            "goals": "Track AI",
            "interests": "Policy",
        },
        {
            "id": "profile-2",
            "user_id": "user-2",
            "email": "empty@example.com",
            "name": "Empty",
            "title": None,
            "goals": None,
            "interests": None,
        },
    ]
    client = RecordingClient(profile_rows=rows)
    repository = SupabaseOrchestrationRepository(client)

    profiles = asyncio.run(repository.list_eligible_profiles())

    assert [profile.user_id for profile in profiles] == ["user-1"]
    assert profiles[0].interests == "Policy"
    assert ("is", "goals", "null") in client.profile_query.operations
    assert ("is", "remove", "null") in client.profile_query.operations
