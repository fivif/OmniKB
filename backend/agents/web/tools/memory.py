"""Skill memory: persist successful execution recipes for re-use.

recall_skill(query, url): top-k similar past skills (regex match on url + cosine
on dense embedding of name + description).
save_skill(...):           crystallize a successful execution path.
load_seed_skills_if_empty: read seed markdown files into DB on first start.

Embeddings are produced via pipeline.embedder.embed_dense (BGE-M3 by default,
1024 dims, float32). Stored as raw bytes in skills.embedding column. When the
embedder is unavailable, skills are saved without embeddings and recall falls
back to regex-only matching.
"""
from __future__ import annotations

import json
import logging
import re
import struct
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(__file__).resolve().parent.parent / "seeds"


# ── Embedding helpers ────────────────────────────────────────

def _floats_to_bytes(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _bytes_to_floats(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


async def _embed(text: str) -> bytes | None:
    try:
        from pipeline.embedder import embed_dense
        vecs = await embed_dense([text])
        if vecs and vecs[0]:
            return _floats_to_bytes(vecs[0])
    except Exception as exc:
        logger.debug("skill embed failed: %s", exc)
    return None


def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── Seed loader ───────────────────────────────────────────────

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter (very minimal: key: value lines)."""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    front_block, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in front_block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body.strip()


async def load_seed_skills_if_empty(seeds_dir: Path = _SEEDS_DIR) -> int:
    """Read seed markdown files into the DB on first start. Returns count loaded."""
    from storage.metadata_db import count_skills, upsert_skill
    if await count_skills() > 0:
        return 0
    if not seeds_dir.is_dir():
        logger.info("no seeds dir at %s, skipping seed load", seeds_dir)
        return 0

    loaded = 0
    for md_path in sorted(seeds_dir.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name") or md_path.stem
            description = meta.get("description", "")
            url_pattern = meta.get("url_pattern", "")
            recipe = json.dumps({
                "source": "seed",
                "body": body,
            }, ensure_ascii=False)
            embedding = await _embed(f"{name}\n{description}")
            await upsert_skill({
                "id": str(uuid.uuid4()),
                "name": name,
                "url_pattern": url_pattern,
                "description": description,
                "recipe": recipe,
                "embedding": embedding,
            })
            loaded += 1
        except Exception as exc:
            logger.warning("seed skill %s failed: %s", md_path.name, exc)

    logger.info("Loaded %d seed skills from %s", loaded, seeds_dir)
    return loaded


# ── Public agent tools ────────────────────────────────────────

async def recall_skill(query: str = "", url: str = "", top_k: int = 3) -> str:
    """Retrieve up to *top_k* skills relevant to *query* and/or *url*.

    Ranking:
      1. Skills whose url_pattern regex-matches *url* are boosted
      2. Cosine similarity of (query) embedding against skills.embedding
      3. Tiebreak by success_count desc, then last_used_at desc

    Returns a formatted string suitable for inclusion in an LLM system prompt.
    """
    from storage.metadata_db import list_skills
    skills = await list_skills()
    if not skills:
        return ""

    q_vec = None
    if query.strip():
        q_blob = await _embed(query)
        if q_blob:
            q_vec = _bytes_to_floats(q_blob)

    scored = []
    for s in skills:
        score = 0.0
        if url and s.get("url_pattern"):
            try:
                if re.search(s["url_pattern"], url):
                    score += 1.0
            except re.error:
                pass
        if q_vec is not None and s.get("embedding"):
            try:
                v = _bytes_to_floats(s["embedding"])
                score += _cosine(q_vec, v)
            except Exception:
                pass
        score += 0.001 * (s.get("success_count") or 0)
        scored.append((score, s))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = [s for sc, s in scored[:top_k] if sc > 0]
    if not top:
        return ""

    blocks = []
    for s in top:
        recipe = s.get("recipe", "{}")
        try:
            r = json.loads(recipe)
            recipe_text = r.get("body", recipe) if isinstance(r, dict) else str(recipe)
        except Exception:
            recipe_text = recipe
        blocks.append(
            f"## Skill: {s['name']}\n"
            f"For URLs matching: {s.get('url_pattern') or '(any)'}\n"
            f"What: {s.get('description', '')}\n\n"
            f"{recipe_text[:1200]}"
        )
    return "\n\n---\n\n".join(blocks)


async def save_skill(name: str, url_pattern: str, description: str, recipe) -> str:
    """Persist a successful execution path. Returns the new skill ID."""
    from storage.metadata_db import upsert_skill
    if isinstance(recipe, (dict, list)):
        recipe_str = json.dumps(recipe, ensure_ascii=False)
    else:
        recipe_str = str(recipe)
    embedding = await _embed(f"{name}\n{description}")
    sid = str(uuid.uuid4())
    await upsert_skill({
        "id": sid,
        "name": name,
        "url_pattern": url_pattern,
        "description": description,
        "recipe": recipe_str,
        "embedding": embedding,
    })
    return sid
