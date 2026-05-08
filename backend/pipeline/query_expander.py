"""Query expansion for broad/compound search queries.

Automatically detects queries that are too broad or contain multiple sub-questions,
and expands them into multiple targeted sub-queries for better retrieval coverage.
"""
from __future__ import annotations

import re

# Patterns that indicate a broad query needing expansion
_BROAD_PATTERNS = [
    r"(?:列举|列出|有哪些|包含哪些|所有|全部)",
    r"(?:what are|list|all|every)",
]

# Domain-specific expansion rules for the DeepSeek knowledge base
_DOMAIN_EXPANSIONS: dict[str, list[str]] = {
    "产品": [
        "DeepSeek-V4",
        "DeepSeek-V3",
        "DeepSeek-R1",
        "DeepSeek-Coder",
        "DeepSeek-VL2",
        "DeepSeek-OCR",
        "DeepSeek-Prover",
    ],
    "模型": [
        "DeepSeek-V4",
        "DeepSeek-V3",
        "DeepSeek-R1",
        "DeepSeek-Coder",
        "DeepSeek-VL2",
        "DeepSeek-OCR",
        "DeepSeek-Prover",
    ],
    "model": [
        "DeepSeek-V4",
        "DeepSeek-V3",
        "DeepSeek-R1",
        "DeepSeek-Coder",
        "DeepSeek-VL2",
        "DeepSeek-OCR",
        "DeepSeek-Prover",
    ],
    "基准": [
        "MMLU",
        "AIME",
        "MATH-500",
        "Codeforces",
        "HumanEval",
        "GPQA",
    ],
    "benchmark": [
        "MMLU",
        "AIME",
        "MATH-500",
        "Codeforces",
        "HumanEval",
        "GPQA-Diamond",
    ],
    "价格": [
        "pricing input",
        "pricing output",
        "cache hit price",
        "deepseek-v4-flash price",
        "deepseek-v4-pro price",
    ],
    "pricing": [
        "input cost per million",
        "output cost per million",
        "cache hit",
    ],
    "API": [
        "base URL",
        "authentication",
        "rate limit",
        "error code",
        "model list",
        "function calling",
    ],
}


def should_expand(query: str) -> bool:
    """Check if a query is broad enough to warrant expansion."""
    for pattern in _BROAD_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            return True
    return False


def expand_query(query: str, top_k: int = 5) -> list[str]:
    """Expand a broad/compound query into multiple sub-queries.

    Returns the original query plus any expanded sub-queries.
    For compound questions (containing '和', '与', 'and'), splits into
    individual sub-questions.
    """
    sub_queries = [query]

    # Compound question detection
    compound_delimiters = [r"(?:和|与|以及|还有|、)", r"(?:and|vs|versus)"]
    for delim in compound_delimiters:
        parts = re.split(delim, query, maxsplit=3)
        if len(parts) >= 2:
            for part in parts:
                part = part.strip()
                if len(part) > 3 and part not in sub_queries:
                    sub_queries.append(part)

    # Domain-specific expansion
    query_lower = query.lower()
    for keyword, expansions in _DOMAIN_EXPANSIONS.items():
        if keyword in query_lower:
            sub_queries.extend(expansions)

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for q in sub_queries:
        if q not in seen:
            seen.add(q)
            deduped.append(q)

    # Limit total sub-queries
    return deduped[:top_k + 2]


def merge_results(all_results: list[list[dict]], max_total: int = 10) -> list[dict]:
    """Merge and interleave results from multiple sub-queries.

    Uses round-robin to ensure diversity across sub-queries,
    then deduplicates by chunk ID.
    """
    seen_ids = set()
    merged = []

    # Round-robin interleaving
    max_len = max(len(r) for r in all_results) if all_results else 0
    for i in range(max_len):
        for rl in all_results:
            if i < len(rl):
                r = rl[i]
                rid = r.get("id", "")
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    merged.append(r)
                    if len(merged) >= max_total:
                        return merged
    return merged[:max_total]
