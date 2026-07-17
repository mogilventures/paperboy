"""Behavioral tests for privacy-safe link-quality classification."""

import asyncio

import httpx

from src.config import settings
from src.content_extractor import TavilyExtractor
from src.digest_service_enhanced import EnhancedDigestService
from src.models import ContentType, RankedArticle
from src.link_quality import (
    LinkAccessStatus,
    LinkQualityOutcome,
    classify_tavily_result,
    emit_link_quality_summary,
    summarize_link_quality,
)


def test_valid_extracted_content_is_accessible() -> None:
    outcome = classify_tavily_result(
        content="A complete article body. " * 20,
        failure_error=None,
    )

    assert outcome.status is LinkAccessStatus.ACCESSIBLE
    assert outcome.extraction_success is True


def test_explicit_paywall_evidence_is_classified_conservatively() -> None:
    failed = classify_tavily_result(
        failure_error="Unable to extract: subscription required to continue reading"
    )
    teaser = classify_tavily_result(
        content="Subscribe to continue reading this article. Already a subscriber? Sign in."
    )

    assert failed.status is LinkAccessStatus.SUSPECTED_PAYWALL
    assert teaser.status is LinkAccessStatus.SUSPECTED_PAYWALL
    assert failed.extraction_success is False
    assert teaser.extraction_success is False

    full_but_paywalled = classify_tavily_result(
        content="Subscribe to continue reading. " + ("Useful extracted article text. " * 20)
    )
    assert full_but_paywalled.status is LinkAccessStatus.SUSPECTED_PAYWALL
    assert full_but_paywalled.extraction_success is True


def test_terminal_link_failures_are_broken_but_ambiguous_failures_are_unknown() -> None:
    for error in (
        "HTTP 404: page not found",
        "HTTP 410: resource gone",
        "DNS name resolution failed",
        "Invalid host in URL",
    ):
        assert classify_tavily_result(failure_error=error).status is LinkAccessStatus.BROKEN

    for error in ("HTTP 403: access denied", "request timed out", "provider returned 503"):
        assert classify_tavily_result(failure_error=error).status is LinkAccessStatus.UNKNOWN

    article_prose = "A study of 404 participants and the phrase page not found. " * 10
    assert classify_tavily_result(content=article_prose).status is LinkAccessStatus.ACCESSIBLE


def test_extractor_classifies_failed_result_without_a_second_fetch(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [],
                "failed_results": [
                    {
                        "url": "https://publisher.example/story",
                        "error": "Subscription required to continue reading",
                    }
                ],
                "request_id": "req-1",
            },
        )

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    extractor = TavilyExtractor(client=client)

    outcome = asyncio.run(
        extractor.extract_single_with_quality("https://publisher.example/story")
    )
    asyncio.run(client.aclose())

    assert outcome.status is LinkAccessStatus.SUSPECTED_PAYWALL
    assert outcome.extraction_success is False
    assert len(requests) == 1


def test_extractor_treats_malformed_response_as_unknown(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=["not", "an", "object"])

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    extractor = TavilyExtractor(client=client)

    outcome = asyncio.run(
        extractor.extract_single_with_quality("https://publisher.example/story")
    )
    asyncio.run(client.aclose())

    assert outcome.status is LinkAccessStatus.UNKNOWN
    assert outcome.extraction_success is False
    assert len(requests) == 1


def test_extractor_retries_one_transient_provider_failure(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={"results": [{"content": "Recovered article body. " * 20}]},
        )

    async def no_wait(seconds: float) -> None:
        pass

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    extractor = TavilyExtractor(client=client, sleep=no_wait)

    outcome = asyncio.run(
        extractor.extract_single_with_quality("https://publisher.example/story")
    )
    asyncio.run(client.aclose())

    assert outcome.status is LinkAccessStatus.ACCESSIBLE
    assert outcome.extraction_success is True
    assert len(requests) == 2


def test_extractor_retries_one_rate_limit_response(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={"results": [{"content": "Recovered article body. " * 20}]},
        )

    async def no_wait(seconds: float) -> None:
        pass

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    extractor = TavilyExtractor(client=client, sleep=no_wait)

    outcome = asyncio.run(
        extractor.extract_single_with_quality("https://publisher.example/story")
    )
    asyncio.run(client.aclose())

    assert outcome.status is LinkAccessStatus.ACCESSIBLE
    assert len(requests) == 2


def test_repeated_rate_limit_suppresses_more_requests_for_the_utc_day(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, json={"error": "rate limited"})

    async def no_wait(seconds: float) -> None:
        pass

    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    extractor = TavilyExtractor(client=client, sleep=no_wait)

    first = asyncio.run(
        extractor.extract_single_with_quality("https://publisher.example/one")
    )
    second = asyncio.run(
        extractor.extract_single_with_quality("https://publisher.example/two")
    )
    asyncio.run(client.aclose())

    assert first.status is LinkAccessStatus.UNKNOWN
    assert second.status is LinkAccessStatus.UNKNOWN
    assert len(requests) == 2  # first attempt + one retry; second URL is suppressed


def test_summary_reports_percentages_without_link_or_user_data() -> None:
    outcomes = [
        LinkQualityOutcome(LinkAccessStatus.ACCESSIBLE, True),
        LinkQualityOutcome(LinkAccessStatus.ACCESSIBLE, True),
        LinkQualityOutcome(LinkAccessStatus.SUSPECTED_PAYWALL, False),
        LinkQualityOutcome(LinkAccessStatus.BROKEN, False),
        LinkQualityOutcome(LinkAccessStatus.UNKNOWN, False),
    ]

    summary = summarize_link_quality(outcomes)

    assert summary == {
        "schema_version": 1,
        "measurement_scope": "selected_news_links",
        "attempted_count": 5,
        "accessible_count": 2,
        "suspected_paywall_count": 1,
        "broken_count": 1,
        "unknown_count": 1,
        "extraction_success_count": 2,
        "accessible_pct": 40.0,
        "suspected_paywall_pct": 20.0,
        "broken_pct": 20.0,
        "unknown_pct": 20.0,
    }
    assert not ({"url", "domain", "title", "email", "user_id", "task_id"} & summary.keys())


def test_emitter_records_one_bounded_privacy_safe_event() -> None:
    events: list[tuple[str, dict]] = []

    def record(message: str, **attributes) -> None:
        events.append((message, attributes))

    outcomes = [
        LinkQualityOutcome(LinkAccessStatus.ACCESSIBLE, True),
        LinkQualityOutcome(LinkAccessStatus.BROKEN, False),
    ]
    emit_link_quality_summary(outcomes, emit=record)

    assert len(events) == 1
    message, attributes = events[0]
    assert message == "Digest link quality measured"
    assert attributes["attempted_count"] == 2
    assert attributes["broken_pct"] == 50.0
    serialized = repr(attributes).lower()
    for forbidden in ("https://", "publisher", "email", "user_id", "task_id"):
        assert forbidden not in serialized


def test_news_processing_falls_back_and_reports_one_aggregate_event() -> None:
    class Extractor:
        def __init__(self) -> None:
            self.calls = 0

        async def extract_single_with_quality(self, url: str) -> LinkQualityOutcome:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("unexpected extractor defect")
            return LinkQualityOutcome(LinkAccessStatus.BROKEN, False)

    class LLM:
        def __init__(self) -> None:
            self.calls = 0

        async def summarize_single_news(self, article, content, user_info):
            self.calls += 1
            return {
                "title": article["title"],
                "type": "news",
                "summary": content,
                "url": article["url"],
            }

    class Breaker:
        async def call(self, fn, *args):
            return await fn(*args)

    class Breakers:
        def get(self, name: str) -> Breaker:
            return Breaker()

    reports: list[list[LinkQualityOutcome]] = []
    service = EnhancedDigestService.__new__(EnhancedDigestService)
    service.content_extractor = Extractor()
    service.llm_client = LLM()
    service.circuit_breakers = Breakers()
    service.link_quality_reporter = lambda outcomes: reports.append(list(outcomes))
    articles = [
        RankedArticle(
            title=f"Story {index}",
            authors=["Reporter"],
            subject="news",
            score_reason="Useful preview content",
            relevance_score=90,
            abstract_url=f"https://publisher.example/story-{index}",
            type=ContentType.NEWS,
        )
        for index in (1, 2)
    ]

    summaries = asyncio.run(service._process_news_parallel(articles, {"name": "Ada"}))

    assert len(summaries) == 2
    assert service.llm_client.calls == 2
    assert len(reports) == 1
    assert [outcome.status for outcome in reports[0]] == [
        LinkAccessStatus.UNKNOWN,
        LinkAccessStatus.BROKEN,
    ]
