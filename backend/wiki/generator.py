"""Two-step CoT wiki generation pipeline.

Lifecycle of one ingest event
-----------------------------
1. ``WikiGenerator.generate(event)`` is called by the worker.
2. Step 1 (analysis): single LLM call → JSON plan describing what
   pages to create / update + the wikilinks between them.
3. Step 2 (generation): one LLM call per planned page (bounded
   concurrency). Each call writes ``(frontmatter, body)`` markdown.
4. Disk + DB writes happen together: a successful page-write upserts
   the row in ``wiki_pages`` and renders the markdown file. A failure
   on either side is logged and skipped — we never half-write a page.
5. After all pages, edges are upserted in ``wikilinks``.
6. The ``index.md`` and ``log.md`` files are refreshed.

Cost controls
-------------
- ``settings.wiki_max_tokens_per_ingest`` caps the source text fed to
  the analysis step (default 8000 chars). Long PDFs / videos get
  truncated to head + tail + ellipsis. Anything longer than that
  needs a real summarisation pass which is P5 work.
- Generation is fan-out concurrent with a small semaphore (default 3)
  so a single ingest doesn't pin every LLM connection slot.
- Errors are *swallowed per-page* — a malformed page response loses
  one page but doesn't kill the whole ingest.

Mocking for tests
-----------------
The class accepts an optional ``llm_invoker`` callable so unit tests
can drive both steps without spinning up a real LLM. The default
invoker uses :func:`agents.llm.get_llm`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from storage.metadata_db import (
    WIKI_PAGE_TYPES,
    append_wiki_event,
    get_wiki_page,
    list_wiki_pages,
    upsert_wiki_page,
    upsert_wikilink,
)

from agent_core.events import AgentEvent, get_event_stream

from .bootstrap import page_path
from .parser import atomic_write, parse_page, render_page, slugify, strip_code_fences
from .prompts import build_analysis_messages, build_generation_messages

logger = logging.getLogger(__name__)


# ── Public types ─────────────────────────────────────────────────────


LlmInvoker = Callable[[list[dict[str, str]]], Awaitable[str]]
"""Async callable: list-of-chat-messages → response text. Lets tests
inject a deterministic mock without touching the real LLM stack."""


@dataclass(slots=True)
class GenerationResult:
    """Outcome of one ingest event passed through :class:`WikiGenerator`."""
    pages_created:  int = 0
    pages_updated:  int = 0
    pages_failed:   int = 0
    edges_added:    int = 0
    retries:        int = 0
    error:          str | None = None       # non-None ⇒ analysis step failed; nothing written
    page_ids:       list[str] = None        # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.page_ids is None:
            self.page_ids = []

    @property
    def ok(self) -> bool:
        """The pipeline succeeded if analysis finished and at least one
        page was written. A pure-fail run is still ``ok=False`` so the
        worker can mark the event ``kind='ingest_failed'``."""
        return self.error is None and (self.pages_created + self.pages_updated) > 0


# ── Defaults ────────────────────────────────────────────────────────


DEFAULT_SOURCE_TRUNCATE_CHARS = 200000  # model has 1M context window, no need to truncate   # ~12k tokens; large enough for full docs
DEFAULT_GENERATION_CONCURRENCY = 3
DEFAULT_GENERATION_MAX_TOKENS = 2000
DEFAULT_ANALYSIS_MAX_TOKENS = 1500

MAX_INVOKE_RETRIES = 6  # 6 retries for rotating API keys
INVOKE_RETRY_BASE_DELAY = 1.0
INVOKE_RETRY_MAX_DELAY = 8.0

_TRANSIENT_ERROR_TYPES = (
    "Timeout", "ConnectionError", "ConnectError", "ConnectTimeout",
    "ReadTimeout", "RemoteProtocolError", "RateLimitError",
    "InternalServerError", "ServiceUnavailableError", "ServerError",
    "GatewayTimeout", "TooManyRequests", "BusyError",
)


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.TimeoutError):
        return True
    exc_type_name = type(exc).__name__
    if any(t in exc_type_name for t in _TRANSIENT_ERROR_TYPES):
        return True
    msg = str(exc).lower()
    if any(kw in msg for kw in ("timeout","timed out","connection","rate limit","server error","service unavailable","too many requests","503","502","504","429","try again","overloaded")):
        return True
    return False


# ── Generator ───────────────────────────────────────────────────────


class WikiGenerator:
    """End-to-end LLM-driven wiki generator.

    One instance per worker is fine — the class is stateless across
    events. Pass a custom ``llm_invoker`` in tests; callers in
    production should use the no-arg constructor.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        llm_invoker: LlmInvoker | None = None,
        source_truncate_chars: int = DEFAULT_SOURCE_TRUNCATE_CHARS,
        generation_concurrency: int = DEFAULT_GENERATION_CONCURRENCY,
    ):
        self._data_dir = Path(data_dir).expanduser()
        self._invoke: LlmInvoker = llm_invoker or _default_llm_invoker
        self._truncate = max(1000, int(source_truncate_chars))
        self._sem = asyncio.Semaphore(max(1, int(generation_concurrency)))

    # ── Event publishing ────────────────────────────────────────

    @staticmethod
    def _publish_event(type: str, data: dict, task_id: str | None) -> None:
        if task_id is None:
            return
        try:
            stream = get_event_stream()
            evt = AgentEvent(type=type, task_id=task_id, data=data)
            import asyncio
            asyncio.create_task(stream.publish(evt))
        except Exception:
            pass

    # ── Public entry ──────────────────────────────────────────

    async def generate(
        self,
        *,
        source_id: str,
        source_text: str,
        source_metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> GenerationResult:
        """Run the two-step pipeline for one ingested source."""
        meta = dict(source_metadata or {})
        title = meta.get("title", source_id)
        WikiGenerator._publish_event("wiki_analysis_start", {"source_id": source_id, "title": title[:120]}, task_id)

        if not source_text.strip():
            return GenerationResult(error="empty source text")

        truncated = self._truncate_source(source_text)
        purpose_excerpt = self._read_meta_excerpt("purpose.md", limit=3000)
        index_excerpt = self._read_meta_excerpt("index.md", limit=8000)
        schema_excerpt = self._read_meta_excerpt("schema.md", limit=3000)
        overview_text = self._read_meta_excerpt("overview.md", limit=4000)

        # Step 1 — analysis
        try:
            analysis_text = await self._run_analysis(
                source_id=source_id,
                source_metadata=meta,
                source_text=truncated,
                purpose_excerpt=purpose_excerpt,
                index_excerpt=index_excerpt,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki analysis failed for %s: %s", source_id, exc)
            return GenerationResult(error=f"analysis: {type(exc).__name__}: {exc}")

        WikiGenerator._publish_event("wiki_analysis_complete", {
            "source_id": source_id,
            "analysis_len": len(analysis_text),
            "preview": analysis_text[:200],
        }, task_id)

        # Extract JSON plan from analysis text (free-form analysis + dispatch plan)
        plan: dict[str, Any] = {}
        dispatcher_marker = "---DISPATCH PLAN---"
        if dispatcher_marker in analysis_text:
            _, _, plan_text = analysis_text.partition(dispatcher_marker)
            plan = _extract_json_object(plan_text) or {}
        # Fallback: old JSON-only format
        if not plan:
            plan = _extract_json_object(analysis_text) or {}
        pages: list[dict[str, Any]] = plan.get("pages", [])
        # Fill in missing "id" fields: {type}:{slug}
        for p in pages:
            if "id" not in p and "page_type" in p and "slug" in p:
                p["id"] = f"{p['page_type']}:{p['slug']}"
        # Always ensure a source page exists
        has_source = any(p.get("page_type") == "source" for p in pages)
        if not has_source:
            default_slug = slugify(title)
            pages.append({
                "page_type": "source",
                "slug": default_slug,
                "id": f"source:{default_slug}",
                "title": title,
                "tags": _listify(meta.get("tags")),
                "aliases": _listify(meta.get("aliases")),
                "sources": [source_id],
                "rationale": f"Source document: {title}",
            })

        if not pages:
            return GenerationResult(error="no pages to generate")

        # Step 2 — generate every page (source pages bypass LLM, write full text directly)
        result = GenerationResult()
        page_tasks = [
            asyncio.create_task(
                self._write_source_page_directly(p, source_id=source_id, source_text=truncated)
                if p.get("page_type") == "source"
                else self._run_generation_one(
                    plan_page=p,
                    source_id=source_id,
                    source_text=truncated,
                    purpose_excerpt=purpose_excerpt,
                    schema_excerpt=schema_excerpt,
                    index_excerpt=index_excerpt,
                    overview_text=overview_text,
                    analysis_text=analysis_text,
                )
            )
            for p in pages
        ]
        outcomes = await asyncio.gather(*page_tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                result.pages_failed += 1
                logger.warning("wiki page generation crashed: %s", outcome)
                continue
            kind, page_id = outcome  # type: ignore[misc]
            if kind == "created":
                result.pages_created += 1
                result.page_ids.append(page_id)
                WikiGenerator._publish_event("wiki_page_created", {"source_id": source_id, "page_id": page_id, "kind": kind}, task_id)
            elif kind == "updated":
                result.pages_updated += 1
                result.page_ids.append(page_id)
                WikiGenerator._publish_event("wiki_page_created", {"source_id": source_id, "page_id": page_id, "kind": kind}, task_id)
            else:
                result.pages_failed += 1
                WikiGenerator._publish_event("wiki_page_error", {"source_id": source_id, "error": "page generation returned failed"}, task_id)

        # Step 3 — wikilinks. Cross-link new pages with existing ones.
        try:
            existing_pages = await list_wiki_pages(limit=100)
            for page_id in result.page_ids:
                for row in existing_pages:
                    other_id = row["id"]
                    if other_id == page_id:
                        continue
                    try:
                        await upsert_wikilink(
                            page_id, other_id,
                            relation="mentions",
                            weight=0.5,
                        )
                        result.edges_added += 1
                    except Exception:
                        pass
                    if result.edges_added >= 20:
                        break
                if result.edges_added >= 20:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.debug("wiki edge upsert failed: %s", exc)

        # Step 4 — refresh index.md / log.md from authoritative DB state.
        try:
            await self._refresh_index()
        except Exception as exc:  # noqa: BLE001
            logger.debug("wiki index refresh failed: %s", exc)

        # Record a structured event so the UI / events feed can show
        # this run's outcome separately from the simple stub event the
        # worker also writes.
        try:
            await append_wiki_event(
                kind="ingest_generated",
                source_id=source_id,
                page_ids=result.page_ids,
                summary=f"created {result.pages_created} / updated {result.pages_updated}",
            )
        except Exception:  # noqa: BLE001
            pass

        WikiGenerator._publish_event("wiki_sync_complete", {
            "source_id": source_id,
            "pages_created": result.pages_created,
            "pages_updated": result.pages_updated,
            "pages_failed": result.pages_failed,
            "edges_added": result.edges_added,
            "page_ids": result.page_ids,
        }, task_id)

        return result

    # ── Step 1: analysis ─────────────────────────────────────

    async def _run_analysis(
        self,
        *,
        source_id: str,
        source_metadata: dict[str, Any],
        source_text: str,
        purpose_excerpt: str,
        index_excerpt: str,
    ) -> str:
        messages = build_analysis_messages(
            source_id=source_id,
            source_title=source_metadata.get("title") or source_id,
            source_type=source_metadata.get("file_type") or source_metadata.get("type") or "unknown",
            source_url=source_metadata.get("source_url") or source_metadata.get("url"),
            source_text=source_text,
            purpose_excerpt=purpose_excerpt,
            index_excerpt=index_excerpt,
        )
        # Emit thinking card for agent console
        WikiGenerator._publish_event("message_start", {"source_id": source_id, "step": "analysis", "summary": "LLM 分析中…"}, None)
        raw = await self._invoke(messages)
        WikiGenerator._publish_event("message_end", {"source_id": source_id, "step": "analysis", "content": raw[:200]}, None)
        return raw

    # ── Step 2a: write source page directly (no LLM, full text) ──

    async def _write_source_page_directly(
        self, plan_page: dict[str, Any], *, source_id: str, source_text: str
    ) -> tuple[str, str]:
        """Write the source text verbatim to a wiki page. No LLM involved.
        Karpathy pattern: the source page IS the original document."""
        from wiki.parser import slugify, render_page
        from wiki.bootstrap import PAGE_TYPE_DIRECTORY
        from storage.metadata_db import upsert_wiki_page, get_wiki_page

        slug = plan_page.get("slug") or slugify(plan_page.get("title", source_id))
        page_id = plan_page.get("id") or f"source:{slug}"
        title = plan_page.get("title", slug)
        tags = plan_page.get("tags", [])
        aliases = plan_page.get("aliases", [])

        frontmatter = {
            "title": title,
            "type": "source",
            "sources": [source_id],
            "tags": tags,
            "aliases": aliases,
            "created_at": "",
            "updated_at": "",
        }
        body = source_text  # Full text, verbatim — never summarized
        rendered = render_page(frontmatter, body)

        dir_name = PAGE_TYPE_DIRECTORY.get("source", "sources")
        file_path = f"wiki/{dir_name}/{slug}.md"
        await atomic_write(self._data_dir / file_path, rendered)

        existing = await get_wiki_page(page_id)
        is_new = existing is None
        await upsert_wiki_page(
            page_id=page_id, page_type="source", slug=slug, title=title,
            file_path=file_path, summary=body[:200], frontmatter=frontmatter,
            source_ids=[source_id],
        )
        return ("created" if is_new else "updated", page_id)

    # ── Step 2: generate one page via LLM ─────────────────────

    async def _run_generation_one(
        self,
        *,
        plan_page: dict[str, Any],
        source_id: str,
        source_text: str,
        purpose_excerpt: str = "",
        schema_excerpt: str = "",
        index_excerpt: str = "",
        overview_text: str = "",
        analysis_text: str = "",
    ) -> tuple[str, str]:
        """Returns ``("created"|"updated"|"failed", page_id)``."""
        page_type = plan_page["page_type"]
        slug = plan_page["slug"]
        page_id = f"{page_type}:{slug}"

        existing_row = await get_wiki_page(page_id)
        existing_text = ""
        if existing_row is not None:
            try:
                existing_text = self._read_existing_page(existing_row["file_path"])
            except Exception as exc:  # noqa: BLE001
                logger.debug("could not read existing page %s: %s", page_id, exc)

        # Make sure the prompt includes our source id so citations resolve.
        plan_page = dict(plan_page)
        sources = plan_page.get("sources") or []
        if source_id not in sources:
            sources = [*sources, source_id]
        plan_page["sources"] = sources

        messages = build_generation_messages(
            plan_page=plan_page,
            source_text=source_text,
            existing_page=existing_text,
            purpose_excerpt=purpose_excerpt,
            schema_excerpt=schema_excerpt,
            index_excerpt=index_excerpt,
            overview_text=overview_text,
            analysis_text=analysis_text,
        )

        WikiGenerator._publish_event("message_start", {"source_id": source_id, "step": "generation", "page_id": page_id}, None)
        async with self._sem:
            raw = await self._invoke(messages)
        WikiGenerator._publish_event("message_end", {"source_id": source_id, "step": "generation", "page_id": page_id, "content": raw[:150]}, None)

        # Parse + validate the LLM output. We accept the same markdown
        # we'd accept on a manual edit.
        if not raw or not raw.strip():
            return ("failed", page_id)

        page_text = strip_code_fences(raw).strip() + "\n"
        try:
            parsed = parse_page(page_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiki page parse failed for %s: %s", page_id, exc)
            return ("failed", page_id)

        # Language guard — reject pages not predominantly Chinese
        if not self._language_guard(parsed.body):
            logger.warning("wiki page %s language guard failed (not Chinese), skipping", page_id)
            return ("failed", page_id)

        # Backfill the frontmatter with the canonical metadata so the
        # LLM can't drift the type / slug. Title is allowed to come
        # from the LLM since it's the human-readable form.
        fm = dict(parsed.frontmatter or {})
        fm["type"] = page_type
        fm["title"] = fm.get("title") or plan_page.get("title") or slug
        fm["sources"] = sorted(set([*(_listify(fm.get("sources"))), *sources]))
        fm.setdefault("tags", _listify(plan_page.get("tags")))
        fm.setdefault("aliases", _listify(plan_page.get("aliases")))

        rendered = render_page(fm, parsed.body)

        # Post-merge body length validation for existing pages
        is_new = existing_row is None
        if not is_new and not self._validate_merge(parsed.body, existing_text):
            logger.warning("wiki page %s merge rejected (body shrank too much)", page_id)
            return ("failed", page_id)

        # Disk + DB upsert. If disk fails we DON'T touch the DB so the
        # row never points at a non-existent file.
        on_disk = self._page_disk_path(page_type, slug)
        try:
            await asyncio.to_thread(atomic_write, on_disk, rendered)
        except OSError as exc:
            logger.error("wiki page disk write failed for %s: %s", page_id, exc)
            return ("failed", page_id)

        rel_path = on_disk.relative_to(self._data_dir).as_posix()
        try:
            row_after = await upsert_wiki_page({
                "id":          page_id,
                "page_type":   page_type,
                "slug":        slug,
                "title":       fm["title"],
                "file_path":   rel_path,
                "summary":     _first_paragraph(parsed.body, max_chars=240),
                "frontmatter": fm,
                "source_ids":  fm["sources"],
            })
        except Exception as exc:  # noqa: BLE001
            logger.error("wiki page DB upsert failed for %s: %s", page_id, exc)
            return ("failed", page_id)

        kind = "updated" if existing_row is not None else "created"
        if existing_row is not None and row_after["revision"] == 1:
            # Defensive: the row got reset somehow; treat as updated still.
            kind = "updated"
        return (kind, page_id)

    # ── Validation + helpers ─────────────────────────────────

    @staticmethod
    def _language_guard(body: str) -> bool:
        """Return True if body is predominantly Chinese (matching expected wiki language)."""
        import re
        body = re.sub(r'```[\s\S]*?```', '', body)
        body = re.sub(r'\$\$[\s\S]*?\$\$', '', body)
        sample = body.strip()[:800]
        if len(sample) < 20:
            return True
        cjk = sum(1 for c in sample if '一' <= c <= '鿿')
        latin = sum(1 for c in sample if c.isascii() and c.isalpha())
        return cjk > latin * 0.5

    @staticmethod
    def _validate_merge(new_body: str, existing_body: str) -> bool:
        """Reject merge if body shrank > 30%."""
        if not existing_body.strip() or not new_body.strip():
            return True
        ratio = len(new_body) / len(existing_body)
        if ratio < 0.7:
            logger.warning("merge rejected: body shrank %.0f%%", (1-ratio)*100)
            return False
        return True

    def _truncate_source(self, text: str) -> str:
        """Return full source text. Model has 1M context — no truncation needed."""
        return text  # 1M context window, agent auto-compacts at 80%

    def _read_meta_excerpt(self, name: str, *, limit: int) -> str:
        p = self._data_dir / "wiki" / name
        try:
            if not p.is_file():
                return ""
            text = p.read_text(encoding="utf-8")
            # Drop the frontmatter for prompt clarity.
            parsed = parse_page(text)
            body = parsed.body.strip()
            return body[:limit]
        except OSError:
            return ""

    def _page_disk_path(self, page_type: str, slug: str) -> Path:
        return page_path(self._data_dir, page_type, slug)

    def _read_existing_page(self, file_path: str) -> str:
        p = self._data_dir / file_path
        return p.read_text(encoding="utf-8")

    async def _refresh_index(self) -> None:
        """Rebuild ``data/wiki/index.md`` from the current DB state, then
        optionally enhance it with LLM-written summaries."""
        sections: list[tuple[str, str]] = [
            ("Overview",      "overview"),
            ("Entities",      "entity"),
            ("Concepts",      "concept"),
            ("Sources",       "source"),
            ("Saved queries", "query"),
        ]
        lines: list[str] = ["---", 'title: "Index"', 'kind: "meta"']
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines.append(f'updated_at: "{now}"')
        lines.append("---")
        lines.append("")
        lines.append("# Index")
        lines.append("")
        lines.append("")
        all_pages = []
        for heading, ptype in sections:
            pages = await list_wiki_pages(page_type=ptype, limit=500)
            all_pages.extend([
                {"type": ptype, "slug": p["slug"], "title": p["title"], "summary": (p.get("summary") or "")[:200]}
                for p in pages
            ])
            lines.append(f"## {heading}")
            if not pages:
                lines.append("_(none yet)_")
            else:
                for row in pages:
                    summary = row.get("summary") or ""
                    summary = summary.replace("\n", " ").strip()
                    if len(summary) > 140:
                        summary = summary[:139].rstrip() + "…"
                    link = f"[[{row['page_type']}:{row['slug']}]]"
                    lines.append(f"- {link} — {summary}" if summary else f"- {link}")
            lines.append("")

        path = self._data_dir / "wiki" / "index.md"
        await asyncio.to_thread(atomic_write, path, "\n".join(lines) + "\n")

        # Auto-update overview.md if we have enough pages
        total_pages = sum(1 for _, _pgs in [(h, await list_wiki_pages(page_type=pt, limit=500)) for h, pt in sections] for _ in _pgs)
        if total_pages >= 5:
            try:
                index_text = "\n".join(lines)
                overview_prompt = (
                    "Write a 2-4 paragraph synthesis of the ENTIRE wiki based on the index below. "
                    "Use Chinese (简体中文). Write in a cohesive narrative style. Do NOT use markdown headings, "
                    "just plain paragraphs. The overview should serve as a TL;DR for new readers.\n\n"
                    f"{index_text}"
                )
                overview_raw = await self._invoke([
                    {"role": "system", "content": "You are a wiki curator. Write a concise overview. Use Chinese."},
                    {"role": "user", "content": overview_prompt},
                ])
                overview_md = (
                    "---\n"
                    f'title: "Overview"\n'
                    f'kind: "meta"\n'
                    f'updated_at: "{now}"\n'
                    "---\n\n"
                    "# Overview\n\n"
                    f"{overview_raw.strip()}\n"
                )
                overview_path = self._data_dir / "wiki" / "overview.md"
                await asyncio.to_thread(atomic_write, overview_path, overview_md)
            except Exception as exc:  # noqa: BLE001
                logger.debug("wiki overview auto-update failed: %s", exc)


# ── Helpers (module-private) ─────────────────────────────────────────


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction from a chat completion.

    Models occasionally wrap JSON in prose or markdown fences even when
    asked not to. We try the strict path first, then fall back to
    pulling the largest balanced ``{...}`` substring.
    """
    text = (text or "").strip()
    if not text:
        return None
    # Strip code fences first
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJECT_RE.search(cleaned)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


def _first_paragraph(body: str, *, max_chars: int) -> str:
    """Return the first non-heading paragraph, trimmed."""
    out: list[str] = []
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            if out:
                break
            continue
        if s.startswith("#"):
            continue
        out.append(s)
        if sum(len(x) + 1 for x in out) >= max_chars:
            break
    text = " ".join(out)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


# ── Default LLM invoker ──────────────────────────────────────────────


async def _default_llm_invoker(messages: list[dict[str, str]]) -> str:
    """Call the configured chat model with transient-error retry.

    Lazy-imported so tests with a custom invoker never need real LLM
    credentials at import time."""
    from agents.llm import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

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

    last_error = None
    for attempt in range(MAX_INVOKE_RETRIES + 1):
        try:
            llm = get_llm(temperature=0.2, max_tokens=DEFAULT_GENERATION_MAX_TOKENS)
            resp = await llm.ainvoke(converted)
            return getattr(resp, "content", "") or ""
        except Exception as exc:
            last_error = exc
            if attempt >= MAX_INVOKE_RETRIES or not _is_transient_error(exc):
                raise
            delay = min(INVOKE_RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5), INVOKE_RETRY_MAX_DELAY)
            logging.getLogger("wiki.generator").warning(
                "LLM invoke transient error (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, MAX_INVOKE_RETRIES + 1, type(exc).__name__, delay,
            )
            await asyncio.sleep(delay)
    raise last_error
