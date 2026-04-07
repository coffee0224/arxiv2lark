"""End-to-end importer that pushes a prepared arxiv2md output into Lark.

This module reads the directory layout produced by
:mod:`arxiv2md.lark_pipeline` (a ``digest.md`` plus an ``images.json``
manifest plus the local image files) and creates a Lark docx with all
images injected at their *original* anchor positions.

The strategy avoids any block-level API surgery: ``[[IMG:N]]`` anchors
split the markdown into a sequence of segments, and we use lark-cli's
high-level shortcuts to interleave them with image inserts:

1. ``docs +create`` with the first segment.
2. For each anchor in document order:

   a. ``docs +media-insert`` to upload the local image — this lands at
      the *current* end of the doc, which is exactly where the anchor
      sat in the source markdown.
   b. ``docs +update --mode append`` with the next segment.

That keeps the entire pipeline on well-supported lark-cli commands and
sidesteps the unreliable ``<image url=...>`` server-side fetch path.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from arxiv2md.lark_adapter import LarkImage
from arxiv2md.lark_pipeline import DIGEST_FILENAME, load_manifest

_ANCHOR_RE = re.compile(r"\[\[IMG:(\d+)]]")


class LarkImportError(RuntimeError):
    """Raised when the lark-cli pipeline cannot complete the import."""


@dataclass
class ImportResult:
    doc_id: str
    doc_url: str
    images_inserted: int
    images_skipped: int


def import_paper_to_lark(
    *,
    out_dir: Path,
    title: str,
    folder_token: str | None = None,
) -> ImportResult:
    """Create a Lark docx from a prepared arxiv2md output directory.

    Parameters
    ----------
    out_dir:
        Directory containing ``digest.md``, ``images.json`` and the
        downloaded image files (the layout produced by ``arxiv2md --lark``).
    title:
        Title for the new Lark document.
    folder_token:
        Target Lark Drive folder. If ``None``, the doc lands in the
        caller's drive root.
    """
    if shutil.which("lark-cli") is None:
        raise LarkImportError(
            "lark-cli is not installed or not on PATH. Install via "
            "`npm i -g @larksuite/cli` and run `lark-cli auth login`."
        )

    digest_path = out_dir / DIGEST_FILENAME
    if not digest_path.exists():
        raise LarkImportError(f"missing {digest_path}")
    md = digest_path.read_text(encoding="utf-8")

    images = load_manifest(out_dir)
    by_anchor = {img.anchor: img for img in images}

    segments, ordered_anchors = _split_by_anchors(md)

    # Step 2: create skeleton from the first segment.
    first_segment = segments[0] or " "
    doc_id, doc_url = _create_doc(title, first_segment, folder_token)
    logger.info("Created lark doc {} ({})", doc_id, doc_url)

    inserted = 0
    skipped = 0

    # Step 3-5: interleave image inserts with appended segments.
    for i, anchor in enumerate(ordered_anchors):
        img = by_anchor.get(anchor)
        if img is None:
            logger.warning("Anchor {} has no manifest entry, skipping", anchor)
            skipped += 1
        elif not img.local_path:
            logger.warning("Image {} was not downloaded, skipping", img.id)
            skipped += 1
        else:
            local_file = out_dir / img.local_path
            if not local_file.exists():
                logger.warning("Local file missing for {}: {}", img.id, local_file)
                skipped += 1
            else:
                _media_insert(doc_id, local_file, img.caption)
                inserted += 1

        next_segment = segments[i + 1]
        if next_segment.strip():
            _append_markdown(doc_id, next_segment)

    return ImportResult(
        doc_id=doc_id,
        doc_url=doc_url,
        images_inserted=inserted,
        images_skipped=skipped,
    )


# ---------------------------------------------------------------------------
# markdown splitting
# ---------------------------------------------------------------------------


def _split_by_anchors(md: str) -> tuple[list[str], list[str]]:
    """Split *md* at every ``[[IMG:N]]`` anchor.

    Returns ``(segments, anchors)`` where ``len(segments) == len(anchors) + 1``.
    Each segment is the markdown between two anchors (or before the first /
    after the last). Anchor lines themselves are stripped from the output.
    Trailing/leading whitespace per segment is preserved enough that the
    document keeps its original blank-line structure when re-assembled.
    """
    segments: list[str] = []
    anchors: list[str] = []
    cursor = 0
    for match in _ANCHOR_RE.finditer(md):
        # Strip a single trailing newline before the anchor and the newline
        # right after it, so the anchor's "own line" disappears cleanly.
        start = match.start()
        end = match.end()
        if start > 0 and md[start - 1] == "\n":
            start -= 1
        if end < len(md) and md[end] == "\n":
            end += 1
        segments.append(md[cursor:start])
        anchors.append(match.group(0))
        cursor = end
    segments.append(md[cursor:])
    return segments, anchors


# ---------------------------------------------------------------------------
# lark-cli wrappers
# ---------------------------------------------------------------------------


def _run(cmd: list[str]) -> dict:
    """Run a lark-cli command, returning the parsed top-level JSON object.

    lark-cli prints free-form status lines to stdout before its JSON payload.
    We locate the first ``{`` and parse from there.
    """
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise LarkImportError(
            f"lark-cli command failed (exit {proc.returncode}): "
            f"{' '.join(cmd[:4])}\nstderr: {proc.stderr.strip()}"
        )
    out = proc.stdout
    brace = out.find("{")
    if brace < 0:
        raise LarkImportError(f"no JSON in lark-cli output:\n{out}")
    try:
        payload = json.loads(out[brace:])
    except json.JSONDecodeError as exc:
        raise LarkImportError(f"failed to parse lark-cli JSON: {exc}\n{out}") from exc
    if not payload.get("ok", True) and "data" not in payload:
        raise LarkImportError(f"lark-cli reported error: {payload.get('error')}")
    return payload


def _create_doc(
    title: str, markdown: str, folder_token: str | None
) -> tuple[str, str]:
    cmd = [
        "lark-cli",
        "docs",
        "+create",
        "--title",
        title,
        "--markdown",
        markdown,
    ]
    if folder_token:
        cmd += ["--folder-token", folder_token]
    payload = _run(cmd)
    data = payload.get("data", {})
    doc_id = data.get("doc_id")
    doc_url = data.get("doc_url", "")
    if not doc_id:
        raise LarkImportError(f"docs +create returned no doc_id: {payload}")
    return doc_id, doc_url


def _append_markdown(doc_id: str, markdown: str) -> None:
    _run(
        [
            "lark-cli",
            "docs",
            "+update",
            "--doc",
            doc_id,
            "--mode",
            "append",
            "--markdown",
            markdown,
        ]
    )


def _media_insert(doc_id: str, file_path: Path, caption: str) -> str:
    """Upload a local image and append it as an image block.

    ``lark-cli docs +media-insert`` requires a *relative* file path inside
    the current working directory, so we change into the file's parent for
    the duration of the call.
    """
    cwd = file_path.parent.resolve()
    rel = "./" + file_path.name
    payload = _run_in(
        [
            "lark-cli",
            "docs",
            "+media-insert",
            "--doc",
            doc_id,
            "--file",
            rel,
            "--type",
            "image",
            "--align",
            "center",
            "--caption",
            caption,
        ],
        cwd=cwd,
    )
    block_id = payload.get("data", {}).get("block_id")
    if not block_id:
        raise LarkImportError(f"+media-insert returned no block_id: {payload}")
    return block_id


def _run_in(cmd: list[str], *, cwd: Path) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise LarkImportError(
            f"lark-cli command failed (exit {proc.returncode}): "
            f"{' '.join(cmd[:4])}\nstderr: {proc.stderr.strip()}"
        )
    out = proc.stdout
    brace = out.find("{")
    if brace < 0:
        raise LarkImportError(f"no JSON in lark-cli output:\n{out}")
    return json.loads(out[brace:])
