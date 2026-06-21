from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .specs import SCCAPaths, StudySpec


@dataclass(frozen=True)
class SpatialGraph:
    method: str
    neighbors: tuple[tuple[int, ...], ...]
    warnings: tuple[str, ...] = ()


def _json_ready(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    return value


def _align_source_frame(features: pd.DataFrame, source_frame: Any | None) -> Any | None:
    if source_frame is None:
        return None
    if len(source_frame) == len(features):
        try:
            return source_frame.loc[features.index].reset_index(drop=True)
        except Exception:
            try:
                return source_frame.reset_index(drop=True)
            except Exception:
                return source_frame
    return None


def _geometry_series(source_frame: Any | None) -> Any | None:
    if source_frame is None:
        return None
    if hasattr(source_frame, "geometry"):
        geometry = getattr(source_frame, "geometry")
        if geometry is not None:
            return geometry.reset_index(drop=True)
    if "geometry" in getattr(source_frame, "columns", []):
        return source_frame["geometry"].reset_index(drop=True)
    return None


def _is_polygon_like(geometry: Any) -> bool:
    geom_type = str(getattr(geometry, "geom_type", ""))
    return geom_type in {"Polygon", "MultiPolygon"}


def _query_spatial_index(geometries: Any, geometry: Any, predicate: str) -> list[int]:
    sindex = geometries.sindex
    try:
        return [int(item) for item in sindex.query(geometry, predicate=predicate)]
    except TypeError:
        candidates = [int(item) for item in sindex.query(geometry)]
        result: list[int] = []
        for item in candidates:
            other = geometries.iloc[item]
            try:
                matches = bool(getattr(geometry, predicate)(other))
            except Exception:
                matches = False
            if matches:
                result.append(item)
        return result


def _geometry_adjacency(source_frame: Any | None) -> SpatialGraph | None:
    geometries = _geometry_series(source_frame)
    if geometries is None or len(geometries) < 2:
        return None

    polygon_count = int(
        sum(
            1
            for geometry in geometries
            if geometry is not None
            and not getattr(geometry, "is_empty", True)
            and _is_polygon_like(geometry)
        )
    )
    if polygon_count < max(2, len(geometries) // 2):
        return None

    warnings_: list[str] = []
    neighbors = [set() for _ in range(len(geometries))]
    try:
        for i, geometry in enumerate(geometries):
            if geometry is None or getattr(geometry, "is_empty", True):
                continue
            for j in _query_spatial_index(geometries, geometry, "touches"):
                if i == j:
                    continue
                neighbors[i].add(j)
                neighbors[j].add(i)
    except Exception as exc:
        warnings_.append(f"Geometry adjacency failed: {exc}")
        return None

    edge_count = sum(len(items) for items in neighbors) // 2
    if edge_count == 0:
        warnings_.append("No touching polygon neighbors found; geometry adjacency skipped.")
        return None

    return SpatialGraph(
        method="geometry_touches",
        neighbors=tuple(tuple(sorted(items)) for items in neighbors),
        warnings=tuple(warnings_),
    )


def _coordinates_from_source(
    features: pd.DataFrame,
    spec: StudySpec,
    source_frame: Any | None,
) -> tuple[np.ndarray | None, tuple[str, ...], tuple[str, ...]]:
    warnings_: list[str] = []
    aligned = _align_source_frame(features, source_frame)
    candidate_frames = [features.reset_index(drop=True)]
    if aligned is not None:
        candidate_frames.insert(0, aligned)

    if spec.coordinate_columns:
        x_col, y_col = spec.coordinate_columns
        for frame in candidate_frames:
            columns = getattr(frame, "columns", [])
            if x_col in columns and y_col in columns:
                x = pd.to_numeric(frame[x_col], errors="coerce").to_numpy(dtype=float)
                y = pd.to_numeric(frame[y_col], errors="coerce").to_numpy(dtype=float)
                return np.column_stack([x, y]), (x_col, y_col), tuple(warnings_)

    geometries = _geometry_series(aligned)
    if geometries is not None and len(geometries) == len(features):
        x_values: list[float] = []
        y_values: list[float] = []
        for geometry in geometries:
            point = None
            if geometry is not None and not getattr(geometry, "is_empty", True):
                representative = getattr(geometry, "representative_point", None)
                if callable(representative):
                    point = representative()
                else:
                    point = getattr(geometry, "centroid", None)
            x_values.append(float(getattr(point, "x", np.nan)) if point is not None else np.nan)
            y_values.append(float(getattr(point, "y", np.nan)) if point is not None else np.nan)
        return np.column_stack([x_values, y_values]), ("geometry_x", "geometry_y"), tuple(warnings_)

    warnings_.append("No coordinate columns or usable geometry were available.")
    return None, (), tuple(warnings_)


def _knn_adjacency(
    features: pd.DataFrame,
    spec: StudySpec,
    source_frame: Any | None,
    *,
    k: int = 4,
) -> SpatialGraph | None:
    coordinates, coordinate_columns, warnings_ = _coordinates_from_source(features, spec, source_frame)
    if coordinates is None:
        return None
    finite = np.isfinite(coordinates).all(axis=1)
    valid_positions = np.flatnonzero(finite)
    if len(valid_positions) < 2:
        return SpatialGraph(
            method="coordinate_knn",
            neighbors=tuple(() for _ in range(len(features))),
            warnings=(*warnings_, "Fewer than two finite coordinate pairs were available."),
        )

    k_eff = max(1, min(int(k), len(valid_positions) - 1))
    neighbors = [set() for _ in range(len(features))]
    valid_coordinates = coordinates[valid_positions]
    try:
        from sklearn.neighbors import NearestNeighbors

        model = NearestNeighbors(n_neighbors=k_eff + 1)
        model.fit(valid_coordinates)
        _, local_indices = model.kneighbors(valid_coordinates)
        for row_position, local_neighbors in zip(valid_positions, local_indices):
            for local_neighbor in local_neighbors:
                neighbor_position = int(valid_positions[int(local_neighbor)])
                if neighbor_position == row_position:
                    continue
                neighbors[int(row_position)].add(neighbor_position)
                neighbors[neighbor_position].add(int(row_position))
    except Exception:
        distances = np.linalg.norm(
            valid_coordinates[:, None, :] - valid_coordinates[None, :, :],
            axis=2,
        )
        np.fill_diagonal(distances, np.inf)
        order = np.argsort(distances, axis=1)[:, :k_eff]
        for i_local, local_neighbors in enumerate(order):
            row_position = int(valid_positions[i_local])
            for local_neighbor in local_neighbors:
                neighbor_position = int(valid_positions[int(local_neighbor)])
                neighbors[row_position].add(neighbor_position)
                neighbors[neighbor_position].add(row_position)

    return SpatialGraph(
        method="coordinate_knn",
        neighbors=tuple(tuple(sorted(items)) for items in neighbors),
        warnings=(
            *warnings_,
            f"Coordinate graph used columns: {', '.join(coordinate_columns)}.",
            f"k={k_eff}.",
        ),
    )


def _build_spatial_graph(
    features: pd.DataFrame,
    spec: StudySpec,
    source_frame: Any | None,
) -> SpatialGraph:
    aligned = _align_source_frame(features, source_frame)
    geometry_graph = _geometry_adjacency(aligned)
    if geometry_graph is not None:
        return geometry_graph
    knn_graph = _knn_adjacency(features, spec, aligned)
    if knn_graph is not None:
        return knn_graph
    return SpatialGraph(
        method="unavailable",
        neighbors=tuple(() for _ in range(len(features))),
        warnings=("Spatial graph could not be built from geometry or coordinates.",),
    )


def build_spatial_graph(
    features: pd.DataFrame,
    spec: StudySpec,
    source_frame: Any | None = None,
) -> SpatialGraph:
    """Public wrapper for building the spatial graph used by SCCA diagnostics."""

    return _build_spatial_graph(features.reset_index(drop=True).copy(), spec, source_frame)


def build_coordinate_knn_graph(
    features: pd.DataFrame,
    spec: StudySpec,
    source_frame: Any | None = None,
    *,
    k: int = 4,
) -> SpatialGraph:
    """Build a coordinate kNN graph for graph-specification sensitivity checks."""

    analysis_features = features.reset_index(drop=True).copy()
    graph = _knn_adjacency(analysis_features, spec, _align_source_frame(analysis_features, source_frame), k=k)
    if graph is not None:
        return graph
    return SpatialGraph(
        method="unavailable",
        neighbors=tuple(() for _ in range(len(analysis_features))),
        warnings=("Coordinate kNN graph could not be built.",),
    )


def spatial_coordinates(
    features: pd.DataFrame,
    spec: StudySpec,
    source_frame: Any | None = None,
) -> np.ndarray | None:
    coordinates, _, _ = _coordinates_from_source(
        features.reset_index(drop=True).copy(),
        spec,
        _align_source_frame(features.reset_index(drop=True).copy(), source_frame),
    )
    return coordinates


def _graph_summary(graph: SpatialGraph) -> dict[str, object]:
    n = len(graph.neighbors)
    degrees = np.asarray([len(items) for items in graph.neighbors], dtype=float)
    edge_count = int(degrees.sum() // 2)
    isolate_count = int((degrees == 0).sum()) if n else 0
    return {
        "method": graph.method,
        "n_units": int(n),
        "edge_count": edge_count,
        "average_degree": float(degrees.mean()) if n else None,
        "max_degree": int(degrees.max()) if n else 0,
        "isolate_count": isolate_count,
        "isolate_share": float(isolate_count / n) if n else None,
        "warnings": list(graph.warnings),
    }


def _moran_core(values: np.ndarray, neighbors: tuple[tuple[int, ...], ...]) -> dict[str, object]:
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values)
    n_valid = int(valid.sum())
    if n_valid < 3:
        return {"moran_i": None, "n": n_valid, "s0": 0, "status": "skipped"}

    centered = values.copy()
    centered[valid] = centered[valid] - float(np.nanmean(values[valid]))
    denominator = float(np.sum(centered[valid] ** 2))
    if not np.isfinite(denominator) or denominator <= 0:
        return {"moran_i": None, "n": n_valid, "s0": 0, "status": "skipped"}

    numerator = 0.0
    s0 = 0
    for i, items in enumerate(neighbors):
        if not valid[i]:
            continue
        for j in items:
            if j < len(values) and valid[j]:
                numerator += float(centered[i] * centered[j])
                s0 += 1
    if s0 == 0:
        return {"moran_i": None, "n": n_valid, "s0": 0, "status": "skipped"}

    moran_i = (n_valid / s0) * (numerator / denominator)
    return {
        "moran_i": float(moran_i) if np.isfinite(moran_i) else None,
        "expected_i": float(-1.0 / (n_valid - 1)) if n_valid > 1 else None,
        "n": n_valid,
        "s0": int(s0),
        "status": "ok",
    }


def _moran_summary(
    values: pd.Series | np.ndarray,
    graph: SpatialGraph,
    *,
    n_permutations: int,
    random_state: int,
) -> dict[str, object]:
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    observed = _moran_core(numeric, graph.neighbors)
    if observed.get("status") != "ok" or observed.get("moran_i") is None or n_permutations <= 0:
        return observed

    rng = np.random.default_rng(random_state)
    valid = np.isfinite(numeric)
    valid_values = numeric[valid].copy()
    observed_i = float(observed["moran_i"])
    more_extreme = 0
    for _ in range(n_permutations):
        permuted = numeric.copy()
        permuted[valid] = rng.permutation(valid_values)
        permuted_i = _moran_core(permuted, graph.neighbors).get("moran_i")
        if permuted_i is not None and abs(float(permuted_i)) >= abs(observed_i):
            more_extreme += 1
    observed["permutation_p_value"] = float((more_extreme + 1) / (n_permutations + 1))
    observed["n_permutations"] = int(n_permutations)
    return observed


def _model_covariates(features: pd.DataFrame, spec: StudySpec) -> list[str]:
    return [
        column
        for column in dict.fromkeys([*spec.confounders, *spec.context_columns])
        if column in features.columns
    ]


def _coef_value(values: Any, key: str) -> float | None:
    try:
        value = float(values.get(key, np.nan))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _ci_value(conf_int: pd.DataFrame, key: str, position: int) -> float | None:
    if key not in getattr(conf_int, "index", []):
        return None
    try:
        value = float(conf_int.loc[key, position])
    except (TypeError, ValueError, KeyError):
        return None
    return value if np.isfinite(value) else None


def _cov_value(cov_params: Any, row_key: str, col_key: str) -> float | None:
    try:
        if hasattr(cov_params, "loc"):
            value = float(cov_params.loc[row_key, col_key])
        else:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    return value if np.isfinite(value) else None


def _normal_two_sided_p(z_score: float | None) -> float | None:
    if z_score is None or not np.isfinite(float(z_score)):
        return None
    return float(math.erfc(abs(float(z_score)) / math.sqrt(2.0)))


def _spatial_adjustment_sensitivity(
    baseline_exposure_coef: float | None,
    exposure_coef: float | None,
) -> dict[str, object]:
    if baseline_exposure_coef is None or not np.isfinite(float(baseline_exposure_coef)):
        return {}
    baseline = float(baseline_exposure_coef)
    if exposure_coef is None or not np.isfinite(float(exposure_coef)):
        return {
            "baseline_exposure_coef": baseline,
            "spatial_adjusted_exposure_coef": None,
            "coef_delta": None,
            "relative_change": None,
            "sign_stable": None,
        }
    delta = float(exposure_coef) - baseline
    relative_change = abs(delta) / max(abs(baseline), np.finfo(float).eps)
    return {
        "baseline_exposure_coef": baseline,
        "spatial_adjusted_exposure_coef": float(exposure_coef),
        "coef_delta": float(delta),
        "relative_change": float(relative_change),
        "sign_stable": bool(np.sign(baseline) == np.sign(float(exposure_coef)))
        if baseline != 0
        else None,
    }


def _main_model_residuals(features: pd.DataFrame, spec: StudySpec) -> tuple[pd.Series, dict[str, object]]:
    covariates = _model_covariates(features, spec)
    columns = [spec.outcome, spec.exposure, *covariates]
    if spec.outcome not in features.columns or spec.exposure not in features.columns:
        return (
            pd.Series(np.nan, index=features.index, dtype=float),
            {"status": "skipped", "warning": "Outcome or exposure column is missing."},
        )
    frame = features[columns].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < max(3, len(covariates) + 2) or frame[spec.exposure].nunique() < 2:
        return (
            pd.Series(np.nan, index=features.index, dtype=float),
            {"status": "skipped", "warning": "Too few rows or no exposure variation for residual diagnostics."},
        )
    try:
        x = sm.add_constant(frame[[spec.exposure, *covariates]], has_constant="add").astype(float)
        y = frame[spec.outcome].astype(float)
        model = sm.OLS(y, x, missing="drop").fit()
        residuals = pd.Series(np.nan, index=features.index, dtype=float)
        residuals.loc[frame.index] = model.resid
        return residuals, {"status": "ok", "n": int(model.nobs)}
    except Exception as exc:
        return (
            pd.Series(np.nan, index=features.index, dtype=float),
            {"status": "unstable", "warning": f"Residual model failed: {exc}"},
        )


def _neighbor_mean(values: pd.Series, graph: SpatialGraph) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    result = np.repeat(np.nan, len(numeric))
    for i, items in enumerate(graph.neighbors):
        neighbor_values = numeric[list(items)] if items else np.asarray([], dtype=float)
        finite = neighbor_values[np.isfinite(neighbor_values)]
        if finite.size:
            result[i] = float(finite.mean())
    return pd.Series(result, index=values.index, dtype=float)


def _neighbor_exposure_model(
    features: pd.DataFrame,
    spec: StudySpec,
    graph: SpatialGraph,
    *,
    baseline_exposure_coef: float | None = None,
) -> dict[str, object]:
    if graph.method == "unavailable" or spec.exposure not in features.columns or spec.outcome not in features.columns:
        return {"status": "skipped"}
    covariates = _model_covariates(features, spec)
    frame = features[[spec.outcome, spec.exposure, *covariates]].copy()
    frame["neighbor_exposure"] = _neighbor_mean(features[spec.exposure], graph)
    required = [spec.outcome, spec.exposure, "neighbor_exposure", *covariates]
    numeric = frame[required].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(numeric) < max(5, len(covariates) + 3) or numeric["neighbor_exposure"].nunique() < 2:
        return {
            "status": "skipped",
            "n": int(len(numeric)),
            "warning": "Too few complete rows or no neighbor-exposure variation.",
        }

    try:
        model_columns = [spec.exposure, "neighbor_exposure", *covariates]
        x = sm.add_constant(numeric[model_columns], has_constant="add").astype(float)
        y = numeric[spec.outcome].astype(float)
        model = sm.OLS(y, x, missing="drop").fit(cov_type="HC3")
        conf_int = model.conf_int()
        coef = _coef_value(model.params, "neighbor_exposure")
        p_value = _coef_value(model.pvalues, "neighbor_exposure")
        exposure_coef = _coef_value(model.params, spec.exposure)
        return {
            "status": "ok" if coef is not None else "unstable",
            "n": int(model.nobs),
            "exposure_coef": exposure_coef,
            "coef": coef,
            "p_value": p_value,
            "ci_lower": _ci_value(conf_int, "neighbor_exposure", 0),
            "ci_upper": _ci_value(conf_int, "neighbor_exposure", 1),
            "r_squared": float(model.rsquared) if np.isfinite(model.rsquared) else None,
            "spatial_adjustment_sensitivity": _spatial_adjustment_sensitivity(
                baseline_exposure_coef,
                exposure_coef,
            ),
        }
    except Exception as exc:
        return {"status": "unstable", "warning": f"Neighbor exposure model failed: {exc}"}


def _spatial_lag_model(
    features: pd.DataFrame,
    spec: StudySpec,
    graph: SpatialGraph,
    *,
    baseline_exposure_coef: float | None = None,
) -> dict[str, object]:
    if graph.method == "unavailable" or spec.exposure not in features.columns or spec.outcome not in features.columns:
        return {"status": "skipped"}

    covariates = _model_covariates(features, spec)
    frame = features[[spec.outcome, spec.exposure, *covariates]].copy()
    frame["neighbor_exposure"] = _neighbor_mean(features[spec.exposure], graph)
    lag_columns: list[str] = []
    for column in covariates:
        lag_name = f"neighbor_{column}"
        frame[lag_name] = _neighbor_mean(features[column], graph)
        lag_columns.append(lag_name)

    required = [spec.outcome, spec.exposure, "neighbor_exposure", *covariates, *lag_columns]
    numeric = frame[required].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    min_rows = max(12, len(covariates) * 2 + 6)
    if len(numeric) < min_rows:
        return {
            "status": "skipped",
            "n": int(len(numeric)),
            "warning": "Too few complete rows for spatial lag adjustment.",
        }
    if numeric["neighbor_exposure"].nunique() < 2 or numeric[spec.exposure].nunique() < 2:
        return {
            "status": "skipped",
            "n": int(len(numeric)),
            "warning": "No variation in exposure or neighbor exposure for spatial lag adjustment.",
        }

    model_columns = [spec.exposure, "neighbor_exposure", *covariates, *lag_columns]
    try:
        x = sm.add_constant(numeric[model_columns], has_constant="add").astype(float)
        if x.shape[1] >= len(numeric):
            return {
                "status": "skipped",
                "n": int(len(numeric)),
                "warning": "Spatial lag adjustment is over-parameterized for the available rows.",
            }
        rank = int(np.linalg.matrix_rank(x.to_numpy(dtype=float)))
        if rank < x.shape[1]:
            return {
                "status": "unstable",
                "n": int(len(numeric)),
                "warning": "Spatial lag adjustment design matrix is rank deficient.",
            }
        y = numeric[spec.outcome].astype(float)
        model = sm.OLS(y, x, missing="drop").fit(cov_type="HC3")
        conf_int = model.conf_int()
        exposure_coef = _coef_value(model.params, spec.exposure)
        neighbor_exposure_coef = _coef_value(model.params, "neighbor_exposure")
        lag_significant_count = 0
        for lag_name in lag_columns:
            p_value = _coef_value(model.pvalues, lag_name)
            if p_value is not None and p_value <= 0.05:
                lag_significant_count += 1
        return {
            "status": "ok" if exposure_coef is not None else "unstable",
            "n": int(model.nobs),
            "exposure_coef": exposure_coef,
            "coef": neighbor_exposure_coef,
            "p_value": _coef_value(model.pvalues, "neighbor_exposure"),
            "ci_lower": _ci_value(conf_int, "neighbor_exposure", 0),
            "ci_upper": _ci_value(conf_int, "neighbor_exposure", 1),
            "r_squared": float(model.rsquared) if np.isfinite(model.rsquared) else None,
            "lag_covariate_count": int(len(lag_columns)),
            "lag_covariates_significant": int(lag_significant_count),
            "spatial_adjustment_sensitivity": _spatial_adjustment_sensitivity(
                baseline_exposure_coef,
                exposure_coef,
            ),
        }
    except Exception as exc:
        return {"status": "unstable", "warning": f"Spatial lag model failed: {exc}"}


_SLX_COLUMNS = [
    "term",
    "source_column",
    "role",
    "coef",
    "se",
    "p_value",
    "ci_lower",
    "ci_upper",
]


def _empty_slx_estimates() -> pd.DataFrame:
    return pd.DataFrame(columns=_SLX_COLUMNS)


def _slx_role(term: str, spec: StudySpec, covariates: list[str]) -> tuple[str, str]:
    if term == "const":
        return term, "intercept"
    if term == spec.exposure:
        return term, "direct_exposure"
    if term == "neighbor_exposure":
        return spec.exposure, "indirect_exposure"
    if term.startswith("neighbor_"):
        source_column = term.removeprefix("neighbor_")
        if source_column in spec.confounders:
            return source_column, "neighbor_confounder"
        if source_column in spec.context_columns:
            return source_column, "neighbor_context"
        return source_column, "neighbor_covariate"
    if term in spec.confounders:
        return term, "local_confounder"
    if term in spec.context_columns:
        return term, "local_context"
    if term in covariates:
        return term, "local_covariate"
    return term, "other"


def _slx_coefficient_table(
    model: Any,
    conf_int: pd.DataFrame,
    model_columns: list[str],
    spec: StudySpec,
    covariates: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    terms = ["const", *model_columns]
    for term in terms:
        source_column, role = _slx_role(term, spec, covariates)
        rows.append(
            {
                "term": term,
                "source_column": source_column,
                "role": role,
                "coef": _coef_value(model.params, term),
                "se": _coef_value(model.bse, term),
                "p_value": _coef_value(model.pvalues, term),
                "ci_lower": _ci_value(conf_int, term, 0),
                "ci_upper": _ci_value(conf_int, term, 1),
            }
        )
    return pd.DataFrame(rows, columns=_SLX_COLUMNS)


def run_spatial_slx_summary(
    features: pd.DataFrame,
    spec: StudySpec,
    graph: SpatialGraph,
    *,
    baseline_exposure_coef: float | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Fit an SLX-style spatial covariate lag model and summarize impacts."""

    if graph.method == "unavailable" or spec.exposure not in features.columns or spec.outcome not in features.columns:
        return _empty_slx_estimates(), {"status": "skipped", "model": "SLX"}

    covariates = _model_covariates(features, spec)
    frame = features[[spec.outcome, spec.exposure, *covariates]].copy()
    frame["neighbor_exposure"] = _neighbor_mean(features[spec.exposure], graph)
    lag_columns: list[str] = []
    for column in covariates:
        lag_name = f"neighbor_{column}"
        frame[lag_name] = _neighbor_mean(features[column], graph)
        lag_columns.append(lag_name)

    required = [spec.outcome, spec.exposure, "neighbor_exposure", *covariates, *lag_columns]
    numeric = frame[required].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    min_rows = max(12, len(covariates) * 2 + 6)
    if len(numeric) < min_rows:
        return _empty_slx_estimates(), {
            "status": "skipped",
            "model": "SLX",
            "n": int(len(numeric)),
            "warning": "Too few complete rows for SLX spatial covariate lag adjustment.",
        }
    if numeric["neighbor_exposure"].nunique() < 2 or numeric[spec.exposure].nunique() < 2:
        return _empty_slx_estimates(), {
            "status": "skipped",
            "model": "SLX",
            "n": int(len(numeric)),
            "warning": "No variation in exposure or neighbor exposure for SLX adjustment.",
        }

    model_columns = [spec.exposure, "neighbor_exposure", *covariates, *lag_columns]
    try:
        x = sm.add_constant(numeric[model_columns], has_constant="add").astype(float)
        if x.shape[1] >= len(numeric):
            return _empty_slx_estimates(), {
                "status": "skipped",
                "model": "SLX",
                "n": int(len(numeric)),
                "warning": "SLX adjustment is over-parameterized for the available rows.",
            }
        rank = int(np.linalg.matrix_rank(x.to_numpy(dtype=float)))
        if rank < x.shape[1]:
            return _empty_slx_estimates(), {
                "status": "unstable",
                "model": "SLX",
                "n": int(len(numeric)),
                "warning": "SLX design matrix is rank deficient.",
            }
        y = numeric[spec.outcome].astype(float)
        model = sm.OLS(y, x, missing="drop").fit(cov_type="HC3")
        conf_int = model.conf_int()
        cov_params = model.cov_params()
        coefficient_table = _slx_coefficient_table(model, conf_int, model_columns, spec, covariates)

        direct = _coef_value(model.params, spec.exposure)
        indirect = _coef_value(model.params, "neighbor_exposure")
        total = direct + indirect if direct is not None and indirect is not None else None
        direct_var = _cov_value(cov_params, spec.exposure, spec.exposure)
        indirect_var = _cov_value(cov_params, "neighbor_exposure", "neighbor_exposure")
        direct_indirect_cov = _cov_value(cov_params, spec.exposure, "neighbor_exposure")
        total_se = None
        total_ci_lower = None
        total_ci_upper = None
        total_p_value = None
        if (
            total is not None
            and direct_var is not None
            and indirect_var is not None
            and direct_indirect_cov is not None
        ):
            total_var = direct_var + indirect_var + 2.0 * direct_indirect_cov
            if total_var >= 0 and np.isfinite(total_var):
                total_se = float(math.sqrt(total_var))
                total_ci_lower = float(total - 1.96 * total_se)
                total_ci_upper = float(total + 1.96 * total_se)
                if total_se > 0:
                    total_p_value = _normal_two_sided_p(float(total / total_se))
        if total is not None:
            coefficient_table = pd.concat(
                [
                    coefficient_table,
                    pd.DataFrame(
                        [
                            {
                                "term": "total_effect",
                                "source_column": spec.exposure,
                                "role": "derived_total_exposure_effect",
                                "coef": total,
                                "se": total_se,
                                "p_value": total_p_value,
                                "ci_lower": total_ci_lower,
                                "ci_upper": total_ci_upper,
                            }
                        ],
                        columns=_SLX_COLUMNS,
                    ),
                ],
                ignore_index=True,
            )
        lag_significant_count = 0
        for lag_name in lag_columns:
            p_value = _coef_value(model.pvalues, lag_name)
            if p_value is not None and p_value <= 0.05:
                lag_significant_count += 1

        summary = {
            "status": "ok" if direct is not None else "unstable",
            "model": "SLX",
            "n": int(model.nobs),
            "r_squared": float(model.rsquared) if np.isfinite(model.rsquared) else None,
            "graph_method": graph.method,
            "weighting": "row_standardized_neighbor_mean",
            "exposure_coef": direct,
            "coef": indirect,
            "p_value": _coef_value(model.pvalues, "neighbor_exposure"),
            "ci_lower": _ci_value(conf_int, "neighbor_exposure", 0),
            "ci_upper": _ci_value(conf_int, "neighbor_exposure", 1),
            "direct_effect": direct,
            "direct_p_value": _coef_value(model.pvalues, spec.exposure),
            "direct_ci_lower": _ci_value(conf_int, spec.exposure, 0),
            "direct_ci_upper": _ci_value(conf_int, spec.exposure, 1),
            "indirect_effect": indirect,
            "indirect_p_value": _coef_value(model.pvalues, "neighbor_exposure"),
            "indirect_ci_lower": _ci_value(conf_int, "neighbor_exposure", 0),
            "indirect_ci_upper": _ci_value(conf_int, "neighbor_exposure", 1),
            "total_effect": total,
            "total_se": total_se,
            "total_p_value": total_p_value,
            "total_ci_lower": total_ci_lower,
            "total_ci_upper": total_ci_upper,
            "lag_covariate_count": int(len(lag_columns)),
            "lag_covariates_significant": int(lag_significant_count),
            "coefficient_count": int(len(coefficient_table)),
            "spatial_adjustment_sensitivity": _spatial_adjustment_sensitivity(
                baseline_exposure_coef,
                direct,
            ),
            "interpretation": "spatial_covariate_lag_sensitivity",
            "note": (
                "SLX regresses the outcome on local exposure/covariates and row-standardized neighboring "
                "exposure/covariates. Direct, indirect, and total effects are model-implied sensitivity "
                "summaries, not SAR/CAR simultaneous feedback effects or randomized network-interference effects."
            ),
        }
        return coefficient_table, summary
    except Exception as exc:
        return _empty_slx_estimates(), {
            "status": "unstable",
            "model": "SLX",
            "warning": f"SLX model failed: {exc}",
        }


def _diagnostic_flags(diagnostics: dict[str, object]) -> list[str]:
    flags: list[str] = []
    residual = diagnostics.get("residual_moran")
    if isinstance(residual, dict):
        moran_i = residual.get("moran_i")
        p_value = residual.get("permutation_p_value")
        if (
            isinstance(moran_i, (int, float))
            and isinstance(p_value, (int, float))
            and abs(float(moran_i)) >= 0.05
            and float(p_value) <= 0.05
        ):
            flags.append(
                f"Residual spatial autocorrelation detected (Moran's I={float(moran_i):.3f}, p={float(p_value):.3f})."
            )

    neighbor = diagnostics.get("neighbor_exposure_model")
    if isinstance(neighbor, dict):
        coef = neighbor.get("coef")
        p_value = neighbor.get("p_value")
        if (
            isinstance(coef, (int, float))
            and isinstance(p_value, (int, float))
            and float(p_value) <= 0.05
        ):
            flags.append(
                f"Neighbor exposure remains associated with the outcome after adjustment (coef={float(coef):.3f}, p={float(p_value):.3f})."
            )
        sensitivity = neighbor.get("spatial_adjustment_sensitivity")
        if isinstance(sensitivity, dict):
            relative_change = sensitivity.get("relative_change")
            sign_stable = sensitivity.get("sign_stable")
            adjusted = sensitivity.get("spatial_adjusted_exposure_coef")
            if sign_stable is False:
                flags.append(
                    "Main exposure coefficient changes sign after adding neighbor exposure."
                )
            elif isinstance(relative_change, (int, float)) and float(relative_change) >= 0.25:
                flags.append(
                    "Main exposure coefficient shifts materially after adding neighbor exposure "
                    f"(spatial-adjusted coef={float(adjusted):.3f}, relative change={float(relative_change):.3f})."
                )

    lag_model = diagnostics.get("spatial_lag_model")
    if isinstance(lag_model, dict) and lag_model.get("status") == "ok":
        sensitivity = lag_model.get("spatial_adjustment_sensitivity")
        if isinstance(sensitivity, dict):
            relative_change = sensitivity.get("relative_change")
            sign_stable = sensitivity.get("sign_stable")
            adjusted = sensitivity.get("spatial_adjusted_exposure_coef")
            if sign_stable is False:
                flags.append(
                    "Main exposure coefficient changes sign after adding neighboring covariate/context lags."
                )
            elif isinstance(relative_change, (int, float)) and float(relative_change) >= 0.25:
                flags.append(
                    "Main exposure coefficient shifts materially after adding neighboring covariate/context lags "
                    f"(spatial-lag-adjusted coef={float(adjusted):.3f}, relative change={float(relative_change):.3f})."
                )

    graph_sensitivity = diagnostics.get("graph_sensitivity_summary")
    if isinstance(graph_sensitivity, dict) and graph_sensitivity.get("status") == "ok":
        max_relative_change = graph_sensitivity.get("neighbor_adjusted_relative_change_max")
        sign_stability = graph_sensitivity.get("neighbor_adjusted_sign_stability")
        if sign_stability is False:
            flags.append("Main exposure coefficient changes sign across alternative spatial graph specifications.")
        elif isinstance(max_relative_change, (int, float)) and float(max_relative_change) >= 0.25:
            flags.append(
                "Main exposure coefficient is sensitive to spatial graph specification "
                f"(max relative change across k graphs={float(max_relative_change):.3f})."
            )
    return flags


def run_spatial_graph_sensitivity(
    features: pd.DataFrame,
    spec: StudySpec,
    *,
    source_frame: Any | None = None,
    baseline_exposure_coef: float | None = None,
    n_permutations: int = 19,
    random_state: int = 0,
    k_values: tuple[int, ...] = (2, 4, 6, 8),
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Evaluate spatial diagnostics under multiple coordinate-kNN graph specifications."""

    coordinates = spatial_coordinates(features, spec, source_frame)
    if coordinates is None:
        rows = pd.DataFrame(
            columns=[
                "graph_spec",
                "graph_method",
                "edge_count",
                "exposure_moran_i",
                "residual_moran_i",
                "neighbor_adjusted_coef",
                "neighbor_adjusted_relative_change",
                "spatial_lag_adjusted_coef",
                "spatial_lag_relative_change",
                "neighbor_exposure_coef",
                "neighbor_exposure_p_value",
                "status",
            ]
        )
        return rows, {
            "status": "skipped",
            "warning": "No coordinates were available for graph sensitivity analysis.",
            "n_graphs_requested": int(len(k_values)),
            "n_graphs_valid": 0,
        }

    rows: list[dict[str, object]] = []
    for offset, k in enumerate(k_values):
        graph = build_coordinate_knn_graph(features, spec, source_frame, k=k)
        residuals, _ = _main_model_residuals(features, spec)
        exposure_moran = _moran_summary(
            features[spec.exposure] if spec.exposure in features.columns else pd.Series(dtype=float),
            graph,
            n_permutations=n_permutations,
            random_state=random_state + offset * 10,
        )
        residual_moran = _moran_summary(
            residuals,
            graph,
            n_permutations=n_permutations,
            random_state=random_state + offset * 10 + 1,
        )
        neighbor_model = _neighbor_exposure_model(
            features,
            spec,
            graph,
            baseline_exposure_coef=baseline_exposure_coef,
        )
        lag_model = _spatial_lag_model(
            features,
            spec,
            graph,
            baseline_exposure_coef=baseline_exposure_coef,
        )
        neighbor_sensitivity = (
            neighbor_model.get("spatial_adjustment_sensitivity")
            if isinstance(neighbor_model, dict)
            else {}
        )
        lag_sensitivity = (
            lag_model.get("spatial_adjustment_sensitivity")
            if isinstance(lag_model, dict)
            else {}
        )
        rows.append(
            {
                "graph_spec": f"coordinate_knn_k{k}",
                "graph_method": graph.method,
                "edge_count": _graph_summary(graph).get("edge_count"),
                "exposure_moran_i": exposure_moran.get("moran_i"),
                "residual_moran_i": residual_moran.get("moran_i"),
                "neighbor_adjusted_coef": neighbor_model.get("exposure_coef") if isinstance(neighbor_model, dict) else None,
                "neighbor_adjusted_relative_change": neighbor_sensitivity.get("relative_change")
                if isinstance(neighbor_sensitivity, dict)
                else None,
                "spatial_lag_adjusted_coef": lag_model.get("exposure_coef") if isinstance(lag_model, dict) else None,
                "spatial_lag_relative_change": lag_sensitivity.get("relative_change")
                if isinstance(lag_sensitivity, dict)
                else None,
                "neighbor_exposure_coef": neighbor_model.get("coef") if isinstance(neighbor_model, dict) else None,
                "neighbor_exposure_p_value": neighbor_model.get("p_value") if isinstance(neighbor_model, dict) else None,
                "status": (
                    "ok"
                    if isinstance(neighbor_model, dict)
                    and neighbor_model.get("status") == "ok"
                    else neighbor_model.get("status") if isinstance(neighbor_model, dict) else "skipped"
                ),
            }
        )

    table = pd.DataFrame(rows)
    neighbor_coefs = pd.to_numeric(table.get("neighbor_adjusted_coef"), errors="coerce")
    lag_coefs = pd.to_numeric(table.get("spatial_lag_adjusted_coef"), errors="coerce")
    neighbor_rel = pd.to_numeric(table.get("neighbor_adjusted_relative_change"), errors="coerce")
    lag_rel = pd.to_numeric(table.get("spatial_lag_relative_change"), errors="coerce")
    valid_neighbor = neighbor_coefs[np.isfinite(neighbor_coefs)]
    valid_lag = lag_coefs[np.isfinite(lag_coefs)]
    summary: dict[str, object] = {
        "status": "ok" if not valid_neighbor.empty else "skipped",
        "n_graphs_requested": int(len(k_values)),
        "n_graphs_valid": int(len(valid_neighbor)),
        "graph_specs": list(table["graph_spec"]) if not table.empty else [],
    }
    if not valid_neighbor.empty:
        neighbor_signs = np.sign(valid_neighbor)
        neighbor_signs = neighbor_signs[neighbor_signs != 0]
        summary.update(
            {
                "neighbor_adjusted_coef_min": float(valid_neighbor.min()),
                "neighbor_adjusted_coef_max": float(valid_neighbor.max()),
                "neighbor_adjusted_coef_range": float(valid_neighbor.max() - valid_neighbor.min()),
                "neighbor_adjusted_relative_change_max": float(np.nanmax(neighbor_rel.to_numpy(dtype=float)))
                if np.isfinite(neighbor_rel.to_numpy(dtype=float)).any()
                else None,
                "neighbor_adjusted_sign_stability": bool(neighbor_signs.nunique() <= 1) if len(neighbor_signs) else True,
            }
        )
    if not valid_lag.empty:
        lag_signs = np.sign(valid_lag)
        lag_signs = lag_signs[lag_signs != 0]
        summary.update(
            {
                "spatial_lag_adjusted_coef_min": float(valid_lag.min()),
                "spatial_lag_adjusted_coef_max": float(valid_lag.max()),
                "spatial_lag_adjusted_coef_range": float(valid_lag.max() - valid_lag.min()),
                "spatial_lag_relative_change_max": float(np.nanmax(lag_rel.to_numpy(dtype=float)))
                if np.isfinite(lag_rel.to_numpy(dtype=float)).any()
                else None,
                "spatial_lag_sign_stability": bool(lag_signs.nunique() <= 1) if len(lag_signs) else True,
            }
        )
    return table, summary


def run_spatial_spillover_decomposition(
    diagnostics: dict[str, object],
    graph_sensitivity_rows: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Summarize direct-effect proxy and spillover proxy from spatial adjustment models.

    This is a sensitivity-oriented decomposition based on neighbor-average
    exposure models. It is not a formal network-interference identification
    result.
    """

    rows: list[dict[str, object]] = []
    for model_name, label in (
        ("neighbor_exposure_model", "neighbor_adjusted"),
        ("spatial_lag_model", "spatial_lag_adjusted"),
        ("spatial_slx_model", "slx"),
    ):
        model = diagnostics.get(model_name)
        if not isinstance(model, dict) or model.get("status") != "ok":
            continue
        direct_coef = model.get("exposure_coef")
        spillover_coef = model.get("coef")
        try:
            direct = float(direct_coef)
        except (TypeError, ValueError):
            continue
        try:
            spillover = float(spillover_coef)
        except (TypeError, ValueError):
            spillover = np.nan
        total_local = direct + spillover if np.isfinite(spillover) else direct
        spill_share = (
            abs(spillover) / max(abs(direct) + abs(spillover), np.finfo(float).eps)
            if np.isfinite(spillover)
            else np.nan
        )
        spill_to_direct = spillover / direct if np.isfinite(spillover) and direct != 0 else np.nan
        rows.append(
            {
                "model": label,
                "direct_effect_proxy": direct,
                "spillover_effect_proxy": spillover if np.isfinite(spillover) else np.nan,
                "combined_local_effect": total_local if np.isfinite(total_local) else np.nan,
                "spillover_share_abs": spill_share if np.isfinite(spill_share) else np.nan,
                "spillover_to_direct_ratio": spill_to_direct if np.isfinite(spill_to_direct) else np.nan,
                "spillover_p_value": model.get("p_value"),
                "n": model.get("n"),
            }
        )

    if graph_sensitivity_rows is not None and not graph_sensitivity_rows.empty:
        numeric = graph_sensitivity_rows.copy()
        numeric["direct_effect_proxy"] = pd.to_numeric(numeric["neighbor_adjusted_coef"], errors="coerce")
        numeric["spillover_effect_proxy"] = pd.to_numeric(numeric["neighbor_exposure_coef"], errors="coerce")
        valid = numeric["direct_effect_proxy"].notna() & numeric["spillover_effect_proxy"].notna()
        for _, row in numeric.loc[valid].iterrows():
            direct = float(row["direct_effect_proxy"])
            spillover = float(row["spillover_effect_proxy"])
            total_local = direct + spillover
            spill_share = abs(spillover) / max(abs(direct) + abs(spillover), np.finfo(float).eps)
            spill_to_direct = spillover / direct if direct != 0 else np.nan
            rows.append(
                {
                    "model": str(row.get("graph_spec")),
                    "direct_effect_proxy": direct,
                    "spillover_effect_proxy": spillover,
                    "combined_local_effect": total_local,
                    "spillover_share_abs": spill_share,
                    "spillover_to_direct_ratio": spill_to_direct if np.isfinite(spill_to_direct) else np.nan,
                    "spillover_p_value": row.get("neighbor_exposure_p_value"),
                    "n": np.nan,
                }
            )

    table = pd.DataFrame(rows)
    summary: dict[str, object] = {"status": "skipped"}
    if not table.empty:
        spill_share = pd.to_numeric(table["spillover_share_abs"], errors="coerce")
        spill_ratio = pd.to_numeric(table["spillover_to_direct_ratio"], errors="coerce")
        summary = {
            "status": "ok",
            "models": list(table["model"].astype(str)),
            "direct_effect_proxy_main": table.loc[table["model"] == "neighbor_adjusted", "direct_effect_proxy"].iloc[0]
            if (table["model"] == "neighbor_adjusted").any()
            else None,
            "spillover_effect_proxy_main": table.loc[table["model"] == "neighbor_adjusted", "spillover_effect_proxy"].iloc[0]
            if (table["model"] == "neighbor_adjusted").any()
            else None,
            "spillover_share_abs_main": table.loc[table["model"] == "neighbor_adjusted", "spillover_share_abs"].iloc[0]
            if (table["model"] == "neighbor_adjusted").any()
            else None,
            "spillover_share_abs_min": float(spill_share.min()) if spill_share.notna().any() else None,
            "spillover_share_abs_max": float(spill_share.max()) if spill_share.notna().any() else None,
            "spillover_to_direct_ratio_min": float(spill_ratio.min()) if spill_ratio.notna().any() else None,
            "spillover_to_direct_ratio_max": float(spill_ratio.max()) if spill_ratio.notna().any() else None,
            "interpretation": (
                "spillover_signal_present"
                if (
                    (table["model"] == "neighbor_adjusted").any()
                    and pd.to_numeric(
                        table.loc[table["model"] == "neighbor_adjusted", "spillover_p_value"],
                        errors="coerce",
                    ).iloc[0]
                    <= 0.05
                )
                else "spillover_signal_not_established"
            ),
            "note": (
                "This decomposition is a spatial sensitivity summary based on neighbor-average exposure models; "
                "it is not a formal causal interference identification result."
            ),
        }
    return table, summary


def run_spatial_exposure_mapping(
    features: pd.DataFrame,
    spec: StudySpec,
    graph: SpatialGraph,
    diagnostics: dict[str, object],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Map unit-level direct, indirect, and total effects implied by neighbor exposure.

    The mapping uses row-standardized neighbor exposure: each unit's exposure
    contributes `1 / degree(neighbor)` to each neighbor's neighbor-exposure term.
    """

    if graph.method == "unavailable" or spec.unit_id not in features.columns:
        rows = pd.DataFrame(
            columns=[
                "unit_id",
                "direct_effect",
                "indirect_effect",
                "total_effect",
                "out_neighbor_count",
                "incoming_weight_sum",
            ]
        )
        return rows, {
            "status": "skipped",
            "warning": "Spatial graph or unit ID is unavailable for exposure mapping.",
        }

    preferred_model = diagnostics.get("spatial_slx_model")
    model_name = "spatial_slx_model"
    if not isinstance(preferred_model, dict) or preferred_model.get("status") != "ok":
        preferred_model = diagnostics.get("spatial_lag_model")
        model_name = "spatial_lag_model"
    if not isinstance(preferred_model, dict) or preferred_model.get("status") != "ok":
        preferred_model = diagnostics.get("neighbor_exposure_model")
        model_name = "neighbor_exposure_model"
    if not isinstance(preferred_model, dict) or preferred_model.get("status") != "ok":
        rows = pd.DataFrame(
            columns=[
                "unit_id",
                "direct_effect",
                "indirect_effect",
                "total_effect",
                "out_neighbor_count",
                "incoming_weight_sum",
            ]
        )
        return rows, {
            "status": "skipped",
            "warning": "No usable neighbor-exposure model is available for exposure mapping.",
        }

    direct_coef = preferred_model.get("exposure_coef")
    spillover_coef = preferred_model.get("coef")
    try:
        direct = float(direct_coef)
        spillover = float(spillover_coef)
    except (TypeError, ValueError):
        rows = pd.DataFrame(
            columns=[
                "unit_id",
                "direct_effect",
                "indirect_effect",
                "total_effect",
                "out_neighbor_count",
                "incoming_weight_sum",
            ]
        )
        return rows, {
            "status": "skipped",
            "warning": "Direct or spillover coefficient is non-finite.",
        }

    incoming_weight_sum = np.zeros(len(features), dtype=float)
    for target_index, neighbor_indices in enumerate(graph.neighbors):
        degree = len(neighbor_indices)
        if degree == 0:
            continue
        weight = 1.0 / degree
        for source_index in neighbor_indices:
            if source_index < len(incoming_weight_sum):
                incoming_weight_sum[int(source_index)] += weight

    indirect = spillover * incoming_weight_sum
    total = direct + indirect
    unit_ids = features[spec.unit_id].astype(str).reset_index(drop=True)
    rows = pd.DataFrame(
        {
            "unit_id": unit_ids,
            "direct_effect": direct,
            "indirect_effect": indirect,
            "total_effect": total,
            "out_neighbor_count": [len(items) for items in graph.neighbors],
            "incoming_weight_sum": incoming_weight_sum,
        }
    )
    finite_indirect = rows["indirect_effect"].replace([np.inf, -np.inf], np.nan).dropna()
    finite_total = rows["total_effect"].replace([np.inf, -np.inf], np.nan).dropna()
    summary = {
        "status": "ok",
        "model": model_name,
        "direct_effect": direct,
        "spillover_coefficient": spillover,
        "mean_indirect_effect": float(finite_indirect.mean()) if not finite_indirect.empty else None,
        "median_indirect_effect": float(finite_indirect.median()) if not finite_indirect.empty else None,
        "mean_total_effect": float(finite_total.mean()) if not finite_total.empty else None,
        "median_total_effect": float(finite_total.median()) if not finite_total.empty else None,
        "indirect_effect_p10": float(finite_indirect.quantile(0.10)) if not finite_indirect.empty else None,
        "indirect_effect_p90": float(finite_indirect.quantile(0.90)) if not finite_indirect.empty else None,
        "incoming_weight_sum_mean": float(np.mean(incoming_weight_sum)) if len(incoming_weight_sum) else None,
        "incoming_weight_sum_min": float(np.min(incoming_weight_sum)) if len(incoming_weight_sum) else None,
        "incoming_weight_sum_max": float(np.max(incoming_weight_sum)) if len(incoming_weight_sum) else None,
        "interpretation": "exposure_mapping_sensitivity",
        "note": (
            "Effects are implied by the fitted neighbor-exposure model and row-standardized spatial graph. "
            "They are an exposure-mapping sensitivity analysis, not a fully identified network experiment."
        ),
    }
    return rows, summary


def run_spatial_diagnostics(
    features: pd.DataFrame,
    spec: StudySpec,
    paths: SCCAPaths,
    *,
    source_frame: Any | None = None,
    baseline_exposure_coef: float | None = None,
    n_permutations: int = 99,
    random_state: int = 0,
) -> dict[str, object]:
    """Write spatial graph, residual autocorrelation, and neighbor-exposure diagnostics."""

    paths.ensure()
    analysis_features = features.reset_index(drop=True).copy()
    graph = _build_spatial_graph(analysis_features, spec, source_frame)
    residuals, residual_model = _main_model_residuals(analysis_features, spec)
    graph_sensitivity_rows, graph_sensitivity_summary = run_spatial_graph_sensitivity(
        analysis_features,
        spec,
        source_frame=source_frame,
        baseline_exposure_coef=baseline_exposure_coef,
        n_permutations=max(9, min(n_permutations, 19)),
        random_state=random_state + 100,
    )
    diagnostics: dict[str, object] = {
        "status": "skipped" if graph.method == "unavailable" else "ok",
        "graph": _graph_summary(graph),
        "residual_model": residual_model,
        "exposure_moran": _moran_summary(
            analysis_features[spec.exposure] if spec.exposure in analysis_features.columns else pd.Series(dtype=float),
            graph,
            n_permutations=n_permutations,
            random_state=random_state,
        ),
        "residual_moran": _moran_summary(
            residuals,
            graph,
            n_permutations=n_permutations,
            random_state=random_state + 1,
        ),
        "neighbor_exposure_model": _neighbor_exposure_model(
            analysis_features,
            spec,
            graph,
            baseline_exposure_coef=baseline_exposure_coef,
        ),
        "spatial_lag_model": _spatial_lag_model(
            analysis_features,
            spec,
            graph,
            baseline_exposure_coef=baseline_exposure_coef,
        ),
        "graph_sensitivity_summary": graph_sensitivity_summary,
    }
    slx_rows, slx_summary = run_spatial_slx_summary(
        analysis_features,
        spec,
        graph,
        baseline_exposure_coef=baseline_exposure_coef,
    )
    diagnostics["spatial_slx_model"] = slx_summary
    spillover_rows, spillover_summary = run_spatial_spillover_decomposition(
        diagnostics,
        graph_sensitivity_rows,
    )
    exposure_mapping_rows, exposure_mapping_summary = run_spatial_exposure_mapping(
        analysis_features,
        spec,
        graph,
        diagnostics,
    )
    diagnostics["spillover_summary"] = spillover_summary
    diagnostics["exposure_mapping_summary"] = exposure_mapping_summary
    diagnostics["flags"] = _diagnostic_flags(diagnostics)
    if diagnostics["flags"]:
        diagnostics["interpretation"] = "spatial_caution"
    elif graph.method == "unavailable":
        diagnostics["interpretation"] = "not_estimable"
    else:
        diagnostics["interpretation"] = "no_material_spatial_warning"

    graph_sensitivity_rows.to_csv(paths.spatial_graph_sensitivity, index=False)
    paths.spatial_graph_sensitivity_summary.write_text(
        json.dumps(_json_ready(graph_sensitivity_summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    slx_rows.to_csv(paths.spatial_slx_estimates, index=False)
    paths.spatial_slx_summary.write_text(
        json.dumps(_json_ready(slx_summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    spillover_rows.to_csv(paths.spatial_spillover_decomposition, index=False)
    paths.spatial_spillover_summary.write_text(
        json.dumps(_json_ready(spillover_summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    exposure_mapping_rows.to_csv(paths.spatial_exposure_mapping, index=False)
    paths.spatial_exposure_mapping_summary.write_text(
        json.dumps(_json_ready(exposure_mapping_summary), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    paths.spatial_diagnostics.write_text(
        json.dumps(_json_ready(diagnostics), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return diagnostics


def append_spatial_adjusted_estimate(
    paths: SCCAPaths,
    diagnostics: dict[str, object],
    *,
    estimator_name: str = "spatial_neighbor_adjusted_ols",
) -> dict[str, object] | None:
    """Append the neighbor-exposure-adjusted main coefficient as a formal estimate."""

    neighbor = diagnostics.get("neighbor_exposure_model")
    if not isinstance(neighbor, dict) or neighbor.get("status") != "ok":
        return None

    exposure_coef = neighbor.get("exposure_coef")
    if not isinstance(exposure_coef, (int, float)) or not np.isfinite(float(exposure_coef)):
        return None

    row = {
        "estimator": estimator_name,
        "status": "ok",
        "coef": float(exposure_coef),
        "se": np.nan,
        "p_value": np.nan,
        "ci_lower": np.nan,
        "ci_upper": np.nan,
        "r_squared": neighbor.get("r_squared"),
        "n": neighbor.get("n"),
        "complete_n": neighbor.get("n"),
        "dropped_n": 0,
        "warnings": [],
        "neighbor_exposure_coef": neighbor.get("coef"),
        "neighbor_exposure_p_value": neighbor.get("p_value"),
    }
    sensitivity = neighbor.get("spatial_adjustment_sensitivity")
    if isinstance(sensitivity, dict):
        row.update(
            {
                "baseline_exposure_coef": sensitivity.get("baseline_exposure_coef"),
                "coef_delta": sensitivity.get("coef_delta"),
                "relative_change": sensitivity.get("relative_change"),
                "sign_stable": sensitivity.get("sign_stable"),
            }
        )

    if paths.effect_estimates.exists():
        estimates = pd.read_csv(paths.effect_estimates)
        estimates = estimates.loc[estimates["estimator"].astype(str) != estimator_name].copy()
    else:
        estimates = pd.DataFrame()
    estimates = pd.concat([estimates, pd.DataFrame([row])], ignore_index=True)
    estimates.to_csv(paths.effect_estimates, index=False)

    diagnostics_payload: dict[str, object] = {}
    if paths.model_diagnostics.exists():
        try:
            loaded = json.loads(paths.model_diagnostics.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                diagnostics_payload = loaded
        except (OSError, json.JSONDecodeError):
            diagnostics_payload = {}
    estimators = diagnostics_payload.setdefault("estimators", {})
    if isinstance(estimators, dict):
        estimators[estimator_name] = {
            "status": "ok",
            "n": int(row["n"]) if isinstance(row.get("n"), (int, float)) else 0,
            "complete_n": int(row["complete_n"]) if isinstance(row.get("complete_n"), (int, float)) else 0,
            "dropped_n": 0,
            "warnings": [],
            "neighbor_exposure_coef": row.get("neighbor_exposure_coef"),
            "neighbor_exposure_p_value": row.get("neighbor_exposure_p_value"),
            "spatial_adjustment_sensitivity": sensitivity if isinstance(sensitivity, dict) else {},
        }
    diagnostics_payload["spatial_adjusted_estimator"] = estimator_name
    paths.model_diagnostics.write_text(
        json.dumps(_json_ready(diagnostics_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return row


def append_spatial_lag_adjusted_estimate(
    paths: SCCAPaths,
    diagnostics: dict[str, object],
    *,
    estimator_name: str = "spatial_lag_adjusted_ols",
) -> dict[str, object] | None:
    """Append the main coefficient from the richer spatial lag adjustment."""

    lag_model = diagnostics.get("spatial_lag_model")
    if not isinstance(lag_model, dict) or lag_model.get("status") != "ok":
        return None

    exposure_coef = lag_model.get("exposure_coef")
    if not isinstance(exposure_coef, (int, float)) or not np.isfinite(float(exposure_coef)):
        return None

    row = {
        "estimator": estimator_name,
        "status": "ok",
        "coef": float(exposure_coef),
        "se": np.nan,
        "p_value": np.nan,
        "ci_lower": np.nan,
        "ci_upper": np.nan,
        "r_squared": lag_model.get("r_squared"),
        "n": lag_model.get("n"),
        "complete_n": lag_model.get("n"),
        "dropped_n": 0,
        "warnings": [],
        "neighbor_exposure_coef": lag_model.get("coef"),
        "neighbor_exposure_p_value": lag_model.get("p_value"),
        "lag_covariate_count": lag_model.get("lag_covariate_count"),
        "lag_covariates_significant": lag_model.get("lag_covariates_significant"),
    }
    sensitivity = lag_model.get("spatial_adjustment_sensitivity")
    if isinstance(sensitivity, dict):
        row.update(
            {
                "baseline_exposure_coef": sensitivity.get("baseline_exposure_coef"),
                "coef_delta": sensitivity.get("coef_delta"),
                "relative_change": sensitivity.get("relative_change"),
                "sign_stable": sensitivity.get("sign_stable"),
            }
        )

    if paths.effect_estimates.exists():
        estimates = pd.read_csv(paths.effect_estimates)
        estimates = estimates.loc[estimates["estimator"].astype(str) != estimator_name].copy()
    else:
        estimates = pd.DataFrame()
    estimates = pd.concat([estimates, pd.DataFrame([row])], ignore_index=True)
    estimates.to_csv(paths.effect_estimates, index=False)

    diagnostics_payload: dict[str, object] = {}
    if paths.model_diagnostics.exists():
        try:
            loaded = json.loads(paths.model_diagnostics.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                diagnostics_payload = loaded
        except (OSError, json.JSONDecodeError):
            diagnostics_payload = {}
    estimators = diagnostics_payload.setdefault("estimators", {})
    if isinstance(estimators, dict):
        estimators[estimator_name] = {
            "status": "ok",
            "n": int(row["n"]) if isinstance(row.get("n"), (int, float)) else 0,
            "complete_n": int(row["complete_n"]) if isinstance(row.get("complete_n"), (int, float)) else 0,
            "dropped_n": 0,
            "warnings": [],
            "neighbor_exposure_coef": row.get("neighbor_exposure_coef"),
            "neighbor_exposure_p_value": row.get("neighbor_exposure_p_value"),
            "lag_covariate_count": row.get("lag_covariate_count"),
            "lag_covariates_significant": row.get("lag_covariates_significant"),
            "spatial_adjustment_sensitivity": sensitivity if isinstance(sensitivity, dict) else {},
        }
    paths.model_diagnostics.write_text(
        json.dumps(_json_ready(diagnostics_payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return row


def _spatial_block_groups(
    features: pd.DataFrame,
    spec: StudySpec,
    source_frame: Any | None,
    *,
    bins: int = 4,
) -> pd.Series | None:
    def _quantile_bins(values: pd.Series) -> pd.Series | None:
        clean = values.dropna()
        if len(clean) < 2 or clean.nunique() < 2:
            return None
        q = max(2, min(int(bins), int(clean.nunique()), len(clean)))
        try:
            result = pd.qcut(clean, q=q, duplicates="drop")
        except ValueError:
            ranks = clean.rank(method="first")
            try:
                result = pd.qcut(ranks, q=q, duplicates="drop")
            except ValueError:
                return None
        labels = result.astype(str)
        if labels.nunique(dropna=True) < 2:
            return None
        return labels

    coordinates = spatial_coordinates(features, spec, source_frame)
    if coordinates is None:
        return None
    x = pd.Series(coordinates[:, 0], index=features.index, dtype=float)
    y = pd.Series(coordinates[:, 1], index=features.index, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    if int(finite.sum()) < 2:
        return None

    x_bins = _quantile_bins(x[finite])
    y_bins = _quantile_bins(y[finite])
    groups = pd.Series(np.nan, index=features.index, dtype=object)
    if x_bins is not None and y_bins is not None:
        groups.loc[finite] = x_bins.astype(str) + "|" + y_bins.astype(str)
    elif x_bins is not None:
        groups.loc[finite] = "x|" + x_bins.astype(str)
    elif y_bins is not None:
        groups.loc[finite] = "y|" + y_bins.astype(str)
    else:
        return None
    return groups


def run_spatial_block_bootstrap(
    features: pd.DataFrame,
    spec: StudySpec,
    graph: SpatialGraph,
    *,
    source_frame: Any | None = None,
    baseline_exposure_coef: float | None = None,
    n_replicates: int = 100,
    bins: int = 4,
    random_state: int = 0,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Bootstrap the spatial neighbor-adjusted estimator by resampling spatial blocks."""

    block_groups = _spatial_block_groups(features, spec, source_frame, bins=bins)
    if graph.method == "unavailable" or block_groups is None:
        rows = pd.DataFrame(
            columns=[
                "replicate",
                "block_type",
                "coef",
                "neighbor_exposure_coef",
                "n",
                "status",
            ]
        )
        return rows, {
            "status": "skipped",
            "n_replicates_requested": int(n_replicates),
            "n_replicates_valid": 0,
            "failure_count": int(n_replicates),
            "warning": "Spatial blocks could not be constructed.",
        }

    unique_blocks = block_groups.dropna().astype(str).unique()
    if len(unique_blocks) < 2:
        rows = pd.DataFrame(
            columns=[
                "replicate",
                "block_type",
                "coef",
                "neighbor_exposure_coef",
                "n",
                "status",
            ]
        )
        return rows, {
            "status": "skipped",
            "n_replicates_requested": int(n_replicates),
            "n_replicates_valid": 0,
            "failure_count": int(n_replicates),
            "warning": "Fewer than two spatial blocks were available.",
        }

    rng = np.random.default_rng(random_state)
    bootstrap_spec = spec
    working = features.reset_index(drop=True).copy()
    working["_gc_spatial_block"] = block_groups.reset_index(drop=True).astype(str)
    coordinates = spatial_coordinates(features, spec, source_frame)
    if coordinates is not None and len(coordinates) == len(working):
        x_col = "_gc_bootstrap_x"
        y_col = "_gc_bootstrap_y"
        working[x_col] = coordinates[:, 0]
        working[y_col] = coordinates[:, 1]
        bootstrap_spec = replace(spec, coordinate_columns=(x_col, y_col))
    rows: list[dict[str, object]] = []
    for replicate in range(n_replicates):
        sampled = rng.choice(unique_blocks, size=len(unique_blocks), replace=True)
        parts = [
            working.loc[working["_gc_spatial_block"] == block].copy()
            for block in sampled
        ]
        sample = pd.concat(parts, ignore_index=True) if parts else working.iloc[0:0].copy()
        sample_graph = build_spatial_graph(sample, bootstrap_spec, None)
        diagnostics = {
            "neighbor_exposure_model": _neighbor_exposure_model(
                sample,
                bootstrap_spec,
                sample_graph,
                baseline_exposure_coef=baseline_exposure_coef,
            )
        }
        neighbor = diagnostics["neighbor_exposure_model"]
        rows.append(
            {
                "replicate": replicate,
                "block_type": "quantile_grid",
                "coef": neighbor.get("exposure_coef") if isinstance(neighbor, dict) else None,
                "neighbor_exposure_coef": neighbor.get("coef") if isinstance(neighbor, dict) else None,
                "n": neighbor.get("n") if isinstance(neighbor, dict) else 0,
                "status": neighbor.get("status") if isinstance(neighbor, dict) else "skipped",
                "graph_method": sample_graph.method,
                "warning": neighbor.get("warning") if isinstance(neighbor, dict) else None,
            }
        )

    results = pd.DataFrame(rows)
    coefs = pd.to_numeric(results["coef"], errors="coerce")
    finite = coefs[np.isfinite(coefs)]
    summary: dict[str, object]
    if finite.empty:
        summary = {
            "status": "skipped",
            "n_replicates_requested": int(n_replicates),
            "n_replicates_valid": 0,
            "failure_count": int(n_replicates),
        }
    else:
        signs = np.sign(finite)
        nonzero = signs[signs != 0]
        sign_stability = 1.0 if nonzero.empty else float((nonzero == nonzero.mode().iloc[0]).mean())
        summary = {
            "status": "ok",
            "n_replicates_requested": int(n_replicates),
            "n_replicates_valid": int(len(finite)),
            "failure_count": int(n_replicates - len(finite)),
            "coef_mean": float(finite.mean()),
            "coef_median": float(finite.median()),
            "coef_std": float(finite.std(ddof=1)) if len(finite) > 1 else 0.0,
            "ci_lower_2_5": float(finite.quantile(0.025)),
            "ci_upper_97_5": float(finite.quantile(0.975)),
            "sign_stability": sign_stability,
        }
    return results, summary
