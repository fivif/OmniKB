"""Tests for wiki.insights.auto_dispatch_from_gaps (Round 13).

The dispatcher's job: given a list of WikiIssues that include
``kind=knowledge_gap`` items, pick the gap pages that:

* are not currently being researched (in-flight task ⇒ skip),
* haven't been researched within the cooldown window (recent ``done``
  / ``failed`` ⇒ skip; ``abandoned`` does NOT count toward cooldown),

and dispatch ``kickoff_research`` for the first ``max_per_run``
survivors. Everyone past the cap goes into ``deferred`` so the UI
can show "5 more candidates queued for tomorrow".

We mock ``kickoff`` so no real research / LLM calls happen; we only
verify the policy + DB integration.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.wiki.insights import WikiIssue, auto_dispatch_from_gaps


# ─── Helpers ──────────────────────────────────────────────────────


async def _seed_simple_page(slug_suffix: str) -> str:
    """Create a tiny entity page; returns ``page_id``."""
    from backend.storage.metadata_db import upsert_wiki_page
    page = await upsert_wiki_page({
        "page_type": "entity",
        "slug": f"gap-{slug_suffix}",
        "title": f"Gap Page {slug_suffix}",
        "summary": "Sparse page that lint flags as a knowledge gap.",
        "frontmatter": {"tags": ["test"]},
        "source_ids": [],
    })
    return page["id"]


def _make_kickoff_recorder():
    """Return ``(kickoff_fn, calls_list)``.

    The fake ``kickoff`` writes a minimal task row to the DB so
    follow-up cooldown checks can see it, and records the call args.
    """
    calls: list[dict] = []

    async def fake_kickoff(*, page_id, focus, data_dir, **_):
        from backend.storage.metadata_db import upsert_wiki_research_task
        import time, uuid
        await upsert_wiki_research_task({
            "task_id":     uuid.uuid4().hex,
            "page_id":     page_id,
            "focus":       focus,
            "status":      "queued",
            "phase_note":  "(test stub)",
            "created_at":  time.time(),
            "finished_at": None,
            "result":      None,
            "error":       None,
        })
        calls.append({"page_id": page_id, "focus": focus, "data_dir": str(data_dir)})

    return fake_kickoff, calls


# ─── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_dispatch_returns_empty_when_no_gap_issues(unique_slug, wiki_data_dir):
    """No knowledge_gap items in the issue list → no work, no DB hits."""
    issues = [
        WikiIssue(kind="orphan", severity="warning", title="x",
                  detail="x", page_ids=["entity:something"]),
    ]
    kickoff, calls = _make_kickoff_recorder()
    report = await auto_dispatch_from_gaps(
        issues, data_dir=wiki_data_dir, max_per_run=3,
        cooldown_hours=24, kickoff=kickoff,
    )
    assert report == {"dispatched": [], "skipped_cooldown": [], "deferred": []}
    assert calls == []


@pytest.mark.asyncio
async def test_auto_dispatch_fires_on_fresh_gaps(unique_slug, wiki_data_dir):
    """Three never-researched gap pages, max_per_run=3 → all three fire."""
    pids = [await _seed_simple_page(f"fresh-{unique_slug}-{i}") for i in range(3)]

    issue = WikiIssue(
        kind="knowledge_gap", severity="info",
        title="3 lonely pages", detail="...",
        page_ids=pids,
    )
    kickoff, calls = _make_kickoff_recorder()
    report = await auto_dispatch_from_gaps(
        [issue], data_dir=wiki_data_dir, max_per_run=3,
        cooldown_hours=24, kickoff=kickoff,
    )

    assert set(report["dispatched"]) == set(pids)
    assert report["skipped_cooldown"] == []
    assert report["deferred"] == []
    assert {c["page_id"] for c in calls} == set(pids)
    # Every kickoff carries the explicit focus tag so future debugging
    # can grep DB rows for "auto-research".
    assert all("auto-research" in c["focus"] for c in calls)


@pytest.mark.asyncio
async def test_auto_dispatch_caps_at_max_per_run(unique_slug, wiki_data_dir):
    """Five gap pages, cap=2 → 2 dispatched, 3 deferred."""
    pids = [await _seed_simple_page(f"cap-{unique_slug}-{i}") for i in range(5)]

    issue = WikiIssue(kind="knowledge_gap", severity="info",
                     title="5 gaps", detail="...", page_ids=pids)
    kickoff, calls = _make_kickoff_recorder()
    report = await auto_dispatch_from_gaps(
        [issue], data_dir=wiki_data_dir, max_per_run=2,
        cooldown_hours=24, kickoff=kickoff,
    )

    assert len(report["dispatched"]) == 2
    assert len(report["deferred"])   == 3
    assert len(calls)                 == 2
    # First 2 fire in input order — keeps tests deterministic.
    assert report["dispatched"] == pids[:2]
    assert report["deferred"]   == pids[2:]


@pytest.mark.asyncio
async def test_auto_dispatch_respects_cooldown(unique_slug, wiki_data_dir):
    """A page researched 1h ago must be skipped when cooldown=24h."""
    pid_recent = await _seed_simple_page(f"cooldown-recent-{unique_slug}")
    pid_eligible = await _seed_simple_page(f"cooldown-eligible-{unique_slug}")

    # Plant a 'done' row for pid_recent at "now - 1h".
    from backend.storage.metadata_db import upsert_wiki_research_task
    import time, uuid
    await upsert_wiki_research_task({
        "task_id":     uuid.uuid4().hex,
        "page_id":     pid_recent,
        "focus":       "previous run",
        "status":      "done",
        "phase_note":  "",
        "created_at":  time.time() - 3600,  # 1h ago
        "finished_at": time.time() - 3500,
        "result":      {"new_chars": 1234},
        "error":       None,
    })

    issue = WikiIssue(kind="knowledge_gap", severity="info",
                     title="2 gaps", detail="...",
                     page_ids=[pid_recent, pid_eligible])
    kickoff, calls = _make_kickoff_recorder()
    report = await auto_dispatch_from_gaps(
        [issue], data_dir=wiki_data_dir, max_per_run=5,
        cooldown_hours=24, kickoff=kickoff,
    )

    assert report["dispatched"]       == [pid_eligible]
    assert report["skipped_cooldown"] == [pid_recent]
    assert [c["page_id"] for c in calls] == [pid_eligible]


@pytest.mark.asyncio
async def test_auto_dispatch_ignores_abandoned_for_cooldown(unique_slug, wiki_data_dir):
    """An 'abandoned' task in the recent window must NOT block re-dispatch."""
    pid = await _seed_simple_page(f"abandoned-{unique_slug}")

    from backend.storage.metadata_db import upsert_wiki_research_task
    import time, uuid
    await upsert_wiki_research_task({
        "task_id":     uuid.uuid4().hex,
        "page_id":     pid,
        "focus":       "previous run that crashed",
        "status":      "abandoned",
        "phase_note":  "Backend restarted while task was in flight",
        "created_at":  time.time() - 600,  # 10 min ago, well inside cooldown
        "finished_at": time.time() - 500,
        "result":      None,
        "error":       "Backend restarted while task was in flight",
    })

    issue = WikiIssue(kind="knowledge_gap", severity="info",
                     title="recovered", detail="...", page_ids=[pid])
    kickoff, calls = _make_kickoff_recorder()
    report = await auto_dispatch_from_gaps(
        [issue], data_dir=wiki_data_dir, max_per_run=5,
        cooldown_hours=24, kickoff=kickoff,
    )

    # Abandoned doesn't trip the cooldown; the page is eligible again.
    assert report["dispatched"]       == [pid]
    assert report["skipped_cooldown"] == []
    assert [c["page_id"] for c in calls] == [pid]


@pytest.mark.asyncio
async def test_auto_dispatch_deduplicates_pages_across_issues(unique_slug, wiki_data_dir):
    """A page appearing in multiple knowledge_gap issues must only fire once."""
    pid = await _seed_simple_page(f"dup-{unique_slug}")

    issue_a = WikiIssue(kind="knowledge_gap", severity="info",
                        title="a", detail="", page_ids=[pid])
    issue_b = WikiIssue(kind="knowledge_gap", severity="info",
                        title="b", detail="", page_ids=[pid, pid])

    kickoff, calls = _make_kickoff_recorder()
    report = await auto_dispatch_from_gaps(
        [issue_a, issue_b],
        data_dir=wiki_data_dir, max_per_run=5,
        cooldown_hours=24, kickoff=kickoff,
    )

    assert report["dispatched"] == [pid]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_auto_dispatch_keeps_going_when_one_kickoff_raises(unique_slug, wiki_data_dir):
    """A failing kickoff must not abort the rest of the batch."""
    pids = [await _seed_simple_page(f"kerror-{unique_slug}-{i}") for i in range(3)]

    fired: list[str] = []

    async def flaky_kickoff(*, page_id, focus, data_dir, **_):
        # Mid-batch raise to verify the dispatcher is resilient.
        if page_id == pids[1]:
            raise RuntimeError("synthetic failure")
        fired.append(page_id)

    issue = WikiIssue(kind="knowledge_gap", severity="info",
                     title="3 gaps", detail="", page_ids=pids)

    report = await auto_dispatch_from_gaps(
        [issue], data_dir=wiki_data_dir, max_per_run=3,
        cooldown_hours=24, kickoff=flaky_kickoff,
    )

    # The dispatcher reports all three as dispatched (it tried), but
    # only the survivors actually fired.
    assert report["dispatched"] == pids
    assert pids[0] in fired
    assert pids[2] in fired
    assert pids[1] not in fired
