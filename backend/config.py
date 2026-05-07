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

    # OpenAI (kept for backward compat)
    openai_api_key: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # Ollama
    ollama_base_url: str = "http://localhost:11434"

    # Custom / third-party OpenAI-compatible LLM
    llm_base_url: str = ""   # e.g. https://api.siliconflow.cn/v1
    llm_api_key: str = ""    # API key for the custom provider

    # Default LLM
    llm_provider: Literal["openai", "anthropic", "ollama", "custom"] = "custom"
    llm_model: str = "deepseek-ai/DeepSeek-V3"

    # Embedding — SiliconFlow BGE-M3 (OpenAI-compatible)
    embedding_provider: Literal["openai", "siliconflow"] = "siliconflow"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = 1024  # BGE-M3=1024, text-embedding-3-small=1536
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"

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


settings = Settings()
