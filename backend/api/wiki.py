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
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from config import settings
from storage.metadata_db import (
    WIKI_PAGE_TYPES,
    count_wiki_pages_by_type,
    get_wiki_page,
    graph_neighbors,
    list_wiki_events,
    list_wiki_pages,
    list_wikilinks,
)

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
    edges = await list_wikilinks(limit=1)  # cheap probe — total counted next
    # Total edges is interesting; do one extra fast query.
    from storage.metadata_db import _connect  # local: avoid leaking the helper
    async with _connect() as db:
        async with db.execute("SELECT COUNT(*) FROM wikilinks") as cur:
            row = await cur.fetchone()
            total_edges = int(row[0]) if row else 0

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
) -> dict:
    """Return a list of actionable issues + structural insights.

    Lint is read-only — it never changes pages or edges. The chat
    agent / UI is responsible for surfacing suggestions and asking
    the user before making any edits.
    """
    from wiki.insights import run_lint, graph_insights

    out: list[dict] = []
    if include_lint:
        try:
            issues = await run_lint(data_dir=settings.data_dir)
            out.extend(i.to_dict() for i in issues)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiki insights lint failed: %s", exc)
    if include_graph:
        try:
            issues = await graph_insights(
                knowledge_gap_threshold=knowledge_gap_threshold,
            )
            out.extend(i.to_dict() for i in issues)
        except Exception as exc:  # noqa: BLE001
            logger.warning("wiki insights graph failed: %s", exc)

    # Order: errors first, then warnings, then info — keeps the UI
    # calm by surfacing actionable items at the top.
    severity_order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda d: (severity_order.get(d["severity"], 99), d["kind"]))
    return {"items": out, "count": len(out)}


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
) -> list[DeepResearchTaskOut]:
    from wiki.deep_research import list_recent_tasks
    return [DeepResearchTaskOut(**t.to_dict()) for t in list_recent_tasks(limit)]


@router.get(
    "/research/{task_id}",
    response_model=DeepResearchTaskOut,
    summary="Get the current state of one Deep Research task",
)
async def get_deep_research_task(task_id: str) -> DeepResearchTaskOut:
    from wiki.deep_research import get_task
    task = get_task(task_id)
    if task is None:
        raise HTTPException(404, f"unknown research task: {task_id}")
    return DeepResearchTaskOut(**task.to_dict())
