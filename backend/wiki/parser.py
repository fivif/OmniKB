"""Wiki markdown parser — frontmatter + wikilinks.

Why hand-rolled instead of pyyaml + a markdown lib?
- Frontmatter for OmniKB pages is ALWAYS the same schema (six keys,
  three of them lists of strings). A 60-line dedicated parser handles
  it without dragging pyyaml into the dependency closure.
- Wikilinks are a single regex; no AST needed.
- Keeps ``backend/wiki/`` self-contained: no surprise upgrades, no CVE
  surface, easy to reason about for the LLM-driven content path that
  exercises it on every ingest.

Public surface
--------------
- ``parse_page(text)`` → ``ParsedPage(frontmatter, body, wikilinks)``
- ``render_page(frontmatter, body)`` → string suitable for disk
- ``extract_wikilinks(body)`` → list of ``WikiLinkRef``
- ``slugify(text)`` → URL-safe ASCII slug

This module is pure (no I/O, no async). Tested via ``run_self_check``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# Frontmatter delimiters — must be at the very start of the file and
# match the canonical YAML triple-dash convention. We don't accept
# leading whitespace before the first ``---`` to keep things tight.
_FM_RE = re.compile(r"^---\s*\n(?P<fm>.*?)\n---\s*\n?", re.DOTALL)

# Wikilink syntax. We accept both the typed form ``[[type:slug]]`` and
# the bare ``[[slug]]`` form (which downstream code resolves against
# the page being parsed).
_WIKILINK_RE = re.compile(
    r"\[\[(?P<body>[^\[\]\n]+?)\]\]"
)

# Allowed page types — kept here AND in storage.metadata_db so the
# parser can validate without importing the DB module (avoid cycle).
_VALID_TYPES = ("entity", "concept", "source", "query", "overview")


@dataclass(slots=True)
class WikiLinkRef:
    """One ``[[wikilink]]`` reference extracted from a page body."""
    raw:        str          # the original "[[..]]" text including brackets
    target:     str          # everything between the brackets
    page_type:  str | None   # parsed type prefix when present, else None
    slug:       str          # the slug part
    @property
    def page_id(self) -> str | None:
        """Return ``"<type>:<slug>"`` when a type was specified, else None.
        Bare ``[[slug]]`` references resolve to None and the caller has
        to figure out the type from context."""
        if self.page_type:
            return f"{self.page_type}:{self.slug}"
        return None


@dataclass(slots=True)
class ParsedPage:
    """Result of parsing a wiki markdown file."""
    frontmatter: dict[str, Any]
    body:        str
    wikilinks:   list[WikiLinkRef] = field(default_factory=list)


# ── Slugify ──────────────────────────────────────────────────────────


def slugify(text: str, *, max_length: int = 80) -> str:
    """Produce a URL-safe ASCII slug from arbitrary text.

    Strategy: NFKD-decompose, drop combining marks (so ``café`` →
    ``cafe``), lowercase, replace non-alphanumerics with hyphens,
    collapse runs, trim. Empty input becomes ``unnamed-<hash>``-style
    so the caller never gets a degenerate empty slug.
    """
    if not text:
        return "unnamed"
    norm = unicodedata.normalize("NFKD", text)
    ascii_only = norm.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower()
    # Replace any run of non-[a-z0-9] with a single hyphen.
    slug = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    if not slug:
        # Fallback: ASCII didn't survive (pure CJK input). Hash for
        # determinism, prefixed so it's recognisable.
        import hashlib
        h = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
        return f"page-{h}"
    return slug[:max_length].rstrip("-") or "unnamed"


# ── Frontmatter (yaml-lite) ─────────────────────────────────────────


def _parse_yaml_lite(text: str) -> dict[str, Any]:
    """Tiny YAML subset parser supporting:
    - ``key: "string"``  / ``key: string``  / ``key: 123``  / ``key: true``
    - ``key: [a, b, c]`` (inline list of strings/numbers/bools)
    - ``key:\\n  - item1\\n  - item2`` (block list, 2-space indent)

    Anything else returns ``None`` for that key (best-effort). Caller
    is responsible for type-checking.
    """
    out: dict[str, Any] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue

        key, _, raw_val = line.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()

        # Block list: empty value, following lines start with ``  - ``.
        if raw_val == "":
            block_items: list[Any] = []
            j = i + 1
            while j < len(lines) and lines[j].lstrip().startswith("- "):
                item = lines[j].lstrip()[2:].strip()
                block_items.append(_parse_scalar(item))
                j += 1
            out[key] = block_items
            i = j
            continue

        out[key] = _parse_scalar(raw_val)
        i += 1
    return out


def _parse_scalar(raw: str) -> Any:
    """Convert one YAML scalar to a Python value."""
    raw = raw.strip()
    if not raw:
        return ""

    # Inline list
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        # Naive split on commas not inside quotes — good enough for
        # the controlled surface area we generate.
        items: list[Any] = []
        depth = 0
        buf = ""
        in_quote = ""
        for ch in inner:
            if in_quote:
                buf += ch
                if ch == in_quote:
                    in_quote = ""
                continue
            if ch in "\"'":
                in_quote = ch
                buf += ch
                continue
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            if ch == "," and depth == 0:
                items.append(_parse_scalar(buf))
                buf = ""
            else:
                buf += ch
        if buf.strip():
            items.append(_parse_scalar(buf))
        return items

    # Quoted string
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]

    # Booleans / null
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if raw in ("null", "None", "~"):
        return None

    # Number
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass

    return raw  # bare string


def _dump_yaml_lite(data: dict[str, Any]) -> str:
    """Serialise the same subset back to YAML. Stable key order =
    insertion order, which matches Python dict semantics on 3.7+."""
    out: list[str] = []
    for key, value in data.items():
        out.append(f"{key}: {_dump_scalar(value)}")
    return "\n".join(out)


def _dump_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        rendered = [_dump_scalar(v) for v in value]
        return "[" + ", ".join(rendered) + "]"
    # String — always quote with double quotes, escape any embedded ones.
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


# ── Public API ───────────────────────────────────────────────────────


def parse_page(text: str) -> ParsedPage:
    """Split a wiki page string into ``frontmatter`` + ``body`` + extracted
    wikilinks. Returns empty frontmatter when the file has none — the
    body is still extracted so partial / malformed pages don't crash
    the worker."""
    text = text.lstrip("\ufeff")  # strip BOM if some editor wrote one
    m = _FM_RE.match(text)
    if m:
        fm = _parse_yaml_lite(m.group("fm"))
        body = text[m.end():]
    else:
        fm = {}
        body = text

    return ParsedPage(
        frontmatter=fm,
        body=body,
        wikilinks=extract_wikilinks(body),
    )


def render_page(
    frontmatter: dict[str, Any],
    body: str,
    *,
    fill_timestamps: bool = True,
) -> str:
    """Inverse of :func:`parse_page`: produce the on-disk markdown form."""
    fm = dict(frontmatter)  # shallow copy; we may mutate
    if fill_timestamps:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fm.setdefault("created_at", now)
        # Always refresh updated_at on every render — that's the point.
        fm["updated_at"] = now
    head = _dump_yaml_lite(fm)
    body = body.lstrip("\n")
    return f"---\n{head}\n---\n\n{body}\n" if not body.endswith("\n") else f"---\n{head}\n---\n\n{body}"


def extract_wikilinks(body: str) -> list[WikiLinkRef]:
    """Find every ``[[...]]`` reference in a block of markdown."""
    out: list[WikiLinkRef] = []
    seen: set[tuple[str | None, str]] = set()
    for m in _WIKILINK_RE.finditer(body):
        target = m.group("body").strip()
        if not target:
            continue
        if "|" in target:
            # ``[[type:slug|display text]]`` — we only care about the link half.
            target = target.split("|", 1)[0].strip()
        if ":" in target:
            ptype, _, slug = target.partition(":")
            ptype = ptype.strip().lower()
            if ptype not in _VALID_TYPES:
                # Treat as a bare slug containing a colon.
                ptype = None
                slug = target
        else:
            ptype = None
            slug = target
        slug = slugify(slug)
        key = (ptype, slug)
        if key in seen:
            continue
        seen.add(key)
        out.append(WikiLinkRef(
            raw=m.group(0),
            target=target,
            page_type=ptype,
            slug=slug,
        ))
    return out


# ── Self-check (runnable as ``python -m wiki.parser``) ──────────────


def run_self_check() -> None:
    sample = """---
title: "Andrej Karpathy"
type: "entity"
sources: ["s-001", "s-002"]
tags: [ml, people]
aliases: ["AK"]
created_at: "2026-05-21T18:00:00+00:00"
updated_at: "2026-05-21T18:00:00+00:00"
---

# Andrej Karpathy

Originator of the [[concept:llm-wiki]] pattern (s-001). Frequently cited
together with [[entity:vannevar-bush]] (s-002). See also [[plain-link]].
"""
    parsed = parse_page(sample)
    assert parsed.frontmatter["title"] == "Andrej Karpathy"
    assert parsed.frontmatter["type"] == "entity"
    assert parsed.frontmatter["sources"] == ["s-001", "s-002"]
    assert parsed.frontmatter["tags"] == ["ml", "people"]
    assert parsed.frontmatter["aliases"] == ["AK"]
    assert "# Andrej Karpathy" in parsed.body
    assert len(parsed.wikilinks) == 3, f"expected 3 wikilinks, got {len(parsed.wikilinks)}"
    typed = [w for w in parsed.wikilinks if w.page_id]
    assert len(typed) == 2
    assert {w.page_id for w in typed} == {"concept:llm-wiki", "entity:vannevar-bush"}

    # Round-trip
    rendered = render_page(parsed.frontmatter, parsed.body, fill_timestamps=False)
    parsed2 = parse_page(rendered)
    assert parsed2.frontmatter["title"] == "Andrej Karpathy"
    assert parsed2.frontmatter["sources"] == ["s-001", "s-002"]

    # Slugify
    assert slugify("Andrej Karpathy") == "andrej-karpathy"
    assert slugify("RAG vs. LLM-Wiki!") == "rag-vs-llm-wiki"
    assert slugify("café résumé") == "cafe-resume"
    assert slugify("中文测试").startswith("page-")  # CJK falls back to hash
    assert slugify("") == "unnamed"

    print("wiki.parser self-check OK")


if __name__ == "__main__":
    run_self_check()
