"""FastEmbed BM25 sparse embedder.

Wraps the existing fastembed-managed ``Qdrant/bm25`` model. Same
soft-fail behaviour as before: when HuggingFace is unreachable the
embedder reports unavailable and ``embed()`` returns empty
``([], [])`` tuples so retrieval falls back to dense-only without
the call site having to know.

Extracted from the legacy ``pipeline/embedder.py``. Three pieces of
state survive the refactor as instance attrs (previously module
globals):

* ``_model`` — the SparseTextEmbedding instance, ``False`` if the
  download failed (sentinel deliberately distinct from ``None`` so
  we don't loop trying again on every call), or ``None`` before the
  first attempt.
* ``_downloading`` — set while the first lazy load is in progress so
  the API status endpoint can render ``"downloading"``.
* ``_download_lock`` — guards against concurrent ``_bg_download``
  calls when the user clicks the manual-download button twice.

The ``_bg_download`` and ``is_cached`` helpers are kept with
substantively identical semantics — the API surface in
``pipeline/embedder.py`` exposes them as ``_bm25_bg`` /
``is_bm25_cached`` for back-compat.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FastEmbedBM25SparseEmbedder:
    """Lazy-loaded fastembed BM25 sparse embedder.

    Soft-fail by design: when the model isn't available, ``embed``
    returns empty vectors instead of raising — retrieval gracefully
    drops to dense-only.
    """

    MODEL_NAME = "Qdrant/bm25"

    def __init__(self, fastembed_cache_path: str = "") -> None:
        self.name = "fastembed:bm25"
        self._cache_path_setting = fastembed_cache_path
        self._model: Any | None | bool = None  # None=untried, False=failed, else loaded
        self._downloading = False
        self._download_lock = False  # bool, not threading.Lock — see _bg_download

    # ── helpers ───────────────────────────────────────────────

    def _resolve_cache_dir(self) -> str:
        """Persistent cache directory for the BM25 model.

        Resolution order matches the legacy implementation exactly:

        1. ``FASTEMBED_CACHE_PATH`` env var (``main.py`` may set this
           before fastembed imports anything, which is the only way to
           override fastembed's ``$TMPDIR`` default reliably).
        2. The ``fastembed_cache_path`` injected at construction.
        3. ``~/.cache/fastembed`` — stable user-local default,
           survives reboots (unlike ``$TMPDIR``).
        """
        env_path = os.environ.get("FASTEMBED_CACHE_PATH", "").strip()
        if env_path:
            return env_path
        if self._cache_path_setting:
            return self._cache_path_setting
        return str(Path.home() / ".cache" / "fastembed")

    def is_cached(self) -> bool:
        """True if the BM25 model is already on disk (no download needed).

        Checks the SAME directory fastembed actually writes to —
        getting this wrong (e.g. checking ``~/.cache/huggingface/hub``)
        silently re-downloads the model on every restart.
        """
        root = Path(self._resolve_cache_dir())
        if not root.is_dir():
            return False
        target = root / "models--Qdrant--bm25"
        if target.is_dir():
            try:
                # Targeted check for a known HF cache marker instead of
                # ``rglob("*")`` which walks the entire directory tree.
                return (target / "refs" / "main").is_file()
            except Exception:  # noqa: BLE001
                return True
        # Fallback heuristic for older fastembed cache layouts.
        try:
            for child in root.iterdir():
                n = child.name.lower()
                if "qdrant" in n and "bm25" in n and child.is_dir():
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _try_load(self) -> Any | None:
        """Load the model, returning the instance or ``None`` on failure."""
        from fastembed import SparseTextEmbedding
        kwargs: dict[str, Any] = {"cache_dir": self._resolve_cache_dir()}
        if self.is_cached():
            # If model is cached locally, force offline mode so unreachable
            # huggingface.co doesn't kill us.
            kwargs["local_files_only"] = True
        return SparseTextEmbedding(model_name=self.MODEL_NAME, **kwargs)

    # ── public API (Protocol) ─────────────────────────────────

    @property
    def is_available(self) -> bool:
        return self._model is not None and self._model is not False

    def embed(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        """Sparse-embed *texts*. Empty tuples on soft-fail."""
        model = self._ensure_loaded()
        if model is None:
            return [([], []) for _ in texts]
        results: list[tuple[list[int], list[float]]] = []
        for emb in model.embed(texts):
            results.append((emb.indices.tolist(), emb.values.tolist()))
        return results

    # ── internals & legacy hooks ──────────────────────────────

    def _ensure_loaded(self) -> Any | None:
        """Lazy load. Returns the model instance or None when unavailable."""
        if self._model is False:
            return None
        if self._model is not None:
            return self._model
        # First attempt — try to load. Mark _downloading so the status
        # endpoint can show progress.
        self._downloading = True
        try:
            self._model = self._try_load()
            logger.info(
                "BM25 model loaded (cache=%s, offline=%s)",
                self._resolve_cache_dir(),
                self.is_cached(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "BM25 model unavailable (huggingface.co unreachable). "
                "Sparse search disabled — falling back to dense-only. "
                "Configure a proxy in Settings or set HF_ENDPOINT. Error: %s",
                exc,
            )
            self._model = False
            return None
        return self._model if self._model is not False else None

    def background_download(self, timeout_seconds: float = 15.0) -> None:
        """Trigger a synchronous (blocking) download with a timeout.

        Called from the ``/settings/models/download`` endpoint via the
        executor. The legacy module function ``_bm25_bg`` delegates here.
        Idempotent — concurrent calls are coalesced via ``_download_lock``.
        """
        import threading

        if self._download_lock:
            return
        self._download_lock = True
        try:
            result: list[Any] = [None]

            def _download() -> None:
                from fastembed import SparseTextEmbedding
                try:
                    result[0] = SparseTextEmbedding(
                        model_name=self.MODEL_NAME,
                        cache_dir=self._resolve_cache_dir(),
                    )
                except Exception:  # noqa: BLE001
                    pass

            t = threading.Thread(target=_download, daemon=True)
            t.start()
            t.join(timeout=timeout_seconds)

            # Don't clobber a successful concurrent ``_ensure_loaded``.
            if self.is_available:
                return
            if result[0] is not None:
                self._model = result[0]
                self._downloading = True
                logger.info("BM25 model loaded successfully (background)")
            else:
                self._model = False
                self._downloading = False
                logger.warning(
                    "BM25 download timed out (%.1fs) — sparse search disabled",
                    timeout_seconds,
                )
        finally:
            self._download_lock = False
