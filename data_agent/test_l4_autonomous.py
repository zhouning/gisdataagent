"""Tests for DataLakeMonitor + IntrinsicMotivation (v22.0)."""
import pytest
from unittest.mock import patch, MagicMock

from data_agent.datalake_monitor import (
    DataLakeMonitor, MonitorDiscovery,
    check_data_drift, check_new_data_sources,
    reset_monitor,
)
from data_agent.intrinsic_motivation import (
    IntrinsicMotivationEngine, EpsilonGreedyStrategy,
    MotivatedTask, compute_reward, reset_motivation_engine,
)


def _mock_engine():
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


@pytest.fixture(autouse=True)
def _reset():
    reset_monitor()
    reset_motivation_engine()
    yield
    reset_monitor()
    reset_motivation_engine()


# ---------------------------------------------------------------------------
# MonitorDiscovery
# ---------------------------------------------------------------------------

def test_discovery_to_dict():
    d = MonitorDiscovery(
        discovery_type="data_drift", severity="warning",
        title="Drift detected", affected_asset="parcels",
        metrics={"drift_pct": 35.0},
    )
    result = d.to_dict()
    assert result["discovery_type"] == "data_drift"
    assert result["severity"] == "warning"
    assert result["metrics"]["drift_pct"] == 35.0


# ---------------------------------------------------------------------------
# Data drift check
# ---------------------------------------------------------------------------

@patch("data_agent.datalake_monitor.get_engine")
def test_check_data_drift_detects(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    # Assets with baseline
    assets_result = MagicMock()
    assets_result.fetchall.return_value = [
        (1, "parcels.shp", "1000", "agent_dltb"),
    ]
    # Current count = 1500 (50% drift)
    count_result = MagicMock()
    count_result.scalar.return_value = 1500

    conn.execute.side_effect = [assets_result, count_result]

    import asyncio
    discoveries = asyncio.get_event_loop().run_until_complete(check_data_drift(engine))
    assert len(discoveries) == 1
    assert discoveries[0].discovery_type == "data_drift"
    assert discoveries[0].metrics["drift_pct"] == 50.0


@patch("data_agent.datalake_monitor.get_engine")
def test_check_data_drift_no_drift(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine

    assets_result = MagicMock()
    assets_result.fetchall.return_value = [
        (1, "stable.shp", "1000", "agent_stable"),
    ]
    count_result = MagicMock()
    count_result.scalar.return_value = 1050  # only 5% change

    conn.execute.side_effect = [assets_result, count_result]

    import asyncio
    discoveries = asyncio.get_event_loop().run_until_complete(check_data_drift(engine))
    assert len(discoveries) == 0


# ---------------------------------------------------------------------------
# New data check
# ---------------------------------------------------------------------------

@patch("data_agent.datalake_monitor.get_engine")
def test_check_new_data(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    from datetime import datetime

    conn.execute.return_value.fetchall.return_value = [
        (42, "new_upload.shp", datetime(2026, 4, 8)),
    ]

    import asyncio
    discoveries = asyncio.get_event_loop().run_until_complete(check_new_data_sources(engine))
    assert len(discoveries) == 1
    assert discoveries[0].discovery_type == "new_data"


# ---------------------------------------------------------------------------
# Monitor run_once
# ---------------------------------------------------------------------------

@patch("data_agent.datalake_monitor.get_engine")
def test_monitor_run_once(mock_get_engine):
    engine, conn = _mock_engine()
    mock_get_engine.return_value = engine
    # All checks return empty (no issues)
    conn.execute.return_value.fetchall.return_value = []
    conn.execute.return_value.scalar.return_value = 0

    monitor = DataLakeMonitor(interval_seconds=60)
    import asyncio
    results = asyncio.get_event_loop().run_until_complete(monitor.run_once())
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Reward computation
# ---------------------------------------------------------------------------

def test_compute_reward_base():
    assert compute_reward("new_data") == 10.0
    assert compute_reward("data_drift") == 8.0
    assert compute_reward("unknown_type") == 1.0


def test_compute_reward_with_metrics():
    reward = compute_reward("data_drift", {"drift_pct": 60})
    assert reward == 8.0 * 2.0  # >50% drift = 2x multiplier


def test_compute_reward_large_dataset():
    reward = compute_reward("optimization_opportunity", {"row_count": 200000})
    assert reward == 5.0 * 1.3  # >100k rows = 1.3x


# ---------------------------------------------------------------------------
# ε-greedy strategy
# ---------------------------------------------------------------------------

def test_epsilon_greedy_exploit():
    """With ε=0, always exploit (highest priority)."""
    strategy = EpsilonGreedyStrategy(epsilon=0.0, min_epsilon=0.0)
    tasks = [
        MotivatedTask(task_type="a", description="low", reward_estimate=1, priority_score=0.1),
        MotivatedTask(task_type="b", description="high", reward_estimate=10, priority_score=0.9),
    ]
    selected = strategy.select(tasks)
    assert selected.task_type == "b"


def test_epsilon_greedy_decay():
    strategy = EpsilonGreedyStrategy(epsilon=0.5, decay=0.9)
    tasks = [MotivatedTask(task_type="x", description="t", reward_estimate=5, priority_score=0.5)]
    # Run several selections to trigger decay
    for _ in range(10):
        strategy.select(tasks)
    assert strategy.current_epsilon < 0.5


def test_epsilon_greedy_empty():
    strategy = EpsilonGreedyStrategy()
    assert strategy.select([]) is None


# ---------------------------------------------------------------------------
# Motivation Engine
# ---------------------------------------------------------------------------

def test_generate_tasks_from_discoveries():
    engine = IntrinsicMotivationEngine()
    discoveries = [
        {"discovery_type": "data_drift", "severity": "warning",
         "title": "Drift", "suggested_action": "Re-profile",
         "metrics": {"drift_pct": 30}},
        {"discovery_type": "new_data", "severity": "info",
         "title": "New asset", "suggested_action": "Profile it",
         "metrics": {}},
    ]
    tasks = engine.generate_tasks(discoveries)
    assert len(tasks) == 2
    assert tasks[0].priority_score >= tasks[1].priority_score  # sorted by priority
    assert tasks[0].task_type in ("quality_check", "profile")


def test_select_next_task():
    engine = IntrinsicMotivationEngine(epsilon=0.0)  # always exploit
    discoveries = [
        {"discovery_type": "perf_degradation", "severity": "critical",
         "title": "Slow", "suggested_action": "Optimize",
         "metrics": {}},
    ]
    result = engine.select_next_task(discoveries)
    assert result is not None
    assert result["task_type"] == "optimize"


def test_select_next_task_empty():
    engine = IntrinsicMotivationEngine()
    assert engine.select_next_task([]) is None


def test_task_history():
    engine = IntrinsicMotivationEngine(epsilon=0.0)
    discoveries = [
        {"discovery_type": "new_data", "severity": "info",
         "title": "New", "suggested_action": "Profile", "metrics": {}},
    ]
    engine.select_next_task(discoveries)
    engine.select_next_task(discoveries)
    history = engine.get_task_history()
    assert len(history) == 2


def test_engine_stats():
    engine = IntrinsicMotivationEngine()
    stats = engine.stats
    assert "epsilon" in stats
    assert "total_tasks_generated" in stats
