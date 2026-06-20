"""Tests for the self-evolution orchestration loop."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from data_agent.self_evolution import (
    SelfEvolutionEngine,
    ensure_self_evolution_tables,
    get_cycle,
    get_review_summary,
    list_cycles,
    record_cycle,
    review_cycle_action,
)


class FakeCollector:
    async def collect_all(self, min_score=0.5, days=7, limit=50):
        return [
            {
                "source": "agent_feedback",
                "pipeline": "general",
                "details": {
                    "query": "查询坡度超过25度的地块",
                    "response": "wrong",
                    "issue": "missed filter",
                },
            },
            {
                "source": "eval_history",
                "pipeline": "nl2sql",
                "score": 0.2,
                "details": {"query": "统计建设用地面积"},
            },
        ]


class FakeAnalyzer:
    async def analyze(self, bad_cases):
        return {
            "patterns": [
                {
                    "category": "prompt_unclear",
                    "description": "spatial filters omitted",
                    "frequency": len(bad_cases),
                    "examples": [],
                }
            ],
            "root_causes": ["planner prompt does not require explicit filters"],
            "affected_prompts": ["planner/planner_instruction", "bad-ref"],
        }


class FakePromptOptimizer:
    async def suggest_improvements(self, domain, prompt_key, failure_analysis):
        return {
            "suggested_prompt": "improved",
            "changes": ["Require explicit filters"],
            "expected_improvement": "fewer omitted predicates",
        }

    async def apply_suggestion(self, domain, prompt_key, suggested_prompt, environment="dev"):
        return {"status": "created", "version_id": 7, "environment": environment}


class FakeEvolutionEngine:
    def update_reliability_from_db(self):
        return json.dumps({"status": "success", "updated": 2})

    def get_failure_driven_suggestions(self, failed_tool, error_message):
        return json.dumps({
            "status": "success",
            "suggestions": [
                {
                    "tool": "reproject_spatial_data",
                    "type": "prerequisite",
                    "reason": "CRS mismatch",
                    "description": "Reproject layers",
                }
            ],
        })


class FakeFeedbackStore:
    def get_stats(self, days=7):
        return {
            "total": 3,
            "upvotes": 1,
            "downvotes": 2,
            "satisfaction_rate": 0.3333,
            "by_pipeline": {"general": {"up": 1, "down": 2}},
            "trend": [],
        }

    def list_unresolved_downvotes(self, limit=50):
        return [{"id": 1}, {"id": 2}]


class FakePromptRegistry:
    def create_version(self, domain, prompt_key, prompt_text, env="dev", change_reason="", created_by="system"):
        assert prompt_text == "improved prompt"
        assert env == "dev"
        return 123


class FakeDeployPromptRegistry:
    def __init__(self):
        self.deployed = []

    def deploy(self, version_id, target_env):
        self.deployed.append((version_id, target_env))
        assert target_env == "prod"
        return {"version_id": 900 + int(version_id), "environment": target_env}


class FakeEvalDatasetManager:
    def create_dataset(self, scenario, name, test_cases, version="1.0", description="", created_by="system"):
        assert scenario == "self_evolution"
        assert name == "cycle-review"
        assert len(test_cases) == 1
        return 456


@pytest.mark.asyncio
async def test_self_evolution_cycle_dry_run_generates_auditable_proposals():
    engine = SelfEvolutionEngine(
        collector=FakeCollector(),
        analyzer=FakeAnalyzer(),
        prompt_optimizer=FakePromptOptimizer(),
        evolution_engine=FakeEvolutionEngine(),
        feedback_store=FakeFeedbackStore(),
    )
    with patch.object(engine, "collect_tool_failures", return_value=[
        {
            "id": 1,
            "tool_name": "pairwise_clip",
            "error": "CRS mismatch EPSG:4326 vs EPSG:32650",
            "resolved": False,
        }
    ]):
        result = await engine.run_cycle(limit=10, days=14, persist=False)

    assert result["status"] == "success"
    assert result["mode"] == "dry_run"
    assert result["summary"]["bad_cases"] == 2
    assert result["summary"]["tool_failures"] == 1
    assert result["summary"]["unresolved_downvotes"] == 2
    assert result["summary"]["patterns"] == 1
    assert result["summary"]["prompt_targets"] == 1
    assert result["tool_reliability"]["updated"] == 2
    assert result["proposals"]["tool_suggestions"][0]["suggested_tool"] == "reproject_spatial_data"
    assert result["proposals"]["prompt_suggestions"] == []
    assert result["proposals"]["eval_candidates"]
    assert result["safeguards"]["dry_run_default"] is True


@pytest.mark.asyncio
async def test_self_evolution_cycle_can_generate_and_apply_dev_prompt_suggestions():
    optimizer = FakePromptOptimizer()
    engine = SelfEvolutionEngine(
        collector=FakeCollector(),
        analyzer=FakeAnalyzer(),
        prompt_optimizer=optimizer,
        evolution_engine=FakeEvolutionEngine(),
        feedback_store=FakeFeedbackStore(),
    )
    with patch.object(engine, "collect_tool_failures", return_value=[]):
        result = await engine.run_cycle(
            include_prompt_suggestions=True,
            apply=True,
            environment="dev",
            persist=False,
        )

    suggestions = result["proposals"]["prompt_suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["domain"] == "planner"
    assert suggestions[0]["prompt_key"] == "planner_instruction"
    assert suggestions[0]["suggested_prompt"] == "improved"
    assert suggestions[0]["applied"] is True
    assert suggestions[0]["apply_result"]["environment"] == "dev"


def test_collect_tool_failures_no_db_returns_empty():
    with patch("data_agent.self_evolution.get_engine", return_value=None):
        assert SelfEvolutionEngine(evolution_engine=FakeEvolutionEngine()).collect_tool_failures() == []


def test_collect_tool_failures_reads_failure_learning_table():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        (1, "query_database", "relation not found", "list tables", False, None),
    ]
    db = MagicMock()
    db.connect.return_value.__enter__ = MagicMock(return_value=conn)
    db.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("data_agent.self_evolution.get_engine", return_value=db):
        failures = SelfEvolutionEngine(evolution_engine=FakeEvolutionEngine()).collect_tool_failures()

    assert failures == [{
        "id": 1,
        "tool_name": "query_database",
        "error": "relation not found",
        "hint_applied": "list tables",
        "resolved": False,
        "created_at": None,
    }]


def test_ensure_self_evolution_tables_no_db_returns_false():
    with patch("data_agent.self_evolution.get_engine", return_value=None):
        assert ensure_self_evolution_tables() is False


def test_record_cycle_persists_audit_report():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (42,)
    db = MagicMock()
    db.connect.return_value.__enter__ = MagicMock(return_value=conn)
    db.connect.return_value.__exit__ = MagicMock(return_value=False)

    report = {
        "status": "success",
        "mode": "dry_run",
        "summary": {"bad_cases": 2},
        "analysis": {"patterns": []},
        "proposals": {"next_actions": []},
        "safeguards": {"dry_run_default": True},
    }

    with patch("data_agent.self_evolution.get_engine", return_value=db), \
            patch("data_agent.self_evolution.ensure_self_evolution_tables", return_value=True):
        cycle_id = record_cycle(
            report,
            triggered_by="planner",
            trigger_source="tool",
            apply_requested=False,
        )

    assert cycle_id == 42
    _, params = conn.execute.call_args.args
    assert params["triggered_by"] == "planner"
    assert params["trigger_source"] == "tool"
    assert params["mode"] == "dry_run"
    assert params["status"] == "proposed"
    assert json.loads(params["summary"]) == {"bad_cases": 2}


def test_record_cycle_marks_applied_only_when_prompt_change_was_applied():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (43,)
    db = MagicMock()
    db.connect.return_value.__enter__ = MagicMock(return_value=conn)
    db.connect.return_value.__exit__ = MagicMock(return_value=False)

    report = {
        "status": "success",
        "mode": "apply",
        "summary": {},
        "analysis": {},
        "proposals": {"prompt_suggestions": [{"applied": True}]},
        "safeguards": {},
    }

    with patch("data_agent.self_evolution.get_engine", return_value=db), \
            patch("data_agent.self_evolution.ensure_self_evolution_tables", return_value=True):
        assert record_cycle(report, apply_requested=True) == 43

    _, params = conn.execute.call_args.args
    assert params["status"] == "applied"


@pytest.mark.asyncio
async def test_self_evolution_cycle_records_cycle_id_when_persisted():
    engine = SelfEvolutionEngine(
        collector=FakeCollector(),
        analyzer=FakeAnalyzer(),
        prompt_optimizer=FakePromptOptimizer(),
        evolution_engine=FakeEvolutionEngine(),
        feedback_store=FakeFeedbackStore(),
    )
    with patch.object(engine, "collect_tool_failures", return_value=[]), \
            patch("data_agent.self_evolution.record_cycle", return_value=99):
        result = await engine.run_cycle(
            persist=True,
            triggered_by="alice",
            trigger_source="api",
        )

    assert result["cycle_id"] == 99
    assert result["persistence"] == {"status": "recorded", "cycle_id": 99}


@pytest.mark.asyncio
async def test_self_evolution_cycle_can_disable_persistence():
    engine = SelfEvolutionEngine(
        collector=FakeCollector(),
        analyzer=FakeAnalyzer(),
        prompt_optimizer=FakePromptOptimizer(),
        evolution_engine=FakeEvolutionEngine(),
        feedback_store=FakeFeedbackStore(),
    )
    with patch.object(engine, "collect_tool_failures", return_value=[]), \
            patch("data_agent.self_evolution.record_cycle") as mock_record:
        result = await engine.run_cycle(persist=False)

    mock_record.assert_not_called()
    assert result["persistence"] == {"status": "disabled"}


def test_list_and_get_cycles_decode_json_fields():
    from datetime import datetime

    list_conn = MagicMock()
    list_conn.execute.return_value.fetchall.return_value = [
        (
            1,
            "scheduler",
            "cron",
            "dry_run",
            "proposed",
            '{"bad_cases": 1}',
            '{"next_actions": []}',
            '{"dry_run_default": true}',
            datetime(2026, 6, 18, 12, 0, 0),
        )
    ]
    get_conn = MagicMock()
    get_conn.execute.return_value.fetchone.return_value = (
        1,
        "scheduler",
        "cron",
        "dry_run",
        "proposed",
        {"bad_cases": 1},
        {"patterns": []},
        {"next_actions": []},
        {"dry_run_default": True},
        {"status": "success"},
        datetime(2026, 6, 18, 12, 0, 0),
    )
    db = MagicMock()
    db.connect.return_value.__enter__.side_effect = [list_conn, get_conn]
    db.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("data_agent.self_evolution.get_engine", return_value=db):
        cycles = list_cycles(limit=10, status="proposed")
        cycle = get_cycle(1)

    assert cycles[0]["summary"] == {"bad_cases": 1}
    assert cycles[0]["created_at"] == "2026-06-18T12:00:00"
    assert cycle["analysis"] == {"patterns": []}
    assert cycle["report"] == {"status": "success"}


def test_get_review_summary_builds_pending_review_reminders():
    from datetime import datetime

    conn = MagicMock()
    conn.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=(
            2,
            datetime(2026, 6, 18, 10, 0, 0),
            datetime(2026, 6, 18, 12, 0, 0),
        ))),
        MagicMock(fetchall=MagicMock(return_value=[
            (
                11,
                "scheduler",
                "scheduler",
                "dry_run",
                "proposed",
                '{"bad_cases": 7, "tool_failures": 1, "unresolved_downvotes": 4, '
                '"tool_suggestions": 1, "eval_candidates": 2}',
                {"prompt_suggestions": [{"suggested_prompt": "better"}]},
                datetime(2026, 6, 18, 12, 0, 0),
            ),
            (
                10,
                "alice",
                "ui",
                "dry_run",
                "proposed",
                {"bad_cases": 1, "tool_failures": 0, "unresolved_downvotes": 0},
                {"tool_suggestions": [], "prompt_suggestions": [], "eval_candidates": []},
                datetime(2026, 6, 18, 10, 0, 0),
            ),
        ])),
    ]
    db = MagicMock()
    db.connect.return_value.__enter__ = MagicMock(return_value=conn)
    db.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("data_agent.self_evolution.get_engine", return_value=db):
        summary = get_review_summary(limit=1)

    assert summary["pending_count"] == 2
    assert summary["pending_eval_candidates"] == 2
    assert summary["pending_prompt_suggestions"] == 1
    assert summary["pending_tool_suggestions"] == 1
    assert summary["high_priority_count"] == 1
    assert summary["latest_created_at"] == "2026-06-18T12:00:00"
    assert summary["oldest_created_at"] == "2026-06-18T10:00:00"
    assert len(summary["reminders"]) == 1
    assert summary["reminders"][0]["id"] == 11
    assert summary["reminders"][0]["priority"] == "high"
    assert "eval_candidates_ready" in summary["reminders"][0]["reasons"]
    assert summary["recommended_actions"] == [
        "review_eval_candidates",
        "review_prompt_dev_versions",
        "review_tool_route_suggestions",
        "dismiss_stale_or_low_value_cycles",
    ]


def test_review_cycle_action_promotes_eval_candidates_and_audits():
    cycle = {
        "id": 5,
        "mode": "dry_run",
        "status": "proposed",
        "summary": {"eval_candidates": 1},
        "analysis": {},
        "proposals": {},
        "safeguards": {},
        "report": {
            "status": "success",
            "proposals": {
                "eval_candidates": [{"query": "bad case", "expected_tool_use": []}],
            },
        },
    }

    with patch("data_agent.self_evolution.get_cycle", return_value=cycle), \
            patch("data_agent.eval_scenario.EvalDatasetManager", return_value=FakeEvalDatasetManager()), \
            patch("data_agent.self_evolution._update_cycle_report", return_value=True) as mock_update:
        result = review_cycle_action(
            5,
            action="approve_eval_candidates",
            reviewed_by="admin",
            dataset_name="cycle-review",
            notes="ok",
        )

    assert result["status"] == "success"
    assert result["result"]["dataset_id"] == 456
    args, kwargs = mock_update.call_args
    assert args[0] == 5
    assert kwargs["status"] == "applied"
    assert kwargs["report"]["approvals"][0]["action"] == "approve_eval_candidates"
    assert kwargs["report"]["approvals"][0]["notes"] == "ok"


def test_review_cycle_action_creates_dev_prompt_versions_and_audits():
    cycle = {
        "id": 6,
        "mode": "dry_run",
        "status": "proposed",
        "summary": {"prompt_targets": 1},
        "analysis": {},
        "proposals": {},
        "safeguards": {},
        "report": {
            "status": "success",
            "proposals": {
                "prompt_suggestions": [{
                    "domain": "planner",
                    "prompt_key": "planner_instruction",
                    "suggested_prompt": "improved prompt",
                }],
            },
        },
    }

    with patch("data_agent.self_evolution.get_cycle", return_value=cycle), \
            patch("data_agent.prompt_registry.PromptRegistry", return_value=FakePromptRegistry()), \
            patch("data_agent.self_evolution._update_cycle_report", return_value=True) as mock_update:
        result = review_cycle_action(
            6,
            action="approve_prompt_suggestions",
            reviewed_by="admin",
            environment="dev",
        )

    assert result["status"] == "success"
    assert result["result"]["created_versions"][0]["version_id"] == 123
    assert mock_update.call_args.kwargs["status"] == "applied"


def test_review_cycle_action_blocks_prompt_creation_directly_to_prod():
    cycle = {
        "id": 61,
        "mode": "dry_run",
        "status": "proposed",
        "summary": {"prompt_targets": 1},
        "analysis": {},
        "proposals": {},
        "safeguards": {},
        "report": {
            "status": "success",
            "proposals": {
                "prompt_suggestions": [{
                    "domain": "planner",
                    "prompt_key": "planner_instruction",
                    "suggested_prompt": "improved prompt",
                }],
            },
        },
    }

    with patch("data_agent.self_evolution.get_cycle", return_value=cycle), \
            patch("data_agent.prompt_registry.PromptRegistry") as mock_registry, \
            patch("data_agent.self_evolution._update_cycle_report", return_value=True) as mock_update:
        result = review_cycle_action(
            61,
            action="approve_prompt_suggestions",
            reviewed_by="admin",
            environment="prod",
        )

    assert result["status"] == "error"
    assert "Prod prompt deployment requires" in result["result"]["message"]
    assert result["cycle_status"] == "proposed"
    mock_registry.assert_not_called()
    assert mock_update.call_args.kwargs["status"] == "proposed"


def test_review_cycle_action_deploys_approved_dev_prompt_versions_to_prod():
    cycle = {
        "id": 62,
        "mode": "dry_run",
        "status": "applied",
        "summary": {"prompt_targets": 1},
        "analysis": {},
        "proposals": {},
        "safeguards": {},
        "report": {
            "status": "success",
            "proposals": {
                "prompt_suggestions": [{
                    "domain": "planner",
                    "prompt_key": "planner_instruction",
                    "suggested_prompt": "improved prompt",
                }],
            },
            "approvals": [{
                "action": "approve_prompt_suggestions",
                "status": "success",
                "result": {
                    "created_versions": [{
                        "domain": "planner",
                        "prompt_key": "planner_instruction",
                        "version_id": 123,
                        "environment": "dev",
                    }],
                },
            }],
        },
    }
    fake_registry = FakeDeployPromptRegistry()

    with patch("data_agent.self_evolution.get_cycle", return_value=cycle), \
            patch("data_agent.prompt_registry.PromptRegistry", return_value=fake_registry), \
            patch("data_agent.self_evolution._update_cycle_report", return_value=True) as mock_update:
        result = review_cycle_action(
            62,
            action="deploy_prompt_versions_to_prod",
            reviewed_by="admin",
            target_environment="prod",
            notes="prod gate approved",
        )

    assert result["status"] == "success"
    assert fake_registry.deployed == [(123, "prod")]
    deployed = result["result"]["deployed_versions"][0]
    assert deployed["source_version_id"] == 123
    assert deployed["deployed_version_id"] == 1023
    assert deployed["target_environment"] == "prod"
    assert mock_update.call_args.kwargs["status"] == "applied"
    last_approval = mock_update.call_args.kwargs["report"]["last_approval"]
    assert last_approval["action"] == "deploy_prompt_versions_to_prod"
    assert last_approval["notes"] == "prod gate approved"


def test_review_cycle_action_does_not_redeploy_prompt_versions_already_deployed():
    cycle = {
        "id": 63,
        "mode": "dry_run",
        "status": "applied",
        "summary": {"prompt_targets": 1},
        "analysis": {},
        "proposals": {},
        "safeguards": {},
        "report": {
            "status": "success",
            "proposals": {},
            "approvals": [
                {
                    "action": "approve_prompt_suggestions",
                    "status": "success",
                    "result": {
                        "created_versions": [{
                            "domain": "planner",
                            "prompt_key": "planner_instruction",
                            "version_id": 123,
                            "environment": "dev",
                        }],
                    },
                },
                {
                    "action": "deploy_prompt_versions_to_prod",
                    "status": "success",
                    "result": {
                        "deployed_versions": [{
                            "source_version_id": 123,
                            "deployed_version_id": 1023,
                            "target_environment": "prod",
                        }],
                    },
                },
            ],
        },
    }

    with patch("data_agent.self_evolution.get_cycle", return_value=cycle), \
            patch("data_agent.prompt_registry.PromptRegistry") as mock_registry, \
            patch("data_agent.self_evolution._update_cycle_report", return_value=True) as mock_update:
        result = review_cycle_action(
            63,
            action="deploy_prompt_versions_to_prod",
            reviewed_by="admin",
        )

    assert result["status"] == "error"
    assert "No approved dev prompt versions" in result["result"]["message"]
    mock_registry.assert_not_called()
    assert mock_update.call_args.kwargs["status"] == "applied"


def test_review_cycle_action_dismisses_cycle():
    cycle = {
        "id": 7,
        "mode": "dry_run",
        "status": "proposed",
        "summary": {},
        "analysis": {},
        "proposals": {},
        "safeguards": {},
        "report": {"status": "success", "proposals": {}},
    }

    with patch("data_agent.self_evolution.get_cycle", return_value=cycle), \
            patch("data_agent.self_evolution._update_cycle_report", return_value=True) as mock_update:
        result = review_cycle_action(7, action="dismiss", reviewed_by="admin")

    assert result["status"] == "success"
    assert result["cycle_status"] == "dismissed"
    assert mock_update.call_args.kwargs["status"] == "dismissed"


def test_run_self_evolution_cycle_tool_passes_persistence_options():
    from data_agent.toolsets.evolution_tools import run_self_evolution_cycle

    captured = {}

    class FakeEngine:
        async def run_cycle(self, **kwargs):
            captured.update(kwargs)
            return {"status": "success", "persistence": {"status": "recorded", "cycle_id": 7}}

    with patch("data_agent.self_evolution.SelfEvolutionEngine", return_value=FakeEngine()):
        payload = json.loads(run_self_evolution_cycle(
            limit=5,
            days=3,
            min_score=0.4,
            include_prompt_suggestions="true",
            apply="false",
            environment="dev",
            persist="true",
            triggered_by="planner",
            trigger_source="tool",
        ))

    assert payload["persistence"]["cycle_id"] == 7
    assert captured["limit"] == 5
    assert captured["days"] == 3
    assert captured["min_score"] == 0.4
    assert captured["persist"] == "true"
    assert captured["triggered_by"] == "planner"
    assert captured["trigger_source"] == "tool"


def test_self_evolution_routes_registered_in_frontend_api():
    from data_agent.frontend_api import get_frontend_api_routes

    paths = {route.path for route in get_frontend_api_routes()}
    assert "/api/self-evolution/cycles" in paths
    assert "/api/self-evolution/review-summary" in paths
    assert "/api/self-evolution/cycles/{id:int}" in paths
    assert "/api/self-evolution/cycles/{id:int}/review" in paths
    assert "/api/self-evolution/run" in paths
    assert "/api/self-evolution/scheduler" in paths


def test_self_evolution_admin_api_lists_cycles():
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from data_agent.api.self_evolution_routes import get_self_evolution_routes

    app = Starlette(routes=get_self_evolution_routes())
    client = TestClient(app)

    with patch(
        "data_agent.api.self_evolution_routes._require_admin",
        return_value=(object(), "admin", "admin", None),
    ), patch(
        "data_agent.self_evolution.list_cycles",
        return_value=[{"id": 1, "status": "proposed", "summary": {"bad_cases": 1}}],
    ) as mock_list:
        resp = client.get("/api/self-evolution/cycles?limit=5&status=proposed")

    assert resp.status_code == 200
    assert resp.json()["cycles"][0]["id"] == 1
    mock_list.assert_called_once_with(limit=5, status="proposed")


def test_self_evolution_admin_api_gets_cycle_detail():
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from data_agent.api.self_evolution_routes import get_self_evolution_routes

    app = Starlette(routes=get_self_evolution_routes())
    client = TestClient(app)

    with patch(
        "data_agent.api.self_evolution_routes._require_admin",
        return_value=(object(), "admin", "admin", None),
    ), patch(
        "data_agent.self_evolution.get_cycle",
        return_value={"id": 7, "report": {"status": "success"}},
    ) as mock_get:
        resp = client.get("/api/self-evolution/cycles/7")

    assert resp.status_code == 200
    assert resp.json()["id"] == 7
    mock_get.assert_called_once_with(7)


def test_self_evolution_admin_api_gets_review_summary():
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from data_agent.api.self_evolution_routes import get_self_evolution_routes

    app = Starlette(routes=get_self_evolution_routes())
    client = TestClient(app)

    with patch(
        "data_agent.api.self_evolution_routes._require_admin",
        return_value=(object(), "admin", "admin", None),
    ), patch(
        "data_agent.self_evolution.get_review_summary",
        return_value={"pending_count": 2, "reminders": []},
    ) as mock_summary:
        resp = client.get("/api/self-evolution/review-summary?limit=3")

    assert resp.status_code == 200
    assert resp.json()["pending_count"] == 2
    mock_summary.assert_called_once_with(limit=3)


def test_self_evolution_admin_api_runs_cycle():
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from data_agent.api.self_evolution_routes import get_self_evolution_routes

    captured = {}

    class FakeEngine:
        async def run_cycle(self, **kwargs):
            captured.update(kwargs)
            return {"status": "success", "cycle_id": 11}

    app = Starlette(routes=get_self_evolution_routes())
    client = TestClient(app)

    with patch(
        "data_agent.api.self_evolution_routes._require_admin",
        return_value=(object(), "alice", "admin", None),
    ), patch("data_agent.self_evolution.SelfEvolutionEngine", return_value=FakeEngine()):
        resp = client.post("/api/self-evolution/run", json={
            "limit": 3,
            "days": 2,
            "min_score": "0.25",
            "include_prompt_suggestions": True,
            "apply": False,
            "persist": True,
        })

    assert resp.status_code == 200
    assert resp.json()["cycle_id"] == 11
    assert captured["limit"] == 3
    assert captured["days"] == 2
    assert captured["min_score"] == 0.25
    assert captured["triggered_by"] == "alice"
    assert captured["trigger_source"] == "api"


def test_self_evolution_admin_api_reviews_cycle():
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from data_agent.api.self_evolution_routes import get_self_evolution_routes

    app = Starlette(routes=get_self_evolution_routes())
    client = TestClient(app)

    with patch(
        "data_agent.api.self_evolution_routes._require_admin",
        return_value=(object(), "alice", "admin", None),
    ), patch(
        "data_agent.self_evolution.review_cycle_action",
        return_value={"status": "success", "cycle_id": 7, "cycle_status": "applied"},
    ) as mock_review:
        resp = client.post("/api/self-evolution/cycles/7/review", json={
            "action": "approve_eval_candidates",
            "dataset_name": "cycle-review",
            "notes": "ship",
        })

    assert resp.status_code == 200
    assert resp.json()["cycle_status"] == "applied"
    mock_review.assert_called_once_with(
        7,
        action="approve_eval_candidates",
        reviewed_by="alice",
        environment="dev",
        target_environment="prod",
        dataset_name="cycle-review",
        notes="ship",
    )


@pytest.mark.asyncio
async def test_self_evolution_scheduler_run_once_persists_dry_run_cycle():
    from data_agent.self_evolution_scheduler import SelfEvolutionScheduler

    captured = {}

    class FakeEngine:
        async def run_cycle(self, **kwargs):
            captured.update(kwargs)
            return {"status": "success", "cycle_id": 55}

    scheduler = SelfEvolutionScheduler(
        enabled=True,
        interval_seconds=300,
        days=3,
        limit=9,
        min_score=0.4,
        include_prompt_suggestions=True,
        engine_factory=FakeEngine,
    )
    result = await scheduler.run_once()

    assert result["cycle_id"] == 55
    assert captured["apply"] is False
    assert captured["persist"] is True
    assert captured["trigger_source"] == "scheduler"
    assert captured["triggered_by"] == "self_evolution_scheduler"
    status = scheduler.status()
    assert status["last_cycle_id"] == 55
    assert status["run_count"] == 1


def test_self_evolution_scheduler_default_disabled():
    from data_agent.self_evolution_scheduler import SelfEvolutionScheduler

    scheduler = SelfEvolutionScheduler(enabled=False)
    assert scheduler.start() is False
    assert scheduler.status()["enabled"] is False
    assert scheduler.status()["active"] is False


def test_self_evolution_admin_api_scheduler_status():
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from data_agent.api.self_evolution_routes import get_self_evolution_routes

    fake_scheduler = MagicMock()
    fake_scheduler.status.return_value = {"enabled": False, "active": False}
    app = Starlette(routes=get_self_evolution_routes())
    client = TestClient(app)

    with patch(
        "data_agent.api.self_evolution_routes._require_admin",
        return_value=(object(), "alice", "admin", None),
    ), patch(
        "data_agent.self_evolution_scheduler.get_self_evolution_scheduler",
        return_value=fake_scheduler,
    ):
        resp = client.get("/api/self-evolution/scheduler")

    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_self_evolution_admin_api_scheduler_run_once():
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from data_agent.api.self_evolution_routes import get_self_evolution_routes

    class FakeScheduler:
        async def run_once(self):
            return {"status": "success", "cycle_id": 77}

        def status(self):
            return {"enabled": True, "active": False, "last_cycle_id": 77}

    app = Starlette(routes=get_self_evolution_routes())
    client = TestClient(app)

    with patch(
        "data_agent.api.self_evolution_routes._require_admin",
        return_value=(object(), "alice", "admin", None),
    ), patch(
        "data_agent.self_evolution_scheduler.get_self_evolution_scheduler",
        return_value=FakeScheduler(),
    ):
        resp = client.post("/api/self-evolution/scheduler", json={"action": "run_once"})

    assert resp.status_code == 200
    assert resp.json()["result"]["cycle_id"] == 77
    assert resp.json()["scheduler"]["last_cycle_id"] == 77
