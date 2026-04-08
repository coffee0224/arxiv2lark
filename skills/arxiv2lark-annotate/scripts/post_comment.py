#!/usr/bin/env python3
"""Post a single AI comment to a Lark docx block, idempotently.

Usage::

    post_comment.py <doc_id> <block_id> <category> <content>
    # or read content from stdin:
    echo "your comment text" | post_comment.py <doc_id> <block_id> <category> -

``category`` is a short tag like ``导读``, ``批判``, ``符号``, ``图表``, ``公式``,
``关联``. It becomes part of the visual prefix.

The comment is automatically prefixed with ``🤖 [AI <category>] `` so a
human reader can immediately distinguish AI annotations from their own.

State is recorded in ``comments.json`` next to the script's invocation
directory (or under ``$ARXIV2LARK_OUT_DIR`` if set), keyed by
``(doc_id, block_id, content_hash)``. Re-running with identical inputs
is a no-op.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PREFIX_TEMPLATE = "🤖 [AI {category}] {content}"
MAX_LEN = 1000  # Lark text element hard limit

# Lark's comment API rejects ASCII '<' and '>' in reply_elements.text
# (returns API error 1069302). Replace with full-width / math equivalents.
_FORBIDDEN_CHARS = str.maketrans({"<": "＜", ">": "＞"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("doc_id")
    ap.add_argument("block_id")
    ap.add_argument("category")
    ap.add_argument("content", help='comment text, or "-" to read from stdin')
    ap.add_argument(
        "--state",
        default=None,
        help="path to comments.json state file (default: $ARXIV2LARK_OUT_DIR/comments.json or ./comments.json)",
    )
    args = ap.parse_args()

    raw = sys.stdin.read() if args.content == "-" else args.content
    raw = raw.strip()
    if not raw:
        sys.stderr.write("empty comment content\n")
        return 2

    body = PREFIX_TEMPLATE.format(category=args.category.strip(), content=raw)
    body = body.translate(_FORBIDDEN_CHARS)
    if len(body) > MAX_LEN:
        body = body[: MAX_LEN - 1] + "…"

    state_path = _resolve_state_path(args.state)
    state = _load_state(state_path)

    key = _make_key(args.doc_id, args.block_id, body)
    if key in state:
        sys.stderr.write(f"skip (already posted): {state[key]['comment_id']}\n")
        print(state[key]["comment_id"])
        return 0

    comment_id = _post(args.doc_id, args.block_id, body)
    state[key] = {
        "doc_id": args.doc_id,
        "block_id": args.block_id,
        "category": args.category,
        "comment_id": comment_id,
    }
    _save_state(state_path, state)
    print(comment_id)
    return 0


def _resolve_state_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("ARXIV2LARK_OUT_DIR")
    if env:
        return Path(env) / "comments.json"
    return Path.cwd() / "comments.json"


def _load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_key(doc_id: str, block_id: str, body: str) -> str:
    h = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}:{block_id}:{h}"


def _post(doc_id: str, block_id: str, body: str) -> str:
    payload = {
        "file_type": "docx",
        "reply_elements": [{"type": "text", "text": body}],
        "anchor": {"block_id": block_id},
    }
    cmd = [
        "lark-cli", "drive", "file.comments", "create_v2",
        "--as", "user",
        "--params", json.dumps({"file_token": doc_id}),
        "--data", json.dumps(payload, ensure_ascii=False),
        "--format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(
            f"lark-cli failed (exit {proc.returncode}):\n{proc.stderr}\n"
        )
        sys.exit(2)
    out = proc.stdout
    brace = out.find("{")
    if brace < 0:
        sys.stderr.write(f"no JSON in lark-cli output:\n{out}\n")
        sys.exit(2)
    payload = json.loads(out[brace:])
    data = payload.get("data") or payload
    cid = data.get("comment_id")
    if not cid:
        sys.stderr.write(f"no comment_id in response:\n{json.dumps(payload)}\n")
        sys.exit(2)
    return cid


if __name__ == "__main__":
    sys.exit(main())
