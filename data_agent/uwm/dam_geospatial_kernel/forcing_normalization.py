"""Training-only split and normalization contracts for GWM forcing inputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .temporal_context import GWM_EXPLICIT_MISSING_REASONS


GWM_FORCING_SPLIT_SCHEMA = "gwm.geospatial_kernel.forcing_split_contract.v1"
GWM_FORCING_MISSINGNESS_SCHEMA = (
    "gwm.geospatial_kernel.forcing_missingness_contract.v1"
)
GWM_FORCING_MISSING_LEDGER_SCHEMA = (
    "gwm.geospatial_kernel.forcing_missing_ledger.v1"
)
GWM_FORCING_NORMALIZER_SCHEMA = (
    "gwm.geospatial_kernel.forcing_normalizer.v1"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"contract_sha256", "artifact_sha256"}
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_timestamp(value: str | pd.Timestamp, *, field: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"forcing_split_{field}_required")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"forcing_split_{field}_timezone_required")
    return timestamp.tz_convert("UTC")


@dataclass(frozen=True)
class GWMForcingSplitContract:
    contract_id: str
    feature_names: tuple[str, ...]
    entity_columns: tuple[str, ...]
    train_start: pd.Timestamp
    train_end_exclusive: pd.Timestamp
    evaluation_start: pd.Timestamp
    evaluation_end_exclusive: pd.Timestamp
    expected_frequency: str
    normalization_scope: str
    split_time_semantics: str = "forecast_origin"
    source_artifacts: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("forcing_split_contract_id_required")
        if not self.feature_names or len(set(self.feature_names)) != len(
            self.feature_names
        ):
            raise ValueError("forcing_split_feature_names_must_be_unique")
        if not self.entity_columns or len(set(self.entity_columns)) != len(
            self.entity_columns
        ):
            raise ValueError("forcing_split_entity_columns_must_be_unique")
        for field in (
            "train_start",
            "train_end_exclusive",
            "evaluation_start",
            "evaluation_end_exclusive",
        ):
            object.__setattr__(
                self,
                field,
                _utc_timestamp(getattr(self, field), field=field),
            )
        if self.train_start >= self.train_end_exclusive:
            raise ValueError("forcing_split_training_interval_invalid")
        if self.evaluation_start >= self.evaluation_end_exclusive:
            raise ValueError("forcing_split_evaluation_interval_invalid")
        if self.train_end_exclusive > self.evaluation_start:
            raise ValueError("forcing_split_training_evaluation_overlap")
        if self.normalization_scope != "per_entity_feature":
            raise ValueError("forcing_split_normalization_scope_unsupported")
        if self.split_time_semantics != "forecast_origin":
            raise ValueError("forcing_split_time_semantics_unsupported")
        if not self.expected_frequency.strip():
            raise ValueError("forcing_split_expected_frequency_required")
        for name, path, digest in self.source_artifacts:
            if not name or not path or not _SHA256.fullmatch(digest):
                raise ValueError("forcing_split_source_artifact_invalid")

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema": GWM_FORCING_SPLIT_SCHEMA,
            "contract_id": self.contract_id,
            "feature_names": list(self.feature_names),
            "entity_columns": list(self.entity_columns),
            "train_interval": {
                "start_inclusive": self.train_start.isoformat().replace(
                    "+00:00", "Z"
                ),
                "end_exclusive": self.train_end_exclusive.isoformat().replace(
                    "+00:00", "Z"
                ),
            },
            "evaluation_interval": {
                "start_inclusive": self.evaluation_start.isoformat().replace(
                    "+00:00", "Z"
                ),
                "end_exclusive": self.evaluation_end_exclusive.isoformat().replace(
                    "+00:00", "Z"
                ),
            },
            "expected_frequency": self.expected_frequency,
            "normalization_scope": self.normalization_scope,
            "split_time_semantics": self.split_time_semantics,
            "fit_policy": "training_rows_only_evaluation_values_never_read",
            "source_artifacts": [
                {"name": name, "path": path, "sha256": digest}
                for name, path, digest in self.source_artifacts
            ],
        }
        payload["contract_sha256"] = _canonical_sha256(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> GWMForcingSplitContract:
        if payload.get("schema") != GWM_FORCING_SPLIT_SCHEMA:
            raise ValueError("forcing_split_schema_mismatch")
        if payload.get("contract_sha256") != _canonical_sha256(payload):
            raise ValueError("forcing_split_contract_hash_mismatch")
        if payload.get("fit_policy") != (
            "training_rows_only_evaluation_values_never_read"
        ):
            raise ValueError("forcing_split_fit_policy_mismatch")
        train = payload["train_interval"]
        evaluation = payload["evaluation_interval"]
        return cls(
            contract_id=str(payload["contract_id"]),
            feature_names=tuple(str(value) for value in payload["feature_names"]),
            entity_columns=tuple(str(value) for value in payload["entity_columns"]),
            train_start=pd.Timestamp(train["start_inclusive"]),
            train_end_exclusive=pd.Timestamp(train["end_exclusive"]),
            evaluation_start=pd.Timestamp(evaluation["start_inclusive"]),
            evaluation_end_exclusive=pd.Timestamp(evaluation["end_exclusive"]),
            expected_frequency=str(payload["expected_frequency"]),
            normalization_scope=str(payload["normalization_scope"]),
            split_time_semantics=str(payload["split_time_semantics"]),
            source_artifacts=tuple(
                (str(row["name"]), str(row["path"]), str(row["sha256"]))
                for row in payload.get("source_artifacts", ())
            ),
        )


@dataclass(frozen=True)
class GWMForcingMissingnessContract:
    """Frozen policy for explicit, non-interpolated forcing gaps."""

    contract_id: str
    feature_names: tuple[str, ...]
    missing_reasons: tuple[str, ...]
    source_artifacts: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("forcing_missingness_contract_id_required")
        if not self.feature_names or len(set(self.feature_names)) != len(
            self.feature_names
        ):
            raise ValueError("forcing_missingness_feature_names_must_be_unique")
        if not self.missing_reasons or len(set(self.missing_reasons)) != len(
            self.missing_reasons
        ):
            raise ValueError("forcing_missingness_reasons_must_be_unique")
        unsupported = sorted(
            set(self.missing_reasons) - GWM_EXPLICIT_MISSING_REASONS
        )
        if unsupported:
            raise ValueError(
                "forcing_missingness_reasons_unsupported:" + ",".join(unsupported)
            )
        for name, path, digest in self.source_artifacts:
            if not name or not path or not _SHA256.fullmatch(digest):
                raise ValueError("forcing_missingness_source_artifact_invalid")

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema": GWM_FORCING_MISSINGNESS_SCHEMA,
            "contract_id": self.contract_id,
            "feature_names": list(self.feature_names),
            "observation_status_values": ["present", "missing"],
            "missing_reasons": list(self.missing_reasons),
            "raw_missing_value_policy": "null_required_zero_forbidden",
            "normalized_missing_value_policy": "training_mean_zscore_zero",
            "model_channels_per_feature": [
                "normalized_value",
                "observed_mask",
                "imputation_uncertainty",
            ],
            "channel_values": {
                "present": {
                    "observed_mask": 1.0,
                    "imputation_uncertainty": 0.0,
                },
                "missing": {
                    "observed_mask": 0.0,
                    "imputation_uncertainty": 1.0,
                },
            },
            "imputation_uncertainty_semantics": (
                "structural_missingness_indicator_not_calibrated_variance"
            ),
            "interpolation_or_forward_fill_allowed": False,
            "fit_policy": "normalizer_fitted_from_present_training_values_only",
            "source_artifacts": [
                {"name": name, "path": path, "sha256": digest}
                for name, path, digest in self.source_artifacts
            ],
        }
        payload["contract_sha256"] = _canonical_sha256(payload)
        return payload

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> GWMForcingMissingnessContract:
        if payload.get("schema") != GWM_FORCING_MISSINGNESS_SCHEMA:
            raise ValueError("forcing_missingness_schema_mismatch")
        if payload.get("contract_sha256") != _canonical_sha256(payload):
            raise ValueError("forcing_missingness_contract_hash_mismatch")
        contract = cls(
            contract_id=str(payload["contract_id"]),
            feature_names=tuple(str(value) for value in payload["feature_names"]),
            missing_reasons=tuple(
                str(value) for value in payload["missing_reasons"]
            ),
            source_artifacts=tuple(
                (str(row["name"]), str(row["path"]), str(row["sha256"]))
                for row in payload.get("source_artifacts", ())
            ),
        )
        if contract.as_dict() != dict(payload):
            raise ValueError("forcing_missingness_policy_mismatch")
        return contract


def verify_gwm_forcing_missingness_contract(
    split_contract: GWMForcingSplitContract,
    missingness_contract: GWMForcingMissingnessContract,
) -> str:
    """Verify missingness feature identity and return its canonical hash."""

    if missingness_contract.feature_names != split_contract.feature_names:
        raise ValueError("forcing_missingness_split_feature_mismatch")
    return missingness_contract.as_dict()["contract_sha256"]


def build_gwm_forcing_missing_ledger(
    *,
    split_contract: GWMForcingSplitContract,
    missingness_contract: GWMForcingMissingnessContract,
    missing_timestamps: list[str],
    system_ids: tuple[str, ...],
    archive_report_path: str,
    archive_report_sha256: str,
    archive_missing_count: int,
    archive_interpolation_used: bool,
) -> dict[str, Any]:
    """Materialize known absent source hours without fabricating values."""

    missingness_sha256 = verify_gwm_forcing_missingness_contract(
        split_contract, missingness_contract
    )
    if not system_ids or len(set(system_ids)) != len(system_ids):
        raise ValueError("forcing_missing_ledger_system_ids_must_be_unique")
    if not _SHA256.fullmatch(archive_report_sha256):
        raise ValueError("forcing_missing_ledger_archive_sha256_required")
    if archive_missing_count != len(missing_timestamps):
        raise ValueError("forcing_missing_ledger_archive_count_mismatch")
    if archive_interpolation_used:
        raise ValueError("forcing_missing_ledger_interpolation_forbidden")
    timestamps = [
        _utc_timestamp(value, field="missing_timestamp")
        for value in missing_timestamps
    ]
    if len(set(timestamps)) != len(timestamps):
        raise ValueError("forcing_missing_ledger_timestamps_must_be_unique")
    if timestamps != sorted(timestamps):
        raise ValueError("forcing_missing_ledger_timestamps_must_be_sorted")
    split_frame = pd.DataFrame({"forecast_origin": timestamps})
    temporal_splits = assign_gwm_forcing_split(split_frame, split_contract)
    records = [
        {
            "forecast_origin": timestamp.isoformat().replace("+00:00", "Z"),
            "temporal_split": str(split_name),
            "affected_feature_names": list(missingness_contract.feature_names),
            "observation_status": "missing",
            "missing_reason": "source_object_absent",
            "raw_value": None,
            "affected_system_ids": list(system_ids),
            "available_at_forecast_origin_verified": False,
            "model_input_admitted": False,
        }
        for timestamp, split_name in zip(
            timestamps, temporal_splits, strict=True
        )
    ]
    split_counts = {
        name: int((temporal_splits == name).sum())
        for name in ("train", "evaluation")
    }
    payload = {
        "schema": GWM_FORCING_MISSING_LEDGER_SCHEMA,
        "contract_id": missingness_contract.contract_id,
        "split_contract_sha256": split_contract.as_dict()["contract_sha256"],
        "missingness_contract_sha256": missingness_sha256,
        "archive_report": {
            "path": archive_report_path,
            "sha256": archive_report_sha256,
        },
        "system_ids": list(system_ids),
        "feature_names": list(missingness_contract.feature_names),
        "records": records,
        "summary": {
            "missing_hour_count": len(records),
            "affected_system_record_count": len(records) * len(system_ids),
            "missing_hour_count_by_split": split_counts,
            "raw_null_count": len(records),
            "interpolation_or_forward_fill_used": False,
            "available_at_forecast_origin_verified_count": 0,
            "model_input_admitted_count": 0,
        },
        "claim_boundary": {
            "archive_absence_materialized": True,
            "missing_value_observed": False,
            "input_time_availability_verified": False,
            "forcing_training_input_admitted": False,
            "general_geospatial_kernel_validated": False,
            "general_gwm_validated": False,
        },
    }
    payload["artifact_sha256"] = _canonical_sha256(payload)
    return payload


def verify_gwm_forcing_missing_ledger(
    ledger: Mapping[str, Any],
    *,
    split_contract: GWMForcingSplitContract,
    missingness_contract: GWMForcingMissingnessContract,
    archive_report_sha256: str,
) -> str:
    """Recompute ledger semantics and return its canonical artifact hash."""

    if ledger.get("schema") != GWM_FORCING_MISSING_LEDGER_SCHEMA:
        raise ValueError("forcing_missing_ledger_schema_mismatch")
    digest = _canonical_sha256(ledger)
    if ledger.get("artifact_sha256") != digest:
        raise ValueError("forcing_missing_ledger_artifact_hash_mismatch")
    rebuilt = build_gwm_forcing_missing_ledger(
        split_contract=split_contract,
        missingness_contract=missingness_contract,
        missing_timestamps=[
            str(row["forecast_origin"]) for row in ledger.get("records", ())
        ],
        system_ids=tuple(str(value) for value in ledger.get("system_ids", ())),
        archive_report_path=str(ledger["archive_report"]["path"]),
        archive_report_sha256=archive_report_sha256,
        archive_missing_count=int(ledger["summary"]["missing_hour_count"]),
        archive_interpolation_used=bool(
            ledger["summary"]["interpolation_or_forward_fill_used"]
        ),
    )
    if rebuilt != dict(ledger):
        raise ValueError("forcing_missing_ledger_semantics_mismatch")
    return digest


def assign_gwm_forcing_split(
    records: pd.DataFrame,
    contract: GWMForcingSplitContract,
    *,
    time_column: str = "forecast_origin",
) -> pd.Series:
    """Assign train/evaluation without interpreting naive timestamps as UTC."""

    _validate_split_time_column(time_column)
    if time_column not in records:
        raise ValueError("forcing_split_time_column_missing")
    timestamps = []
    for value in records[time_column]:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            raise ValueError("forcing_split_timestamp_required")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("forcing_split_timestamp_timezone_required")
        timestamps.append(timestamp.tz_convert("UTC"))
    values = pd.Series(timestamps, index=records.index)
    split = pd.Series(pd.NA, index=records.index, dtype="string")
    train = (values >= contract.train_start) & (
        values < contract.train_end_exclusive
    )
    evaluation = (values >= contract.evaluation_start) & (
        values < contract.evaluation_end_exclusive
    )
    split.loc[train] = "train"
    split.loc[evaluation] = "evaluation"
    if split.isna().any():
        raise ValueError("forcing_split_record_outside_frozen_intervals")
    return split


def fit_gwm_forcing_normalizer(
    records: pd.DataFrame,
    contract: GWMForcingSplitContract,
    *,
    training_coverage_verified: bool,
    feature_column: str = "feature_name",
    value_column: str = "value",
    time_column: str = "forecast_origin",
) -> dict[str, Any]:
    """Fit a hash-bound per-entity z-score artifact from training rows only."""

    if not training_coverage_verified:
        raise ValueError("forcing_normalizer_training_coverage_unverified")
    _validate_split_time_column(time_column)
    frame = _validated_frame(
        records,
        contract,
        feature_column=feature_column,
        value_column=value_column,
        time_column=time_column,
    )
    frame["split"] = assign_gwm_forcing_split(
        frame, contract, time_column=time_column
    )
    train = frame.loc[frame["split"] == "train"].copy()
    if train.empty:
        raise ValueError("forcing_normalizer_training_rows_required")
    key_columns = [*contract.entity_columns, feature_column]
    statistics = []
    for key, group in train.groupby(key_columns, sort=True, dropna=False):
        key_values = key if isinstance(key, tuple) else (key,)
        values = group[value_column].to_numpy(dtype=np.float64)
        mean = float(np.mean(values))
        standard_deviation = float(np.std(values, ddof=0))
        if not math.isfinite(mean) or not math.isfinite(standard_deviation):
            raise ValueError("forcing_normalizer_statistic_nonfinite")
        if standard_deviation <= 0.0:
            raise ValueError("forcing_normalizer_standard_deviation_nonpositive")
        statistics.append(
            {
                **{
                    column: str(value)
                    for column, value in zip(key_columns, key_values, strict=True)
                },
                "count": int(len(values)),
                "mean": mean,
                "standard_deviation": standard_deviation,
            }
        )
    expected_keys = {
        (*entity, feature)
        for entity in train.loc[:, contract.entity_columns]
        .drop_duplicates()
        .itertuples(index=False, name=None)
        for feature in contract.feature_names
    }
    actual_keys = {
        tuple(row[column] for column in key_columns) for row in statistics
    }
    if actual_keys != expected_keys:
        raise ValueError("forcing_normalizer_incomplete_entity_feature_grid")

    fingerprint_columns = [
        *contract.entity_columns,
        time_column,
        feature_column,
        value_column,
    ]
    fingerprint_rows = []
    for row in train.sort_values(fingerprint_columns).loc[
        :, fingerprint_columns
    ].itertuples(index=False, name=None):
        values = list(row)
        values[len(contract.entity_columns)] = pd.Timestamp(
            values[len(contract.entity_columns)]
        ).isoformat().replace("+00:00", "Z")
        fingerprint_rows.append(values)
    training_fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_rows,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    artifact = {
        "schema": GWM_FORCING_NORMALIZER_SCHEMA,
        "contract_id": contract.contract_id,
        "split_contract_sha256": contract.as_dict()["contract_sha256"],
        "feature_names": list(contract.feature_names),
        "entity_columns": list(contract.entity_columns),
        "feature_column": feature_column,
        "value_column": value_column,
        "time_column": time_column,
        "method": "zscore_population_standard_deviation",
        "fit_split": "train",
        "evaluation_values_read_during_fit": False,
        "training_row_count": int(len(train)),
        "training_data_sha256": training_fingerprint,
        "statistics": statistics,
    }
    artifact["artifact_sha256"] = _canonical_sha256(artifact)
    return artifact


def apply_gwm_forcing_normalizer(
    records: pd.DataFrame,
    contract: GWMForcingSplitContract,
    artifact: Mapping[str, Any],
) -> pd.DataFrame:
    """Apply a verified frozen artifact without fitting on evaluation records."""

    verify_gwm_forcing_normalizer(contract, artifact)
    feature_column = str(artifact["feature_column"])
    value_column = str(artifact["value_column"])
    time_column = str(artifact["time_column"])
    _validate_split_time_column(time_column)
    frame = _validated_frame(
        records,
        contract,
        feature_column=feature_column,
        value_column=value_column,
        time_column=time_column,
    )
    frame["temporal_split"] = assign_gwm_forcing_split(
        frame, contract, time_column=time_column
    )
    key_columns = [*contract.entity_columns, feature_column]
    statistics = pd.DataFrame(artifact["statistics"])
    if statistics.duplicated(key_columns).any():
        raise ValueError("forcing_normalizer_duplicate_statistic_key")
    frame["_gwm_input_order"] = np.arange(len(frame), dtype=np.int64)
    selected = frame.merge(
        statistics.loc[:, [*key_columns, "mean", "standard_deviation"]],
        on=key_columns,
        how="left",
        validate="many_to_one",
    )
    if selected["mean"].isna().any():
        raise ValueError("forcing_normalizer_statistic_missing")
    selected["normalized_value"] = (
        selected[value_column] - selected["mean"]
    ) / selected["standard_deviation"]
    if not np.isfinite(selected["normalized_value"].to_numpy(dtype=float)).all():
        raise ValueError("forcing_normalizer_output_nonfinite")
    return (
        selected.sort_values("_gwm_input_order")
        .drop(columns=["mean", "standard_deviation", "_gwm_input_order"])
        .reset_index(drop=True)
    )


def apply_gwm_masked_forcing_normalizer(
    records: pd.DataFrame,
    contract: GWMForcingSplitContract,
    artifact: Mapping[str, Any],
    *,
    missingness_contract: GWMForcingMissingnessContract,
    status_column: str = "observation_status",
    missing_reason_column: str = "missing_reason",
) -> pd.DataFrame:
    """Normalize present values and encode explicit missing values fail-closed."""

    verify_gwm_forcing_normalizer(contract, artifact)
    verify_gwm_forcing_missingness_contract(contract, missingness_contract)
    feature_column = str(artifact["feature_column"])
    value_column = str(artifact["value_column"])
    time_column = str(artifact["time_column"])
    required = {status_column, missing_reason_column, value_column}
    missing_columns = sorted(required - set(records.columns))
    if missing_columns:
        raise ValueError(
            "forcing_masked_normalizer_missing_columns:"
            + ",".join(missing_columns)
        )
    frame = records.copy()
    statuses = frame[status_column].astype(str)
    unsupported = sorted(set(statuses) - {"present", "missing"})
    if unsupported:
        raise ValueError(
            "forcing_masked_normalizer_status_unsupported:" + ",".join(unsupported)
        )
    missing = statuses.eq("missing")
    if frame.loc[missing, value_column].notna().any():
        raise ValueError("forcing_masked_normalizer_missing_raw_value_must_be_null")
    if frame.loc[~missing, value_column].isna().any():
        raise ValueError("forcing_masked_normalizer_present_value_required")
    reasons = frame[missing_reason_column].fillna("").astype(str).str.strip()
    if (
        reasons.loc[missing].eq("").any()
        or not set(reasons.loc[missing]).issubset(
            missingness_contract.missing_reasons
        )
    ):
        raise ValueError("forcing_masked_normalizer_missing_reason_invalid")
    if reasons.loc[~missing].ne("").any():
        raise ValueError("forcing_masked_normalizer_present_reason_must_be_empty")

    validation_frame = frame.copy()
    validation_frame.loc[missing, value_column] = 0.0
    validated = _validated_frame(
        validation_frame,
        contract,
        feature_column=feature_column,
        value_column=value_column,
        time_column=time_column,
    )
    validated["temporal_split"] = assign_gwm_forcing_split(
        validated, contract, time_column=time_column
    )
    validated["_gwm_input_order"] = np.arange(len(validated), dtype=np.int64)
    key_columns = [*contract.entity_columns, feature_column]
    statistics = pd.DataFrame(artifact["statistics"])
    if statistics.duplicated(key_columns).any():
        raise ValueError("forcing_normalizer_duplicate_statistic_key")
    selected = validated.merge(
        statistics.loc[:, [*key_columns, "mean", "standard_deviation"]],
        on=key_columns,
        how="left",
        validate="many_to_one",
    )
    if selected["mean"].isna().any():
        raise ValueError("forcing_normalizer_statistic_missing")
    selected_missing = selected[status_column].eq("missing")
    selected["normalized_value"] = (
        selected[value_column] - selected["mean"]
    ) / selected["standard_deviation"]
    selected.loc[selected_missing, "normalized_value"] = 0.0
    selected.loc[selected_missing, value_column] = np.nan
    selected["observed_mask"] = (~selected_missing).astype(np.float32)
    selected["imputation_uncertainty"] = selected_missing.astype(np.float32)
    if not np.isfinite(selected["normalized_value"].to_numpy(dtype=float)).all():
        raise ValueError("forcing_normalizer_output_nonfinite")
    return (
        selected.sort_values("_gwm_input_order")
        .drop(columns=["mean", "standard_deviation", "_gwm_input_order"])
        .reset_index(drop=True)
    )


def verify_gwm_forcing_normalizer(
    contract: GWMForcingSplitContract,
    artifact: Mapping[str, Any],
) -> str:
    """Verify artifact identity and return its canonical SHA-256."""

    if artifact.get("schema") != GWM_FORCING_NORMALIZER_SCHEMA:
        raise ValueError("forcing_normalizer_schema_mismatch")
    digest = _canonical_sha256(artifact)
    if artifact.get("artifact_sha256") != digest:
        raise ValueError("forcing_normalizer_artifact_hash_mismatch")
    if artifact.get("split_contract_sha256") != contract.as_dict()[
        "contract_sha256"
    ]:
        raise ValueError("forcing_normalizer_split_contract_mismatch")
    if tuple(artifact.get("feature_names", ())) != contract.feature_names:
        raise ValueError("forcing_normalizer_feature_order_mismatch")
    if tuple(artifact.get("entity_columns", ())) != contract.entity_columns:
        raise ValueError("forcing_normalizer_entity_columns_mismatch")
    if artifact.get("contract_id") != contract.contract_id:
        raise ValueError("forcing_normalizer_contract_id_mismatch")
    if artifact.get("method") != "zscore_population_standard_deviation":
        raise ValueError("forcing_normalizer_method_mismatch")
    _validate_split_time_column(str(artifact.get("time_column", "")))
    if artifact.get("fit_split") != "train" or artifact.get(
        "evaluation_values_read_during_fit"
    ) is not False:
        raise ValueError("forcing_normalizer_training_only_fit_required")
    return digest


def _validated_frame(
    records: pd.DataFrame,
    contract: GWMForcingSplitContract,
    *,
    feature_column: str,
    value_column: str,
    time_column: str,
) -> pd.DataFrame:
    required = {
        *contract.entity_columns,
        feature_column,
        value_column,
        time_column,
    }
    missing = sorted(required - set(records.columns))
    if missing:
        raise ValueError("forcing_normalizer_missing_columns:" + ",".join(missing))
    frame = records.copy()
    for column in contract.entity_columns:
        if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
            raise ValueError("forcing_normalizer_entity_required:" + column)
        frame[column] = frame[column].astype(str)
    frame[feature_column] = frame[feature_column].astype(str)
    unexpected = sorted(set(frame[feature_column]) - set(contract.feature_names))
    if unexpected:
        raise ValueError(
            "forcing_normalizer_unrequested_features:" + ",".join(unexpected)
        )
    frame[value_column] = pd.to_numeric(frame[value_column], errors="raise")
    if not np.isfinite(frame[value_column].to_numpy(dtype=float)).all():
        raise ValueError("forcing_normalizer_value_nonfinite")
    normalized_times = []
    for value in frame[time_column]:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            raise ValueError("forcing_split_timestamp_required")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("forcing_split_timestamp_timezone_required")
        normalized_times.append(timestamp.tz_convert("UTC"))
    frame[time_column] = pd.Series(normalized_times, index=frame.index)
    keys = [*contract.entity_columns, time_column, feature_column]
    if frame.duplicated(keys).any():
        raise ValueError("forcing_normalizer_duplicate_entity_time_feature")
    return frame


def _validate_split_time_column(time_column: str) -> None:
    if time_column not in {"forecast_origin", "timestamp"}:
        raise ValueError("forcing_split_forecast_origin_column_required")
