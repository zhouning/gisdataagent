"""Self-evolution orchestration loop for GIS Data Agent.

This module composes existing learning surfaces into one auditable cycle:
observe bad cases, analyze failure patterns, refresh tool reliability, and
produce improvement proposals.  It is conservative by default: dry-run mode
does not mutate prompts, tools, or eval datasets.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text

from .database_tools import T_TOOL_FAILURES
from .db_engine import get_engine
from .failure_to_eval import convert_failure_to_testcase
from .observability import get_logger
from .tool_evolution import get_evolution_engine

logger = get_logger("self_evolution")

T_SELF_EVOLUTION_CYCLES = "agent_self_evolution_cycles"
_CYCLE_STATUSES = {"proposed", "applied", "failed", "dismissed"}
_PROD_ENVIRONMENTS = {"prod", "production"}


def _clamp_int(value: int | str, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def _truthy(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_prod_environment(value: str | None) -> bool:
    return str(value or "").strip().lower() in _PROD_ENVIRONMENTS


def _json_param(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _dt(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def ensure_self_evolution_tables() -> bool:
    """Create self-evolution audit tables. Non-fatal when DB is unavailable."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_SELF_EVOLUTION_CYCLES} (
                    id BIGSERIAL PRIMARY KEY,
                    triggered_by VARCHAR(100) DEFAULT '',
                    trigger_source VARCHAR(50) DEFAULT 'tool',
                    mode VARCHAR(20) NOT NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'proposed',
                    summary JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    analysis JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    proposals JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    safeguards JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    report JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_self_evolution_cycles_created "
                f"ON {T_SELF_EVOLUTION_CYCLES} (created_at DESC)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_self_evolution_cycles_status "
                f"ON {T_SELF_EVOLUTION_CYCLES} (status, created_at DESC)"
            ))
            conn.commit()
        return True
    except Exception as exc:
        logger.warning("Failed to create self-evolution tables: %s", exc)
        return False


def _cycle_status(report: dict[str, Any], apply_requested: bool) -> str:
    if report.get("status") != "success":
        return "failed"
    prompt_suggestions = (
        report.get("proposals", {}).get("prompt_suggestions", [])
        if isinstance(report.get("proposals"), dict)
        else []
    )
    if apply_requested and any(item.get("applied") for item in prompt_suggestions):
        return "applied"
    return "proposed"


def record_cycle(
    report: dict[str, Any],
    *,
    triggered_by: str = "",
    trigger_source: str = "tool",
    apply_requested: bool = False,
) -> int | None:
    """Persist one self-evolution cycle report and return its id."""
    engine = get_engine()
    if not engine:
        return None
    if not ensure_self_evolution_tables():
        return None

    status = _cycle_status(report, apply_requested)
    if status not in _CYCLE_STATUSES:
        status = "failed"
    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                INSERT INTO {T_SELF_EVOLUTION_CYCLES}
                    (triggered_by, trigger_source, mode, status,
                     summary, analysis, proposals, safeguards, report)
                VALUES
                    (:triggered_by, :trigger_source, :mode, :status,
                     CAST(:summary AS JSONB), CAST(:analysis AS JSONB),
                     CAST(:proposals AS JSONB), CAST(:safeguards AS JSONB),
                     CAST(:report AS JSONB))
                RETURNING id
            """), {
                "triggered_by": str(triggered_by or "")[:100],
                "trigger_source": str(trigger_source or "tool")[:50],
                "mode": str(report.get("mode") or "dry_run")[:20],
                "status": status,
                "summary": _json_param(report.get("summary") or {}),
                "analysis": _json_param(report.get("analysis") or {}),
                "proposals": _json_param(report.get("proposals") or {}),
                "safeguards": _json_param(report.get("safeguards") or {}),
                "report": _json_param(report),
            }).fetchone()
            conn.commit()
        return int(row[0]) if row else None
    except Exception as exc:
        logger.warning("Failed to record self-evolution cycle: %s", exc)
        return None


def list_cycles(limit: int | str = 50, status: str | None = None) -> list[dict[str, Any]]:
    """List recent self-evolution cycle audit records."""
    engine = get_engine()
    if not engine:
        return []
    limit_n = _clamp_int(limit, default=50, min_value=1, max_value=200)
    clauses: list[str] = []
    params: dict[str, Any] = {"lim": limit_n}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, triggered_by, trigger_source, mode, status,
                       summary, proposals, safeguards, created_at
                  FROM {T_SELF_EVOLUTION_CYCLES}
                  {where}
                 ORDER BY created_at DESC
                 LIMIT :lim
            """), params).fetchall()
        return [
            {
                "id": row[0],
                "triggered_by": row[1] or "",
                "trigger_source": row[2] or "",
                "mode": row[3],
                "status": row[4],
                "summary": _json_value(row[5], {}),
                "proposals": _json_value(row[6], {}),
                "safeguards": _json_value(row[7], {}),
                "created_at": _dt(row[8]),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("Failed to list self-evolution cycles: %s", exc)
        return []


def get_cycle(cycle_id: int | str) -> dict[str, Any] | None:
    """Return one self-evolution audit record by id."""
    engine = get_engine()
    if not engine:
        return None
    try:
        cycle_id_n = int(cycle_id)
    except (TypeError, ValueError):
        return None

    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT id, triggered_by, trigger_source, mode, status,
                       summary, analysis, proposals, safeguards, report, created_at
                  FROM {T_SELF_EVOLUTION_CYCLES}
                 WHERE id = :id
            """), {"id": cycle_id_n}).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "triggered_by": row[1] or "",
            "trigger_source": row[2] or "",
            "mode": row[3],
            "status": row[4],
            "summary": _json_value(row[5], {}),
            "analysis": _json_value(row[6], {}),
            "proposals": _json_value(row[7], {}),
            "safeguards": _json_value(row[8], {}),
            "report": _json_value(row[9], {}),
            "created_at": _dt(row[10]),
        }
    except Exception as exc:
        logger.warning("Failed to get self-evolution cycle %s: %s", cycle_id, exc)
        return None


def _proposal_count(summary: dict[str, Any], proposals: dict[str, Any], key: str) -> int:
    value = summary.get(key)
    if isinstance(value, int):
        return max(0, value)
    items = proposals.get(key)
    return len(items) if isinstance(items, list) else 0


def _review_reasons(counts: dict[str, int]) -> list[str]:
    reasons: list[str] = []
    if counts["eval_candidates"] > 0:
        reasons.append("eval_candidates_ready")
    if counts["prompt_suggestions"] > 0:
        reasons.append("prompt_suggestions_ready")
    if counts["tool_suggestions"] > 0:
        reasons.append("tool_route_suggestions_ready")
    if counts["bad_cases"] >= 5 or counts["unresolved_downvotes"] >= 3:
        reasons.append("feedback_signal_concentrated")
    if counts["tool_failures"] >= 3:
        reasons.append("tool_failure_signal_concentrated")
    return reasons or ["review_required"]


def _review_priority(counts: dict[str, int]) -> str:
    if (
        counts["eval_candidates"] > 0
        and (counts["prompt_suggestions"] > 0 or counts["tool_suggestions"] > 0)
    ):
        return "high"
    if counts["bad_cases"] >= 10 or counts["unresolved_downvotes"] >= 5 or counts["tool_failures"] >= 5:
        return "high"
    if counts["eval_candidates"] > 0 or counts["prompt_suggestions"] > 0 or counts["tool_suggestions"] > 0:
        return "medium"
    return "low"


def get_review_summary(limit: int | str = 5) -> dict[str, Any]:
    """Summarize proposed self-evolution cycles that need human review."""
    empty = {
        "pending_count": 0,
        "pending_eval_candidates": 0,
        "pending_prompt_suggestions": 0,
        "pending_tool_suggestions": 0,
        "latest_created_at": None,
        "oldest_created_at": None,
        "high_priority_count": 0,
        "reminders": [],
        "recommended_actions": [],
    }
    engine = get_engine()
    if not engine:
        return empty
    limit_n = _clamp_int(limit, default=5, min_value=1, max_value=50)
    try:
        with engine.connect() as conn:
            counts_row = conn.execute(text(f"""
                SELECT COUNT(*), MIN(created_at), MAX(created_at)
                  FROM {T_SELF_EVOLUTION_CYCLES}
                 WHERE status = 'proposed'
            """)).fetchone()
            rows = conn.execute(text(f"""
                SELECT id, triggered_by, trigger_source, mode, status,
                       summary, proposals, created_at
                  FROM {T_SELF_EVOLUTION_CYCLES}
                 WHERE status = 'proposed'
                 ORDER BY created_at DESC
            """)).fetchall()
    except Exception as exc:
        logger.warning("Failed to summarize self-evolution review reminders: %s", exc)
        return empty

    reminders: list[dict[str, Any]] = []
    totals = {
        "pending_eval_candidates": 0,
        "pending_prompt_suggestions": 0,
        "pending_tool_suggestions": 0,
    }
    high_priority_count = 0

    for row in rows:
        summary = _json_value(row[5], {})
        proposals = _json_value(row[6], {})
        if not isinstance(summary, dict):
            summary = {}
        if not isinstance(proposals, dict):
            proposals = {}
        counts = {
            "bad_cases": _proposal_count(summary, proposals, "bad_cases"),
            "tool_failures": _proposal_count(summary, proposals, "tool_failures"),
            "unresolved_downvotes": _proposal_count(summary, proposals, "unresolved_downvotes"),
            "tool_suggestions": _proposal_count(summary, proposals, "tool_suggestions"),
            "prompt_suggestions": _proposal_count(summary, proposals, "prompt_suggestions"),
            "eval_candidates": _proposal_count(summary, proposals, "eval_candidates"),
        }
        priority = _review_priority(counts)
        if priority == "high":
            high_priority_count += 1
        totals["pending_eval_candidates"] += counts["eval_candidates"]
        totals["pending_prompt_suggestions"] += counts["prompt_suggestions"]
        totals["pending_tool_suggestions"] += counts["tool_suggestions"]
        if len(reminders) < limit_n:
            reminders.append({
                "id": row[0],
                "created_at": _dt(row[7]),
                "triggered_by": row[1] or "",
                "trigger_source": row[2] or "",
                "mode": row[3],
                "status": row[4],
                "priority": priority,
                "reasons": _review_reasons(counts),
                "counts": counts,
            })

    recommended_actions: list[str] = []
    if totals["pending_eval_candidates"] > 0:
        recommended_actions.append("review_eval_candidates")
    if totals["pending_prompt_suggestions"] > 0:
        recommended_actions.append("review_prompt_dev_versions")
    if totals["pending_tool_suggestions"] > 0:
        recommended_actions.append("review_tool_route_suggestions")
    if reminders:
        recommended_actions.append("dismiss_stale_or_low_value_cycles")

    pending_count = int(counts_row[0] or 0) if counts_row else 0
    return {
        "pending_count": pending_count,
        "pending_eval_candidates": totals["pending_eval_candidates"],
        "pending_prompt_suggestions": totals["pending_prompt_suggestions"],
        "pending_tool_suggestions": totals["pending_tool_suggestions"],
        "latest_created_at": _dt(counts_row[2]) if counts_row else None,
        "oldest_created_at": _dt(counts_row[1]) if counts_row else None,
        "high_priority_count": high_priority_count,
        "reminders": reminders,
        "recommended_actions": recommended_actions,
    }


def _update_cycle_report(
    cycle_id: int | str,
    *,
    status: str,
    report: dict[str, Any],
) -> bool:
    engine = get_engine()
    if not engine:
        return False
    if status not in _CYCLE_STATUSES:
        return False
    try:
        cycle_id_n = int(cycle_id)
    except (TypeError, ValueError):
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {T_SELF_EVOLUTION_CYCLES}
                   SET status = :status,
                       report = CAST(:report AS JSONB)
                 WHERE id = :id
            """), {
                "id": cycle_id_n,
                "status": status,
                "report": _json_param(report),
            })
            conn.commit()
        return True
    except Exception as exc:
        logger.warning("Failed to update self-evolution cycle %s: %s", cycle_id, exc)
        return False


def _append_approval(
    report: dict[str, Any],
    *,
    action: str,
    reviewed_by: str,
    status: str,
    result: dict[str, Any],
    notes: str = "",
) -> dict[str, Any]:
    updated = dict(report or {})
    approvals = list(updated.get("approvals") or [])
    approvals.append({
        "action": action,
        "reviewed_by": reviewed_by or "",
        "status": status,
        "result": result,
        "notes": notes or "",
        "reviewed_at": datetime.utcnow().isoformat() + "Z",
    })
    updated["approvals"] = approvals
    updated["last_approval"] = approvals[-1]
    return updated


def _cycle_report_from_record(cycle: dict[str, Any]) -> dict[str, Any]:
    report = cycle.get("report")
    if isinstance(report, dict) and report:
        return report
    return {
        "status": "success",
        "mode": cycle.get("mode", "dry_run"),
        "summary": cycle.get("summary", {}),
        "analysis": cycle.get("analysis", {}),
        "proposals": cycle.get("proposals", {}),
        "safeguards": cycle.get("safeguards", {}),
    }


def _promote_eval_candidates(
    cycle_id: int,
    report: dict[str, Any],
    *,
    reviewed_by: str,
    dataset_name: str = "",
) -> dict[str, Any]:
    candidates = report.get("proposals", {}).get("eval_candidates", [])
    if not candidates:
        return {"status": "error", "message": "No eval candidates in this cycle"}

    from .eval_scenario import EvalDatasetManager

    name = dataset_name or f"self-evolution-cycle-{cycle_id}"
    version = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    dataset_id = EvalDatasetManager().create_dataset(
        scenario="self_evolution",
        name=name,
        version=version,
        description=f"Review dataset promoted from self-evolution cycle #{cycle_id}",
        test_cases=candidates,
        created_by=reviewed_by or "admin",
    )
    return {
        "status": "success",
        "dataset_id": dataset_id,
        "scenario": "self_evolution",
        "name": name,
        "version": version,
        "case_count": len(candidates),
    }


def _create_prompt_versions(
    cycle_id: int,
    report: dict[str, Any],
    *,
    reviewed_by: str,
    environment: str,
) -> dict[str, Any]:
    suggestions = report.get("proposals", {}).get("prompt_suggestions", [])
    with_text = [s for s in suggestions if s.get("suggested_prompt")]
    if not with_text:
        return {
            "status": "error",
            "message": "No prompt suggestions with suggested_prompt; rerun with include_prompt_suggestions=true",
        }

    from .prompt_registry import PromptRegistry

    registry = PromptRegistry()
    created: list[dict[str, Any]] = []
    for item in with_text:
        version_id = registry.create_version(
            domain=item["domain"],
            prompt_key=item["prompt_key"],
            prompt_text=item["suggested_prompt"],
            env=environment or "dev",
            change_reason=f"Self-evolution cycle #{cycle_id} approved by {reviewed_by or 'admin'}",
            created_by=reviewed_by or "admin",
        )
        created.append({
            "domain": item["domain"],
            "prompt_key": item["prompt_key"],
            "version_id": version_id,
            "environment": environment or "dev",
        })
    return {
        "status": "success",
        "created_versions": created,
        "count": len(created),
        "environment": environment or "dev",
    }


def _prompt_dev_versions_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Find dev/staging prompt versions created by this cycle and not yet deployed."""
    versions: list[dict[str, Any]] = []
    seen: set[int] = set()

    def add_version(item: dict[str, Any], *, source: str) -> None:
        try:
            version_id = int(item.get("version_id"))
        except (TypeError, ValueError):
            return
        environment = str(item.get("environment") or item.get("env") or "dev")
        if _is_prod_environment(environment) or version_id in seen:
            return
        seen.add(version_id)
        versions.append({
            "version_id": version_id,
            "domain": item.get("domain") or "",
            "prompt_key": item.get("prompt_key") or "",
            "environment": environment,
            "source": source,
        })

    for item in report.get("proposals", {}).get("prompt_suggestions", []) or []:
        if not isinstance(item, dict):
            continue
        apply_result = item.get("apply_result") or {}
        if isinstance(apply_result, dict):
            add_version({
                "version_id": apply_result.get("version_id"),
                "environment": apply_result.get("environment"),
                "domain": item.get("domain"),
                "prompt_key": item.get("prompt_key"),
            }, source="cycle_apply")

    for approval in report.get("approvals", []) or []:
        if not isinstance(approval, dict):
            continue
        result = approval.get("result") or {}
        if not isinstance(result, dict):
            continue
        for item in result.get("created_versions", []) or []:
            if isinstance(item, dict):
                add_version(item, source=str(approval.get("action") or "approval"))

    deployed_sources: set[int] = set()
    for approval in report.get("approvals", []) or []:
        if not isinstance(approval, dict):
            continue
        result = approval.get("result") or {}
        if not isinstance(result, dict):
            continue
        for item in result.get("deployed_versions", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                deployed_sources.add(int(item.get("source_version_id")))
            except (TypeError, ValueError):
                continue
    return [item for item in versions if item["version_id"] not in deployed_sources]


def _deploy_prompt_versions_to_prod(
    cycle_id: int,
    report: dict[str, Any],
    *,
    reviewed_by: str,
    target_environment: str = "prod",
) -> dict[str, Any]:
    if not _is_prod_environment(target_environment):
        return {
            "status": "error",
            "message": "Self-evolution prompt production gate only deploys to prod",
        }

    candidates = _prompt_dev_versions_from_report(report)
    if not candidates:
        return {
            "status": "error",
            "message": "No approved dev prompt versions available for prod deployment",
        }

    from .prompt_registry import PromptRegistry

    registry = PromptRegistry()
    deployed: list[dict[str, Any]] = []
    for item in candidates:
        result = registry.deploy(item["version_id"], "prod")
        deployed.append({
            "source_version_id": item["version_id"],
            "domain": item.get("domain") or "",
            "prompt_key": item.get("prompt_key") or "",
            "source_environment": item.get("environment") or "dev",
            "target_environment": result.get("environment", "prod"),
            "deployed_version_id": result.get("version_id"),
            "deployed_by": reviewed_by or "admin",
        })

    return {
        "status": "success",
        "deployed_versions": deployed,
        "count": len(deployed),
        "environment": "prod",
        "cycle_id": cycle_id,
    }


def review_cycle_action(
    cycle_id: int | str,
    *,
    action: str,
    reviewed_by: str = "",
    environment: str = "dev",
    target_environment: str = "prod",
    dataset_name: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Apply a human-reviewed self-evolution action and audit the decision."""
    cycle = get_cycle(cycle_id)
    if not cycle:
        return {"status": "error", "message": "cycle not found"}
    try:
        cycle_id_n = int(cycle_id)
    except (TypeError, ValueError):
        return {"status": "error", "message": "invalid cycle id"}

    report = _cycle_report_from_record(cycle)
    action = str(action or "").strip()
    try:
        if action == "dismiss":
            result = {"status": "success", "message": "cycle dismissed"}
            next_status = "dismissed"
        elif action in {"approve_eval_candidates", "promote_eval_candidates"}:
            result = _promote_eval_candidates(
                cycle_id_n,
                report,
                reviewed_by=reviewed_by,
                dataset_name=dataset_name,
            )
            next_status = "applied" if result.get("status") == "success" else cycle.get("status", "proposed")
        elif action in {"approve_prompt_suggestions", "create_prompt_versions"}:
            if _is_prod_environment(environment):
                result = {
                    "status": "error",
                    "message": "Prod prompt deployment requires deploy_prompt_versions_to_prod",
                }
                next_status = cycle.get("status", "proposed")
            else:
                result = _create_prompt_versions(
                    cycle_id_n,
                    report,
                    reviewed_by=reviewed_by,
                    environment=environment or "dev",
                )
                next_status = "applied" if result.get("status") == "success" else cycle.get("status", "proposed")
        elif action in {"deploy_prompt_versions_to_prod", "deploy_prompt_suggestions_to_prod"}:
            result = _deploy_prompt_versions_to_prod(
                cycle_id_n,
                report,
                reviewed_by=reviewed_by,
                target_environment=target_environment or "prod",
            )
            next_status = "applied" if result.get("status") == "success" else cycle.get("status", "proposed")
        else:
            return {"status": "error", "message": f"unsupported action: {action}"}
    except Exception as exc:
        result = {"status": "error", "message": str(exc)}
        next_status = "failed"

    updated_report = _append_approval(
        report,
        action=action,
        reviewed_by=reviewed_by,
        status=result.get("status", "error"),
        result=result,
        notes=notes,
    )
    if not _update_cycle_report(cycle_id_n, status=next_status, report=updated_report):
        return {
            "status": "error",
            "message": "action result produced but failed to update cycle audit record",
            "action_result": result,
        }
    return {
        "status": result.get("status", "error"),
        "cycle_id": cycle_id_n,
        "cycle_status": next_status,
        "action": action,
        "result": result,
    }


class SelfEvolutionEngine:
    """Run one self-evolution cycle over feedback, failures, tools, and prompts."""

    def __init__(
        self,
        *,
        collector: Any | None = None,
        analyzer: Any | None = None,
        prompt_optimizer: Any | None = None,
        evolution_engine: Any | None = None,
        feedback_store: Any | None = None,
    ) -> None:
        self.collector = collector
        self.analyzer = analyzer
        self.prompt_optimizer = prompt_optimizer
        self.evolution_engine = evolution_engine or get_evolution_engine()
        self.feedback_store = feedback_store

    async def run_cycle(
        self,
        *,
        limit: int | str = 50,
        days: int | str = 7,
        min_score: float = 0.5,
        include_prompt_suggestions: bool | str = False,
        apply: bool | str = False,
        environment: str = "dev",
        persist: bool | str = True,
        triggered_by: str = "",
        trigger_source: str = "tool",
    ) -> dict[str, Any]:
        """Run observe -> analyze -> propose, with optional dev prompt writes."""
        limit_n = _clamp_int(limit, default=50, min_value=1, max_value=100)
        days_n = _clamp_int(days, default=7, min_value=1, max_value=90)
        include_prompts = _truthy(include_prompt_suggestions)
        apply_changes = _truthy(apply)
        persist_report = _truthy(persist)
        environment = environment or "dev"

        bad_cases = await self._collect_bad_cases(limit_n, days_n, min_score)
        tool_failures = self.collect_tool_failures(limit_n)
        feedback_stats = self._feedback_stats(days_n)
        unresolved_downvotes = self._unresolved_downvote_count(limit_n)

        analysis = await self._analyze_failures(bad_cases)
        reliability_update = self._refresh_tool_reliability()
        tool_suggestions = self._tool_suggestions(tool_failures)
        prompt_targets = self._prompt_targets(analysis)
        prompt_suggestions = await self._prompt_suggestions(
            prompt_targets,
            analysis,
            include_prompts=include_prompts,
            apply_changes=apply_changes,
            environment=environment,
        )
        eval_candidates = self._eval_candidates(bad_cases, tool_failures)

        proposals = {
            "tool_suggestions": tool_suggestions,
            "prompt_targets": prompt_targets,
            "prompt_suggestions": prompt_suggestions,
            "eval_candidates": eval_candidates,
            "next_actions": self._next_actions(
                analysis=analysis,
                tool_suggestions=tool_suggestions,
                prompt_targets=prompt_targets,
                eval_candidates=eval_candidates,
                include_prompts=include_prompts,
                apply_changes=apply_changes,
            ),
        }

        report = {
            "status": "success",
            "cycle": "observe_analyze_propose",
            "mode": "apply" if apply_changes else "dry_run",
            "summary": {
                "bad_cases": len(bad_cases),
                "tool_failures": len(tool_failures),
                "unresolved_downvotes": unresolved_downvotes,
                "patterns": len(analysis.get("patterns", [])),
                "root_causes": len(analysis.get("root_causes", [])),
                "tool_suggestions": len(tool_suggestions),
                "prompt_targets": len(prompt_targets),
                "eval_candidates": len(eval_candidates),
            },
            "observe": {
                "feedback_stats": feedback_stats,
                "bad_case_sources": self._source_counts(bad_cases),
                "tool_failures": tool_failures,
            },
            "analysis": analysis,
            "tool_reliability": reliability_update,
            "proposals": proposals,
            "safeguards": {
                "dry_run_default": True,
                "applies_only_when_requested": True,
                "prompt_apply_environment": environment,
                "eval_candidates_not_written": True,
            },
        }
        if persist_report:
            cycle_id = record_cycle(
                report,
                triggered_by=triggered_by,
                trigger_source=trigger_source,
                apply_requested=apply_changes,
            )
            if cycle_id:
                report["cycle_id"] = cycle_id
                report["persistence"] = {"status": "recorded", "cycle_id": cycle_id}
            else:
                report["persistence"] = {
                    "status": "skipped",
                    "reason": "database_unavailable_or_write_failed",
                }
        else:
            report["persistence"] = {"status": "disabled"}
        return report

    async def _collect_bad_cases(
        self,
        limit: int,
        days: int,
        min_score: float,
    ) -> list[dict[str, Any]]:
        try:
            collector = self.collector
            if collector is None:
                from .prompt_optimizer import BadCaseCollector
                collector = BadCaseCollector()
            cases = await collector.collect_all(
                min_score=min_score,
                days=days,
                limit=limit,
            )
            return list(cases or [])
        except Exception as exc:
            logger.warning("self-evolution bad case collection failed: %s", exc)
            return []

    async def _analyze_failures(self, bad_cases: list[dict[str, Any]]) -> dict[str, Any]:
        if not bad_cases:
            return {"patterns": [], "root_causes": [], "affected_prompts": []}
        try:
            analyzer = self.analyzer
            if analyzer is None:
                from .prompt_optimizer import FailureAnalyzer
                analyzer = FailureAnalyzer()
            result = await analyzer.analyze(bad_cases)
            return {
                "patterns": list(result.get("patterns", [])),
                "root_causes": list(result.get("root_causes", [])),
                "affected_prompts": list(result.get("affected_prompts", [])),
            }
        except Exception as exc:
            logger.warning("self-evolution failure analysis failed: %s", exc)
            return {
                "patterns": [],
                "root_causes": [f"Failure analysis unavailable: {exc}"],
                "affected_prompts": [],
            }

    def collect_tool_failures(self, limit: int = 50) -> list[dict[str, Any]]:
        """Collect recent unresolved tool failures from the learning table."""
        engine = get_engine()
        if not engine:
            return []
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(f"""
                    SELECT id, tool_name, error_snippet, hint_applied,
                           resolved, created_at
                      FROM {T_TOOL_FAILURES}
                     WHERE resolved = FALSE
                     ORDER BY created_at DESC
                     LIMIT :lim
                """), {"lim": limit}).fetchall()
            return [
                {
                    "id": row[0],
                    "tool_name": row[1],
                    "error": row[2] or "",
                    "hint_applied": row[3] or "",
                    "resolved": bool(row[4]),
                    "created_at": row[5].isoformat() if row[5] else None,
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("self-evolution tool failure collection failed: %s", exc)
            return []

    def _feedback_stats(self, days: int) -> dict[str, Any]:
        try:
            store = self.feedback_store
            if store is None:
                from .feedback import FeedbackStore
                store = FeedbackStore()
            return store.get_stats(days=days)
        except Exception as exc:
            logger.warning("self-evolution feedback stats failed: %s", exc)
            return {
                "total": 0,
                "upvotes": 0,
                "downvotes": 0,
                "satisfaction_rate": 0.0,
                "by_pipeline": {},
                "trend": [],
            }

    def _unresolved_downvote_count(self, limit: int) -> int:
        try:
            store = self.feedback_store
            if store is None:
                from .feedback import FeedbackStore
                store = FeedbackStore()
            return len(store.list_unresolved_downvotes(limit=limit))
        except Exception:
            return 0

    def _refresh_tool_reliability(self) -> dict[str, Any]:
        try:
            raw = self.evolution_engine.update_reliability_from_db()
            return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _tool_suggestions(
        self,
        tool_failures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        suggestions: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for failure in tool_failures:
            tool_name = str(failure.get("tool_name") or "")
            error = str(failure.get("error") or "")
            if not tool_name or not error:
                continue
            try:
                raw = self.evolution_engine.get_failure_driven_suggestions(tool_name, error)
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                continue
            for item in payload.get("suggestions", []):
                key = (
                    str(item.get("tool") or ""),
                    str(item.get("type") or ""),
                    str(item.get("reason") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append({
                    "failed_tool": tool_name,
                    "error_summary": error[:200],
                    "suggested_tool": item.get("tool") or "",
                    "type": item.get("type") or "unknown",
                    "reason": item.get("reason") or "",
                    "description": item.get("description") or "",
                })
        return suggestions[:20]

    def _prompt_targets(self, analysis: dict[str, Any]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for ref in analysis.get("affected_prompts", []) or []:
            value = str(ref or "").strip()
            if "/" not in value:
                continue
            domain, prompt_key = value.split("/", 1)
            domain = domain.strip()
            prompt_key = prompt_key.strip()
            if not domain or not prompt_key:
                continue
            key = (domain, prompt_key)
            if key in seen:
                continue
            seen.add(key)
            targets.append({"domain": domain, "prompt_key": prompt_key})
        return targets[:5]

    async def _prompt_suggestions(
        self,
        targets: list[dict[str, str]],
        analysis: dict[str, Any],
        *,
        include_prompts: bool,
        apply_changes: bool,
        environment: str,
    ) -> list[dict[str, Any]]:
        if not include_prompts or not targets:
            return []
        optimizer = self.prompt_optimizer
        if optimizer is None:
            from .prompt_optimizer import PromptOptimizer
            optimizer = PromptOptimizer()

        suggestions: list[dict[str, Any]] = []
        for target in targets[:3]:
            result = await optimizer.suggest_improvements(
                target["domain"],
                target["prompt_key"],
                analysis,
            )
            item = {
                "domain": target["domain"],
                "prompt_key": target["prompt_key"],
                "original_prompt": result.get("original_prompt", ""),
                "suggested_prompt": result.get("suggested_prompt", ""),
                "changes": result.get("changes", []),
                "expected_improvement": result.get("expected_improvement", ""),
                "has_suggested_prompt": bool(result.get("suggested_prompt")),
                "applied": False,
            }
            if apply_changes and result.get("suggested_prompt"):
                item["apply_result"] = await optimizer.apply_suggestion(
                    target["domain"],
                    target["prompt_key"],
                    result["suggested_prompt"],
                    environment=environment,
                )
                item["applied"] = item["apply_result"].get("status") == "created"
            suggestions.append(item)
        return suggestions

    def _eval_candidates(
        self,
        bad_cases: list[dict[str, Any]],
        tool_failures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for case in bad_cases[:5]:
            details = case.get("details") or {}
            query = str(details.get("query") or details.get("user_query") or "")
            if not query:
                continue
            candidates.append(convert_failure_to_testcase(
                user_query=query,
                expected_tool=str(details.get("expected_tool") or ""),
                failure_description=str(details.get("issue") or case.get("source") or ""),
                pipeline=str(case.get("pipeline") or "general"),
            ))
        for failure in tool_failures[:5]:
            candidates.append(convert_failure_to_testcase(
                user_query=f"Tool failure: {failure.get('tool_name')}",
                expected_tool=str(failure.get("tool_name") or ""),
                failure_description=str(failure.get("error") or ""),
                pipeline="general",
            ))
        return candidates[:10]

    @staticmethod
    def _source_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in cases:
            source = str(case.get("source") or "unknown")
            counts[source] = counts.get(source, 0) + 1
        return counts

    @staticmethod
    def _next_actions(
        *,
        analysis: dict[str, Any],
        tool_suggestions: list[dict[str, Any]],
        prompt_targets: list[dict[str, str]],
        eval_candidates: list[dict[str, Any]],
        include_prompts: bool,
        apply_changes: bool,
    ) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        if tool_suggestions:
            actions.append({
                "action": "review_tool_routes",
                "reason": "Failure-driven tool alternatives or prerequisites were found.",
            })
        if prompt_targets and not include_prompts:
            actions.append({
                "action": "generate_prompt_suggestions",
                "reason": "Affected prompts were identified; rerun with include_prompt_suggestions=true.",
            })
        if prompt_targets and include_prompts and not apply_changes:
            actions.append({
                "action": "human_review_prompt_suggestions",
                "reason": "Prompt suggestions are generated in dry-run mode.",
            })
        if eval_candidates:
            actions.append({
                "action": "promote_eval_candidates",
                "reason": "Bad cases can be converted into regression tests after review.",
            })
        if analysis.get("root_causes"):
            actions.append({
                "action": "triage_root_causes",
                "reason": "FailureAnalyzer produced root causes for engineering review.",
            })
        if not actions:
            actions.append({
                "action": "no_change",
                "reason": "No strong evolution signal found in the current window.",
            })
        return actions
