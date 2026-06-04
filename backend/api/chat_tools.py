"""KB tools exposed to the chat agent.

These are LangChain ``@tool`` functions the chat-side LLM can call to:
* search the vector store (``search_kb``)
* explore the source catalogue (``list_sources`` / ``list_tags``)
* read full chunks of a known source (``get_source_chunks``)
* fetch a fresh URL on-the-fly without ingesting it (``fetch_url_preview``)

Each tool returns LLM-friendly text. ``search_kb`` ALSO mutates a shared
``ChatContext`` so the outer streaming loop can build accurate citations
from chunks the LLM actually retrieved.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import tool as _lc_tool

logger = logging.getLogger(__name__)


@dataclass
class ChatContext:
    """Shared state between the chat agent loop and its tools.

    The loop hands a single instance to every tool factory at construction time
    so the tools can register the chunks they returned. The outer SSE renderer
    then walks ``retrieved_chunks`` to emit citations.
    """
    kb_filter: dict[str, str] | None = None
    qdrant_filter: object | None = None
    """Optional Qdrant Filter for scenario-scoped retrieval."""
    scenario_source_ids: list[str] | None = None
    """When set, list_sources / get_source_chunks are scoped to these sources."""
    retrieved_chunks: list[dict] = field(default_factory=list)
    """Chunks returned across all search_kb calls, deduped by id."""
    fetched_urls: list[str] = field(default_factory=list)
    """URLs the agent pulled in-session (for transparency in the UI)."""

    def register_chunks(self, chunks: list[dict]) -> None:
        seen = {c["id"] for c in self.retrieved_chunks}
        for c in chunks:
            if c["id"] not in seen:
                self.retrieved_chunks.append(c)
                seen.add(c["id"])


def _fmt_chunk(idx: int, c: dict, max_chars: int = 600) -> str:
    src = c["metadata"].get("source_name") or c["metadata"].get("source_url") or "unknown"
    body = (c.get("content") or "")[:max_chars]
    return f"[{idx}] Source: {src}\nID: {c['id']}\n{body}"


def build_chat_tools(ctx: ChatContext):
    """Build a list of LangChain tools wired to *ctx*.

    Returns a list of ``@tool``-decorated functions that share the same
    context state. Construct fresh per-request — never reuse across users.
    """

    @_lc_tool
    async def search_kb(query: str, top_k: int = 5) -> str:
        """Search the user's personal knowledge base via hybrid (dense + sparse) retrieval.

        Returns up to ``top_k`` chunks formatted as numbered excerpts with
        their source name and chunk ID. Call this whenever the user's
        question might be answered from existing materials.
        """
        from pipeline.retrieval import retrieve_chunks
        try:
            retrieval = await retrieve_chunks(
                query=query,
                top_k=top_k,
                filters=ctx.kb_filter,
                mode="hybrid",
                rerank=True,
                diversify=True,
                expand=True,
                qdrant_filter=ctx.qdrant_filter,
            )
        except Exception as exc:
            return f"[search_kb: search failed — {exc}]"
        chunks = retrieval.results
        if not chunks:
            return "[search_kb: no matching chunks]"
        ctx.register_chunks(chunks)
        # Number relative to the cumulative retrieved set so cite markers
        # the LLM emits in its final answer line up with the citations payload.
        start = len(ctx.retrieved_chunks) - len(chunks) + 1
        parts = [_fmt_chunk(start + i, c) for i, c in enumerate(chunks)]
        return "\n\n---\n\n".join(parts)

    @_lc_tool
    async def list_sources(tag: str = "", limit: int = 20) -> str:
        """List ingested sources, optionally filtered by tag.

        Returns a JSON array of ``{id, name, source_type, tags, created_at}``.
        Use to discover available materials before deeper exploration.
        """
        from storage.metadata_db import list_sources as _list_sources
        try:
            rows = await _list_sources(limit=max(1, min(limit, 50)), filter_tag=tag or None)
        except Exception as exc:
            return f"[list_sources error: {exc}]"
        if ctx.scenario_source_ids is not None:
            sid_set = set(ctx.scenario_source_ids)
            rows = [r for r in rows if r.get("id") in sid_set]
        compact = [
            {
                "id": r.get("id"),
                "name": r.get("name") or r.get("source_url") or "(untitled)",
                "source_type": r.get("source_type"),
                "tags": r.get("tags") or [],
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]
        return json.dumps(compact, ensure_ascii=False)

    @_lc_tool
    async def list_tags() -> str:
        """Return the full set of tags used across the knowledge base."""
        from storage.metadata_db import get_all_tags
        try:
            tags = await get_all_tags()
        except Exception as exc:
            return f"[list_tags error: {exc}]"
        return json.dumps(tags, ensure_ascii=False)

    @_lc_tool
    async def get_source_chunks(source_id: str, limit: int = 5) -> str:
        """Read the leading chunks of a known source verbatim.

        Use after ``list_sources`` to drill into a specific document instead
        of relying on semantic search.
        """
        from storage.metadata_db import list_chunks_by_source
        if ctx.scenario_source_ids is not None and source_id not in ctx.scenario_source_ids:
            return f"[get_source_chunks: source {source_id} not in current scenario]"
        try:
            chunks = await list_chunks_by_source(source_id, limit=max(1, min(limit, 20)))
        except Exception as exc:
            return f"[get_source_chunks error: {exc}]"
        if not chunks:
            return "[get_source_chunks: empty source or unknown id]"
        ctx.register_chunks(chunks)
        start = len(ctx.retrieved_chunks) - len(chunks) + 1
        parts = [_fmt_chunk(start + i, c, max_chars=800) for i, c in enumerate(chunks)]
        return "\n\n---\n\n".join(parts)

    @_lc_tool
    async def fetch_url_preview(url: str, intent: str = "") -> str:
        """Fetch a fresh URL right now (without ingesting it) and return its text.

        Use for transient look-ups where the user wants a one-off answer
        from a live web page they have not yet added to the KB.
        Cookies / auth not supported here — for that, ask the user to ingest.
        """
        try:
            from agents.web_agent import fetch_url as _fetch_url
        except Exception as exc:
            return f"[fetch_url_preview unavailable: {exc}]"
        try:
            doc = await asyncio.wait_for(
                _fetch_url(url=url, mode="auto", intent=intent or "general look-up"),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            return f"[fetch_url_preview: timeout on {url}]"
        except ValueError as exc:
            return f"[fetch_url_preview rejected: {exc}]"
        except Exception as exc:
            return f"[fetch_url_preview error: {exc}]"
        ctx.fetched_urls.append(url)
        body = (doc.content or "")[:4000]
        return f"# Fetched: {url}\n\n{body}"

    # ── Wiki tools (only registered when settings.wiki_retrieval_enabled) ──
    #
    # The L2 wiki layer carries cross-document synthesis the chunk
    # store cannot — entity / concept / source pages with citations.
    # When the feature flag is on, the chat agent gets two extra
    # tools that search and read the wiki. The agent decides whether
    # to use them; when they're off the prompt size shrinks and chat
    # behaviour is identical to before P4.

    try:
        from config import settings as _wiki_settings
        _wiki_on = bool(getattr(_wiki_settings, "wiki_retrieval_enabled", False))
        _data_dir = _wiki_settings.data_dir
    except Exception:  # noqa: BLE001 — defensive: never break chat
        _wiki_on = False
        _data_dir = "data"

    # Wiki-only mode: only expose read_wiki_page + fetch_url_preview.
    # Wiki index is provided in system prompt — no search/listing needed.
    @_lc_tool
    async def read_wiki_page(page_id: str) -> str:
        """Read the full markdown body of a wiki page by id.

        ``page_id`` follows the form ``<type>:<slug>``, e.g.
        ``entity:andrej-karpathy`` or ``concept:llm-wiki``. Use when a
        page listed in ``<wiki_index>`` seems relevant to the user's
        question, or when you already know which page you want.
        """
        from wiki.retriever import read_page_body
        try:
            row, body = await read_page_body(page_id, data_dir=_data_dir)
        except Exception as exc:
            return f"[read_wiki_page error: {exc}]"
        if row is None:
            return f"[read_wiki_page: unknown page id {page_id!r}]"
        if not body:
            return (
                f"# {row['title']}\n\n_(page metadata exists but body is empty — "
                "wiki worker may still be generating it)_"
            )
        return body

    @_lc_tool
    async def update_wiki_page(page_id: str, content: str) -> str:
        """Update the body content of an existing wiki page. Returns confirmation or error."""
        try:
            from storage.metadata_db import get_wiki_page, upsert_wiki_page
            existing = await get_wiki_page(page_id)
            if not existing:
                return f"[update_wiki_page: page not found: {page_id}]"
            updated = copy.deepcopy(existing)
            updated["body"] = content
            await upsert_wiki_page(updated)
            return f"[update_wiki_page: '{page_id}' updated successfully]"
        except Exception as e:
            return f"[update_wiki_page error: {e}]"

    @_lc_tool
    async def create_wiki_page(page_type: str, slug: str, title: str, content: str) -> str:
        """Create a new wiki page. page_type: entity|concept|source|query. Returns confirmation."""
        try:
            from storage.metadata_db import upsert_wiki_page, WIKI_PAGE_TYPES
            from wiki.parser import slugify
            if page_type not in WIKI_PAGE_TYPES:
                return f"[create_wiki_page: invalid type '{page_type}'. Must be one of: {WIKI_PAGE_TYPES}]"
            slug = slugify(slug)
            if slug == "unnamed":
                slug = f"page-{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
            page_id = f"{page_type}:{slug}"
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            await upsert_wiki_page({
                "id": page_id, "page_type": page_type, "slug": slug, "title": title,
                "file_path": f"wiki/{page_type}s/{slug}.md", "summary": content[:200],
                "frontmatter": json.dumps({"tags": [], "aliases": []}),
                "source_ids": json.dumps([]), "body": content,
                "created_at": now, "updated_at": now, "revision": 1,
            })
            return f"[create_wiki_page: '{page_id}' created]"
        except Exception as e:
            return f"[create_wiki_page error: {e}]"

    @_lc_tool
    async def list_wiki_pages_tool(page_type: str = "") -> str:
        """List all wiki pages, optionally filtered by type. Returns page IDs and titles."""
        try:
            from storage.metadata_db import list_wiki_pages
            pages = await list_wiki_pages(page_type=page_type or None, limit=200)
            if not pages:
                return "[list_wiki_pages: no pages found]"
            lines = [f"- {p['id']}: {p['title']} ({p['page_type']})" for p in pages[:50]]
            if len(pages) > 50:
                lines.append(f"... and {len(pages)-50} more")
            return "\n".join(lines)
        except Exception as e:
            return f"[list_wiki_pages error: {e}]"

    @_lc_tool
    async def search_wiki_tool(query: str) -> str:
        """Search wiki pages by query. Returns matching page IDs and summaries."""
        try:
            from wiki.retriever import search_wiki_pages
            results = await search_wiki_pages(query, limit=10)
            if not results:
                return f"[search_wiki: no results for '{query}']"
            lines = [f"- {r['id']}: {r['title']} (score: {r.get('score',0):.1f})" for r in results]
            return "\n".join(lines)
        except Exception as e:
            return f"[search_wiki error: {e}]"

    @_lc_tool
    async def get_wiki_stats_tool() -> str:
        """Get wiki statistics: total pages by type, total edges, worker status."""
        try:
            from storage.metadata_db import count_wiki_pages_by_type, count_wikilinks
            counts = await count_wiki_pages_by_type()
            edges = await count_wikilinks()
            parts = [f"Total pages: {sum(counts.values())}"]
            for t, c in sorted(counts.items()):
                parts.append(f"  {t}: {c}")
            parts.append(f"Total edges: {edges}")
            return "\n".join(parts)
        except Exception as e:
            return f"[wiki_stats error: {e}]"

    @_lc_tool
    def list_sources_tool() -> str:
        """List all knowledge base sources with their names, types, and IDs."""
        try:
            from storage.metadata_db import list_sources as _list_sources
            sources = _sync_run(_list_sources(limit=200))
            if not sources:
                return "No sources found."
            lines = ["Sources in knowledge base:"]
            for s in sources:
                lines.append(f"- {s.get('name','?')[:60]} (id: {s.get('id','?')[:12]}..., type: {s.get('type','?')})")
            return "\n".join(lines)
        except Exception as e:
            return f"[list_sources error: {e}]"

    @_lc_tool
    def read_source_text(source_id: str) -> str:
        """Read the raw text content of an ingested source by its ID. Useful for updating wiki pages from source material."""
        try:
            import sqlite3, json as _json
            from config import settings
            db = sqlite3.connect(settings.sqlite_path)
            row = db.execute(
                "SELECT params_json FROM tasks WHERE source_id = ? AND params_json IS NOT NULL ORDER BY rowid DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            db.close()
            if not row:
                return f"[read_source_text: no content found for source {source_id}]"
            params = _json.loads(row[0]) if row[0] else {}
            text = params.get("content", "")
            if not text:
                return f"[read_source_text: empty content for source {source_id}]"
            # Truncate to 15000 chars to fit context budget
            if len(text) > 15000:
                text = text[:15000] + "\n\n[... content truncated at 15000 chars ...]"
            return text
        except Exception as e:
            return f"[read_source_text error: {e}]"

    return [read_wiki_page, fetch_url_preview, update_wiki_page, create_wiki_page, list_wiki_pages_tool, search_wiki_tool, get_wiki_stats_tool, list_sources_tool, read_source_text]
