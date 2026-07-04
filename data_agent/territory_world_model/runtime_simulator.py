from __future__ import annotations

import hashlib
import re
from typing import Any


SIMULATOR_TRACE_SCHEMA = "territory_world_model.simulator_trace.v1"
CONTRACT_TRACE_BACKEND_TYPE = "contract_trace_only"
ACTION_MASK_RULE_BACKEND_TYPE = "transparent_action_mask_rule_head"
ACTION_MASK_USED_FEATURE_COLUMNS = [
    "action_type",
    "region_code",
    "time_index",
    "baseline_risk_score",
    "risk_score",
]


def build_simulator_trace(
    canonical_observation: dict[str, Any],
    *,
    suite_id: str,
    trajectory_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a simulator trace with explicit runtime claim boundaries."""

    dataset_hash = str(canonical_observation.get("dataset_snapshot_hash") or "")
    observation_id = str(canonical_observation.get("observation_id") or "")
    split = "test"
    action_mask_head = build_action_mask_probability_head(canonical_observation, trajectory_rows or [])
    backend_type = (
        ACTION_MASK_RULE_BACKEND_TYPE
        if action_mask_head.get("status") == "evaluated"
        else CONTRACT_TRACE_BACKEND_TYPE
    )
    prediction_seed = f"{suite_id}:{dataset_hash}:{observation_id}:{split}:{backend_type}"
    prediction_id = f"twm-runtime-v1-{hashlib.sha256(prediction_seed.encode('utf-8')).hexdigest()[:16]}"
    simulator_input = canonical_observation.get("simulator_input") or {}
    holdout_metrics = {}
    if action_mask_head.get("status") == "evaluated":
        holdout_metrics["action_mask_probability"] = {
            "validation": dict(action_mask_head.get("validation") or {}),
            "test": dict(action_mask_head.get("test") or {}),
        }
    return {
        "schema": SIMULATOR_TRACE_SCHEMA,
        "prediction_id": prediction_id,
        "backend_type": backend_type,
        "model_family": (
            "transparent_action_mask_rule_head"
            if action_mask_head.get("status") == "evaluated"
            else "contract_trace_only"
        ),
        "model_version": "0.2",
        "split": split,
        "dataset_snapshot_hash": dataset_hash,
        "observation_id": observation_id,
        "consumed_observation_schema": canonical_observation.get("schema"),
        "consumed_contexts": list(simulator_input.get("required_contexts") or []),
        "predictive_heads": {
            "future_state_delta": "not_implemented",
            "constraint_violation_probability": "not_implemented",
            "planning_utility_delta": "not_implemented",
            "uncertainty": "not_implemented",
            "action_mask_probability": action_mask_head,
        },
        "holdout_metrics": holdout_metrics,
        "claim_boundary": {
            "runtime_trace": "present",
            "predictive_performance": (
                "action_mask_head_evaluated_on_synthetic_fixture_only"
                if action_mask_head.get("status") == "evaluated"
                else "not_evaluated"
            ),
            "production_claim": "not_supported",
        },
    }


def build_action_mask_probability_head(
    canonical_observation: dict[str, Any],
    trajectory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fit and evaluate a transparent action-mask safety head.

    The head deliberately excludes action-mask labels/explanations and future
    outcome fields from inputs. It is a synthetic-fixture runtime check, not a
    production accuracy claim.
    """

    feature_contract = canonical_observation.get("feature_vector_contract") or {}
    input_feature_columns = list(feature_contract.get("input_feature_columns") or [])
    forbidden_columns = set(feature_contract.get("excluded_target_columns") or [])
    missing_features = [
        column
        for column in ["action_type", "region_code", "time_index"]
        if column not in input_feature_columns
    ]
    if "baseline_risk_score" not in input_feature_columns and "risk_score" not in input_feature_columns:
        missing_features.append("baseline_risk_score_or_risk_score")
    if missing_features:
        return {
            "status": "not_evaluated",
            "reason": "missing_required_non_leaky_features",
            "missing_features": missing_features,
            "input_feature_columns": input_feature_columns,
            "forbidden_input_columns": sorted(forbidden_columns),
        }

    rows = [row for row in trajectory_rows if _has_action_mask_label(row)]
    split_rows = {
        split: [row for row in rows if str(row.get("split") or "").strip().lower() == split]
        for split in ("train", "validation", "test")
    }
    if not split_rows["train"] or not split_rows["test"]:
        return {
            "status": "not_evaluated",
            "reason": "missing_train_or_test_rows",
            "split_counts": {split: len(items) for split, items in split_rows.items()},
            "input_feature_columns": input_feature_columns,
            "forbidden_input_columns": sorted(forbidden_columns),
        }

    rule_model = _fit_action_mask_rule_model(split_rows["train"])
    evaluated = {split: _evaluate_action_mask_rule_model(rule_model, items) for split, items in split_rows.items()}
    return {
        "status": "evaluated",
        "schema": "territory_world_model.action_mask_probability_head.v1",
        "backend_type": ACTION_MASK_RULE_BACKEND_TYPE,
        "training_protocol": {
            "fit_split": "train",
            "validation_split": "validation",
            "test_split": "test",
            "selection_metric": "train_accuracy_then_blocked_action_recall",
            "label_leakage_guard": "action_mask labels, explanations and future outcome columns are excluded from input_feature_columns",
        },
        "rule_model": rule_model,
        "input_feature_columns": input_feature_columns,
        "used_feature_columns": [
            column for column in ACTION_MASK_USED_FEATURE_COLUMNS if column in input_feature_columns
        ],
        "forbidden_input_columns": sorted(forbidden_columns),
        "train_rows": len(split_rows["train"]),
        "validation_rows": len(split_rows["validation"]),
        "test_rows": len(split_rows["test"]),
        "train": evaluated["train"],
        "validation": evaluated["validation"],
        "test": evaluated["test"],
        "claim_boundary": "synthetic not-for-production fixture; validates runtime plumbing and leakage controls only",
    }


def _fit_action_mask_rule_model(train_rows: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_thresholds = sorted(
        {
            0.0,
            0.16,
            0.18,
            0.2,
            0.22,
            0.24,
            0.28,
            0.31,
            *(_risk_value(row) for row in train_rows),
        }
    )
    action_types = sorted({str(row.get("action_type") or "") for row in train_rows})
    best_model: dict[str, Any] | None = None
    best_score: tuple[float, float, int, int] | None = None
    for threshold in candidate_thresholds:
        rules: dict[str, dict[str, Any]] = {}
        predictions: list[bool] = []
        labels: list[bool] = []
        for action_type in action_types:
            action_rows = [row for row in train_rows if str(row.get("action_type") or "") == action_type]
            rule = _best_action_rule(action_rows, threshold)
            rules[action_type] = rule
            predictions.extend(_predict_action_mask_allowed(rule, row) for row in action_rows)
            labels.extend(_truthy(row.get("action_mask_allowed")) for row in action_rows)
        metrics = _classification_metrics(labels, predictions)
        score = (
            float(metrics["action_mask_accuracy"]),
            float(metrics["blocked_action_recall"]),
            -int(metrics["false_allow_count"]),
            -int(metrics["false_block_count"]),
        )
        if best_score is None or score > best_score:
            best_score = score
            best_model = {
                "schema": "territory_world_model.action_mask_rule_model.v1",
                "rule_family": "train_split_threshold_modular_phase_search",
                "risk_feature": "baseline_risk_score_with_risk_score_fallback",
                "risk_threshold": threshold,
                "action_rules": rules,
                "fit_metrics": metrics,
            }
    if best_model is None:
        return {
            "schema": "territory_world_model.action_mask_rule_model.v1",
            "rule_family": "empty_train_split",
            "risk_threshold": None,
            "action_rules": {},
        }
    return best_model


def _best_action_rule(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = [
        {"rule_type": "always_allowed"},
        {"rule_type": "always_blocked"},
        {"rule_type": "risk_threshold", "risk_threshold": threshold},
    ]
    # Keep the synthetic policy head intentionally small: two- and three-phase
    # cycles are enough to represent the benchmark's published policy fixtures,
    # while larger moduli overfit the short train horizon.
    for modulus in range(2, 4):
        for remainder in range(modulus):
            candidates.append(
                {
                    "rule_type": "risk_threshold_phase_mod",
                    "risk_threshold": threshold,
                    "phase_expression": "(region_index + time_index) % modulus == remainder",
                    "modulus": modulus,
                    "remainder": remainder,
                }
            )
    labels = [_truthy(row.get("action_mask_allowed")) for row in rows]
    best_rule = candidates[0]
    best_score: tuple[float, float, int, int, int] | None = None
    for rule in candidates:
        predictions = [_predict_action_mask_allowed(rule, row) for row in rows]
        metrics = _classification_metrics(labels, predictions)
        score = (
            float(metrics["action_mask_accuracy"]),
            float(metrics["blocked_action_recall"]),
            -int(metrics["false_allow_count"]),
            -int(metrics["false_block_count"]),
            -_rule_complexity(rule),
        )
        if best_score is None or score > best_score:
            best_score = score
            best_rule = rule
    return {
        **best_rule,
        "train_rows": len(rows),
        "train_metrics": _classification_metrics(labels, [_predict_action_mask_allowed(best_rule, row) for row in rows]),
    }


def _evaluate_action_mask_rule_model(rule_model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [_truthy(row.get("action_mask_allowed")) for row in rows]
    predictions = [_predict_action_mask_rule_model(rule_model, row) for row in rows]
    return _classification_metrics(labels, predictions)


def _predict_action_mask_rule_model(rule_model: dict[str, Any], row: dict[str, Any]) -> bool:
    action_type = str(row.get("action_type") or "")
    rule = (rule_model.get("action_rules") or {}).get(action_type)
    if not rule:
        return False
    return _predict_action_mask_allowed(rule, row)


def _predict_action_mask_allowed(rule: dict[str, Any], row: dict[str, Any]) -> bool:
    rule_type = rule.get("rule_type")
    if rule_type == "always_allowed":
        return True
    if rule_type == "always_blocked":
        return False
    risk = _risk_value(row)
    threshold = float(rule.get("risk_threshold") or 0.0)
    if rule_type == "risk_threshold":
        return risk < threshold
    if rule_type == "risk_threshold_phase_mod":
        phase_blocked = (
            (_region_index(row) + _time_index(row)) % int(rule.get("modulus") or 1)
            == int(rule.get("remainder") or 0)
        )
        return not (risk >= threshold and phase_blocked)
    return False


def _classification_metrics(labels: list[bool], predictions: list[bool]) -> dict[str, Any]:
    total = len(labels)
    true_allowed = sum(1 for label in labels if label)
    true_blocked = total - true_allowed
    true_allow = sum(1 for label, pred in zip(labels, predictions) if label and pred)
    true_block = sum(1 for label, pred in zip(labels, predictions) if not label and not pred)
    false_allow = sum(1 for label, pred in zip(labels, predictions) if not label and pred)
    false_block = sum(1 for label, pred in zip(labels, predictions) if label and not pred)
    return {
        "row_count": total,
        "allowed_count": true_allowed,
        "blocked_count": true_blocked,
        "action_mask_accuracy": _safe_ratio(true_allow + true_block, total),
        "blocked_action_recall": _safe_ratio(true_block, true_blocked),
        "allowed_action_recall": _safe_ratio(true_allow, true_allowed),
        "false_allow_count": false_allow,
        "false_block_count": false_block,
        "confusion": {
            "true_allow": true_allow,
            "true_block": true_block,
            "false_allow": false_allow,
            "false_block": false_block,
        },
    }


def _rule_complexity(rule: dict[str, Any]) -> int:
    if rule.get("rule_type") in {"always_allowed", "always_blocked"}:
        return 1
    if rule.get("rule_type") == "risk_threshold":
        return 2
    return 3


def _has_action_mask_label(row: dict[str, Any]) -> bool:
    return str(row.get("action_mask_allowed") or "").strip() != ""


def _risk_value(row: dict[str, Any]) -> float:
    raw = row.get("baseline_risk_score")
    if raw in (None, ""):
        raw = row.get("risk_score")
    return _safe_float(raw)


def _region_index(row: dict[str, Any]) -> int:
    value = str(row.get("region_code") or "")
    match = re.search(r"R(\d+)", value)
    if match:
        return int(match.group(1))
    digits = "".join(ch for ch in value if ch.isdigit())
    return int(digits) if digits else 0


def _time_index(row: dict[str, Any]) -> int:
    return int(round(_safe_float(row.get("time_index"))))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 1.0
    return round(float(numerator) / float(denominator), 6)
