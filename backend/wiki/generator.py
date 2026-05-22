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

from .bootstrap import page_path
from .parser import parse_page, render_page, slugify
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


DEFAULT_SOURCE_TRUNCATE_CHARS = 8000   # ~2k tokens; analysis call budget
DEFAULT_GENERATION_CONCURRENCY = 3
DEFAULT_GENERATION_MAX_TOKENS = 2000
DEFAULT_ANALYSIS_MAX_TOKENS = 1500


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

    # ── Public entry ──────────────────────────────────────────

    async def generate(
        self,
        *,
        source_id: str,
        source_text: str,
        source_metadata: dict[str, Any] | None = None,
    ) -> GenerationResult:
        """Run the two-step pipeline for one ingested source."""
        meta = dict(source_metadata or {})
        if not source_text.strip():
            return GenerationResult(error="empty source text")

        truncated = self._truncate_source(source_text)
        purpose_excerpt = self._read_meta_excerpt("purpose.md", limit=600)
        index_excerpt = self._read_meta_excerpt("index.md", limit=400)

        # Step 1 — analysis
        try:
            plan = await self._run_analysis(
                source_id=source_id,
                source_metadata=meta,
                source_text=truncated,
                purpose_excerpt=purpose_excerpt,
                index_excerpt=index_excerpt,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("wiki analysis failed for %s: %s", source_id, exc)
            return GenerationResult(error=f"analysis: {type(exc).__name__}: {exc}")

        if not plan.get("pages"):
            return GenerationResult(error="analysis returned no pages")

        # Step 2 — generate every page concurrently (bounded)
        result = GenerationResult()
        page_tasks = [
            asyncio.create_task(
                self._run_generation_one(
                    plan_page=p,
                    source_id=source_id,
                    source_text=truncated,
                )
            )
            for p in plan["pages"]
            if self._validate_plan_page(p)
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
            elif kind == "updated":
                result.pages_updated += 1
                result.page_ids.append(page_id)
            else:
                result.pages_failed += 1

        # Step 3 — wikilinks. Done after all pages so cascade FK is satisfied.
        for edge in plan.get("wikilinks") or []:
            try:
                src = edge.get("src")
                dst = edge.get("dst")
                if not src or not dst or src == dst:
                    continue
                # Only create edges between pages we actually wrote in this run
                # OR pages that already existed. Otherwise FK insert fails.
                if not (await get_wiki_page(src)) or not (await get_wiki_page(dst)):
                    continue
                await upsert_wikilink(
                    src, dst,
                    relation=edge.get("relation") or "mentions",
                    weight=1.0,
                )
                result.edges_added += 1
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
                summary=plan.get("summary") or
                        f"created {result.pages_created} / updated {result.pages_updated}",
            )
        except Exception:  # noqa: BLE001
            pass

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
    ) -> dict[str, Any]:
        messages = build_analysis_messages(
            source_id=source_id,
            source_title=source_metadata.get("title") or source_id,
            source_type=source_metadata.get("file_type") or source_metadata.get("type") or "unknown",
            source_url=source_metadata.get("source_url") or source_metadata.get("url"),
            source_text=source_text,
            purpose_excerpt=purpose_excerpt,
            index_excerpt=index_excerpt,
        )
        raw = await self._invoke(messages)
        plan = _extract_json_object(raw)
        if not isinstance(plan, dict):
            raise ValueError(f"analysis output is not a JSON object: {raw[:120]}")
        # Normalise: ensure required keys exist.
        plan.setdefault("pages", [])
        plan.setdefault("wikilinks", [])
        plan.setdefault("summary", "")
        return plan

    # ── Step 2: generate one page ────────────────────────────

    async def _run_generation_one(
        self,
        *,
        plan_page: dict[str, Any],
        source_id: str,
        source_text: str,
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
        )

        async with self._sem:
            raw = await self._invoke(messages)

        # Parse + validate the LLM output. We accept the same markdown
        # we'd accept on a manual edit.
        if not raw or not raw.strip():
            return ("failed", page_id)

        page_text = _strip_code_fences(raw).strip() + "\n"
        try:
            parsed = parse_page(page_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiki page parse failed for %s: %s", page_id, exc)
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

        # Disk + DB upsert. If disk fails we DON'T touch the DB so the
        # row never points at a non-existent file.
        on_disk = self._page_disk_path(page_type, slug)
        try:
            await asyncio.to_thread(_atomic_write, on_disk, rendered)
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
    def _validate_plan_page(p: Any) -> bool:
        if not isinstance(p, dict):
            return False
        if p.get("page_type") not in WIKI_PAGE_TYPES:
            logger.debug("dropping plan page with bad type: %s", p)
            return False
        slug = p.get("slug")
        if not isinstance(slug, str) or not slug:
            return False
        # Re-slugify to be safe; the LLM occasionally writes "Andrej Karpathy"
        # in the slug field.
        p["slug"] = slugify(slug)
        return bool(p["slug"]) and p["slug"] != "unnamed"

    def _truncate_source(self, text: str) -> str:
        if len(text) <= self._truncate:
            return text
        # Keep head + tail so leads + conclusions both make it.
        head = self._truncate * 2 // 3
        tail = self._truncate - head - 64
        return (
            text[:head]
            + f"\n\n[...truncated {len(text) - head - tail} chars...]\n\n"
            + text[-tail:]
        )

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
        """Rebuild ``data/wiki/index.md`` from the current DB state."""
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
        lines.append("> Regenerated automatically by the wiki worker after every ingest.")
        lines.append("> Do not edit by hand — your changes will be overwritten.")
        lines.append("")
        for heading, ptype in sections:
            pages = await list_wiki_pages(page_type=ptype, limit=500)
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
        await asyncio.to_thread(_atomic_write, path, "\n".join(lines) + "\n")


# ── Helpers (module-private) ─────────────────────────────────────────


def _atomic_write(path: Path, content: str) -> None:
    """Write to ``path.tmp`` then rename — never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _strip_code_fences(text: str) -> str:
    """LLMs sometimes wrap their output in ```markdown ... ```. Peel
    the outermost fence if present so :func:`parse_page` sees the
    raw frontmatter."""
    text = text.strip()
    if text.startswith("```"):
        # Drop opening fence
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text


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
    cleaned = _strip_code_fences(text)
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
    """Call the configured chat model. Lazy-imported so tests with a
    custom invoker never need real LLM credentials at import time."""
    from agents.llm import get_llm
    llm = get_llm(temperature=0.2, max_tokens=DEFAULT_GENERATION_MAX_TOKENS)
    # langchain_openai.ChatOpenAI wants BaseMessage instances; convert
    # cheaply so callers can keep speaking "OpenAI dicts".
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
    resp = await llm.ainvoke(converted)
    return getattr(resp, "content", "") or ""
