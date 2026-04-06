"""Post-process standard Markdown into Lark-compatible Markdown.

Lark (飞书) rich text has limited Markdown support compared to standard
Markdown. This adapter transforms the output of the arxiv2md pipeline so
that it renders correctly inside Lark messages and documents.

Key transformations:
- Images: plain-text references → ``<image>`` tags for Lark document preview.
- Display math: ``$$ … $$`` → cleaned & centered ``$$…$$`` block.
- Tables: standard pipe tables are kept (Lark supports them).
"""

from __future__ import annotations

import re


# Pattern: "Figure: caption" on one line, followed by "Alt: src_url" on the next.
_FIGURE_BLOCK_RE = re.compile(
    r"^(?P<caption>Figure:\s*.+)\n(?P<alt>.+?):\s*(?P<src>\S+)$",
    re.MULTILINE,
)

# Standalone image line without caption: "Alt text: url"
# Matches both absolute URLs and relative paths ending with image extensions.
_IMAGE_LINE_RE = re.compile(
    r"^(?P<alt>[^:\n]+):\s*(?P<src>\S+\.(?:png|jpg|jpeg|gif|svg|webp)\S*)$",
    re.MULTILINE | re.IGNORECASE,
)

# Display math: "$$ (num) $formula$ $$" or "$$ formula $$"
# Captures the entire line so we can clean up nested $ and equation numbers.
_DISPLAY_MATH_RE = re.compile(r"^\$\$\s*(.+?)\s*\$\$$", re.MULTILINE)

_ARXIV_HTML_BASE = "https://arxiv.org"


def convert_markdown_to_lark(md: str, *, arxiv_html_base: str = _ARXIV_HTML_BASE) -> str:
    """Transform standard arxiv2md Markdown into Lark-compatible format."""
    result = md

    # 1. Convert figure blocks (caption + image) to <image> tags
    result = _FIGURE_BLOCK_RE.sub(
        lambda m: _figure_to_lark(m, arxiv_html_base),
        result,
    )

    # 2. Clean up display math for centered rendering
    result = _DISPLAY_MATH_RE.sub(_clean_display_math, result)

    # 3. Convert remaining standalone image lines to <image> tags
    result = _IMAGE_LINE_RE.sub(
        lambda m: _image_line_to_lark(m, arxiv_html_base),
        result,
    )

    return result


def _clean_display_math(match: re.Match) -> str:
    """Clean display math for Lark: strip nested $, move eq number, ensure $$…$$ block."""
    inner = match.group(1).strip()

    # Extract leading equation number like "(1)" or "(2.3)"
    eq_num = ""
    num_match = re.match(r"^\([\d.]+\)\s*", inner)
    if num_match:
        eq_num = num_match.group(0).strip()
        inner = inner[num_match.end():]

    # Strip nested inline-math $ delimiters: "$formula$" → "formula"
    # Handle multiple adjacent $…$ groups (e.g. "$a$ $=b$" → "a =b")
    inner = re.sub(r"\$([^$]*)\$", r"\1", inner)
    inner = inner.strip()

    if not inner:
        return match.group(0)

    # Append equation number at the end if present
    if eq_num:
        inner = f"{inner} \\qquad {eq_num}"

    return f"$$\n{inner}\n$$"


def _resolve_src(src: str, base: str) -> str:
    """Make relative image paths absolute."""
    if src.startswith(("http://", "https://")):
        return src
    return base.rstrip("/") + "/" + src.lstrip("/")


def _figure_to_lark(match: re.Match, base: str) -> str:
    caption = match.group("caption").replace("Figure: ", "", 1)
    src = _resolve_src(match.group("src").strip(), base)
    return f'<image url="{src}" caption="{caption}"/>'


def _image_line_to_lark(match: re.Match, base: str) -> str:
    alt = match.group("alt").strip()
    src = _resolve_src(match.group("src").strip(), base)
    return f'<image url="{src}" caption="{alt}"/>'
