"""
Email Renderer Module - Step 1: Python Email Templates

Renders DigestEmailData to HTML using Jinja2 templates.
This replaces LLM-generated HTML with deterministic template rendering.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import logfire

from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound

from .models import DigestEmailData

# Template directory relative to this file
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates" / "email"

# Initialize Jinja2 environment with security settings
_env: Optional[Environment] = None


def _get_env() -> Environment:
    """Get or create the Jinja2 environment (lazy initialization)."""
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(enabled_extensions=("html", "jinja")),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logfire.info(f"Initialized Jinja2 environment with templates from: {TEMPLATES_DIR}")
    return _env


def render_digest_html(digest: DigestEmailData) -> str:
    """
    Render a DigestEmailData object to HTML using Jinja2 templates.

    Args:
        digest: The structured digest data to render

    Returns:
        Complete HTML string ready for email sending

    Raises:
        TemplateNotFound: If the template file is missing
        Exception: For other rendering errors
    """
    try:
        env = _get_env()
        template = env.get_template("digest.html.jinja")

        # Convert Pydantic model to dict for template rendering
        # Using model_dump() for Pydantic v2 compatibility
        digest_dict = digest.model_dump()

        html = template.render(**digest_dict)

        logfire.info(
            "Rendered digest HTML",
            template="digest.html.jinja",
            html_length=len(html),
            article_count=len(digest.directly_relevant) + len(digest.expand_knowledge) + len(digest.quick_scan),
            highlight_count=len(digest.highlights),
        )

        return html

    except TemplateNotFound as e:
        logfire.error(f"Template not found: {e}")
        raise
    except Exception as e:
        logfire.error(f"Failed to render digest HTML: {e}")
        raise


def render_digest_html_safe(digest: DigestEmailData, fallback_html: str = "") -> str:
    """
    Safely render digest HTML with fallback on error.

    Args:
        digest: The structured digest data to render
        fallback_html: HTML to return if rendering fails

    Returns:
        Rendered HTML or fallback_html on error
    """
    try:
        return render_digest_html(digest)
    except Exception as e:
        logfire.error(f"Safe render failed, using fallback: {e}")
        return fallback_html


def get_template_path() -> Path:
    """Get the path to the templates directory (useful for debugging)."""
    return TEMPLATES_DIR
