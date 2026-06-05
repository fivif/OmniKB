"""JsHookMcpClient — async MCP stdio client for @jshookmcp/jshook.

jshookmcp exposes 387+ tools across 36 domains (browser automation, network
interception, JS deobfuscation, CDP debugging, WASM analysis, …).

Typical use:
    async with JsHookMcpClient() as client:
        # One-shot page text extraction
        text = await client.fetch_page("https://example.com")

    # Generic tool call
    async with JsHookMcpClient(profile="workflow") as client:
        result = await client.call_tool("page_navigate", {"url": "https://example.com"})
        html   = await client.call_tool(
            "page_evaluate",
            {"expression": "document.documentElement.outerHTML"},
        )

MCP transport: stdio / JSON-RPC 2.0, newline-delimited messages.
Server binary : npx -y @jshookmcp/jshook@latest
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_MCP_VERSION = "2024-11-05"

# Browser tools needed in workflow profile
_BROWSER_TOOLS = [
    "browser_launch",
    "page_navigate",
    "page_evaluate",
    "page_wait_for_selector",
    "page_cookies",
    "stealth_inject",
    "browser_close",
]


class JsHookMcpClient:
    """Async MCP stdio client for @jshookmcp/jshook.

    Parameters
    ----------
    profile:
        ``'search'``   — minimal startup (~3K tokens), discover tools via search_tools.
        ``'workflow'`` — browser + network + workflow domains pre-loaded (default).
        ``'full'``     — all 387 tools available (~40K tokens, slower init).
    """

    def __init__(self, profile: str = "workflow") -> None:
        self._profile = profile
        self._proc: asyncio.subprocess.Process | None = None
        self._id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._initialized = False
        self._exit_code: int | None = None

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the server subprocess and complete MCP initialize handshake."""
        npx = shutil.which("npx")
        if not npx:
            raise RuntimeError(
                "npx not found — install Node.js to use jshookmcp"
            )

        try:
            from utils.agent_bus import emit as _emit
        except ImportError:
            def _emit(*a, **kw): pass  # type: ignore

        env = {**os.environ, "JSHOOK_BASE_PROFILE": self._profile}
        _emit(f"启动 jshookmcp 服务器 (profile={self._profile})…", kind="progress", agent="jshook")
        self._proc = await asyncio.create_subprocess_exec(
            npx, "-y", "@jshookmcp/jshook@latest",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        # MCP handshake
        await self._request(
            "initialize",
            {
                "protocolVersion": _MCP_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "omnigkb", "version": "1.0.0"},
            },
            timeout=60.0,
        )
        await self._notify("notifications/initialized", {})
        self._initialized = True
        _emit(f"[OK] jshookmcp 就绪 (pid={self._proc.pid})", kind="success", agent="jshook")
        logger.info("jshookmcp ready (profile=%s, pid=%s)", self._profile, self._proc.pid)

    async def close(self) -> None:
        """Terminate the server subprocess and cancel the reader task."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await asyncio.wait_for(self._reader_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._initialized = False

    async def reconnect(self, *, max_retries: int = 3) -> bool:
        """Reconnect to the jshookmcp server with exponential backoff.

        Returns True on success, False if all retries exhausted.
        Use when the reader loop detects the process has unexpectedly exited.
        """
        for attempt in range(1, max_retries + 1):
            delay = min(1.0 * (2 ** (attempt - 1)), 30.0)
            logger.info(
                "jshookmcp reconnect attempt %d/%d (delay=%.1fs)",
                attempt, max_retries, delay,
            )
            try:
                # Fully tear down any remnants before retrying.
                await self.close()
                await asyncio.sleep(delay)
                await self.start()
                logger.info(
                    "jshookmcp reconnected (profile=%s, pid=%s)",
                    self._profile,
                    self._proc.pid if self._proc else "?",
                )
                return True
            except Exception as exc:
                logger.warning(
                    "jshookmcp reconnect attempt %d failed: %s",
                    attempt, exc,
                )
        logger.error(
            "jshookmcp reconnect exhausted (%d attempts, profile=%s)",
            max_retries, self._profile,
        )
        return False

    async def __aenter__(self) -> "JsHookMcpClient":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Internal transport ────────────────────────────────────

    async def _read_loop(self) -> None:
        """Background task: read JSON-RPC messages from the server stdout."""
        assert self._proc is not None
        try:
            while True:
                try:
                    raw = await self._proc.stdout.readline()
                except (asyncio.CancelledError, Exception):
                    break
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("jshookmcp unparseable: %.120s", line)
                    continue
                msg_id = msg.get("id")
                if msg_id is not None:
                    fut = self._pending.pop(int(msg_id), None)
                    if fut and not fut.done():
                        if "error" in msg:
                            err = msg["error"]
                            fut.set_exception(
                                RuntimeError(
                                    err.get("message", str(err)) if isinstance(err, dict) else str(err)
                                )
                            )
                        else:
                            fut.set_result(msg.get("result"))
        finally:
            # Capture exit code so the pool / caller can inspect why it died.
            if self._proc is not None:
                if self._proc.returncode is None:
                    self._exit_code = -15  # approximate: shut down externally
                else:
                    self._exit_code = self._proc.returncode
            else:
                self._exit_code = -1
            logger.warning(
                "jshookmcp disconnected (profile=%s, pid=%s, exit_code=%s)",
                self._profile,
                self._proc.pid if self._proc else "?",
                self._exit_code,
            )

        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("jshookmcp process ended"))
        self._pending.clear()

    async def _request(self, method: str, params: dict, timeout: float = 60.0) -> Any:
        assert self._proc is not None
        self._id += 1
        msg_id = self._id
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[msg_id] = fut

        data = (json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}) + "\n").encode()
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

        return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)

    async def _notify(self, method: str, params: dict) -> None:
        assert self._proc is not None
        data = (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n").encode()
        self._proc.stdin.write(data)
        await self._proc.stdin.drain()

    # ── Public API ────────────────────────────────────────────

    async def call_tool(self, name: str, arguments: dict, timeout: float = 60.0) -> Any:
        """Call a jshookmcp tool by name.

        Returns the raw MCP result (usually ``{"content": [{"type": "text", "text": ...}]}``).
        Use :meth:`extract_text` to get a plain string from the result.
        """
        if not self._initialized:
            raise RuntimeError("Client not started — use 'async with JsHookMcpClient()'")
        return await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )

    @staticmethod
    def extract_text(result: Any) -> str:
        """Extract text from an MCP tool result (content-array format)."""
        if isinstance(result, dict) and "content" in result:
            parts: list[str] = []
            for item in result["content"]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "resource":
                    parts.append(str(item.get("resource", {}).get("text", "")))
            return "\n".join(parts)
        if isinstance(result, str):
            return result
        return json.dumps(result) if result is not None else ""

    async def search_tools(self, query: str) -> str:
        """BM25-ranked tool search; returns formatted result text.

        Preferred chain: search_tools → activate_tools → call_tool.
        """
        result = await self.call_tool("search_tools", {"query": query})
        return self.extract_text(result)

    async def activate_tools(self, tool_names: list[str]) -> None:
        """Make specific tools available from the current profile tier."""
        await self.call_tool("activate_tools", {"tools": tool_names})

    async def activate_domain(self, domain: str) -> None:
        """Bulk-activate all tools in a domain (e.g. 'page', 'network', 'browser')."""
        await self.call_tool("activate_domain", {"domain": domain})

    async def list_tools(self) -> list[dict]:
        """List all currently exposed MCP tools."""
        result = await self._request("tools/list", {})
        return result.get("tools", []) if isinstance(result, dict) else []

    # ── High-level helpers ────────────────────────────────────

    async def fetch_page(self, url: str, cookies: dict | None = None, stealth: bool = False) -> str:
        """Render *url* in Chromium via jshookmcp and return the page text.

        Parameters
        ----------
        url:
            Target URL.
        cookies:
            Optional ``{name: value}`` dict; injected before navigation.
        stealth:
            If True, call ``stealth_inject`` before navigation to reduce
            bot-detection fingerprinting.
        """
        # Ensure browser tools are active (no-op if already loaded in profile)
        try:
            await self.activate_tools(_BROWSER_TOOLS)
        except Exception as exc:
            logger.debug("activate_tools (non-fatal): %s", exc)

        # Launch headless browser
        try:
            await self.call_tool("browser_launch", {}, timeout=30.0)
        except Exception as exc:
            logger.debug("browser_launch: %s", exc)

        # Optional stealth mode
        if stealth:
            try:
                await self.call_tool("stealth_inject", {}, timeout=15.0)
            except Exception as exc:
                logger.debug("stealth_inject (non-fatal): %s", exc)

        # Inject cookies before navigating (so they're available from the start)
        if cookies:
            domain = urlparse(url).netloc
            cookie_list = [
                {"name": k, "value": v, "domain": domain, "path": "/"}
                for k, v in cookies.items()
            ]
            try:
                await self.call_tool(
                    "page_cookies",
                    {"action": "set", "cookies": cookie_list},
                    timeout=10.0,
                )
            except Exception as exc:
                logger.debug("page_cookies set (non-fatal): %s", exc)

        text = ""
        try:
            await self.call_tool("page_navigate", {"url": url}, timeout=45.0)

            # Try plain text first
            result = await self.call_tool(
                "page_evaluate",
                {"expression": "document.body ? document.body.innerText : document.documentElement.textContent"},
                timeout=30.0,
            )
            text = self.extract_text(result).strip()

            if not text:
                # Fall back to full HTML
                result = await self.call_tool(
                    "page_evaluate",
                    {"expression": "document.documentElement.outerHTML"},
                    timeout=30.0,
                )
                text = self.extract_text(result).strip()
        finally:
            try:
                await self.call_tool("browser_close", {}, timeout=10.0)
            except Exception:
                pass

        return text
