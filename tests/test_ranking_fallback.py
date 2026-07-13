"""Service-level tests: one source failing to rank must not sink the digest.

Incident on 2026-06-23: paper *or* news ranking raising an AttributeError
failed the entire digest. The digest service now ranks each source
independently — if at least one source ranks, the digest proceeds; only when
all attempted sources fail does it fail, with an actionable message.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.config as config_module
from src import llm_client as llm_module
from src import digest_service_enhanced as dse
from src.digest_service_enhanced import EnhancedDigestService
from src.models import RankedArticle


class _FakeAsyncOpenAI:
    def __init__(self, **kwargs):
        self.responses = SimpleNamespace(create=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=None))


def _ranked(title, ctype):
    return RankedArticle(
        title=title,
        authors=["A"],
        subject="news" if ctype == "news" else "cs.AI",
        score_reason="because",
        relevance_score=80,
        abstract_url="https://example.com/x",
        type=ctype,
    )


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(llm_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(config_module.settings, "llm_provider", "openai", raising=False)
    monkeypatch.setattr(config_module.settings, "openai_api_key", "sk-test", raising=False)
    # TaskStateManager builds a real Supabase client at construction; the
    # ranking-isolation logic never touches it, so stub it out entirely.
    monkeypatch.setattr(dse, "TaskStateManager", lambda: AsyncMock())
    svc = EnhancedDigestService()
    svc.state_manager = AsyncMock()
    svc.daily_sources_manager = AsyncMock()
    return svc


def _stub_sources(monkeypatch, svc):
    async def fake_load(source_date=None):
        return {
            "source_date": "2026-06-22",
            "arxiv_papers": [{"title": "P1", "type": "paper"}],
            "news_articles": [{"title": "N1", "type": "news"}],
        }

    monkeypatch.setattr(svc, "_load_daily_sources", fake_load)
    # Downstream of ranking — return trivially so we observe the ranking branch.
    monkeypatch.setattr(svc, "_process_papers_parallel", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_process_news_parallel",
                        AsyncMock(return_value=[{"type": "news", "title": "N1"}]))
    monkeypatch.setattr(svc, "_generate_final_digest", AsyncMock(return_value="<html>ok</html>"))


def test_paper_ranking_failure_still_completes_when_news_succeeds(service, monkeypatch):
    _stub_sources(monkeypatch, service)

    async def papers_boom(*a, **k):
        raise ValueError("Ranking failed: AttributeError: 'NoneType' has no attribute 'strip'")

    monkeypatch.setattr(service, "_rank_papers_separately", papers_boom)
    monkeypatch.setattr(service, "_rank_news_separately",
                        AsyncMock(return_value=[_ranked("N1", "news")]))

    complete = AsyncMock()
    monkeypatch.setattr(service, "_complete_task", complete)
    callbacks = []
    monkeypatch.setattr(dse, "send_webhook_callback",
                        AsyncMock(side_effect=lambda *a, **k: callbacks.append(a)))

    asyncio.run(service.generate_digest(
        "task-1", {"name": "X"}, callback_url="http://cb",
        digest_sources={"arxiv": True, "news_api": True},
    ))

    # Digest completed (news carried it) — the all-failed branch was NOT taken.
    assert complete.await_count == 1
    result_arg = complete.await_args.args[1]
    assert result_arg == "<html>ok</html>"


def test_news_only_digest_uses_deterministic_ranking_when_provider_returns_invalid_json(
    service, monkeypatch
):
    async def fake_load(source_date=None):
        return {
            "source_date": "2026-07-12",
            "arxiv_papers": [],
            "news_articles": [
                {
                    "title": "N1",
                    "author": "Reporter",
                    "url": "https://example.com/news/1",
                    "type": "news",
                }
            ],
        }

    monkeypatch.setattr(service, "_load_daily_sources", fake_load)
    monkeypatch.setattr(
        service.llm_client,
        "rank_news_only",
        AsyncMock(
            side_effect=ValueError(
                "Both structured output and manual parsing failed: Invalid JSON"
            )
        ),
    )
    monkeypatch.setattr(service, "_process_papers_parallel", AsyncMock(return_value=[]))

    processed_news = []

    async def process_news(items, user_info):
        processed_news.extend(items)
        return [{"type": "news", "title": item.title} for item in items]

    monkeypatch.setattr(service, "_process_news_parallel", process_news)
    monkeypatch.setattr(
        service, "_generate_final_digest", AsyncMock(return_value="<html>ok</html>")
    )

    complete = AsyncMock()
    monkeypatch.setattr(service, "_complete_task", complete)

    asyncio.run(
        service.generate_digest(
            "task-news-only",
            {"name": "X"},
            source_date="2026-07-12",
            digest_sources={"arxiv": True, "news_api": True},
        )
    )

    assert complete.await_args.args[1] == "<html>ok</html>"
    assert [item.title for item in processed_news] == ["N1"]
    assert processed_news[0].score_reason == "LLM ranking unavailable - default ranking"


def test_paper_only_digest_uses_deterministic_ranking_when_provider_returns_invalid_json(
    service, monkeypatch
):
    async def fake_load(source_date=None):
        return {
            "source_date": "2026-07-13",
            "arxiv_papers": [
                {
                    "title": "P1",
                    "authors": ["Researcher"],
                    "abstract_url": "https://example.com/paper/1",
                    "type": "paper",
                }
            ],
            "news_articles": [],
        }

    monkeypatch.setattr(service, "_load_daily_sources", fake_load)
    monkeypatch.setattr(
        service.llm_client,
        "rank_papers_only",
        AsyncMock(side_effect=ValueError("Invalid JSON in response")),
    )

    processed_papers = []

    async def process_papers(items, user_info):
        processed_papers.extend(items)
        return [{"type": "paper", "title": item.title} for item in items]

    monkeypatch.setattr(service, "_process_papers_parallel", process_papers)
    monkeypatch.setattr(service, "_process_news_parallel", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        service, "_generate_final_digest", AsyncMock(return_value="<html>ok</html>")
    )
    complete = AsyncMock()
    monkeypatch.setattr(service, "_complete_task", complete)

    asyncio.run(
        service.generate_digest(
            "task-paper-only",
            {"name": "X"},
            source_date="2026-07-13",
            digest_sources={"arxiv": True, "news_api": True},
        )
    )

    assert complete.await_args.args[1] == "<html>ok</html>"
    assert [item.title for item in processed_papers] == ["P1"]
    assert processed_papers[0].score_reason == "LLM ranking unavailable - default ranking"


def test_both_ranking_failures_fail_with_actionable_message(service, monkeypatch):
    _stub_sources(monkeypatch, service)

    async def papers_boom(*a, **k):
        raise ValueError("Ranking failed: AttributeError: papers broke")

    async def news_boom(*a, **k):
        raise ValueError("Ranking failed: AttributeError: news broke")

    monkeypatch.setattr(service, "_rank_papers_separately", papers_boom)
    monkeypatch.setattr(service, "_rank_news_separately", news_boom)

    complete = AsyncMock()
    monkeypatch.setattr(service, "_complete_task", complete)
    sent = {}
    async def fake_cb(url, task_id, status, message):
        sent.update(status=status, message=message)
    monkeypatch.setattr(dse, "send_webhook_callback", fake_cb)

    asyncio.run(service.generate_digest(
        "task-2", {"name": "X"}, callback_url="http://cb",
        digest_sources={"arxiv": True, "news_api": True},
    ))

    # Did not "complete"; sent a failed callback naming both sources.
    assert complete.await_count == 0
    assert sent["status"] == "failed"
    assert "papers:" in sent["message"] and "news:" in sent["message"]
    assert "papers broke" in sent["message"] and "news broke" in sent["message"]
