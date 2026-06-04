from __future__ import annotations
import logging
import os

# Disable TensorFlow backend in HuggingFace transformers before any import
# that might trigger the chain: sentence_transformers → transformers → tensorflow.
# tensorflow 2.16.x was compiled against numpy 1.x and crashes under numpy 2.x.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")

import time

from config import settings

# HuggingFace mirror — must be set before any fastembed / huggingface_hub import
if settings.hf_endpoint:
    os.environ["HF_ENDPOINT"] = settings.hf_endpoint

# Persistent fastembed cache. Without this, fastembed defaults to
# tempfile.gettempdir() / "fastembed_cache" — on macOS this resolves to
# $TMPDIR (/var/folders/...), which is purged periodically by launchd, and
# on Linux containers /tmp is wiped on every restart. The result is that
# BM25/sparse models redownload every cold start. Anchor the cache to the
# user's persistent ~/.cache/fastembed/ unless the operator overrode it.


def apply_proxy(proxy_url: str) -> None:
    """Set HTTP_PROXY / HTTPS_PROXY in os.environ so httpx/aiohttp use it."""
    if proxy_url:
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["ALL_PROXY"] = proxy_url
    else:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            os.environ.pop(k, None)


apply_proxy(settings.http_proxy)

from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from storage.file_store import init_file_store
from storage.metadata_db import close_db, init_db
from api import ingest, search, chat, kb
from api import kb_api
from api import mcp_logs
from api import agent_stream
from api import metrics
from api import scenarios
from api import settings as settings_api
from api import wiki as wiki_api
from api.auth import AdminAuthMiddleware, router as auth_router
from mcp_server.server import create_mcp_app

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("omnikb")


# ── Rate limiter middleware for /mcp routes ────────────────────

class McpRateLimiter(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter: 60 requests / 60 s per IP for /mcp."""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self._max = max_requests
        self._window = window_seconds
        self._counters: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        ip = (request.client.host if request.client else "unknown")
        now = time.time()
        # Evict stale timestamps
        self._counters[ip] = [
            t for t in self._counters[ip] if now - t < self._window
        ]
        if len(self._counters[ip]) >= self._max:
            return JSONResponse(
                {"detail": f"Rate limit exceeded: {self._max} requests/{self._window}s for /mcp"},
                status_code=429,
                headers={"Retry-After": str(self._window)},
            )
        self._counters[ip].append(now)
        return await call_next(request)


# ── App lifecycle ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configuration self-check — surface drift before request handlers blow up.
    from config import verify_settings
    issues = verify_settings()
    for issue in issues:
        logger.warning("config: %s", issue)
    app.state.config_issues = issues

    os.makedirs(settings.data_dir, exist_ok=True)
    await init_db()
    init_file_store()

    # Wiki layer (L2 secondary index) — bootstrap directory + worker.
    # Bootstrap is idempotent so a wiped data dir auto-heals on next
    # start. The worker stays up for the process lifetime; ingest /
    # MCP / chat code reaches it via app.state.wiki_worker.
    import wiki as _wiki_pkg
    from wiki.bootstrap import init_wiki_filesystem
    from wiki.worker import WikiWorker
    wiki_manifest = init_wiki_filesystem(settings.data_dir)
    if wiki_manifest["created"]:
        logger.info("wiki bootstrap: %d new entries under %s",
                    len(wiki_manifest["created"]), wiki_manifest["wiki_root"])
    app.state.wiki_worker = WikiWorker(settings.data_dir)
    await app.state.wiki_worker.start()
    # Publish to the package-level pointer so producers
    # (agents.orchestrator, MCP tools) can enqueue without reaching
    # into FastAPI's app.state from non-request contexts.
    _wiki_pkg.WORKER = app.state.wiki_worker

    # Global typed-event stream (PC.1) — one shared EventStream for all agent runs.
    # Producers (agent_core.run_loop) publish here; subscribers
    # (GET /agent/v2/events) consume.
    from agent_core.events import EventStream, set_event_stream
    stream = EventStream(max_queue=2000)
    app.state.event_stream = stream
    set_event_stream(stream)

    from agents.web import pool as _pool_mod
    from agents.web.pool import JsHookPool, PlaywrightPool
    app.state.jshook_pool = JsHookPool(size=settings.jshook_pool_size)
    app.state.playwright_pool = PlaywrightPool(size=settings.playwright_pool_size)
    _pool_mod.JSHOOK_POOL = app.state.jshook_pool
    _pool_mod.PLAYWRIGHT_POOL = app.state.playwright_pool
    try:
        await app.state.jshook_pool.start()
    except Exception as exc:
        logger.warning("JsHookPool startup failed (non-fatal): %s", exc)
    if settings.playwright_pool_size > 0:
        try:
            await app.state.playwright_pool.start()
        except Exception as exc:
            logger.warning("PlaywrightPool startup failed (non-fatal): %s", exc)

    # P2: register jshookmcp tools as LangChain StructuredTools
    app.state.jshook_tools = []
    try:
        from agents.web.tools.jshook_dynamic import discover_jshook_tools
        app.state.jshook_tools = await discover_jshook_tools()
    except Exception as exc:
        logger.warning("jshook tool discovery failed (non-fatal): %s", exc)

    # P3: load seed skills if skills table empty
    try:
        from agents.web.tools.memory import load_seed_skills_if_empty
        loaded = await load_seed_skills_if_empty()
        if loaded:
            logger.info("Loaded %d seed skills", loaded)
    except Exception as exc:
        logger.warning("seed skill load failed (non-fatal): %s", exc)

    # Crash recovery: re-queue tasks that were still pending / processing in
    # the database when the previous process exited unexpectedly. Without this
    # zombie tasks would stay "processing" forever after a restart.
    try:
        from api.ingest import resume_pending_tasks
        report = await resume_pending_tasks()
        if report.get("resumed") or report.get("failed"):
            logger.info(
                "Crash recovery: resumed=%d failed=%d",
                report["resumed"], report["failed"],
            )
    except Exception as exc:
        logger.warning("task recovery failed (non-fatal): %s", exc)

    # Same logic for Deep Research tasks: any in-flight task whose
    # owning asyncio.Task died with the previous process is now an
    # orphan. Mark it 'abandoned' so the UI poller settles instead of
    # spinning forever.
    try:
        from storage.metadata_db import abandon_orphaned_research_tasks
        abandoned = await abandon_orphaned_research_tasks()
        if abandoned:
            logger.info("Research recovery: abandoned %d orphaned task(s)", abandoned)
    except Exception as exc:
        logger.warning("research-task recovery failed (non-fatal): %s", exc)

    # Optional: scheduled auto-research worker. Off by default; needs
    # both the master switch AND a non-zero interval.
    app.state.scheduled_research_worker = None
    if (
        getattr(settings, "wiki_auto_research_enabled", False)
        and float(getattr(settings, "wiki_auto_research_interval_hours", 0.0)) > 0.0
    ):
        try:
            from wiki.scheduled_research import ScheduledResearchWorker
            srw = ScheduledResearchWorker(
                settings.data_dir,
                interval_seconds=settings.wiki_auto_research_interval_hours * 3600.0,
                max_per_run=settings.wiki_auto_research_max_per_run,
                cooldown_hours=settings.wiki_auto_research_cooldown_hours,
            )
            await srw.start()
            app.state.scheduled_research_worker = srw
            logger.info(
                "Scheduled research worker started (interval=%.1fh, max=%d, cooldown=%dh)",
                settings.wiki_auto_research_interval_hours,
                settings.wiki_auto_research_max_per_run,
                settings.wiki_auto_research_cooldown_hours,
            )
        except Exception as exc:
            logger.warning("scheduled research worker start failed (non-fatal): %s", exc)

    logger.info("OmniKB startup complete")
    yield

    try:
        await app.state.jshook_pool.stop()
    except Exception as exc:
        logger.debug("JsHookPool stop: %s", exc)
    try:
        await app.state.playwright_pool.stop()
    except Exception as exc:
        logger.debug("PlaywrightPool stop: %s", exc)
    _pool_mod.JSHOOK_POOL = None
    _pool_mod.PLAYWRIGHT_POOL = None
    try:
        await app.state.wiki_worker.stop()
    except Exception as exc:
        logger.debug("wiki worker stop: %s", exc)
    _wiki_pkg.WORKER = None
    if getattr(app.state, "scheduled_research_worker", None) is not None:
        try:
            await app.state.scheduled_research_worker.stop()
        except Exception as exc:
            logger.debug("scheduled research worker stop: %s", exc)
    try:
        await close_db()
    except Exception as exc:
        logger.debug("close_db: %s", exc)
    logger.info("OmniKB shutdown")


app = FastAPI(
    title="OmniKB",
    description="Universal AI Knowledge Base Agent",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(AdminAuthMiddleware)
app.add_middleware(McpRateLimiter)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dev: disable caching for static assets so CSS/JS edits take effect immediately
@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.endswith((".css", ".js", ".html")) or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

app.include_router(ingest.router,   prefix="/ingest",    tags=["ingest"])
app.include_router(search.router,   prefix="/search",    tags=["search"])
app.include_router(chat.router,     prefix="/chat",      tags=["chat"])
app.include_router(kb.router,       prefix="/kb",        tags=["kb"])
app.include_router(mcp_logs.router,    prefix="/mcp/logs",  tags=["mcp"])
app.include_router(agent_stream.router, prefix="/agent",     tags=["agent"])
app.include_router(metrics.router,      prefix="/metrics",   tags=["metrics"])
app.include_router(auth_router,       prefix="/auth",     tags=["auth"])
app.include_router(settings_api.router, prefix="/settings",  tags=["settings"])
app.include_router(scenarios.router,  prefix="/scenarios", tags=["scenarios"])
app.include_router(kb_api.router,    prefix="/kb-api",   tags=["kb-api"])
app.include_router(wiki_api.router)   # /wiki/* — prefix declared on the router itself

# MCP SSE endpoint (authenticated)
app.mount("/mcp", create_mcp_app())


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health", tags=["system"])
async def health():
    """Liveness probe + lightweight config diagnostics.

    Reports ``config_issues`` (list of strings) so operators can spot drift
    without grepping startup logs. Secrets are never echoed back.
    """
    return {
        "status": "ok",
        "version": app.version,
        "config_issues": getattr(app.state, "config_issues", []),
    }


@app.get("/health/config", tags=["system"])
async def health_config():
    """Return the full redacted configuration (secrets masked).

    Useful when debugging an install: shows exactly which provider,
    base URL, and feature flags are in effect, with API keys reduced to
    a 4-char prefix.
    """
    from config import redacted_settings, verify_settings
    return {
        "settings": redacted_settings(),
        "issues": verify_settings(),
    }


# Serve frontend if present (production mode)
_frontend = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend):
    from fastapi.responses import FileResponse

    @app.get("/admin", tags=["system"])
    async def admin_spa():
        """Serve the management SPA at /admin."""
        return FileResponse(os.path.join(_frontend, "index.html"))

    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("OMNIKB_HOST", "0.0.0.0")
    port = int(os.environ.get("OMNIKB_PORT", "6886"))
    uvicorn.run(app, host=host, port=port)