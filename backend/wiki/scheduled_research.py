"""Tick-driven worker that periodically runs auto_dispatch_from_gaps.

Round 14 makes the LLM self-audit loop actually self-driving. Round 13
added :func:`wiki.insights.auto_dispatch_from_gaps` and exposed it
behind ``GET /wiki/insights?auto_research=true`` — but that still
required a curator to hit the endpoint. With this worker enabled, the
backend itself ticks every ``WIKI_AUTO_RESEARCH_INTERVAL_HOURS`` and
fires research on whatever knowledge_gap pages survive the cooldown
filter. The wallet implications are non-trivial, hence:

1. **Default off** — the worker is only constructed + started when
   ``wiki_auto_research_enabled=True`` in settings.
2. **Re-uses the cooldown / cap policy** from Round 13 verbatim — same
   ``wiki_auto_research_max_per_run`` (default 3) and
   ``wiki_auto_research_cooldown_hours`` (default 24) caps apply.
3. **Polite startup** — the first tick waits one full interval before
   firing, so a backend that gets restarted hourly never fires twice
   in quick succession.
"""
from __future__ import annotations

import logging
from pathlib import Path

from workers import BackgroundWorker

logger = logging.getLogger(__name__)


class ScheduledResearchWorker(BackgroundWorker):
    """Periodic dispatcher that turns lint knowledge_gaps into research runs.

    Tick-driven: inherits the default :meth:`_run` loop from the base
    class; we only override :meth:`_loop_iteration` with the actual
    work and bump :attr:`TICK_INTERVAL_S` to the configured hours.
    """

    name = "scheduled-research"
    DRAIN_TIMEOUT_S = 5.0  # nothing real to drain; just settle quickly

    def __init__(
        self,
        data_dir: str | Path,
        *,
        interval_seconds: float,
        max_per_run: int,
        cooldown_hours: float,
        knowledge_gap_threshold: int = 1,
    ) -> None:
        super().__init__()
        self._data_dir = Path(data_dir).expanduser()
        self.TICK_INTERVAL_S = max(60.0, float(interval_seconds))  # never tick faster than 1/min
        self._max_per_run = max(0, int(max_per_run))
        self._cooldown_hours = max(0.0, float(cooldown_hours))
        self._knowledge_gap_threshold = max(0, int(knowledge_gap_threshold))
        # Stats specific to this worker.
        self._dispatched = 0
        self._skipped_cooldown = 0
        self._deferred = 0

    # ── overrides ──────────────────────────────────────────────

    async def _loop_iteration(self) -> None:
        """Run lint + graph_insights, hand the result to the dispatcher.

        Failures inside any single stage log + count toward the worker's
        ``failed`` total but never propagate; the loop will tick again.
        """
        # Lazy-import to avoid pulling the wiki stack at module load.
        from wiki.insights import (
            auto_dispatch_from_gaps,
            graph_insights,
            run_lint,
        )

        issues = []
        try:
            issues.extend(await run_lint(data_dir=self._data_dir))
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("run_lint failed: %s", exc)

        try:
            issues.extend(await graph_insights(
                knowledge_gap_threshold=self._knowledge_gap_threshold,
            ))
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("graph_insights failed: %s", exc)

        if not issues:
            self._logger.debug("no issues this tick — quiet wiki")
            return

        report = await auto_dispatch_from_gaps(
            issues,
            data_dir=self._data_dir,
            max_per_run=self._max_per_run,
            cooldown_hours=self._cooldown_hours,
        )

        n_dispatched = len(report.get("dispatched") or [])
        n_skipped    = len(report.get("skipped_cooldown") or [])
        n_deferred   = len(report.get("deferred") or [])
        self._dispatched      += n_dispatched
        self._skipped_cooldown += n_skipped
        self._deferred        += n_deferred

        if n_dispatched:
            self._logger.info(
                "tick → dispatched=%d skipped_cooldown=%d deferred=%d",
                n_dispatched, n_skipped, n_deferred,
            )
        else:
            self._logger.debug(
                "tick → no new dispatches (skipped=%d deferred=%d)",
                n_skipped, n_deferred,
            )

    def stats(self) -> dict[str, int]:
        return {
            **super().stats(),
            "dispatched":       self._dispatched,
            "skipped_cooldown": self._skipped_cooldown,
            "deferred":         self._deferred,
            "interval_s":       int(self.TICK_INTERVAL_S),
        }
