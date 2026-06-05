"""OmniKB Doctor — pre-flight environment check.

Run BEFORE starting the server to catch:
- Missing system binaries (ffmpeg, chromium)
- Missing / empty config keys (delegates to config.verify_settings)
- Unreachable LLM / embedding endpoints
- Inaccessible data directories

Exit codes:
    0 — all checks passed (or only warnings)
    1 — at least one ERROR found
    2 — script crashed

Usage:
    python -m scripts.doctor              # full check
    python -m scripts.doctor --quick      # skip network probes
    python -m scripts.doctor --json       # machine-readable output
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import shutil
import sys
from pathlib import Path


# Make ``config`` etc. importable when invoked as ``python scripts/doctor.py``
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Disable TF / JAX before any transitive import drags them in (mirrors main.py).
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_JAX", "0")


class Reporter:
    """Collects checks and emits human / json output."""

    def __init__(self, json_mode: bool = False):
        self.results: list[dict] = []
        self.json_mode = json_mode

    def add(self, name: str, level: str, message: str, hint: str = "") -> None:
        self.results.append({
            "name": name,
            "level": level,  # ok | warn | error
            "message": message,
            "hint": hint,
        })
        if not self.json_mode:
            icon = {"ok": "+", "warn": "!", "error": "X"}.get(level, "?")
            colour = {"ok": "\033[32m", "warn": "\033[33m", "error": "\033[31m"}.get(level, "")
            reset = "\033[0m"
            print(f" {colour}{icon}{reset} {name:32} {message}")
            if hint and level != "ok":
                print(f"     ↳ {hint}")

    @property
    def has_error(self) -> bool:
        return any(r["level"] == "error" for r in self.results)

    @property
    def has_warn(self) -> bool:
        return any(r["level"] == "warn" for r in self.results)

    def summary(self) -> dict:
        return {
            "ok":    sum(1 for r in self.results if r["level"] == "ok"),
            "warn":  sum(1 for r in self.results if r["level"] == "warn"),
            "error": sum(1 for r in self.results if r["level"] == "error"),
        }


# ── Individual checks ────────────────────────────────────────────


def check_python(rep: Reporter) -> None:
    v = sys.version_info
    if v >= (3, 11):
        rep.add("python.version", "ok", f"{v.major}.{v.minor}.{v.micro}")
    else:
        rep.add(
            "python.version",
            "error",
            f"{v.major}.{v.minor}.{v.micro} too old",
            "OmniKB requires Python >= 3.11",
        )


def check_binary(rep: Reporter, name: str, *, required: bool, hint: str = "") -> None:
    path = shutil.which(name)
    if path:
        rep.add(f"binary.{name}", "ok", path)
    elif required:
        rep.add(f"binary.{name}", "error", "not found in PATH", hint)
    else:
        rep.add(f"binary.{name}", "warn", "not found in PATH (optional)", hint)


def check_python_packages(rep: Reporter) -> None:
    required = [
        "fastapi", "uvicorn", "pydantic", "pydantic_settings",
        "qdrant_client", "aiosqlite", "openai", "langchain_openai",
        "fastmcp", "pdfplumber", "bs4", "httpx", "fastembed",
    ]
    optional = [
        ("faster_whisper", "audio/video transcription"),
        ("sentence_transformers", "cross-encoder reranking"),
        ("scrapling", "static web fetching"),
        ("patchright", "stealth Playwright rendering"),
    ]
    for pkg in required:
        try:
            mod = importlib.import_module(pkg)
            version = getattr(mod, "__version__", "?")
            rep.add(f"pkg.{pkg}", "ok", version)
        except ImportError as exc:
            rep.add(f"pkg.{pkg}", "error", "import failed", str(exc))
    for pkg, use in optional:
        try:
            mod = importlib.import_module(pkg)
            version = getattr(mod, "__version__", "?")
            rep.add(f"pkg.{pkg}", "ok", f"{version} ({use})")
        except ImportError:
            rep.add(f"pkg.{pkg}", "warn", f"not installed ({use} disabled)")


def check_config(rep: Reporter) -> None:
    try:
        from config import settings, verify_settings  # type: ignore
    except Exception as exc:
        rep.add("config.load", "error", "could not import config", str(exc))
        return

    rep.add("config.load", "ok", f"{len(type(settings).model_fields)} fields")

    issues = verify_settings()
    if not issues:
        rep.add("config.verify", "ok", "no drift detected")
        return
    for issue in issues:
        # MCP default key is a security issue, treat as error; others are warnings
        # because the app still starts.
        level = "error" if "MCP_API_KEY" in issue else "warn"
        rep.add("config.verify", level, issue)


def check_data_dirs(rep: Reporter) -> None:
    try:
        from config import settings  # type: ignore
    except Exception:
        return
    candidates = [
        ("data_dir", settings.data_dir),
        ("qdrant_local_path", settings.qdrant_local_path),
        ("fastembed_cache_path", settings.fastembed_cache_path or os.path.expanduser("~/.cache/fastembed")),
    ]
    for label, raw in candidates:
        if not raw:
            continue
        p = Path(raw)
        try:
            p.mkdir(parents=True, exist_ok=True)
            # Write probe
            probe = p / ".doctor-probe"
            probe.write_text("ok")
            probe.unlink(missing_ok=True)
            rep.add(f"dir.{label}", "ok", str(p))
        except Exception as exc:
            rep.add(f"dir.{label}", "error", f"unwriteable: {p}", str(exc))


async def check_llm_endpoint(rep: Reporter) -> None:
    try:
        from config import settings  # type: ignore
        from openai import AsyncOpenAI
    except Exception as exc:
        rep.add("net.llm", "error", "openai SDK unavailable", str(exc))
        return

    base = settings.llm_base_url
    key = settings.llm_api_key
    if not key:
        rep.add("net.llm", "warn", "skipped (no llm_api_key)")
        return
    client = AsyncOpenAI(api_key=key, base_url=base, timeout=10.0)
    try:
        # Cheap call: list models. Most OpenAI-compatible gateways support it.
        await client.models.list()
        rep.add("net.llm", "ok", f"{base} reachable")
    except Exception as exc:
        rep.add(
            "net.llm",
            "warn",
            f"reach failed for {base}",
            f"{type(exc).__name__}: {str(exc)[:120]}",
        )
    finally:
        await client.close()


async def check_embedding_endpoint(rep: Reporter) -> None:
    try:
        from config import settings  # type: ignore
        from openai import AsyncOpenAI
    except Exception:
        return

    if settings.embedding_provider != "siliconflow":
        return
    key = settings.siliconflow_api_key
    if not key:
        rep.add("net.embed", "warn", "skipped (no siliconflow_api_key)")
        return
    client = AsyncOpenAI(api_key=key, base_url=settings.siliconflow_base_url, timeout=10.0)
    try:
        resp = await client.embeddings.create(
            model=settings.embedding_model,
            input=["doctor probe"],
        )
        dim = len(resp.data[0].embedding) if resp.data else 0
        rep.add("net.embed", "ok", f"{settings.embedding_model} dim={dim}")
    except Exception as exc:
        rep.add(
            "net.embed",
            "warn",
            "reach failed",
            f"{type(exc).__name__}: {str(exc)[:120]}",
        )
    finally:
        await client.close()


# ── Main ────────────────────────────────────────────────────────


async def run_all(args: argparse.Namespace) -> Reporter:
    rep = Reporter(json_mode=args.json)

    if not args.json:
        print("\nOmniKB Doctor — environment pre-flight\n")
        print(" runtime")

    check_python(rep)
    check_binary(rep, "ffmpeg", required=True,
                 hint="Install: apt install ffmpeg / brew install ffmpeg")
    check_binary(rep, "git", required=False)

    if not args.json:
        print("\n packages")
    check_python_packages(rep)

    if not args.json:
        print("\n config")
    check_config(rep)
    check_data_dirs(rep)

    if not args.quick:
        if not args.json:
            print("\n network")
        await check_llm_endpoint(rep)
        await check_embedding_endpoint(rep)

    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniKB environment doctor")
    parser.add_argument(
        "--quick", action="store_true",
        help="skip network reachability probes (faster, offline-safe)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON instead of human text",
    )
    args = parser.parse_args()

    try:
        rep = asyncio.run(run_all(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"\ndoctor crashed: {exc}", file=sys.stderr)
        return 2

    summary = rep.summary()
    if args.json:
        print(json.dumps({
            "summary": summary,
            "results": rep.results,
            "exit_code": 1 if rep.has_error else 0,
        }, ensure_ascii=False, indent=2))
    else:
        print(
            f"\n summary: {summary['ok']} ok, "
            f"{summary['warn']} warn, {summary['error']} error\n"
        )
        if rep.has_error:
            print(" → fix ERROR items before starting the server.")
        elif rep.has_warn:
            print(" → server can start, but some features may be disabled.")
        else:
            print(" → ready to launch.\n")

    return 1 if rep.has_error else 0


if __name__ == "__main__":
    sys.exit(main())
