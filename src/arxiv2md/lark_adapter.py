"""Post-process standard Markdown into Lark-compatible Markdown.

Lark (飞书) rich text has limited Markdown support compared to standard
Markdown. This adapter transforms the output of the arxiv2md pipeline so
that it renders correctly inside Lark messages and documents.

Key transformations:
- Images: plain-text references → ``<image>`` tags for Lark document preview.
- Display math: ``$$ … $$`` → cleaned & centered ``$$…$$`` block.
- Tables: standard pipe tables are kept (Lark supports them).

Two output modes are supported:

* ``convert_markdown_to_lark(md)`` (default): emit ``<image url="..." caption="..."/>``
  tags inline. Suitable when the consumer can fetch images itself.
* ``convert_markdown_to_lark_with_manifest(md)``: emit a unique ``[[IMG:N]]``
  anchor on its own line in place of every image, and return a parallel
  ``LarkImage`` manifest. Suitable for the arxiv2lark pipeline, which
  downloads images locally and injects them via the docx blocks API at the
  exact anchor positions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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


@dataclass
class LarkImage:
    """Manifest entry for an image extracted from arxiv2md output."""

    id: str          # stable id, e.g. "fig-1"
    anchor: str      # unique placeholder string emitted in markdown, e.g. "[[IMG:1]]"
    url: str         # absolute source URL (arxiv or other)
    caption: str     # human-readable caption
    local_path: str | None = None  # set after download by the pipeline


@dataclass
class _ManifestState:
    images: list[LarkImage] = field(default_factory=list)

    def add(self, *, url: str, caption: str) -> str:
        idx = len(self.images) + 1
        anchor = f"[[IMG:{idx}]]"
        self.images.append(
            LarkImage(id=f"fig-{idx}", anchor=anchor, url=url, caption=caption)
        )
        return anchor


def convert_markdown_to_lark(md: str, *, arxiv_html_base: str = _ARXIV_HTML_BASE) -> str:
    """Transform standard arxiv2md Markdown into Lark-compatible format.

    Inline mode: emits ``<image url="..." caption="..."/>`` tags. Captions
    are kept verbatim.
    """
    return _convert(md, arxiv_html_base=arxiv_html_base, manifest=None)


def convert_markdown_to_lark_with_manifest(
    md: str, *, arxiv_html_base: str = _ARXIV_HTML_BASE
) -> tuple[str, list[LarkImage]]:
    """Transform Markdown emitting ``[[IMG:N]]`` anchors and a parallel manifest.

    Used by the arxiv2lark pipeline so that images can be downloaded locally
    and re-injected into the Lark doc at the exact anchor positions via the
    docx blocks API.
    """
    state = _ManifestState()
    result = _convert(md, arxiv_html_base=arxiv_html_base, manifest=state)
    return result, state.images


def _convert(
    md: str, *, arxiv_html_base: str, manifest: _ManifestState | None
) -> str:
    result = md

    # 1. Convert figure blocks (caption + image)
    result = _FIGURE_BLOCK_RE.sub(
        lambda m: _figure_to_lark(m, arxiv_html_base, manifest),
        result,
    )

    # 2. Clean up display math for centered rendering
    result = _DISPLAY_MATH_RE.sub(_clean_display_math, result)

    # 3. Convert remaining standalone image lines
    result = _IMAGE_LINE_RE.sub(
        lambda m: _image_line_to_lark(m, arxiv_html_base, manifest),
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


def _figure_to_lark(
    match: re.Match, base: str, manifest: _ManifestState | None
) -> str:
    caption = match.group("caption").replace("Figure: ", "", 1)
    src = _resolve_src(match.group("src").strip(), base)
    if manifest is not None:
        return manifest.add(url=src, caption=caption)
    return f'<image url="{src}" caption="{caption}"/>'


def _image_line_to_lark(
    match: re.Match, base: str, manifest: _ManifestState | None
) -> str:
    alt = match.group("alt").strip()
    src = _resolve_src(match.group("src").strip(), base)
    if manifest is not None:
        return manifest.add(url=src, caption=alt)
    return f'<image url="{src}" caption="{alt}"/>'
