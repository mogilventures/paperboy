"""Digest rendering contract for the Paperboy feedback CTA."""

from src.config import settings
from src.email_renderer import render_digest_html
from src.models import DigestEmailData, DigestStats


def test_digest_renders_feedback_cta_before_footer() -> None:
    digest = DigestEmailData(
        date="July 16, 2026",
        user_name="Ada",
        user_title="Researcher",
        stats=DigestStats(),
    )

    html = render_digest_html(digest)

    assert html.count("https://tally.so/r/A7G02o") == 1
    assert "Help shape Paperboy" in html
    assert html.index("Help shape Paperboy") < html.index("Your Research Impact This Week")
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_feedback_cta_can_be_disabled_without_changing_the_template(monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_cta_enabled", False)
    digest = DigestEmailData(
        date="July 16, 2026",
        user_name="Ada",
        user_title="Researcher",
        stats=DigestStats(),
    )

    html = render_digest_html(digest)

    assert "https://tally.so/r/A7G02o" not in html
    assert "Help shape Paperboy" not in html


def test_feedback_cta_uses_configured_form_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "feedback_cta_enabled", True)
    monkeypatch.setattr(settings, "feedback_form_url", "https://tally.so/r/NEW123")
    digest = DigestEmailData(
        date="July 16, 2026",
        user_name="Ada",
        user_title="Researcher",
        stats=DigestStats(),
    )

    html = render_digest_html(digest)

    assert "https://tally.so/r/NEW123" in html
    assert "https://tally.so/r/A7G02o" not in html
