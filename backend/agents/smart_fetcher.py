"""URL Fetch Agent — LLM agent with three general-purpose fetch tools.

The agent receives a URL + user intent and autonomously decides:
  - WHAT to fetch (the original URL, an API endpoint, a CDN raw file, etc.)
  - HOW to fetch it (fast HTTP, JS browser, or full CDP control)
  - WHETHER to call more tools after seeing the first result
  - WHEN enough information has been gathered

Tools (general-purpose, not site-specific):
  http_get     — httpx/scrapling fast static fetch, no JavaScript
                 Best for: REST APIs, JSON endpoints, plain HTML docs, PDFs
                 The LLM can call any URL it deduces — e.g. for a GitHub repo
                 it should call https://api.github.com/repos/owner/repo, not the HTML page.

  browser_get  — agent-browser CLI (Chromium-based, native CDP)
                 Best for: SPAs, JS-rendered pages, lazy-loaded content, YouTube

  cdp_get      — jshookmcp full CDP browser
                 Best for: anti-bot sites (Cloudflare), JS obfuscation,
                 network-level interception, sites that detect headless browsers

The LLM uses its own knowledge to pick the right URL and tool:
  - GitHub repo  → http_get https://api.github.com/repos/owner/repo
                   + http_get https://api.github.com/repos/owner/repo/readme
  - arXiv paper  → http_get https://export.arxiv.org/api/query?id_list=2301.12345
  - Wikipedia    → http_get https://en.wikipedia.org/api/rest_v1/page/summary/TITLE
  - PyPI package → http_get https://pypi.org/pypi/requests/json
  - npm package  → http_get https://registry.npmjs.org/react/latest
  - YouTube      → browser_get https://youtube.com/watch?v=...
  - Cloudflare   → cdp_get https://...
  - Regular site → http_get https://...
"""
from __future__ import annotations

import asyncio
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from agents.doc_agent import RawDocument

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# System prompt — teaches the LLM how to reason and act
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM = """You are an autonomous deep-research agent for a personal knowledge base.
Your mission is NOT just to download a page. It is to thoroughly RESEARCH the topic,
COLLECT content from multiple angles, and SYNTHESIZE a comprehensive knowledge record.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## TOOLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**http_get(url)** — Fast static HTTP. Best for: JSON/XML APIs, plain HTML, Markdown, PDFs.
  Known API shortcuts (ALWAYS prefer these over HTML):
  • GitHub repo   → https://api.github.com/repos/{owner}/{repo}
                    https://api.github.com/repos/{owner}/{repo}/readme
                    https://api.github.com/repos/{owner}/{repo}/releases?per_page=5
  • arXiv paper   → http://export.arxiv.org/api/query?id_list={id}
  • Wikipedia     → https://en.wikipedia.org/api/rest_v1/page/summary/{title}
                    https://en.wikipedia.org/api/rest_v1/page/mobile-sections/{title}
  • PyPI          → https://pypi.org/pypi/{package}/json
  • npm           → https://registry.npmjs.org/{package}/latest
  • HuggingFace   → https://huggingface.co/api/models/{id}
                    https://huggingface.co/{id}/raw/main/README.md

**browser_get(url)** — Headless Chromium (JS rendering). Use when: SPA, YouTube, lazy-loaded,
  or when http_get returned < 300 chars of meaningful content.

**cdp_get(url)** — Full CDP browser. Use when: Cloudflare, anti-bot, or browser_get fails.

**get_links(url, max_links=60)** — Extract all internal links from a page as JSON [{url, text}].
  Use to map a site's structure before deciding which sub-pages to crawl.

**http_get_batch(urls)** — Parallel-fetch up to 15 URLs at once. Use for bulk sub-page collection.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## THREE-PHASE WORKFLOW (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### PHASE 1 — Initial Collection (multi-strategy)
For the target URL, apply strategies IN ORDER until you get rich content:
  1. If a structured API exists → http_get the API endpoint
  2. http_get the original URL
  3. If result < 300 chars OR looks like a JS-rendered blank → browser_get
  4. If browser_get also thin → cdp_get
  ⚠️ Do NOT stop at the first strategy that "works". If you got 500 chars from http_get
  but the page is clearly a docs site with more content, still try browser_get to compare.

### PHASE 2 — Deep Discovery (mandatory for any page with links)
After Phase 1, ALWAYS do ALL of the following that apply:
  a. **Embedded URL extraction**: scan your collected text for URLs and links to:
     - GitHub repos, npm packages, PyPI packages, docs sites, papers, related articles
     → Fetch each important one with http_get (or its known API endpoint)
  b. **Site structure mapping**: if the page is a docs/wiki/blog index →
     call get_links(url, max_links=60), then select the 5-10 most relevant sub-pages,
     then call http_get_batch on them
  c. **Alternative sources**: for the same topic, what other angles exist?
     - Package → also fetch its GitHub repo
     - GitHub repo → also fetch README + releases + wiki if available
     - Paper → also fetch the HTML version and any cited papers listed
     - Blog post → get_links to find related posts on the same site
  d. **Fallback escalation**: for any sub-page where http_get_batch gives < 200 chars,
     individually retry with browser_get

### PHASE 3 — Gap Analysis & Re-collection
Before writing your final answer, explicitly ask yourself:
  - What aspects of the user's intent are NOT yet covered by collected content?
  - Are there URLs/references in collected content that I haven't visited?
  - Did any page mention newer/related resources worth fetching?
  - Would alternative fetch methods yield richer content for any page I visited?
  → If yes to ANY of the above: do more tool calls.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## MINIMUM TOOL CALL REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You MUST make at least 5 tool calls before outputting a final answer.
Site-specific minimums:
  • GitHub repo     : ≥4 calls (API + README + releases + at least one sub-resource)
  • arXiv paper     : ≥3 calls (Atom + HTML + related or cited work)
  • Docs site       : ≥7 calls (root + get_links + http_get_batch ≥5 pages)
  • PyPI/npm pkg    : ≥3 calls (pkg JSON + GitHub repo + docs)
  • Wikipedia       : ≥3 calls (summary API + mobile-sections + ≥1 linked article)
  • YouTube video   : ≥2 calls (browser_get page + any linked resources)
  • News/blog site  : ≥4 calls (article + get_links + batch ≥2 related articles)
  • Unknown site    : ≥4 calls (root + get_links + batch sub-pages + fallback method)

Maximum: 15 tool calls total.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## OUTPUT FORMAT (after thorough collection)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a SYNTHESIZED final answer — not a raw dump of what you downloaded.
Understand the material, extract what matters, and write a comprehensive knowledge record.

## Summary
[3–5 sentences: what this resource is, its significance, and how it relates to the user's intent.
Write this as an analyst — not a webpage title repeat.]

## Analysis
[Your analytical understanding: why this matters, what problem it solves, how it fits into the
broader landscape. Include comparisons, context, caveats. 3–8 sentences.]

## Key Information
[Organized bullet points — group by theme if there are multiple aspects.
Include specific: version numbers, dates, metrics, names, URLs, technical details.
Minimum 8 bullets, no maximum.]

## Sources Collected
[Brief list of all URLs successfully fetched, one per line, with 1-line description of what was found.]

## Full Content
[All fetched text organized by source. Each source headed with its URL.
Include important verbatim excerpts but REMOVE navigation menus, cookie banners,
boilerplate footers, and repeated UI text. Preserve code blocks, config examples,
technical specifications, and factual data verbatim.]
"""

# Reflection prompt injected mid-loop to force gap analysis
_REFLECTION_PROMPT = """Pause and reflect on your collection so far:

1. **Gaps**: What aspects of the user's intent are NOT yet covered by what you've collected?
2. **Unexplored links**: List any URLs or resources you found in collected content that you have NOT yet fetched.
3. **Untried strategies**: For any URL that gave thin results, have you tried all three methods (http_get → browser_get → cdp_get)?
4. **Missing depth**: Are there sub-pages, linked docs, API endpoints, or related resources you should still fetch?

Based on this reflection, continue collecting. Do NOT write your final answer yet.
Make at least 2 more tool calls addressing the gaps you identified."""


# ─────────────────────────────────────────────────────────────────────────────
# Three general-purpose tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def http_get(url: str) -> str:
    """Fetch any URL via fast static HTTP. No JavaScript execution.
    Returns cleaned plain text up to 20 000 characters.
    Call API endpoints directly when you know them (GitHub API, arXiv API, PyPI JSON, etc.).

    Strategy: always go through ``httpx`` first so the ``Content-Type`` header
    drives the parser. Only fall back to scrapling when the response is HTML
    and the cleaned text is too thin — scrapling indiscriminately runs an HTML
    parser, which would otherwise corrupt JSON / XML / PDF responses.
    """
    import httpx
    from bs4 import BeautifulSoup

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept": "*/*"},
            timeout=25,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        # Fall back to scrapling for sites that reject our default UA / TLS
        try:
            from agents.web_agent import _scrapling_static
            doc = await _scrapling_static(url)
            return doc.content[:20000]
        except Exception:
            return f"[http_get error: {exc}]"

    ct = resp.headers.get("content-type", "").lower()
    body_lstrip = resp.text.lstrip() if resp.text else ""

    # PDF — binary path, do not look at resp.text
    if "pdf" in ct or url.lower().endswith(".pdf"):
        try:
            import io, pdfplumber
            pages = []
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                for page in pdf.pages[:80]:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
            return "\n\n".join(pages)[:20000] if pages else "[PDF: no text extracted]"
        except Exception as exc:
            return f"[PDF extraction failed: {exc}]"

    # JSON — return raw (LLM can parse it directly)
    if "json" in ct or body_lstrip.startswith(("{", "[")):
        return resp.text[:20000]

    # XML — return raw (arXiv Atom feed, sitemaps, RSS, etc.)
    if "xml" in ct or body_lstrip.startswith("<?xml"):
        return resp.text[:20000]

    # Plain text / Markdown — return verbatim
    if ct.startswith("text/plain") or ct.startswith("text/markdown"):
        return resp.text[:20000]

    # HTML — clean
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    body = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n", strip=True))
    result = f"# {title}\n\n{body}" if title else body

    # If the cleaned HTML is suspiciously thin, give scrapling a shot — it
    # handles a few quirky sites (custom rendering, partial blocks) better.
    if len(result.strip()) < 300:
        try:
            from agents.web_agent import _scrapling_static
            doc = await _scrapling_static(url)
            if len(doc.content.strip()) > len(result.strip()):
                return doc.content[:20000]
        except Exception:
            pass

    return result[:20000]


@tool
async def browser_get(url: str) -> str:
    """Fetch a JavaScript-heavy page using a headless Chromium browser (agent-browser).
    Use for SPAs, YouTube, lazy-loaded content, or any page that requires JS to render.
    Returns extracted page text."""
    from agents.web_agent import _agent_browser_fetch
    doc = await _agent_browser_fetch(url)
    return doc.content[:20000]


@tool
async def cdp_get(url: str) -> str:
    """Fetch a page using full CDP (Chrome DevTools Protocol) control via jshookmcp.
    Use for Cloudflare-protected sites, heavy anti-bot detection, JS obfuscation,
    or when agent-browser is blocked. Requires Node.js / npx.
    Returns extracted page text."""
    from agents.web_agent import _jshook_fetch
    doc = await _jshook_fetch(url)
    return doc.content[:20000]


@tool
async def get_links(url: str, max_links: int = 60) -> str:
    """Extract hyperlinks from a page. Returns JSON list of {url, text} objects (up to max_links).
    Use this to understand a site's structure before deciding which sub-pages to fetch.
    Only returns same-domain links (internal navigation)."""
    import httpx, json as _json
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, timeout=20, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    base = urlparse(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    seen: set[str] = set()
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = urljoin(url, href)
        p = urlparse(full)
        # same-domain only
        if p.netloc != base.netloc:
            continue
        clean = p._replace(fragment="").geturl()
        if clean in seen:
            continue
        seen.add(clean)
        text = a.get_text(strip=True)[:80]
        links.append({"url": clean, "text": text})
        if len(links) >= max_links:
            break

    return _json.dumps(links, ensure_ascii=False)


@tool
async def http_get_batch(urls: list) -> str:
    """Fetch multiple URLs in parallel via fast static HTTP. Returns each page's text separated by ---.
    Use when you need content from several sub-pages at once (docs site, wiki, news site).
    Maximum 15 URLs. Each result is truncated to 8 000 chars to stay within context limits."""
    import httpx
    from bs4 import BeautifulSoup

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    if len(urls) > 15:
        urls = urls[:15]

    async def _fetch_one(u: str) -> str:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _UA}, timeout=20, follow_redirects=True
            ) as client:
                resp = await client.get(u)
                resp.raise_for_status()
            ct = resp.headers.get("content-type", "").lower()
            if "json" in ct or resp.text.lstrip().startswith(("{",'[')):
                return f"[{u}]\n{resp.text[:8000]}"
            if "xml" in ct or resp.text.lstrip().startswith("<?xml"):
                return f"[{u}]\n{resp.text[:8000]}"
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            body = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n", strip=True))
            return f"[{u}]\n{body[:8000]}"
        except Exception as exc:
            return f"[{u}]\n[fetch error: {exc}]"

    results = await asyncio.gather(*[_fetch_one(u) for u in urls])
    return "\n\n---\n\n".join(results)


# ─────────────────────────────────────────────────────────────────────────────
# LLM factory
# ─────────────────────────────────────────────────────────────────────────────

def _get_llm():
    from config import settings
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.llm_model, api_key=settings.anthropic_api_key,
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
        temperature=0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tool registry
# ─────────────────────────────────────────────────────────────────────────────

_TOOLS = [http_get, browser_get, cdp_get, get_links, http_get_batch]
_TOOL_MAP = {t.name: t for t in _TOOLS}


def _emit_progress(msg: str) -> None:
    try:
        from utils.agent_bus import emit as _e
        _e(msg, kind="progress", agent="url_fetch_agent")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Main agent entry point
# ─────────────────────────────────────────────────────────────────────────────

async def smart_fetch(
    url: str,
    intent: str = "",
    cookies=None,  # noqa: ARG001 — accepted for backward compatibility
    analysis=None,  # noqa: ARG001 — accepted for backward compatibility
) -> RawDocument:
    """DEPRECATED — delegates to :func:`agents.web.loop.run_agent`.

    The legacy ReAct loop that lived here was replaced by the unified
    ``agent_core.run_loop``-driven agent in ``agents/web/loop.py`` (with
    plan/execute/verify phases, skill memory, research-state tracking,
    BudgetTracker, and steering support). This shim is retained so external
    callers don't break.
    """
    import warnings
    warnings.warn(
        "agents.smart_fetcher.smart_fetch is deprecated; "
        "use agents.web.loop.run_agent instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    _emit_progress(f"🤖 (compat) smart_fetch → web/loop.run_agent: {url[:80]}")

    from agents.web.loop import run_agent as _unified_run_agent
    return await _unified_run_agent(url=url, intent=intent, task_id=None)
