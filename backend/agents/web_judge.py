"""WebJudge — LLM-powered content intelligence for web ingestion.

Two public coroutines:
  - ``judge_page(url, content, intent)``
      Decide whether a single page is worth ingesting and extract a summary.
  - ``score_links(links, context_url, intent)``
      Given a list of candidate URLs (with optional anchor text), return only
      the ones an LLM considers likely to contain relevant content.

Both calls are cheap (fast, low-token prompts).  They degrade gracefully:
  - If web_judge_enabled=false, every page passes and every link is kept.
  - On LLM error, the same permissive fallback applies — ingestion never
    stalls due to a judge failure.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────

_PAGE_SYS = (
    "You are an expert content curator for a personal knowledge base. "
    "Analyse the given web page content and decide whether it is worth storing.\n\n"
    "REJECT (score 0-2, keep=false):\n"
    "  - Login walls, 404/403 error pages, Cloudflare/DDoS challenge pages\n"
    "  - Pure navigation/index pages, cookie dialogs, ads-only pages\n"
    "  - Empty or near-empty pages\n"
    "  - AI agent self-reports about fetch failures (\"I was unable to access\",\n"
    "    \"all tool tiers exhausted\", HTTP status code summaries, etc.)\n"
    "  - Any content that describes the act of fetching rather than the fetched material itself\n\n"
    "ACCEPT (score 5-10, keep=true):\n"
    "  - Actual articles, documentation, READMEs, code, transcripts, papers\n"
    "  - Real web page content extracted from the target URL\n\n"
    "Return ONLY a JSON object with these keys:\n"
    '  "keep": true/false\n'
    '  "score": integer 0-10  (0=garbage, 10=highly relevant)\n'
    '  "reason": one-sentence explanation in the same language as the page\n'
    '  "summary": 2-3 sentence summary of the page (empty string if keep=false)\n'
    "No other text outside the JSON."
)

_PAGE_USER = (
    "User intent: {intent}\n"
    "Page URL: {url}\n"
    "Page content (first 1500 chars):\n{snippet}\n\n"
    "Respond with the JSON object."
)

_LINKS_SYS = (
    "You are filtering hyperlinks for a focused web crawl. "
    "Given a base URL, a user intent, and a list of candidate links, "
    "return ONLY the URLs that are likely to contain substantive content "
    "relevant to the intent.\n\n"
    "Discard: navigation, login, logout, register, share, print, search, "
    "cart, cookie, privacy-policy, terms-of-service, and obviously off-topic links.\n\n"
    "Return ONLY a JSON array of URL strings from the input list. "
    "No other text."
)

_LINKS_USER = (
    "Base URL: {base_url}\n"
    "User intent: {intent}\n"
    "Candidate links (up to 40):\n{links_json}\n\n"
    "Return a JSON array of URLs to follow."
)


# ── Result types ──────────────────────────────────────────────

@dataclass
class PageVerdict:
    keep: bool
    score: int          # 0-10
    reason: str
    summary: str        # empty string when keep=False


# ── LLM client helper ─────────────────────────────────────────

def _get_llm():
    from agents.llm import build_chat_model, normalize_provider
    from config import settings
    from langchain_core.messages import HumanMessage, SystemMessage  # noqa

    provider = normalize_provider(
        settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )
    return build_chat_model(
        provider,
        settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        max_tokens=512,
        temperature=0,
    )


def _parse_json_block(text: str) -> dict:
    """Extract first JSON object or array from LLM output (strips markdown fences)."""
    text = text.strip()
    # Strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    # Find first {...} or [...]
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
    if m:
        return json.loads(m.group(1))
    return json.loads(text)


# ── Public API ────────────────────────────────────────────────

async def judge_page(
    url: str,
    content: str,
    intent: str = "",
) -> PageVerdict:
    """Ask the LLM whether this page is worth ingesting.

    Parameters
    ----------
    url:     The page URL (for context).
    content: Plain-text content of the page.
    intent:  Free-text description of what the user is trying to collect,
             e.g. "Python async tutorials" or tags like "RAG, LLM".
             Empty string means "general knowledge — accept most things".

    Returns
    -------
    PageVerdict
        Always returns a verdict; never raises.
    """
    from config import settings
    if not settings.web_judge_enabled:
        return PageVerdict(keep=True, score=5, reason="judge disabled", summary="")

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _get_llm()
        snippet = content[:1500].strip()
        if not snippet:
            return PageVerdict(keep=False, score=0, reason="empty content", summary="")

        resp = await llm.ainvoke([
            SystemMessage(content=_PAGE_SYS),
            HumanMessage(content=_PAGE_USER.format(
                intent=intent or "general knowledge base",
                url=url,
                snippet=snippet,
            )),
        ])
        data = _parse_json_block(resp.content)
        return PageVerdict(
            keep=bool(data.get("keep", True)),
            score=int(data.get("score", 5)),
            reason=str(data.get("reason", "")),
            summary=str(data.get("summary", "")),
        )
    except Exception as exc:
        logger.warning("web_judge.judge_page failed for %s: %s", url, exc)
        return PageVerdict(keep=True, score=5, reason=f"judge error: {exc}", summary="")


async def score_links(
    links: list[str],
    base_url: str,
    intent: str = "",
) -> list[str]:
    """Filter a list of candidate URLs to only those relevant to *intent*.

    Parameters
    ----------
    links:    Raw list of absolute URLs extracted from the current page.
    base_url: The URL of the page these links came from (context).
    intent:   Same intent string as ``judge_page``.

    Returns
    -------
    list[str]
        Subset of *links* the LLM considers worth following.
        Falls back to the original list on error.
    """
    from config import settings
    if not settings.web_judge_enabled or not links:
        return links

    # Only send first 40 links to keep prompt small
    candidates = links[:40]
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _get_llm()
        resp = await llm.ainvoke([
            SystemMessage(content=_LINKS_SYS),
            HumanMessage(content=_LINKS_USER.format(
                base_url=base_url,
                intent=intent or "general knowledge base",
                links_json=json.dumps(candidates, ensure_ascii=False),
            )),
        ])
        filtered: list = _parse_json_block(resp.content)
        if isinstance(filtered, list):
            # Only keep URLs that were actually in the candidate list (safety)
            allowed = set(candidates)
            result = [u for u in filtered if u in allowed]
            # Append any candidates beyond the first 40 unchanged
            result += links[40:]
            return result
    except Exception as exc:
        logger.warning("web_judge.score_links failed for %s: %s", base_url, exc)
    return links
