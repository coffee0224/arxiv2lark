"""Tests for Lark Markdown adapter."""

from __future__ import annotations

from arxiv2md.lark_adapter import (
    convert_markdown_to_lark,
    convert_markdown_to_lark_with_manifest,
)


def test_figure_block_converted_to_image_tag() -> None:
    md = "Figure: A sample diagram\nDiagram: https://arxiv.org/html/2501.11120v1/x1.png"
    result = convert_markdown_to_lark(md)
    assert '<image url="https://arxiv.org/html/2501.11120v1/x1.png" caption="A sample diagram"/>' in result


def test_absolute_url_kept() -> None:
    md = "Figure: Photo\nPhoto: https://example.com/img.png"
    result = convert_markdown_to_lark(md)
    assert 'url="https://example.com/img.png"' in result


def test_standalone_image_line() -> None:
    md = "Some text\nImage: https://arxiv.org/html/2501.11120v1/figure1.png\nMore text"
    result = convert_markdown_to_lark(md)
    assert '<image url="https://arxiv.org/html/2501.11120v1/figure1.png" caption="Image"/>' in result
    assert "Some text" in result
    assert "More text" in result


def test_no_images_unchanged() -> None:
    md = "## Introduction\n\nSome plain text with $x+y$ math."
    result = convert_markdown_to_lark(md)
    assert result == md


def test_relative_path_resolved() -> None:
    md = "Figure: Chart\nChart: /html/123/fig.png"
    result = convert_markdown_to_lark(md)
    assert 'url="https://arxiv.org/html/123/fig.png"' in result


def test_custom_base_url() -> None:
    md = "Figure: Chart\nChart: /html/123/fig.png"
    result = convert_markdown_to_lark(md, arxiv_html_base="https://ar5iv.labs.arxiv.org")
    assert 'url="https://ar5iv.labs.arxiv.org/html/123/fig.png"' in result


def test_display_math_centered() -> None:
    md = r"$$ (1) $Goodput=\frac{A}{B}$ $$"
    result = convert_markdown_to_lark(md)
    assert result == '<equation>Goodput=\\frac{A}{B} \\qquad (1)</equation> {align="center"}'


def test_display_math_no_number() -> None:
    md = r"$$ $x + y = z$ $$"
    result = convert_markdown_to_lark(md)
    assert result == '<equation>x + y = z</equation> {align="center"}'


def test_display_math_without_inner_delimiters() -> None:
    md = r"$$ x^2 + y^2 $$"
    result = convert_markdown_to_lark(md)
    assert result == '<equation>x^2 + y^2</equation> {align="center"}'


def test_display_math_multiple_groups() -> None:
    md = r"$$ (3) $T_{fwd}(M)$ $=\alpha\cdot N$ $$"
    result = convert_markdown_to_lark(md)
    assert result == '<equation>T_{fwd}(M) =\\alpha\\cdot N \\qquad (3)</equation> {align="center"}'


def test_manifest_mode_emits_anchors_and_collects_images() -> None:
    md = (
        "Intro text\n"
        "Figure: Alpha\nDiagram: https://arxiv.org/html/x/a.png\n"
        "Middle text\n"
        "Figure: Beta\nDiagram: https://arxiv.org/html/x/b.png\n"
        "Tail text"
    )
    result, images = convert_markdown_to_lark_with_manifest(md)

    assert "[[IMG:1]]" in result
    assert "[[IMG:2]]" in result
    assert "<image" not in result  # anchors replace inline tags

    assert [img.id for img in images] == ["fig-1", "fig-2"]
    assert images[0].url == "https://arxiv.org/html/x/a.png"
    assert images[0].caption == "Alpha"
    assert images[0].anchor == "[[IMG:1]]"
    assert images[1].url == "https://arxiv.org/html/x/b.png"
    assert images[1].caption == "Beta"
    assert all(img.local_path is None for img in images)


def test_manifest_mode_no_images_returns_empty_list() -> None:
    md = "## Intro\n\nplain text only"
    result, images = convert_markdown_to_lark_with_manifest(md)
    assert images == []
    assert result == md


def test_split_by_anchors_basic() -> None:
    from arxiv2md.lark_import import _split_by_anchors

    md = "before\n[[IMG:1]]\nmiddle\n[[IMG:2]]\nafter"
    segments, anchors = _split_by_anchors(md)
    assert anchors == ["[[IMG:1]]", "[[IMG:2]]"]
    assert segments == ["before", "middle", "after"]


def test_split_by_anchors_no_anchors() -> None:
    from arxiv2md.lark_import import _split_by_anchors

    md = "no images here"
    segments, anchors = _split_by_anchors(md)
    assert anchors == []
    assert segments == [md]
