"""OmniKB Wiki layer — LLM-maintained secondary knowledge index.

This package contains:
- ``bootstrap``      filesystem scaffolding (data_dir/wiki/...) and template seeding
- ``worker``         async worker that turns ingest events into wiki page edits (P2+)
- ``templates/``     starter markdown documents shipped with every install

The page metadata + edges live in SQLite via ``storage.metadata_db``.
The page bodies live on disk so users can browse them with Obsidian /
git / their favourite editor.

Process-wide pointer to the live worker — populated by ``main.lifespan``
on startup, cleared on shutdown. Producers (ingest pipeline) check
truthiness before enqueuing so unit tests / one-off scripts that don't
spin up the worker don't crash on imports.
"""
from __future__ import annotations

# Late-bound to avoid an import cycle: ``worker`` imports from
# ``storage.metadata_db``, which has nothing to do with this module's
# import-time work. We declare the type for static checkers without
# materialising the class here.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .worker import WikiEvent, WikiWorker

# Set by main.lifespan; consumers must always handle the ``None`` case.
WORKER: "WikiWorker | None" = None


async def enqueue_event(event: "WikiEvent") -> bool:
    """Producer-side helper used by the ingest pipeline.

    Returns ``True`` if the event made it into the queue, ``False`` if
    the worker isn't running (tests, CLI tools) OR the queue is full.
    Callers MUST treat the return as advisory only — wiki maintenance
    is best-effort and never blocks the user-facing request.
    """
    w = WORKER
    if w is None:
        return False
    return await w.enqueue(event)
