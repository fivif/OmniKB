"""Tests for backend.wiki.retriever — tokenisation + ranked search.

Two layers:

1. **Synchronous tokenisation tests** — exercise ``_tokenize`` in
   isolation (no DB). These guard the bilingual contract: English
   words + CJK bigrams + stopword filtering must all stay correct
   because they're the foundation of every score.

2. **Async retrieval tests** — exercise ``search_wiki_pages`` against
   a freshly-seeded set of pages. We assert relative ordering rather
   than exact scores so the tests stay robust to scoring tweaks.

Each test seeds its own pages with ``unique_slug`` so concurrent test
runs don't trip over each other inside the shared session DB.
"""
from __future__ import annotations

import pytest

# Module-level import is safe — backend.wiki.retriever only imports
# storage.metadata_db lazily inside async functions.
from backend.wiki.retriever import (
    WikiHit,
    _tokenize,
    read_page_body,
    search_wiki_pages,
)


# ─── Tokenisation (sync, no DB) ──────────────────────────────────


def test_tokenize_basic_english_words():
    out = _tokenize("Andrej Karpathy describes the LLM-Wiki pattern.")
    assert "karpathy" in out
    assert "andrej" in out
    assert "llm-wiki" in out
    assert "pattern" in out


def test_tokenize_drops_english_stopwords():
    out = _tokenize("the cat is in the hat")
    # All four content words survive; the four stopwords don't.
    for stop in ("the", "is", "in"):
        assert stop not in out
    assert "cat" in out and "hat" in out


def test_tokenize_drops_short_tokens():
    """Single-letter or empty tokens add no signal and only inflate scores."""
    out = _tokenize("a b c hello")
    assert out == ["hello"]


def test_tokenize_cjk_bigrams():
    out = _tokenize("知识库的检索路径")
    # 4-char "知识库的" generates bigrams 知识 / 识库; "的" is a stopword;
    # 检索路径 → 检索 / 索路 / 路径.
    assert "知识" in out
    assert "识库" in out
    assert "检索" in out


def test_tokenize_cjk_stopword_particles_filtered():
    """Particle ``的`` must be stripped from bigrams AND single-char runs."""
    out = _tokenize("Karpathy 的 LLM-Wiki")
    assert "的" not in out
    assert "karpathy" in out
    assert "llm-wiki" in out


def test_tokenize_mixed_cn_en_preserves_both_sides():
    out = _tokenize("Karpathy 的 LLM-Wiki 模式")
    assert "karpathy" in out
    assert "llm-wiki" in out
    assert "模式" in out


def test_tokenize_lowercases_english():
    out = _tokenize("HELLO World KARPATHY")
    assert "hello" in out
    assert "world" in out
    assert "karpathy" in out
    # All-uppercase should not leak through
    assert "KARPATHY" not in out


def test_tokenize_empty_input_returns_empty_list():
    assert _tokenize("") == []
    assert _tokenize(None or "") == []


def test_tokenize_only_punctuation_returns_empty():
    assert _tokenize("!!! ??? ,,,") == []


# ─── search_wiki_pages (async, uses session DB) ───────────────────


async def _seed_pages(prefix: str) -> dict[str, str]:
    """Seed a small set of pages and return ``{name: page_id}``."""
    from backend.storage.metadata_db import upsert_wiki_page

    pages = [
        ("entity", f"karpathy-{prefix}", "Andrej Karpathy",
         "Founder of Tesla AI, originator of LLM-Wiki pattern.",
         ["ml", "people"]),
        ("concept", f"llm-wiki-{prefix}", "LLM-Wiki",
         "Persistent compounding knowledge artifact.",
         ["knowledge-base"]),
        ("concept", f"rag-{prefix}", "RAG",
         "Retrieval-augmented generation — chunk and embed.",
         ["retrieval", "rag"]),
        ("source", f"src-{prefix}", "Karpathy Gist",
         "The seed gist by Karpathy describing LLM-Wiki.",
         ["seed", "ml"]),
    ]
    ids = {}
    for ptype, slug, title, summary, tags in pages:
        await upsert_wiki_page({
            "page_type": ptype,
            "slug": slug,
            "title": title,
            "summary": summary,
            "frontmatter": {"tags": tags},
            "source_ids": [],
        })
        ids[title] = f"{ptype}:{slug}"
    return ids


@pytest.mark.asyncio
async def test_search_wiki_pages_matches_by_title(unique_slug):
    ids = await _seed_pages(f"title-{unique_slug}")
    hits = await search_wiki_pages("Andrej Karpathy biography", top_k=3)
    # Top hit should be the Karpathy entity (highest title score)
    assert len(hits) >= 1
    assert isinstance(hits[0], WikiHit)
    assert hits[0].page_id == ids["Andrej Karpathy"]


@pytest.mark.asyncio
async def test_search_wiki_pages_matches_by_summary(unique_slug):
    ids = await _seed_pages(f"summary-{unique_slug}")
    # Query that only matches LLM-Wiki via the word "compounding" in summary
    hits = await search_wiki_pages("compounding artifact", top_k=3)
    assert any(h.page_id == ids["LLM-Wiki"] for h in hits)


@pytest.mark.asyncio
async def test_search_wiki_pages_matches_by_tag(unique_slug):
    ids = await _seed_pages(f"tag-{unique_slug}")
    # Tag-only query should still find RAG via "retrieval" tag
    hits = await search_wiki_pages("retrieval", top_k=3)
    assert any(h.page_id == ids["RAG"] for h in hits)


@pytest.mark.asyncio
async def test_search_wiki_pages_returns_empty_on_junk_query(unique_slug):
    await _seed_pages(f"junk-{unique_slug}")
    hits = await search_wiki_pages("xyzzy plugh nonsense", top_k=5)
    assert hits == []


@pytest.mark.asyncio
async def test_search_wiki_pages_respects_top_k(unique_slug):
    await _seed_pages(f"topk-{unique_slug}")
    # Broad query that matches multiple pages
    hits = await search_wiki_pages("karpathy llm-wiki retrieval", top_k=2)
    assert len(hits) <= 2


@pytest.mark.asyncio
async def test_search_wiki_pages_filters_by_page_type(unique_slug):
    ids = await _seed_pages(f"type-{unique_slug}")
    hits = await search_wiki_pages(
        "karpathy llm-wiki", top_k=10, page_types=["entity"]
    )
    # No concept / source pages should appear
    assert all(h.page_type == "entity" for h in hits)
    assert any(h.page_id == ids["Andrej Karpathy"] for h in hits)


@pytest.mark.asyncio
async def test_search_wiki_pages_min_score_filter(unique_slug):
    await _seed_pages(f"minscore-{unique_slug}")
    # Very high min_score → nothing should pass
    hits = await search_wiki_pages("rag", top_k=5, min_score=1000.0)
    assert hits == []


@pytest.mark.asyncio
async def test_search_wiki_pages_reports_matched_tokens(unique_slug):
    ids = await _seed_pages(f"matched-{unique_slug}")
    hits = await search_wiki_pages("karpathy founder", top_k=3)
    # The Karpathy page should report 'karpathy' and 'founder' in matched
    karpathy_hit = next((h for h in hits if h.page_id == ids["Andrej Karpathy"]), None)
    assert karpathy_hit is not None
    assert "karpathy" in karpathy_hit.matched
    # 'founder' is in summary, also picked up
    assert "founder" in karpathy_hit.matched


@pytest.mark.asyncio
async def test_search_wiki_pages_empty_query_returns_nothing(unique_slug):
    await _seed_pages(f"empty-{unique_slug}")
    assert await search_wiki_pages("", top_k=5) == []
    assert await search_wiki_pages("   ", top_k=5) == []


@pytest.mark.asyncio
async def test_search_wiki_pages_scoring_orders_title_above_summary(unique_slug):
    """Title matches must outrank summary-only matches because
    the retriever's weights say so (4 vs 2)."""
    from backend.storage.metadata_db import upsert_wiki_page

    suffix = f"order-{unique_slug}"
    await upsert_wiki_page({
        "page_type": "entity", "slug": f"alpha-{suffix}",
        "title": "Quantum Computing",  # match in title
        "summary": "Generic placeholder.",
        "frontmatter": {"tags": []},
        "source_ids": [],
    })
    await upsert_wiki_page({
        "page_type": "concept", "slug": f"beta-{suffix}",
        "title": "Some Concept",
        "summary": "Quantum computing is mentioned only here.",  # match in summary
        "frontmatter": {"tags": []},
        "source_ids": [],
    })

    hits = await search_wiki_pages("quantum computing", top_k=10)
    titles_in_order = [h.title for h in hits if h.slug.endswith(suffix)]
    # The page with quantum/computing in TITLE must come before the
    # page with it only in summary.
    assert titles_in_order[0] == "Quantum Computing", titles_in_order


# ─── read_page_body ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_page_body_returns_row_and_body(wiki_data_dir, unique_slug):
    from backend.storage.metadata_db import upsert_wiki_page
    from backend.wiki.bootstrap import page_path

    slug = f"readbody-{unique_slug}"
    page_id = f"concept:{slug}"
    await upsert_wiki_page({
        "page_type": "concept", "slug": slug,
        "title": "Read Body Test",
        "summary": "A page with a real on-disk body.",
        "frontmatter": {"tags": []},
        "source_ids": [],
    })
    body_text = "# Read Body Test\n\nReal content lives here.\n"
    page_path(wiki_data_dir, "concept", slug).write_text(body_text, encoding="utf-8")

    row, body = await read_page_body(page_id, data_dir=wiki_data_dir)
    assert row is not None
    assert row["title"] == "Read Body Test"
    assert body is not None
    assert "Real content lives here" in body


@pytest.mark.asyncio
async def test_read_page_body_unknown_id_returns_none_none(wiki_data_dir):
    row, body = await read_page_body("entity:does-not-exist", data_dir=wiki_data_dir)
    assert row is None
    assert body is None


@pytest.mark.asyncio
async def test_read_page_body_missing_file_returns_row_with_no_body(wiki_data_dir, unique_slug):
    """DB row exists but the file was deleted — row returned, body is None
    (the caller is expected to surface "wiki worker still generating" UX)."""
    from backend.storage.metadata_db import upsert_wiki_page

    slug = f"missing-{unique_slug}"
    page_id = f"entity:{slug}"
    await upsert_wiki_page({
        "page_type": "entity", "slug": slug,
        "title": "Missing File",
        "summary": "Metadata only.",
        "frontmatter": {"tags": []},
        "source_ids": [],
    })
    # Don't write the body file at all.

    row, body = await read_page_body(page_id, data_dir=wiki_data_dir)
    assert row is not None
    assert body is None


@pytest.mark.asyncio
async def test_read_page_body_respects_max_chars(wiki_data_dir, unique_slug):
    from backend.storage.metadata_db import upsert_wiki_page
    from backend.wiki.bootstrap import page_path

    slug = f"truncate-{unique_slug}"
    page_id = f"source:{slug}"
    await upsert_wiki_page({
        "page_type": "source", "slug": slug,
        "title": "Big Body",
        "summary": "x",
        "frontmatter": {"tags": []},
        "source_ids": [],
    })
    big = "a" * 10_000
    page_path(wiki_data_dir, "source", slug).write_text(big, encoding="utf-8")

    _, body = await read_page_body(page_id, data_dir=wiki_data_dir, max_chars=200)
    assert body is not None
    assert len(body) == 200
