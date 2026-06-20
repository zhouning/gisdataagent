"""Lightweight scheduler for self-evolution cycles.

Runs conservative dry-run self-evolution cycles on an interval and persists
the reports for admin review. The scheduler is disabled by default and never
deploys prompt changes or writes eval datasets directly.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any

from .observability import get_logger
from .self_evolution import SelfEvolutionEngine

logger = get_logger("self_evolution_scheduler")


def _truthy(value: bool | str | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(value, max_value))


class SelfEvolutionScheduler:
    """Single-process interval scheduler for self-evolution dry-run cycles."""

    def __init__(
        self,
        *,
        enabled: bool | str | None = None,
        interval_seconds: int | None = None,
        days: int | None = None,
        limit: int | None = None,
        min_score: float | None = None,
        include_prompt_suggestions: bool | str | None = None,
        engine_factory: Any | None = None,
    ) -> None:
        self.enabled = (
            _truthy(enabled)
            if enabled is not None
            else _truthy(os.environ.get("SELF_EVOLUTION_SCHEDULER_ENABLED", "false"))
        )
        self.interval_seconds = interval_seconds or _env_int(
            "SELF_EVOLUTION_SCHEDULER_INTERVAL_SECONDS",
            86400,
            300,
            30 * 86400,
        )
        self.days = days or _env_int("SELF_EVOLUTION_SCHEDULER_DAYS", 7, 1, 90)
        self.limit = limit or _env_int("SELF_EVOLUTION_SCHEDULER_LIMIT", 50, 1, 100)
        try:
            self.min_score = float(os.environ.get("SELF_EVOLUTION_SCHEDULER_MIN_SCORE", "0.5"))
        except (TypeError, ValueError):
            self.min_score = 0.5
        if min_score is not None:
            self.min_score = float(min_score)
        self.min_score = max(0.0, min(self.min_score, 1.0))
        self.include_prompt_suggestions = (
            _truthy(include_prompt_suggestions)
            if include_prompt_suggestions is not None
            else _truthy(os.environ.get("SELF_EVOLUTION_SCHEDULER_INCLUDE_PROMPTS", "false"))
        )
        self.engine_factory = engine_factory or SelfEvolutionEngine
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False
        self._last_run_at: str | None = None
        self._last_cycle_id: int | None = None
        self._last_error: str = ""
        self._run_count = 0

    def start(self) -> bool:
        """Start scheduler in the current event loop. Returns True if started."""
        if not self.enabled:
            logger.info("Self-evolution scheduler disabled")
            return False
        if self._task and not self._task.done():
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Self-evolution scheduler start requires a running event loop")
            return False
        self._stop_event = asyncio.Event()
        self._task = loop.create_task(self._loop(), name="self-evolution-scheduler")
        logger.info(
            "Self-evolution scheduler started interval=%ss days=%s limit=%s prompts=%s",
            self.interval_seconds,
            self.days,
            self.limit,
            self.include_prompt_suggestions,
        )
        return True

    async def stop(self) -> None:
        """Stop scheduler and wait briefly for the loop task to finish."""
        if self._stop_event:
            self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stop_event = None
        self._running = False

    async def run_once(self) -> dict[str, Any]:
        """Run one scheduled dry-run cycle and persist it for review."""
        if self._running:
            return {"status": "skipped", "reason": "already_running"}
        self._running = True
        self._last_error = ""
        try:
            report = await self.engine_factory().run_cycle(
                limit=self.limit,
                days=self.days,
                min_score=self.min_score,
                include_prompt_suggestions=self.include_prompt_suggestions,
                apply=False,
                environment="dev",
                persist=True,
                triggered_by="self_evolution_scheduler",
                trigger_source="scheduler",
            )
            self._last_run_at = datetime.utcnow().isoformat() + "Z"
            self._last_cycle_id = report.get("cycle_id")
            self._run_count += 1
            return report
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Scheduled self-evolution cycle failed: %s", exc)
            return {"status": "error", "message": str(exc)}
        finally:
            self._running = False

    async def _loop(self) -> None:
        if self._stop_event is None:
            self._stop_event = asyncio.Event()
        while not self._stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def status(self) -> dict[str, Any]:
        active = bool(self._task and not self._task.done())
        return {
            "enabled": self.enabled,
            "active": active,
            "running": self._running,
            "interval_seconds": self.interval_seconds,
            "days": self.days,
            "limit": self.limit,
            "min_score": self.min_score,
            "include_prompt_suggestions": self.include_prompt_suggestions,
            "last_run_at": self._last_run_at,
            "last_cycle_id": self._last_cycle_id,
            "last_error": self._last_error,
            "run_count": self._run_count,
        }


_scheduler: SelfEvolutionScheduler | None = None


def get_self_evolution_scheduler() -> SelfEvolutionScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = SelfEvolutionScheduler()
    return _scheduler


def reset_self_evolution_scheduler() -> None:
    global _scheduler
    _scheduler = None
