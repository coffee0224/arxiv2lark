---
name: arxiv2lark-annotate
description: 在已导入飞书的 arxiv 论文文档上，由 AI 以个人身份发布有针对性的批注式评论。当用户希望"让 AI 帮我读论文 / 给已导入的 lark 论文加 AI 评论 / 标注论文重点"时使用。
---

# arxiv2lark-annotate

为 `arxiv2lark` 已导入的飞书 docx 论文添加 AI 批注式评论。
评论以**个人身份**（user token）发布，**不修改正文**，
所有 AI 评论都带统一前缀以便区分和清理。

## 何时使用

触发场景：
- 用户已经用 `arxiv2lark` 把一篇 arxiv 论文导入到飞书，要求"加 AI 评论"、"AI 批注"、"AI 帮我读"
- 用户给出一个 docx URL/token，希望对其中的论文内容做评论式辅助阅读
- 用户要求"清掉 AI 评论"、"重新评论一遍" → 用 `clear_ai_comments.py` 然后重跑本流程

不适用：
- 普通飞书文档（非论文）—— 评论方法论是为论文设计的
- Wiki 链接 —— 需先用 `lark-cli wiki spaces get_node` 解析出真实 docx token
- 需要修改正文 → 用 lark-doc skill 而不是本 skill

## 前置条件

1. **认证**：`lark-cli auth login`（user token），见 [`../lark-shared/SKILL.md`](../lark-shared/SKILL.md)
2. **scope**：`docs:document.comment:create`、`docs:document` 读取 scope。如果 lark-cli 报权限不足，按 lark-shared 的指引补 scope 后重新登录
3. **doc_id**：必须是 docx 类型的真实 file_token。如果用户给的是 wiki URL，先解析

## 工作流（必须按顺序）

### Step 1 — 拿到 doc_id
- URL `https://*.feishu.cn/docx/<TOKEN>` → `TOKEN` 直接是 doc_id
- URL `https://*.feishu.cn/wiki/<TOKEN>` → 用 `lark-cli wiki spaces get_node --params '{"token":"TOKEN"}'`，取返回的 `node.obj_token`，并确认 `node.obj_type == "docx"`

### Step 2 — 读取候选块
```bash
python skills/arxiv2lark-annotate/scripts/list_commentable_blocks.py <doc_id> > /tmp/blocks.json
```

输出一个 JSON 数组，每项是 `{block_id, type, text}`。type 可能是
`heading2`、`image`、`equation`、`text` 等。脚本已经过滤掉了根块、
空段、参考文献条目等噪声。

**通读这个 JSON**，对每一项做判断：是否值得评论？属于哪一类评论
（导读 / 批判 / 符号 / 图表 / 公式 / 关联）？写什么内容？

### Step 3 — 规划评论（关键步骤）
基于 [`references/what-to-comment.md`](references/what-to-comment.md) 的方法论：

**硬约束**：
- **总评论数 ≤ 50**（用户明确要求的硬上限）
- 单节（两个 heading 之间的所有块）评论数 ≤ 6
- 每条评论 50-200 字，绝不超过 300 字
- 优先级：批判性 > 公式/图表 > 导读 > 符号 > 关联 > 个性化

**禁止**：
- 复述原文
- 每段都评论
- 泛泛赞美

输出一个本地草稿 JSON 列表 `/tmp/plan.json`：
```json
[
  {"block_id": "...", "category": "导读", "content": "本节将 X 形式化为 Y 优化问题..."},
  {"block_id": "...", "category": "批判", "content": "baseline 未包含 2024 年的 ZeRO-Inf..."},
  ...
]
```

把草稿交给用户**预览**（特别是首次跑），用户确认后再 Step 4。

### Step 4 — 写回评论
对 plan.json 中的每条记录，调用：
```bash
python skills/arxiv2lark-annotate/scripts/post_comment.py \
    <doc_id> <block_id> <category> "<content>"
```

或批量：
```bash
ARXIV2LARK_OUT_DIR=/tmp/<arxiv_id>_<ts> python -c "
import json, subprocess, sys
plan = json.load(open('/tmp/plan.json'))
for c in plan:
    subprocess.run([
        'python', 'skills/arxiv2lark-annotate/scripts/post_comment.py',
        '$DOC_ID', c['block_id'], c['category'], c['content']
    ], check=True)
"
```

每条 post 会：
- 自动添加 `🤖 [AI <category>] ` 前缀
- 写入 `comments.json` 状态文件，下次重跑时同 hash 直接 skip
- 失败立即退出，不会半途留下状态

### Step 5 — 汇报
告诉用户：
- 实际写入了多少条评论（按类别统计）
- 文档 URL（可点击预览效果）
- 如何清理：`python skills/arxiv2lark-annotate/scripts/clear_ai_comments.py <doc_id>`

## 重新评论的流程
1. `clear_ai_comments.py <doc_id>` 删除所有 `🤖 [AI` 前缀的评论
2. 删除本地 `comments.json`（否则 idempotency 会让 post_comment 全部 skip）
3. 重新执行 Step 2-4

## 评论身份与可见性

- **身份**：`--as user`（个人身份），评论会显示为你本人的头像和名字
- **区分**：所有 AI 评论的 `🤖 [AI ...]` 前缀是唯一的人/AI 区分标志
  —— 千万不要绕过 `post_comment.py` 直接调 lark-cli，否则前缀会丢失，
  后续 `clear_ai_comments.py` 也无法清理
- **scope**：评论是 user token 操作，需要个人账号有评论权限。
  如果某文档你不是成员/没有评论权，会收到 403，按提示申请权限后重试

## 已知 API 约束（脚本已自动规避，但 LLM 在 plan 阶段也要知道）

1. **图片块不接受评论**：`block_type=27` 调用 `create_v2` 会返回 `1069301`。
   `list_commentable_blocks.py` 已在过滤阶段直接丢弃图片块。要评论图，
   把锚点放到**引入图的上一段或下一段文字块**上，评论一样会显示在图旁。

2. **ASCII `<` `>` 被服务端拒绝**：即使 JSON 规范转义，含 `<30ms` / `L>3`
   的 reply_elements 仍触发 `1069302`。`post_comment.py` 在写入前会自动把
   `<` 替换为 `＜`、`>` 替换为 `＞`。LLM 在起草 plan 时无须自己处理，
   但要知道：如果你想精确表达 `<`、`>`，最终在文档里看到的会是全角形式。

## 脚本清单

| 脚本 | 作用 |
|------|------|
| `scripts/list_commentable_blocks.py` | 拉取 docx 所有 block，过滤为评论候选 |
| `scripts/post_comment.py` | 发布单条评论（自动加前缀 + 幂等） |
| `scripts/clear_ai_comments.py` | 批量删除所有 🤖 前缀的 AI 评论 |

## 参考

- [`references/what-to-comment.md`](references/what-to-comment.md) — 6 类评论方法论 + 风格指南 + 反面清单
- 上游 pipeline：[`../../src/arxiv2md/arxiv2lark_cli.py`](../../src/arxiv2md/arxiv2lark_cli.py)
- 飞书评论 API: `drive file.comments create_v2` —— `lark-cli schema drive.file.comments.create_v2` 查看完整定义
