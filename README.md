# arxiv2md / arxiv2lark

<div align="center">
  <img src="assets/image.png" alt="arxiv2md" width="400">

  **arXiv papers → clean Markdown, or fully-rendered Lark documents with AI commentary.**

  [Live Demo](https://arxiv2md.org) · [PyPI](https://pypi.org/project/arxiv2markdown/) · [Report Bug](https://github.com/timf34/arxiv2md/issues)
</div>

---

## Why?

[gitingest](https://gitingest.com) but for arXiv papers.

**The trick:** append `2md` to any arXiv URL — `https://arxiv.org/abs/2501.11120v1` → `https://arxiv2md.org/abs/2501.11120v1`.

Instead of OCR'ing PDFs, arxiv2md parses the structured HTML arXiv provides for newer papers: clean section boundaries, math (MathML → LaTeX), reliable tables, fast.

This repo ships three things:

| Tool | Purpose |
|------|---------|
| **`arxiv2md`** | arXiv → clean Markdown (CLI / REST / web / library) |
| **`arxiv2lark`** | arXiv → Lark docx with images downloaded and inserted at original positions |
| **`arxiv2lark-annotate`** skill | LLM-driven批注 comments on an imported Lark doc, anchored to specific blocks |

---

## For Users

### Web app — quickest path
Visit [arxiv2md.org](https://arxiv2md.org), paste any arXiv URL, click sections to include/exclude, export Markdown.

### CLI — Markdown
```bash
pip install arxiv2markdown

# basic
arxiv2md 2501.11120v1 -o paper.md

# section filtering / cleanup
arxiv2md 2501.11120v1 --section-filter-mode include \
    --sections "Abstract,Introduction" -o -
arxiv2md 2501.11120v1 --remove-refs --remove-toc --frontmatter -o paper.md

# Lark-flavored markdown (display math centered, image tags emitted)
arxiv2md 2501.11120v1 --lark -o /tmp/paper_lark/
```

### CLI — end-to-end Lark import
`arxiv2lark` chains ingestion → image download → docx creation, putting figures back at their original positions inside the doc:

```bash
# install lark-cli first and run `lark-cli auth login` once
arxiv2lark 2501.11120v1 \
    --folder-token <your-drive-folder-token> \
    --remove-inline-citations
```

What you get:
- A new Lark docx under the chosen Drive folder, titled with the paper's actual title
- All figures downloaded locally, then inserted at the exact anchor where they appear in the markdown (not appended at the end)
- Display math centered (via `<equation>` paragraph + `align="center"`)
- Output directory `/tmp/<arxiv_id>_<timestamp>/` containing `digest.md`, `images.json`, and `fig-N.*` files for inspection / re-import

Useful flags: `--title` overrides the doc title, `--output/-o` sets a custom output dir, `--remove-refs --remove-toc` strip noise, `--remove-inline-citations` cleans up `(Smith et al., 2023)` markers.

### Python library
```python
from arxiv2md import ingest_paper
result = await ingest_paper("2501.11120v1")
print(result.content)
```

---

## For Agents

The repo offers two agent integration paths: a zero-setup REST API for ingestion, and a Claude Code skill for the full "import-and-annotate" workflow on Lark.

### REST API — drop-in for any LLM workflow
No MCP server, no OAuth, no SDK. Two GET endpoints, 30 req/min/IP rate limit:

```bash
# JSON response (with metadata)
curl "https://arxiv2md.org/api/json?url=2312.00752"

# Raw markdown
curl "https://arxiv2md.org/api/markdown?url=2312.00752"
```

| Param | Default | Description |
|-------|---------|-------------|
| `url` | required | arXiv URL or ID |
| `remove_refs` | `true` | Remove references |
| `remove_toc` | `true` | Remove table of contents |
| `remove_citations` | `true` | Remove inline citations |
| `frontmatter` | `false` | Prepend YAML frontmatter (`/api/markdown` only) |

Feed the output straight into the agent's context. Section filtering keeps token budgets in check.

### Claude Code skill — `arxiv2lark-annotate`

For agents that already manage Lark documents (e.g. Claude Code with `lark-cli` configured), this repo ships a skill at [`skills/arxiv2lark-annotate/`](skills/arxiv2lark-annotate/) that lets the agent post AI批注 comments onto an already-imported paper. It is purely additive — the markdown source is never modified — and all comments carry a `🤖 [AI ...]` prefix so a human can distinguish and bulk-clear them at any time.

Trigger phrases the skill recognises (Chinese & English):
- "给这篇论文加 AI 评论 / AI 批注 / AI 帮我读"
- "annotate this paper", "add AI comments to my Lark doc"

Workflow the agent follows:
1. **Resolve** the docx token (handles wiki URLs via `lark-cli wiki spaces get_node`)
2. **Walk** the block tree via `scripts/list_commentable_blocks.py`, which keeps headings, equations, and claim-bearing paragraphs while filtering noise (root, references, image blocks that the API rejects, etc.)
3. **Plan** comments per [`references/what-to-comment.md`](skills/arxiv2lark-annotate/references/what-to-comment.md): six categories (导读 / 批判 / 符号 / 公式 / 图表 / 关联), 50-comment hard cap, written for a CS PhD reader
4. **Show plan** to the user for approval
5. **Post** via `scripts/post_comment.py` — idempotent (state in `comments.json`), auto-prefixes `🤖 [AI <类别>]`, auto-translates ASCII `<>` (which the Lark API rejects) to fullwidth `＜＞`
6. **Clean up** later via `scripts/clear_ai_comments.py`, which removes any `🤖`-prefixed comment via reply-delete

Setup:
```bash
# one-time
npm i -g @larksuiteoapi/lark-cli   # or your distribution's package
lark-cli auth login                # personal-identity scope is sufficient

# inside Claude Code (the skill is auto-discovered if this repo is in your workspace)
# just ask: "用 arxiv2lark 把 2501.11120 导入飞书 Papers 文件夹，然后加 AI 批注"
```

Identity & visibility:
- Comments are posted as **personal identity** (`--as user`), so they show up under your own avatar
- The `🤖 [AI ...]` prefix is the only AI-vs-human distinguisher; never bypass `post_comment.py`, or the prefix is lost and `clear_ai_comments.py` won't find them later
- Required scopes: `docs:document.comment:create` plus `docs:document` read

See [`skills/arxiv2lark-annotate/SKILL.md`](skills/arxiv2lark-annotate/SKILL.md) for the full agent contract, known API quirks, and re-run / cleanup recipes.

---

## Development

```bash
pip install -e .[server,dev]
uvicorn server.main:app --reload --app-dir src
pytest tests
```

## Contributing

PRs welcome — fork, branch, add tests, open a PR.

## License

MIT
