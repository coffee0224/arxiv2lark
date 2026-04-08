#!/usr/bin/env python3
"""List commentable blocks of a Lark docx document.

Walks the block tree via ``lark-cli api`` and emits a JSON array of
candidate blocks the LLM should consider commenting on. Filters out
empty paragraphs, citation-only blocks, and other low-value targets so
the LLM doesn't waste tokens reasoning over noise.

Usage:
    python list_commentable_blocks.py <doc_id>
    python list_commentable_blocks.py <doc_id> --max 200

Output JSON shape::

    [
      {"block_id": "...", "type": "heading2", "text": "3. Methodology"},
      {"block_id": "...", "type": "image",    "text": "<image>"},
      {"block_id": "...", "type": "equation", "text": "L = ..."},
      {"block_id": "...", "type": "text",     "text": "We achieve 23.4% ..."}
    ]

The ``type`` field is a friendly label, not the raw lark block_type
integer. ``text`` is a short preview (<= 400 chars) suitable for
prompting; for headings/equations it's the full content.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

# Lark docx block_type integer → friendly label.
# See https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/document-docx/docx-v1/data-structure/block
_BLOCK_TYPE = {
    1: "page",
    2: "text",
    3: "heading1",
    4: "heading2",
    5: "heading3",
    6: "heading4",
    7: "heading5",
    8: "heading6",
    9: "heading7",
    10: "heading8",
    11: "heading9",
    12: "bullet",
    13: "ordered",
    14: "code",
    15: "quote",
    17: "todo",
    19: "callout",
    27: "image",
    31: "table",
    34: "quote_container",
}

# Heuristics for "this paragraph might contain a claim worth commenting on".
# We're permissive — the LLM does the final filtering.
_CLAIM_HINTS = re.compile(
    r"\b("
    r"we (?:propose|present|introduce|show|demonstrate|find|observe|achieve|prove)"
    r"|outperforms?|state[- ]of[- ]the[- ]art|sota"
    r"|(?:\d+(?:\.\d+)?%)"  # any percentage
    r"|(?:\d+(?:\.\d+)?\s*[x×])"  # speedup
    r"|baseline|ablation|hypothesis|assumption"
    r")\b",
    re.IGNORECASE,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("doc_id", help="docx document id (the token after /docx/ in the URL)")
    ap.add_argument("--max", type=int, default=500, help="hard cap on returned candidates")
    args = ap.parse_args()

    blocks = _fetch_blocks(args.doc_id)
    candidates = []
    for block in blocks:
        entry = _classify(block)
        if entry is not None:
            candidates.append(entry)
        if len(candidates) >= args.max:
            break

    json.dump(candidates, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _fetch_blocks(doc_id: str) -> list[dict]:
    """Call lark-cli to walk all blocks of the document."""
    cmd = [
        "lark-cli", "api", "GET",
        f"/open-apis/docx/v1/documents/{doc_id}/blocks",
        "--page-all",
        "--page-size", "500",
        "--format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(f"lark-cli failed: {proc.stderr}\n")
        sys.exit(2)
    out = proc.stdout
    brace = out.find("{")
    if brace < 0:
        sys.stderr.write(f"no JSON in lark-cli output:\n{out}\n")
        sys.exit(2)
    payload = json.loads(out[brace:])
    # The /blocks endpoint returns {"data": {"items": [...], "page_token": ...}}
    # With --page-all lark-cli flattens pages into a single items array.
    data = payload.get("data") or payload
    items = data.get("items") or data.get("blocks") or []
    return items


def _classify(block: dict) -> dict | None:
    """Decide whether a block is worth commenting on, return preview entry."""
    btype = block.get("block_type")
    label = _BLOCK_TYPE.get(btype, f"type{btype}")
    bid = block.get("block_id")
    if not bid:
        return None

    # Skip the page (root) block — comments on root behave like global comments,
    # which we'd rather create explicitly.
    if btype == 1:
        return None

    # Image blocks (block_type=27) reject anchored comments via create_v2
    # (returns API error 1069301). Skip them — comments about figures should
    # be anchored to the surrounding text block instead.
    if btype == 27:
        return None

    text = _extract_text(block)
    if not text:
        return None

    # Skip pure citation noise like "[1] Smith et al..." references list entries
    if _looks_like_reference(text):
        return None

    # Headings always count
    if btype in (3, 4, 5, 6, 7, 8, 9, 10, 11):
        return {"block_id": bid, "type": label, "text": _truncate(text, 200)}

    # Equation: text blocks containing inline equation elements
    if _has_equation(block):
        return {"block_id": bid, "type": "equation", "text": _truncate(text, 400)}

    # Plain paragraph: only keep if it looks claim-bearing OR is reasonably long
    if btype == 2:
        if _CLAIM_HINTS.search(text) or len(text) >= 200:
            return {"block_id": bid, "type": "text", "text": _truncate(text, 400)}
        return None

    # Code, quote, callout, table — keep with preview, LLM decides
    if btype in (14, 15, 19, 31, 34):
        return {"block_id": bid, "type": label, "text": _truncate(text, 300)}

    return None


def _extract_text(block: dict) -> str:
    """Pull a flat text preview from any block that carries text elements."""
    parts: list[str] = []
    for key in ("text", "heading1", "heading2", "heading3", "heading4",
                "heading5", "heading6", "heading7", "heading8", "heading9",
                "bullet", "ordered", "code", "quote", "callout", "todo"):
        node = block.get(key)
        if isinstance(node, dict):
            for el in node.get("elements") or []:
                tr = el.get("text_run")
                if tr and tr.get("content"):
                    parts.append(tr["content"])
                eq = el.get("equation")
                if eq and eq.get("content"):
                    parts.append(eq["content"])
    return "".join(parts).strip()


def _has_equation(block: dict) -> bool:
    for key in ("text",):
        node = block.get(key)
        if isinstance(node, dict):
            for el in node.get("elements") or []:
                if el.get("equation"):
                    return True
    return False


def _looks_like_reference(text: str) -> bool:
    # Lines that start with "[N]" or "N." followed by author-year-style content
    return bool(re.match(r"^\s*\[\d+\]\s+\w", text)) or bool(
        re.match(r"^\s*\d+\.\s+[A-Z][a-zA-Z]+,?\s+[A-Z]\.", text)
    )


def _truncate(text: str, n: int) -> str:
    text = " ".join(text.split())  # collapse whitespace
    return text if len(text) <= n else text[: n - 1] + "…"


if __name__ == "__main__":
    sys.exit(main())
