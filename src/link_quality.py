"""Privacy-safe link accessibility classification from existing extraction evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Callable

import logfire


_PAYWALL_PATTERN = re.compile(
    r"(?:subscribe|subscription) (?:to continue|to read|required)|"
    r"already a subscriber|subscriber[- ]only|"
    r"(?:sign in|log in|register) to continue reading|"
    r"(?:sign[- ]in|login) required",
    re.IGNORECASE,
)
_BROKEN_PATTERN = re.compile(
    r"(?:http(?: status)?\s*)?(?:404|410)\b|"
    r"\b(?:page|resource) not found\b|"
    r"\bdns (?:name )?resolution failed\b|"
    r"\bno such host\b|\binvalid (?:url|host)\b",
    re.IGNORECASE,
)


class LinkAccessStatus(str, Enum):
    ACCESSIBLE = "accessible"
    SUSPECTED_PAYWALL = "suspected_paywall"
    BROKEN = "broken"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LinkQualityOutcome:
    status: LinkAccessStatus
    extraction_success: bool
    content: str = ""


def summarize_link_quality(outcomes: list[LinkQualityOutcome]) -> dict[str, int | float | str]:
    """Build the bounded aggregate event recorded for one digest."""
    total = len(outcomes)
    counts = {
        status: sum(1 for outcome in outcomes if outcome.status is status)
        for status in LinkAccessStatus
    }

    def percentage(status: LinkAccessStatus) -> float:
        return round((counts[status] / total) * 100, 1) if total else 0.0

    return {
        "schema_version": 1,
        "measurement_scope": "selected_news_links",
        "attempted_count": total,
        "accessible_count": counts[LinkAccessStatus.ACCESSIBLE],
        "suspected_paywall_count": counts[LinkAccessStatus.SUSPECTED_PAYWALL],
        "broken_count": counts[LinkAccessStatus.BROKEN],
        "unknown_count": counts[LinkAccessStatus.UNKNOWN],
        "extraction_success_count": sum(
            1 for outcome in outcomes if outcome.extraction_success
        ),
        "accessible_pct": percentage(LinkAccessStatus.ACCESSIBLE),
        "suspected_paywall_pct": percentage(LinkAccessStatus.SUSPECTED_PAYWALL),
        "broken_pct": percentage(LinkAccessStatus.BROKEN),
        "unknown_pct": percentage(LinkAccessStatus.UNKNOWN),
    }


def emit_link_quality_summary(
    outcomes: list[LinkQualityOutcome],
    *,
    emit: Callable[..., Any] | None = None,
) -> dict[str, int | float | str]:
    """Emit exactly one bounded event and return its attributes."""
    summary = summarize_link_quality(outcomes)
    emitter = emit or logfire.info
    emitter("Digest link quality measured", **summary)
    return summary


def classify_tavily_result(
    *, content: str = "", failure_error: str | None = None
) -> LinkQualityOutcome:
    """Classify one target using only Tavily's existing response evidence."""
    failure_evidence = failure_error or ""
    content_evidence = content[:1000]
    has_extractable_content = len(content.strip()) >= 100
    if _PAYWALL_PATTERN.search(f"{failure_evidence}\n{content_evidence}"):
        return LinkQualityOutcome(
            status=LinkAccessStatus.SUSPECTED_PAYWALL,
            extraction_success=has_extractable_content,
            content=content,
        )
    if _BROKEN_PATTERN.search(failure_evidence):
        return LinkQualityOutcome(
            status=LinkAccessStatus.BROKEN,
            extraction_success=False,
            content=content,
        )
    if has_extractable_content:
        return LinkQualityOutcome(
            status=LinkAccessStatus.ACCESSIBLE,
            extraction_success=True,
            content=content,
        )
    return LinkQualityOutcome(
        status=LinkAccessStatus.UNKNOWN,
        extraction_success=False,
        content=content,
    )
