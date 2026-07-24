"""Behavioral tests for NewsAPI requests."""

import asyncio

import httpx

from src.config import settings
from src.news_fetcher import NewsAPIFetcher


def test_news_api_credentials_are_sent_in_a_header_not_the_url(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "totalResults": 1,
                "articles": [
                    {
                        "title": "AI update",
                        "description": "AI research news",
                        "url": "https://example.com/ai-update",
                        "publishedAt": "2026-07-23T12:00:00Z",
                        "source": {"name": "Example"},
                    }
                ],
            },
        )

    monkeypatch.setattr(settings, "newsapi_key", "test-news-key")
    fetcher = NewsAPIFetcher()
    original_client = fetcher.client
    fetcher.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    fetcher._min_request_interval = 0

    async def run_fetch() -> list[dict]:
        await original_client.aclose()
        try:
            return await fetcher.fetch_news(
                queries=["AI"], target_date="2026-07-23", max_articles=10
            )
        finally:
            await fetcher.close()

    articles = asyncio.run(run_fetch())

    assert len(articles) == 1
    assert len(requests) == 1
    assert "apiKey" not in requests[0].url.params
    assert requests[0].headers["x-api-key"] == "test-news-key"
