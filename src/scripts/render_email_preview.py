"""
Render a local HTML preview of the Paperboy digest email.

Usage:
  python -m paperboy.src.scripts.render_email_preview

Output:
  ./paperboy/src/scripts/out/digest_preview.html
"""

from __future__ import annotations

from pathlib import Path

from ..email_renderer import render_digest_html
from ..models import DigestEmailData, DigestStats, DigestArticle, HighlightItem


def _sample_digest() -> DigestEmailData:
    stats = DigestStats(
        paper_count=5,
        news_count=4,
        reading_time_minutes=12,
        papers_processed=120,
        articles_selected=18,
        time_saved_minutes=95,
    )

    highlights = [
        HighlightItem(title="Top theme", insight="A short, punchy highlight that reads well in email.", type="news"),
        HighlightItem(title="Actionable", insight="A second highlight with the brand look and spacing.", type="paper"),
    ]

    directly = [
        DigestArticle(
            title="Paper: Robust reasoning in LLM systems (2025)",
            type="paper",
            relevance_score=94,
            importance_label="CRITICAL",
            summary="This paper proposes a practical architecture for safer, more reliable reasoning pipelines.",
            why_relevant="This aligns with your focus on reliability and evaluation, and suggests concrete engineering patterns.",
            key_takeaway="Use deterministic structure + post-validation to reduce hallucinations.",
            article_url="https://example.com/paper",
            pdf_url="https://example.com/paper.pdf",
            source="arXiv",
        )
    ]

    expand = [
        DigestArticle(
            title="News: Major model provider updates eval tooling",
            type="news",
            relevance_score=86,
            importance_label="IMPORTANT",
            summary="A new suite of eval tools aims to make regression testing for LLM apps easier.",
            why_relevant="These tools may reduce iteration time and tighten quality gates for your digest pipeline.",
            key_takeaway="Treat prompts like code: version, test, and monitor.",
            article_url="https://example.com/news",
            pdf_url=None,
            source="Industry",
        )
    ]

    quick = [
        DigestArticle(
            title="Quick: A small but useful library release",
            type="news",
            relevance_score=72,
            importance_label="NOTEWORTHY",
            summary="A new release improves performance and introduces nicer developer ergonomics.",
            why_relevant="Might simplify a couple of steps in your current workflow.",
            key_takeaway="Worth skimming the changelog.",
            article_url="https://example.com/quick",
            pdf_url=None,
            source="GitHub",
        )
    ]

    return DigestEmailData(
        date="Sunday, Dec 14, 2025",
        user_name="Noah",
        user_title="Builder",
        stats=stats,
        highlights=highlights,
        directly_relevant=directly,
        expand_knowledge=expand,
        quick_scan=quick,
    )


def main() -> None:
    digest = _sample_digest()
    html = render_digest_html(digest)

    out_dir = Path(__file__).resolve().parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "digest_preview.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"Wrote preview to: {out_path}")


if __name__ == "__main__":
    main()

