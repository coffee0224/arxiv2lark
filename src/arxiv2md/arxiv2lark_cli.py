"""End-to-end CLI: arXiv URL → Lark docx (with images at original positions).

``arxiv2lark`` chains the existing arxiv2md ingestion pipeline with the
``lark_import`` orchestrator. It is the single command that turns a paper
URL into a properly-rendered Lark document under a target Drive folder.

Example::

    arxiv2lark https://arxiv.org/abs/2511.18793 \
        --folder-token VGh6f6odflsTqAdnk4dcC28znJg \
        --remove-inline-citations
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from arxiv2md.ingestion import ingest_paper
from arxiv2md.lark_import import LarkImportError, import_paper_to_lark
from arxiv2md.lark_pipeline import (
    default_output_dir,
    materialize_lark_output,
    prepare_lark_output_text,
)
from arxiv2md.query_parser import parse_arxiv_input


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = _parse_args()
    try:
        asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        sys.exit(130)
    except LarkImportError as exc:
        print(f"Lark import failed: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 — surface to CLI
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


async def _async_main(args: argparse.Namespace) -> None:
    query = parse_arxiv_input(args.input_text)

    print(f"==> Fetching arXiv {query.arxiv_id} ...", file=sys.stderr)
    result, metadata = await ingest_paper(
        arxiv_id=query.arxiv_id,
        version=query.version,
        html_url=query.html_url,
        ar5iv_url=query.ar5iv_url,
        remove_refs=args.remove_refs,
        remove_toc=args.remove_toc,
        remove_inline_citations=args.remove_inline_citations,
        section_filter_mode="exclude",
        sections=[],
        include_frontmatter=False,
    )

    # Convert to lark-flavored markdown with anchor placeholders.
    content_with_anchors, images = prepare_lark_output_text(result.content)
    full_text = "\n\n".join(part for part in (result.summary, content_with_anchors) if part).strip()

    # Resolve / create the output directory.
    out_dir = Path(args.output) if args.output else default_output_dir(query.arxiv_id)
    print(f"==> Output directory: {out_dir}", file=sys.stderr)

    digest_path, manifest_path = await materialize_lark_output(
        full_text=full_text,
        images=images,
        out_dir=out_dir,
    )
    downloaded = sum(1 for img in images if img.local_path)
    print(
        f"    digest={digest_path.name} manifest={manifest_path.name} "
        f"images={downloaded}/{len(images)} downloaded",
        file=sys.stderr,
    )

    title = args.title or _default_title(metadata, query.arxiv_id)
    print(f"==> Importing to Lark as: {title!r}", file=sys.stderr)
    import_result = import_paper_to_lark(
        out_dir=out_dir,
        title=title,
        folder_token=args.folder_token,
    )

    print(
        f"==> Done. {import_result.images_inserted} images inserted, "
        f"{import_result.images_skipped} skipped.",
        file=sys.stderr,
    )
    print(import_result.doc_url)


def _default_title(metadata: dict, arxiv_id: str) -> str:
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return f"arXiv:{arxiv_id}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="arxiv2lark",
        description=(
            "Convert an arXiv paper to a Lark document, downloading images "
            "locally and inserting them at their original positions."
        ),
    )
    parser.add_argument(
        "input_text",
        help="arXiv ID or URL (e.g. 2511.18793 or https://arxiv.org/abs/2511.18793)",
    )
    parser.add_argument(
        "--folder-token",
        default=None,
        help="Lark Drive folder token to import the doc into (default: drive root).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Override the document title (default: paper title from arxiv).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help=(
            "Local output directory holding digest.md, images.json, and the "
            "downloaded image files. Defaults to /tmp/<arxiv_id>_<timestamp>/."
        ),
    )
    parser.add_argument(
        "--remove-refs",
        action="store_true",
        help="Strip the references / bibliography section from the doc.",
    )
    parser.add_argument(
        "--remove-toc",
        action="store_true",
        help="Strip the auto-generated table of contents.",
    )
    parser.add_argument(
        "--remove-inline-citations",
        action="store_true",
        help="Strip inline citation markers like (Smith et al., 2023).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
