"""End-to-end tests for backend.wiki.deep_research orchestrator.

These tests **do not** call any real LLM, web search, or browser. The
``DeepResearcher`` class accepts three injection points:

* ``llm_invoker`` — replaced with a deterministic mock that returns a
  pre-canned JSON query plan or markdown synthesis.
* ``search_fn``   — returns a fixed list of ``SearchResult``\\s.
* ``research_fn`` — returns a fixed markdown record per URL.

We assert the **invariants that matter** at this layer:

1. **Append-only**: the original page body is preserved verbatim — the
   orchestrator only adds a ``## Recent Research (...)`` section.
2. **Failure isolation**: per-URL errors don't kill the run; only when
   *every* URL fails do we abort and leave the page untouched.
3. **Audit trail**: a ``wiki_event`` row of kind ``deep_research`` is
   appended on success.
4. **Edges**: every ``[[type:slug]]`` mentioned in the new section
   becomes a wikilink edge from the target page.
5. **Task lifecycle**: status transitions ``queued → … → done|failed``.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.wiki.deep_research import (
    DeepResearcher,
    ResearchTask,
    _TASKS,
    get_task,
    list_recent_tasks,
)
from backend.wiki.web_search import SearchResult


# ─── Mock factories ───────────────────────────────────────────────


def _mock_plan_response(queries: list[tuple[str, str]]) -> str:
    """Build a JSON plan string the orchestrator can parse."""
    import json
    return json.dumps({
        "queries": [{"query": q, "intent": i} for q, i in queries]
    })


def _mock_synthesis_response(*, today: str = "2099-01-01") -> str:
    """A synthesised section that exercises the wikilink + citation paths."""
    return (
        f"## Recent Research ({today})\n\n"
        "Summary of findings:\n\n"
        "- [[entity:tesla]] launched a new chip design in 2024 "
        "([source](https://example.com/a)).\n"
        "- The technique extends [[concept:attention]] from "
        "[Vaswani et al.](https://example.com/b).\n\n"
        "> ⚠ Contradicts: source A says 50%, source B says 70%.\n"
    )


def _make_invoker(plan_resp: str, synth_resp: str):
    """Return an LLM mock that distinguishes plan vs synthesis by system msg."""
    calls = {"plan": 0, "synth": 0}

    async def invoker(messages: list[dict[str, str]]) -> str:
        sys_msg = next(
            (m["content"] for m in messages if m.get("role") == "system"),
            "",
        )
        if "research planning assistant" in sys_msg:
            calls["plan"] += 1
            return plan_resp
        if "curator of a personal knowledge base" in sys_msg:
            calls["synth"] += 1
            return synth_resp
        raise AssertionError(f"unexpected LLM call, system msg: {sys_msg[:80]!r}")

    invoker.calls = calls  # type: ignore[attr-defined]
    return invoker


def _make_search(results_per_query: dict[str, list[SearchResult]] | list[SearchResult]):
    """Mock search that returns either fixed results or per-query results."""
    async def search_fn(query: str, limit: int) -> list[SearchResult]:
        if isinstance(results_per_query, dict):
            return results_per_query.get(query, [])[:limit]
        return list(results_per_query)[:limit]
    return search_fn


def _make_research(per_url: dict[str, str | Exception]):
    """Mock URL research — either a markdown record or an exception per URL."""
    async def research_fn(url: str, intent: str) -> str:
        out = per_url.get(url)
        if isinstance(out, Exception):
            raise out
        if out is None:
            raise RuntimeError(f"unexpected url {url!r}")
        return out
    return research_fn


# ─── Page seeding helper ──────────────────────────────────────────


async def _seed_page(slug_suffix: str, *, body: str = "") -> tuple[str, str]:
    """Create a wiki page in DB and on disk; return ``(page_id, file_abs)``."""
    from pathlib import Path

    from backend.config import settings
    from backend.storage.metadata_db import upsert_wiki_page

    slug = f"karpathy-{slug_suffix}"
    title = "Andrej Karpathy"
    page = await upsert_wiki_page({
        "page_type": "entity",
        "slug": slug,
        "title": title,
        "summary": "Researcher; coined LLM-Wiki pattern.",
        "frontmatter": {"tags": ["ml", "people"]},
        "source_ids": [],
    })
    file_abs = Path(settings.data_dir) / page["file_path"]
    file_abs.parent.mkdir(parents=True, exist_ok=True)
    file_abs.write_text(body or f"# {title}\n\nFounder text.\n", encoding="utf-8")
    return page["id"], str(file_abs)


# ─── Happy path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_research_page_happy_path_appends_section(unique_slug):
    """Full success: plan → search → research → synthesise → append."""
    from pathlib import Path

    from backend.config import settings
    from backend.storage.metadata_db import (
        get_wiki_page, list_wiki_events,
    )

    initial_body = "# Andrej Karpathy\n\nOriginal body that must survive verbatim.\n"
    page_id, file_abs = await _seed_page(unique_slug, body=initial_body)
    page_before = await get_wiki_page(page_id)
    rev_before = page_before["revision"]

    invoker = _make_invoker(
        plan_resp=_mock_plan_response([
            ("karpathy biography 2024", "biographical depth"),
            ("karpathy llm-wiki",       "technical core"),
        ]),
        synth_resp=_mock_synthesis_response(),
    )
    search = _make_search([
        SearchResult(url="https://example.com/a", title="Tesla post", snippet="..."),
        SearchResult(url="https://example.com/b", title="Vaswani paper", snippet="..."),
    ])
    research = _make_research({
        "https://example.com/a": "Tesla launched the Dojo chip in 2024. " * 30,
        "https://example.com/b": "Attention is all you need. " * 40,
    })

    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker, search_fn=search, research_fn=research,
        max_urls=2, max_queries=2,
    )
    result = await researcher.research_page(page_id=page_id, focus="recent work")

    # ─ Page on disk: original body preserved + new section appended.
    body_after = Path(file_abs).read_text(encoding="utf-8")
    assert initial_body.rstrip() in body_after, "original body must survive verbatim"
    assert "## Recent Research" in body_after
    assert "[[entity:tesla]]" in body_after
    assert "[[concept:attention]]" in body_after

    # ─ DB: revision bumped, summary unchanged.
    page_after = await get_wiki_page(page_id)
    assert page_after["revision"] == rev_before + 1

    # ─ Edges: tesla + attention edges should exist.
    from backend.storage.metadata_db import _connect
    async with _connect() as db:
        async with db.execute(
            "SELECT dst_page_id FROM wikilinks WHERE src_page_id = ?",
            (page_id,),
        ) as cur:
            dsts = {row[0] for row in await cur.fetchall()}
    assert "entity:tesla"     in dsts
    assert "concept:attention" in dsts

    # ─ Audit event written.
    events = await list_wiki_events(limit=10)
    assert any(e["kind"] == "deep_research" and page_id in (e["page_ids"] or []) for e in events)

    # ─ Task lifecycle.
    assert result["urls_used"] == ["https://example.com/a", "https://example.com/b"]
    assert result["urls_failed"] == []
    assert result["new_links"] >= 2

    # ─ LLM was called exactly once for plan, once for synthesis.
    assert invoker.calls == {"plan": 1, "synth": 1}  # type: ignore[attr-defined]


# ─── Failure isolation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_url_failure_still_synthesises(unique_slug):
    """One URL fails, one succeeds → synthesis still runs over the survivor."""
    from backend.config import settings

    page_id, _ = await _seed_page(unique_slug)

    invoker = _make_invoker(
        plan_resp=_mock_plan_response([("query", "intent")]),
        synth_resp=_mock_synthesis_response(),
    )
    search = _make_search([
        SearchResult(url="https://good.example.com", title="ok", snippet=""),
        SearchResult(url="https://bad.example.com",  title="bad", snippet=""),
    ])
    research = _make_research({
        "https://good.example.com": "Good content here. " * 30,
        "https://bad.example.com":  RuntimeError("network refused"),
    })

    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker, search_fn=search, research_fn=research,
        max_urls=2, max_queries=1,
    )
    result = await researcher.research_page(page_id=page_id)

    assert "https://good.example.com" in result["urls_used"]
    assert "https://bad.example.com"  in result["urls_failed"]
    assert result["new_chars"] > 0


@pytest.mark.asyncio
async def test_all_urls_fail_aborts_without_touching_page(unique_slug):
    """0 URLs survive → ValueError, page on disk + revision unchanged."""
    from pathlib import Path

    from backend.config import settings
    from backend.storage.metadata_db import get_wiki_page

    initial_body = "# Andrej Karpathy\n\nUntouchable body.\n"
    page_id, file_abs = await _seed_page(unique_slug, body=initial_body)
    rev_before = (await get_wiki_page(page_id))["revision"]

    invoker = _make_invoker(
        plan_resp=_mock_plan_response([("q", "i")]),
        synth_resp="(should never be called)",
    )
    search = _make_search([
        SearchResult(url="https://x.example.com", title="x", snippet=""),
        SearchResult(url="https://y.example.com", title="y", snippet=""),
    ])
    research = _make_research({
        "https://x.example.com": RuntimeError("502 bad gateway"),
        "https://y.example.com": RuntimeError("dns fail"),
    })

    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker, search_fn=search, research_fn=research,
        max_urls=2, max_queries=1,
    )

    with pytest.raises(ValueError, match="every URL fetch failed"):
        await researcher.research_page(page_id=page_id)

    # Page must be untouched (cardinal append-only invariant).
    body_after = Path(file_abs).read_text(encoding="utf-8")
    assert body_after == initial_body
    rev_after = (await get_wiki_page(page_id))["revision"]
    assert rev_after == rev_before

    # Synthesis LLM was never called.
    assert invoker.calls["synth"] == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_empty_query_plan_aborts(unique_slug):
    from backend.config import settings

    page_id, _ = await _seed_page(unique_slug)
    invoker = _make_invoker(
        plan_resp='{"queries": []}',
        synth_resp="(unused)",
    )
    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker,
        search_fn=_make_search([]),
        research_fn=_make_research({}),
    )
    with pytest.raises(ValueError, match="no queries"):
        await researcher.research_page(page_id=page_id)


@pytest.mark.asyncio
async def test_no_urls_for_any_query_aborts(unique_slug):
    """Plan succeeds but search returns nothing → abort cleanly."""
    from backend.config import settings

    page_id, _ = await _seed_page(unique_slug)
    invoker = _make_invoker(
        plan_resp=_mock_plan_response([("q", "i")]),
        synth_resp="(unused)",
    )
    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker,
        search_fn=_make_search([]),  # empty for every query
        research_fn=_make_research({}),
    )
    with pytest.raises(ValueError, match="no URLs found"):
        await researcher.research_page(page_id=page_id)


@pytest.mark.asyncio
async def test_unknown_page_id_raises(tmp_path):
    """Page doesn't exist in DB → fail fast, no LLM call."""
    invoker = _make_invoker(plan_resp="(unused)", synth_resp="(unused)")
    researcher = DeepResearcher(
        data_dir=str(tmp_path),
        llm_invoker=invoker,
        search_fn=_make_search([]),
        research_fn=_make_research({}),
    )
    with pytest.raises(ValueError, match="unknown wiki page"):
        await researcher.research_page(page_id="entity:nonexistent-xyz")
    assert invoker.calls == {"plan": 0, "synth": 0}  # type: ignore[attr-defined]


# ─── Task tracking ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_task_lifecycle_done(unique_slug):
    """A passed-in task should walk through queued → … → done."""
    from backend.config import settings

    page_id, _ = await _seed_page(unique_slug)

    task = ResearchTask(task_id=f"test-{unique_slug}", page_id=page_id)
    _TASKS[task.task_id] = task
    assert task.status == "queued"

    invoker = _make_invoker(
        plan_resp=_mock_plan_response([("q", "i")]),
        synth_resp=_mock_synthesis_response(),
    )
    research = _make_research({
        "https://only.example.com": "Sufficient content. " * 30,
    })
    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker,
        search_fn=_make_search([
            SearchResult(url="https://only.example.com", title="t", snippet=""),
        ]),
        research_fn=research,
        max_urls=1, max_queries=1,
    )
    await researcher.research_page(page_id=page_id, task=task)

    assert task.status == "done"
    assert task.error is None
    assert task.finished_at is not None
    assert task.result is not None and "new_chars" in task.result

    # Lookups round-trip — get_task / list_recent_tasks are now async
    # because they fall back to the wiki_research_task table when the
    # in-process cache misses (post-restart, cross-process).
    assert (await get_task(task.task_id)) is task
    recent = await list_recent_tasks(limit=5)
    assert task in recent


@pytest.mark.asyncio
async def test_persistence_survives_simulated_restart(unique_slug):
    """After a happy-path run, evicting the in-process cache simulates a
    backend restart. get_task / list_recent_tasks must still return the
    task by reading the wiki_research_task table."""
    from backend.config import settings

    page_id, _ = await _seed_page(unique_slug)

    invoker = _make_invoker(
        plan_resp=_mock_plan_response([("q", "i")]),
        synth_resp=_mock_synthesis_response(),
    )
    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker,
        search_fn=_make_search([
            SearchResult(url="https://persist.example.com", title="t", snippet=""),
        ]),
        research_fn=_make_research({
            "https://persist.example.com": "Persisted content. " * 30,
        }),
        max_urls=1, max_queries=1,
    )
    task = ResearchTask(task_id=f"persist-{unique_slug}", page_id=page_id)
    _TASKS[task.task_id] = task
    await researcher.research_page(page_id=page_id, task=task)
    assert task.status == "done"

    # Simulate a restart: drop the in-process cache. Lookups must fall
    # back to the DB row written by mark()/persist().
    cached_id = task.task_id
    _TASKS.pop(cached_id, None)

    rebuilt = await get_task(cached_id)
    assert rebuilt is not None, "task should be reconstructable from the DB"
    assert rebuilt.task_id == cached_id
    assert rebuilt.status == "done"
    assert rebuilt.result is not None and rebuilt.result.get("new_chars", 0) > 0

    # And it must show up in list_recent_tasks even with empty cache.
    history = await list_recent_tasks(limit=10)
    assert any(t.task_id == cached_id for t in history)


@pytest.mark.asyncio
async def test_persistence_filters_by_page_id(unique_slug):
    """list_recent_tasks must accept a page_id filter for 'this page's
    research history' queries."""
    from backend.config import settings

    page_a, _ = await _seed_page(f"a-{unique_slug}")
    page_b, _ = await _seed_page(f"b-{unique_slug}")

    invoker = _make_invoker(
        plan_resp=_mock_plan_response([("q", "i")]),
        synth_resp=_mock_synthesis_response(),
    )
    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker,
        search_fn=_make_search([
            SearchResult(url="https://x.example.com", title="t", snippet=""),
        ]),
        research_fn=_make_research({
            "https://x.example.com": "Content. " * 30,
        }),
        max_urls=1, max_queries=1,
    )
    await researcher.research_page(page_id=page_a)
    await researcher.research_page(page_id=page_b)

    only_a = await list_recent_tasks(limit=20, page_id=page_a)
    assert all(t.page_id == page_a for t in only_a)
    assert any(t.page_id == page_a for t in only_a)


@pytest.mark.asyncio
async def test_task_lifecycle_failed(unique_slug):
    """Failure path: status='failed', error populated, page untouched."""
    from backend.config import settings

    page_id, _ = await _seed_page(unique_slug)
    task = ResearchTask(task_id=f"fail-{unique_slug}", page_id=page_id)
    _TASKS[task.task_id] = task

    invoker = _make_invoker(
        plan_resp='{"queries": []}',  # forces no-queries failure
        synth_resp="(unused)",
    )
    researcher = DeepResearcher(
        data_dir=settings.data_dir,
        llm_invoker=invoker,
        search_fn=_make_search([]),
        research_fn=_make_research({}),
    )
    with pytest.raises(ValueError):
        await researcher.research_page(page_id=page_id, task=task)

    assert task.status == "failed"
    assert task.error and "no queries" in task.error
    assert task.finished_at is not None
