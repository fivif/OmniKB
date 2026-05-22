from __future__ import annotations

from fastmcp import FastMCP

from config import settings

mcp = FastMCP("OmniKB")


# ── Tool definitions ──────────────────────────────────────────

@mcp.tool()
async def search_kb(
    query: str,
    top_k: int = 10,
    filter_source: str | None = None,
) -> list[dict]:
    """Search the knowledge base with hybrid semantic + BM25 retrieval."""
    from mcp_server.tools import search_kb as _fn
    return await _fn(query, top_k=top_k, filter_source=filter_source)


@mcp.tool()
async def ask_kb(question: str, context_k: int = 5) -> dict:
    """Retrieve the most relevant context for a question from the knowledge base."""
    from mcp_server.tools import ask_kb as _fn
    return await _fn(question, context_k=context_k)


@mcp.tool()
async def ingest_url(
    url: str,
    title: str | None = None,
    tags: list[str] | None = None,
    mode: str = "auto",
) -> dict:
    """Fetch and ingest a web page URL into the knowledge base.

    Choose *mode* to control the fetch strategy:
    - ``'auto'`` / ``'static'`` — scrapling static + httpx fallback (default, fast)
    - ``'dynamic'`` / ``'stealth'`` — Playwright-based rendering (JS-heavy pages)
    - ``'agent_browser'`` — agent-browser CLI (SPA, scroll-to-load, interactive)
    - ``'jshook'`` — jshookmcp CDP browser (anti-bot, network capture, deep JS)
    """
    from mcp_server.tools import ingest_url_tool
    return await ingest_url_tool(url, tags=tags, mode=mode)


@mcp.tool()
async def ingest_text(
    content: str,
    title: str = "Untitled",
    tags: list[str] | None = None,
) -> dict:
    """Ingest raw text content into the knowledge base."""
    from mcp_server.tools import ingest_text_tool
    return await ingest_text_tool(content, title=title, tags=tags)


@mcp.tool()
async def list_sources(limit: int = 20, offset: int = 0) -> list[dict]:
    """List all sources currently in the knowledge base."""
    from mcp_server.tools import list_sources_tool
    return await list_sources_tool(limit=limit, offset=offset)


@mcp.tool()
async def get_chunk(chunk_id: str) -> dict | None:
    """Retrieve a specific knowledge base chunk by its ID."""
    from mcp_server.tools import get_chunk_tool
    return await get_chunk_tool(chunk_id)


@mcp.tool()
async def browser_fetch(
    url: str,
    mode: str = "agent_browser",
    max_chars: int = 8000,
) -> dict:
    """Fetch a web page and return its text content (without ingesting).

    Use this to read real-time web content in chat responses or preview
    a page before ingesting.

    *mode* values: ``'agent_browser'`` (default), ``'jshook'``, ``'stealth'``,
    ``'dynamic'``, ``'static'``.
    """
    from mcp_server.tools import browser_fetch_tool
    return await browser_fetch_tool(url, mode=mode, max_chars=max_chars)


@mcp.tool()
async def search_wiki(query: str, top_k: int = 5) -> list[dict]:
    """Search the L2 wiki layer for entity / concept / source / query pages.

    Returns the highest-scoring pages by tokenised title + summary +
    tag matching. Use this when an external agent wants synthesised
    knowledge over multiple sources rather than raw chunks.

    Each hit contains ``page_id``, ``page_type``, ``title``, ``summary``,
    ``score``, and which query tokens matched. Call ``read_wiki_page``
    next to fetch the full markdown body.

    Returns ``[]`` when the L2 layer has no relevant pages — the caller
    can then fall back to ``search_kb`` (chunks).
    """
    from wiki.retriever import search_wiki_pages
    hits = await search_wiki_pages(query=query, top_k=max(1, min(top_k, 50)))
    return [h.to_dict() for h in hits]


@mcp.tool()
async def read_wiki_page(page_id: str) -> dict:
    """Fetch the full body + metadata of a wiki page by id.

    ``page_id`` follows ``<type>:<slug>``, e.g. ``entity:andrej-karpathy``.
    Use after :func:`search_wiki` finds a candidate, or when the caller
    already has an id from ``list_wiki_pages`` / ``graph_neighbors``.

    Returns ``{"id", "title", "page_type", "frontmatter", "source_ids",
    "revision", "body"}``. Body is empty when the page metadata exists
    but the wiki worker has not yet generated content (fresh ingest).
    """
    from wiki.retriever import read_page_body
    row, body = await read_page_body(page_id, data_dir=settings.data_dir)
    if row is None:
        return {"error": f"unknown wiki page id: {page_id!r}"}
    return {
        "id":          row["id"],
        "title":       row["title"],
        "page_type":   row["page_type"],
        "frontmatter": row.get("frontmatter") or {},
        "source_ids":  row.get("source_ids") or [],
        "revision":    row["revision"],
        "body":        body or "",
    }


@mcp.tool()
async def list_wiki_pages(
    page_type: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Browse wiki pages, optionally filtered by type.

    ``page_type`` ∈ ``entity | concept | source | query | overview``.
    Returns lightweight metadata (no body) — call ``read_wiki_page``
    to drill in.
    """
    from storage.metadata_db import list_wiki_pages as _list, WIKI_PAGE_TYPES
    if page_type is not None and page_type not in WIKI_PAGE_TYPES:
        return [{"error": f"unknown page_type {page_type!r}; expected one of {list(WIKI_PAGE_TYPES)}"}]
    rows = await _list(page_type=page_type, limit=max(1, min(limit, 200)))
    # Strip frontmatter to keep the payload small for MCP transports.
    return [
        {
            "id":         r["id"],
            "page_type":  r["page_type"],
            "slug":       r["slug"],
            "title":      r["title"],
            "summary":    r.get("summary") or "",
            "tags":       (r.get("frontmatter") or {}).get("tags") or [],
            "updated_at": r["updated_at"],
            "revision":   r["revision"],
        }
        for r in rows
    ]


@mcp.tool()
async def graph_neighbors(page_id: str, hops: int = 1) -> dict:
    """Return the wiki neighbourhood around a page.

    Performs a breadth-first walk up to ``hops`` away (max 4) over
    the ``[[wikilink]]`` graph and returns ``{"nodes", "edges"}``
    suitable for client-side graph visualisation. Use to discover
    what's connected to a known page (related concepts, source-of
    relationships, contradictions).
    """
    from storage.metadata_db import graph_neighbors as _gn
    if not page_id:
        return {"nodes": [], "edges": []}
    return await _gn(page_id, hops=max(1, min(int(hops), 4)))


@mcp.tool()
async def deep_research(
    page_id: str,
    focus: str = "",
    max_urls: int = 3,
    wait: bool = True,
    poll_interval_s: float = 1.0,
    timeout_s: float = 240.0,
) -> dict:
    """Autonomously enrich a wiki page from the open web.

    Runs the Deep Research orchestrator on ``page_id`` (canonical
    ``<type>:<slug>`` form). The orchestrator:

    1. Plans 3-5 web search queries from the page's title + summary
       + tags + body excerpt (steered by ``focus`` if given).
    2. Searches DuckDuckGo (no API key required) for each query.
    3. Investigates the top ``max_urls`` URLs in parallel via the
       existing web research agent (Plan → Execute → Verify).
    4. Synthesises one new ``## Recent Research (YYYY-MM-DD)`` section
       and APPENDS it to the page — never overwrites existing content.
    5. Records new ``[[wikilink]]`` edges and a ``wiki_event`` row.

    Parameters
    ----------
    page_id:
        Canonical id, e.g. ``"entity:andrej-karpathy"``.
    focus:
        Optional free-text steer. Examples: ``"education work since 2024"``,
        ``"comparison with peers"``, ``"open critiques"``.
    max_urls:
        How many URLs to actually dig into (1-6, default 3). Cost scales
        roughly linearly with this number — keep it small unless the page
        is high-value.
    wait:
        When ``True`` (default), blocks until the task finishes and returns
        the full result. When ``False``, kicks off in the background and
        returns the task handle immediately (poll via the
        ``GET /wiki/research/{task_id}`` HTTP endpoint).
    poll_interval_s / timeout_s:
        Polling tunables when ``wait=True``. The orchestrator's per-URL
        budget caps individual research calls; this is a safety lid for
        the whole task.
    """
    from wiki.deep_research import kickoff_research, get_task

    if not page_id or ":" not in page_id:
        return {"error": "page_id must be of the form '<type>:<slug>'"}
    if max_urls < 1 or max_urls > 6:
        return {"error": "max_urls must be between 1 and 6"}

    task = await kickoff_research(
        page_id=page_id,
        focus=focus,
        data_dir=settings.data_dir,
        max_urls=max_urls,
    )

    if not wait:
        return task.to_dict()

    # Poll until terminal state or timeout. The background asyncio.Task
    # writes status into the in-process _TASKS dict (and asynchronously
    # to the wiki_research_task table); get_task transparently falls
    # back to the DB so this loop also works when the MCP client lives
    # in a different process from the worker.
    import asyncio
    deadline = asyncio.get_event_loop().time() + max(5.0, float(timeout_s))
    interval = max(0.2, float(poll_interval_s))
    while True:
        snap = await get_task(task.task_id)
        if snap is None:
            return {"error": "task lost from registry", "task_id": task.task_id}
        if snap.status in ("done", "failed", "abandoned"):
            return snap.to_dict()
        if asyncio.get_event_loop().time() >= deadline:
            return {
                **snap.to_dict(),
                "warning": "MCP timeout reached; task still running. "
                           f"Poll GET /wiki/research/{snap.task_id} for final state.",
            }
        await asyncio.sleep(interval)


@mcp.tool()
async def jshook_call(tool_name: str, arguments: dict) -> dict:
    """Call any jshookmcp tool directly for advanced browser/JS analysis.

    jshookmcp provides 387+ tools across 36 domains:
    browser automation, CDP debugging, network interception, JS deobfuscation,
    WASM analysis, source map reconstruction, anti-debug bypass, and more.

    Start with ``tool_name='search_tools'`` and ``arguments={'query': '...'}``
    to discover relevant tools. Then call them by name.

    Examples:
    - search tools: ``{'tool_name': 'search_tools', 'arguments': {'query': 'navigate page content'}}``
    - launch browser: ``{'tool_name': 'browser_launch', 'arguments': {}}``
    - navigate: ``{'tool_name': 'page_navigate', 'arguments': {'url': 'https://example.com'}}``
    - evaluate JS: ``{'tool_name': 'page_evaluate', 'arguments': {'expression': 'document.title'}}``
    """
    from mcp_server.tools import jshook_call_tool
    return await jshook_call_tool(tool_name, arguments)


# ── ASGI app factory (SSE, with API-key auth) ─────────────────

def create_mcp_app():
    """Return an ASGI app that wraps the MCP SSE endpoint with Bearer key auth."""
    try:
        from fastmcp.server.http import create_sse_app
        sse_subapp = create_sse_app(mcp, message_path="/messages/", sse_path="/sse")
    except ImportError:
        sse_subapp = mcp.sse_app()

    async def _auth_wrapper(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            expected = f"Bearer {settings.mcp_api_key}"
            if auth != expected:
                from starlette.responses import JSONResponse
                response = JSONResponse(
                    {"detail": "Invalid or missing API key"}, status_code=401
                )
                await response(scope, receive, send)
                return
        await sse_subapp(scope, receive, send)

    return _auth_wrapper
