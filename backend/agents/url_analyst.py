"""URLAnalyst — understand what a URL contains before touching it.

Two layers:
1. Rule-based fast path (no LLM cost) for well-known patterns.
2. LLM fallback for anything else, returning site_type + strategy list
   + any contextual knowledge the model has about the URL/topic.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class URLAnalysis:
    site_type: str          # see SITE_TYPES below
    confidence: float       # 0.0 – 1.0
    extraction_goals: list[str]          # ["README", "abstract", "transcript", …]
    strategies: list[str]                # ordered best→worst
    known_context: str      # ≤200 chars of LLM prior knowledge about this URL
    requires_auth: bool
    is_dynamic: bool


# ── Rule-based fast path ──────────────────────────────────────

def _rule_based(url: str) -> URLAnalysis | None:
    """Deterministic URL-pattern detection. No LLM, no network call."""
    try:
        p = urlparse(url)
        host = p.netloc.lower().removeprefix("www.")
        path = p.path
    except Exception:
        return None

    # ── GitHub ──────────────────────────────────────────────
    if host == "github.com":
        parts = [x for x in path.split("/") if x]
        if len(parts) == 2:
            return URLAnalysis(
                site_type="github_repo",
                confidence=0.99,
                extraction_goals=["README", "description", "topics", "language", "stars"],
                strategies=["github_api", "static_scrape"],
                known_context="",
                requires_auth=False,
                is_dynamic=False,
            )
        if len(parts) >= 4 and parts[2] in ("blob", "raw", "tree"):
            return URLAnalysis(
                site_type="github_file",
                confidence=0.99,
                extraction_goals=["file content"],
                strategies=["direct_download", "static_scrape"],
                known_context="",
                requires_auth=False,
                is_dynamic=False,
            )
        # Issues, PR, Discussions, etc.
        return URLAnalysis(
            site_type="general_webpage",
            confidence=0.80,
            extraction_goals=["main content"],
            strategies=["static_scrape", "dynamic_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=True,
        )

    # ── YouTube ─────────────────────────────────────────────
    if host in ("youtube.com", "youtu.be", "m.youtube.com") or host.endswith(".youtube.com"):
        return URLAnalysis(
            site_type="youtube_video",
            confidence=0.99,
            extraction_goals=["title", "description", "transcript", "chapters", "uploader"],
            strategies=["youtube_meta", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=True,
        )

    # ── Bilibili ─────────────────────────────────────────────
    if "bilibili.com" in host:
        return URLAnalysis(
            site_type="video_platform",
            confidence=0.95,
            extraction_goals=["title", "description", "uploader", "tags"],
            strategies=["dynamic_scrape", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=True,
        )

    # ── arXiv ───────────────────────────────────────────────
    if "arxiv.org" in host:
        return URLAnalysis(
            site_type="arxiv_paper",
            confidence=0.99,
            extraction_goals=["title", "authors", "abstract", "categories"],
            strategies=["arxiv_api", "direct_download", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=False,
        )

    # ── Wikipedia ───────────────────────────────────────────
    if "wikipedia.org" in host:
        return URLAnalysis(
            site_type="wikipedia_article",
            confidence=0.99,
            extraction_goals=["title", "summary", "full_article"],
            strategies=["wikipedia_api", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=False,
        )

    # ── HuggingFace ─────────────────────────────────────────
    if host == "huggingface.co":
        site_type = "huggingface_dataset" if "/datasets/" in path else "huggingface_model"
        return URLAnalysis(
            site_type=site_type,
            confidence=0.98,
            extraction_goals=["model_card", "description", "tasks", "tags", "metrics"],
            strategies=["huggingface_api", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=True,
        )

    # ── PyPI ────────────────────────────────────────────────
    if host == "pypi.org" and "/project/" in path:
        return URLAnalysis(
            site_type="pypi_package",
            confidence=0.99,
            extraction_goals=["name", "summary", "description", "version", "classifiers"],
            strategies=["pypi_api", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=False,
        )

    # ── npm ─────────────────────────────────────────────────
    if host == "npmjs.com" and "/package/" in path:
        return URLAnalysis(
            site_type="npm_package",
            confidence=0.99,
            extraction_goals=["name", "description", "README", "keywords", "version"],
            strategies=["npm_api", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=False,
        )

    # ── PDF ─────────────────────────────────────────────────
    if path.lower().endswith(".pdf"):
        return URLAnalysis(
            site_type="pdf_document",
            confidence=0.97,
            extraction_goals=["full_text"],
            strategies=["direct_download"],
            known_context="",
            requires_auth=False,
            is_dynamic=False,
        )

    # ── Twitter / X ─────────────────────────────────────────
    if host in ("twitter.com", "x.com", "mobile.twitter.com"):
        return URLAnalysis(
            site_type="twitter_post",
            confidence=0.97,
            extraction_goals=["tweet_text", "author", "replies"],
            strategies=["dynamic_scrape", "agent_browser", "static_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=True,
        )

    # ── Docs sites ──────────────────────────────────────────
    doc_hosts = ("docs.", "developer.", "dev.", "api.", "reference.")
    if any(host.startswith(prefix) for prefix in doc_hosts):
        return URLAnalysis(
            site_type="documentation",
            confidence=0.85,
            extraction_goals=["main content", "code examples", "API reference"],
            strategies=["static_scrape", "dynamic_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=False,
        )

    return None


# ── LLM-powered analysis ──────────────────────────────────────

_ANALYST_SYS = """\
You are a URL intelligence analyst for a personal knowledge base.
Analyze the given URL (and optional user intent) to determine:
  1. What kind of content it contains
  2. The best strategy to extract useful knowledge from it

Return ONLY a valid JSON object (no markdown, no explanation):
{
  "site_type": "<type>",
  "confidence": <0.0-1.0>,
  "extraction_goals": ["<specific info to extract>", ...],
  "strategies": ["<preferred strategy>", "<fallback>", ...],
  "known_context": "<max 200 chars: what you know about this URL/domain/topic>",
  "requires_auth": <true|false>,
  "is_dynamic": <true|false>
}

site_type options:
  github_repo, github_file, youtube_video, arxiv_paper, wikipedia_article,
  huggingface_model, huggingface_dataset, npm_package, pypi_package,
  twitter_post, blog_article, news_article, documentation, pdf_document,
  forum_thread, social_media, ecommerce, video_platform, general_webpage

strategy options (ordered best→worst for each type):
  github_api        → GitHub REST API (repos, README, metadata)
  youtube_meta      → yt-dlp metadata + description + chapters
  arxiv_api         → arXiv Atom API (abstract, authors, categories)
  wikipedia_api     → Wikipedia REST API (summary + full sections)
  huggingface_api   → HuggingFace Hub API (model/dataset card)
  npm_api           → npm registry JSON API
  pypi_api          → PyPI JSON API
  direct_download   → download the resource directly (PDF, raw file)
  static_scrape     → scrapling static fetcher / httpx + BeautifulSoup
  dynamic_scrape    → Playwright headless browser (JS-heavy pages)
  agent_browser     → agent-browser CLI (SPA, scroll-to-load, interactive)
  jshook            → jshookmcp CDP browser (anti-bot, network capture)

Always include at least one fallback strategy (static_scrape or dynamic_scrape).
For known_context: write what you know about this specific repo / channel / domain.
If you know nothing specific, write "".
"""


def _parse_json_safe(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)


def _get_llm():
    from config import settings
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            max_tokens=600,
            temperature=0,
        )
    if settings.llm_provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=settings.llm_model, temperature=0)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key or settings.openai_api_key or "none",
        base_url=settings.llm_base_url or None,
        max_tokens=600,
        temperature=0,
    )


async def analyze_url(url: str, intent: str = "") -> URLAnalysis:
    """Determine URL type and extraction strategy.

    Uses rule-based fast path first (no LLM cost, no latency).
    Falls back to LLM for unknown patterns.
    Never raises — returns generic analysis on any error.
    """
    # Fast path
    fast = _rule_based(url)
    if fast and fast.confidence >= 0.95:
        # For well-known patterns, optionally enrich known_context via LLM
        # but don't block the pipeline on it (skip if LLM is not configured)
        try:
            from config import settings
            if settings.llm_api_key or settings.siliconflow_api_key or settings.anthropic_api_key:
                fast.known_context = await _fetch_known_context(url, fast.site_type, intent)
        except Exception:
            pass
        return fast

    # LLM path for unknown URLs
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _get_llm()
        user_msg = f"URL: {url}"
        if intent:
            user_msg += f"\nUser intent: {intent}"
        resp = await llm.ainvoke([
            SystemMessage(content=_ANALYST_SYS),
            HumanMessage(content=user_msg),
        ])
        data = _parse_json_safe(resp.content)
        return URLAnalysis(
            site_type=str(data.get("site_type", "general_webpage")),
            confidence=float(data.get("confidence", 0.7)),
            extraction_goals=list(data.get("extraction_goals", ["main content"])),
            strategies=list(data.get("strategies", ["static_scrape", "dynamic_scrape"])),
            known_context=str(data.get("known_context", ""))[:300],
            requires_auth=bool(data.get("requires_auth", False)),
            is_dynamic=bool(data.get("is_dynamic", False)),
        )
    except Exception as exc:
        logger.warning("url_analyst.analyze_url failed for %s: %s", url, exc)
        return fast or URLAnalysis(
            site_type="general_webpage",
            confidence=0.5,
            extraction_goals=["main content"],
            strategies=["static_scrape", "dynamic_scrape"],
            known_context="",
            requires_auth=False,
            is_dynamic=False,
        )


_CONTEXT_SYS = (
    "You are helping build a knowledge base. "
    "Given a URL and its detected type, write 1-2 sentences (max 200 chars) "
    "describing what you know about this specific resource. "
    "If it's a famous project, paper, or channel, describe it. "
    "If you don't know the specific resource, write an empty string. "
    "Return ONLY the description string, nothing else."
)


async def _fetch_known_context(url: str, site_type: str, intent: str) -> str:
    """Ask LLM what it knows about this specific URL."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        llm = _get_llm()
        resp = await llm.ainvoke([
            SystemMessage(content=_CONTEXT_SYS),
            HumanMessage(content=f"URL: {url}\nType: {site_type}\nIntent: {intent or 'general'}"),
        ])
        ctx = resp.content.strip().strip('"').strip("'")
        return ctx[:300] if ctx.lower() not in ("", "none", "n/a", "unknown") else ""
    except Exception:
        return ""
