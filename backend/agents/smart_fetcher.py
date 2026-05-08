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
    """Fetch any URL via fast static HTTP (httpx + scrapling). No JavaScript execution.
    Returns cleaned plain text up to 20 000 characters.
    Call API endpoints directly when you know them (GitHub API, arXiv API, PyPI JSON, etc.)."""
    import httpx
    from bs4 import BeautifulSoup

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # Try scrapling first for better HTML rendering
    try:
        from agents.web_agent import _scrapling_static
        doc = await _scrapling_static(url)
        return doc.content[:20000]
    except Exception:
        pass

    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, timeout=25, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    ct = resp.headers.get("content-type", "").lower()

    # PDF
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
    if "json" in ct or resp.text.lstrip().startswith("{") or resp.text.lstrip().startswith("["):
        return resp.text[:20000]

    # XML — return raw (arXiv Atom feed, sitemaps, etc.)
    if "xml" in ct or resp.text.lstrip().startswith("<?xml"):
        return resp.text[:20000]

    # HTML — clean
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    body = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n", strip=True))
    result = f"# {title}\n\n{body}" if title else body
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
async def get_links(url: str, max_links: int = 40) -> str:
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
    cookies=None,
    analysis=None,  # optional URLAnalysis hint — informational only
) -> RawDocument:
    """Run the URL fetch agent. LLM decides which URLs to fetch and which tools to use.

    Falls back to plain static fetch if the agent itself raises.
    """
    llm = _get_llm()
    llm_with_tools = llm.bind_tools(_TOOLS)

    hint = ""
    if analysis and getattr(analysis, "site_type", None) and analysis.site_type not in ("unknown", "general_webpage"):
        hint = f"Hint (not binding): this URL looks like a {analysis.site_type}.\n"

    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=(
            f"URL: {url}\n"
            f"User intent: {intent or 'general — extract as much useful information as possible'}\n"
            + hint
        )),
    ]

    _emit_progress(f"🤖 URL Agent 启动: {url[:80]}")
    logger.info("url_fetch_agent  url=%s  intent=%r", url, intent)

    _MAX_ITER = 15
    _MIN_TOOL_CALLS = 5       # force exploration before allowing final answer
    _REFLECT_AT = 4           # inject reflection prompt after this many tool calls

    total_tool_calls = 0
    reflection_injected = False

    try:
        for iteration in range(_MAX_ITER):
            response: AIMessage = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            tool_calls = getattr(response, "tool_calls", None) or []

            if not tool_calls:
                # LLM wants to stop ── enforce minimum depth
                if total_tool_calls < _MIN_TOOL_CALLS and iteration < (_MAX_ITER - 2):
                    logger.info(
                        "url_fetch_agent: early stop at %d tool calls (iter %d) — nudging",
                        total_tool_calls, iteration + 1,
                    )
                    messages.append(HumanMessage(
                        content=(
                            f"You have only made {total_tool_calls} tool call(s). "
                            "This is insufficient. You must:\n"
                            "1. Try browser_get or cdp_get on the original URL if you only used http_get\n"
                            "2. Call get_links on the main page to discover sub-pages\n"
                            "3. Fetch at least 3 more sub-pages or related resources\n"
                            "Do NOT write a final answer yet. Make more tool calls now."
                        )
                    ))
                    continue

                logger.info(
                    "url_fetch_agent complete: %d tool calls, %d iterations  url=%s",
                    total_tool_calls, iteration + 1, url,
                )
                break

            # Inject reflection prompt mid-loop to force gap analysis
            if not reflection_injected and total_tool_calls >= _REFLECT_AT:
                reflection_injected = True
                messages.append(HumanMessage(content=_REFLECTION_PROMPT))
                logger.info("url_fetch_agent: reflection injected at %d tool calls", total_tool_calls)
                # Don't process tool calls from this message — get new response
                continue

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("args", {})
                tool_call_id = tc["id"]

                called_url = tool_args.get("url", "")
                _emit_progress(f"🔧 [{total_tool_calls + 1}] {tool_name}({called_url[:70]})")
                logger.info("url_fetch_agent [%d] → %s  %s", total_tool_calls + 1, tool_name, called_url)

                t = _TOOL_MAP.get(tool_name)
                if t is None:
                    result = f"[Unknown tool: {tool_name}]"
                else:
                    try:
                        result = str(await t.ainvoke(tool_args))
                    except Exception as exc:
                        result = f"[{tool_name} error: {exc}]"
                        logger.warning("url_fetch_agent tool error  tool=%s  err=%s", tool_name, exc)

                # Auto-escalate: if result is thin and we haven't tried browser_get yet
                if (
                    tool_name == "http_get"
                    and len(result.strip()) < 400
                    and not result.startswith("[")  # not an error marker
                    and called_url
                ):
                    logger.info(
                        "url_fetch_agent: thin result from http_get (%d chars) for %s — "
                        "appending browser_get escalation note",
                        len(result.strip()), called_url,
                    )
                    result += (
                        "\n\n[AGENT NOTE: This result is thin (<400 chars). "
                        "You should retry this URL with browser_get to get the JS-rendered content.]"
                    )

                messages.append(ToolMessage(content=result, tool_call_id=tool_call_id))
                total_tool_calls += 1

                # Inject reflection after crossing threshold (only if not yet injected)
                if not reflection_injected and total_tool_calls >= _REFLECT_AT:
                    reflection_injected = True
                    messages.append(HumanMessage(content=_REFLECTION_PROMPT))
                    logger.info("url_fetch_agent: reflection injected after tool call %d", total_tool_calls)
                    break  # break inner loop; outer loop will re-invoke LLM with reflection

    except Exception as agent_exc:
        logger.error("url_fetch_agent loop failed for %s: %s", url, agent_exc)

    # Final AI answer (last AIMessage with no pending tool calls)
    final_content = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not (getattr(msg, "tool_calls", None) or []):
            final_content = msg.content or ""
            break

    # Fallback: concatenate raw tool outputs
    if not final_content:
        tool_results = [m.content for m in messages if isinstance(m, ToolMessage)]
        final_content = (
            "\n\n---\n\n".join(tool_results)
            if tool_results
            else f"[URL Fetch Agent: no content retrieved from {url}]"
        )

    site_type = getattr(analysis, "site_type", "unknown") if analysis else "unknown"
    tools_called = [
        tc["name"]
        for msg in messages if isinstance(msg, AIMessage)
        for tc in (getattr(msg, "tool_calls", None) or [])
    ]

    return RawDocument(
        content=final_content,
        metadata={
            "file_type": "url",
            "source_url": url,
            "site_type": site_type,
            "fetch_mode": "smart",
            "strategy_used": ", ".join(dict.fromkeys(tools_called)) or "none",
        },
    )
