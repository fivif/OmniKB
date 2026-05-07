from __future__ import annotations
import json
from datetime import datetime, timezone

import aiosqlite

from config import settings

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    url         TEXT,
    tags        TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    content     TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    log         TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_tasks_source  ON tasks(source_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    thread_id     TEXT PRIMARY KEY,
    messages_json TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_call_logs (
    id             TEXT PRIMARY KEY,
    tool_name      TEXT NOT NULL,
    args_json      TEXT NOT NULL DEFAULT '{}',
    result_preview TEXT,
    duration_ms    INTEGER,
    called_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mcp_logs_tool ON mcp_call_logs(tool_name);
CREATE INDEX IF NOT EXISTS idx_mcp_logs_time ON mcp_call_logs(called_at);
"""


async def init_db() -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.executescript(_CREATE_TABLES)
        # Migration: add log column to existing tasks tables
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN log TEXT NOT NULL DEFAULT ''")
            await db.commit()
        except Exception:
            pass  # column already exists


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Sources ───────────────────────────────────────────────────

async def insert_source(src: dict) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            """INSERT INTO sources (id, name, type, url, tags, status, created_at, updated_at)
               VALUES (:id, :name, :type, :url, :tags, :status, :created_at, :updated_at)""",
            {
                **src,
                "tags": json.dumps(src.get("tags", [])),
                "status": src.get("status", "pending"),
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        await db.commit()


async def get_source(source_id: str) -> dict | None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                d = dict(row)
                d["tags"] = json.loads(d["tags"])
                return d
    return None


async def list_sources(
    limit: int = 50,
    offset: int = 0,
    filter_tag: str | None = None,
) -> list[dict]:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        if filter_tag:
            sql = (
                "SELECT * FROM sources WHERE tags LIKE ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?"
            )
            params = (f'%"{filter_tag}"%', limit, offset)
        else:
            sql = "SELECT * FROM sources ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params = (limit, offset)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d["tags"] = json.loads(d["tags"])
                result.append(d)
            return result


async def update_source_status(source_id: str, status: str) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            "UPDATE sources SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), source_id),
        )
        await db.commit()


async def update_source_tags(source_id: str, tags: list[str]) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            "UPDATE sources SET tags = ?, updated_at = ? WHERE id = ?",
            (json.dumps(tags), _now(), source_id),
        )
        await db.commit()


async def get_all_tags() -> list[str]:
    """Return sorted list of all distinct tags across all sources."""
    async with aiosqlite.connect(settings.sqlite_path) as db:
        async with db.execute(
            "SELECT DISTINCT tags FROM sources WHERE tags != '[]'"
        ) as cur:
            rows = await cur.fetchall()
    all_tags: set[str] = set()
    for (raw,) in rows:
        try:
            all_tags.update(json.loads(raw))
        except Exception:
            pass
    return sorted(all_tags)


async def delete_source(source_id: str) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        await db.commit()


async def count_sources() -> int:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        async with db.execute("SELECT COUNT(*) FROM sources") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Chunks ────────────────────────────────────────────────────

async def insert_chunks(chunks: list[dict]) -> None:
    now = _now()
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.executemany(
            """INSERT OR IGNORE INTO chunks
               (id, source_id, content, chunk_index, metadata, created_at)
               VALUES (:id, :source_id, :content, :chunk_index, :metadata, :created_at)""",
            [
                {
                    **c,
                    "metadata": json.dumps(c.get("metadata", {})),
                    "created_at": now,
                }
                for c in chunks
            ],
        )
        await db.commit()


async def list_chunks_by_source(
    source_id: str, limit: int = 100, offset: int = 0
) -> list[dict]:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM chunks WHERE source_id = ? ORDER BY chunk_index LIMIT ? OFFSET ?",
            (source_id, limit, offset),
        ) as cur:
            rows = await cur.fetchall()
            return [
                {**dict(r), "metadata": json.loads(r["metadata"])} for r in rows
            ]


async def get_chunk(chunk_id: str) -> dict | None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM chunks WHERE id = ?", (chunk_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                d = dict(row)
                d["metadata"] = json.loads(d["metadata"])
                return d
    return None


async def check_content_hash_exists(content_hash: str) -> bool:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        async with db.execute(
            "SELECT 1 FROM chunks WHERE json_extract(metadata, '$.content_hash') = ? LIMIT 1",
            (content_hash,),
        ) as cur:
            return await cur.fetchone() is not None


async def count_chunks() -> int:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        async with db.execute("SELECT COUNT(*) FROM chunks") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Tasks ─────────────────────────────────────────────────────

async def insert_task(task: dict) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            """INSERT INTO tasks (id, source_id, status, created_at, updated_at)
               VALUES (:id, :source_id, :status, :created_at, :updated_at)""",
            {**task, "created_at": _now(), "updated_at": _now()},
        )
        await db.commit()


async def get_task(task_id: str) -> dict | None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_tasks(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT t.*, s.name AS source_name, s.type AS source_type
            FROM tasks t
            LEFT JOIN sources s ON s.id = t.source_id
            ORDER BY t.created_at DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def update_task(task_id: str, status: str, error: str | None = None) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, _now(), task_id),
        )
        await db.commit()


async def append_task_log(task_id: str, line: str) -> None:
    """Append a log line (timestamped) to the task's log field."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {line}\n"
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            "UPDATE tasks SET log = log || ?, updated_at = ? WHERE id = ?",
            (entry, _now(), task_id),
        )
        await db.commit()


# ── Chat sessions ──────────────────────────────────────────────

async def get_session(thread_id: str) -> dict | None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM chat_sessions WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                d = dict(row)
                d["messages"] = json.loads(d["messages_json"])
                return d
    return None


async def upsert_session(thread_id: str, messages: list[dict]) -> None:
    now = _now()
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            """
            INSERT INTO chat_sessions (thread_id, messages_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                messages_json = excluded.messages_json,
                updated_at    = excluded.updated_at
            """,
            (thread_id, json.dumps(messages, ensure_ascii=False), now, now),
        )
        await db.commit()


async def delete_session(thread_id: str) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            "DELETE FROM chat_sessions WHERE thread_id = ?", (thread_id,)
        )
        await db.commit()


# ── MCP call logs ─────────────────────────────────────────────

async def insert_mcp_log(log: dict) -> None:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(
            """
            INSERT INTO mcp_call_logs
                (id, tool_name, args_json, result_preview, duration_ms, called_at)
            VALUES (:id, :tool_name, :args_json, :result_preview, :duration_ms, :called_at)
            """,
            log,
        )
        await db.commit()


async def list_mcp_logs(
    limit: int = 50,
    tool: str | None = None,
) -> list[dict]:
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row
        if tool:
            sql = (
                "SELECT * FROM mcp_call_logs WHERE tool_name = ? "
                "ORDER BY called_at DESC LIMIT ?"
            )
            params = (tool, limit)
        else:
            sql = "SELECT * FROM mcp_call_logs ORDER BY called_at DESC LIMIT ?"
            params = (limit,)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Export ────────────────────────────────────────────────────

async def export_all_data() -> dict:
    """Return a full snapshot of sources + chunks for export."""
    async with aiosqlite.connect(settings.sqlite_path) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT * FROM sources ORDER BY created_at DESC") as cur:
            src_rows = await cur.fetchall()

        sources = []
        for row in src_rows:
            src = dict(row)
            src["tags"] = json.loads(src["tags"])

            async with db.execute(
                "SELECT id, content, chunk_index, metadata FROM chunks "
                "WHERE source_id = ? ORDER BY chunk_index",
                (src["id"],),
            ) as ccur:
                chunk_rows = await ccur.fetchall()
            src["chunks"] = [
                {**dict(c), "metadata": json.loads(c["metadata"])}
                for c in chunk_rows
            ]
            sources.append(src)

    return {"sources": sources, "total_sources": len(sources)}


async def batch_delete_sources(source_ids: list[str]) -> int:
    """Delete multiple sources by ID. Returns count deleted."""
    if not source_ids:
        return 0
    placeholders = ",".join("?" * len(source_ids))
    async with aiosqlite.connect(settings.sqlite_path) as db:
        await db.execute(f"DELETE FROM sources WHERE id IN ({placeholders})", source_ids)
        await db.execute(f"DELETE FROM chunks WHERE source_id IN ({placeholders})", source_ids)
        await db.commit()
    return len(source_ids)


async def batch_update_tags(
    source_ids: list[str],
    tags: list[str],
    mode: str = "replace",  # replace | add | remove
) -> None:
    """Batch update tags on multiple sources.

    mode='replace': set tags to exactly ``tags``
    mode='add':     union of existing tags and ``tags``
    mode='remove':  remove ``tags`` from existing tags
    """
    if not source_ids:
        return
    placeholders = ",".join("?" * len(source_ids))
    now = _now()
    async with aiosqlite.connect(settings.sqlite_path) as db:
        if mode == "replace":
            tags_json = json.dumps(tags)
            await db.execute(
                f"UPDATE sources SET tags = ?, updated_at = ? WHERE id IN ({placeholders})",
                [tags_json, now] + source_ids,
            )
        else:
            # Read current tags, merge/remove, write back
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT id, tags FROM sources WHERE id IN ({placeholders})", source_ids
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                existing = set(json.loads(row["tags"]))
                if mode == "add":
                    new_tags = sorted(existing | set(tags))
                else:  # remove
                    new_tags = sorted(existing - set(tags))
                await db.execute(
                    "UPDATE sources SET tags = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(new_tags), now, row["id"]),
                )
        await db.commit()
