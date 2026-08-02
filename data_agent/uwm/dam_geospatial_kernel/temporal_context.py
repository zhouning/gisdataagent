"""Evidence-gated temporal context contract shared by GWM domain adapters."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
import torch

from .contracts import DAMGKBatch


GWM_TEMPORAL_CONTEXT_SCHEMA = "gwm.geospatial_kernel.temporal_context.v1"
GWM_MASKED_TEMPORAL_CONTEXT_SCHEMA = (
    "gwm.geospatial_kernel.masked_temporal_context.v1"
)
GWM_TEMPORAL_CONTEXT_COLUMNS = (
    "node_key",
    "forecast_origin",
    "step_index",
    "feature_name",
    "value",
    "valid_time",
    "available_at",
    "evidence_class",
    "admission_status",
    "source_id",
    "source_artifact_sha256",
)
GWM_TEMPORAL_CONTEXT_EVIDENCE_CLASSES = {
    "observed",
    "derived_observed",
    "forecast",
}
GWM_EXPLICIT_MISSING_REASONS = {
    "source_object_absent",
    "source_value_fill_or_nonfinite",
    "unavailable_at_forecast_origin",
    "quality_control_rejected",
}
GWM_MASKED_TEMPORAL_CONTEXT_COLUMNS = (
    *GWM_TEMPORAL_CONTEXT_COLUMNS,
    "observation_status",
    "missing_reason",
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class GWMTemporalContextCompilation:
    """A model-ready context tensor plus its fail-closed evidence audit."""

    schema: str
    feature_names: tuple[str, ...]
    node_keys: tuple[str, ...]
    forecast_origins: tuple[pd.Timestamp, ...]
    tensor: torch.Tensor
    audit: dict[str, Any]

    @property
    def node_count(self) -> int:
        return len(self.node_keys)

    @property
    def horizon(self) -> int:
        return int(self.tensor.shape[1])

    @property
    def context_dim(self) -> int:
        return len(self.feature_names)


def compile_gwm_temporal_context(
    records: pd.DataFrame,
    *,
    node_keys: Sequence[str],
    forecast_origins: Sequence[str | pd.Timestamp],
    horizon: int,
    feature_names: Iterable[str],
) -> GWMTemporalContextCompilation:
    """Compile a complete node/step/feature grid without temporal leakage.

    Observed and derived-observed values must be valid no later than the
    forecast origin. Forecast values may have a future valid time, but their
    publication time must still be no later than the forecast origin.
    """

    ordered_nodes = tuple(str(value) for value in node_keys)
    ordered_features = tuple(str(value) for value in feature_names)
    if horizon <= 0:
        raise ValueError("temporal_context_horizon_must_be_positive")
    if not ordered_nodes or len(set(ordered_nodes)) != len(ordered_nodes):
        raise ValueError("temporal_context_node_keys_must_be_unique")
    if not ordered_features or len(set(ordered_features)) != len(ordered_features):
        raise ValueError("temporal_context_feature_names_must_be_unique")
    if len(forecast_origins) != len(ordered_nodes):
        raise ValueError("temporal_context_forecast_origin_count_mismatch")

    origins = tuple(_utc_timestamp(value) for value in forecast_origins)
    missing_columns = sorted(set(GWM_TEMPORAL_CONTEXT_COLUMNS) - set(records.columns))
    if missing_columns:
        raise ValueError(
            "temporal_context_missing_columns:" + ",".join(missing_columns)
        )
    frame = records.loc[:, GWM_TEMPORAL_CONTEXT_COLUMNS].copy()
    if frame.empty:
        raise ValueError("temporal_context_records_empty")

    frame["node_key"] = frame["node_key"].astype(str)
    frame["feature_name"] = frame["feature_name"].astype(str)
    frame["step_index"] = pd.to_numeric(frame["step_index"], errors="raise")
    if (frame["step_index"] % 1 != 0).any():
        raise ValueError("temporal_context_step_index_must_be_integer")
    frame["step_index"] = frame["step_index"].astype(int)
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    for column in ("forecast_origin", "valid_time", "available_at"):
        frame[column] = _timezone_aware_utc_series(frame[column], column=column)

    expected_origins = dict(zip(ordered_nodes, origins, strict=True))
    _reject_unrequested_values(frame, "node_key", set(ordered_nodes))
    _reject_unrequested_values(frame, "feature_name", set(ordered_features))
    if not frame["step_index"].between(0, horizon - 1).all():
        raise ValueError("temporal_context_step_index_out_of_range")
    expected_origin_series = frame["node_key"].map(expected_origins)
    if not frame["forecast_origin"].equals(expected_origin_series):
        raise ValueError("temporal_context_forecast_origin_mismatch")

    key_columns = ["node_key", "step_index", "feature_name"]
    if frame.duplicated(key_columns).any():
        raise ValueError("temporal_context_duplicate_node_step_feature")
    expected_index = pd.MultiIndex.from_product(
        [ordered_nodes, range(horizon), ordered_features], names=key_columns
    )
    actual_index = pd.MultiIndex.from_frame(frame[key_columns])
    missing_index = expected_index.difference(actual_index)
    if len(missing_index):
        raise ValueError(
            f"temporal_context_incomplete_grid:missing={len(missing_index)}"
        )
    if not np.isfinite(frame["value"].to_numpy(dtype=float)).all():
        raise ValueError("temporal_context_value_must_be_finite")

    evidence = set(frame["evidence_class"].astype(str))
    unsupported = sorted(evidence - GWM_TEMPORAL_CONTEXT_EVIDENCE_CLASSES)
    if unsupported:
        raise ValueError(
            "temporal_context_unsupported_evidence_class:" + ",".join(unsupported)
        )
    if not frame["admission_status"].astype(str).eq("admitted").all():
        raise ValueError("temporal_context_contains_unadmitted_record")
    if (
        frame["source_id"].isna().any()
        or frame["source_id"].astype(str).str.strip().eq("").any()
    ):
        raise ValueError("temporal_context_source_id_required")
    hashes = frame["source_artifact_sha256"].astype(str)
    if not hashes.map(lambda value: bool(_SHA256.fullmatch(value))).all():
        raise ValueError("temporal_context_source_sha256_required")
    if (frame["available_at"] > frame["forecast_origin"]).any():
        raise ValueError("temporal_context_publication_time_leakage")

    observed = frame["evidence_class"].isin({"observed", "derived_observed"})
    if (
        frame.loc[observed, "valid_time"]
        > frame.loc[observed, "forecast_origin"]
    ).any():
        raise ValueError("temporal_context_observation_time_leakage")
    forecast = frame["evidence_class"].eq("forecast")
    if (
        frame.loc[forecast, "valid_time"]
        < frame.loc[forecast, "forecast_origin"]
    ).any():
        raise ValueError("temporal_context_forecast_valid_before_origin")

    ordered = frame.set_index(key_columns).loc[expected_index].reset_index()
    values = ordered["value"].to_numpy(dtype=np.float32).reshape(
        len(ordered_nodes), horizon, len(ordered_features)
    )
    source_pairs = ordered[["source_id", "source_artifact_sha256"]].drop_duplicates()
    audit = {
        "record_count": len(ordered),
        "node_count": len(ordered_nodes),
        "horizon": horizon,
        "feature_count": len(ordered_features),
        "complete_grid": True,
        "publication_time_leakage_count": 0,
        "observation_time_leakage_count": 0,
        "unadmitted_record_count": 0,
        "source_artifact_count": len(source_pairs),
        "evidence_class_counts": {
            str(key): int(value)
            for key, value in ordered["evidence_class"].value_counts().sort_index().items()
        },
        "claim_boundary": {
            "model_input_admitted": True,
            "causal_effect_identified": False,
            "general_gwm_validated": False,
        },
    }
    return GWMTemporalContextCompilation(
        schema=GWM_TEMPORAL_CONTEXT_SCHEMA,
        feature_names=ordered_features,
        node_keys=ordered_nodes,
        forecast_origins=origins,
        tensor=torch.from_numpy(values),
        audit=audit,
    )


def compile_gwm_masked_temporal_context(
    records: pd.DataFrame,
    *,
    node_keys: Sequence[str],
    forecast_origins: Sequence[str | pd.Timestamp],
    horizon: int,
    feature_names: Iterable[str],
    normalizer_artifact_sha256: str,
    missingness_contract_sha256: str,
) -> GWMTemporalContextCompilation:
    """Compile normalized values with explicit missingness model channels.

    Missing raw values must already have passed the masked normalizer. Their
    normalized value is the training mean (zero), accompanied by a zero
    observed mask and unit imputation uncertainty. No interpolation occurs.
    """

    ordered_features = tuple(str(value) for value in feature_names)
    if not ordered_features or len(set(ordered_features)) != len(ordered_features):
        raise ValueError("masked_temporal_context_feature_names_must_be_unique")
    if any(
        feature.endswith(
            ("__observed_mask", "__imputation_uncertainty")
        )
        for feature in ordered_features
    ):
        raise ValueError("masked_temporal_context_feature_name_reserved")
    if not _SHA256.fullmatch(str(normalizer_artifact_sha256)):
        raise ValueError("masked_temporal_context_normalizer_sha256_required")
    if not _SHA256.fullmatch(str(missingness_contract_sha256)):
        raise ValueError("masked_temporal_context_missingness_sha256_required")
    missing_columns = sorted(
        set(GWM_MASKED_TEMPORAL_CONTEXT_COLUMNS) - set(records.columns)
    )
    if missing_columns:
        raise ValueError(
            "masked_temporal_context_missing_columns:" + ",".join(missing_columns)
        )
    frame = records.loc[:, GWM_MASKED_TEMPORAL_CONTEXT_COLUMNS].copy()
    if frame.empty:
        raise ValueError("masked_temporal_context_records_empty")
    frame["feature_name"] = frame["feature_name"].astype(str)
    unexpected_features = sorted(
        set(frame["feature_name"]) - set(ordered_features)
    )
    if unexpected_features:
        raise ValueError(
            "masked_temporal_context_unrequested_features:"
            + ",".join(unexpected_features)
        )
    statuses = frame["observation_status"].astype(str)
    unsupported_statuses = sorted(set(statuses) - {"present", "missing"})
    if unsupported_statuses:
        raise ValueError(
            "masked_temporal_context_status_unsupported:"
            + ",".join(unsupported_statuses)
        )
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if not np.isfinite(frame["value"].to_numpy(dtype=float)).all():
        raise ValueError("masked_temporal_context_value_must_be_finite")
    missing = statuses.eq("missing")
    if not frame.loc[missing, "value"].eq(0.0).all():
        raise ValueError("masked_temporal_context_missing_value_must_be_zero")
    reasons = frame["missing_reason"].fillna("").astype(str).str.strip()
    invalid_missing_reasons = sorted(
        set(reasons.loc[missing]) - GWM_EXPLICIT_MISSING_REASONS
    )
    if invalid_missing_reasons or reasons.loc[missing].eq("").any():
        raise ValueError("masked_temporal_context_missing_reason_invalid")
    if reasons.loc[~missing].ne("").any():
        raise ValueError("masked_temporal_context_present_reason_must_be_empty")

    expanded_features = tuple(
        channel
        for feature in ordered_features
        for channel in (
            feature,
            f"{feature}__observed_mask",
            f"{feature}__imputation_uncertainty",
        )
    )
    expanded_rows = []
    for row in frame.to_dict(orient="records"):
        is_present = row["observation_status"] == "present"
        for channel, value in (
            (row["feature_name"], row["value"]),
            (f"{row['feature_name']}__observed_mask", float(is_present)),
            (
                f"{row['feature_name']}__imputation_uncertainty",
                float(not is_present),
            ),
        ):
            expanded_rows.append(
                {
                    **{
                        column: row[column]
                        for column in GWM_TEMPORAL_CONTEXT_COLUMNS
                    },
                    "feature_name": channel,
                    "value": value,
                }
            )
    compilation = compile_gwm_temporal_context(
        pd.DataFrame(expanded_rows),
        node_keys=node_keys,
        forecast_origins=forecast_origins,
        horizon=horizon,
        feature_names=expanded_features,
    )
    audit = {
        **compilation.audit,
        "base_feature_count": len(ordered_features),
        "base_feature_names": list(ordered_features),
        "input_record_count": len(frame),
        "explicit_missing_record_count": int(missing.sum()),
        "present_record_count": int((~missing).sum()),
        "missing_value_fill": "training_mean_normalized_zero",
        "observed_mask_emitted": True,
        "imputation_uncertainty_emitted": True,
        "interpolation_or_forward_fill_used": False,
        "normalizer_artifact_sha256": str(normalizer_artifact_sha256),
        "missingness_contract_sha256": str(missingness_contract_sha256),
        "claim_boundary": {
            **compilation.audit["claim_boundary"],
            "missing_values_observed": False,
            "missing_values_interpolated": False,
        },
    }
    return GWMTemporalContextCompilation(
        schema=GWM_MASKED_TEMPORAL_CONTEXT_SCHEMA,
        feature_names=expanded_features,
        node_keys=compilation.node_keys,
        forecast_origins=compilation.forecast_origins,
        tensor=compilation.tensor,
        audit=audit,
    )


def attach_gwm_temporal_context(
    batch: DAMGKBatch,
    compilation: GWMTemporalContextCompilation,
    *,
    append: bool = True,
) -> DAMGKBatch:
    """Attach compiled time-varying context while preserving all batch fields."""

    node_count = batch.node_state.shape[0]
    if compilation.node_count != node_count:
        raise ValueError("temporal_context_node_count_mismatch")
    context_by_step = compilation.tensor.to(
        dtype=batch.node_state.dtype, device=batch.node_state.device
    )
    if append:
        base = batch.node_context_by_step
        if base is None and batch.node_context is not None:
            base = batch.node_context.unsqueeze(1).expand(
                -1, compilation.horizon, -1
            )
        if base is not None:
            if base.shape[:2] != context_by_step.shape[:2]:
                raise ValueError("temporal_context_append_shape_mismatch")
            context_by_step = torch.cat([base, context_by_step], dim=-1)
    return replace(
        batch,
        node_context=context_by_step[:, 0],
        node_context_by_step=context_by_step,
    )


def _utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("temporal_context_forecast_origin_required")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("temporal_context_forecast_origin_timezone_required")
    return timestamp.tz_convert("UTC")


def _timezone_aware_utc_series(
    values: pd.Series, *, column: str
) -> pd.Series:
    try:
        timestamps = [pd.Timestamp(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("temporal_context_timestamp_invalid:" + column) from exc
    if any(pd.isna(value) for value in timestamps):
        raise ValueError("temporal_context_timestamps_required")
    if any(
        value.tzinfo is None or value.utcoffset() is None
        for value in timestamps
    ):
        raise ValueError(
            "temporal_context_timestamp_timezone_required:" + column
        )
    return pd.Series(
        pd.to_datetime(timestamps, errors="raise", utc=True),
        index=values.index,
        name=values.name,
    )


def _reject_unrequested_values(
    frame: pd.DataFrame, column: str, allowed: set[str]
) -> None:
    unexpected = sorted(set(frame[column]) - allowed)
    if unexpected:
        raise ValueError(
            f"temporal_context_unrequested_{column}:" + ",".join(unexpected)
        )
