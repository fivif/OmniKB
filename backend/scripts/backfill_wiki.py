"""Backfill wiki pages from existing KB sources.

Run once after wiki tables are created on an existing database.
Requires a working LLM configuration.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from wiki.generator import WikiGenerator
from wiki.worker import WikiEvent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backfill_wiki")


async def main():
    db_path = settings.sqlite_path
    data_dir = settings.data_dir

    db = sqlite3.connect(db_path)
    rows = db.execute(
        "SELECT id, name, url, type, status FROM sources WHERE status='done' ORDER BY created_at"
    ).fetchall()
    db.close()

    total = len(rows)
    logger.info("Found %d sources with status=done", total)
    if total == 0:
        logger.info("Nothing to backfill.")
        return

    # Check which sources already have wiki pages
    db = sqlite3.connect(db_path)
    existing = db.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]
    db.close()

    if existing > 0:
        logger.info("Wiki already has %d pages. Skipping backfill to avoid duplicates.", existing)
        return

    generator = WikiGenerator(
        data_dir,
        source_truncate_chars=settings.wiki_max_source_chars,
        generation_concurrency=min(settings.wiki_generation_concurrency, 3),
    )

    success = 0
    skipped = 0
    failed = 0

    for idx, (src_id, name, url, stype, status) in enumerate(rows, 1):
        # Get chunk text
        db = sqlite3.connect(db_path)
        chunks = db.execute(
            "SELECT content FROM chunks WHERE source_id=? ORDER BY chunk_index",
            (src_id,),
        ).fetchall()
        db.close()

        if not chunks:
            logger.warning("[%d/%d] %s: no chunks, skipping", idx, total, src_id[:8])
            skipped += 1
            continue

        raw_text = "\n\n".join(c[0] for c in chunks)
        title = name or url or src_id

        logger.info("[%d/%d] Processing: %s (%d chunks, %d chars)",
                     idx, total, title[:60], len(chunks), len(raw_text))

        try:
            result = await generator.generate(WikiEvent(
                kind="ingest",
                source_id=src_id,
                summary=f"{title} ({len(chunks)} chunks)",
                raw_text=raw_text,
                source_metadata={"url": url or "", "type": stype, "title": title},
            ))
            if result.error:
                logger.error("[%d/%d] %s: analysis failed — %s", idx, total, title[:40], result.error)
                failed += 1
            elif result.pages_created == 0:
                logger.warning("[%d/%d] %s: no pages generated", idx, total, title[:40])
                skipped += 1
            else:
                logger.info("[%d/%d] %s: %d pages created, %d edges",
                             idx, total, title[:40], result.pages_created, result.edges_added)
                success += 1
        except Exception as exc:
            logger.exception("[%d/%d] %s: unhandled error — %s", idx, total, title[:40], exc)
            failed += 1

    logger.info("Backfill complete: %d success, %d skipped, %d failed", success, skipped, failed)


if __name__ == "__main__":
    asyncio.run(main())
