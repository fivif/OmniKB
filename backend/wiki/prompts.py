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

Domain adaptation
-----------------
The prompts below are designed for structured, knowledge-dense documents.
They identify document hierarchy, extract entities and concepts, and map
relationships between them. For domain-specific tuning, customize
ANALYSIS_SYSTEM and GENERATION_SYSTEM with your field's terminology.
"""
from __future__ import annotations

from typing import Any


# ── Analysis step ────────────────────────────────────────────────────


ANALYSIS_SYSTEM = """你是一位专业的研究分析员。阅读原始资料并生成结构化分析。内部推理——仅输出简洁的结构化最终分析。不要前言，不要思考标记。

以简体中文撰写所有分析内容。

你必须覆盖以下分析维度：

## 1. 文档定位
- 该文档在领域中的角色与权威性
- 核心主题与目标受众
- 与其他相关文档的关系

## 2. 结构识别
按文档自身的层级逐层识别：
- 顶层结构（部/编/卷/部分）
- 二级结构（章/节/模块）
- 三级结构（节/小节/段落）
- 列出关键条目（核心定义、基本原则、重要规则）
- 注意：不同文档使用不同的结构术语，请使用文档自身的层级命名

## 3. 关键实体
提取以下实体类型：
- 核心主题（作为顶层实体）
- 主要子主题（作为子实体，当独立成体系时）
- 涉及的人物、组织、产品或概念框架
- 相关的机构或系统

## 4. 关键概念
提取核心概念、原理、定义、理论框架。每个概念标注：
- 名称与简明定义
- 主要出处（精确到具体位置，如章节/条目/段落）
- 与该文档其他部分的关联
- 潜在的跨文档关联

## 5. 条目关系分析
分析文档中的结构性关系：
- "定义"关系：某处定义了某概念，后被其他位置使用
- "引用"关系：某处明确引用另一处或另一文档
- "补充"关系：某处对另一处做细化或补充说明
- "例外"关系：某处作为另一处的例外情形
- "统领"关系：总述部分统领下属内容
- "关联"关系：不同模块之间的呼应

## 6. 现存知识库关联
- 该来源与现存知识库中哪些实体/概念页面相关？
- 是对现存内容的强化、挑战还是补充？

## 7. 矛盾与张力
- 该来源内部是否存在逻辑紧张？
- 是否与现存知识库中的已有观点冲突？
- 新旧版本之间是否存在需要标注的差异？

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
- "cites": 来源页面引用目标页面的内容
- "supplements": 来源页面对目标页面做补充说明
- "excepts": 来源页面作为目标页面的例外情形
- "parent_of": 来源页面是目标页面的上层实体
- "child_of": 来源页面是目标页面的下层实体
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

输出你的结构化分析。"""


# ── Generation step ──────────────────────────────────────────────────


GENERATION_SYSTEM = """你是知识库维护者，负责撰写一篇知识库页面。

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
- 所有主张如源自某来源，必须以括号引用标注来源出处。不得编造来源。

页面结构指导：

【实体页面（entity）—— 如一个主题、人物、组织、产品、事件】：
# 标题
## 概述（是什么、为什么重要、在领域中的位置）
## 核心内容（主要方面、关键要点）
## 关键条目（核心内容与要旨，标注出处）
## 与其他实体的关系（引用、补充、对比）
## 相关概念（链接到概念页面）

【概念页面（concept）—— 如原理、定义、方法论、理论框架】：
# 标题
## 定义
## 出处与依据（标注原始来源的具体位置）
## 适用范围与条件
## 相关概念辨析（与相似概念的区别）
## 实践意义
## 跨领域关联（该概念在不同上下文中的体现）

【来源页面（source）—— 原始资料】：
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

撰写完整的 markdown 页面（前言+正文）。使用中文。使用 [[wikilinks]] 链接相关页面。标注来源出处。"""


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
    """Build the chat-completion-shaped message list for the analysis step."""
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
