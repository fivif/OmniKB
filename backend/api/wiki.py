"""HTTP API for the L2 wiki layer.

Routes
------
- GET  /wiki/stats                  counts by page_type + worker queue stats
- GET  /wiki/pages                  list pages (filter by type, paginated)
- GET  /wiki/pages/{page_id}        fetch one page (metadata + body markdown)
- GET  /wiki/graph                  node + edge dump for the graph view
- GET  /wiki/graph/{page_id}        BFS neighbourhood around a single page
- GET  /wiki/events                 recent worker events (latest first)
- GET  /wiki/insights               lint + structural issues for the curator UI
- POST /wiki/research               kick off Deep Research on one page (async)
- GET  /wiki/research               list recent research tasks (for UI poll)
- GET  /wiki/research/{task_id}     status + result of one research task
- POST /wiki/sync                   trigger wiki generation for selected sources
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from config import settings
from storage.metadata_db import (
    WIKI_PAGE_TYPES,
    count_wiki_pages_by_type,
    count_wikilinks,
    get_source,
    get_wiki_page,
    graph_neighbors,
    list_chunks_by_source,
    list_wiki_events,
    list_wiki_pages,
    list_wikilinks,
    upsert_wiki_page,
)
from wiki.parser import slugify

router = APIRouter(prefix="/wiki", tags=["wiki"])
logger = logging.getLogger(__name__)


# ── Response models ───────────────────────────────────────────────────


class WikiStats(BaseModel):
    page_counts: dict[str, int]
    total_pages: int
    total_edges: int
    worker: dict[str, int] | None


class WikiPageOut(BaseModel):
    id: str
    page_type: str
    slug: str
    title: str
    file_path: str
    summary: str
    frontmatter: dict
    source_ids: list[str]
    created_at: str
    updated_at: str
    revision: int
    body: str | None = None  # populated only on the single-page endpoint


class WikiEdge(BaseModel):
    src_page_id: str
    dst_page_id: str
    relation: str
    weight: float


class WikiGraph(BaseModel):
    nodes: list[WikiPageOut]
    edges: list[WikiEdge]


class WikiSyncRequest(BaseModel):
    source_ids: list[str]


class WikiSyncResponse(BaseModel):
    task_id: str
    accepted: int
    rejected: int


# ── Helpers ──────────────────────────────────────────────────────────


def _read_body(file_path: str) -> str | None:
    """Read a wiki page body off disk. Returns None on any I/O error so
    the API stays useful even when the filesystem is partially populated
    (e.g. DB row exists but P2 hasn't written the markdown yet)."""
    p = Path(settings.data_dir).expanduser() / file_path
    try:
        if not p.is_file():
            return None
        # Cap at ~512 KB to keep responses bounded; very large pages
        # would mean we picked the wrong abstraction anyway.
        return p.read_text(encoding="utf-8")[:524_288]
    except OSError as exc:
        logger.debug("wiki body read failed for %s: %s", file_path, exc)
        return None


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/stats", response_model=WikiStats)
async def wiki_stats(request: Request) -> WikiStats:
    counts = await count_wiki_pages_by_type()
    total_edges = await count_wikilinks()

    worker_stats: dict[str, int] | None = None
    w = getattr(request.app.state, "wiki_worker", None)
    if w is not None:
        worker_stats = w.stats()

    return WikiStats(
        page_counts=counts,
        total_pages=sum(counts.values()),
        total_edges=total_edges,
        worker=worker_stats,
    )


@router.get("/pages", response_model=list[WikiPageOut])
async def list_pages(
    page_type: str | None = Query(None, description=f"one of {list(WIKI_PAGE_TYPES)}"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[WikiPageOut]:
    if page_type is not None and page_type not in WIKI_PAGE_TYPES:
        raise HTTPException(400, f"unknown page_type {page_type!r}")
    rows = await list_wiki_pages(page_type=page_type, limit=limit, offset=offset)
    # Body intentionally omitted from list view — keep the payload light.
    return [WikiPageOut(**row) for row in rows]


@router.get("/pages/{page_id:path}", response_model=WikiPageOut)
async def get_page(page_id: str) -> WikiPageOut:
    row = await get_wiki_page(page_id)
    if row is None:
        raise HTTPException(404, f"wiki page not found: {page_id}")
    body = _read_body(row["file_path"])
    return WikiPageOut(**row, body=body)


@router.get("/graph", response_model=WikiGraph)
async def whole_graph(
    edge_limit: int = Query(2000, ge=1, le=10000),
    page_limit: int = Query(500, ge=1, le=5000),
) -> WikiGraph:
    """Return the entire graph (node + edge tables) up to safe limits.

    Frontends should switch to ``/wiki/graph/{page_id}`` once the graph
    crosses the limits — at that scale full rendering is unusable
    anyway.
    """
    pages = await list_wiki_pages(limit=page_limit)
    edges = await list_wikilinks(limit=edge_limit)
    return WikiGraph(
        nodes=[WikiPageOut(**p) for p in pages],
        edges=[WikiEdge(**e) for e in edges],
    )


@router.get("/graph/{page_id:path}", response_model=WikiGraph)
async def neighbourhood(
    page_id: str,
    hops: int = Query(1, ge=1, le=4),
) -> WikiGraph:
    g = await graph_neighbors(page_id, hops=hops)
    if not g["nodes"]:
        raise HTTPException(404, f"wiki page not found: {page_id}")
    return WikiGraph(
        nodes=[WikiPageOut(**p) for p in g["nodes"]],
        edges=[WikiEdge(**e) for e in g["edges"]],
    )


@router.get("/events")
async def recent_events(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    return await list_wiki_events(limit=limit)


@router.get("/insights")
async def insights(
    include_lint: bool = Query(True, description="run page-level health scan"),
    include_graph: bool = Query(True, description="run structural graph analysis"),
    knowledge_gap_threshold: int = Query(1, ge=0, le=10),
    auto_research: bool = Query(
        False,
        description=(
            "If true and WIKI_AUTO_RESEARCH_ENABLED, dispatch Deep "
            "Research kickoffs for any knowledge_gap pages not in "
            "cooldown. Returns the dispatch report under 'auto_research'."
        ),
    ),
) -> dict:
    """Return a list of actionable issues + structural insights.

    Lint is read-only — it never changes pages or edges. The chat
    agent / UI is responsible for surfacing suggestions and asking
    the user before making any edits.

    When ``auto_research=true`` AND the global
    ``WIKI_AUTO_RESEARCH_ENABLED`` setting is on, the endpoint
    additionally fire-and-forget kicks off Deep Research jobs against
    any ``knowledge_gap`` pages not in cooldown. Both gates must agree
    before any work is dispatched.
    """
    from wiki.insights import run_lint, graph_insights

    out: list[dict] = []
    raw_issues: list = []  # kept around for the auto-research dispatcher
    if include_lint:
        try:
            issues = await run_lint(data_dir=settings.data_dir)
            raw_issues.extend(issues)
            out.extend(i.to_dict() for i in issues)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiki insights lint failed: %s", exc)
    if include_graph:
        try:
            issues = await graph_insights(
                knowledge_gap_threshold=knowledge_gap_threshold,
            )
            raw_issues.extend(issues)
            out.extend(i.to_dict() for i in issues)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiki insights graph failed: %s", exc)

    # Order: errors first, then warnings, then info — keeps the UI
    # calm by surfacing actionable items at the top.
    severity_order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda d: (severity_order.get(d["severity"], 99), d["kind"]))
    response: dict = {"items": out, "count": len(out)}

    # Auto-dispatch Deep Research from knowledge_gap items, if both
    # the per-call flag and the global setting say yes.
    if auto_research and settings.wiki_auto_research_enabled and raw_issues:
        try:
            from wiki.insights import auto_dispatch_from_gaps
            report = await auto_dispatch_from_gaps(
                raw_issues,
                data_dir=settings.data_dir,
                max_per_run=settings.wiki_auto_research_max_per_run,
                cooldown_hours=settings.wiki_auto_research_cooldown_hours,
            )
            response["auto_research"] = report
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto-research dispatch failed: %s", exc)
            response["auto_research"] = {"error": str(exc)}
    elif auto_research and not settings.wiki_auto_research_enabled:
        response["auto_research"] = {
            "error": "WIKI_AUTO_RESEARCH_ENABLED is false; refusing to dispatch.",
        }

    return response


# ── Save Chat to Wiki ────────────────────────────────────────────────


class SaveToWikiRequest(BaseModel):
    title: str
    content: str


@router.post("/save-chat", response_model=WikiPageOut, status_code=201)
async def save_chat_to_wiki(req: SaveToWikiRequest):
    """Save a chat response as a new query-type wiki page."""
    slug = slugify(req.title)
    if slug == "unnamed":
        slug = f"query-{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"
    page_id = f"query:{slug}"
    now = datetime.now(timezone.utc).isoformat()

    # Check if page already exists
    existing = await get_wiki_page(page_id)
    if existing:
        # Append as new section
        new_body = existing.get("body", "") + "\n\n---\n\n## Saved Answer\n\n" + req.content
        await upsert_wiki_page({
            "id": page_id, "page_type": "query", "slug": slug, "title": req.title,
            "file_path": f"wiki/queries/{slug}.md", "summary": req.content[:200],
            "frontmatter": json.dumps({"tags": ["saved-chat"], "aliases": []}),
            "source_ids": json.dumps([]), "body": new_body,
            "created_at": existing.get("created_at", now), "updated_at": now,
            "revision": existing.get("revision", 1) + 1,
        })
    else:
        await upsert_wiki_page({
            "id": page_id, "page_type": "query", "slug": slug, "title": req.title,
            "file_path": f"wiki/queries/{slug}.md", "summary": req.content[:200],
            "frontmatter": json.dumps({"tags": ["saved-chat"], "aliases": []}),
            "source_ids": json.dumps([]), "body": req.content,
            "created_at": now, "updated_at": now, "revision": 1,
        })
    return await get_wiki_page(page_id)


# ── Deep Research ────────────────────────────────────────────────────


class DeepResearchRequest(BaseModel):
    """Body for ``POST /wiki/research``.

    The ``page_id`` is the canonical ``"<type>:<slug>"`` key. ``focus``
    is an optional free-text steering hint surfaced to the LLM during
    query planning + final synthesis. ``max_urls`` caps how many URLs
    we actually fetch + research; defaults to 3 to keep wallet damage
    low for opportunistic enrichments triggered from the UI.
    """
    page_id:  str
    focus:    str = ""
    max_urls: int = 3


class DeepResearchTaskOut(BaseModel):
    """Mirrors ``ResearchTask.to_dict``. Fields stay loose so progress
    metadata is forward-compatible without an API version bump."""
    task_id:     str
    page_id:     str
    focus:       str
    status:      str
    phase_note:  str
    created_at:  float
    finished_at: float | None
    result:      dict | None
    error:       str | None


@router.post(
    "/research",
    response_model=DeepResearchTaskOut,
    status_code=202,
    summary="Kick off autonomous Deep Research enrichment for one page",
)
async def kickoff_deep_research(req: DeepResearchRequest) -> DeepResearchTaskOut:
    """Start a Deep Research task in the background.

    Returns immediately (202 Accepted) with a task handle. The UI is
    expected to poll ``GET /wiki/research/{task_id}`` for progress.
    """
    if not req.page_id or ":" not in req.page_id:
        raise HTTPException(400, "page_id must be of the form '<type>:<slug>'")

    # Validate that the page exists *before* spawning the background
    # task — surfaces "wrong page id" as a synchronous 404 rather than
    # an opaque "task failed" message a few seconds later.
    row = await get_wiki_page(req.page_id)
    if row is None:
        raise HTTPException(404, f"wiki page not found: {req.page_id}")

    # Bound max_urls — even 6 means the orchestrator spawns 6 parallel
    # web/loop runs, each of which can fan out many tool calls. Past
    # that, latency + token cost scale faster than usefulness.
    if req.max_urls < 1 or req.max_urls > 6:
        raise HTTPException(400, "max_urls must be between 1 and 6")

    from wiki.deep_research import kickoff_research

    task = await kickoff_research(
        page_id=req.page_id,
        focus=req.focus,
        data_dir=settings.data_dir,
        max_urls=req.max_urls,
    )
    return DeepResearchTaskOut(**task.to_dict())


@router.get(
    "/research",
    response_model=list[DeepResearchTaskOut],
    summary="List recent Deep Research tasks (most recent first)",
)
async def list_deep_research_tasks(
    limit: int = Query(20, ge=1, le=200),
    page_id: str | None = Query(None, description="Optional page filter"),
) -> list[DeepResearchTaskOut]:
    from wiki.deep_research import list_recent_tasks
    tasks = await list_recent_tasks(limit, page_id=page_id)
    return [DeepResearchTaskOut(**t.to_dict()) for t in tasks]


@router.get(
    "/research/{task_id}",
    response_model=DeepResearchTaskOut,
    summary="Get the current state of one Deep Research task",
)
async def get_deep_research_task(task_id: str) -> DeepResearchTaskOut:
    from wiki.deep_research import get_task
    task = await get_task(task_id)
    if task is None:
        raise HTTPException(404, f"unknown research task: {task_id}")
    return DeepResearchTaskOut(**task.to_dict())


# ── Wiki Sync ────────────────────────────────────────────────────────


@router.post("/sync", response_model=WikiSyncResponse, status_code=202)
async def sync_sources(req: WikiSyncRequest):
    """Trigger wiki generation for selected knowledge base sources.

    Runs in background. The caller receives an immediate 202 with a
    task_id that can be used to track progress in the Agent Console.
    """
    task_id = f"wiki-sync-{uuid.uuid4().hex[:12]}"
    accepted = 0
    rejected = 0

    # Validate sources exist and have raw text (chunks table removed)
    valid_ids = []
    for sid in req.source_ids:
        src = await get_source(sid)
        if src is None:
            rejected += 1
            continue
        # Read raw text from tasks table (chunks table was removed)
        raw = await _read_source_text(sid)
        if not raw:
            rejected += 1
            continue
        valid_ids.append(sid)
        accepted += 1

    if valid_ids:
        asyncio.create_task(_run_wiki_sync(task_id, valid_ids))

    return WikiSyncResponse(task_id=task_id, accepted=accepted, rejected=rejected)


async def _read_source_text(source_id: str) -> str:
    """Read raw text from the tasks table for a given source_id."""
    import sqlite3, json
    try:
        db_path = str(Path(settings.data_dir) / "omnikb.db")
        _db = sqlite3.connect(db_path)
        _row = _db.execute(
            "SELECT params_json FROM tasks WHERE source_id = ? AND params_json IS NOT NULL ORDER BY rowid DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        _db.close()
        if _row:
            _params = json.loads(_row[0]) if _row[0] else {}
            return _params.get("content", "")
    except Exception:
        pass
    return ""


async def _run_wiki_sync(task_id: str, source_ids: list[str]) -> None:
    """Background: fetch source text and run wiki generator for each source."""
    from wiki.generator import WikiGenerator
    from agent_core.events import AgentEvent, get_event_stream
    from utils.agent_bus import emit

    logger = logging.getLogger(__name__)
    gen = WikiGenerator(settings.data_dir)
    total_created = 0
    total_updated = 0
    total_failed = 0
    failed_sources: list[dict] = []

    # Publish batch start
    try:
        stream = get_event_stream()
        await stream.publish(AgentEvent(
            type="wiki_batch_start",
            task_id=task_id,
            data={"source_count": len(source_ids)},
        ))
    except Exception:
        pass

    # Emit to v1 agent_bus for Agent Console visibility
    try:
        emit(f"📝 Wiki 同步: {len(source_ids)} 个来源", kind="progress", agent="wiki", task_id=task_id)
    except Exception:
        pass

    for sid in source_ids:
        src = await get_source(sid)
        if src is None:
            continue
        source_text = await _read_source_text(sid)
        if not source_text:
            continue

        # Emit per-source progress to Agent Console
        try:
            emit(f"🧠 Wiki 生成: {src.get('name', sid)[:50]}", kind="progress", agent="wiki", task_id=task_id)
        except Exception:
            pass
        source_name = src.get("name", sid)
        meta = {
            "title": source_name,
            "type": src.get("type", "unknown"),
            "source_url": src.get("url", ""),
            "tags": src.get("tags", []),
        }
        try:
            result = await gen.generate(
                source_id=sid,
                source_text=source_text,
                source_metadata=meta,
                task_id=task_id,
            )
            if result.error:
                total_failed += 1
                failed_sources.append({"source_id": sid, "name": source_name, "error": result.error})
                logger.warning("wiki sync: source %s analysis failed: %s", sid, result.error)
            else:
                total_created += result.pages_created
                total_updated += result.pages_updated
                total_failed += result.pages_failed
                if result.pages_failed > 0:
                    failed_sources.append({
                        "source_id": sid, "name": source_name,
                        "error": f"{result.pages_failed} page(s) failed during generation",
                    })
        except Exception as exc:
            total_failed += 1
            failed_sources.append({"source_id": sid, "name": source_name, "error": f"{type(exc).__name__}: {exc}"})
            logger.exception("wiki sync failed for source %s: %s", sid, exc)

    # Publish batch complete
    try:
        stream = get_event_stream()
        await stream.publish(AgentEvent(
            type="wiki_sync_complete",
            task_id=task_id,
            data={
                "total_sources": len(source_ids),
                "total_created": total_created,
                "total_updated": total_updated,
                "total_failed": total_failed,
                "failed_sources": failed_sources,
            },
        ))
    except Exception:
        pass

    # Emit completion to Agent Console
    try:
        if total_failed > 0:
            failed_names = ", ".join(f["name"] for f in failed_sources[:3])
            if len(failed_sources) > 3:
                failed_names += f" 等 {len(failed_sources)} 个来源"
            emit(f"⚠️ Wiki 完成: {total_created} 创建 / {total_updated} 更新 / {total_failed} 失败 — {failed_names}",
                kind="warning", agent="wiki", task_id=task_id)
        else:
            emit(f"✅ Wiki 完成: {total_created} 创建 / {total_updated} 更新",
                kind="success", agent="wiki", task_id=task_id)
    except Exception:
        pass
