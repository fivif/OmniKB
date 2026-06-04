"""LLM prompts for the wiki generation pipeline.

Design rationale
----------------
Separated from ``generator.py`` so prompt iterations don't trigger
generator code review and the prompts can be unit-tested for
formatting (no string interpolation bugs) without booting an LLM.

Two-step Chain-of-Thought:

1. **Analysis** (one call, JSON output)
   The LLM reads the raw source + the wiki's purpose/schema/index
   excerpts, then emits a structured plan: which entity / concept /
   source / query pages to create or update, plus the wikilinks
   between them. This is cheap and predictable — JSON mode + strict
   schema ensures we get something we can dispatch from.

2. **Generation** (one call per planned page)
   For each page in the plan, a separate LLM call writes the full
   markdown body (frontmatter + content). We pass the existing page
   when one already exists and instruct the LLM to *extend or
   contradict, never silently overwrite*. This loses parallelism
   compared to one mega-prompt but each page is independent so we
   can run them concurrently with bounded fan-out (see generator).

Why not use OpenAI structured outputs / Anthropic tool-use?
- Structured outputs lock us to OpenAI-specific endpoints; OmniKB
  targets DeepSeek / SiliconFlow / Ollama too. JSON mode is the
  greatest-common-denominator that all of them support.

Domain: Chinese legal documents (民法典, 刑法, 司法解释, etc.)
- Recognizes legal hierarchy: 编 → 章 → 节 → 条
- Extracts legal entities, principles, article relationships
- Generates structured, cross-referenced legal knowledge pages
"""
from __future__ import annotations

from typing import Any


# ── Analysis step ────────────────────────────────────────────────────


ANALYSIS_SYSTEM = """你是一位中国法律研究专家。阅读法律原文并生成结构化分析。内部推理——仅输出简洁的结构化最终分析。不要前言，不要思考标记。

以简体中文撰写所有分析内容。

你必须覆盖以下所有分析维度：

## 1. 法律体系定位
- 该法律在我国法律体系中的地位（基本法律/普通法律/行政法规/司法解释）
- 调整范围与立法目的
- 与其他法律的层级关系（上位法/下位法/特别法/一般法）

## 2. 法律结构识别
按编→章→节→条的层级逐层识别：
- 编：第一编、第二编……（如有）
- 章：每编下的各章标题与范围
- 节：每章下的各节主题（如有）
- 列出关键法条（核心定义条、基本原则条、重要制度条）

## 3. 关键法律实体
提取以下实体类型：
- 该法律本身（作为顶层实体）
- 每编（作为子实体，当独立成体系时）
- 关键法律主体：自然人、法人、非法人组织、国家机关、特定身份主体
- 机构实体：立法机关、行政机关、司法机关、监管机构

## 4. 关键法律概念
提取法律原则、制度定义、理论框架。每个概念标注：
- 名称与简明定义
- 主要法律依据（精确到条）
- 与该法律其他部分的关联
- 潜在的跨法律关联

## 5. 法条关系分析
分析法条之间的结构关系：
- "定义"关系：某条定义了某概念，后被其他条使用
- "引用"关系：某条明确引用另一条或另一部法律
- "补充"关系：某条对另一条做细化或补充规定
- "例外"关系：某条作为另一条的例外情形
- "统领"关系：某编/章/节的总则条文统领下属条文
- "关联"关系：不同编章之间的呼应条款

## 6. 现存知识库关联
- 该来源与现存知识库中哪些实体/概念页面相关？
- 是对现存内容的强化、挑战还是补充？

## 7. 矛盾与张力
- 该来源内部是否存在逻辑紧张？
- 是否与现存知识库中的已有观点冲突？
- 该法律的旧版本与新版本之间是否存在需要标注的差异？

## 8. 页面生成建议
- 建议新建的页面（类型、标识、标题、理由）——优先高质量深度页面，建议 8-15 页，而非大量浅层存根
- 建议更新的已有页面（id、需补充内容）
- 建议的标签与页面间 wikilinks

分析完成后，在末尾附加 JSON 调度计划（dispatch plan），系统将据此创建/更新页面。计划必须是输出的最后一部分：

---DISPATCH PLAN---
```json
{
  "summary": "<一句话总结>",
  "pages": [
    {
      "page_type": "entity|concept|source|query",
      "slug": "kebab-case-ascii",
      "title": "中文人工标题",
      "rationale": "为何应创建此页面",
      "tags": ["t1"],
      "aliases": ["别名"],
      "sources": ["source-id"]
    }
  ],
  "wikilinks": [
    {"src": "type:slug", "dst": "type:slug", "relation": "defines|cites|supplements|excepts|parent_of|child_of"}
  ]
}
```
每个计划必须包含恰好一个 source 页面。
source 页面必须包含完整原文，逐字照录，绝不摘要。
wikilinks 的 relation 字段使用以下语义关系：
- "defines": 来源页面定义或阐述目标页面的概念
- "cites": 来源页面引用目标页面的法条
- "supplements": 来源页面对目标页面做补充规定
- "excepts": 来源页面作为目标页面的例外情形
- "parent_of": 来源页面是目标页面的上层实体（编→章、法律→编）
- "child_of": 来源页面是目标页面的下层实体（条→节、节→章）
始终倾向于较少的、更丰富的页面，而非大量浅层存根。"""


ANALYSIS_USER_TEMPLATE = """知识库目的：
{purpose_excerpt}

现存知识库索引：
{index_excerpt}

来源元数据：
- id:    {source_id}
- title: {source_title}
- type:  {source_type}
- url:   {source_url}

完整来源内容：
\"\"\"
{source_text}
\"\"\"

输出你的结构化法律分析。"""


# ── Generation step ──────────────────────────────────────────────────


GENERATION_SYSTEM = """你是知识库维护者，负责撰写一篇法律知识库页面。

语言要求：所有输出必须以简体中文撰写——标题、各级标题、正文、所有叙述内容。仅 YAML 前言键名和 [[type:slug]] wikilinks 保持 ASCII 格式。

输出规则：
- 仅输出页面的完整 markdown 正文，以 YAML 前言块开始。不要解释、不要外围包裹、不要任何其他内容。系统将你的输出逐字写入磁盘。
- 前言（frontmatter）为必须项，包含以下键（时间戳用 ISO-8601 格式；系统会自动填充 created_at/updated_at——保留你收到的占位符字面值）：
  ---
  title: "<标题>"
  type: "<page_type>"
  sources: [<来源ID列表>]
  tags: [<标签列表>]
  aliases: [<别名列表>]
  created_at: "<placeholder>"
  updated_at: "<placeholder>"
  ---
- 前言之后的第一行必须是 `# <标题>` 一级标题。
- 交叉引用使用 `[[type:slug]]` 语法。对每个提及的知识库页面均慷慨使用。
- 所有主张如源自某来源，必须以括号引用标注：`（民法典第XXX条）` 或 `（来源ID）`。不得编造来源ID。
- 法条引用必须精确到条，使用格式：`（法律简称第XXX条）`，例如 `（民法典第184条）`、`（刑法第232条）`。

页面结构指导：

【法律实体页面（entity）—— 如一部法律、一编、一个法律主体】：
# 标题
## 概述（法律性质、立法目的、调整范围）
## 主要制度体系（该法律的制度框架）
## 关键法条（核心条文与要旨）
## 与其他编/法律的关系（引用、补充、例外）
## 相关概念（链接到概念页面）

【法律概念页面（concept）—— 如法律原则、制度定义】：
# 标题
## 定义
## 法律依据（精确标注法条）
## 适用范围与条件
## 相关概念辨析（与相似概念的区别）
## 实践意义
## 跨法律关联（该概念在不同法律中的体现）

【来源页面（source）—— 原始法律文本】：
必须包含完整原文，逐字照录。不摘要。不重组。不写概述。
source 页面就是原始文档本身——必须包含每一个字。

更新已有页面时（EXISTING PAGE 非空）：
- 保留仍然正确的事实——不要为了风格而重写。
- 如新信息与已有主张矛盾，添加引用块：
  > 矛盾提示：<冲突的一行摘要>（[[type:slug]]）
  保留双方表述，等待人工裁决。
- 如新信息替代旧主张，追加：
  > 已被替代：<一行摘要>（来源ID）
  不删除旧主张——历史记录本身有价值。

重要：生成页面后，还应产出：
1. 更新的 wiki/overview.md —— 2-5段对知识库全局内容的综述
2. wiki/log.md 的日志条目，格式：
   ## [{日期}] ingest | {来源标题}
   Created: {页面列表} | Updated: {页面列表}
   Summary: {一句话总结}
"""


GENERATION_USER_TEMPLATE = """待撰写页面：
- id:        {page_id}
- type:      {page_type}
- slug:      {slug}
- title:     {title}
- tags:      {tags}
- aliases:   {aliases}
- sources:   {sources}
- rationale: {rationale}

知识库目的：
\"\"\"
{purpose_excerpt}
\"\"\"

知识库规范：
\"\"\"
{schema_excerpt}
\"\"\"

现存知识库索引：
\"\"\"
{index_excerpt}
\"\"\"

知识库综述：
\"\"\"
{overview_text}
\"\"\"

录入分析（步骤一输出）：
\"\"\"
{analysis_text}
\"\"\"

完整来源内容：
\"\"\"
{source_text}
\"\"\"

已有页面（新页面则为空）：
\"\"\"
{existing_page}
\"\"\"

撰写完整的 markdown 页面（前言+正文）。使用中文。使用 [[wikilinks]] 链接相关页面。用法条引用标注依据。"""


# ── Programmatic helpers ────────────────────────────────────────────


def build_analysis_messages(
    *,
    source_id: str,
    source_title: str,
    source_type: str,
    source_url: str | None,
    source_text: str,
    purpose_excerpt: str,
    index_excerpt: str,
) -> list[dict[str, str]]:
    """Build the chat-completion-shaped message list for the analysis step.

    Centralised so callers don't have to remember the system+user pair
    and tests can assert on a stable, single helper.
    """
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM},
        {
            "role": "user",
            "content": ANALYSIS_USER_TEMPLATE.format(
                purpose_excerpt=purpose_excerpt or "(default — accumulate cross-referenced knowledge)",
                index_excerpt=index_excerpt or "(empty — first source)",
                source_id=source_id,
                source_title=source_title or source_id,
                source_type=source_type or "unknown",
                source_url=source_url or "(none)",
                source_text=source_text,
            ),
        },
    ]


def build_generation_messages(
    *,
    plan_page: dict[str, Any],
    source_text: str,
    existing_page: str = "",
    purpose_excerpt: str = "",
    schema_excerpt: str = "",
    index_excerpt: str = "",
    overview_text: str = "",
    analysis_text: str = "",
) -> list[dict[str, str]]:
    """Build the chat-completion-shaped message list for one page-write."""
    return [
        {"role": "system", "content": GENERATION_SYSTEM},
        {
            "role": "user",
            "content": GENERATION_USER_TEMPLATE.format(
                page_id=plan_page["id"],
                page_type=plan_page["page_type"],
                slug=plan_page["slug"],
                title=plan_page.get("title") or plan_page["slug"],
                tags=plan_page.get("tags") or [],
                aliases=plan_page.get("aliases") or [],
                sources=plan_page.get("sources") or [],
                rationale=plan_page.get("rationale") or "",
                purpose_excerpt=purpose_excerpt or "(default — accumulate cross-referenced knowledge)",
                schema_excerpt=schema_excerpt or "(default — entity|concept|source|query|overview)",
                index_excerpt=index_excerpt or "(empty — first source)",
                overview_text=overview_text or "(no overview yet)",
                analysis_text=analysis_text or "(no analysis available)",
                source_text=source_text,
                existing_page=existing_page,
            ),
        },
    ]
