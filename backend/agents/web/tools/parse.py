"""Atomic parsing tools — replaces a code_run sandbox for common scrape patterns.

Exposes html_query / regex_extract / json_path / text_search as LangChain tools.
The LLM uses these to slice up content fetched by http_get / browser_get_text.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import tool


@tool
def html_query(html: str, css: str, max_results: int = 10) -> str:
    """Run a CSS selector against an HTML string. Returns up to max_results
    text snippets (one per match), separated by '\n---\n'.

    Examples:
      html_query(html, "h1") -> top headings
      html_query(html, "table.data tr") -> table rows
      html_query(html, "a[href*='/blog/']") -> blog links
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "[html_query: bs4 missing]"
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        nodes = soup.select(css)[:max_results]
        return "\n---\n".join(n.get_text(" ", strip=True) for n in nodes) or "[no matches]"
    except Exception as exc:
        return f"[html_query error: {exc}]"


@tool
def regex_extract(text: str, pattern: str, max_matches: int = 20) -> str:
    """Find all regex matches in text. Returns matches as JSON array (groups joined).
    Use Python re syntax; flags can be embedded as (?i)(?m).
    """
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"[regex compile error: {exc}]"
    matches = []
    for m in rx.finditer(text or ""):
        if m.groups():
            matches.append(list(m.groups()))
        else:
            matches.append(m.group(0))
        if len(matches) >= max_matches:
            break
    return json.dumps(matches, ensure_ascii=False)


@tool
def json_path(json_str: str, path: str) -> str:
    """Navigate a JSON document using dotted path with [index] for arrays.

    Examples:
      json_path(s, "name") -> root.name
      json_path(s, "items[0].title") -> first item's title
      json_path(s, "data.users[2].profile.email")

    Returns the matched value as a JSON-encoded string. Use empty path to dump root.
    """
    try:
        data = json.loads(json_str or "{}")
    except json.JSONDecodeError as exc:
        return f"[json parse error: {exc}]"
    if not path.strip():
        return json.dumps(data, ensure_ascii=False)[:8000]

    cur: Any = data
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    for raw in parts:
        if raw.startswith("["):
            try:
                idx = int(raw[1:-1])
                cur = cur[idx]
            except (IndexError, ValueError, TypeError):
                return f"[index out of range or wrong type at '{raw}']"
        else:
            if isinstance(cur, dict):
                if raw not in cur:
                    return f"[key '{raw}' not found]"
                cur = cur[raw]
            else:
                return f"[expected dict at '{raw}', got {type(cur).__name__}]"
    if isinstance(cur, (dict, list)):
        return json.dumps(cur, ensure_ascii=False)[:8000]
    return str(cur)


@tool
def text_search(text: str, query: str, context_chars: int = 200) -> str:
    """Find first occurrence of *query* (case-insensitive) in text;
    return surrounding context_chars of context. Returns '[not found]' if absent.
    """
    if not text or not query:
        return "[empty input]"
    idx = text.lower().find(query.lower())
    if idx < 0:
        return "[not found]"
    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(query) + context_chars)
    return text[start:end]
