from __future__ import annotations
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite

from config import settings

logger = logging.getLogger(__name__)


# ── Long-lived connection ─────────────────────────────────────────────
#
# Earlier versions opened a fresh aiosqlite connection (≈ 187 µs each) for
# every query. With 55 call sites that adds 1-2 ms of pointless overhead to
# every request hot-path. aiosqlite runs each connection on its own worker
# thread and already serialises operations, so a single shared connection is
# the right primitive — it preserves the existing 'async with _connect()'
# call shape so no caller has to change.
#
# The connection is lazily opened on first use and reused for the process
# lifetime. ``close_db()`` is exposed for clean shutdown (called from
# ``main.py`` lifespan).

_shared_conn: aiosqlite.Connection | None = None
_open_lock = asyncio.Lock()


async def _open_shared_connection() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(settings.sqlite_path)
    # Per-connection PRAGMAs that must be re-set every time SQLite opens
    # this database handle:
    # - ``busy_timeout=5000``: wait up to 5 s on writer contention before
    #   raising ``database is locked``. WAL (enabled persistently in
    #   :func:`init_db`) lets readers and writers coexist gracefully.
    # - ``foreign_keys=ON``: SQLite ships with FK enforcement disabled by
    #   default, which silently breaks ``ON DELETE CASCADE`` clauses.
    await conn.execute("PRAGMA busy_timeout = 5000")
    await conn.execute("PRAGMA foreign_keys = ON")
    return conn


async def _get_conn() -> aiosqlite.Connection:
    """Return the lazily-initialised process-wide aiosqlite connection."""
    global _shared_conn
    if _shared_conn is not None:
        return _shared_conn
    async with _open_lock:
        if _shared_conn is None:
            _shared_conn = await _open_shared_connection()
            logger.debug("metadata_db: opened shared connection to %s", settings.sqlite_path)
    return _shared_conn


async def close_db() -> None:
    """Close the shared connection. Idempotent; safe to call multiple times."""
    global _shared_conn
    conn, _shared_conn = _shared_conn, None
    if conn is not None:
        try:
            await conn.close()
        except Exception as exc:
            logger.debug("metadata_db: close error (non-fatal): %s", exc)


@asynccontextmanager
async def _connect():
    """Yield the shared aiosqlite connection.

    Kept as an ``async with`` context manager for backwards compatibility:
    every existing call site uses ``async with _connect() as db:`` and
    closing the connection per request is no longer correct. The CM is a
    no-op around the singleton.
    """
    conn = await _get_conn()
    yield conn

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

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    task_id     TEXT,
    cwd         TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT,
    tool_calls  TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_session_msgs_sid ON session_messages(session_id);

CREATE TABLE IF NOT EXISTS skills (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    url_pattern     TEXT,
    description     TEXT,
    recipe          TEXT NOT NULL DEFAULT '{}',
    embedding       BLOB,
    success_count   INTEGER NOT NULL DEFAULT 0,
    last_used_at    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);

CREATE TABLE IF NOT EXISTS scenarios (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    system_prompt   TEXT NOT NULL DEFAULT '',
    llm_provider    TEXT NOT NULL DEFAULT 'custom',
    llm_model       TEXT NOT NULL DEFAULT '',
    llm_base_url    TEXT NOT NULL DEFAULT '',
    llm_api_key     TEXT NOT NULL DEFAULT '',
    ui_config       TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_sources (
    scenario_id     TEXT NOT NULL,
    source_id       TEXT,
    chunk_id        TEXT,
    added_by        TEXT NOT NULL DEFAULT 'manual',
    created_at      TEXT NOT NULL,
    PRIMARY KEY (scenario_id, source_id, chunk_id),
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
    -- chunk_id FK omitted intentionally: empty string = whole-source reference
);
CREATE INDEX IF NOT EXISTS idx_scenario_sources_sid ON scenario_sources(scenario_id);

CREATE TABLE IF NOT EXISTS scenario_api_keys (
    id              TEXT PRIMARY KEY,
    scenario_id     TEXT NOT NULL,
    key_name        TEXT NOT NULL DEFAULT '',
    key_hash        TEXT NOT NULL,
    key_prefix      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT,
    FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_scenario_keys_sid ON scenario_api_keys(scenario_id);
CREATE INDEX IF NOT EXISTS idx_scenario_keys_hash ON scenario_api_keys(key_hash);

-- ── L2 Wiki layer (LLM-Wiki secondary index) ────────────────────────
-- Page metadata; the rendered markdown lives on disk under
-- ``data_dir/wiki/{page_type}s/{slug}.md``. We keep two copies of
-- intent: file system for human reading + git versioning, DB for fast
-- lookup, type filtering, and graph queries.
CREATE TABLE IF NOT EXISTS wiki_pages (
    id           TEXT PRIMARY KEY,         -- e.g. "entity:karpathy"
    page_type    TEXT NOT NULL,            -- entity | concept | source | query | overview
    slug         TEXT NOT NULL,            -- url-safe filename (no extension)
    title        TEXT NOT NULL,
    file_path    TEXT NOT NULL,            -- relative to data_dir, e.g. wiki/entities/karpathy.md
    summary      TEXT NOT NULL DEFAULT '',
    frontmatter  TEXT NOT NULL DEFAULT '{}', -- JSON: tags[], aliases[], dates, ...
    source_ids   TEXT NOT NULL DEFAULT '[]', -- JSON list of contributing source.id
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    revision     INTEGER NOT NULL DEFAULT 1, -- bumped on every LLM edit
    UNIQUE(page_type, slug)
);
CREATE INDEX IF NOT EXISTS idx_wiki_pages_type    ON wiki_pages(page_type);
CREATE INDEX IF NOT EXISTS idx_wiki_pages_updated ON wiki_pages(updated_at);

-- Directed [[wikilink]] edge table. ``relation`` lets us encode
-- semantically richer ties later (contradicts / extends / source-of)
-- without schema churn — for P1 every edge is just 'mentions'.
CREATE TABLE IF NOT EXISTS wikilinks (
    src_page_id  TEXT NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    dst_page_id  TEXT NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    relation     TEXT NOT NULL DEFAULT 'mentions',
    weight       REAL NOT NULL DEFAULT 1.0,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (src_page_id, dst_page_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_wikilinks_dst ON wikilinks(dst_page_id);

-- Append-only log of wiki worker events; mirrors data/wiki/log.md but
-- with structured fields for UI / analytics. Worker writes both.
CREATE TABLE IF NOT EXISTS wiki_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,             -- ingest | lint | query_save | manual_edit
    source_id   TEXT,                      -- optional FK to sources.id (no cascade — keep history)
    page_ids    TEXT NOT NULL DEFAULT '[]', -- JSON: pages touched by this event
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wiki_events_kind ON wiki_events(kind);
CREATE INDEX IF NOT EXISTS idx_wiki_events_time ON wiki_events(created_at);
"""


async def init_db() -> None:
    async with _connect() as db:
        # WAL is a persistent database property; setting it once survives across
        # all future connections. Combined with per-connection ``busy_timeout``
        # this allows readers and writers to coexist without ``database is locked``.
        try:
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            pass

        await db.executescript(_CREATE_TABLES)
        await _migrate_scenario_sources_schema(db)

        # Idempotent migrations for older databases.
        for ddl in (
            "ALTER TABLE tasks ADD COLUMN log TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE tasks ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'",
        ):
            try:
                await db.execute(ddl)
            except Exception:
                pass  # column already exists

        # Expression index on content_hash inside metadata JSON. Without this,
        # ``check_content_hash_exists`` degenerates to a full table scan once
        # the chunks table grows beyond a few thousand rows.
        try:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_content_hash "
                "ON chunks(json_extract(metadata, '$.content_hash'))"
            )
        except Exception:
            pass

        await db.commit()


async def _migrate_scenario_sources_schema(db: aiosqlite.Connection) -> None:
    """Drop the legacy chunk_id foreign key from scenario_sources if present.

    Older databases created ``scenario_sources.chunk_id -> chunks.id``. That
    makes whole-source references impossible because this table intentionally
    stores an empty string in ``chunk_id`` to mean "the entire source".
    Rebuild the table in place when we detect that legacy FK.
    """
    async with db.execute("PRAGMA foreign_key_list('scenario_sources')") as cur:
        foreign_keys = await cur.fetchall()

    has_chunk_fk = any(
        row[2] == "chunks" and row[3] == "chunk_id"
        for row in foreign_keys
    )
    if not has_chunk_fk:
        return

    await db.execute("ALTER TABLE scenario_sources RENAME TO scenario_sources_legacy")
    await db.execute(
        """CREATE TABLE scenario_sources (
            scenario_id     TEXT NOT NULL,
            source_id       TEXT,
            chunk_id        TEXT,
            added_by        TEXT NOT NULL DEFAULT 'manual',
            created_at      TEXT NOT NULL,
            PRIMARY KEY (scenario_id, source_id, chunk_id),
            FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE,
            FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
        )"""
    )
    await db.execute(
        """INSERT OR IGNORE INTO scenario_sources
           (scenario_id, source_id, chunk_id, added_by, created_at)
           SELECT legacy.scenario_id,
                  legacy.source_id,
                  COALESCE(legacy.chunk_id, ''),
                  COALESCE(legacy.added_by, 'manual'),
                  legacy.created_at
           FROM scenario_sources_legacy AS legacy
           JOIN scenarios AS sc ON sc.id = legacy.scenario_id
           LEFT JOIN sources AS src ON src.id = legacy.source_id
           WHERE legacy.source_id IS NULL OR src.id IS NOT NULL"""
    )
    await db.execute("DROP TABLE scenario_sources_legacy")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_scenario_sources_sid ON scenario_sources(scenario_id)"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Sources ───────────────────────────────────────────────────

async def insert_source(src: dict) -> None:
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
        await db.execute(
            "UPDATE sources SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), source_id),
        )
        await db.commit()


async def update_source_tags(source_id: str, tags: list[str]) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE sources SET tags = ?, updated_at = ? WHERE id = ?",
            (json.dumps(tags), _now(), source_id),
        )
        await db.commit()


async def get_all_tags() -> list[str]:
    """Return sorted list of all distinct tags across all sources."""
    async with _connect() as db:
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
    async with _connect() as db:
        await db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        await db.commit()


async def count_sources() -> int:
    async with _connect() as db:
        async with db.execute("SELECT COUNT(*) FROM sources") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Chunks ────────────────────────────────────────────────────

async def insert_chunks(chunks: list[dict]) -> None:
    now = _now()
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
        async with db.execute(
            "SELECT 1 FROM chunks WHERE json_extract(metadata, '$.content_hash') = ? LIMIT 1",
            (content_hash,),
        ) as cur:
            return await cur.fetchone() is not None


async def count_chunks() -> int:
    async with _connect() as db:
        async with db.execute("SELECT COUNT(*) FROM chunks") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Tasks ─────────────────────────────────────────────────────

async def insert_task(task: dict) -> None:
    """Persist a task row. ``task['params']`` (optional) captures the inputs
    needed to re-run the task after a crash; we serialise it as JSON into the
    ``params_json`` column."""
    params = task.get("params") or {}
    async with _connect() as db:
        await db.execute(
            """INSERT INTO tasks (id, source_id, status, params_json, created_at, updated_at)
               VALUES (:id, :source_id, :status, :params_json, :created_at, :updated_at)""",
            {
                "id": task["id"],
                "source_id": task["source_id"],
                "status": task.get("status", "pending"),
                "params_json": json.dumps(params, ensure_ascii=False),
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        await db.commit()


async def get_task(task_id: str) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_resumable_tasks() -> list[dict]:
    """Return tasks left in ``pending`` / ``processing`` state by a previous
    process. Used by the lifespan hook to re-queue work after a crash so users
    don't see "zombie" tasks stuck forever.

    Tasks without ``params_json`` (older rows or tasks that pre-date this
    migration) cannot be safely re-run and are skipped — callers should mark
    those as ``error`` if they remain orphaned.
    """
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT t.*, s.name AS source_name, s.type AS source_type
               FROM tasks t
               LEFT JOIN sources s ON s.id = t.source_id
               WHERE t.status IN ('pending', 'processing')
               ORDER BY t.created_at ASC"""
        ) as cur:
            rows = await cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d.get("params_json") or "{}")
        except Exception:
            d["params"] = {}
        out.append(d)
    return out


async def list_tasks(limit: int = 50, offset: int = 0) -> list[dict]:
    async with _connect() as db:
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
    async with _connect() as db:
        await db.execute(
            "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, _now(), task_id),
        )
        await db.commit()


async def append_task_log(task_id: str, line: str) -> None:
    """Append a log line (timestamped) to the task's log field."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {line}\n"
    async with _connect() as db:
        await db.execute(
            "UPDATE tasks SET log = log || ?, updated_at = ? WHERE id = ?",
            (entry, _now(), task_id),
        )
        await db.commit()
    # Broadcast to agent activity console
    try:
        from utils.agent_bus import emit
        kind = (
            "success" if any(x in line for x in ("✅", "🏁", "已完成", "完成"))
            else "error"   if any(x in line for x in ("❌", "失败", "错误", "Error"))
            else "warning"  if any(x in line for x in ("⚠️", "跳过", "重复"))
            else "progress" if any(x in line for x in ("⚙️", "📄", "✂️", "🔍", "🔢", "📥", "📝", "🌐", "🏷️"))
            else "info"
        )
        emit(line, kind=kind, agent="ingest", task_id=task_id)
    except Exception:
        pass


# ── Chat sessions ──────────────────────────────────────────────

async def get_session(thread_id: str) -> dict | None:
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
        await db.execute(
            "DELETE FROM chat_sessions WHERE thread_id = ?", (thread_id,)
        )
        await db.commit()


# ── MCP call logs ─────────────────────────────────────────────

async def insert_mcp_log(log: dict) -> None:
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
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
    async with _connect() as db:
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

# ── Web Agent sessions (P3) ───────────────────────────────────

async def create_web_session(session: dict) -> None:
    now = _now()
    async with _connect() as db:
        await db.execute(
            """INSERT INTO sessions (id, task_id, cwd, status, created_at, updated_at)
               VALUES (:id, :task_id, :cwd, :status, :created_at, :updated_at)""",
            {
                "id": session["id"],
                "task_id": session.get("task_id"),
                "cwd": session.get("cwd"),
                "status": session.get("status", "running"),
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()


async def append_session_message(session_id: str, role: str, content: str | None, tool_calls: str | None = None) -> None:
    async with _connect() as db:
        await db.execute(
            """INSERT INTO session_messages (session_id, role, content, tool_calls, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, tool_calls, _now()),
        )
        await db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )
        await db.commit()


async def list_session_messages(session_id: str, limit: int = 1000) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM session_messages WHERE session_id = ? ORDER BY id LIMIT ?",
            (session_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def update_session_status(session_id: str, status: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), session_id),
        )
        await db.commit()


async def get_web_session(session_id: str) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def list_web_sessions(limit: int = 50, offset: int = 0) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Skills (P3) ───────────────────────────────────────────────

async def upsert_skill(skill: dict) -> None:
    """Insert or replace a skill. ``embedding`` should be float32 bytes or None."""
    now = _now()
    async with _connect() as db:
        await db.execute(
            """INSERT INTO skills (id, name, url_pattern, description, recipe,
                                   embedding, success_count, last_used_at, created_at)
               VALUES (:id, :name, :url_pattern, :description, :recipe,
                       :embedding, :success_count, :last_used_at, :created_at)
               ON CONFLICT(id) DO UPDATE SET
                 name           = excluded.name,
                 url_pattern    = excluded.url_pattern,
                 description    = excluded.description,
                 recipe         = excluded.recipe,
                 embedding      = excluded.embedding""",
            {
                "id": skill["id"],
                "name": skill["name"],
                "url_pattern": skill.get("url_pattern"),
                "description": skill.get("description"),
                "recipe": skill.get("recipe", "{}"),
                "embedding": skill.get("embedding"),
                "success_count": skill.get("success_count", 0),
                "last_used_at": skill.get("last_used_at"),
                "created_at": skill.get("created_at", now),
            },
        )
        await db.commit()


async def list_skills() -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM skills") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def increment_skill_use(skill_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            "UPDATE skills SET success_count = success_count + 1, last_used_at = ? WHERE id = ?",
            (_now(), skill_id),
        )
        await db.commit()


async def count_skills() -> int:
    async with _connect() as db:
        async with db.execute("SELECT COUNT(*) FROM skills") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Scenarios ──────────────────────────────────────────────────

async def list_scenarios() -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scenarios ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
            return [
                {**dict(r), "ui_config": json.loads(r["ui_config"])}
                for r in rows
            ]


async def get_scenario(scenario_id: str) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                d = dict(row)
                d["ui_config"] = json.loads(d["ui_config"])
                return d
    return None


async def insert_scenario(sc: dict) -> None:
    now = _now()
    async with _connect() as db:
        await db.execute(
            """INSERT INTO scenarios
               (id, name, description, system_prompt, llm_provider,
                llm_model, llm_base_url, llm_api_key, ui_config,
                created_at, updated_at)
               VALUES (:id, :name, :description, :system_prompt, :llm_provider,
                       :llm_model, :llm_base_url, :llm_api_key, :ui_config,
                       :created_at, :updated_at)""",
            {
                "id": sc["id"],
                "name": sc["name"],
                "description": sc.get("description", ""),
                "system_prompt": sc.get("system_prompt", ""),
                "llm_provider": sc.get("llm_provider", "custom"),
                "llm_model": sc.get("llm_model", ""),
                "llm_base_url": sc.get("llm_base_url", ""),
                "llm_api_key": sc.get("llm_api_key", ""),
                "ui_config": json.dumps(sc.get("ui_config", {}), ensure_ascii=False),
                "created_at": now,
                "updated_at": now,
            },
        )
        await db.commit()


async def update_scenario(scenario_id: str, updates: dict) -> None:
    fields = []
    values = []
    for key in ("name", "description", "system_prompt", "llm_provider",
                "llm_model", "llm_base_url", "llm_api_key"):
        if key in updates:
            fields.append(f"{key} = ?")
            values.append(updates[key])
    if "ui_config" in updates:
        fields.append("ui_config = ?")
        values.append(json.dumps(updates["ui_config"], ensure_ascii=False))
    if not fields:
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(scenario_id)
    async with _connect() as db:
        await db.execute(
            f"UPDATE scenarios SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        await db.commit()


async def delete_scenario(scenario_id: str) -> None:
    async with _connect() as db:
        await db.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
        await db.commit()


# ── Scenario sources ───────────────────────────────────────────

async def list_scenario_sources(scenario_id: str) -> list[dict]:
    """Return chunks linked to a scenario, enriched with source info."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT ss.source_id, COALESCE(ss.chunk_id, '') AS chunk_id, ss.added_by, ss.created_at,
                      c.content AS chunk_content, c.chunk_index,
                      s.name AS source_name, s.type AS source_type
               FROM scenario_sources ss
               LEFT JOIN chunks c ON ss.chunk_id = c.id
               LEFT JOIN sources s ON ss.source_id = s.id
               WHERE ss.scenario_id = ?
               ORDER BY ss.created_at DESC""",
            (scenario_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def add_scenario_source(
    scenario_id: str, source_id: str, chunk_id: str = "", added_by: str = "manual"
) -> None:
    async with _connect() as db:
        await db.execute(
            """INSERT OR IGNORE INTO scenario_sources
               (scenario_id, source_id, chunk_id, added_by, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (scenario_id, source_id, chunk_id, added_by, _now()),
        )
        await db.commit()


async def add_scenario_sources_batch(
    scenario_id: str, entries: list[tuple[str, str]], added_by: str = "manual"
) -> int:
    """Batch insert: *entries* is [(source_id, chunk_id), ...]. Returns count inserted."""
    now = _now()
    count = 0
    async with _connect() as db:
        for source_id, chunk_id in entries:
            cur = await db.execute(
                """INSERT OR IGNORE INTO scenario_sources
                   (scenario_id, source_id, chunk_id, added_by, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (scenario_id, source_id, chunk_id, added_by, now),
            )
            if cur.rowcount > 0:
                count += 1
        await db.commit()
    return count


async def remove_scenario_source(
    scenario_id: str, source_id: str, chunk_id: str = ""
) -> None:
    async with _connect() as db:
        if chunk_id:
            await db.execute(
                """DELETE FROM scenario_sources
                   WHERE scenario_id = ? AND source_id = ? AND chunk_id = ?""",
                (scenario_id, source_id, chunk_id),
            )
        else:
            await db.execute(
                """DELETE FROM scenario_sources
                   WHERE scenario_id = ? AND source_id = ?""",
                (scenario_id, source_id),
            )
        await db.commit()


async def count_scenario_sources(scenario_id: str) -> int:
    async with _connect() as db:
        async with db.execute(
            "SELECT COUNT(DISTINCT COALESCE(source_id, chunk_id)) FROM scenario_sources WHERE scenario_id = ?",
            (scenario_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ── Scenario API keys ──────────────────────────────────────────

async def list_scenario_keys(scenario_id: str) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, scenario_id, key_name, key_prefix, created_at, last_used_at
               FROM scenario_api_keys WHERE scenario_id = ?
               ORDER BY created_at DESC""",
            (scenario_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def insert_scenario_key(key: dict) -> None:
    now = _now()
    async with _connect() as db:
        await db.execute(
            """INSERT INTO scenario_api_keys
               (id, scenario_id, key_name, key_hash, key_prefix, created_at, last_used_at)
               VALUES (:id, :scenario_id, :key_name, :key_hash, :key_prefix, :created_at, :last_used_at)""",
            {
                **key,
                "created_at": key.get("created_at") or now,
                "last_used_at": key.get("last_used_at"),
            },
        )
        await db.commit()


async def delete_scenario_key(key_id: str) -> None:
    async with _connect() as db:
        await db.execute(
            "DELETE FROM scenario_api_keys WHERE id = ?", (key_id,)
        )
        await db.commit()


async def verify_scenario_key(key_raw: str) -> tuple[str, str] | None:
    """Return (scenario_id, key_id) if key is valid, else None."""
    import hashlib
    h = hashlib.sha256(key_raw.encode()).hexdigest()
    async with _connect() as db:
        async with db.execute(
            "SELECT id, scenario_id FROM scenario_api_keys WHERE key_hash = ?",
            (h,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                # Update last_used_at
                await db.execute(
                    "UPDATE scenario_api_keys SET last_used_at = ? WHERE id = ?",
                    (_now(), row[0]),
                )
                await db.commit()
                return row[1], row[0]
    return None


# ── Wiki layer (L2 secondary index) ──────────────────────────────────
#
# Thin CRUD over wiki_pages / wikilinks / wiki_events. The page
# *content* lives on disk under ``data_dir/wiki/...`` and is owned by
# the wiki worker (P2); these helpers only manage metadata + edges.

WIKI_PAGE_TYPES: tuple[str, ...] = ("entity", "concept", "source", "query", "overview")


def _coerce_json_list(raw) -> list:
    """Defensive JSON list parser used by every wiki row reader."""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def _coerce_json_dict(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _row_to_wiki_page(row) -> dict:
    return {
        "id":          row["id"],
        "page_type":   row["page_type"],
        "slug":        row["slug"],
        "title":       row["title"],
        "file_path":   row["file_path"],
        "summary":     row["summary"],
        "frontmatter": _coerce_json_dict(row["frontmatter"]),
        "source_ids":  _coerce_json_list(row["source_ids"]),
        "created_at":  row["created_at"],
        "updated_at":  row["updated_at"],
        "revision":    row["revision"],
    }


def make_wiki_page_id(page_type: str, slug: str) -> str:
    """Canonical PK for a wiki page. Surfaced because callers (worker,
    api, MCP tool) all need to construct IDs deterministically without
    duplicating the format string."""
    if page_type not in WIKI_PAGE_TYPES:
        raise ValueError(f"unknown wiki page_type {page_type!r}; expected one of {WIKI_PAGE_TYPES}")
    return f"{page_type}:{slug}"


async def upsert_wiki_page(page: dict) -> dict:
    """Create or update a wiki page row by (page_type, slug).

    On update the ``revision`` column is bumped automatically and
    ``updated_at`` refreshed. ``created_at`` is preserved on update.
    Returns the canonical row dict.
    """
    page_type = page["page_type"]
    slug = page["slug"]
    pid = page.get("id") or make_wiki_page_id(page_type, slug)
    now = _now()

    # Default file path uses the canonical type→dir map so ``entity``
    # → ``entities/``, ``query`` → ``queries/`` (not ``entitys`` /
    # ``querys``). Imported lazily to avoid pulling the wiki package
    # into pure storage callers.
    default_path = page.get("file_path")
    if not default_path:
        try:
            from wiki.bootstrap import directory_for
            sub = directory_for(page_type)
            default_path = (
                f"wiki/{slug}.md" if sub is None else f"wiki/{sub}/{slug}.md"
            )
        except Exception:  # noqa: BLE001 — fallback, very unlikely
            default_path = f"wiki/{page_type}/{slug}.md"

    record = {
        "id":          pid,
        "page_type":   page_type,
        "slug":        slug,
        "title":       page.get("title") or slug,
        "file_path":   default_path,
        "summary":     page.get("summary") or "",
        "frontmatter": json.dumps(page.get("frontmatter") or {}, ensure_ascii=False),
        "source_ids":  json.dumps(page.get("source_ids") or [], ensure_ascii=False),
        "created_at":  page.get("created_at") or now,
        "updated_at":  now,
    }

    async with _connect() as db:
        # ON CONFLICT keeps original created_at, bumps revision, updates
        # the rest. Using the (page_type, slug) UNIQUE constraint as the
        # conflict target so callers don't have to know the PK shape.
        await db.execute(
            """INSERT INTO wiki_pages
                (id, page_type, slug, title, file_path, summary,
                 frontmatter, source_ids, created_at, updated_at, revision)
               VALUES
                (:id, :page_type, :slug, :title, :file_path, :summary,
                 :frontmatter, :source_ids, :created_at, :updated_at, 1)
               ON CONFLICT(page_type, slug) DO UPDATE SET
                 title       = excluded.title,
                 file_path   = excluded.file_path,
                 summary     = excluded.summary,
                 frontmatter = excluded.frontmatter,
                 source_ids  = excluded.source_ids,
                 updated_at  = excluded.updated_at,
                 revision    = wiki_pages.revision + 1""",
            record,
        )
        await db.commit()

    fetched = await get_wiki_page(pid)
    assert fetched is not None  # we just wrote it
    return fetched


async def get_wiki_page(page_id: str) -> dict | None:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM wiki_pages WHERE id = ?", (page_id,)
        ) as cur:
            row = await cur.fetchone()
            return _row_to_wiki_page(row) if row else None


async def get_wiki_page_by_slug(page_type: str, slug: str) -> dict | None:
    return await get_wiki_page(make_wiki_page_id(page_type, slug))


async def list_wiki_pages(
    *,
    page_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """List pages newest-first; filter by ``page_type`` when given."""
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        if page_type is not None:
            if page_type not in WIKI_PAGE_TYPES:
                return []
            sql = ("SELECT * FROM wiki_pages WHERE page_type = ? "
                   "ORDER BY updated_at DESC LIMIT ? OFFSET ?")
            params: tuple = (page_type, limit, offset)
        else:
            sql = ("SELECT * FROM wiki_pages "
                   "ORDER BY updated_at DESC LIMIT ? OFFSET ?")
            params = (limit, offset)
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [_row_to_wiki_page(r) for r in rows]


async def count_wiki_pages_by_type() -> dict[str, int]:
    """Return ``{page_type: count}`` for every present type. Useful for
    sidebar badges and graph legends."""
    async with _connect() as db:
        async with db.execute(
            "SELECT page_type, COUNT(*) FROM wiki_pages GROUP BY page_type"
        ) as cur:
            rows = await cur.fetchall()
            return {r[0]: r[1] for r in rows}


async def delete_wiki_page(page_id: str) -> None:
    """Delete a page and (via FK cascade) all its wikilinks edges."""
    async with _connect() as db:
        await db.execute("DELETE FROM wiki_pages WHERE id = ?", (page_id,))
        await db.commit()


async def upsert_wikilink(
    src_page_id: str,
    dst_page_id: str,
    *,
    relation: str = "mentions",
    weight: float = 1.0,
) -> None:
    """Idempotent edge insert. Updating ``weight`` on a duplicate edge
    is the simplest accumulation strategy — every time the LLM mentions
    page A from page B again the edge gets stronger."""
    async with _connect() as db:
        await db.execute(
            """INSERT INTO wikilinks (src_page_id, dst_page_id, relation, weight, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(src_page_id, dst_page_id, relation) DO UPDATE
                 SET weight = wikilinks.weight + excluded.weight""",
            (src_page_id, dst_page_id, relation, weight, _now()),
        )
        await db.commit()


async def list_wikilinks(
    *,
    src: str | None = None,
    dst: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """List edges; pass ``src`` and/or ``dst`` to filter direction.

    Returning all edges (no filter) is OK at moderate scale (P1
    targets ~thousands of edges). Switch to a streaming reader once
    the graph crosses ~50k edges.
    """
    sql = "SELECT src_page_id, dst_page_id, relation, weight, created_at FROM wikilinks"
    where: list[str] = []
    params: list = []
    if src is not None:
        where.append("src_page_id = ?")
        params.append(src)
    if dst is not None:
        where.append("dst_page_id = ?")
        params.append(dst)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " LIMIT ?"
    params.append(limit)

    async with _connect() as db:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "src_page_id": r[0],
                    "dst_page_id": r[1],
                    "relation":    r[2],
                    "weight":      r[3],
                    "created_at":  r[4],
                }
                for r in rows
            ]


async def graph_neighbors(page_id: str, *, hops: int = 1) -> dict:
    """Breadth-first neighbour expansion up to ``hops`` away.

    Returns ``{"nodes": [page_dict...], "edges": [edge_dict...]}`` so
    the frontend can hand it straight to sigma.js without a join. Both
    incoming and outgoing edges count as adjacency.
    """
    if hops < 1:
        hops = 1
    if hops > 4:
        hops = 4  # bound the BFS — wider neighbourhoods belong to a real graph query API

    seen_pages: set[str] = {page_id}
    seen_edges: set[tuple[str, str, str]] = set()
    frontier: set[str] = {page_id}

    nodes: list[dict] = []
    edges: list[dict] = []

    seed = await get_wiki_page(page_id)
    if seed is None:
        return {"nodes": [], "edges": []}
    nodes.append(seed)

    for _ in range(hops):
        if not frontier:
            break
        next_frontier: set[str] = set()
        for pid in frontier:
            outgoing = await list_wikilinks(src=pid)
            incoming = await list_wikilinks(dst=pid)
            for e in outgoing + incoming:
                key = (e["src_page_id"], e["dst_page_id"], e["relation"])
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                edges.append(e)
                for other in (e["src_page_id"], e["dst_page_id"]):
                    if other not in seen_pages:
                        seen_pages.add(other)
                        next_frontier.add(other)
                        page = await get_wiki_page(other)
                        if page:
                            nodes.append(page)
        frontier = next_frontier

    return {"nodes": nodes, "edges": edges}


async def append_wiki_event(
    *,
    kind: str,
    source_id: str | None = None,
    page_ids: list[str] | None = None,
    summary: str = "",
) -> int:
    """Record a structured event. Returns the autoincrement id so
    callers can correlate (e.g. attach to ingest task logs)."""
    async with _connect() as db:
        cur = await db.execute(
            """INSERT INTO wiki_events (kind, source_id, page_ids, summary, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                kind,
                source_id,
                json.dumps(page_ids or [], ensure_ascii=False),
                summary,
                _now(),
            ),
        )
        await db.commit()
        return cur.lastrowid or 0


async def list_wiki_events(*, limit: int = 100) -> list[dict]:
    async with _connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM wiki_events ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [
                {
                    "id":         r["id"],
                    "kind":       r["kind"],
                    "source_id":  r["source_id"],
                    "page_ids":   _coerce_json_list(r["page_ids"]),
                    "summary":    r["summary"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
