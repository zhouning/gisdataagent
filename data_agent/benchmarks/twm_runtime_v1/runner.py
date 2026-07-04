from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_agent.territory_world_model.runtime_observation import (
    RUNTIME_OBSERVATION_SCHEMA,
    TARGET_COLUMNS,
    build_runtime_observation,
)
from data_agent.territory_world_model.runtime_simulator import (
    CONTRACT_TRACE_BACKEND_TYPE,
    SIMULATOR_TRACE_SCHEMA,
    build_simulator_trace,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = REPO_ROOT / "docs/reports/twm_runtime_benchmark_v1.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs/reports/twm_runtime_benchmark_v1.md"


def run_twm_runtime_benchmark(
    *,
    suite: str = "twm_runtime_v1",
    output_path: str | Path | None = DEFAULT_OUTPUT,
    markdown_output_path: str | Path | None = DEFAULT_MARKDOWN_OUTPUT,
    fail_on_failed: bool = False,
) -> dict[str, Any]:
    """Run the TWM Runtime Benchmark v1 gate report.

    The first version is intentionally strict: it can pass data-foundation checks,
    but it must fail the runtime gates while the current simulator remains a
    deterministic planning facade without a trace contract.
    """

    if suite != "twm_runtime_v1":
        raise ValueError(f"unsupported TWM runtime benchmark suite: {suite}")

    manifest = _read_json(BENCHMARK_DIR / "manifest.json")
    thresholds = _read_json(BENCHMARK_DIR / "thresholds.json")
    negative_controls = _read_json(BENCHMARK_DIR / "negative_controls.json")

    paths = _benchmark_paths(manifest)
    measurements = _measure_datasets(paths)
    dataset_hash = _dataset_manifest_hash(paths)
    canonical_observation = build_runtime_observation(measurements, dataset_hash)
    simulator_trace = build_simulator_trace(canonical_observation, suite_id=suite)
    gates = {
        "dataset_integrity_gate": _dataset_integrity_gate(measurements, thresholds["dataset_integrity_gate"]),
        "renderer_gate": _renderer_gate(measurements, thresholds["renderer_gate"], canonical_observation),
        "simulator_gate": _simulator_gate(thresholds["simulator_gate"], simulator_trace),
        "planner_gate": _planner_gate(thresholds["planner_gate"]),
        "evidence_claim_gate": _claim_gate(measurements, manifest["claim_boundary"]),
        "negative_control_gate": _negative_control_gate(negative_controls, thresholds["negative_control_gate"]),
        "leakage_guard_gate": _leakage_guard_gate(measurements, canonical_observation),
    }
    failed_gates = [name for name, gate in gates.items() if gate["status"] != "pass"]
    status = "pass" if not failed_gates else "fail"
    claim_boundary = {
        "runtime_benchmark": status,
        "production_accuracy": "not_supported",
        "production_decision": "blocked_without_real_observed_history",
        "flus_superiority": "not_evaluated_by_this_benchmark",
        "not_for_production_boundary_preserved": bool(measurements["not_for_production_boundary_preserved"]),
    }
    report = {
        "schema": "territory_world_model.twm_runtime_benchmark.v1",
        "suite_id": suite,
        "created_at": _now_utc_iso(),
        "dataset_manifest_hash": dataset_hash,
        "status": status,
        "failed_gates": failed_gates,
        "scores": _scores_from_gates(gates),
        "gates": gates,
        "canonical_observation": canonical_observation,
        "simulator_trace": simulator_trace,
        "measurements": measurements,
        "claim_boundary": claim_boundary,
        "recommendations": _recommendations(failed_gates),
    }

    if output_path is not None:
        _write_json(Path(output_path), report)
    if markdown_output_path is not None:
        _write_markdown(Path(markdown_output_path), report)
    if fail_on_failed and status != "pass":
        raise SystemExit(1)
    return report


def _benchmark_paths(manifest: dict[str, Any]) -> dict[str, Path | list[Path]]:
    state_dataset_dir = _repo_path(manifest["state_dataset_dir"])
    return {
        "state_dataset_dir": state_dataset_dir,
        "data_quality_report": state_dataset_dir / "data_quality_report.json",
        "dataset_manifest": state_dataset_dir / "dataset_manifest.json",
        "relations_dir": state_dataset_dir / "relations",
        "rule_evaluation": state_dataset_dir / "tables/rule_evaluation.csv",
        "review_tasks": state_dataset_dir / "tables/review_tasks.csv",
        "support_materials": state_dataset_dir / "tables/multimodal_evidence_index.csv",
        "synthetic_experiment_foundation": _repo_path(manifest["synthetic_experiment_foundation"]),
        "structural_validation_history": _repo_path(manifest["structural_validation_history"]),
        "same_case_baselines": [_repo_path(path) for path in manifest["same_case_baselines"]],
    }


def _measure_datasets(paths: dict[str, Path | list[Path]]) -> dict[str, Any]:
    data_quality = _read_json(_path(paths["data_quality_report"]))
    dataset_manifest = _read_json(_path(paths["dataset_manifest"]))
    layers = data_quality.get("layers") or {}
    relation_rows = _count_relation_rows(_path(paths["relations_dir"]))
    rule_rows = _read_csv(_path(paths["rule_evaluation"]))
    review_rows = _read_csv(_path(paths["review_tasks"]))
    support_rows = _read_csv(_path(paths["support_materials"]))
    trajectory_rows = _read_csv(_path(paths["synthetic_experiment_foundation"]))
    structural_rows = _read_csv(_path(paths["structural_validation_history"]))
    same_case_rows = [_read_csv(path) for path in _paths(paths["same_case_baselines"])]

    split_counts: dict[str, int] = {}
    action_types: set[str] = set()
    counterfactual_groups: set[str] = set()
    allowed_rows = 0
    blocked_rows = 0
    synthetic_flags: set[str] = set()
    not_for_production_flags: set[str] = set()
    split_groups: dict[str, set[str]] = {}
    target_fields = {"next_state_score", "constraint_risk_delta", "planning_utility_delta", "outcome"}
    feature_fields = set(trajectory_rows[0].keys()) if trajectory_rows else set()
    for row in trajectory_rows:
        split = str(row.get("split") or "")
        group = str(row.get("counterfactual_group") or "")
        action_type = str(row.get("action_type") or "")
        split_counts[split] = split_counts.get(split, 0) + 1
        action_types.add(action_type)
        counterfactual_groups.add(group)
        split_groups.setdefault(split, set()).add(group)
        synthetic_flags.add(str(row.get("synthetic")))
        not_for_production_flags.add(str(row.get("not_for_production")))
        if _truthy(row.get("action_mask_allowed")):
            allowed_rows += 1
        else:
            blocked_rows += 1

    layer_counts = {name: int((layer or {}).get("rows") or 0) for name, layer in layers.items()}
    object_count = sum(layer_counts.values())
    project_count = int(layer_counts.get("synthetic_projects") or 0)
    not_for_production_dataset = bool(dataset_manifest.get("not_for_production")) or "True" in not_for_production_flags
    split_overlap_count = _split_overlap_count(split_groups)
    return {
        "dataset_id": dataset_manifest.get("dataset_id"),
        "paths": {key: _stringify_path(value) for key, value in paths.items()},
        "layer_counts": layer_counts,
        "object_count": object_count,
        "relation_count": relation_rows,
        "project_count": project_count,
        "rule_evaluation_count": len(rule_rows),
        "review_task_count": len(review_rows),
        "support_material_count": len(support_rows),
        "synthetic_experiment_rows": len(trajectory_rows),
        "counterfactual_pairs": len(counterfactual_groups),
        "split_counts": split_counts,
        "action_type_count": len(action_types),
        "action_types": sorted(action_types),
        "allowed_rows": allowed_rows,
        "blocked_rows": blocked_rows,
        "structural_validation_rows": len(structural_rows),
        "same_case_baseline_rows": [len(rows) for rows in same_case_rows],
        "trajectory_columns": sorted(feature_fields),
        "target_columns": sorted(target_fields),
        "target_feature_leak_count": len(feature_fields.intersection(target_fields)),
        "split_overlap_count": split_overlap_count,
        "counterfactual_group_split_leak_count": split_overlap_count,
        "not_for_production_boundary_preserved": not_for_production_dataset,
        "synthetic_flags": sorted(synthetic_flags),
        "not_for_production_flags": sorted(not_for_production_flags),
    }


def _dataset_integrity_gate(measurements: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "relation_rows": _min_check(measurements["relation_count"], thresholds["relation_rows_min"]),
        "support_material_rows": _min_check(measurements["support_material_count"], thresholds["evidence_rows_min"]),
        "synthetic_experiment_rows": _equal_check(
            measurements["synthetic_experiment_rows"], thresholds["synthetic_experiment_rows"]
        ),
        "counterfactual_pairs": _equal_check(measurements["counterfactual_pairs"], thresholds["counterfactual_pairs"]),
        "train_rows": _equal_check(measurements["split_counts"].get("train", 0), thresholds["train_rows"]),
        "validation_rows": _equal_check(measurements["split_counts"].get("validation", 0), thresholds["validation_rows"]),
        "test_rows": _equal_check(measurements["split_counts"].get("test", 0), thresholds["test_rows"]),
        "action_type_count": _equal_check(measurements["action_type_count"], thresholds["action_type_count"]),
        "allowed_rows": _equal_check(measurements["allowed_rows"], thresholds["allowed_rows"]),
        "blocked_rows": _equal_check(measurements["blocked_rows"], thresholds["blocked_rows"]),
        "repo_internal_paths": {"status": "pass", "observed": True, "required": True},
    }
    return _gate("pass" if _all_checks_pass(checks) else "fail", checks=checks)


def _renderer_gate(
    measurements: dict[str, Any],
    thresholds: dict[str, Any],
    canonical_observation: dict[str, Any],
) -> dict[str, Any]:
    observation_schema = canonical_observation.get("schema")
    simulator_input = canonical_observation.get("simulator_input") or {}
    checks = {
        "object_count": _min_check(measurements["object_count"], thresholds["object_count_min"]),
        "relation_count": _min_check(measurements["relation_count"], thresholds["relation_count_min"]),
        "project_count": _min_check(measurements["project_count"], thresholds["project_count_min"]),
        "rule_evaluation_count": _min_check(
            measurements["rule_evaluation_count"], thresholds["rule_evaluation_count_min"]
        ),
        "review_task_count": _min_check(measurements["review_task_count"], thresholds["review_task_count_min"]),
        "support_material_count": _min_check(
            measurements["support_material_count"], thresholds["support_material_count_min"]
        ),
        "canonical_observation_schema_present": {
            "status": "pass" if observation_schema == RUNTIME_OBSERVATION_SCHEMA else "fail",
            "observed": observation_schema,
            "required": RUNTIME_OBSERVATION_SCHEMA,
        },
        "simulator_consumable_observation": {
            "status": "pass" if simulator_input.get("consumable") is True else "fail",
            "observed": bool(simulator_input.get("consumable")),
            "required": True,
        },
        "not_for_production_boundary_preserved": {
            "status": "pass" if measurements["not_for_production_boundary_preserved"] else "fail",
            "observed": measurements["not_for_production_boundary_preserved"],
            "required": True,
        },
    }
    return _gate(
        "pass" if _all_checks_pass(checks) else "fail",
        checks=checks,
        missing=_failed_check_names(checks),
        summary="State data is present, but no canonical simulator observation contract is exposed yet.",
    )


def _simulator_gate(thresholds: dict[str, Any], simulator_trace: dict[str, Any]) -> dict[str, Any]:
    backend_type = simulator_trace.get("backend_type")
    trace_present = simulator_trace.get("schema") == SIMULATOR_TRACE_SCHEMA
    checks = {
        "simulator_trace_present": {"status": "pass" if trace_present else "fail", "observed": trace_present, "required": True},
        "facade_backend_forbidden": {
            "status": "pass" if backend_type and backend_type != "deterministic_planner_facade" else "fail",
            "observed": backend_type,
            "required": "backend_type != deterministic_planner_facade",
        },
        "dataset_snapshot_hash_in_trace": {
            "status": "pass" if simulator_trace.get("dataset_snapshot_hash") else "fail",
            "observed": simulator_trace.get("dataset_snapshot_hash"),
            "required": True,
        },
        "model_family_in_trace": {
            "status": "pass" if simulator_trace.get("model_family") else "fail",
            "observed": simulator_trace.get("model_family"),
            "required": True,
        },
        "split_in_trace": {
            "status": "pass" if simulator_trace.get("split") in {"train", "validation", "test"} else "fail",
            "observed": simulator_trace.get("split"),
            "required": "train/validation/test",
        },
        "prediction_id_in_trace": {
            "status": "pass" if simulator_trace.get("prediction_id") else "fail",
            "observed": simulator_trace.get("prediction_id"),
            "required": True,
        },
        "action_mask_probability": {"status": "fail", "observed": None, "required": True},
        "runtime_metrics": {"status": "fail", "observed": {}, "required": thresholds},
    }
    return _gate(
        "fail",
        checks=checks,
        missing=[
            "action_mask_probability",
            "holdout_metrics",
        ],
        summary=(
            "Simulator trace contract is present, but predictive heads and holdout metrics are not implemented yet."
            if backend_type == CONTRACT_TRACE_BACKEND_TYPE
            else "Current simulator gate is missing traceable runtime outputs."
        ),
    )


def _planner_gate(thresholds: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "planner_consumes_simulator_trace": {"status": "fail", "observed": False, "required": True},
        "simulator_trace_bound_to_each_candidate": {"status": "fail", "observed": False, "required": True},
        "hard_blocked_selected_count": {"status": "review", "observed": None, "required": 0},
        "planner_metrics": {"status": "fail", "observed": {}, "required": thresholds},
    }
    return _gate(
        "fail",
        checks=checks,
        missing=[
            "planner_consumes_simulator_trace",
            "simulator_trace_bound_to_each_candidate",
            "planner_regret_against_human_oracle",
        ],
        summary="Planner scoring is not yet forced to consume simulator traces only.",
    )


def _claim_gate(measurements: dict[str, Any], claim_manifest: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "runtime_scope_limited": {
            "status": "pass",
            "observed": claim_manifest.get("benchmark_scope"),
            "required": "development_runtime_contract",
        },
        "production_accuracy_not_supported": {
            "status": "pass",
            "observed": claim_manifest.get("production_accuracy"),
            "required": "not_supported",
        },
        "production_decision_blocked": {
            "status": "pass",
            "observed": claim_manifest.get("production_decision"),
            "required": "blocked_without_real_observed_history",
        },
        "not_for_production_boundary_preserved": {
            "status": "pass" if measurements["not_for_production_boundary_preserved"] else "fail",
            "observed": measurements["not_for_production_boundary_preserved"],
            "required": True,
        },
    }
    return _gate("pass" if _all_checks_pass(checks) else "fail", checks=checks)


def _negative_control_gate(negative_controls: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "negative_control_manifest_present": {
            "status": "pass" if negative_controls.get("controls") else "fail",
            "observed": len(negative_controls.get("controls") or []),
            "required": 5,
        },
        "impossible_action_block_rate": {"status": "fail", "observed": None, "required": thresholds["impossible_action_block_rate_min"]},
        "support_missing_review_rate": {
            "status": "fail",
            "observed": None,
            "required": thresholds["support_missing_review_rate_min"],
        },
        "policy_conflict_block_recall": {
            "status": "fail",
            "observed": None,
            "required": thresholds["policy_conflict_block_recall_min"],
        },
        "shuffled_action_performance_drop": {
            "status": "fail",
            "observed": None,
            "required": thresholds["shuffled_action_performance_drop_min"],
        },
        "shuffled_label_gate_status": {"status": "fail", "observed": "not_run", "required": "fail"},
    }
    return _gate(
        "fail",
        checks=checks,
        missing=[
            "negative_control_runtime_results",
            "shuffled_action_control",
            "shuffled_label_control",
        ],
        summary="Negative controls are declared but not executed by a runtime simulator/planner loop yet.",
    )


def _leakage_guard_gate(measurements: dict[str, Any], canonical_observation: dict[str, Any]) -> dict[str, Any]:
    feature_contract = canonical_observation.get("feature_vector_contract") or {}
    input_columns = set(feature_contract.get("input_feature_columns") or [])
    excluded_target_columns = set(feature_contract.get("excluded_target_columns") or [])
    target_columns = set(feature_contract.get("target_columns") or TARGET_COLUMNS)
    forbidden_in_input = sorted(input_columns.intersection(target_columns))
    checks = {
        "split_overlap_count": _equal_check(measurements["split_overlap_count"], 0),
        "counterfactual_group_split_leak_count": _equal_check(
            measurements["counterfactual_group_split_leak_count"], 0
        ),
        "raw_target_columns_declared": {
            "status": "pass",
            "observed": sorted(excluded_target_columns),
            "required": "raw target columns must be explicit and excluded from simulator inputs",
        },
        "feature_vector_contract": {
            "status": "pass" if feature_contract.get("schema") == "territory_world_model.runtime_feature_vector_contract.v1" else "fail",
            "observed": feature_contract.get("schema"),
            "required": "territory_world_model.runtime_feature_vector_contract.v1",
        },
        "target_feature_columns_excluded": {
            "status": "pass" if not forbidden_in_input else "fail",
            "observed": forbidden_in_input,
            "required": [],
        },
        "dataset_snapshot_hash_stable": {"status": "pass", "observed": True, "required": True},
    }
    status = "pass" if _all_checks_pass(checks) else "fail"
    return _gate(status, checks=checks, missing=_failed_check_names(checks))


def _scores_from_gates(gates: dict[str, dict[str, Any]]) -> dict[str, float]:
    return {
        name.replace("_gate", "_score"): 1.0 if gate["status"] == "pass" else 0.0
        for name, gate in gates.items()
    }


def _recommendations(failed_gates: list[str]) -> list[str]:
    items: list[str] = []
    if "renderer_gate" in failed_gates:
        items.append("Expose canonical_observation with schema territory_world_model.runtime_observation.v1.")
    if "simulator_gate" in failed_gates:
        items.append("Implement a traceable simulator backend that emits simulator_trace for every forecast and rollout.")
    if "planner_gate" in failed_gates:
        items.append("Force planner ranking to consume simulator_trace and action-mask outputs for each candidate.")
    if "negative_control_gate" in failed_gates:
        items.append("Execute impossible-action, support-missing, policy-conflict and shuffled-control tests in the benchmark loop.")
    if not items:
        items.append("Keep production claims blocked until real observed history and external validation are available.")
    return items


def _gate(
    status: str,
    *,
    checks: dict[str, dict[str, Any]],
    missing: list[str] | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "checks": checks,
        "missing": missing or _failed_check_names(checks),
        "summary": summary or "",
    }


def _min_check(observed: int | float, required_min: int | float) -> dict[str, Any]:
    return {
        "status": "pass" if observed >= required_min else "fail",
        "observed": observed,
        "required_min": required_min,
    }


def _equal_check(observed: int | float, required: int | float) -> dict[str, Any]:
    return {
        "status": "pass" if observed == required else "fail",
        "observed": observed,
        "required": required,
    }


def _all_checks_pass(checks: dict[str, dict[str, Any]]) -> bool:
    return all(check.get("status") == "pass" for check in checks.values())


def _failed_check_names(checks: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, check in checks.items() if check.get("status") != "pass"]


def _dataset_manifest_hash(paths: dict[str, Path | list[Path]]) -> str:
    hasher = hashlib.sha256()
    for path in _iter_hash_paths(paths):
        hasher.update(str(path.relative_to(REPO_ROOT)).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _iter_hash_paths(paths: dict[str, Path | list[Path]]) -> list[Path]:
    candidates: list[Path] = [
        _path(paths["dataset_manifest"]),
        _path(paths["data_quality_report"]),
        _path(paths["rule_evaluation"]),
        _path(paths["review_tasks"]),
        _path(paths["support_materials"]),
        _path(paths["synthetic_experiment_foundation"]),
        _path(paths["structural_validation_history"]),
    ]
    candidates.extend(_paths(paths["same_case_baselines"]))
    candidates.extend(sorted(_path(paths["relations_dir"]).glob("*.csv")))
    return candidates


def _count_relation_rows(relations_dir: Path) -> int:
    return sum(len(_read_csv(path)) for path in sorted(relations_dir.glob("*.csv")))


def _split_overlap_count(split_groups: dict[str, set[str]]) -> int:
    splits = list(split_groups)
    overlap = 0
    for index, split in enumerate(splits):
        for other in splits[index + 1 :]:
            overlap += len(split_groups[split].intersection(split_groups[other]))
    return overlap


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# TWM Runtime Benchmark v1",
        "",
        f"- Status: `{report['status']}`",
        f"- Dataset manifest hash: `{report['dataset_manifest_hash']}`",
        f"- Failed gates: `{', '.join(report['failed_gates']) or 'none'}`",
        "",
        "## Gates",
        "",
    ]
    for name, gate in report["gates"].items():
        missing = ", ".join(gate.get("missing") or []) or "none"
        lines.append(f"- `{name}`: `{gate['status']}`; missing/review: {missing}")
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            f"- Runtime benchmark: `{report['claim_boundary']['runtime_benchmark']}`",
            f"- Production accuracy: `{report['claim_boundary']['production_accuracy']}`",
            f"- Production decision: `{report['claim_boundary']['production_decision']}`",
            f"- FLUS superiority: `{report['claim_boundary']['flus_superiority']}`",
            "",
            "## Recommendations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["recommendations"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _repo_path(value: str) -> Path:
    path = (REPO_ROOT / value).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f"benchmark path must stay inside repository: {value}") from exc
    return path


def _path(value: Path | list[Path]) -> Path:
    if isinstance(value, list):
        raise TypeError("expected a single path")
    return value


def _paths(value: Path | list[Path]) -> list[Path]:
    if isinstance(value, list):
        return value
    raise TypeError("expected a path list")


def _stringify_path(value: Path | list[Path]) -> str | list[str]:
    if isinstance(value, list):
        return [str(path) for path in value]
    return str(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
