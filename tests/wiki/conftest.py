"""Shared fixtures + env setup for wiki tests (P1-P5 regression).

This module sets ``DATA_DIR`` / ``SQLITE_PATH`` / ``WIKI_ENABLED`` env
vars **at conftest import time** — before any test module imports
``backend.config`` or ``backend.storage.metadata_db`` — so the pydantic
``Settings`` instance points at a disposable tmp dir instead of the
user's real ``./data`` folder.

Two important wrinkles:

* The backend modules use bare imports like ``from config import settings``
  (because they run with ``backend/`` as cwd at production time). We
  put ``backend/`` on ``sys.path`` here so those imports still resolve
  when pytest runs from the repo root.

* We bring up the DB schema + filesystem **once per session** and use
  unique slugs per test to avoid cross-test contamination. Reloading
  config per-test would reset ``metadata_db._shared_conn`` and break
  the aiosqlite handle reuse — that's why we share state instead.

The wiki worker is disabled (``WIKI_ENABLED=false``); generator tests
inject their own mock LLM and exercise the generator directly.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import pytest


# ── sys.path setup first (so `from config import settings` resolves) ─

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND   = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# ── Env setup must happen before any backend imports ───────────────

_TMP_DIR = tempfile.mkdtemp(prefix="omnikb_wiki_tests_")
os.environ.setdefault("DATA_DIR", _TMP_DIR)
os.environ.setdefault("SQLITE_PATH", os.path.join(_TMP_DIR, "wiki_test.db"))
os.environ.setdefault("QDRANT_LOCAL_PATH", os.path.join(_TMP_DIR, "qdrant_test"))
# Keep transformers off our test imports — wiki tests don't need them
# and importing tf / jax slows the suite by ~3 s.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")
# Disable the worker so it doesn't try to call a real LLM. Generator
# tests construct their own WikiGenerator with a mock invoker.
os.environ.setdefault("WIKI_ENABLED", "false")


# ── Session setup ─────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _wiki_session_setup():
    """Bring up the DB schema + wiki filesystem once per test session."""
    from backend.storage.metadata_db import init_db, close_db
    from backend.wiki.bootstrap import init_wiki_filesystem

    asyncio.run(init_db())
    init_wiki_filesystem(_TMP_DIR)
    yield
    try:
        asyncio.run(close_db())
    except Exception:
        pass
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


# ── Per-test helpers ──────────────────────────────────────────────


@pytest.fixture
def wiki_data_dir() -> str:
    """Read-only handle to the shared session-scope tmp data dir."""
    return _TMP_DIR


@pytest.fixture
def unique_slug() -> str:
    """A test-unique slug suffix so concurrent tests don't collide."""
    return uuid.uuid4().hex[:10]
