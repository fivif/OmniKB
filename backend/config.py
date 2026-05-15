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

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "omnikb"
    # qdrant_mode: remote | local | memory
    # remote = 连接独立 Qdrant 服务; local = 本地文件持久化(无需服务); memory = 内存临时存储
    qdrant_mode: str = "local"
    qdrant_local_path: str = "./data/qdrant"

    # OpenAI key is still used by the optional embedding provider and old .env files.
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

    # Embedding — SiliconFlow BGE-M3 (OpenAI-compatible)
    embedding_provider: Literal["openai", "siliconflow"] = "siliconflow"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = 1024  # BGE-M3=1024, text-embedding-3-small=1536
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    # Max concurrent embedding API calls (prevents RPM 403 on SiliconFlow free tier)
    embedding_concurrency: int = 3
    # Texts per API call (SiliconFlow recommends <=32 per request)
    embedding_batch_size: int = 32
    # Max embedding API requests per minute (0 = disabled). Set to your provider's RPM quota.
    # SiliconFlow free tier ≈ 10 RPM; paid tier is higher. Proactively throttles before hitting 403.
    embedding_rpm_limit: int = 10

    # MCP
    mcp_api_key: str = "changeme-replace-with-strong-secret"

    # Storage
    data_dir: str = "./data"
    sqlite_path: str = "./data/omnikb.db"

    # ── P1 features ──────────────────────────────────────────────

    # Media transcription (faster-whisper)
    # Sizes: tiny | base | small | medium | large-v2
    whisper_model_size: str = "base"

    # Re-ranker (sentence-transformers CrossEncoder)
    # Set to False by default — requires large model download on first use
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

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

    # Persistent directory for fastembed-managed models (BM25 / sparse).
    # When empty, ``main.py`` anchors fastembed to ``~/.cache/fastembed``
    # so the BM25 model survives reboots instead of being repeatedly
    # redownloaded from $TMPDIR (which macOS / containers purge).
    fastembed_cache_path: str = ""

    # ── Chat ─────────────────────────────────────────────────
    # System prompt for RAG chat. Overridable at runtime via settings API.
    rag_system_prompt: str = (
        "You are OmniKB, a knowledgeable AI assistant. "
        "When relevant reference material from the user's knowledge base is provided, "
        "use it to supplement and enrich your answer. "
        "You are NOT limited to the provided context — draw on your own knowledge freely. "
        "Cite knowledge-base sources inline as [1], [2], etc. only when you actually use them. "
        "Never refuse to answer just because the context is limited."
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

    # ── Web agent budget caps (BudgetTracker defaults) ─────────────
    # Soft caps enforced by agent_core.budget.BudgetTracker. Set to 0 to
    # disable a specific cap. Triggered run terminates cleanly with
    # final_status="budget_exceeded" and snapshot in the agent_end event.
    web_agent_max_input_tokens: int = 200_000
    web_agent_max_output_tokens: int = 50_000
    web_agent_max_seconds: float = 300.0
    web_agent_max_tool_calls: int = 0  # 0 = disabled
    # Inject a reflection prompt every N tool calls so the agent reviews
    # progress and re-plans — replaces hard tool-call caps. 0 = disabled.
    web_agent_reflection_interval: int = 8

    # ── Chat agent (agentic chat with KB tools) ────────────────────
    # When true, /chat routes through an agent loop that can call
    # search_kb / list_sources / fetch_url. Falls back to the legacy
    # streaming-RAG path on agent failure.
    chat_agent_enabled: bool = True
    chat_agent_max_turns: int = 6
    chat_agent_max_tool_calls: int = 10


settings = Settings()
