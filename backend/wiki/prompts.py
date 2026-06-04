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
"""
from __future__ import annotations

from typing import Any


# ── Analysis step ────────────────────────────────────────────────────


ANALYSIS_SYSTEM = """You are an expert research analyst. Read the source document
and produce a structured analysis. Reason internally — output only the concise,
structured final analysis. No preamble, no chain-of-thought markers.

LANGUAGE: Write all analysis prose in Chinese (简体中文).

Your analysis MUST cover ALL of these sections:

## 1. Key Entities
List people, organizations, products, datasets, tools. For each: name, type, role in this source.

## 2. Key Concepts
List theories, methods, techniques, phenomena. For each: name + brief definition, significance.

## 3. Main Arguments & Findings
Core claims/results. What's new, surprising, or important?

## 4. Connections to Existing Wiki
Which existing pages relate? Does it strengthen, challenge, or extend?

## 5. Contradictions & Tensions
Any conflicts with existing wiki? Internal tensions or caveats?

## 6. Wiki Structure Recommendations
- What new pages to create (type, slug, title, why)?
- Which existing pages to update (id, what to add)?
- Suggested tags and wikilinks between pages

After the free-form analysis, append a JSON dispatch plan so the
system knows exactly which pages to create/update. The plan must be the
LAST thing in your output:

---DISPATCH PLAN---
```json
{
  "summary": "<one sentence>",
  "pages": [
    {
      "page_type": "entity|concept|source|query",
      "slug": "kebab-case-ascii",
      "title": "Human Title in Chinese",
      "rationale": "Why this page should exist",
      "tags": ["t1"],
      "aliases": ["alt"]
    }
  ],
  "wikilinks": [
    {"src": "type:slug", "dst": "type:slug", "relation": "mentions"}
  ]
}
```
Every plan MUST include exactly one source page.
The source page MUST contain the FULL original text, word-for-word, never summarized.
Prefer fewer, higher-quality pages over many shallow stubs."""



ANALYSIS_USER_TEMPLATE = """Wiki purpose:
{purpose_excerpt}

Existing wiki index:
{index_excerpt}

Source metadata:
- id:    {source_id}
- title: {source_title}
- type:  {source_type}
- url:   {source_url}

Full source content:
\"\"\"
{source_text}
\"\"\"

Produce your structured analysis now."""


# ── Generation step ──────────────────────────────────────────────────


GENERATION_SYSTEM = """You are the wiki maintainer writing ONE wiki page.

LANGUAGE: ALL output MUST be written in Chinese (简体中文) — the title,
headings, body text, and ALL prose content. Only YAML frontmatter keys
and [[type:slug]] wikilinks keep ASCII format.

Output rules:
- Output ONLY the page body in markdown, starting with the YAML
  frontmatter block. No explanation, no surrounding fences, nothing
  else. The system writes your output verbatim to disk.
- Frontmatter is REQUIRED with exactly these keys (use ISO-8601 for
  timestamps; the system fills created_at/updated_at — leave the
  literal placeholder values you receive):
  ---
  title: "<title>"
  type: "<page_type>"
  sources: [<list of source ids>]
  tags: [<list of tags>]
  aliases: [<list of aliases>]
  created_at: "<placeholder>"
  updated_at: "<placeholder>"
  ---
- The first body line after the frontmatter MUST be a level-1
  heading: ``# <Title>``.
- Cross-references use ``[[type:slug]]`` syntax. Use them generously
  for any wiki page you mention.
- Every claim derived from a source must end with a parenthetical
  citation referencing a source id from the frontmatter:
  ``...the persistent wiki keeps getting richer (s-001).``
  Never invent source ids.

When updating an existing page (``EXISTING PAGE`` is non-empty):
- Preserve facts that are still correct — don't rewrite for style.
- If new information CONTRADICTS an existing claim, add a block:
  > ⚠ Contradicts: <one-line summary of the conflict> ([[type:slug]])
  Keep both versions visible until a human resolves it.
- If new information SUPERSEDES an old claim, append:
  > 🕒 Superseded by: <one-line summary> (<source id>)
  Don't delete the old claim — the history matters.

CRITICAL: For source-type pages: include the COMPLETE original text VERBATIM.
Do NOT summarize. Do NOT reorganize. Do NOT write an overview.
Copy the full source text into the page body word-for-word.
The source page IS the original document — it must contain every single word.
For entity/concept pages: include ALL relevant facts, never omit or abbreviate.

IMPORTANT: After generating pages, also produce:
1. An updated wiki/overview.md — a 2-5 paragraph synthesis of what the ENTIRE wiki covers
2. A log entry for wiki/log.md in format:
   ## [{date}] ingest | {source_title}
   Created: {pages} | Updated: {pages}
   Summary: {one sentence}
"""


GENERATION_USER_TEMPLATE = """Page to write:
- id:        {page_id}
- type:      {page_type}
- slug:      {slug}
- title:     {title}
- tags:      {tags}
- aliases:   {aliases}
- sources:   {sources}
- rationale: {rationale}

Wiki purpose (what matters in this KB):
\"\"\"
{purpose_excerpt}
\"\"\"

Wiki routing rules:
\"\"\"
{schema_excerpt}
\"\"\"

Current wiki index (link to existing pages):
\"\"\"
{index_excerpt}
\"\"\"

Current wiki overview (global synthesis):
\"\"\"
{overview_text}
\"\"\"

Ingest analysis (from Step 1):
\"\"\"
{analysis_text}
\"\"\"

Full source content:
\"\"\"
{source_text}
\"\"\"

EXISTING PAGE (empty if new):
\"\"\"
{existing_page}
\"\"\"

Write the full markdown page now (frontmatter + body). Use Chinese. Include [[wikilinks]] to related pages. Cite sources with (source-id) notation."""


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
