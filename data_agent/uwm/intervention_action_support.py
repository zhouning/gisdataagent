"""Primitive-action support diagnostics for intervention-conditioned models."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from scipy.optimize import linprog, minimize


def _as_design(
    development: np.ndarray,
    target: np.ndarray,
    feature_names: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
    x = np.asarray(development, dtype=np.float64)
    h = np.asarray(target, dtype=np.float64)
    names = tuple(feature_names)
    if x.ndim != 2 or h.ndim != 1:
        raise ValueError("development must be 2-D and target must be 1-D")
    if x.shape[1] != h.shape[0] or len(names) != h.shape[0]:
        raise ValueError("feature dimensions do not match")
    if x.shape[0] < 1 or x.shape[1] < 1:
        raise ValueError("action design must not be empty")
    if len(set(names)) != len(names):
        raise ValueError("feature names must be unique")
    if not np.isfinite(x).all() or not np.isfinite(h).all():
        raise ValueError("action design contains non-finite values")
    return x, h, names


def _relative_residual(residual: float, target: np.ndarray) -> float:
    return float(residual / max(float(np.linalg.norm(target)), 1.0))


def _convex_reconstruction(
    design: np.ndarray,
    target: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float, bool]:
    n_rows = design.shape[0]
    equality_matrix = np.vstack([design.T, np.ones(n_rows)])
    equality_target = np.concatenate([target, [1.0]])
    feasibility = linprog(
        np.zeros(n_rows),
        A_eq=equality_matrix,
        b_eq=equality_target,
        bounds=(0.0, None),
        method="highs",
    )
    if feasibility.success:
        weights = np.asarray(feasibility.x, dtype=np.float64)
        reconstruction = weights @ design
        residual = float(np.linalg.norm(reconstruction - target))
        return weights, reconstruction, residual, True

    initial = np.full(n_rows, 1.0 / n_rows, dtype=np.float64)

    result = minimize(
        lambda weights: float(np.sum((weights @ design - target) ** 2)),
        initial,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * n_rows,
        constraints=[{"type": "eq", "fun": lambda weights: weights.sum() - 1.0}],
        options={"ftol": 1e-14, "maxiter": 5_000},
    )
    weights = np.asarray(result.x, dtype=np.float64)
    reconstruction = weights @ design
    residual = float(np.linalg.norm(reconstruction - target))
    feasible = bool(
        result.success
        and abs(float(weights.sum()) - 1.0) <= 1e-7
        and float(weights.min()) >= -1e-9
    )
    return weights, reconstruction, residual, feasible


def analyze_action_support(
    development: np.ndarray,
    target: np.ndarray,
    feature_names: Sequence[str],
    *,
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Analyze a target action without mixing primitive and derived features.

    Rows are observed action vectors and columns are declared primitive action
    dimensions. The null-space witness is the target residual after projection
    onto the observed row space. It demonstrates observational equivalence for
    a locally linear response whenever that residual is non-zero.
    """

    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    x, h, names = _as_design(development, target, feature_names)
    unique = np.unique(x, axis=0)
    scale = np.maximum(np.max(np.abs(unique), axis=0), 1e-12)
    xs = unique / scale
    hs = h / scale

    singular_values = np.linalg.svd(xs, compute_uv=False)
    centered = xs - xs.mean(axis=0, keepdims=True)
    centered_singular_values = np.linalg.svd(centered, compute_uv=False)
    rank = int(np.linalg.matrix_rank(xs, tol=tolerance))
    centered_rank = int(np.linalg.matrix_rank(centered, tol=tolerance))
    positive_singular_values = singular_values[singular_values > tolerance]
    condition_number = (
        float(positive_singular_values[0] / positive_singular_values[-1])
        if len(positive_singular_values)
        else None
    )

    row_weights = np.linalg.lstsq(xs.T, hs, rcond=tolerance)[0]
    row_reconstruction = row_weights @ xs
    row_residual_vector = hs - row_reconstruction
    row_residual = float(np.linalg.norm(row_residual_vector))

    augmented = np.vstack([xs.T, np.ones(xs.shape[0])])
    affine_target = np.concatenate([hs, [1.0]])
    affine_weights = np.linalg.lstsq(augmented, affine_target, rcond=tolerance)[0]
    affine_reconstruction = affine_weights @ xs
    affine_residual = float(np.linalg.norm(affine_reconstruction - hs))
    affine_sum_error = abs(float(affine_weights.sum()) - 1.0)

    _, convex_reconstruction, convex_residual, convex_feasible = (
        _convex_reconstruction(xs, hs)
    )

    null_norm = float(np.linalg.norm(row_residual_vector))
    if null_norm > tolerance:
        null_witness = row_residual_vector / null_norm
        max_observed_dot = float(np.max(np.abs(xs @ null_witness)))
        target_dot = float(hs @ null_witness)
        witness = {
            "available": True,
            "vector": {
                name: float(value) for name, value in zip(names, null_witness)
            },
            "max_abs_observed_action_dot": max_observed_dot,
            "target_action_dot": target_dot,
            "interpretation": (
                "A locally linear response can be changed along this direction "
                "without changing any observed development-action response."
            ),
        }
    else:
        witness = {
            "available": False,
            "vector": None,
            "max_abs_observed_action_dot": None,
            "target_action_dot": None,
            "interpretation": (
                "No target-separating null-space witness exists at this tolerance; "
                "this does not establish convex interpolation or nonlinear identification."
            ),
        }

    componentwise: dict[str, dict[str, float | bool]] = {}
    for index, name in enumerate(names):
        lower = float(unique[:, index].min())
        upper = float(unique[:, index].max())
        value = float(h[index])
        componentwise[name] = {
            "development_min": lower,
            "development_max": upper,
            "target": value,
            "inside": bool(lower - tolerance <= value <= upper + tolerance),
        }

    relative_row_residual = _relative_residual(row_residual, hs)
    relative_affine_residual = _relative_residual(affine_residual, hs)
    relative_convex_residual = _relative_residual(convex_residual, hs)
    return {
        "feature_names": list(names),
        "feature_count": len(names),
        "unique_development_vectors": int(len(unique)),
        "rank": rank,
        "centered_rank": centered_rank,
        "full_column_rank": rank == len(names),
        "singular_values": [float(value) for value in singular_values],
        "centered_singular_values": [
            float(value) for value in centered_singular_values
        ],
        "condition_number_nonzero_singular_values": condition_number,
        "componentwise_support": componentwise,
        "componentwise_support_pass": all(
            bool(row["inside"]) for row in componentwise.values()
        ),
        "row_span": {
            "residual": row_residual,
            "relative_residual": relative_row_residual,
            "pass": relative_row_residual <= tolerance,
        },
        "affine_hull": {
            "residual": affine_residual,
            "relative_residual": relative_affine_residual,
            "weight_sum_error": affine_sum_error,
            "pass": (
                relative_affine_residual <= tolerance
                and affine_sum_error <= tolerance
            ),
        },
        "convex_hull": {
            "residual": convex_residual,
            "relative_residual": relative_convex_residual,
            "optimization_feasible": convex_feasible,
            "pass": convex_feasible and relative_convex_residual <= tolerance,
            "reconstruction": {
                name: float(value)
                for name, value in zip(names, convex_reconstruction * scale)
            },
        },
        "null_space_witness": witness,
        "interpretation_boundary": (
            "Convex-hull support implies affine-hull and row-span support and also "
            "implies componentwise range inclusion. Componentwise inclusion and "
            "row-span support do not imply one another. Full rank of an exposure-"
            "weighted node design is not independent policy-event variation."
        ),
    }
