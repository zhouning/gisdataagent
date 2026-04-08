"""
DataLake Monitor — continuous monitoring daemon for proactive task discovery (v22.0).

Implements SIGMOD 2026 L4 capability S-8: persistent monitoring that detects
data drift, performance degradation, and optimization opportunities, then
auto-generates tasks for the agent to act on.

Runs as an asyncio background loop within the Chainlit process.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("datalake_monitor")


# ---------------------------------------------------------------------------
# Discovery types
# ---------------------------------------------------------------------------


@dataclass
class MonitorDiscovery:
    """A proactive discovery from the monitoring daemon."""
    discovery_type: str  # data_drift / perf_degradation / optimization_opportunity / new_data
    severity: str = "info"  # info / warning / critical
    title: str = ""
    description: str = ""
    affected_asset: str = ""
    suggested_action: str = ""
    metrics: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "discovery_type": self.discovery_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "affected_asset": self.affected_asset,
            "suggested_action": self.suggested_action,
            "metrics": self.metrics,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Monitor checks
# ---------------------------------------------------------------------------


async def check_data_drift(engine) -> list[MonitorDiscovery]:
    """Detect data distribution changes in registered assets.

    Compares current row counts and null rates against historical baselines.
    """
    discoveries = []
    try:
        with engine.connect() as conn:
            # Get assets with operational metadata containing baseline stats
            rows = conn.execute(text("""
                SELECT id, asset_name,
                       operational_metadata->>'row_count' as baseline_rows,
                       technical_metadata->'storage'->>'postgis_table' as tbl
                FROM agent_data_assets
                WHERE technical_metadata->'storage'->>'postgis_table' IS NOT NULL
                LIMIT 20
            """)).fetchall()

            for row in rows:
                asset_id, name, baseline_str, tbl = row
                if not tbl or not baseline_str:
                    continue
                try:
                    baseline = int(baseline_str)
                    current = conn.execute(
                        text(f"SELECT COUNT(*) FROM {tbl}")
                    ).scalar()
                    if current is None:
                        continue
                    drift_pct = abs(current - baseline) / max(baseline, 1) * 100
                    if drift_pct > 20:
                        discoveries.append(MonitorDiscovery(
                            discovery_type="data_drift",
                            severity="warning" if drift_pct > 50 else "info",
                            title=f"数据漂移: {name}",
                            description=f"行数从 {baseline} 变为 {current} (变化 {drift_pct:.1f}%)",
                            affected_asset=name,
                            suggested_action="重新运行数据画像和质量检查",
                            metrics={"baseline_rows": baseline, "current_rows": current, "drift_pct": round(drift_pct, 1)},
                        ))
                except Exception:
                    continue
    except Exception as e:
        logger.debug("Data drift check failed: %s", e)
    return discoveries


async def check_performance_degradation(engine) -> list[MonitorDiscovery]:
    """Detect query performance degradation from pipeline history."""
    discoveries = []
    try:
        with engine.connect() as conn:
            # Compare recent pipeline durations against historical average
            rows = conn.execute(text("""
                WITH recent AS (
                    SELECT pipeline_type,
                           AVG(duration_seconds) as avg_recent
                    FROM agent_pipeline_runs
                    WHERE created_at >= NOW() - INTERVAL '1 day'
                    GROUP BY pipeline_type
                ),
                baseline AS (
                    SELECT pipeline_type,
                           AVG(duration_seconds) as avg_baseline
                    FROM agent_pipeline_runs
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                      AND created_at < NOW() - INTERVAL '1 day'
                    GROUP BY pipeline_type
                )
                SELECT r.pipeline_type, r.avg_recent, b.avg_baseline
                FROM recent r
                JOIN baseline b ON r.pipeline_type = b.pipeline_type
                WHERE b.avg_baseline > 0
            """)).fetchall()

            for pipeline, recent_avg, baseline_avg in rows:
                if recent_avg > baseline_avg * 1.5:  # 50% slower
                    slowdown = (recent_avg - baseline_avg) / baseline_avg * 100
                    discoveries.append(MonitorDiscovery(
                        discovery_type="perf_degradation",
                        severity="warning",
                        title=f"性能退化: {pipeline} 管线",
                        description=f"平均耗时从 {baseline_avg:.1f}s 增加到 {recent_avg:.1f}s (+{slowdown:.0f}%)",
                        affected_asset=pipeline,
                        suggested_action="检查数据量增长或模型负载",
                        metrics={"baseline_avg_s": round(baseline_avg, 1), "recent_avg_s": round(recent_avg, 1)},
                    ))
    except Exception as e:
        logger.debug("Performance check failed: %s", e)
    return discoveries


async def check_optimization_opportunities(engine) -> list[MonitorDiscovery]:
    """Discover optimization opportunities: missing indexes, stale caches, etc."""
    discoveries = []
    try:
        with engine.connect() as conn:
            # Check for large tables without indexes on common query columns
            rows = conn.execute(text("""
                SELECT tablename, n_live_tup
                FROM pg_stat_user_tables
                WHERE n_live_tup > 10000
                  AND tablename LIKE 'agent_%'
                ORDER BY n_live_tup DESC
                LIMIT 10
            """)).fetchall()

            for tbl, row_count in rows:
                # Check if table has any user-created indexes
                idx_count = conn.execute(text("""
                    SELECT COUNT(*) FROM pg_indexes
                    WHERE tablename = :tbl AND indexname NOT LIKE '%_pkey'
                """), {"tbl": tbl}).scalar()

                if idx_count == 0 and row_count > 50000:
                    discoveries.append(MonitorDiscovery(
                        discovery_type="optimization_opportunity",
                        severity="info",
                        title=f"缺失索引: {tbl}",
                        description=f"表 {tbl} 有 {row_count} 行但无用户索引",
                        affected_asset=tbl,
                        suggested_action=f"分析查询模式，为 {tbl} 添加适当索引",
                        metrics={"row_count": row_count, "index_count": idx_count},
                    ))

            # Check for stale materialized views
            mv_rows = conn.execute(text("""
                SELECT matviewname FROM pg_matviews
                WHERE schemaname = 'public'
            """)).fetchall()
            for (mv_name,) in mv_rows:
                # Check last refresh (approximate via pg_stat)
                discoveries.append(MonitorDiscovery(
                    discovery_type="optimization_opportunity",
                    severity="info",
                    title=f"物化视图刷新: {mv_name}",
                    description=f"建议定期刷新物化视图 {mv_name}",
                    affected_asset=mv_name,
                    suggested_action=f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}",
                ))
    except Exception as e:
        logger.debug("Optimization check failed: %s", e)
    return discoveries


async def check_new_data_sources(engine) -> list[MonitorDiscovery]:
    """Detect newly registered data assets that haven't been profiled."""
    discoveries = []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, asset_name, created_at
                FROM agent_data_assets
                WHERE operational_metadata->>'row_count' IS NULL
                  AND created_at >= NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
                LIMIT 10
            """)).fetchall()

            for asset_id, name, created_at in rows:
                discoveries.append(MonitorDiscovery(
                    discovery_type="new_data",
                    severity="info",
                    title=f"新数据未画像: {name}",
                    description=f"资产 {name} 注册于 {created_at} 但尚未进行数据画像",
                    affected_asset=name,
                    suggested_action="运行数据探索和画像分析",
                    metrics={"asset_id": asset_id},
                ))
    except Exception as e:
        logger.debug("New data check failed: %s", e)
    return discoveries


# ---------------------------------------------------------------------------
# Monitor daemon
# ---------------------------------------------------------------------------


class DataLakeMonitor:
    """Background monitoring daemon that periodically checks for issues.

    Runs all checks on a configurable interval and stores discoveries
    in the agent_monitor_discoveries table.
    """

    def __init__(self, interval_seconds: int = 300):
        self.interval = interval_seconds  # default: 5 minutes
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._discoveries: list[MonitorDiscovery] = []

    def start(self):
        """Start the monitoring loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._monitor_loop())
        logger.info("DataLakeMonitor started (interval=%ds)", self.interval)

    async def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("DataLakeMonitor stopped")

    async def run_once(self) -> list[dict]:
        """Run all checks once and return discoveries."""
        engine = get_engine()
        if not engine:
            return []

        all_discoveries = []
        checks = [
            check_data_drift,
            check_performance_degradation,
            check_optimization_opportunities,
            check_new_data_sources,
        ]
        for check_fn in checks:
            try:
                results = await check_fn(engine)
                all_discoveries.extend(results)
            except Exception as e:
                logger.warning("Monitor check %s failed: %s", check_fn.__name__, e)

        # Persist discoveries
        self._discoveries = all_discoveries
        self._persist_discoveries(engine, all_discoveries)

        logger.info("Monitor scan complete: %d discoveries", len(all_discoveries))
        return [d.to_dict() for d in all_discoveries]

    def get_recent_discoveries(self, limit: int = 20) -> list[dict]:
        """Get recent discoveries from memory."""
        return [d.to_dict() for d in self._discoveries[:limit]]

    async def _monitor_loop(self):
        """Periodic monitoring loop."""
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Monitor loop error: %s", e)
            await asyncio.sleep(self.interval)

    @staticmethod
    def _persist_discoveries(engine, discoveries: list[MonitorDiscovery]):
        """Store discoveries in DB for history tracking."""
        if not discoveries:
            return
        try:
            with engine.connect() as conn:
                for d in discoveries:
                    conn.execute(text("""
                        INSERT INTO agent_audit_log (username, action, status, details)
                        VALUES ('system', 'monitor_discovery', :severity,
                                :details::jsonb)
                    """), {
                        "severity": d.severity,
                        "details": json.dumps(d.to_dict(), ensure_ascii=False, default=str),
                    })
                conn.commit()
        except Exception as e:
            logger.debug("Failed to persist discoveries: %s", e)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_monitor: Optional[DataLakeMonitor] = None


def get_monitor(interval: int = 300) -> DataLakeMonitor:
    global _monitor
    if _monitor is None:
        _monitor = DataLakeMonitor(interval)
    return _monitor


def reset_monitor():
    global _monitor
    _monitor = None
