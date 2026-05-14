from __future__ import annotations
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite

from config import settings


@asynccontextmanager
async def _connect():
    """Open a SQLite connection with WAL-friendly PRAGMAs applied.

    - ``busy_timeout=5000``: wait up to 5 s on writer contention before raising
      ``database is locked``. With WAL enabled in :func:`init_db`, this lets
      concurrent ingest / chat / MCP writes coexist gracefully.
    - ``foreign_keys=ON``: SQLite ships with FK enforcement disabled by default,
      which silently breaks ``ON DELETE CASCADE`` clauses. We need it ON so that
      deleting a source actually cascades into ``chunks`` and
      ``scenario_sources`` instead of leaving orphans.
    """
    conn = await aiosqlite.connect(settings.sqlite_path)
    try:
        await conn.execute("PRAGMA busy_timeout = 5000")
        await conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        await conn.close()

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
            """SELECT ss.source_id, ss.chunk_id, ss.added_by, ss.created_at,
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
        await db.execute(
            """DELETE FROM scenario_sources
               WHERE scenario_id = ? AND source_id = ? AND chunk_id = ?""",
            (scenario_id, source_id, chunk_id),
        )
        await db.commit()


async def count_scenario_sources(scenario_id: str) -> int:
    async with _connect() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM scenario_sources WHERE scenario_id = ?",
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
