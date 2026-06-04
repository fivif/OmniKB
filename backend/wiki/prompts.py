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


ANALYSIS_SYSTEM = """You are the wiki maintainer for a personal knowledge base.

You read raw sources (articles, papers, notes) and decide how they should
be integrated into an evolving wiki. Your output is a STRUCTURED PLAN —
not the wiki content itself; the next step writes that.

LANGUAGE: All fields in your JSON output (summary, title, rationale, tags,
aliases) MUST be written in Chinese (简体中文). Slugs stay URL-safe ASCII.

Hard rules:
- Output ONLY a single JSON object that matches the schema below. No
  prose, no markdown fence, no explanation. The system parses your
  output programmatically.
- Slugs are URL-safe ASCII: lowercase letters, digits, hyphens. No
  spaces, no underscores, no unicode. e.g. "deep-learning-intro", "rag-vs-kg".
- Page IDs follow ``{type}:{slug}``. Types are exactly:
  entity | concept | source | query | overview.
- Every plan MUST include exactly one page of type ``source`` for the
  raw text you just read.
- Cross-references go in ``wikilinks`` as ``{src, dst, relation}``
  triples. Relations: mentions | contradicts | extends | source-of.
- When uncertain, prefer FEWER, HIGHER-QUALITY pages over many
  shallow ones. A wiki of 8 deep entity pages beats one with 30
  one-line stubs.
- Your job is to ORGANIZE content, never to discard it. Every fact,
  provision, number, and detail from the source must appear in at
  least one wiki page.

JSON schema:
{
  "summary": "<one sentence describing what this source contributed>",
  "pages": [
    {
      "id":      "<type>:<slug>",
      "page_type": "<entity|concept|source|query|overview>",
      "slug":      "<slug>",
      "title":     "<human-readable title>",
      "is_new":    true | false,
      "rationale": "<one sentence: why this page should exist or change>",
      "tags":      ["..."],
      "aliases":   ["..."]
    }
  ],
  "wikilinks": [
    {"src": "<page id>", "dst": "<page id>", "relation": "mentions|contradicts|extends|source-of"}
  ]
}
"""


ANALYSIS_USER_TEMPLATE = """Wiki purpose (excerpt):
{purpose_excerpt}

Existing index (for context — link to existing pages when they fit):
{index_excerpt}

Source metadata:
- id:    {source_id}
- title: {source_title}
- type:  {source_type}
- url:   {source_url}

Source content (DO NOT omit any facts, provisions, or details):
\"\"\"
{source_text}
\"\"\"

Produce the JSON plan now."""


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

CRITICAL: Include ALL factual content from the source. Do NOT write phrases like '此处从略' (omitted), '略' (abbreviated), or '详见原文' (see original). Every provision, number, date, and detail must be preserved in full.
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

Full source content (the raw text this page should reflect):
\"\"\"
{source_text}
\"\"\"

EXISTING PAGE (empty if new):
\"\"\"
{existing_page}
\"\"\"

Write the full markdown page now (frontmatter + body)."""


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
                source_text=source_text,
                existing_page=existing_page,
            ),
        },
    ]
