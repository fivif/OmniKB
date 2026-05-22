"""Wiki health analysis (P5).

Two analysers, both pure-Python and dependency-free:

- :func:`run_lint`     finds maintenance issues per-page:
    * orphans         (no incoming OR outgoing edges)
    * contradictions  (pages containing the ``> ⚠ Contradicts:`` block)
    * stale claims    (pages containing ``> 🕒 Superseded by:`` block)
    * empty bodies    (DB row exists but file missing / empty — wiki
                       worker crashed mid-write or never reached the
                       page)
- :func:`graph_insights` finds structural notabilities across pages:
    * surprising connections  (cross-type edges, e.g. source ↔ query)
    * bridges                 (pages connecting many otherwise-disjoint
                               components — degree ≥ 3 across types)
    * knowledge gaps          (low-degree concept / entity pages —
                               candidates for Deep Research expansion)

Why not Louvain? It needs a real graph library (graphology, networkx)
and only pays off for graphs > a few hundred nodes. We deliberately
ship a simpler heuristic so P5 stays additive — when the wiki grows
past the point those heuristics break, that's exactly when we have
data justifying the upgrade.

Both functions are read-only — they never modify pages or the DB.
The chat agent / UI layer is responsible for surfacing suggestions
and asking the user before making any edits.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from storage.metadata_db import (
    list_wiki_pages,
    list_wikilinks,
)

logger = logging.getLogger(__name__)


# ── Issue types ───────────────────────────────────────────────────


@dataclass(slots=True)
class WikiIssue:
    """One actionable lint or insight item.

    The ``severity`` sets how prominently the UI surfaces this:
    ``error``   pages that are *broken* (missing file, malformed)
    ``warning`` pages with maintenance debt (orphan, stale, contradicts)
    ``info``    structural insights (bridge nodes, surprising edges)
    """
    kind:        str                          # short stable identifier
    severity:    str                          # error | warning | info
    title:       str                          # one-line headline
    detail:      str                          # short explanatory paragraph
    page_ids:    list[str] = field(default_factory=list)
    suggestion:  str = ""                     # what an LLM might do next

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind":       self.kind,
            "severity":   self.severity,
            "title":      self.title,
            "detail":     self.detail,
            "page_ids":   self.page_ids,
            "suggestion": self.suggestion,
        }


# Markers we expect the LLM to use when it follows ``schema.md``.
_CONTRADICT_MARKER = re.compile(r"^>\s*⚠\s*Contradicts:", re.MULTILINE)
_SUPERSEDED_MARKER = re.compile(r"^>\s*🕒\s*Superseded\s*by:", re.MULTILINE)


# ── Lint ─────────────────────────────────────────────────────────


async def run_lint(*, data_dir: str | Path) -> list[WikiIssue]:
    """Walk the wiki and return all lint issues.

    Cheap enough to run on every visit to the insights pane — for a
    100-page wiki it's <50 ms. Beyond ~5k pages we'd want incremental
    indexing instead, but that's a different milestone.
    """
    issues: list[WikiIssue] = []
    pages = await list_wiki_pages(limit=2000)
    if not pages:
        return issues

    # Build adjacency (both directions) once for orphan detection.
    edges = await list_wikilinks(limit=20_000)
    in_degree:  dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    for e in edges:
        in_degree[e["dst_page_id"]]  += 1
        out_degree[e["src_page_id"]] += 1

    base = Path(data_dir).expanduser()
    orphan_ids: list[str] = []
    empty_ids:  list[str] = []
    contradicting: list[str] = []
    superseded: list[str] = []

    for page in pages:
        pid = page["id"]
        # ── Orphan check ────────────────────────────────────
        # The single global ``overview`` page is by design never
        # linked from anywhere (and doesn't outbound to one specific
        # page) so we skip it from this rule.
        if page["page_type"] != "overview" and \
                in_degree[pid] == 0 and out_degree[pid] == 0:
            orphan_ids.append(pid)

        # ── Body inspection ─────────────────────────────────
        try:
            file_path = base / page["file_path"]
            if not file_path.is_file() or file_path.stat().st_size < 30:
                empty_ids.append(pid)
                continue
            body = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("lint: read failed for %s: %s", pid, exc)
            empty_ids.append(pid)
            continue

        if _CONTRADICT_MARKER.search(body):
            contradicting.append(pid)
        if _SUPERSEDED_MARKER.search(body):
            superseded.append(pid)

    if orphan_ids:
        issues.append(WikiIssue(
            kind="orphan",
            severity="warning",
            title=f"{len(orphan_ids)} 个孤立页面没有任何出入链接",
            detail=(
                "孤立页面意味着该实体/概念没有被其他页面引用，也没有引用其他"
                "页面。Karpathy 模式中 wiki 的价值正是 cross-reference——可"
                "考虑让 LLM 找到合适的链接，或者评估这个页面是否值得保留。"
            ),
            page_ids=orphan_ids,
            suggestion="运行 lint pass 让 LLM 给孤立页面找出 [[wikilink]] 候选并提交人工评审。",
        ))
    if empty_ids:
        issues.append(WikiIssue(
            kind="empty_body",
            severity="error",
            title=f"{len(empty_ids)} 个页面元数据存在但内容缺失",
            detail=(
                "数据库里有这些页面的行，但磁盘上的 markdown 文件不存在或几乎"
                "为空。通常是 wiki worker 在写盘前崩溃，或文件被外部删除。"
            ),
            page_ids=empty_ids,
            suggestion="重摄入对应的 source，或让 lint pass 重新生成页面。",
        ))
    if contradicting:
        issues.append(WikiIssue(
            kind="contradicts",
            severity="warning",
            title=f"{len(contradicting)} 个页面包含未解决的矛盾标记",
            detail=(
                "页面里有 ``> ⚠ Contradicts:`` 块说明 LLM 摄入新源时发现了"
                "与既有声明冲突的内容。schema 要求保留两个版本等待人工裁决。"
            ),
            page_ids=contradicting,
            suggestion="在 wiki UI 里查看每个页面的矛盾块，决定保留哪个版本（或都保留并加引用）。",
        ))
    if superseded:
        issues.append(WikiIssue(
            kind="superseded",
            severity="info",
            title=f"{len(superseded)} 个页面包含过时声明标记",
            detail=(
                "页面里有 ``> 🕒 Superseded by:`` 块——较新的源已经替代了旧"
                "声明。历史保留在内供回溯，但读者读到主体内容可能并不需要"
                "那段过时信息。"
            ),
            page_ids=superseded,
            suggestion="周期性归档过时段落到一个 ``history`` section，保持页面主体清爽。",
        ))

    return issues


# ── Graph insights ────────────────────────────────────────────────


async def graph_insights(*, knowledge_gap_threshold: int = 1) -> list[WikiIssue]:
    """Compute structural insights from the wikilink graph.

    Three flavours, all derived from edge degrees:

    - **Surprising connections** — edges whose endpoints have very
      different page types (e.g. ``query → source``). These are
      candidates for "you might not have realised these are related"
      callouts.
    - **Bridges** — pages with ≥ 3 outbound edges spanning ≥ 2 distinct
      page types. They glue the wiki together; if any of them goes
      stale, the surrounding map fragments.
    - **Knowledge gaps** — entity / concept pages with total degree
      ≤ ``knowledge_gap_threshold``. Often candidates for Deep Research
      enrichment.
    """
    pages = await list_wiki_pages(limit=2000)
    if len(pages) < 2:
        return []
    edges = await list_wikilinks(limit=20_000)

    type_by_id: dict[str, str] = {p["id"]: p["page_type"] for p in pages}
    title_by_id: dict[str, str] = {p["id"]: p["title"] for p in pages}
    outgoing_types: dict[str, set[str]] = defaultdict(set)
    total_degree: dict[str, int] = defaultdict(int)

    cross_type_edges: list[tuple[str, str, str]] = []   # (src, dst, relation)

    for e in edges:
        src = e["src_page_id"]
        dst = e["dst_page_id"]
        relation = e["relation"]
        st = type_by_id.get(src)
        dt = type_by_id.get(dst)
        if st is None or dt is None:
            continue
        total_degree[src] += 1
        total_degree[dst] += 1
        outgoing_types[src].add(dt)
        if st != dt and not (st == "source" and dt in ("entity", "concept")):
            # source→entity/concept is the trivially expected shape;
            # everything else is "surprising" (entity ↔ query, etc.)
            cross_type_edges.append((src, dst, relation))

    issues: list[WikiIssue] = []

    if cross_type_edges:
        # Cap at the 8 most novel — surfacing too many is noise.
        sample = cross_type_edges[:8]
        page_ids = sorted({pid for triple in sample for pid in triple[:2]})
        bullets = "; ".join(
            f"{title_by_id.get(s, s)} → {title_by_id.get(d, d)} ({r})"
            for s, d, r in sample
        )
        issues.append(WikiIssue(
            kind="surprising_connection",
            severity="info",
            title=f"{len(cross_type_edges)} 条跨类型连接值得注意",
            detail=(
                "这些边连接了不同种类的页面，是 wiki 累积价值的关键体现。"
                "示例：" + bullets
            ),
            page_ids=page_ids,
            suggestion="点击任意页面查看上下文；可考虑把高质量发现固化为一个 ``query`` 页面归档。",
        ))

    bridges = [
        pid for pid, types in outgoing_types.items()
        if len(types) >= 2 and total_degree[pid] >= 3
    ]
    if bridges:
        issues.append(WikiIssue(
            kind="bridge",
            severity="info",
            title=f"{len(bridges)} 个桥接页面连接多种类型",
            detail=(
                "这些页面同时引用了多种类型的内容（实体、概念、来源混合）。"
                "它们是知识图谱的关键节点——如果其中一个长期不更新，周围"
                "的关系可能会脱节。"
            ),
            page_ids=bridges[:20],
            suggestion="周期性查看这些页面是否仍然反映最新理解；过时则触发 Deep Research 更新。",
        ))

    gap_ids = [
        p["id"] for p in pages
        if p["page_type"] in ("entity", "concept")
        and total_degree.get(p["id"], 0) <= knowledge_gap_threshold
    ]
    if gap_ids:
        issues.append(WikiIssue(
            kind="knowledge_gap",
            severity="info",
            title=f"{len(gap_ids)} 个实体/概念页面引用稀疏",
            detail=(
                "这些页面在图谱中几乎是孤岛——它们在某次摄入中被建立，但"
                "后续没有被再次提及。这往往说明对应的话题还没有展开足够的"
                "深度。"
            ),
            page_ids=gap_ids[:30],
            suggestion="选一两个页面跑 Deep Research（让 LLM 主动检索补全），或检查是否值得删除。",
        ))

    return issues
