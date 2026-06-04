from __future__ import annotations
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 的父目录即项目根，.env 放在那里
_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI key kept for legacy .env compatibility only

    # Qdrant storage (needed for ingest pipeline, not for RAG)
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "omnikb"
    qdrant_mode: str = "local"
    qdrant_local_path: str = "./data/qdrant"
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    openai_api_key: str = ""

    # Legacy Anthropic key kept only so older .env files still parse cleanly.
    anthropic_api_key: str = ""

    # Legacy Ollama base URL kept only so older .env files still parse.
    ollama_base_url: str = "http://localhost:11434"

    # DeepSeek or third-party OpenAI-compatible LLM
    llm_base_url: str = ""   # e.g. https://api.deepseek.com/v1 or a third-party gateway
    llm_api_key: str = ""    # API key for DeepSeek or the custom provider
    # JSON object passed as extra_body to OpenAI-compatible chat clients. Useful for
    # provider-specific flags such as {"enable_thinking": false} on hybrid
    # thinking models. Empty string = no extra body.
    llm_extra_body_json: str = ""

    # Normalized runtime providers: deepseek | custom.
    # Older values like openai / anthropic / ollama are accepted and normalized later.
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-pro"

    siliconflow_api_key: str = ""

    # MCP
    mcp_api_key: str = "changeme-replace-with-strong-secret"

    # Storage
    data_dir: str = "./data"
    sqlite_path: str = "./data/omnikb.db"

    # ── P1 features ──────────────────────────────────────────────

    # Media transcription (faster-whisper)
    # Sizes: tiny | base | small | medium | large-v2
    whisper_model_size: str = "base"


    # Auto-tag (LLM-based, uses LLM credits)
    autotag_enabled: bool = False

    # ── Vision (multimodal cloud LLM for OCR + video frame description) ──
    # Set vision_enabled=true to activate; vision_provider defaults to llm_provider
    vision_enabled: bool = False
    # Provider: "" = inherit llm_provider | "deepseek" | "custom"
    vision_provider: str = ""
    # Model: deepseek-vl compatible endpoint or any OpenAI-compatible vision model
    vision_model: str = "gpt-4o-mini"
    # Independent API key for vision provider; falls back to provider's default key when empty
    vision_api_key: str = ""
    # Independent base URL for vision provider (OpenAI-compatible); falls back when empty
    vision_base_url: str = ""
    # Seconds between keyframes when describing video (0 = disable frame description)
    vision_frame_interval: int = 60
    # Min chars per PDF page below which OCR is triggered (0 = always OCR image pages)
    vision_pdf_ocr_threshold: int = 80

    # ── Web Judge (LLM-powered content intelligence for web ingestion) ──
    web_judge_enabled: bool = False
    # Pages with LLM score below this threshold are dropped (0-10 scale).
    web_judge_min_score: int = 4

    # ── HuggingFace (model downloads) ─────────────────────────────
    # Mirror endpoint for downloading models (e.g. https://hf-mirror.com).
    # Leave empty to use the default huggingface.co.
    hf_endpoint: str = ""


    # ── Chat ─────────────────────────────────────────────────
    # System prompt for wiki chat. Overridable at runtime via settings API.
    rag_system_prompt: str = (
        "You are OmniKB, a knowledgeable AI assistant. "
        "Your knowledge base is structured as a wiki — the `<wiki_index>` in your "
        "system prompt lists all available pages. Use `read_wiki_page(id)` to fetch "
        "full content of any page that seems relevant. "
        "The wiki index is your authoritative knowledge source — answer based on it. "
        "You may use your own knowledge only when the wiki has no relevant information. "
        "Be honest when the wiki lacks information on a topic."
    )

    # ── Network proxy ──────────────────────────────────────────
    # HTTP(S) proxy for all outbound calls (LLM, embeddings, web scraping,
    # model downloads). Format: http://host:port or socks5://host:port.
    # Leave empty for direct connection.
    http_proxy: str = ""

    # ── Web agent pools (P0) ──────────────────────────────────────
    # JsHookMcpClient instance count to keep alive in app lifespan
    jshook_pool_size: int = 2
    # patchright/playwright browser count (0 = disable)
    playwright_pool_size: int = 1

    # ── L2 Wiki layer (LLM-Wiki secondary index) ──────────────────
    # Master switch for the worker. When false, ingest still enqueues
    # events for the audit trail but the LLM generation step is
    # skipped — useful for cost-sensitive deployments and CI.
    wiki_enabled: bool = True
    # Maximum chars of source text fed to the analysis prompt. Beyond
    # this we truncate (head + tail). Costs roughly 1 token per 4
    # chars for English, ~1 per 2 chars for CJK.
    wiki_max_source_chars: int = 8000
    # Concurrent LLM calls inside one ingest (one per generated page).
    # Keeps a single ingest from saturating the LLM connection pool.
    wiki_generation_concurrency: int = 3
    # Whether the chat / MCP retrieval path also reads wiki pages.
    # P4 turns this on by default once we trust the generated content.
    wiki_retrieval_enabled: bool = True

    # Auto-trigger Deep Research from lint knowledge_gap insights.
    # Default OFF because this opens a wallet faucet — every gap page
    # could spawn a multi-LLM research run. Operators must opt in by
    # setting WIKI_AUTO_RESEARCH_ENABLED=true once they've seen the
    # cost profile of manual runs.
    wiki_auto_research_enabled: bool = False
    # Hard cap per insights scan. With max_urls=3 default and ~5-10
    # LLM calls per URL, 3 dispatches ≈ 50-100 LLM calls upper bound.
    wiki_auto_research_max_per_run: int = 3
    # How long to suppress repeated research on the same page.
    # 24h is a reasonable trade-off: long enough for fresh content to
    # emerge on the open web, short enough to keep gaps shrinking.
    wiki_auto_research_cooldown_hours: int = 24
    # If non-zero AND wiki_auto_research_enabled, a periodic background
    # worker (`ScheduledResearchWorker`) ticks every N hours and runs
    # the same auto-dispatch logic as `?auto_research=true`. 0 disables
    # the worker entirely (manual /insights polling is still available).
    wiki_auto_research_interval_hours: float = 0.0

    # ── Web agent budget caps — 0 = unlimited, compaction handles safety ──
    web_agent_max_input_tokens: int = 0  # 0 = unlimited
    web_agent_max_output_tokens: int = 0  # 0 = unlimited
    web_agent_max_seconds: float = 0  # 0 = unlimited
    web_agent_max_tool_calls: int = 0  # 0 = unlimited
    # Inject a reflection prompt every N tool calls so the agent reviews
    # progress and re-plans — replaces hard tool-call caps. 0 = disabled.
    web_agent_reflection_interval: int = 8

    # ── Admin authentication ─────────────────────────────────────
    # When non-empty, the main admin panel requires password auth via
    # cookie-based session. kb-chat.html, kb-api/*, /health, /mcp/*
    # and /scenario-api.html are never protected.
    admin_password: str = ""

    # ── Chat agent (agentic chat with KB tools) ────────────────────
    # When true, /chat routes through an agent loop that can call
    # search_kb / list_sources / fetch_url. Falls back to the legacy
    # streaming-RAG path on agent failure.
    chat_agent_enabled: bool = True
    chat_agent_max_turns: int = 6
    chat_agent_max_tool_calls: int = 10
    chat_context_window: int = 1_000_000  # 1M tokens
    chat_compaction_threshold: float = 0.80  # compact at 80%


settings = Settings()


# ── Self-check & redaction ────────────────────────────────────────────
#
# These helpers make configuration drift observable instead of silent.
# ``verify_settings()`` is called by ``main.py`` during lifespan startup and
# logs ERROR / WARNING lines for misconfigurations that would otherwise blow
# up later inside a request handler. ``redacted_settings()`` produces a dict
# safe for /health, /metrics, or debugging endpoints — no secrets leak.


_SECRET_FIELDS = frozenset({
    "openai_api_key",
    "anthropic_api_key",
    "llm_api_key",
    "siliconflow_api_key",
    "vision_api_key",
    "mcp_api_key",
})


def _redact(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-2:]}"


def redacted_settings() -> dict:
    """Return a dict copy of settings with secrets masked.

    Safe to log, return from /health, or include in error reports.
    """
    out: dict = {}
    for name in type(settings).model_fields:
        value = getattr(settings, name, None)
        if name in _SECRET_FIELDS and isinstance(value, str):
            out[name] = _redact(value)
        else:
            out[name] = value
    return out


def verify_settings() -> list[str]:
    """Validate runtime settings and return a list of issue strings.

    Empty list ⇒ healthy configuration. Caller decides whether to log,
    fail, or surface to the operator. ``main.py`` logs warnings but does
    not abort startup so partially configured installs (e.g. embeddings
    not yet wired) can still serve cached content.
    """
    issues: list[str] = []

    # LLM credentials
    if not settings.llm_api_key:
        issues.append(
            "LLM_API_KEY is empty — all LLM calls will fail. Set it in .env"
        )
    provider = (settings.llm_provider or "").strip().lower()
    if provider not in {"deepseek", "custom", "openai", "anthropic", "claude", "ollama"}:
        issues.append(
            f"LLM_PROVIDER={provider!r} is unrecognised; expected "
            "'deepseek' or 'custom'"
        )
    if provider == "custom" and not settings.llm_base_url:
        issues.append(
            "LLM_PROVIDER=custom but LLM_BASE_URL is empty — custom providers "
            "need an OpenAI-compatible endpoint URL"
        )

    # Vision (only if enabled)
    if settings.vision_enabled:
        # Vision falls back to llm_* credentials when its own are blank,
        # so we only complain if BOTH paths are empty.
        vk = settings.vision_api_key or settings.llm_api_key
        if not vk:
            issues.append(
                "VISION_ENABLED=true but no vision_api_key and no llm_api_key "
                "configured"
            )

    # MCP key default
    if settings.mcp_api_key == "changeme-replace-with-strong-secret":
        issues.append(
            "MCP_API_KEY is still the default placeholder — anyone reaching "
            "/mcp can call your tools. Rotate it before exposing the port."
        )

    # Budget sanity
    if settings.web_agent_max_seconds <= 0 and settings.web_agent_max_input_tokens <= 0:
        issues.append(
            "web_agent_max_seconds and web_agent_max_input_tokens are both "
            "disabled — runaway agents have no time/token cap"
        )

    # Reflection vs hard cap: warn if both are off
    if (
        settings.web_agent_reflection_interval <= 0
        and settings.web_agent_max_tool_calls <= 0
    ):
        issues.append(
            "Both web_agent_reflection_interval and web_agent_max_tool_calls "
            "are disabled — the agent will never self-reflect or stop on "
            "tool-call count. Consider setting one."
        )

    return issues
