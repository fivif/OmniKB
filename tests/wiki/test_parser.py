"""Tests for backend.wiki.parser — the hand-rolled YAML-lite + wikilink parser.

The parser's contract is pure (no DB, no env) so we exercise it in
isolation. Three behaviours matter:

1. ``slugify``         — deterministic + safe under unicode + empty inputs.
2. ``parse_page``      — extracts frontmatter, body, wikilinks; tolerant
                          of missing or malformed frontmatter.
3. ``render_page``     — produces a string ``parse_page`` can read back.

A regression in any of these silently corrupts every wiki page we
generate, so this is the load-bearing test module for the L2 layer.
"""
from __future__ import annotations

from backend.wiki.parser import (
    ParsedPage,
    WikiLinkRef,
    extract_wikilinks,
    parse_page,
    render_page,
    slugify,
)


# ─── slugify ──────────────────────────────────────────────────────


def test_slugify_strips_punctuation_and_lowercases():
    assert slugify("Andrej Karpathy!") == "andrej-karpathy"


def test_slugify_collapses_whitespace_and_hyphens():
    # Multiple spaces + dashes collapse into single hyphens.
    assert slugify("LLM   Wiki  --  Pattern") == "llm-wiki-pattern"


def test_slugify_handles_leading_trailing_whitespace():
    assert slugify("   hello world   ") == "hello-world"


def test_slugify_alphanumerics_with_versions():
    """Dots in version numbers become hyphens; digits preserved."""
    assert slugify("GPT-4o vs Claude 3.5") == "gpt-4o-vs-claude-3-5"


def test_slugify_pure_cjk_uses_md5_fallback():
    """Pure-CJK input has no ASCII transliteration — must hash deterministically."""
    out1 = slugify("中文测试")
    out2 = slugify("中文测试")
    assert out1.startswith("page-"), out1
    assert out1 == out2, "slugify must be deterministic"
    # Different CJK input → different hash
    assert slugify("另一个标题") != out1


def test_slugify_mixed_cjk_and_ascii_keeps_ascii_part():
    """Mixed input keeps the ASCII portion and drops CJK characters."""
    out = slugify("Karpathy 论文")
    assert "karpathy" in out
    # Must not contain raw CJK in the slug
    assert "论" not in out


def test_slugify_empty_returns_unnamed():
    # Documented contract: empty input never returns an empty string.
    assert slugify("") == "unnamed"


def test_slugify_only_punctuation_uses_md5_fallback():
    """Punctuation-only collapses to an empty ASCII core, so the
    fallback hash kicks in (matches pure-CJK behaviour)."""
    out = slugify("!!!---???")
    assert out.startswith("page-"), out
    # Determinism: same input → same hash
    assert slugify("!!!---???") == out


def test_slugify_idempotent_on_already_slugified():
    s1 = slugify("Some Title")
    s2 = slugify(s1)
    assert s1 == s2 == "some-title"


def test_slugify_respects_max_length():
    long_title = "a" * 200
    out = slugify(long_title, max_length=20)
    assert len(out) <= 20


def test_slugify_strips_combining_diacritics():
    """``café`` → ``cafe`` via NFKD decompose + ASCII fold."""
    assert slugify("café") == "cafe"
    assert slugify("naïve") == "naive"


# ─── extract_wikilinks ────────────────────────────────────────────


def test_extract_wikilinks_basic_typed():
    out = extract_wikilinks("See [[entity:andrej-karpathy]] for details.")
    assert len(out) == 1
    link = out[0]
    assert isinstance(link, WikiLinkRef)
    assert link.page_type == "entity"
    assert link.slug == "andrej-karpathy"
    assert link.page_id == "entity:andrej-karpathy"


def test_extract_wikilinks_typed_with_display_text_keeps_link_half():
    out = extract_wikilinks("References [[concept:llm-wiki|the wiki pattern]].")
    assert len(out) == 1
    assert out[0].page_type == "concept"
    assert out[0].slug == "llm-wiki"
    # The display text is discarded — we only need the link half.


def test_extract_wikilinks_bare_slug_has_no_type():
    out = extract_wikilinks("See [[some-slug]] also.")
    assert len(out) == 1
    assert out[0].page_type is None
    assert out[0].slug == "some-slug"
    assert out[0].page_id is None  # contract: bare link has no canonical id


def test_extract_wikilinks_finds_all_links_in_order():
    text = (
        "Karpathy [[entity:andrej-karpathy]] coined [[concept:llm-wiki]]. "
        "Compare with [[concept:rag|RAG]]."
    )
    out = extract_wikilinks(text)
    types = [t.page_type for t in out]
    slugs = [t.slug for t in out]
    assert types == ["entity", "concept", "concept"]
    assert slugs == ["andrej-karpathy", "llm-wiki", "rag"]


def test_extract_wikilinks_deduplicates_identical_references():
    """Same link twice in body → only one entry returned."""
    text = "[[entity:karpathy]] said it. [[entity:karpathy]] meant it."
    out = extract_wikilinks(text)
    assert len(out) == 1


def test_extract_wikilinks_ignores_non_link_brackets():
    """Single brackets and broken pairs must not match."""
    # The regex only requires `[[ <body> ]]` where body has no brackets
    # or newlines. Single brackets and truly-unclosed openings won't match.
    out = extract_wikilinks("[not-a-link] is single. and [[unclosed without close.")
    assert out == []


def test_extract_wikilinks_skips_multiline_links():
    """A link split across newlines is malformed by our schema — skip it."""
    out = extract_wikilinks("This [[link\nspans\nlines]] is malformed.")
    assert out == []


def test_extract_wikilinks_unknown_type_treated_as_bare():
    """``[[xyz:foo]]`` where xyz is not a valid type → bare link with full target as slug."""
    out = extract_wikilinks("See [[bogustype:something]] here.")
    assert len(out) == 1
    assert out[0].page_type is None  # unknown type prefix → bare


def test_extract_wikilinks_empty_input():
    assert extract_wikilinks("") == []
    assert extract_wikilinks("plain text with no links") == []


# ─── parse_page ────────────────────────────────────────────────────


def _sample_page() -> str:
    """A canonical page matching the schema we promise the LLM to follow."""
    return (
        '---\n'
        'title: "Andrej Karpathy"\n'
        'type: "entity"\n'
        'sources: ["s-001", "s-002"]\n'
        'tags: ["ml", "people"]\n'
        'aliases: ["karpathy"]\n'
        '---\n'
        '\n'
        '# Andrej Karpathy\n'
        '\n'
        'Founder of Tesla AI; coined the [[concept:llm-wiki|LLM-Wiki]] pattern.\n'
    )


def test_parse_page_extracts_frontmatter_and_body():
    doc = parse_page(_sample_page())
    assert isinstance(doc, ParsedPage)
    assert doc.frontmatter["title"] == "Andrej Karpathy"
    assert doc.frontmatter["type"] == "entity"
    assert doc.frontmatter["sources"] == ["s-001", "s-002"]
    assert doc.frontmatter["tags"] == ["ml", "people"]
    assert doc.frontmatter["aliases"] == ["karpathy"]
    assert "# Andrej Karpathy" in doc.body
    assert "[[concept:llm-wiki|LLM-Wiki]]" in doc.body


def test_parse_page_extracts_wikilinks_from_body():
    doc = parse_page(_sample_page())
    assert len(doc.wikilinks) == 1
    assert doc.wikilinks[0].page_id == "concept:llm-wiki"


def test_parse_page_no_frontmatter_returns_body_only():
    raw = "# Just A Body\n\nNo frontmatter here.\n"
    doc = parse_page(raw)
    assert doc.frontmatter == {}
    assert "Just A Body" in doc.body


def test_parse_page_tolerates_bom_prefix():
    """Some editors prepend BOM — must not break frontmatter detection."""
    raw = "\ufeff" + _sample_page()
    doc = parse_page(raw)
    assert doc.frontmatter["title"] == "Andrej Karpathy"


def test_parse_page_malformed_frontmatter_does_not_raise():
    """User-edited YAML junk must be tolerated, not crash the worker."""
    raw = "---\nnot: valid: yaml: at all\n  weird indent\n---\n\nbody\n"
    doc = parse_page(raw)
    assert isinstance(doc, ParsedPage)
    assert "body" in doc.body


def test_parse_page_inline_list_with_mixed_types():
    raw = (
        '---\n'
        'tags: [ml, "people", retrieval]\n'
        '---\n'
        '\nbody\n'
    )
    doc = parse_page(raw)
    assert doc.frontmatter["tags"] == ["ml", "people", "retrieval"]


def test_parse_page_block_list_indented_dashes():
    """Block list form: ``key:\\n  - item1\\n  - item2``."""
    raw = (
        '---\n'
        'tags:\n'
        '  - first\n'
        '  - second\n'
        '  - third\n'
        '---\n'
        '\nbody\n'
    )
    doc = parse_page(raw)
    assert doc.frontmatter["tags"] == ["first", "second", "third"]


# ─── render_page ───────────────────────────────────────────────────


def test_render_page_then_parse_round_trips_user_data():
    """Anything the LLM writes should round-trip — timestamps are added by
    render_page automatically, so we compare only the original fields."""
    fm = {
        "title": "RAG",
        "type": "concept",
        "sources": ["s-100"],
        "tags": ["retrieval", "rag"],
        "aliases": [],
    }
    body = "# RAG\n\nRetrieval-augmented generation.\n"

    rendered = render_page(fm, body)
    doc = parse_page(rendered)

    for key in ("title", "type", "sources", "tags", "aliases"):
        assert doc.frontmatter[key] == fm[key], f"key {key!r} did not round-trip"
    assert doc.body.strip().startswith("# RAG")


def test_render_page_fills_timestamps_by_default():
    """``render_page`` should attach ``created_at`` + ``updated_at`` when
    they're missing — that's how P2 keeps the audit trail honest."""
    rendered = render_page(
        {"title": "X", "type": "concept", "sources": [], "tags": [], "aliases": []},
        "body\n",
    )
    doc = parse_page(rendered)
    assert "created_at" in doc.frontmatter
    assert "updated_at" in doc.frontmatter


def test_render_page_unicode_titles_survive_round_trip():
    fm = {"title": "中文条目", "type": "entity", "sources": [], "tags": [], "aliases": []}
    body = "# 中文条目\n\n这是一段中文。\n"
    rendered = render_page(fm, body)
    doc = parse_page(rendered)
    assert doc.frontmatter["title"] == "中文条目"
    assert "中文" in doc.body


def test_render_page_can_skip_timestamps():
    """``fill_timestamps=False`` for tests + deterministic snapshots."""
    rendered = render_page(
        {"title": "X", "type": "concept", "sources": [], "tags": [], "aliases": []},
        "body\n",
        fill_timestamps=False,
    )
    doc = parse_page(rendered)
    assert "created_at" not in doc.frontmatter
    assert "updated_at" not in doc.frontmatter


def test_render_page_string_with_colon_round_trips():
    """A title containing a colon (common in academic-style titles) must
    parse back unchanged — that's why we quote unconditionally."""
    fm = {
        "title": "OmniKB: a two-layer system",
        "type": "concept",
        "sources": [],
        "tags": [],
        "aliases": [],
    }
    rendered = render_page(fm, "body\n", fill_timestamps=False)
    doc = parse_page(rendered)
    assert doc.frontmatter["title"] == "OmniKB: a two-layer system"
