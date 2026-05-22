"""Tests for backend.agent_core.truncate."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent_core.truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    OutputAccumulator,
    truncate_head,
    truncate_tail,
)


# ─── truncate_head / truncate_tail ────────────────────────────────────


def test_truncate_head_under_limit_returns_intact():
    text = "line1\nline2\nline3"
    out, truncated = truncate_head(text)
    assert truncated is False
    assert out == text


def test_truncate_head_with_byte_overflow_appends_hint():
    text = "x" * (DEFAULT_MAX_BYTES + 100)
    out, truncated = truncate_head(text)
    assert truncated is True
    assert "more bytes" in out or "more lines" in out
    assert out.startswith("x")  # head retained


def test_truncate_head_with_line_overflow_appends_hint():
    text = "\n".join(f"l{i}" for i in range(DEFAULT_MAX_LINES + 50))
    out, truncated = truncate_head(text)
    assert truncated is True
    assert "more lines" in out
    assert out.split("\n")[0] == "l0"


def test_truncate_tail_under_limit_returns_intact():
    text = "abc"
    out, truncated = truncate_tail(text)
    assert truncated is False
    assert out == "abc"


def test_truncate_tail_with_overflow_keeps_end_and_prepends_hint():
    text = "\n".join(f"l{i}" for i in range(DEFAULT_MAX_LINES + 50))
    out, truncated = truncate_tail(text)
    assert truncated is True
    assert "earlier" in out
    # Last line preserved (after the hint)
    assert out.rstrip().endswith(f"l{DEFAULT_MAX_LINES + 49}")


def test_truncate_head_custom_limits_apply():
    text = "abcdefghij"
    out, truncated = truncate_head(text, max_bytes=5, max_lines=10)
    assert truncated is True
    assert "more bytes" in out


def test_truncate_handles_unicode_safely():
    """Cut on a multi-byte char should not produce invalid UTF-8."""
    text = "中" * 1000  # 3 bytes per char
    out, truncated = truncate_head(text, max_bytes=100, max_lines=10000)
    assert truncated is True
    # Should be decodable / printable
    assert isinstance(out, str)


# ─── OutputAccumulator ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_accumulator_no_overflow_returns_buffer_no_log(tmp_path: Path):
    acc = OutputAccumulator("t1", "tc-1", max_inline_bytes=100, base_dir=tmp_path)
    await acc.feed("hello ")
    await acc.feed("world")
    preview, log_path = await acc.finalize()
    assert preview == "hello world"
    assert log_path is None


@pytest.mark.asyncio
async def test_accumulator_overflow_writes_file_and_returns_path(tmp_path: Path):
    acc = OutputAccumulator("t1", "tc-1", max_inline_bytes=20, base_dir=tmp_path)
    await acc.feed("A" * 30)  # triggers overflow
    await acc.feed("B" * 30)  # appended after overflow
    preview, log_path = await acc.finalize()
    assert log_path is not None
    p = Path(log_path)
    assert p.exists()
    full = p.read_text(encoding="utf-8")
    # Both flushes present
    assert full.count("A") == 30
    assert full.count("B") == 30
    # Preview limited
    assert "[full output saved to" in preview


@pytest.mark.asyncio
async def test_accumulator_preview_size_capped(tmp_path: Path):
    """Even when full content is huge, preview must not exceed cap (+ small footer)."""
    acc = OutputAccumulator("t1", "tc-1", max_inline_bytes=100, base_dir=tmp_path)
    await acc.feed("X" * 5000)
    preview, log_path = await acc.finalize()
    assert log_path is not None
    # preview = truncated content + footer; budget 100 bytes + reasonable footer (~80 chars)
    assert len(preview.encode("utf-8")) < 500


@pytest.mark.asyncio
async def test_accumulator_head_mode_keeps_beginning(tmp_path: Path):
    acc = OutputAccumulator(
        "t1", "tc-1", max_inline_bytes=20, base_dir=tmp_path, truncate_mode="head"
    )
    await acc.feed("HEADXXX_______MIDDLE_______YYYYTAIL")
    preview, log_path = await acc.finalize()
    assert log_path is not None
    assert preview.startswith("HEAD")


@pytest.mark.asyncio
async def test_accumulator_tail_mode_keeps_end(tmp_path: Path):
    acc = OutputAccumulator(
        "t1", "tc-1", max_inline_bytes=20, base_dir=tmp_path, truncate_mode="tail"
    )
    await acc.feed("HEADXXX_______MIDDLE_______YYYYTAIL")
    preview, log_path = await acc.finalize()
    assert log_path is not None
    # Tail content must appear before the appended footer
    assert "TAIL" in preview.split("[full output saved")[0]


@pytest.mark.asyncio
async def test_accumulator_invalid_truncate_mode_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        OutputAccumulator("t1", "tc-1", base_dir=tmp_path, truncate_mode="weird")
