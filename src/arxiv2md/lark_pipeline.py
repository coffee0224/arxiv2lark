"""Shared helpers for the Lark output pipeline.

These helpers turn an arxiv2md ``IngestionResult`` (or any Markdown body)
into a self-contained directory layout that downstream tools (the
``arxiv2lark`` importer, manual editing, etc.) can consume:

::

    <out_dir>/
        digest.md         # Lark-flavored Markdown with [[IMG:N]] anchors
        images.json       # manifest mapping anchors → local image files
        fig-1.png
        fig-2.png
        ...

Both the ``arxiv2md --lark`` CLI and the ``arxiv2lark`` end-to-end command
use these helpers, so the on-disk format stays in sync.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

import httpx
from loguru import logger

from arxiv2md.lark_adapter import (
    LarkImage,
    convert_markdown_to_lark_with_manifest,
)

DIGEST_FILENAME = "digest.md"
MANIFEST_FILENAME = "images.json"

# Skip downloads larger than this (Lark image block hard limit is 10 MB).
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def default_output_dir(arxiv_id: str) -> Path:
    """Return a fresh ``/tmp/<arxiv_id>_<timestamp>/`` directory.

    The directory is created if it does not exist. The timestamp suffix
    ensures repeated runs against the same paper do not collide.
    """
    safe = arxiv_id.replace("/", "_")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path("/tmp") / f"{safe}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_manifest(images: list[LarkImage], out_dir: Path) -> Path:
    """Serialize the image manifest to ``images.json`` inside ``out_dir``."""
    path = out_dir / MANIFEST_FILENAME
    payload = {"images": [asdict(img) for img in images]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_manifest(out_dir: Path) -> list[LarkImage]:
    """Load an ``images.json`` manifest written by :func:`write_manifest`."""
    raw = json.loads((out_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    return [LarkImage(**entry) for entry in raw["images"]]


async def download_images(images: list[LarkImage], out_dir: Path) -> None:
    """Download each image into ``out_dir`` and populate ``local_path``.

    Failures are logged but do not abort the run; the corresponding
    ``LarkImage.local_path`` simply stays ``None``, and downstream consumers
    skip those entries.
    """
    if not images:
        return

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        await asyncio.gather(*(_download_one(client, img, out_dir) for img in images))


async def _download_one(
    client: httpx.AsyncClient, img: LarkImage, out_dir: Path
) -> None:
    suffix = Path(urlparse(img.url).path).suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        suffix = ".png"
    target = out_dir / f"{img.id}{suffix}"

    if target.exists() and target.stat().st_size > 0:
        img.local_path = target.name
        return

    try:
        resp = await client.get(img.url)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — surfaced via warning
        logger.warning("Failed to download {}: {}", img.url, exc)
        return

    body = resp.content
    if len(body) > _MAX_IMAGE_BYTES:
        logger.warning(
            "Skipping {} ({} bytes > 10MB limit)", img.url, len(body)
        )
        return

    target.write_bytes(body)
    img.local_path = target.name


def prepare_lark_output_text(content: str) -> tuple[str, list[LarkImage]]:
    """Run the lark adapter in manifest mode without touching the filesystem."""
    return convert_markdown_to_lark_with_manifest(content)


async def materialize_lark_output(
    *,
    full_text: str,
    images: list[LarkImage],
    out_dir: Path,
) -> tuple[Path, Path]:
    """Persist ``digest.md`` and download all referenced images.

    Returns ``(digest_path, manifest_path)``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    digest_path = out_dir / DIGEST_FILENAME
    digest_path.write_text(full_text, encoding="utf-8")

    await download_images(images, out_dir)
    manifest_path = write_manifest(images, out_dir)
    return digest_path, manifest_path
