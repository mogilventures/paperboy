"""Regression tests for Logfire warning API compatibility.

Production Logfire exposes ``warn`` but not ``warning``. A prior use of
``logfire.warning`` in the Python email-template path caused template rendering
to raise and fall back to LLM-generated HTML.
"""
import ast
import asyncio
from pathlib import Path

import pytest

import src.config as config_module
from src import llm_client as llm_module
from src.llm_client import LLMClient


class _FakeAsyncOpenAI:
    def __init__(self, **kwargs):
        self.responses = None
        self.chat = None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(llm_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(config_module.settings, "llm_provider", "fireworks", raising=False)
    monkeypatch.setattr(config_module.settings, "fireworks_api_key", "fw-test", raising=False)
    return LLMClient()


def test_no_logfire_warning_calls_in_src():
    """Guard against the production AttributeError: logfire.warning missing."""
    src_dir = Path(__file__).resolve().parents[1] / "src"
    offenders = []
    for path in src_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "warning"
                and isinstance(node.value, ast.Name)
                and node.value.id == "logfire"
            ):
                offenders.append(f"{path.relative_to(src_dir.parent)}:{node.lineno}")

    assert offenders == []


def test_create_digest_data_highlight_fallback_does_not_break_template_path(client, monkeypatch):
    """Invalid highlight JSON should fall back deterministically, not raise."""

    async def invalid_json(*args, **kwargs):
        return "not json"

    monkeypatch.setattr(client, "_call_llm", invalid_json)

    summaries = [
        {
            "title": "Graph-Based Phonetic Error Correction of Noisy ASR",
            "type": "paper",
            "relevance_score": 96,
            "summary": "A graph-based ASR correction method.",
            "why_relevant": "Improves speech recognition reliability.",
            "key_takeaway": "Can improve noisy transcripts without heavy model overhead.",
            "abstract_url": "https://arxiv.org/abs/1234.5678",
            "pdf_url": "https://arxiv.org/pdf/1234.5678",
        }
    ]

    digest = asyncio.run(
        client.create_digest_data(
            summaries,
            {"name": "Noah Mogil", "title": "Solutions Engineer", "goals": "Voice AI"},
        )
    )

    assert digest.user_name == "Noah Mogil"
    assert digest.highlights
    assert digest.directly_relevant[0].title == summaries[0]["title"]
