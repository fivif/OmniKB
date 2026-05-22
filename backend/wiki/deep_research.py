"""Deep Research orchestrator — autonomously enrich a wiki page from the web.

Pipeline (one ``research_page`` call):

1. **Load** the target wiki page from DB + disk.
2. **Plan queries** — LLM proposes 3-5 web search queries from the
   page's title / summary / tags / body excerpt + optional focus.
3. **Search** the open web (``wiki.web_search``) for each query, merge
   + dedupe, keep top ``max_urls`` results.
4. **Investigate** each URL in parallel by reusing the existing
   ``agents.web.loop.run_agent`` (Plan→Execute→Verify) — it already
   knows how to extract clean text, handle anti-bot, and verify
   sufficiency. Each call returns a synthesised markdown record.
5. **Synthesise** all per-URL records into a *single* ``## Recent
   Research (YYYY-MM-DD)`` section. The synthesis LLM is told to
   ``extend never overwrite`` (Karpathy's core principle) and cite
   every URL.
6. **Append** the new section atomically to the page on disk, bump
   the DB ``revision``, and add fresh ``[[wikilink]]`` edges.
7. **Audit** by writing a ``wiki_event`` row + log.md line.

Failure isolation:

* Per-URL fetch errors are captured as ``{url, error}`` entries and
  surfaced in the result; the synthesis runs over whatever succeeded.
* If 0 URLs survive, the run ends as ``failed`` and the page is not
  touched.
* The whole orchestrator is wrapped in a try/finally so the task
  status dict always settles to a terminal value.

Concurrency note: ``max_urls`` defaults to 3. The web agent can fan
out many tool calls per URL, so even 3 URLs can mean dozens of LLM
calls. We rely on the existing ``BudgetTracker`` defaults in
``agents.web.loop._default_budget`` to keep that bounded.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from storage.metadata_db import (
    append_wiki_event,
    get_wiki_page,
    upsert_wiki_page,
    upsert_wikilink,
)
from .bootstrap import page_path
from .parser import extract_wikilinks
from .web_search import SearchError, SearchResult, web_search

logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────

DEFAULT_MAX_URLS         = 3       # how many URLs to actually dig into
DEFAULT_MAX_QUERIES      = 4       # how many search queries to run
DEFAULT_RESULTS_PER_Q    = 5       # candidate URLs per query before dedup
DEFAULT_BODY_EXCERPT     = 1500    # chars of existing body to show planner
DEFAULT_PER_URL_BUDGET_S = 90.0    # cap each URL's research call

LLMInvoker = Callable[[list[dict[str, str]]], Awaitable[str]]
"""Same shape as ``WikiGenerator``'s invoker — easy mock injection."""

SearchFn = Callable[[str, int], Awaitable[list[SearchResult]]]
"""``(query, limit) → results``. Override in tests."""

ResearchFn = Callable[[str, str], Awaitable[str]]
"""``(url, intent) → markdown record``. Override in tests."""


# ── Status tracking (in-process, v0) ──────────────────────────────


@dataclass(slots=True)
class ResearchTask:
    """Mutable handle the API returns + the UI polls.

    Kept in a process-local dict — when the backend restarts, in-flight
    research vanishes. Acceptable for v0 since research is initiated
    manually and a restart while one is running is unlikely. If we
    later want persistence, swap this for a sqlite row.
    """
    task_id:     str
    page_id:     str
    focus:       str = ""
    status:      str = "queued"   # queued|searching|fetching|synthesising|writing|done|failed
    phase_note:  str = ""         # short human-readable subdetail
    created_at:  float = field(default_factory=time.time)
    finished_at: float | None = None
    result:      dict | None = None
    error:       str | None = None

    def mark(self, status: str, *, note: str = "") -> None:
        self.status = status
        self.phase_note = note
        logger.info("research[%s] %s — %s", self.task_id[:8], status, note or "")

    def to_dict(self) -> dict:
        return {
            "task_id":     self.task_id,
            "page_id":     self.page_id,
            "focus":       self.focus,
            "status":      self.status,
            "phase_note":  self.phase_note,
            "created_at":  self.created_at,
            "finished_at": self.finished_at,
            "result":      self.result,
            "error":       self.error,
        }


_TASKS: dict[str, ResearchTask] = {}


def get_task(task_id: str) -> ResearchTask | None:
    return _TASKS.get(task_id)


def list_recent_tasks(limit: int = 20) -> list[ResearchTask]:
    """Most recent first — used by the UI status panel."""
    items = sorted(_TASKS.values(), key=lambda t: t.created_at, reverse=True)
    return items[:limit]


# ── Prompts ───────────────────────────────────────────────────────

_QUERY_PLAN_SYSTEM = (
    "You are a research planning assistant for a personal knowledge base.\n"
    "Given an existing wiki page and an optional focus, propose web search "
    "queries that would surface FRESH, AUTHORITATIVE information the page "
    "doesn't already cover.\n\n"
    "Output STRICT JSON only — no prose, no markdown fence:\n"
    '{\n'
    '  "queries": [\n'
    '    {"query": "...", "intent": "what gap this query fills"},\n'
    '    ...\n'
    '  ]\n'
    '}\n\n'
    "Rules:\n"
    "- 3 to 5 queries; never more.\n"
    "- Each query is 3 to 8 words, specific enough to find the named "
    "entity / concept reliably on the open web.\n"
    "- Cover DIFFERENT angles: biographical, technical depth, recent "
    "news, comparable work, criticisms.\n"
    "- Avoid queries the existing summary already fully answers.\n"
    "- If focus is given, lean toward it but keep at least one orthogonal query."
)

_QUERY_PLAN_USER = """## Page (current state)

Title: {title}
Type:  {page_type}
Tags:  {tags}
Summary: {summary}

### Body excerpt
{body_excerpt}

### Focus
{focus}

Now emit the JSON query plan."""


_SYNTHESIS_SYSTEM = (
    "You are the curator of a personal knowledge base modelled on the "
    "Karpathy LLM-Wiki pattern. You receive an existing wiki page and a "
    "set of research findings from multiple web sources. Your job is to "
    "write a SINGLE new markdown section to APPEND to the page.\n\n"
    "Hard rules:\n"
    "- Output starts with `## Recent Research ({today})` exactly.\n"
    "- NEVER rewrite or contradict the existing body. Only extend.\n"
    "- Cite every web URL inline using `[label](url)` form.\n"
    "- Add `[[type:slug]]` wikilinks for newly mentioned entities / "
    "concepts. Use `entity:` for people/organisations, `concept:` for "
    "ideas/techniques.\n"
    "- If two sources contradict each other, surface both with a "
    "`> ⚠ Contradicts:` blockquote and cite each.\n"
    "- 200-800 words total. Be specific. No fluff, no introductions.\n"
    "- Output ONLY the new section markdown. No frontmatter, no "
    "surrounding prose, no code fences around the output."
)

_SYNTHESIS_USER = """## Existing page

Title: {title}
Type:  {page_type}

```markdown
{existing_body}
```

## Research findings (one block per source)

{findings_blob}

## Optional focus
{focus}

Now write ONLY the new ## Recent Research section to append."""


# ── Orchestrator ──────────────────────────────────────────────────


class DeepResearcher:
    """One instance per process is fine — stateless across runs."""

    def __init__(
        self,
        data_dir: str | Path,
        *,
        llm_invoker:  LLMInvoker | None = None,
        search_fn:    SearchFn | None = None,
        research_fn:  ResearchFn | None = None,
        max_urls:     int = DEFAULT_MAX_URLS,
        max_queries:  int = DEFAULT_MAX_QUERIES,
    ) -> None:
        self._data_dir = Path(data_dir).expanduser()
        self._invoke   = llm_invoker or _default_llm_invoker
        self._search   = search_fn   or _default_search_fn
        self._research = research_fn or _default_research_fn
        self._max_urls = max(1, int(max_urls))
        self._max_q    = max(1, int(max_queries))

    # ── Public entry ─────────────────────────────────────────

    async def research_page(
        self,
        *,
        page_id: str,
        focus: str = "",
        task: ResearchTask | None = None,
    ) -> dict:
        """End-to-end: load → plan → search → research → synthesise → apply."""
        if task is None:
            task = ResearchTask(task_id=uuid.uuid4().hex, page_id=page_id, focus=focus)
            _TASKS[task.task_id] = task

        try:
            task.mark("loading", note=f"reading {page_id}")
            page = await get_wiki_page(page_id)
            if page is None:
                raise ValueError(f"unknown wiki page: {page_id}")
            existing_body = self._read_body(page)

            # ── Plan queries ───────────────────────────────
            task.mark("planning", note="LLM proposing search queries")
            queries = await self._plan_queries(
                page=page, body=existing_body, focus=focus,
            )
            if not queries:
                raise ValueError("query planner returned no queries")

            # ── Search ──────────────────────────────────────
            task.mark("searching", note=f"{len(queries)} queries on DDG")
            urls = await self._collect_urls(queries)
            if not urls:
                raise ValueError("no URLs found for any query")

            # ── Per-URL research ────────────────────────────
            task.mark("fetching", note=f"investigating {len(urls)} URLs")
            findings = await self._investigate_urls(
                urls=urls, page=page, focus=focus,
            )
            successful = [f for f in findings if not f.get("error")]
            if not successful:
                raise ValueError("every URL fetch failed; nothing to synthesise")

            # ── Synthesise + write back ─────────────────────
            task.mark("synthesising", note="merging findings into a new section")
            new_section = await self._synthesise_section(
                page=page, existing_body=existing_body,
                findings=successful, focus=focus,
            )
            if not new_section.strip():
                raise ValueError("synthesis produced an empty section")

            task.mark("writing", note="appending to page + bumping revision")
            applied = await self._apply_section(
                page=page, new_section=new_section,
            )

            # ── Audit ───────────────────────────────────────
            await append_wiki_event(
                kind="deep_research",
                page_ids=[page_id],
                source_id=task.task_id,
                summary=(
                    f"Added {applied['new_chars']} chars, "
                    f"{applied['new_links']} new links from "
                    f"{len(successful)}/{len(urls)} URL(s)"
                ),
            )

            task.result = {
                "page_id":         page_id,
                "queries":         queries,
                "urls_used":       [f["url"] for f in successful],
                "urls_failed":     [f["url"] for f in findings if f.get("error")],
                "new_chars":       applied["new_chars"],
                "new_links":       applied["new_links"],
                "new_section_head": new_section[:200],
            }
            task.mark("done", note=f"+{applied['new_chars']} chars")
            return task.result

        except Exception as exc:  # noqa: BLE001 — top-level barrier
            task.error = str(exc)
            task.mark("failed", note=str(exc)[:120])
            logger.warning("research[%s] failed: %s", task.task_id[:8], exc, exc_info=True)
            raise
        finally:
            task.finished_at = time.time()

    # ── Internal stages ──────────────────────────────────────

    def _read_body(self, page: dict) -> str:
        try:
            return (self._data_dir / page["file_path"]).read_text(
                encoding="utf-8", errors="replace",
            )
        except OSError as exc:
            logger.warning("research: cannot read %s: %s", page["file_path"], exc)
            return f"# {page['title']}\n\n(body file missing)\n"

    async def _plan_queries(
        self, *, page: dict, body: str, focus: str,
    ) -> list[dict]:
        body_excerpt = body[:DEFAULT_BODY_EXCERPT]
        tags = (page.get("frontmatter") or {}).get("tags") or []
        msgs = [
            {"role": "system", "content": _QUERY_PLAN_SYSTEM},
            {"role": "user", "content": _QUERY_PLAN_USER.format(
                title=page["title"],
                page_type=page["page_type"],
                tags=", ".join(tags) if tags else "(none)",
                summary=page.get("summary") or "(empty)",
                body_excerpt=body_excerpt,
                focus=focus or "(none — explore broadly)",
            )},
        ]
        raw = await self._invoke(msgs)
        plan = _extract_json(raw)
        queries = (plan or {}).get("queries") or []
        # Normalise + cap.
        out: list[dict] = []
        seen: set[str] = set()
        for q in queries:
            if not isinstance(q, dict):
                continue
            qs = (q.get("query") or "").strip()
            if not qs or qs.lower() in seen:
                continue
            seen.add(qs.lower())
            out.append({"query": qs, "intent": (q.get("intent") or "").strip()})
            if len(out) >= self._max_q:
                break
        return out

    async def _collect_urls(self, queries: list[dict]) -> list[SearchResult]:
        # Fan out the searches but bound concurrency to avoid DDG rate-limit.
        sem = asyncio.Semaphore(2)

        async def _one(q: dict) -> list[SearchResult]:
            async with sem:
                try:
                    return await self._search(q["query"], DEFAULT_RESULTS_PER_Q)
                except SearchError as exc:
                    logger.warning("search %r failed: %s", q["query"], exc)
                    return []
                except Exception as exc:  # noqa: BLE001
                    logger.warning("search %r unexpected %s", q["query"], exc)
                    return []

        per_query = await asyncio.gather(*[_one(q) for q in queries])

        merged: list[SearchResult] = []
        seen: set[str] = set()
        # Interleave: take 1st of each query, then 2nd of each, etc. so we get
        # diversity rather than top-5-of-query-1.
        depth = 0
        while len(merged) < self._max_urls and depth < DEFAULT_RESULTS_PER_Q:
            for results in per_query:
                if depth >= len(results):
                    continue
                hit = results[depth]
                key = _canonical_url(hit.url)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(hit)
                if len(merged) >= self._max_urls:
                    break
            depth += 1
        return merged

    async def _investigate_urls(
        self, *, urls: list[SearchResult], page: dict, focus: str,
    ) -> list[dict]:
        """Run the existing web research agent on each URL in parallel."""
        intent_template = (
            f"Extract information about {page['title']!r} "
            f"({page['page_type']}) from this page. "
        )
        if focus:
            intent_template += f"Focus on: {focus}. "
        intent_template += "Return a markdown record with inline citations."

        async def _one(hit: SearchResult) -> dict:
            try:
                content = await asyncio.wait_for(
                    self._research(hit.url, intent_template),
                    timeout=DEFAULT_PER_URL_BUDGET_S,
                )
            except asyncio.TimeoutError:
                return {"url": hit.url, "title": hit.title, "error": "timeout"}
            except Exception as exc:  # noqa: BLE001
                return {"url": hit.url, "title": hit.title, "error": str(exc)[:200]}
            if not content or len(content.strip()) < 100:
                return {"url": hit.url, "title": hit.title, "error": "empty content"}
            return {"url": hit.url, "title": hit.title, "content": content}

        return await asyncio.gather(*[_one(u) for u in urls])

    async def _synthesise_section(
        self, *, page: dict, existing_body: str,
        findings: list[dict], focus: str,
    ) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Keep the existing-body slice small — the synthesis prompt only
        # needs enough context to avoid duplicating, not the whole page.
        body_slice = existing_body[:3000]

        blocks: list[str] = []
        for i, f in enumerate(findings, 1):
            content = f["content"][:4000]
            blocks.append(
                f"### Source {i}: {f['title']}\n"
                f"URL: {f['url']}\n\n"
                f"{content}"
            )
        findings_blob = "\n\n---\n\n".join(blocks)

        msgs = [
            {"role": "system", "content": _SYNTHESIS_SYSTEM.format(today=today)},
            {"role": "user",   "content": _SYNTHESIS_USER.format(
                title=page["title"],
                page_type=page["page_type"],
                existing_body=body_slice,
                findings_blob=findings_blob,
                focus=focus or "(none — synthesise broadly)",
            )},
        ]
        raw = await self._invoke(msgs)
        # The model sometimes wraps output in fences despite the instruction;
        # strip them so we don't pollute the page.
        return _strip_code_fence(raw).strip()

    async def _apply_section(
        self, *, page: dict, new_section: str,
    ) -> dict:
        """Append the new section, atomically rewrite the file, bump rev."""
        path = self._data_dir / page["file_path"]
        existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

        # Append after a blank line — keep markdown clean.
        sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
        new_full = existing + sep + new_section.rstrip() + "\n"

        # Atomic write via tmp + rename.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(new_full, encoding="utf-8")
        tmp.replace(path)

        # Bump revision via upsert (re-uses the same data; updated_at refreshes).
        await upsert_wiki_page({
            "page_type":   page["page_type"],
            "slug":        page["slug"],
            "title":       page["title"],
            "summary":     page.get("summary") or "",
            "frontmatter": page.get("frontmatter") or {},
            "source_ids":  page.get("source_ids") or [],
        })

        # Extract wikilinks from the new section and upsert edges.
        new_links = 0
        for link in extract_wikilinks(new_section):
            if not link.page_type:
                continue
            dst = f"{link.page_type}:{link.slug}"
            try:
                await upsert_wikilink(page["id"], dst, relation="references")
                new_links += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("upsert_wikilink %s→%s failed: %s", page["id"], dst, exc)

        return {
            "new_chars": len(new_section),
            "new_links": new_links,
        }


# ── Helpers ───────────────────────────────────────────────────────


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
_FENCE_RE      = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n([\s\S]*?)\n```\s*$", re.MULTILINE)


def _extract_json(raw: str) -> dict | None:
    """Best-effort JSON parsing — tolerates ```json``` fences or bare JSON."""
    if not raw:
        return None
    m = _JSON_FENCE_RE.search(raw)
    candidate = m.group(1) if m else raw.strip()
    # Fall back: locate the outermost {...} span.
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        candidate = candidate[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _strip_code_fence(text: str) -> str:
    """If the whole response is wrapped in ```...```, return the inside."""
    m = _FENCE_RE.match(text.strip())
    return m.group(1) if m else text


def _canonical_url(url: str) -> str:
    """Same canonicalisation as web_search — reused for cross-query dedup."""
    from .web_search import _canonical
    return _canonical(url)


# ── Default invokers (lazy) ──────────────────────────────────────


async def _default_llm_invoker(messages: list[dict[str, str]]) -> str:
    """Same shape as ``wiki.generator``'s default — keep style consistent."""
    from agents.llm import get_llm
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    llm = get_llm(temperature=0.3, max_tokens=4000)
    converted = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "assistant":
            converted.append(AIMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))
    resp = await llm.ainvoke(converted)
    return getattr(resp, "content", "") or ""


async def _default_search_fn(query: str, limit: int) -> list[SearchResult]:
    return await web_search(query, limit=limit)


async def _default_research_fn(url: str, intent: str) -> str:
    """Reuse the existing URL-driven research agent."""
    from agents.web.loop import run_agent as _web_run_agent
    doc = await _web_run_agent(url=url, intent=intent, task_id=None)
    return getattr(doc, "content", "") or ""


# ── Convenience public entry (used by API + MCP) ──────────────────


async def kickoff_research(
    *,
    page_id: str,
    focus: str = "",
    data_dir: str | Path,
    max_urls: int = DEFAULT_MAX_URLS,
) -> ResearchTask:
    """Create a task, start the orchestrator in the background, return immediately.

    The HTTP API returns the task right away; the UI polls
    ``GET /wiki/research/{task_id}`` for progress.
    """
    researcher = DeepResearcher(data_dir=data_dir, max_urls=max_urls)
    task = ResearchTask(task_id=uuid.uuid4().hex, page_id=page_id, focus=focus)
    _TASKS[task.task_id] = task

    async def _runner() -> None:
        try:
            await researcher.research_page(
                page_id=page_id, focus=focus, task=task,
            )
        except Exception:  # noqa: BLE001 — already captured on task.error
            pass

    asyncio.create_task(_runner(), name=f"deep-research:{task.task_id[:8]}")
    return task
