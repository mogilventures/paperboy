"""
Email theme tokens for Paperboy.

Purpose:
- Provide a single source of truth for brand styling in email templates.
- Use email-safe values (hex colors, px sizing, font stacks).

These tokens are derived from the frontend theme (Tailwind + CSS variables) in:
- paperboy-newsstand-daily/tailwind.config.ts
- paperboy-newsstand-daily/src/index.css
"""

from __future__ import annotations

THEME = {
    "colors": {
        # Paper / background (from tailwind.config.ts: paper.*)
        "paper_bg": "#F5F2E8",
        "paper_aged": "#E8E1D1",
        "paper_dark": "#D3CAB4",
        # Newsprint / ink (from tailwind.config.ts: newsprint.*)
        "newsprint": "#1A1F2C",
        "newsprint_light": "#333333",
        "newsprint_red": "#ea384c",
        # Semantic
        "background": "#F5F2E8",
        "surface": "#FFFFFF",
        "text": "#1A1F2C",
        "muted_text": "#666666",
        "border": "#D3CAB4",
        "divider": "#E8E1D1",
        "link": "#1A1F2C",
        "link_hover": "#ea384c",
        "callout_bg": "#F8F6F0",
        "callout_border": "#D3CAB4",
    },
    "type": {
        # Email-safe font stacks (webfonts may be ignored by many clients)
        "font_body": "Georgia, 'Times New Roman', serif",
        "font_heading": "'Playfair Display', Georgia, 'Times New Roman', serif",
        "font_mono": "'Courier New', Courier, monospace",
        "sizes": {
            "xs": "12px",
            "sm": "14px",
            "base": "16px",
            "lg": "18px",
            "xl": "20px",
            "h1": "32px",
            "h2": "18px",
            "h3": "16px",
        },
        "line_height": {
            "tight": "1.2",
            "normal": "1.6",
        },
    },
    "spacing": {
        "2": "2px",
        "4": "4px",
        "6": "6px",
        "8": "8px",
        "10": "10px",
        "12": "12px",
        "16": "16px",
        "20": "20px",
        "24": "24px",
        "28": "28px",
        "32": "32px",
        "40": "40px",
    },
    "radii": {
        # Frontend radius is 0.125rem (~2px). Emails benefit from small radii only.
        "sm": "2px",
        "md": "4px",
    },
    "layout": {
        # Common email container width for consistent client rendering
        "container_width": "600px",
        "gutter": "20px",
    },
    "components": {
        "button": {
            "bg": "#1A1F2C",
            "text": "#F5F2E8",
            "bg_hover": "#333333",
        },
        "badge": {
            "bg": "#F0EBDD",
            "text": "#1A1F2C",
            "border": "#D3CAB4",
        },
    },
}

