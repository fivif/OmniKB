"""Dynamic LangChain tool registration for jshookmcp.

At app startup we query jshookmcp via tools/list, filter by ALLOWED_PREFIXES,
cap at TOOL_LIMIT, and convert each MCP tool descriptor into a LangChain
StructuredTool that uses JsHookPool under the hood.

JSON Schema -> pydantic conversion is intentionally minimal: we handle the
common cases (object with typed properties, basic primitives, arrays).
oneOf/anyOf and other edge constructs fall back to ``Any``.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import Field, create_model

from agents.web import pool as _pool_mod

logger = logging.getLogger(__name__)

ALLOWED_PREFIXES: tuple[str, ...] = (
    "page_", "network_", "stealth_", "browser_", "cdp_",
)
# Meta-tools jshookmcp exposes by default. These are how an agent discovers
# and activates the 388+ specialised tools (search → activate → call).
# Without these in the registry, the agent has no entry point into jshookmcp.
META_TOOLS: frozenset[str] = frozenset({
    "search_tools",      # find tools by keyword/description
    "describe_tool",     # show a tool's full schema before calling it
    "activate_tools",    # activate one or more tools by name
    "activate_domain",   # activate an entire domain at once
    "call_tool",         # invoke an activated tool
})
TOOL_LIMIT: int = 50
SKIP: frozenset[str] = frozenset({
    "browser_launch", "browser_close",
    "page_screenshot",
    # Skip these meta-tools the agent rarely needs and we want to avoid
    # destabilising the toolset mid-run.
    "deactivate_tools", "route_tool",
})

_PRIM_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_schema_field(prop_schema: dict, required: bool) -> tuple[Any, Any]:
    if not isinstance(prop_schema, dict):
        return (Any, Field(... if required else None))

    desc = prop_schema.get("description", "")[:200]
    t = prop_schema.get("type")

    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        py_type = _PRIM_TYPES.get(non_null[0], Any) if non_null else Any
    elif isinstance(t, str):
        py_type = _PRIM_TYPES.get(t, Any)
    else:
        py_type = Any

    if required:
        return (py_type, Field(..., description=desc))
    default = prop_schema.get("default")
    return (py_type, Field(default, description=desc))


def _build_args_model(tool_name: str, schema):
    if not isinstance(schema, dict):
        return create_model(f"{tool_name}_args")

    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if not props:
        return create_model(f"{tool_name}_args")

    fields: dict[str, tuple[Any, Any]] = {}
    for name, prop in props.items():
        if not isinstance(name, str) or name.startswith("__"):
            continue
        fields[name] = _json_schema_field(prop, required=name in required)

    return create_model(f"{tool_name}_args", **fields)


def _compact_desc(desc: str, max_chars: int = 180) -> str:
    desc = (desc or "").strip().replace("\n", " ")
    if len(desc) <= max_chars:
        return desc
    return desc[:max_chars - 1].rstrip() + "..."


def _make_runner(tool_name: str):
    async def _runner(**kwargs):
        pool = _pool_mod.JSHOOK_POOL
        if pool is None or not pool.available:
            return f"[jshook tool {tool_name} unavailable: pool not started]"
        try:
            async with pool.acquire(timeout=30.0) as client:
                from agents.jshook_client import JsHookMcpClient
                raw = await client.call_tool(tool_name, kwargs, timeout=60.0)
                return JsHookMcpClient.extract_text(raw)[:8000]
        except Exception as exc:
            logger.warning("jshook tool %s failed: %s", tool_name, exc)
            return f"[jshook tool {tool_name} error: {exc}]"

    _runner.__name__ = f"jshook_{tool_name}"
    return _runner


async def discover_jshook_tools(pool=None, allowed_prefixes=ALLOWED_PREFIXES, limit=TOOL_LIMIT):
    pool = pool or _pool_mod.JSHOOK_POOL
    if pool is None or not pool.available:
        logger.warning("discover_jshook_tools: pool unavailable")
        return []

    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        logger.warning("langchain_core not installed; cannot register jshook tools")
        return []

    try:
        async with pool.acquire(timeout=30.0) as client:
            meta = await client.list_tools()
    except Exception as exc:
        logger.warning("discover_jshook_tools: list_tools failed: %s", exc)
        return []

    if not isinstance(meta, list):
        logger.warning("discover_jshook_tools: unexpected tools/list shape: %r", type(meta))
        return []

    selected = []
    seen: set[str] = set()
    for m in meta:
        if not isinstance(m, dict):
            continue
        name = m.get("name", "")
        if not name or name in seen or name in SKIP:
            continue
        # Accept either a meta-tool (always-on entrypoints) or a domain tool
        # whose name carries an allowed prefix.
        if name not in META_TOOLS and not name.startswith(allowed_prefixes):
            continue
        seen.add(name)
        selected.append(m)
        if len(selected) >= limit:
            break

    tools = []
    for m in selected:
        name = m["name"]
        try:
            ArgsModel = _build_args_model(name, m.get("inputSchema"))
        except Exception as exc:
            logger.debug("schema build failed for %s: %s -- skipping", name, exc)
            continue
        runner = _make_runner(name)
        try:
            tool = StructuredTool.from_function(
                coroutine=runner,
                name=f"jshook__{name}",
                description=_compact_desc(m.get("description", "")),
                args_schema=ArgsModel,
            )
            tools.append(tool)
        except Exception as exc:
            logger.debug("StructuredTool build failed for %s: %s -- skipping", name, exc)
            continue

    logger.info("Registered %d jshook tools as LangChain tools", len(tools))
    return tools
