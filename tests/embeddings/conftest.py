"""Shared fixtures + env setup for embedding factory tests.

These tests don't touch the SQLite DB or the wiki filesystem — they
exercise the in-memory factory + Protocol implementations only — so
this conftest is much smaller than ``tests/wiki/conftest.py``. Just
two responsibilities:

1. Put ``backend/`` on ``sys.path`` so ``from config import settings``
   and ``from pipeline.embeddings`` resolve when pytest runs from the
   repo root.

2. Reset the factory's process-cached singletons before each test
   (the factory is module-level state; without this, ordering between
   tests would leak the dense / sparse / reranker instances).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# Put backend/ on sys.path BEFORE any backend import.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND   = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Keep tensorflow / jax out of test imports — sentence-transformers
# would otherwise pull them in transitively and add ~3 s of startup.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")
# Avoid hitting the real network during tests.
os.environ.setdefault("HF_HUB_OFFLINE", "1")


@pytest.fixture(autouse=True)
def _reset_factory_cache():
    """Drop cached embedder/reranker singletons before AND after each test.

    The factory caches one instance per type process-wide. Without
    this fixture, an earlier test's mock embedder would leak into the
    next test's factory call, masking real wiring bugs.
    """
    from pipeline.embeddings import factory as fac
    fac._dense = None
    fac._sparse = None
    fac._reranker = None
    fac._reranker_resolved = False
    yield
    fac._dense = None
    fac._sparse = None
    fac._reranker = None
    fac._reranker_resolved = False
