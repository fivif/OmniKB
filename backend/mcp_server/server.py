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
) -> dict:
    """Fetch and ingest a web page URL into the knowledge base (scrapling + httpx fallback)."""
    from mcp_server.tools import ingest_url_tool
    return await ingest_url_tool(url, tags=tags)


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
