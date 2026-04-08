#!/usr/bin/env python3
"""Delete all AI-authored comments from a Lark docx document.

Identifies AI comments by the ``🤖 [AI`` prefix in the reply text, so it
won't touch human-authored comments. Useful for re-running the annotate
flow with a different prompt or model.

Implementation note: Lark's API has no top-level "delete comment" endpoint.
The only way to remove a comment is to delete every reply inside it
(``file.comment.replys delete``). When the last reply is removed, the
parent comment also disappears from the document. We rely on this behavior.

Usage::

    clear_ai_comments.py <doc_id>
    clear_ai_comments.py <doc_id> --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

AI_PREFIX = "🤖 [AI"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("doc_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    comments = _list_comments(args.doc_id)
    targets = [c for c in comments if _is_ai(c)]
    sys.stderr.write(f"found {len(targets)} AI comments out of {len(comments)} total\n")

    deleted = 0
    failed = 0
    for c in targets:
        cid = c.get("comment_id")
        replies = (c.get("reply_list") or {}).get("replies") or []
        ai_replies = [r for r in replies if _reply_is_ai(r)]
        preview = _preview(c)
        if args.dry_run:
            sys.stderr.write(
                f"would delete {len(ai_replies)} AI reply(ies) of {cid}: {preview}\n"
            )
            continue
        all_ok = True
        for r in ai_replies:
            ok = _delete_reply(args.doc_id, cid, r["reply_id"])
            if not ok:
                all_ok = False
                failed += 1
        if all_ok:
            deleted += 1
            sys.stderr.write(f"deleted {cid}: {preview}\n")

    if not args.dry_run:
        sys.stderr.write(f"summary: {deleted} comments removed, {failed} reply deletes failed\n")
    return 0


def _list_comments(doc_id: str) -> list[dict]:
    cmd = [
        "lark-cli", "drive", "file.comments", "list",
        "--as", "user",
        "--params", json.dumps({"file_token": doc_id, "file_type": "docx"}),
        "--page-all",
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
    data = payload.get("data") or payload
    return data.get("items") or []


def _is_ai(comment: dict) -> bool:
    for reply in (comment.get("reply_list") or {}).get("replies", []) or []:
        if _reply_is_ai(reply):
            return True
    return False


def _reply_is_ai(reply: dict) -> bool:
    for el in (reply.get("content") or {}).get("elements", []) or []:
        text = (el.get("text_run") or {}).get("text", "")
        if AI_PREFIX in text:
            return True
    return False


def _preview(comment: dict) -> str:
    for reply in (comment.get("reply_list") or {}).get("replies", []) or []:
        for el in (reply.get("content") or {}).get("elements", []) or []:
            text = (el.get("text_run") or {}).get("text", "")
            if text:
                return text[:80]
    return ""


def _delete_reply(doc_id: str, comment_id: str, reply_id: str) -> bool:
    """Delete a single reply. Returns True on success.

    When the only remaining reply of a comment is deleted, the parent
    comment also disappears from the document — this is how we achieve
    "delete the comment" semantics.
    """
    cmd = [
        "lark-cli", "drive", "file.comment.replys", "delete",
        "--as", "user",
        "--params", json.dumps({
            "file_token": doc_id,
            "comment_id": comment_id,
            "reply_id": reply_id,
            "file_type": "docx",
        }),
        "--format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(
            f"delete reply {reply_id} failed: {proc.stderr.strip()[:200]}\n"
        )
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
