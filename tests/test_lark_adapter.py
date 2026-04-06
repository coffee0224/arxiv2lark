"""Tests for Lark Markdown adapter."""

from __future__ import annotations

from arxiv2md.lark_adapter import convert_markdown_to_lark


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
    assert result == "$$\nGoodput=\\frac{A}{B} \\qquad (1)\n$$"


def test_display_math_no_number() -> None:
    md = r"$$ $x + y = z$ $$"
    result = convert_markdown_to_lark(md)
    assert result == "$$\nx + y = z\n$$"


def test_display_math_without_inner_delimiters() -> None:
    md = r"$$ x^2 + y^2 $$"
    result = convert_markdown_to_lark(md)
    assert result == "$$\nx^2 + y^2\n$$"


def test_display_math_multiple_groups() -> None:
    md = r"$$ (3) $T_{fwd}(M)$ $=\alpha\cdot N$ $$"
    result = convert_markdown_to_lark(md)
    assert result == "$$\nT_{fwd}(M) =\\alpha\\cdot N \\qquad (3)\n$$"
