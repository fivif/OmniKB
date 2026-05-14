#!/usr/bin/env python3
"""Run OmniKB MCP server in stdio mode (for Claude Desktop, Claude Code, Cursor, etc.)

Claude Code config (~/.claude.json or project .mcp.json):

    {
      "mcpServers": {
        "omnikb": {
          "command": "python",
          "args": ["/path/to/OmniKB/backend/mcp_server/run_stdio.py"],
          "env": {
            "LLM_API_KEY": "sk-...",
            "LLM_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_MODEL": "deepseek-chat",
            "QDRANT_URL": "http://localhost:6333",
            "QDRANT_MODE": "local",
            "MCP_API_KEY": "optional-shared-secret"
          }
        }
      }
    }

Or set env vars in your shell profile (~/.zshrc) and omit them from the config.
The script also reads ``backend/.env`` as a fallback.
"""
from __future__ import annotations
import asyncio
import os
import sys

# Windows async policy fix
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure backend/ is on the path regardless of CWD
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Explicitly load .env (check project root first, then backend/) so CWD doesn't matter
_project_root = os.path.dirname(_backend_dir)
for _env_dir in (_project_root, _backend_dir):
    _env_file = os.path.join(_env_dir, ".env")
    if os.path.isfile(_env_file):
        with open(_env_file) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _key, _, _val = _line.partition("=")
                    _key, _val = _key.strip(), _val.strip().strip('"').strip("'")
                    if _key and _key not in os.environ:
                        os.environ[_key] = _val
        break  # only load first found .env

from config import settings  # noqa: E402


async def _init() -> None:
    os.makedirs(settings.data_dir, exist_ok=True)
    from storage.metadata_db import init_db
    from storage.file_store import init_file_store
    await init_db()
    init_file_store()
    # Note: vector_store client is initialized lazily in the MCP event loop


asyncio.run(_init())

# Import MCP instance after path is set up
from mcp_server.server import mcp  # noqa: E402

if __name__ == "__main__":
    mcp.run()
