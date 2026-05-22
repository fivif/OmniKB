"""Bootstrap the wiki directory under ``data_dir/wiki/``.

This module is idempotent and safe to run on every startup:
- It creates the directory tree if missing.
- It copies template files (``purpose.md``, ``schema.md``, ``index.md``,
  ``log.md``, ``overview.md``) only when the destination doesn't exist.
- It NEVER overwrites a file the user has edited — the user's wiki is
  sacred.

Returned manifest reports what was created vs. left alone, so callers
(``main.lifespan``, the doctor CLI) can surface it in logs.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Canonical ``page_type`` → folder-name mapping. English plurals are
# slightly irregular: 'entity' → 'entities' (not 'entitys'), 'query' →
# 'queries' (not 'querys'). Centralising this here means every consumer
# (bootstrap, generator, MCP tool, future migration scripts) agrees on
# the directory layout. Adding a new page type? Add it to BOTH this map
# and ``WIKI_PAGE_TYPES`` in ``storage.metadata_db``.
PAGE_TYPE_DIRECTORY: dict[str, str] = {
    "entity":   "entities",
    "concept":  "concepts",
    "source":   "sources",
    "query":    "queries",
    # ``overview`` lives at the wiki root (overview.md), so no folder.
}

# Backwards-compatible iterable of just the folder names — useful where
# we only care about creating directories, not the type→dir mapping.
PAGE_TYPE_DIRS: tuple[str, ...] = tuple(PAGE_TYPE_DIRECTORY.values())


def directory_for(page_type: str) -> str | None:
    """Return the on-disk subdirectory name for a given page type.

    ``None`` is returned for types that live at the wiki root (only
    ``overview`` today). Raises ``KeyError`` for unknown types so
    typos surface immediately rather than producing ``unknowns/`` or
    similar phantom folders."""
    if page_type == "overview":
        return None
    return PAGE_TYPE_DIRECTORY[page_type]

# Top-level meta files; copied verbatim from backend/wiki/templates/.
META_FILES: tuple[str, ...] = (
    "purpose.md",
    "schema.md",
    "index.md",
    "log.md",
    "overview.md",
)


def _templates_dir() -> Path:
    """Return the absolute path to backend/wiki/templates/."""
    return Path(__file__).resolve().parent / "templates"


def init_wiki_filesystem(data_dir: str | Path) -> dict[str, Any]:
    """Ensure ``data_dir/wiki/`` exists with all skeleton files in place.

    Returns a manifest dict::

        {
            "wiki_root":  "/abs/path/to/data/wiki",
            "created":    [list of paths newly written],
            "preserved":  [list of paths left alone because they exist],
        }

    Raises only on filesystem errors (perm denied, disk full); never
    on "already initialised". Designed to be called on every startup
    so a wiped data dir auto-heals.
    """
    root = Path(data_dir).expanduser() / "wiki"
    created: list[str] = []
    preserved: list[str] = []

    # 1. Per-type subdirectories.
    for sub in PAGE_TYPE_DIRS:
        d = root / sub
        if d.exists():
            preserved.append(str(d))
        else:
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # 2. Meta files at the wiki root.
    src_dir = _templates_dir()
    if not src_dir.is_dir():
        # Should never happen — templates ship with the package — but
        # log loudly so the failure is visible instead of producing an
        # empty wiki.
        logger.error("wiki templates dir missing: %s", src_dir)
        return {"wiki_root": str(root), "created": created, "preserved": preserved}

    for fname in META_FILES:
        dst = root / fname
        if dst.exists():
            preserved.append(str(dst))
            continue
        src = src_dir / fname
        if not src.is_file():
            logger.warning("wiki template file missing: %s", src)
            continue
        shutil.copy2(src, dst)
        created.append(str(dst))

    if created:
        logger.info(
            "wiki bootstrap: created %d files/dirs under %s (preserved %d)",
            len(created),
            root,
            len(preserved),
        )
    else:
        logger.debug("wiki bootstrap: nothing to do, %d existing entries", len(preserved))

    return {
        "wiki_root": str(root),
        "created":   created,
        "preserved": preserved,
    }


def page_path(data_dir: str | Path, page_type: str, slug: str) -> Path:
    """Resolve the on-disk path for a wiki page of a given type+slug.

    Single source of truth for "where does this page live?". Routes
    through :func:`directory_for` to handle the irregular plurals
    (entity → entities, query → queries).
    """
    root = Path(data_dir).expanduser() / "wiki"
    sub = directory_for(page_type)
    if sub is None:
        # Root-level file (overview.md). The slug is ignored — there's
        # only one overview page per wiki — but we honour the input
        # for non-canonical callers.
        return root / f"{slug}.md"
    return root / sub / f"{slug}.md"
