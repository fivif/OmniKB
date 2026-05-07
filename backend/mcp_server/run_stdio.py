#!/usr/bin/env python3
"""Run OmniKB MCP server in stdio mode (for Claude Desktop, Cursor, etc.)

Usage:
    python backend/mcp_server/run_stdio.py

Configure in claude_desktop_config.json:
    {
      "mcpServers": {
        "omnikb": {
          "command": "python",
          "args": ["<absolute-path>/backend/mcp_server/run_stdio.py"],
          "env": { "OPENAI_API_KEY": "sk-...", "MCP_API_KEY": "..." }
        }
      }
    }
"""
from __future__ import annotations
import asyncio
import os
import sys

# Windows async policy fix (see user memory notes)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Ensure backend/ is on the path regardless of CWD
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

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
