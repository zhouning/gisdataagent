from __future__ import annotations

import math
import random
from typing import Any

from .utils import safe_float, safe_int


NEURAL_DYNAMICS_SCHEMA = "territory_world_model.neural_multi_head_dynamics_parameters.v1"
HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA = "territory_world_model.hierarchical_graph_dynamics_parameters.v1"
SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA = "territory_world_model.spatiotemporal_transformer_dynamics_parameters.v1"


def train_neural_multi_head_dynamics(
    dataset: dict[str, Any],
    trainer: dict[str, Any],
    objective_report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Train a small action-conditioned multi-head dynamics candidate.

    This is a local trainable candidate, not the final graph/transformer TWM.
    It preserves the same multi-head report contract used by forecast, rollout,
    backend, and objective gates.
    """
    try:
        import torch
        import torch.nn as nn
    except Exception as exc:  # pragma: no cover - depends on runtime package set.
        return {
            "learned_parameters": _blocked_parameters(trainer, objective_report, f"torch unavailable: {exc}"),
            "predictions": {},
            "diagnostics": {"status": "blocked", "reason": "torch_unavailable", "error": str(exc)},
        }

    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    usable = [item for item in examples if not item.get("not_for_training_reasons")]
    train_examples = [item for item in usable if str(item.get("split") or "candidate") != "holdout"] or usable
    if len(train_examples) < 2:
        return {
            "learned_parameters": _blocked_parameters(trainer, objective_report, "at least two usable training examples are required"),
            "predictions": {},
            "diagnostics": {"status": "blocked", "reason": "insufficient_training_examples", "train_sample_count": len(train_examples)},
        }

    cfg = _training_config(payload)
    _seed_everything(cfg["seed"], torch)

    feature_rows = [_feature_row(item) for item in usable]
    feature_names = sorted({key for row in feature_rows for key in row})
    target_rows = [_target_row(item) for item in usable]
    all_x = [_vectorize(_feature_row(item), feature_names) for item in usable]
    train_ids = {str(item.get("id") or "") for item in train_examples}
    train_indices = [idx for idx, item in enumerate(usable) if str(item.get("id") or "") in train_ids]
    if not feature_names:
        feature_names = ["bias"]
        all_x = [[1.0] for _ in usable]

    x_stats = _normalization_stats(all_x)
    y_stats = _target_stats([target_rows[idx] for idx in train_indices])
    x_train = _normalize_matrix([all_x[idx] for idx in train_indices], x_stats)
    y_train = [target_rows[idx] for idx in train_indices]

    x_tensor = torch.tensor(x_train, dtype=torch.float32)
    y_area = torch.tensor([_normalize_value(row["area_total"], y_stats["area_total"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_constraint = torch.tensor([row["constraint_probability"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_utility = torch.tensor([_normalize_value(row["utility_delta"], y_stats["utility_delta"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_confidence = torch.tensor([row["confidence"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_calibration = torch.tensor([_normalize_value(row["calibrated_utility_delta"], y_stats["calibrated_utility_delta"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_allowed = torch.tensor([row["action_allowed"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_ranking = torch.tensor([row["ranking_score"] for row in y_train], dtype=torch.float32)

    model = _MultiHeadDynamicsMLP(input_dim=len(feature_names), hidden_dim=cfg["hidden_dim"], dropout=cfg["dropout"], nn=nn)
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    bce = nn.BCEWithLogitsLoss()
    mse = nn.MSELoss()
    losses: list[dict[str, float]] = []
    for epoch in range(cfg["epochs"]):
        model.train()
        optimizer.zero_grad()
        out = model(x_tensor)
        utility_pred = out[:, 2:3]
        constraint_prob = torch.sigmoid(out[:, 1:2])
        loss = (
            mse(out[:, 0:1], y_area)
            + bce(out[:, 1:2], y_constraint)
            + cfg["constraint_risk_calibration_weight"] * mse(constraint_prob, y_constraint)
            + 1.2 * mse(utility_pred, y_utility)
            + 0.7 * bce(out[:, 3:4], y_confidence)
            + 0.8 * mse(out[:, 4:5], y_calibration)
            + 0.6 * bce(out[:, 5:6], y_allowed)
            + cfg["ranking_weight"] * _pairwise_ranking_loss(utility_pred.squeeze(1), y_ranking, torch)
        )
        loss.backward()
        optimizer.step()
        if epoch == 0 or epoch == cfg["epochs"] - 1:
            losses.append({"epoch": float(epoch + 1), "loss": round(float(loss.detach().cpu().item()), 6)})

    all_x_norm = _normalize_matrix(all_x, x_stats)
    with torch.no_grad():
        model.eval()
        raw = model(torch.tensor(all_x_norm, dtype=torch.float32)).detach().cpu()

    predictions: dict[str, dict[str, Any]] = {}
    for idx, example in enumerate(usable):
        example_id = str(example.get("id") or f"example:{idx}")
        row = raw[idx].tolist()
        area = _denormalize_value(row[0], y_stats["area_total"])
        constraint = _sigmoid(row[1])
        utility = _denormalize_value(row[2], y_stats["utility_delta"])
        confidence = _sigmoid(row[3])
        calibration = _denormalize_value(row[4], y_stats["calibrated_utility_delta"])
        allowed_probability = _sigmoid(row[5])
        predictions[example_id] = _prediction_from_outputs(
            example=example,
            area_total=area,
            constraint_probability=constraint,
            utility_delta=utility,
            confidence=confidence,
            calibrated_utility=calibration,
            action_allowed_probability=allowed_probability,
            source="torch_multi_head_mlp",
        )

    learned_parameters = {
        "schema": NEURAL_DYNAMICS_SCHEMA,
        "training_status": "pass",
        "trainer": dict(trainer),
        "architecture": {
            "model_type": "torch_multi_head_mlp",
            "input_feature_groups": ["hierarchy_summary", "explicit_gis_state", "action", "scenario", "constraint_context", "action_mask_context"],
            "heads": [
                "future_latent_state.area_total",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty.confidence",
                "calibration.calibrated_utility_delta",
                "action_mask.allowed",
            ],
            "hidden_dim": cfg["hidden_dim"],
            "dropout": cfg["dropout"],
        },
        "feature_contract": {
            "flat_vector_allowed": False,
            "vectorization_note": "The PyTorch MLP consumes grouped hierarchical GIS features after explicit contract vectorization; this is a trainable candidate, not the final graph/transformer TWM.",
            "feature_names": feature_names,
            "feature_count": len(feature_names),
            "action_mask_context_feature_names": _action_mask_context_feature_names(feature_names),
            "normalization": x_stats,
        },
        "target_normalization": y_stats,
        "objective_contract": dict(objective_report.get("objective_contract") or {}),
        "loss_components": dict(objective_report.get("loss_components") or {}),
        "training_config": cfg,
        "training_diagnostics": {
            "status": "pass",
            "train_sample_count": len(train_examples),
            "usable_sample_count": len(usable),
            "prediction_count": len(predictions),
            "final_loss": losses[-1]["loss"] if losses else None,
            "loss_trace": losses,
            "constraint_risk_calibration_weight": cfg["constraint_risk_calibration_weight"],
        },
        "model_state_dict": _serializable_state_dict(model),
        "limitations": [
            "local trainable MLP candidate; not yet the final graph/transformer hierarchical TWM",
            "future_latent_state currently predicts compact area-level latent outputs rather than full parcel geometry",
            "claim upgrade still depends on readiness, backend, objective, causal, GeoFM and validation gates",
        ],
    }
    return {
        "learned_parameters": learned_parameters,
        "predictions": predictions,
        "diagnostics": dict(learned_parameters["training_diagnostics"]),
    }


def train_hierarchical_graph_dynamics(
    dataset: dict[str, Any],
    trainer: dict[str, Any],
    objective_report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Train a hierarchy-aware candidate with token-group encoders and relation mixing.

    This is still a candidate backend, but it is closer to TWM's intended
    parcel/block/township/county token contract than a flat MLP.
    """
    try:
        import torch
        import torch.nn as nn
    except Exception as exc:  # pragma: no cover - depends on runtime package set.
        return {
            "learned_parameters": _blocked_parameters(trainer, objective_report, f"torch unavailable: {exc}", schema=HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA),
            "predictions": {},
            "diagnostics": {"status": "blocked", "reason": "torch_unavailable", "error": str(exc)},
        }

    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    usable = [item for item in examples if not item.get("not_for_training_reasons")]
    train_examples = [item for item in usable if str(item.get("split") or "candidate") != "holdout"] or usable
    if len(train_examples) < 2:
        return {
            "learned_parameters": _blocked_parameters(
                trainer,
                objective_report,
                "at least two usable training examples are required",
                schema=HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA,
            ),
            "predictions": {},
            "diagnostics": {"status": "blocked", "reason": "insufficient_training_examples", "train_sample_count": len(train_examples)},
        }

    cfg = _training_config(payload)
    _seed_everything(cfg["seed"], torch)

    token_rows = [_hierarchical_feature_groups(item) for item in usable]
    token_keys = _token_group_keys(token_rows)
    relation_keys = _relation_feature_keys(token_rows)
    target_rows = [_target_row(item) for item in usable]
    train_ids = {str(item.get("id") or "") for item in train_examples}
    train_indices = [idx for idx, item in enumerate(usable) if str(item.get("id") or "") in train_ids]

    token_matrices = {group: [_vectorize(row.get(group, {}), token_keys[group]) for row in token_rows] for group in token_keys}
    relation_matrix = [_vectorize(row.get("relations", {}), relation_keys) for row in token_rows]
    action_matrix = [_vectorize(row.get("action", {}), sorted({key for row in token_rows for key in row.get("action", {})})) for row in token_rows]
    scenario_matrix = [_vectorize(row.get("scenario", {}), sorted({key for row in token_rows for key in row.get("scenario", {})})) for row in token_rows]
    context_matrix = [_vectorize(row.get("context", {}), sorted({key for row in token_rows for key in row.get("context", {})})) for row in token_rows]
    temporal_matrix = [_vectorize(row.get("temporal", {}), sorted({key for row in token_rows for key in row.get("temporal", {})})) for row in token_rows]

    action_keys = sorted({key for row in token_rows for key in row.get("action", {})})
    scenario_keys = sorted({key for row in token_rows for key in row.get("scenario", {})})
    context_keys = sorted({key for row in token_rows for key in row.get("context", {})})
    temporal_keys = sorted({key for row in token_rows for key in row.get("temporal", {})})

    token_stats = {group: _normalization_stats([token_matrices[group][idx] for idx in train_indices]) for group in token_keys}
    relation_stats = _normalization_stats([relation_matrix[idx] for idx in train_indices]) if relation_keys else {"mean": [0.0], "std": [1.0]}
    action_stats = _normalization_stats([action_matrix[idx] for idx in train_indices]) if action_keys else {"mean": [0.0], "std": [1.0]}
    scenario_stats = _normalization_stats([scenario_matrix[idx] for idx in train_indices]) if scenario_keys else {"mean": [0.0], "std": [1.0]}
    context_stats = _normalization_stats([context_matrix[idx] for idx in train_indices]) if context_keys else {"mean": [0.0], "std": [1.0]}
    temporal_stats = _normalization_stats([temporal_matrix[idx] for idx in train_indices]) if temporal_keys else {"mean": [0.0], "std": [1.0]}
    y_stats = _target_stats([target_rows[idx] for idx in train_indices])

    token_train = {
        group: _normalize_matrix([token_matrices[group][idx] for idx in train_indices], token_stats[group])
        for group in token_keys
    }
    relation_train = _normalize_matrix([relation_matrix[idx] for idx in train_indices], relation_stats) if relation_keys else [[0.0] for _ in train_indices]
    action_train = _normalize_matrix([action_matrix[idx] for idx in train_indices], action_stats) if action_keys else [[0.0] for _ in train_indices]
    scenario_train = _normalize_matrix([scenario_matrix[idx] for idx in train_indices], scenario_stats) if scenario_keys else [[0.0] for _ in train_indices]
    context_train = _normalize_matrix([context_matrix[idx] for idx in train_indices], context_stats) if context_keys else [[0.0] for _ in train_indices]
    temporal_train = _normalize_matrix([temporal_matrix[idx] for idx in train_indices], temporal_stats) if temporal_keys else [[0.0] for _ in train_indices]
    y_train = [target_rows[idx] for idx in train_indices]

    token_tensors = {
        group: torch.tensor(rows, dtype=torch.float32)
        for group, rows in token_train.items()
    }
    relation_tensor = torch.tensor(relation_train, dtype=torch.float32)
    action_tensor = torch.tensor(action_train, dtype=torch.float32)
    scenario_tensor = torch.tensor(scenario_train, dtype=torch.float32)
    context_tensor = torch.tensor(context_train, dtype=torch.float32)
    temporal_tensor = torch.tensor(temporal_train, dtype=torch.float32)
    y_area = torch.tensor([_normalize_value(row["area_total"], y_stats["area_total"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    temporal_area_target = torch.tensor(
        [_normalize_value(_temporal_next_area_proxy(token_rows[idx], target_rows[idx]), y_stats["area_total"]) for idx in train_indices],
        dtype=torch.float32,
    ).unsqueeze(1)
    y_constraint = torch.tensor([row["constraint_probability"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_utility = torch.tensor([_normalize_value(row["utility_delta"], y_stats["utility_delta"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_confidence = torch.tensor([row["confidence"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_calibration = torch.tensor([_normalize_value(row["calibrated_utility_delta"], y_stats["calibrated_utility_delta"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_allowed = torch.tensor([row["action_allowed"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_ranking = torch.tensor([row["ranking_score"] for row in y_train], dtype=torch.float32)

    model = _HierarchicalGraphDynamicsModel(
        token_dims={group: len(token_keys[group]) for group in token_keys},
        action_dim=len(action_keys) or 1,
        scenario_dim=len(scenario_keys) or 1,
        relation_dim=len(relation_keys) or 1,
        context_dim=len(context_keys) or 1,
        temporal_dim=len(temporal_keys) or 1,
        hidden_dim=cfg["hidden_dim"],
        dropout=cfg["dropout"],
        nn=nn,
        torch=torch,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    bce = nn.BCEWithLogitsLoss()
    mse = nn.MSELoss()
    losses: list[dict[str, float]] = []
    for epoch in range(cfg["epochs"]):
        model.train()
        optimizer.zero_grad()
        out = model(token_tensors, action_tensor, scenario_tensor, relation_tensor, context_tensor, temporal_tensor)
        utility_pred = out[:, 2:3]
        area_pred = out[:, 0:1]
        constraint_prob = torch.sigmoid(out[:, 1:2])
        loss = (
            mse(area_pred, y_area)
            + bce(out[:, 1:2], y_constraint)
            + cfg["constraint_risk_calibration_weight"] * mse(constraint_prob, y_constraint)
            + 1.25 * mse(utility_pred, y_utility)
            + 0.7 * bce(out[:, 3:4], y_confidence)
            + 0.85 * mse(out[:, 4:5], y_calibration)
            + 0.7 * bce(out[:, 5:6], y_allowed)
            + cfg["ranking_weight"] * _pairwise_ranking_loss(utility_pred.squeeze(1), y_ranking, torch)
            + cfg["temporal_consistency_weight"] * _temporal_consistency_loss(area_pred, temporal_area_target, torch)
        )
        loss.backward()
        optimizer.step()
        if epoch == 0 or epoch == cfg["epochs"] - 1:
            losses.append({"epoch": float(epoch + 1), "loss": round(float(loss.detach().cpu().item()), 6)})

    all_token_tensors = {
        group: torch.tensor(_normalize_matrix(token_matrices[group], token_stats[group]), dtype=torch.float32)
        for group in token_keys
    }
    all_relation_tensor = torch.tensor(_normalize_matrix(relation_matrix, relation_stats), dtype=torch.float32) if relation_keys else torch.tensor([[0.0] for _ in usable], dtype=torch.float32)
    all_action_tensor = torch.tensor(_normalize_matrix(action_matrix, action_stats), dtype=torch.float32) if action_keys else torch.tensor([[0.0] for _ in usable], dtype=torch.float32)
    all_scenario_tensor = torch.tensor(_normalize_matrix(scenario_matrix, scenario_stats), dtype=torch.float32) if scenario_keys else torch.tensor([[0.0] for _ in usable], dtype=torch.float32)
    all_context_tensor = torch.tensor(_normalize_matrix(context_matrix, context_stats), dtype=torch.float32) if context_keys else torch.tensor([[0.0] for _ in usable], dtype=torch.float32)
    all_temporal_tensor = torch.tensor(_normalize_matrix(temporal_matrix, temporal_stats), dtype=torch.float32) if temporal_keys else torch.tensor([[0.0] for _ in usable], dtype=torch.float32)
    with torch.no_grad():
        model.eval()
        raw = model(all_token_tensors, all_action_tensor, all_scenario_tensor, all_relation_tensor, all_context_tensor, all_temporal_tensor).detach().cpu()

    predictions: dict[str, dict[str, Any]] = {}
    for idx, example in enumerate(usable):
        example_id = str(example.get("id") or f"example:{idx}")
        row = raw[idx].tolist()
        area = _denormalize_value(row[0], y_stats["area_total"])
        constraint = _sigmoid(row[1])
        utility = _denormalize_value(row[2], y_stats["utility_delta"])
        confidence = _sigmoid(row[3])
        calibration = _denormalize_value(row[4], y_stats["calibrated_utility_delta"])
        allowed_probability = _sigmoid(row[5])
        prediction = _prediction_from_outputs(
            example=example,
            area_total=area,
            constraint_probability=constraint,
            utility_delta=utility,
            confidence=confidence,
            calibrated_utility=calibration,
            action_allowed_probability=allowed_probability,
            source="torch_hierarchical_graph",
        )
        prediction["hierarchical_token_summary"] = {
            "token_groups": sorted(token_keys),
            "relation_feature_count": len(relation_keys),
            "temporal_feature_count": len(temporal_keys),
            "encoder_source": "hierarchical_graph_candidate",
        }
        predictions[example_id] = prediction

    learned_parameters = {
        "schema": HIERARCHICAL_GRAPH_DYNAMICS_SCHEMA,
        "training_status": "pass",
        "trainer": dict(trainer),
        "architecture": {
            "model_type": "torch_hierarchical_graph_candidate",
            "token_groups": sorted(token_keys),
            "relation_feature_count": len(relation_keys),
            "action_feature_count": len(action_keys),
            "scenario_feature_count": len(scenario_keys),
            "context_feature_count": len(context_keys),
            "action_mask_context_feature_count": len(_action_mask_context_feature_names(context_keys)),
            "temporal_feature_count": len(temporal_keys),
            "temporal_message_passing": True,
            "hidden_dim": cfg["hidden_dim"],
            "dropout": cfg["dropout"],
            "heads": [
                "future_latent_state.area_total",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty.confidence",
                "calibration.calibrated_utility_delta",
                "action_mask.allowed",
            ],
        },
        "feature_contract": {
            "flat_vector_allowed": False,
            "vectorization_note": "Hierarchy token groups are encoded separately; relation and temporal features are mixed through lightweight message blocks before action/scenario/context fusion.",
            "token_feature_names": token_keys,
            "relation_feature_names": relation_keys,
            "action_feature_names": action_keys,
            "scenario_feature_names": scenario_keys,
            "context_feature_names": context_keys,
            "action_mask_context_feature_names": _action_mask_context_feature_names(context_keys),
            "temporal_feature_names": temporal_keys,
            "normalization": {
                "token_stats": token_stats,
                "relation_stats": relation_stats,
                "action_stats": action_stats,
                "scenario_stats": scenario_stats,
                "context_stats": context_stats,
                "temporal_stats": temporal_stats,
            },
        },
        "target_normalization": y_stats,
        "objective_contract": dict(objective_report.get("objective_contract") or {}),
        "loss_components": dict(objective_report.get("loss_components") or {}),
        "training_config": cfg,
        "training_diagnostics": {
            "status": "pass",
            "train_sample_count": len(train_examples),
            "usable_sample_count": len(usable),
            "prediction_count": len(predictions),
            "final_loss": losses[-1]["loss"] if losses else None,
            "loss_trace": losses,
            "constraint_risk_calibration_weight": cfg["constraint_risk_calibration_weight"],
        },
        "model_state_dict": _serializable_state_dict(model),
        "limitations": [
            "hierarchical token groups are encoded separately and temporal features are consumed explicitly, but this candidate still uses lightweight learned message mixing rather than a full spatiotemporal graph transformer backbone",
            "parcel/block/township/county token quality remains bounded by current state contract and review-level proxies",
            "claim upgrade still depends on readiness, backend, objective, causal, GeoFM and validation gates",
        ],
    }
    return {
        "learned_parameters": learned_parameters,
        "predictions": predictions,
        "diagnostics": dict(learned_parameters["training_diagnostics"]),
    }


def train_spatiotemporal_transformer_dynamics(
    dataset: dict[str, Any],
    trainer: dict[str, Any],
    objective_report: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Train a lightweight spatiotemporal transformer candidate.

    This remains a compact contract-compatible candidate backend. It upgrades
    the simulator path from grouped message mixing to fixed-token attention over
    parcel/block/township/county + relation/temporal/action/scenario/context.
    """
    try:
        import torch
        import torch.nn as nn
    except Exception as exc:  # pragma: no cover - depends on runtime package set.
        return {
            "learned_parameters": _blocked_parameters(
                trainer,
                objective_report,
                f"torch unavailable: {exc}",
                schema=SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA,
            ),
            "predictions": {},
            "diagnostics": {"status": "blocked", "reason": "torch_unavailable", "error": str(exc)},
        }

    examples = [dict(item) for item in dataset.get("examples") or [] if isinstance(item, dict)]
    usable = [item for item in examples if not item.get("not_for_training_reasons")]
    train_examples = [item for item in usable if str(item.get("split") or "candidate") != "holdout"] or usable
    if len(train_examples) < 2:
        return {
            "learned_parameters": _blocked_parameters(
                trainer,
                objective_report,
                "at least two usable training examples are required",
                schema=SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA,
            ),
            "predictions": {},
            "diagnostics": {"status": "blocked", "reason": "insufficient_training_examples", "train_sample_count": len(train_examples)},
        }

    cfg = _training_config(payload)
    _seed_everything(cfg["seed"], torch)

    token_rows = [_hierarchical_feature_groups(item) for item in usable]
    token_feature_keys = _sequence_feature_keys(token_rows)
    target_rows = [_target_row(item) for item in usable]
    train_ids = {str(item.get("id") or "") for item in train_examples}
    train_indices = [idx for idx, item in enumerate(usable) if str(item.get("id") or "") in train_ids]

    token_matrices = {
        name: [_vectorize(row.get(name, {}), token_feature_keys[name]) for row in token_rows]
        for name in token_feature_keys
    }
    token_stats = {
        name: _normalization_stats([token_matrices[name][idx] for idx in train_indices])
        for name in token_feature_keys
    }
    token_train = {
        name: _normalize_matrix([token_matrices[name][idx] for idx in train_indices], token_stats[name])
        for name in token_feature_keys
    }
    y_stats = _target_stats([target_rows[idx] for idx in train_indices])
    y_train = [target_rows[idx] for idx in train_indices]

    token_tensors = {
        name: torch.tensor(rows, dtype=torch.float32)
        for name, rows in token_train.items()
    }
    y_area = torch.tensor([_normalize_value(row["area_total"], y_stats["area_total"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    temporal_area_target = torch.tensor(
        [_normalize_value(_temporal_next_area_proxy(token_rows[idx], target_rows[idx]), y_stats["area_total"]) for idx in train_indices],
        dtype=torch.float32,
    ).unsqueeze(1)
    y_constraint = torch.tensor([row["constraint_probability"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_utility = torch.tensor([_normalize_value(row["utility_delta"], y_stats["utility_delta"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_confidence = torch.tensor([row["confidence"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_calibration = torch.tensor([_normalize_value(row["calibrated_utility_delta"], y_stats["calibrated_utility_delta"]) for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_allowed = torch.tensor([row["action_allowed"] for row in y_train], dtype=torch.float32).unsqueeze(1)
    y_ranking = torch.tensor([row["ranking_score"] for row in y_train], dtype=torch.float32)

    model = _SpatiotemporalTransformerDynamicsModel(
        token_dims={name: len(token_feature_keys[name]) for name in token_feature_keys},
        hidden_dim=cfg["hidden_dim"],
        dropout=cfg["dropout"],
        risk_head_mode=cfg["risk_head_mode"],
        feasibility_head_mode=cfg["feasibility_head_mode"],
        nn=nn,
        torch=torch,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["learning_rate"], weight_decay=cfg["weight_decay"])
    bce = nn.BCEWithLogitsLoss()
    mse = nn.MSELoss()
    action_mask_weights = _action_mask_training_weights(train_examples, cfg, torch)
    constraint_risk_weights = _constraint_risk_training_weights(train_examples, cfg, torch)
    losses: list[dict[str, float]] = []
    for epoch in range(cfg["epochs"]):
        model.train()
        optimizer.zero_grad()
        out = model(token_tensors)
        utility_pred = out[:, 2:3]
        area_pred = out[:, 0:1]
        constraint_prob = torch.sigmoid(out[:, 1:2])
        constraint_bce = _weighted_binary_loss(out[:, 1:2], y_constraint, constraint_risk_weights, nn)
        constraint_mse = _weighted_mse_loss(constraint_prob, y_constraint, constraint_risk_weights, torch)
        loss = (
            mse(area_pred, y_area)
            + constraint_bce
            + cfg["constraint_risk_calibration_weight"] * constraint_mse
            + 1.25 * mse(utility_pred, y_utility)
            + 0.7 * bce(out[:, 3:4], y_confidence)
            + 0.85 * mse(out[:, 4:5], y_calibration)
            + 0.7 * _weighted_action_mask_loss(out[:, 5:6], y_allowed, action_mask_weights, nn)
            + cfg["ranking_weight"] * _pairwise_ranking_loss(utility_pred.squeeze(1), y_ranking, torch)
            + cfg["temporal_consistency_weight"] * _temporal_consistency_loss(area_pred, temporal_area_target, torch)
        )
        loss.backward()
        optimizer.step()
        if epoch == 0 or epoch == cfg["epochs"] - 1:
            losses.append({"epoch": float(epoch + 1), "loss": round(float(loss.detach().cpu().item()), 6)})

    all_token_tensors = {
        name: torch.tensor(_normalize_matrix(token_matrices[name], token_stats[name]), dtype=torch.float32)
        for name in token_feature_keys
    }
    with torch.no_grad():
        model.eval()
        raw = model(all_token_tensors).detach().cpu()

    predictions: dict[str, dict[str, Any]] = {}
    for idx, example in enumerate(usable):
        example_id = str(example.get("id") or f"example:{idx}")
        row = raw[idx].tolist()
        area = _denormalize_value(row[0], y_stats["area_total"])
        constraint = _sigmoid(row[1])
        utility = _denormalize_value(row[2], y_stats["utility_delta"])
        confidence = _sigmoid(row[3])
        calibration = _denormalize_value(row[4], y_stats["calibrated_utility_delta"])
        allowed_probability = _sigmoid(row[5])
        prediction = _prediction_from_outputs(
            example=example,
            area_total=area,
            constraint_probability=constraint,
            utility_delta=utility,
            confidence=confidence,
            calibrated_utility=calibration,
            action_allowed_probability=allowed_probability,
            source="torch_spatiotemporal_transformer",
        )
        prediction["hierarchical_token_summary"] = {
            "token_groups": ["parcel", "block", "township", "county"],
            "sequence_token_order": list(model.token_order),
            "sequence_token_count": len(model.token_order),
            "attention_backbone": True,
            "encoder_source": "spatiotemporal_transformer_candidate",
        }
        predictions[example_id] = prediction

    learned_parameters = {
        "schema": SPATIOTEMPORAL_TRANSFORMER_DYNAMICS_SCHEMA,
        "training_status": "pass",
        "trainer": dict(trainer),
        "architecture": {
            "model_type": "torch_spatiotemporal_transformer_candidate",
            "token_groups": ["parcel", "block", "township", "county"],
            "sequence_token_order": list(model.token_order),
            "sequence_token_count": len(model.token_order),
            "uses_attention_backbone": True,
            "temporal_token_present": True,
            "action_mask_context_feature_count": len(_action_mask_context_feature_names(token_feature_keys.get("context", []))),
            "constraint_risk_head": cfg["risk_head_mode"],
            "constraint_risk_context_tokens": list(getattr(model, "risk_head_context_tokens", ())),
            "action_mask_feasibility_head": cfg["feasibility_head_mode"],
            "action_mask_feasibility_context_tokens": list(getattr(model, "feasibility_head_context_tokens", ())),
            "hidden_dim": cfg["hidden_dim"],
            "dropout": cfg["dropout"],
            "heads": [
                "future_latent_state.area_total",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty.confidence",
                "calibration.calibrated_utility_delta",
                "action_mask.allowed",
            ],
        },
        "feature_contract": {
            "flat_vector_allowed": False,
            "vectorization_note": "Parcel/block/township/county state, relation, temporal, action, scenario and context are encoded as fixed semantic tokens and fused with lightweight self-attention.",
            "sequence_feature_names": token_feature_keys,
            "action_mask_context_feature_names": _action_mask_context_feature_names(token_feature_keys.get("context", [])),
            "normalization": {"token_stats": token_stats},
        },
        "target_normalization": y_stats,
        "objective_contract": dict(objective_report.get("objective_contract") or {}),
        "loss_components": dict(objective_report.get("loss_components") or {}),
        "training_config": cfg,
        "training_diagnostics": {
            "status": "pass",
            "train_sample_count": len(train_examples),
            "usable_sample_count": len(usable),
            "prediction_count": len(predictions),
            "final_loss": losses[-1]["loss"] if losses else None,
            "loss_trace": losses,
            "learning_rate": cfg["learning_rate"],
            "weight_decay": cfg["weight_decay"],
            "dropout": cfg["dropout"],
            "constraint_risk_calibration_weight": cfg["constraint_risk_calibration_weight"],
            "constraint_risk_contextual_weight": cfg["constraint_risk_contextual_weight"],
            "constraint_risk_weight_mean": round(float(constraint_risk_weights.mean().detach().cpu().item()), 6)
            if constraint_risk_weights is not None
            else 1.0,
            "constraint_risk_weight_max": round(float(constraint_risk_weights.max().detach().cpu().item()), 6)
            if constraint_risk_weights is not None
            else 1.0,
            "seed": cfg["seed"],
            "risk_head_mode": cfg["risk_head_mode"],
            "feasibility_head_mode": cfg["feasibility_head_mode"],
            "action_mask_allowed_positive_weight": cfg["action_mask_allowed_positive_weight"],
            "action_mask_conditioned_allowed_weight": cfg["action_mask_conditioned_allowed_weight"],
            "action_mask_blocked_negative_weight": cfg["action_mask_blocked_negative_weight"],
            "action_mask_mixed_blocked_weight": cfg["action_mask_mixed_blocked_weight"],
        },
        "model_state_dict": _serializable_state_dict(model),
        "limitations": [
            "lightweight fixed-token transformer candidate; not yet a production-scale territorial graph transformer",
            "attention operates over compact hierarchy/relation/temporal summary tokens rather than full parcel graph neighborhoods",
            "claim upgrade still depends on readiness, backend, objective, causal, GeoFM and validation gates",
        ],
    }
    return {
        "learned_parameters": learned_parameters,
        "predictions": predictions,
        "diagnostics": dict(learned_parameters["training_diagnostics"]),
    }


def _blocked_parameters(trainer: dict[str, Any], objective_report: dict[str, Any], reason: str, *, schema: str = NEURAL_DYNAMICS_SCHEMA) -> dict[str, Any]:
    return {
        "schema": schema,
        "training_status": "blocked",
        "trainer": dict(trainer),
        "objective_contract": dict(objective_report.get("objective_contract") or {}),
        "training_diagnostics": {"status": "blocked", "reason": reason},
        "limitations": [reason],
    }


class _MultiHeadDynamicsMLP:
    def __new__(cls, *, input_dim: int, hidden_dim: int, dropout: float, nn: Any):
        return nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 6),
        )


class _HierarchicalGraphDynamicsModel:
    def __new__(
        cls,
        *,
        token_dims: dict[str, int],
        action_dim: int,
        scenario_dim: int,
        relation_dim: int,
        context_dim: int,
        temporal_dim: int,
        hidden_dim: int,
        dropout: float,
        nn: Any,
        torch: Any,
    ):
        class _HierarchicalGraphDynamicsModule(nn.Module):
            def __init__(self):
                super().__init__()
                self.token_order = sorted(token_dims)
                self.token_encoders = nn.ModuleDict(
                    {
                        name: nn.Sequential(
                            nn.Linear(max(1, dim), hidden_dim),
                            nn.ReLU(),
                            nn.Linear(hidden_dim, hidden_dim),
                        )
                        for name, dim in token_dims.items()
                    }
                )
                self.relation_encoder = nn.Sequential(
                    nn.Linear(max(1, relation_dim), hidden_dim),
                    nn.ReLU(),
                    nn.Linear(hidden_dim, hidden_dim),
                )
                self.action_encoder = nn.Sequential(
                    nn.Linear(max(1, action_dim), hidden_dim),
                    nn.ReLU(),
                )
                self.scenario_encoder = nn.Sequential(
                    nn.Linear(max(1, scenario_dim), hidden_dim),
                    nn.ReLU(),
                )
                self.context_encoder = nn.Sequential(
                    nn.Linear(max(1, context_dim), hidden_dim),
                    nn.ReLU(),
                )
                self.temporal_encoder = nn.Sequential(
                    nn.Linear(max(1, temporal_dim), hidden_dim),
                    nn.ReLU(),
                    nn.Linear(hidden_dim, hidden_dim),
                )
                self.message_gate = nn.Sequential(
                    nn.Linear(hidden_dim * 2, hidden_dim),
                    nn.Sigmoid(),
                )
                self.temporal_gate = nn.Sequential(
                    nn.Linear(hidden_dim * 2, hidden_dim),
                    nn.Sigmoid(),
                )
                self.head = nn.Sequential(
                    nn.Linear(hidden_dim * (len(self.token_order) + 5), hidden_dim * 2),
                    nn.LayerNorm(hidden_dim * 2),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(hidden_dim * 2, hidden_dim),
                    nn.ReLU(),
                    nn.Linear(hidden_dim, 6),
                )

            def forward(
                self,
                token_tensors: dict[str, Any],
                action_tensor: Any,
                scenario_tensor: Any,
                relation_tensor: Any,
                context_tensor: Any,
                temporal_tensor: Any,
            ) -> Any:
                encoded_tokens = []
                relation_latent = self.relation_encoder(relation_tensor)
                temporal_latent = self.temporal_encoder(temporal_tensor)
                for idx, name in enumerate(self.token_order):
                    token_latent = self.token_encoders[name](token_tensors[name])
                    gate = self.message_gate(torch.cat([token_latent, relation_latent], dim=1))
                    residual = relation_latent if idx == 0 else encoded_tokens[-1]
                    mixed = token_latent + gate * residual
                    temporal_gate = self.temporal_gate(torch.cat([mixed, temporal_latent], dim=1))
                    encoded_tokens.append(mixed + temporal_gate * temporal_latent)
                action_latent = self.action_encoder(action_tensor)
                scenario_latent = self.scenario_encoder(scenario_tensor)
                context_latent = self.context_encoder(context_tensor)
                fused = torch.cat(encoded_tokens + [relation_latent, temporal_latent, action_latent, scenario_latent, context_latent], dim=1)
                return self.head(fused)

        return _HierarchicalGraphDynamicsModule()


class _SpatiotemporalTransformerDynamicsModel:
    def __new__(
        cls,
        *,
        token_dims: dict[str, int],
        hidden_dim: int,
        dropout: float,
        risk_head_mode: str,
        feasibility_head_mode: str,
        nn: Any,
        torch: Any,
    ):
        class _SpatiotemporalTransformerDynamicsModule(nn.Module):
            def __init__(self):
                super().__init__()
                self.token_order = tuple(token_dims)
                self.risk_head_mode = risk_head_mode
                self.feasibility_head_mode = feasibility_head_mode
                self.risk_head_context_tokens = tuple(
                    name for name in ("action", "context", "temporal") if name in token_dims
                ) if self.risk_head_mode in {"context_residual", "context_direct"} else tuple()
                self.feasibility_head_context_tokens = tuple(
                    name for name in ("action", "context", "temporal") if name in token_dims
                ) if self.feasibility_head_mode == "context_residual" else tuple()
                self.token_encoders = nn.ModuleDict(
                    {
                        name: nn.Sequential(
                            nn.Linear(max(1, dim), hidden_dim),
                            nn.LayerNorm(hidden_dim),
                            nn.ReLU(),
                        )
                        for name, dim in token_dims.items()
                    }
                )
                self.token_type_embedding = nn.Parameter(torch.zeros(len(self.token_order), hidden_dim))
                encoder_layer = nn.TransformerEncoderLayer(
                    d_model=hidden_dim,
                    nhead=_attention_head_count(hidden_dim),
                    dim_feedforward=max(hidden_dim * 2, 32),
                    dropout=dropout,
                    activation="relu",
                    batch_first=True,
                )
                self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=2)
                self.pool = nn.Sequential(
                    nn.Linear(hidden_dim * len(self.token_order), hidden_dim * 2),
                    nn.LayerNorm(hidden_dim * 2),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                    nn.Linear(hidden_dim * 2, hidden_dim),
                    nn.ReLU(),
                )
                self.head = nn.Linear(hidden_dim, 6)
                if self.risk_head_mode == "context_residual":
                    self.constraint_risk_residual_head = nn.Sequential(
                        nn.Linear(hidden_dim * (1 + len(self.risk_head_context_tokens)), hidden_dim),
                        nn.LayerNorm(hidden_dim),
                        nn.ReLU(),
                        nn.Dropout(dropout),
                        nn.Linear(hidden_dim, 1),
                    )
                else:
                    self.constraint_risk_residual_head = None
                if self.risk_head_mode == "context_direct":
                    self.constraint_risk_direct_head = nn.Sequential(
                        nn.Linear(hidden_dim * (1 + len(self.risk_head_context_tokens)), hidden_dim),
                        nn.LayerNorm(hidden_dim),
                        nn.ReLU(),
                        nn.Dropout(dropout),
                        nn.Linear(hidden_dim, 1),
                    )
                else:
                    self.constraint_risk_direct_head = None
                if self.feasibility_head_mode == "context_residual":
                    self.action_mask_feasibility_residual_head = nn.Sequential(
                        nn.Linear(hidden_dim * (1 + len(self.feasibility_head_context_tokens)), hidden_dim),
                        nn.LayerNorm(hidden_dim),
                        nn.ReLU(),
                        nn.Dropout(dropout),
                        nn.Linear(hidden_dim, 1),
                    )
                else:
                    self.action_mask_feasibility_residual_head = None

            def forward(self, token_tensors: dict[str, Any]) -> Any:
                encoded = []
                for idx, name in enumerate(self.token_order):
                    token_latent = self.token_encoders[name](token_tensors[name])
                    token_latent = token_latent + self.token_type_embedding[idx].unsqueeze(0)
                    encoded.append(token_latent)
                sequence = torch.stack(encoded, dim=1)
                attended = self.encoder(sequence)
                flattened = attended.reshape(attended.shape[0], -1)
                pooled = self.pool(flattened)
                out = self.head(pooled)
                token_index = {name: idx for idx, name in enumerate(self.token_order)}
                if self.constraint_risk_residual_head is not None:
                    risk_inputs = [pooled]
                    for name in self.risk_head_context_tokens:
                        risk_inputs.append(attended[:, token_index[name], :])
                    risk_residual = self.constraint_risk_residual_head(torch.cat(risk_inputs, dim=1))
                    out = torch.cat([out[:, 0:1], out[:, 1:2] + risk_residual, out[:, 2:]], dim=1)
                if self.constraint_risk_direct_head is not None:
                    risk_inputs = [pooled]
                    for name in self.risk_head_context_tokens:
                        risk_inputs.append(attended[:, token_index[name], :])
                    risk_logit = self.constraint_risk_direct_head(torch.cat(risk_inputs, dim=1))
                    out = torch.cat([out[:, 0:1], risk_logit, out[:, 2:]], dim=1)
                if self.action_mask_feasibility_residual_head is not None:
                    feasibility_inputs = [pooled]
                    for name in self.feasibility_head_context_tokens:
                        feasibility_inputs.append(attended[:, token_index[name], :])
                    feasibility_residual = self.action_mask_feasibility_residual_head(torch.cat(feasibility_inputs, dim=1))
                    out = torch.cat([out[:, :5], out[:, 5:6] + feasibility_residual], dim=1)
                return out

        return _SpatiotemporalTransformerDynamicsModule()


class _DeprecatedHierarchicalGraphDynamicsModule:
    def __init__(
        self,
        *,
        token_dims: dict[str, int],
        action_dim: int,
        scenario_dim: int,
        relation_dim: int,
        context_dim: int,
        hidden_dim: int,
        dropout: float,
        nn: Any,
        torch: Any,
    ):
        # Kept only to avoid stale references during interactive reloads; new code
        # returns a proper nn.Module from _HierarchicalGraphDynamicsModel.
        raise RuntimeError("use _HierarchicalGraphDynamicsModel")


class _HierarchicalGraphDynamicsModuleRemoved:
    def __new__(
        cls,
        *,
        token_dims: dict[str, int],
        action_dim: int,
        scenario_dim: int,
        relation_dim: int,
        context_dim: int,
        hidden_dim: int,
        dropout: float,
        nn: Any,
        torch: Any,
    ):
        return _DeprecatedHierarchicalGraphDynamicsModule(
            token_dims=token_dims,
            action_dim=action_dim,
            scenario_dim=scenario_dim,
            relation_dim=relation_dim,
            context_dim=context_dim,
            hidden_dim=hidden_dim,
            dropout=dropout,
            nn=nn,
            torch=torch,
        )


def _training_config(payload: dict[str, Any]) -> dict[str, Any]:
    raw = dict(payload.get("training_config") or {})
    return {
        "epochs": max(1, min(500, safe_int(raw.get("epochs"), 80) or 80)),
        "hidden_dim": max(8, min(256, safe_int(raw.get("hidden_dim"), 32) or 32)),
        "learning_rate": float(safe_float(raw.get("learning_rate"), 0.01) or 0.01),
        "weight_decay": float(safe_float(raw.get("weight_decay"), 0.001) or 0.001),
        "dropout": max(0.0, min(0.5, float(safe_float(raw.get("dropout"), 0.0) or 0.0))),
        "ranking_weight": max(0.0, min(2.0, float(safe_float(raw.get("ranking_weight"), 0.2) or 0.2))),
        "temporal_consistency_weight": max(0.0, min(2.0, float(safe_float(raw.get("temporal_consistency_weight"), 0.15) or 0.15))),
        "constraint_risk_calibration_weight": max(
            0.0,
            min(2.0, float(safe_float(raw.get("constraint_risk_calibration_weight"), 0.0) or 0.0)),
        ),
        "constraint_risk_contextual_weight": max(
            1.0,
            min(4.0, float(safe_float(raw.get("constraint_risk_contextual_weight"), 1.0) or 1.0)),
        ),
        "action_mask_allowed_positive_weight": max(
            0.1,
            min(8.0, float(safe_float(raw.get("action_mask_allowed_positive_weight"), 1.0) or 1.0)),
        ),
        "action_mask_conditioned_allowed_weight": max(
            0.1,
            min(8.0, float(safe_float(raw.get("action_mask_conditioned_allowed_weight"), 1.0) or 1.0)),
        ),
        "action_mask_blocked_negative_weight": max(
            0.1,
            min(8.0, float(safe_float(raw.get("action_mask_blocked_negative_weight"), 1.0) or 1.0)),
        ),
        "action_mask_mixed_blocked_weight": max(
            0.1,
            min(8.0, float(safe_float(raw.get("action_mask_mixed_blocked_weight"), 1.0) or 1.0)),
        ),
        "risk_head_mode": _risk_head_mode(raw.get("risk_head_mode")),
        "feasibility_head_mode": _feasibility_head_mode(raw.get("feasibility_head_mode")),
        "seed": safe_int(raw.get("seed"), 42) or 42,
    }


def _risk_head_mode(value: Any) -> str:
    mode = str(value or "shared").strip().lower()
    if mode in {"context_direct", "context_residual", "shared"}:
        return mode
    return "shared"


def _feasibility_head_mode(value: Any) -> str:
    mode = str(value or "shared").strip().lower()
    if mode in {"context_residual", "shared"}:
        return mode
    return "shared"


def _seed_everything(seed: int, torch: Any) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    try:
        torch.set_num_threads(1)
    except Exception:
        pass


def _feature_row(example: dict[str, Any]) -> dict[str, float]:
    current = dict(example.get("current_state_summary") or {})
    action = dict(example.get("action") or {})
    scenario = dict(example.get("scenario_context") or {})
    row: dict[str, float] = {}
    _flatten_numeric("state", current, row, max_depth=4)
    _flatten_numeric("action", _pre_action_features(action), row, max_depth=3)
    _flatten_numeric("scenario", _pre_scenario_features(scenario), row, max_depth=4)
    _one_hot(row, "action_type", str(action.get("action_type") or "unknown"))
    _one_hot(row, "target_role", str(action.get("target_role") or "unknown"))
    _one_hot(row, "scenario_name", str(scenario.get("scenario") or "unknown"))
    row.update(_action_mask_context_features(example))
    row["action.target_object_count"] = float(len(action.get("target_objects") or []))
    row["action.has_treatment"] = 1.0 if action.get("treatment") else 0.0
    return row


def _hierarchical_feature_groups(example: dict[str, Any]) -> dict[str, dict[str, float]]:
    current = dict(example.get("current_state_summary") or {})
    hierarchy = dict(current.get("hierarchy_tokens") or {})
    object_counts = dict(current.get("object_counts_by_role") or hierarchy.get("object_counts_by_role") or {})
    relation_counts = dict(current.get("relation_counts_by_type") or hierarchy.get("relation_counts_by_type") or {})
    quality = dict(current.get("quality_summary") or {})
    action = dict(example.get("action") or {})
    scenario = dict(example.get("scenario_context") or {})
    targets = dict(example.get("targets") or {})
    labels = dict(example.get("labels") or {})
    provenance = dict(example.get("provenance") or {})

    groups = {
        "parcel": {
            "object_count": _count_aliases(object_counts, ("parcel", "parcel_current", "plot", "cadastral_parcel")),
            "annual_change_relations": _count_aliases(relation_counts, ("annual_change_of_parcel", "parcel_temporal_transition")),
            "action_target_count": float(len(action.get("target_objects") or [])),
        },
        "block": {
            "object_count": _count_aliases(object_counts, ("block", "planning_zone", "project")),
            "aggregation_relations": _count_aliases(relation_counts, ("parcel_in_block", "project_overlaps_planning_zone", "block_contains_parcel")),
            "project_count": _count_aliases(object_counts, ("project",)),
        },
        "township": {
            "object_count": _count_aliases(object_counts, ("township", "admin_unit", "street_town")),
            "admin_relations": _count_aliases(relation_counts, ("township_contains_block", "admin_contains_project", "project_in_admin_unit")),
            "review_proxy": 1.0 if _count_aliases(object_counts, ("township", "admin_unit", "street_town")) else 0.0,
        },
        "county": {
            "object_count": 1.0,
            "state_object_count": float(safe_float(current.get("object_count"), 0.0) or 0.0),
            "state_relation_count": float(safe_float(current.get("relation_count"), 0.0) or 0.0),
            "total_area_proxy": float(safe_float(current.get("area_m2"), 0.0) or 0.0),
        },
        "relations": {},
        "action": {},
        "scenario": {},
        "context": {},
        "temporal": {},
    }
    for key, value in sorted(object_counts.items(), key=lambda item: str(item[0])):
        role = _safe_feature_key(str(key))
        amount = float(safe_float(value, 0.0) or 0.0)
        if role in {"parcel", "parcel_current", "plot", "cadastral_parcel"}:
            groups["parcel"][f"role_count.{role}"] = amount
        elif role in {"block", "planning_zone", "project"}:
            groups["block"][f"role_count.{role}"] = amount
        elif role in {"township", "admin_unit", "street_town"}:
            groups["township"][f"role_count.{role}"] = amount
        else:
            groups["county"][f"role_count.{role}"] = amount
    for key, value in sorted(relation_counts.items(), key=lambda item: str(item[0])):
        groups["relations"][f"relation_count.{_safe_feature_key(str(key))}"] = float(safe_float(value, 0.0) or 0.0)
    _flatten_numeric("quality", quality, groups["context"], max_depth=3)
    groups["context"].update(_action_mask_context_features(example))
    _flatten_numeric("temporal", _temporal_features_from_example(example), groups["temporal"], max_depth=4)
    groups["context"]["label.evidence_supported"] = 1.0 if labels.get("evidence_supported") else 0.0
    _flatten_numeric("action", _pre_action_features(action), groups["action"], max_depth=3)
    _one_hot(groups["action"], "action_type", str(action.get("action_type") or "unknown"))
    _one_hot(groups["action"], "target_role", str(action.get("target_role") or "unknown"))
    groups["action"]["target_object_count"] = float(len(action.get("target_objects") or []))
    groups["action"]["has_treatment"] = 1.0 if action.get("treatment") else 0.0
    _flatten_numeric("scenario", _pre_scenario_features(scenario), groups["scenario"], max_depth=3)
    _one_hot(groups["scenario"], "scenario_name", str(scenario.get("scenario") or "unknown"))
    return groups


def _action_mask_context_features(example: dict[str, Any]) -> dict[str, float]:
    current = dict(example.get("current_state_summary") or {})
    scenario = dict(example.get("scenario_context") or {})
    provenance = dict(example.get("provenance") or {})
    features: dict[str, float] = {}

    policy = str(scenario.get("action_mask_policy") or provenance.get("action_mask_policy") or "unspecified")
    _one_hot(features, "action_mask_context.policy", policy)
    normalized_policy = _safe_feature_key(policy)
    policy_requires_review = any(
        item in normalized_policy for item in ("review", "block", "blocked", "hard")
    )
    policy_allows_action = "allow" in normalized_policy and not any(
        item in normalized_policy for item in ("blocked", "block", "hard")
    )
    features["action_mask_context.policy_requires_review"] = 1.0 if policy_requires_review else 0.0
    features["action_mask_context.policy_allows_action"] = 1.0 if policy_allows_action else 0.0
    features["action_mask_context.policy_blocks_action"] = 1.0 if (
        not policy_allows_action and policy_requires_review
    ) else 0.0
    features["action_mask_context.policy_mixed_risk"] = 1.0 if "mixed_risk" in normalized_policy else 0.0
    features["action_mask_context.policy_has_conditions"] = 1.0 if "condition" in normalized_policy else 0.0
    features["action_mask_context.policy_allows_with_conditions"] = 1.0 if (
        policy_allows_action and "condition" in normalized_policy
    ) else 0.0

    baseline_risk = safe_float(current.get("baseline_risk_score"), None)
    if baseline_risk is not None:
        risk_proxy = float(baseline_risk or 0.0)
        features["action_mask_context.risk_proxy_source.current_action"] = 1.0
    else:
        risk_proxy = 0.0
        features["action_mask_context.risk_proxy_source.missing_current_action"] = 1.0
    risk_proxy = _clamp01(risk_proxy)
    features["action_mask_context.risk_proxy"] = risk_proxy
    _one_hot(features, "action_mask_context.risk_bucket", _risk_bucket(risk_proxy))
    return features


def _pre_action_features(action: dict[str, Any]) -> dict[str, Any]:
    spatial_scope = dict(action.get("spatial_scope") or {})
    parameters = dict(action.get("parameters") or {})
    return {
        "spatial_scope": spatial_scope,
        "target_object_count": len(action.get("target_objects") or []),
        "has_treatment": 1.0 if action.get("treatment") else 0.0,
        "parameters": {
            "counterfactual_group_present": 1.0 if parameters.get("counterfactual_group") else 0.0,
        },
    }


def _pre_scenario_features(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "time_index": scenario.get("time_index"),
        "synthetic_experiment": scenario.get("synthetic_experiment"),
    }


def _action_mask_training_weights(examples: list[dict[str, Any]], cfg: dict[str, Any], torch: Any) -> Any:
    weights = []
    for example in examples:
        targets = dict(example.get("targets") or {})
        action_mask = dict(targets.get("action_mask") or {})
        allowed = bool(action_mask.get("allowed", True))
        weight = 1.0
        policy = str(
            (example.get("scenario_context") or {}).get("action_mask_policy")
            or (example.get("provenance") or {}).get("action_mask_policy")
            or ""
        )
        normalized_policy = _safe_feature_key(policy)
        if allowed:
            weight *= float(cfg.get("action_mask_allowed_positive_weight") or 1.0)
            if "condition" in normalized_policy or action_mask.get("required_reviews"):
                weight *= float(cfg.get("action_mask_conditioned_allowed_weight") or 1.0)
        else:
            weight *= float(cfg.get("action_mask_blocked_negative_weight") or 1.0)
            if "mixed_risk" in normalized_policy or action_mask.get("required_reviews") or action_mask.get("hard_blocks"):
                weight *= float(cfg.get("action_mask_mixed_blocked_weight") or 1.0)
        weights.append(float(weight))
    return torch.tensor(weights, dtype=torch.float32).unsqueeze(1)


def _constraint_risk_training_weights(examples: list[dict[str, Any]], cfg: dict[str, Any], torch: Any) -> Any:
    contextual_weight = float(cfg.get("constraint_risk_contextual_weight") or 1.0)
    if contextual_weight <= 1.0:
        return torch.ones((len(examples), 1), dtype=torch.float32)
    weights: list[float] = []
    for example in examples:
        current = dict(example.get("current_state_summary") or {})
        scenario = dict(example.get("scenario_context") or {})
        provenance = dict(example.get("provenance") or {})
        baseline_risk = _clamp01(float(safe_float(current.get("baseline_risk_score"), 0.0) or 0.0))
        policy = str(scenario.get("action_mask_policy") or provenance.get("action_mask_policy") or "")
        normalized_policy = _safe_feature_key(policy)
        context_score = baseline_risk
        if "mixed_risk" in normalized_policy:
            context_score = max(context_score, 0.55)
        if any(item in normalized_policy for item in ("condition", "review")):
            context_score = max(context_score, 0.65)
        if any(item in normalized_policy for item in ("block", "blocked", "hard")):
            context_score = max(context_score, 0.75)
        weight = 1.0 + (contextual_weight - 1.0) * context_score
        weights.append(round(float(weight), 6))
    return torch.tensor(weights, dtype=torch.float32).unsqueeze(1)


def _weighted_binary_loss(logits: Any, targets: Any, weights: Any, nn: Any) -> Any:
    loss = nn.functional.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    if weights is None or weights.numel() != loss.numel():
        return loss.mean()
    return (loss * weights).mean()


def _weighted_mse_loss(predictions: Any, targets: Any, weights: Any, torch: Any) -> Any:
    loss = (predictions - targets) ** 2
    if weights is None or weights.numel() != loss.numel():
        return loss.mean()
    return (loss * weights).mean()


def _weighted_action_mask_loss(logits: Any, targets: Any, weights: Any, nn: Any) -> Any:
    loss = nn.functional.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    if weights is None or weights.numel() != loss.numel():
        return loss.mean()
    return (loss * weights).mean()


def _action_mask_context_feature_names(names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if name.startswith("action_mask_context.") or name.startswith("category.action_mask_context.")
    ]


def _risk_bucket(value: float) -> str:
    value = float(value)
    if value >= 0.3:
        return "high"
    if value >= 0.24:
        return "medium"
    return "low"


def _temporal_features_from_example(example: dict[str, Any]) -> dict[str, Any]:
    scenario = dict(example.get("scenario_context") or {})
    current = dict(example.get("current_state_summary") or {})
    time_index = safe_float(scenario.get("time_index"), safe_float(current.get("time_index"), 0.0))
    features = {
        "time_index": float(time_index or 0.0),
        "sample_type_temporal": 1.0 if str(example.get("sample_type") or "") == "temporal_state_transition" else 0.0,
        "baseline_state_score": safe_float(current.get("baseline_state_score"), 0.0) or 0.0,
        "baseline_risk_score": safe_float(current.get("baseline_risk_score"), 0.0) or 0.0,
        "quality_score": safe_float(current.get("quality_score"), 0.0) or 0.0,
        "area_m2": safe_float(current.get("area_m2"), 0.0) or 0.0,
    }
    return features


def _flatten_temporal_latent(prefix: str, latent: dict[str, Any], out: dict[str, float]) -> None:
    if not latent:
        return
    out[f"{prefix}.total_area_m2"] = float(safe_float(latent.get("total_area_m2"), 0.0) or 0.0)
    for key, value in sorted(dict(latent.get("land_space_types") or {}).items(), key=lambda item: str(item[0])):
        if isinstance(value, dict):
            out[f"{prefix}.land_space_types.{_safe_feature_key(str(key))}.area_m2"] = float(safe_float(value.get("area_m2"), 0.0) or 0.0)


def _temporal_next_area_proxy(token_row: dict[str, dict[str, float]], target_row: dict[str, float]) -> float:
    temporal = dict(token_row.get("temporal") or {})
    observed = safe_float(temporal.get("temporal.observed_next.total_area_m2"), None)
    if observed is not None:
        return float(observed)
    current = safe_float(temporal.get("temporal.current.total_area_m2"), None)
    net_delta = safe_float(temporal.get("temporal.delta.net_area_delta_m2"), None)
    if current is not None and net_delta is not None:
        return float(current) + float(net_delta)
    return float(target_row.get("area_total") or 0.0)


def _temporal_consistency_loss(area_pred: Any, temporal_area_target: Any, torch: Any) -> Any:
    if area_pred.numel() == 0 or temporal_area_target.numel() == 0:
        return torch.tensor(0.0, dtype=area_pred.dtype if hasattr(area_pred, "dtype") else torch.float32)
    return ((area_pred - temporal_area_target) ** 2).mean()


def _count_aliases(counts: dict[str, Any], aliases: tuple[str, ...]) -> float:
    return float(sum(float(safe_float(counts.get(alias), 0.0) or 0.0) for alias in aliases))


def _token_group_keys(rows: list[dict[str, dict[str, float]]]) -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for group in ("parcel", "block", "township", "county"):
        group_keys = sorted({key for row in rows for key in row.get(group, {})})
        keys[group] = group_keys or ["bias"]
        for row in rows:
            if not row.get(group):
                row[group] = {"bias": 1.0}
    return keys


def _relation_feature_keys(rows: list[dict[str, dict[str, float]]]) -> list[str]:
    keys = sorted({key for row in rows for key in row.get("relations", {})})
    if not keys:
        for row in rows:
            row["relations"] = {"bias": 1.0}
        return ["bias"]
    return keys


def _sequence_feature_keys(rows: list[dict[str, dict[str, float]]]) -> dict[str, list[str]]:
    keys = _token_group_keys(rows)
    for group in ("relations", "temporal", "action", "scenario", "context"):
        feature_names = sorted({key for row in rows for key in row.get(group, {})})
        keys[group] = feature_names or ["bias"]
        for row in rows:
            if not row.get(group):
                row[group] = {"bias": 1.0}
    return keys


def _attention_head_count(hidden_dim: int) -> int:
    for candidate in (4, 3, 2):
        if hidden_dim % candidate == 0:
            return candidate
    return 1


def _safe_feature_key(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_") or "unknown"


def _flatten_numeric(prefix: str, value: Any, out: dict[str, float], *, max_depth: int) -> None:
    if max_depth < 0:
        return
    if isinstance(value, bool):
        out[prefix] = 1.0 if value else 0.0
        return
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        out[prefix] = float(value)
        return
    if isinstance(value, dict):
        for key, nested in sorted(value.items(), key=lambda item: str(item[0])):
            _flatten_numeric(f"{prefix}.{key}", nested, out, max_depth=max_depth - 1)
        return
    if isinstance(value, (list, tuple)):
        out[f"{prefix}.count"] = float(len(value))
        numeric = [float(item) for item in value if isinstance(item, (int, float)) and math.isfinite(float(item))]
        if numeric:
            out[f"{prefix}.sum"] = float(sum(numeric))
            out[f"{prefix}.mean"] = float(sum(numeric) / len(numeric))


def _one_hot(row: dict[str, float], prefix: str, value: str) -> None:
    safe = "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_") or "unknown"
    row[f"category.{prefix}.{safe}"] = 1.0


def _target_row(example: dict[str, Any]) -> dict[str, float]:
    targets = dict(example.get("targets") or {})
    labels = dict(example.get("labels") or {})
    uncertainty = dict(targets.get("uncertainty") or {})
    calibration = dict(targets.get("calibration") or {})
    action_mask = dict(targets.get("action_mask") or {})
    utility = float(safe_float(targets.get("planning_utility_delta"), 0.0) or 0.0)
    calibrated = safe_float(calibration.get("calibrated_utility_delta"), None)
    if calibrated is None:
        calibrated = safe_float(calibration.get("observed_transition_proxy"), None)
    return {
        "area_total": _target_area_total(targets),
        "constraint_probability": _clamp01(float(safe_float(targets.get("constraint_violation_probability"), 0.0) or 0.0)),
        "utility_delta": utility,
        "confidence": _clamp01(float(safe_float(uncertainty.get("confidence"), 0.0) or 0.0)),
        "calibrated_utility_delta": float(calibrated if calibrated is not None else utility),
        "action_allowed": 1.0 if action_mask.get("allowed", True) else 0.0,
        "ranking_score": float(safe_float(labels.get("ranking_score"), utility) or utility),
    }


def _target_area_total(targets: dict[str, Any]) -> float:
    latent = dict(targets.get("future_latent_state") or {})
    observed = dict(latent.get("observed_next") or latent.get("projected") or {})
    value = safe_float(observed.get("total_area_m2"), None)
    if value is not None:
        return float(value)
    land_types = dict(observed.get("land_space_types") or {})
    total = 0.0
    for item in land_types.values():
        if isinstance(item, dict):
            total += float(safe_float(item.get("area_m2"), 0.0) or 0.0)
    return total


def _vectorize(row: dict[str, float], feature_names: list[str]) -> list[float]:
    return [float(row.get(name, 0.0)) for name in feature_names]


def _normalization_stats(rows: list[list[float]]) -> dict[str, list[float]]:
    if not rows:
        return {"mean": [0.0], "std": [1.0]}
    width = len(rows[0])
    means = [sum(row[idx] for row in rows) / len(rows) for idx in range(width)]
    stds = []
    for idx, mean in enumerate(means):
        var = sum((row[idx] - mean) ** 2 for row in rows) / max(1, len(rows))
        stds.append(math.sqrt(var) or 1.0)
    return {"mean": [round(item, 6) for item in means], "std": [round(item, 6) for item in stds]}


def _normalize_matrix(rows: list[list[float]], stats: dict[str, list[float]]) -> list[list[float]]:
    means = list(stats.get("mean") or [])
    stds = list(stats.get("std") or [])
    return [[(value - means[idx]) / (stds[idx] or 1.0) for idx, value in enumerate(row)] for row in rows]


def _target_stats(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    return {
        key: _scalar_stats([row[key] for row in rows])
        for key in ("area_total", "utility_delta", "calibrated_utility_delta")
    }


def _scalar_stats(values: list[float]) -> dict[str, float]:
    mean = sum(values) / max(1, len(values))
    var = sum((item - mean) ** 2 for item in values) / max(1, len(values))
    return {"mean": round(mean, 6), "std": round(math.sqrt(var) or 1.0, 6)}


def _normalize_value(value: float, stats: dict[str, float]) -> float:
    return (float(value) - float(stats.get("mean") or 0.0)) / (float(stats.get("std") or 1.0) or 1.0)


def _denormalize_value(value: float, stats: dict[str, float]) -> float:
    return round(float(value) * (float(stats.get("std") or 1.0) or 1.0) + float(stats.get("mean") or 0.0), 6)


def _pairwise_ranking_loss(pred_utility: Any, ranking: Any, torch: Any) -> Any:
    if pred_utility.numel() < 2:
        return torch.tensor(0.0, dtype=pred_utility.dtype)
    diff_target = ranking.unsqueeze(1) - ranking.unsqueeze(0)
    mask = diff_target > 0
    if not bool(mask.any()):
        return torch.tensor(0.0, dtype=pred_utility.dtype)
    diff_pred = pred_utility.unsqueeze(1) - pred_utility.unsqueeze(0)
    return torch.relu(0.05 - diff_pred[mask]).mean()


def _prediction_from_outputs(
    *,
    example: dict[str, Any],
    area_total: float,
    constraint_probability: float,
    utility_delta: float,
    confidence: float,
    calibrated_utility: float,
    action_allowed_probability: float,
    source: str,
) -> dict[str, Any]:
    action = dict(example.get("action") or {})
    allowed = action_allowed_probability >= 0.5
    latent_observed = {"total_area_m2": round(max(0.0, float(area_total)), 6)}
    return {
        "action": action,
        "future_latent_state": {
            "schema": "territory_world_model.predicted_latent_state.v1",
            "observed_next": latent_observed,
            "projected": {
                "total_area_m2": latent_observed["total_area_m2"],
                "projected_risk_pressure": round(_clamp01(constraint_probability), 6),
                "projected_utility_delta": round(float(utility_delta), 6),
            },
            "latent_head_scope": "area_total_plus_planning_heads",
        },
        "constraint_violation_probability": round(_clamp01(constraint_probability), 6),
        "planning_utility_delta": round(float(utility_delta), 6),
        "uncertainty": {
            "confidence": round(_clamp01(confidence), 6),
            "source": source,
        },
        "calibration": {
            "calibrated_utility_delta": round(float(calibrated_utility), 6),
            "source": source,
        },
        "action_mask": {
            "allowed": bool(allowed),
            "predicted_allowed_probability": round(_clamp01(action_allowed_probability), 6),
            "confidence": round(max(action_allowed_probability, 1.0 - action_allowed_probability), 6),
            "source": source,
        },
    }


def _serializable_state_dict(model: Any) -> dict[str, Any]:
    state = {}
    for key, tensor in model.state_dict().items():
        value = tensor.detach().cpu().tolist()
        state[key] = _round_nested(value)
    return state


def _round_nested(value: Any) -> Any:
    if isinstance(value, list):
        return [_round_nested(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(value)))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
