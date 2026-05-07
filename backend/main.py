from __future__ import annotations
import logging
import os

# Disable TensorFlow backend in HuggingFace transformers before any import
# that might trigger the chain: sentence_transformers → transformers → tensorflow.
# tensorflow 2.16.x was compiled against numpy 1.x and crashes under numpy 2.x.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")

import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings
from storage.file_store import init_file_store
from storage.metadata_db import init_db
from storage.vector_store import init_vector_store
from api import ingest, search, chat, kb
from api import mcp_logs
from api import agent_stream
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
    os.makedirs(settings.data_dir, exist_ok=True)
    await init_db()
    await init_vector_store()
    init_file_store()
    logger.info("OmniKB startup complete")
    yield
    logger.info("OmniKB shutdown")


app = FastAPI(
    title="OmniKB",
    description="Universal AI Knowledge Base Agent",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(McpRateLimiter)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router,   prefix="/ingest",    tags=["ingest"])
app.include_router(search.router,   prefix="/search",    tags=["search"])
app.include_router(chat.router,     prefix="/chat",      tags=["chat"])
app.include_router(kb.router,       prefix="/kb",        tags=["kb"])
app.include_router(mcp_logs.router,    prefix="/mcp/logs",  tags=["mcp"])
app.include_router(agent_stream.router, prefix="/agent",     tags=["agent"])

# MCP SSE endpoint (authenticated)
app.mount("/mcp", create_mcp_app())


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": app.version}


# Serve frontend if present (production mode)
_frontend = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)