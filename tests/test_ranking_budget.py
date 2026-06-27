"""Regression tests for the 2026-06-27 context-length incident.

50 digests, 35 failed with Fireworks 400 "prompt is too long" (~141k > 131k
tokens). Root cause: the source-separated ranking path
(rank_papers_only / rank_news_only) sent the full daily corpus (646 papers) to
the LLM, bypassing the RANKING_INPUT_MAX_ARTICLES cap the mixed path already had.

Secondary bug: news items carry ``url`` not ``abstract_url``; normalization
mapped score/reason but not the URL, so every news item failed RankedArticle
validation and the all-sources failure followed.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import src.config as config_module
from src import llm_client as llm_module
from src.llm_client import LLMClient, RankingResponse


class _FakeAsyncOpenAI:
    def __init__(self, **kwargs):
        self.responses = SimpleNamespace(create=None)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=None))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(llm_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(config_module.settings, "llm_provider", "openai", raising=False)
    monkeypatch.setattr(config_module.settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(config_module.settings, "ranking_input_max_articles", 20, raising=False)
    monkeypatch.setattr(config_module.settings, "ranking_delay", 0, raising=False)
    return LLMClient()


def _capture_prompt(client, monkeypatch):
    """Patch the LLM call to record the user prompt and return one ranking."""
    captured = {}

    async def fake_call(system_prompt, user_prompt, response_model, **kwargs):
        captured["user_prompt"] = user_prompt
        return RankingResponse(articles=[{
            "title": "x", "authors": ["a"], "subject": "cs.AI",
            "abstract_url": "https://example.com/x",
            "relevance_score": 50, "score_reason": "r",
        }])

    monkeypatch.setattr(client, "_call_llm_structured", fake_call)
    return captured


def _serialized_items(user_prompt, label):
    """Pull the JSON array that follows e.g. 'Papers:' out of the prompt."""
    payload = user_prompt.split(f"{label}:\n", 1)[1]
    return json.loads(payload)


def test_large_paper_input_is_capped_before_serialization(client, monkeypatch):
    captured = _capture_prompt(client, monkeypatch)
    papers = [
        {"title": f"P{i}", "authors": ["A"], "subject": "cs.AI",
         "abstract_url": f"https://arxiv.org/abs/{i}"}
        for i in range(646)
    ]

    asyncio.run(client.rank_papers_only(papers, {"name": "X"}, top_n=10))

    serialized = _serialized_items(captured["user_prompt"], "Papers")
    assert len(serialized) == 20  # not 646 — the provider never sees the full corpus


def test_large_news_input_is_capped_before_serialization(client, monkeypatch):
    captured = _capture_prompt(client, monkeypatch)
    news = [
        {"title": f"N{i}", "url": f"https://news.example.com/{i}", "type": "news"}
        for i in range(200)
    ]

    asyncio.run(client.rank_news_only(news, {"name": "X"}, top_n=10))

    serialized = _serialized_items(captured["user_prompt"], "News Articles")
    assert len(serialized) == 20


def test_news_item_with_url_but_no_abstract_url_validates(client):
    """A news item carrying only 'url' must normalize into a valid RankedArticle."""
    item = {
        "title": "Some news",
        "authors": ["Reporter"],
        "url": "https://news.example.com/story",  # no abstract_url
        "relevance_score": 70,
        "score_reason": "relevant",
        "type": "news",
        # no subject either
    }
    client._normalize_ranking_fields(item, content_type="news", infer_type=False)

    from src.models import RankedArticle
    article = RankedArticle(**item)
    assert str(article.abstract_url) == "https://news.example.com/story"
    assert article.subject == "news"
    assert article.type.value == "news"
