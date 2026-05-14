"""Output truncation + accumulator for tool results.

Tools (especially ``bash``, ``http_get``, ``jshook_fetch``) frequently produce
output that's too long to feed back to the LLM verbatim — easily 100KB+ HTML
dumps or multi-thousand-line logs. This module provides:

* :func:`truncate_head` — keep the first N bytes/lines (read-style: source
  order matters, e.g. file reads).
* :func:`truncate_tail` — keep the last N bytes/lines (bash/fetch-style: the
  most recent output is usually what matters).
* :class:`OutputAccumulator` — async-friendly buffer that streams tool output;
  if the result fits inline (≤ ``max_inline_bytes``) we just return it; if it
  overflows, the full content is written to ``data/tool_outputs/<task_id>/<tc_id>.log``
  and the LLM-facing preview is truncated.

Constants are conservative defaults — callers may override per-tool.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

DEFAULT_MAX_BYTES = 50_000
DEFAULT_MAX_LINES = 2_000


# ─── Pure helpers ─────────────────────────────────────────────────────


def _truncate_to_limits(
    text: str,
    max_bytes: int,
    max_lines: int,
    *,
    keep_head: bool,
) -> tuple[str, bool, int, int]:
    """Returns (truncated_text, was_truncated, dropped_bytes, dropped_lines).

    Whichever limit hits first wins.
    """
    if not text:
        return "", False, 0, 0

    raw_bytes = text.encode("utf-8")
    raw_byte_len = len(raw_bytes)
    raw_lines = text.split("\n")
    raw_line_count = len(raw_lines)

    over_bytes = raw_byte_len > max_bytes
    over_lines = raw_line_count > max_lines
    if not over_bytes and not over_lines:
        return text, False, 0, 0

    # Determine cut by line first (more readable cuts), then by bytes.
    if keep_head:
        # Try line-first cut from head
        kept_lines = raw_lines
        if over_lines:
            kept_lines = raw_lines[:max_lines]
        kept = "\n".join(kept_lines)
        kept_bytes = kept.encode("utf-8")
        if len(kept_bytes) > max_bytes:
            # Further cut by bytes — find a safe utf-8 boundary
            cut = max_bytes
            while cut > 0 and (kept_bytes[cut] & 0xC0) == 0x80:
                cut -= 1
            kept = kept_bytes[:cut].decode("utf-8", errors="ignore")
        # Recompute droppage
        dropped_bytes = max(0, raw_byte_len - len(kept.encode("utf-8")))
        dropped_lines = max(0, raw_line_count - len(kept.split("\n")))
        return kept, True, dropped_bytes, dropped_lines
    else:
        # Tail
        kept_lines = raw_lines
        if over_lines:
            kept_lines = raw_lines[-max_lines:]
        kept = "\n".join(kept_lines)
        kept_bytes = kept.encode("utf-8")
        if len(kept_bytes) > max_bytes:
            # cut from beginning until safe
            start = len(kept_bytes) - max_bytes
            while start < len(kept_bytes) and (kept_bytes[start] & 0xC0) == 0x80:
                start += 1
            kept = kept_bytes[start:].decode("utf-8", errors="ignore")
        dropped_bytes = max(0, raw_byte_len - len(kept.encode("utf-8")))
        dropped_lines = max(0, raw_line_count - len(kept.split("\n")))
        return kept, True, dropped_bytes, dropped_lines


def truncate_head(
    text: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_lines: int = DEFAULT_MAX_LINES,
) -> tuple[str, bool]:
    """Keep the head of ``text``; append a hint when content was dropped.

    Returns ``(truncated_or_intact_text, was_truncated)``.
    """
    kept, truncated, dropped_bytes, dropped_lines = _truncate_to_limits(
        text, max_bytes, max_lines, keep_head=True
    )
    if not truncated:
        return text, False
    hint = f"\n... <{dropped_bytes} more bytes / {dropped_lines} more lines truncated>"
    return kept + hint, True


def truncate_tail(
    text: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_lines: int = DEFAULT_MAX_LINES,
) -> tuple[str, bool]:
    """Keep the tail of ``text``; prepend a hint when content was dropped."""
    kept, truncated, dropped_bytes, dropped_lines = _truncate_to_limits(
        text, max_bytes, max_lines, keep_head=False
    )
    if not truncated:
        return text, False
    hint = f"... <{dropped_bytes} earlier bytes / {dropped_lines} earlier lines truncated>\n"
    return hint + kept, True


# ─── OutputAccumulator ────────────────────────────────────────────────


class OutputAccumulator:
    """Streams chunks; if total exceeds ``max_inline_bytes``, write to disk.

    Usage::

        acc = OutputAccumulator(task_id="t1", tool_call_id="tc-1")
        async for chunk in stream:
            await acc.feed(chunk)
        preview, log_path = await acc.finalize()
        # Send `preview` back to the LLM; `log_path` (or None) goes into
        # ToolMessage.full_log_path so the UI can offer "show full output".
    """

    def __init__(
        self,
        task_id: str,
        tool_call_id: str,
        max_inline_bytes: int = DEFAULT_MAX_BYTES,
        *,
        base_dir: str | os.PathLike[str] | None = None,
        truncate_mode: str = "tail",
    ):
        self.task_id = task_id
        self.tool_call_id = tool_call_id
        self.max_inline_bytes = max_inline_bytes
        self._truncate_mode = truncate_mode
        if truncate_mode not in ("head", "tail"):
            raise ValueError(f"truncate_mode must be 'head' or 'tail', got {truncate_mode!r}")

        # Path resolution: default project root data dir, override-able for tests
        if base_dir is None:
            project_root = Path(__file__).resolve().parents[2]
            base_dir = project_root / "data" / "tool_outputs"
        self._base_dir = Path(base_dir)
        self._log_path: Path | None = None  # set once we overflow

        self._buffer: list[str] = []
        self._buffer_bytes: int = 0

    @property
    def log_path(self) -> str | None:
        return str(self._log_path) if self._log_path is not None else None

    async def feed(self, chunk: str) -> None:
        if not chunk:
            return
        self._buffer.append(chunk)
        self._buffer_bytes += len(chunk.encode("utf-8"))

        if self._buffer_bytes > self.max_inline_bytes and self._log_path is None:
            # First overflow: flush everything to disk
            target = self._base_dir / self.task_id / f"{self.tool_call_id}.log"
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            full = "".join(self._buffer)
            await asyncio.to_thread(target.write_text, full, encoding="utf-8")
            self._log_path = target
            return

        if self._log_path is not None:
            # Already overflowed: keep appending to disk (cheap append)
            text = chunk
            await asyncio.to_thread(self._append_to_log, text)

    def _append_to_log(self, text: str) -> None:
        # Synchronous helper run via to_thread.
        assert self._log_path is not None
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(text)

    async def finalize(self) -> tuple[str, str | None]:
        """Return (LLM-facing preview, full_log_path or None)."""
        if self._log_path is None:
            # Never overflowed — preview is the buffer verbatim
            return "".join(self._buffer), None

        # Overflowed — read whole file back, then truncate for preview
        full_text = await asyncio.to_thread(
            self._log_path.read_text, encoding="utf-8"
        )
        if self._truncate_mode == "head":
            preview, _ = truncate_head(full_text, max_bytes=self.max_inline_bytes)
        else:
            preview, _ = truncate_tail(full_text, max_bytes=self.max_inline_bytes)

        # Append a "(see full at ...)" footer so the LLM knows where to look.
        footer = f"\n[full output saved to: {self._log_path}]"
        return preview + footer, str(self._log_path)
