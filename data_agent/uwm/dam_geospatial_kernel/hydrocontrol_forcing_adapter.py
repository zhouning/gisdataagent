"""HydroControl binding for the shared GWM temporal-context contract."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

import pandas as pd
import torch

from .forcing_admission import (
    GWMForcingAdmissionCertificate,
    verify_gwm_forcing_admission_certificate,
)
from .forcing_normalization import (
    GWMForcingMissingnessContract,
    GWMForcingSplitContract,
    apply_gwm_forcing_normalizer,
    apply_gwm_masked_forcing_normalizer,
    verify_gwm_forcing_missingness_contract,
    verify_gwm_forcing_normalizer,
)
from .hydrocontrol_adapter import HydroControlDAMGKDataset
from .negative_controls import (
    permute_temporal_context_features,
    zero_temporal_context_features,
)
from .temporal_context import (
    GWMTemporalContextCompilation,
    attach_gwm_temporal_context,
    compile_gwm_masked_temporal_context,
    compile_gwm_temporal_context,
)


HYDROCONTROL_FORCING_ADAPTER_SCHEMA = (
    "gwm.geospatial_kernel.hydrocontrol_forcing_adapter.v1"
)
HYDROCONTROL_FORCING_COLUMNS = (
    "system_id",
    "timestamp",
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
HYDROCONTROL_MASKED_FORCING_COLUMNS = (
    *HYDROCONTROL_FORCING_COLUMNS,
    "observation_status",
    "missing_reason",
)
HYDROCONTROL_FORCING_MISSINGNESS_POLICIES = {
    "reject",
    "explicit_training_mean_mask",
}


def attach_hydrocontrol_forcing_context(
    dataset: HydroControlDAMGKDataset,
    forcing_records: pd.DataFrame,
    *,
    feature_names: Iterable[str],
    admission_certificate: GWMForcingAdmissionCertificate,
    split_contract: GWMForcingSplitContract,
    normalizer_artifact: Mapping[str, Any],
    timestamp_timezone: str,
    missingness_policy: str = "reject",
    missingness_contract: GWMForcingMissingnessContract | None = None,
) -> tuple[HydroControlDAMGKDataset, GWMTemporalContextCompilation]:
    """Attach admitted forcing to both nodes of each disjoint hydro sample.

    Raw values are transformed with a verified normalizer frozen from training
    data. This adapter never fits a scaler on a mixed train/evaluation table.
    """

    ordered_features = tuple(str(value) for value in feature_names)
    verify_gwm_forcing_admission_certificate(admission_certificate)
    if not admission_certificate.model_input_admitted:
        raise ValueError(
            "hydrocontrol_forcing_admission_blocked:"
            f"{admission_certificate.first_nonpass_gate}"
        )
    if admission_certificate.feature_names != ordered_features:
        raise ValueError("hydrocontrol_forcing_certificate_feature_mismatch")
    if split_contract.feature_names != ordered_features:
        raise ValueError("hydrocontrol_forcing_split_feature_mismatch")
    normalizer_sha256 = verify_gwm_forcing_normalizer(
        split_contract, normalizer_artifact
    )
    if not str(timestamp_timezone).strip():
        raise ValueError("hydrocontrol_forcing_timestamp_timezone_required")
    if missingness_policy not in HYDROCONTROL_FORCING_MISSINGNESS_POLICIES:
        raise ValueError("hydrocontrol_forcing_missingness_policy_unsupported")
    missingness_contract_sha256 = None
    if missingness_policy == "explicit_training_mean_mask":
        if missingness_contract is None:
            raise ValueError("hydrocontrol_forcing_missingness_contract_required")
        missingness_contract_sha256 = verify_gwm_forcing_missingness_contract(
            split_contract, missingness_contract
        )
    required_columns = (
        HYDROCONTROL_MASKED_FORCING_COLUMNS
        if missingness_policy == "explicit_training_mean_mask"
        else HYDROCONTROL_FORCING_COLUMNS
    )
    missing = sorted(
        set(required_columns) - set(forcing_records.columns)
    )
    if missing:
        raise ValueError("hydrocontrol_forcing_missing_columns:" + ",".join(missing))
    frame = forcing_records.loc[:, required_columns].copy()
    frame["system_id"] = frame["system_id"].astype(str)
    frame["timestamp"] = _timestamps_to_utc(
        frame["timestamp"], timezone=timestamp_timezone
    )
    if missingness_policy == "explicit_training_mean_mask":
        normalized = apply_gwm_masked_forcing_normalizer(
            frame,
            split_contract,
            normalizer_artifact,
            missingness_contract=missingness_contract,
        )
    else:
        normalized = apply_gwm_forcing_normalizer(
            frame,
            split_contract,
            normalizer_artifact,
        )
    frame = normalized.loc[:, required_columns].copy()
    frame["value"] = normalized["normalized_value"].to_numpy()

    sample_index = pd.DataFrame(
        {
            "sample_index": range(dataset.sample_count),
            "system_id": dataset.system_ids,
            "timestamp": _timestamps_to_utc(
                pd.Series(dataset.input_timestamps),
                timezone=timestamp_timezone,
            ),
        }
    )
    if sample_index.duplicated(["system_id", "timestamp"]).any():
        raise ValueError("duplicate_hydrocontrol_sample_key")
    selected = sample_index.merge(
        frame,
        on=["system_id", "timestamp"],
        how="left",
        validate="one_to_many",
    )
    if selected["feature_name"].isna().any():
        raise ValueError("hydrocontrol_forcing_sample_missing")

    node_rows = []
    node_keys = []
    forecast_origins = []
    for sample_id, group in selected.groupby("sample_index", sort=True):
        origin = pd.Timestamp(group["timestamp"].iloc[0])
        for role in ("action", "response"):
            node_key = f"hydro:{sample_id}:{role}"
            node_keys.append(node_key)
            forecast_origins.append(origin)
            copied = group.copy()
            copied["node_key"] = node_key
            copied["forecast_origin"] = origin
            node_rows.append(copied)
    common = pd.concat(node_rows, ignore_index=True)
    if missingness_policy == "explicit_training_mean_mask":
        compilation = compile_gwm_masked_temporal_context(
            common,
            node_keys=node_keys,
            forecast_origins=forecast_origins,
            horizon=1,
            feature_names=ordered_features,
            normalizer_artifact_sha256=normalizer_sha256,
            missingness_contract_sha256=missingness_contract_sha256,
        )
    else:
        compilation = compile_gwm_temporal_context(
            common,
            node_keys=node_keys,
            forecast_origins=forecast_origins,
            horizon=1,
            feature_names=ordered_features,
        )
    batch = attach_gwm_temporal_context(dataset.batch, compilation, append=True)
    augmented = replace(
        dataset,
        schema=HYDROCONTROL_FORCING_ADAPTER_SCHEMA,
        batch=batch,
        context_feature_names=(
            *dataset.context_feature_names,
            *compilation.feature_names,
        ),
        context_audit={
            **compilation.audit,
            "normalization_contract": "pre_fitted_training_only_values_required",
            "normalization_applied_by_adapter": True,
            "missingness_policy": missingness_policy,
            "missingness_contract_sha256": missingness_contract_sha256,
            "normalizer_artifact_sha256": normalizer_sha256,
            "split_contract_sha256": split_contract.as_dict()[
                "contract_sha256"
            ],
            "domain_binding": "hydrocontrol",
            "forcing_feature_names": list(compilation.feature_names),
            "forcing_base_feature_names": list(ordered_features),
            "admission_certificate": admission_certificate.as_dict(),
        },
    )
    return augmented, compilation


def _timestamps_to_utc(
    values: pd.Series, *, timezone: str
) -> pd.Series:
    timestamps = pd.to_datetime(values, errors="raise")
    if timestamps.isna().any():
        raise ValueError("hydrocontrol_forcing_timestamp_required")
    try:
        if timestamps.dt.tz is None:
            timestamps = timestamps.dt.tz_localize(
                timezone, ambiguous="raise", nonexistent="raise"
            )
        return timestamps.dt.tz_convert("UTC")
    except (TypeError, ValueError) as exc:
        raise ValueError("hydrocontrol_forcing_timestamp_timezone_invalid") from exc


def with_hydrocontrol_forcing_control(
    dataset: HydroControlDAMGKDataset,
    *,
    mode: str,
    seed: int = 0,
) -> HydroControlDAMGKDataset:
    """Build no-forcing or within-system shuffled-forcing controls."""

    audit = dataset.context_audit or {}
    forcing_names = tuple(audit.get("forcing_feature_names", ()))
    if not forcing_names:
        raise ValueError("hydrocontrol_forcing_context_required")
    indices = torch.tensor(
        [dataset.context_feature_names.index(name) for name in forcing_names],
        dtype=torch.long,
    )
    if mode == "zero":
        batch = zero_temporal_context_features(dataset.batch, indices)
    elif mode == "shuffle_within_system":
        generator = torch.Generator().manual_seed(seed)
        sample_permutation = torch.arange(dataset.sample_count, dtype=torch.long)
        for system_id in sorted(set(dataset.system_ids)):
            members = torch.tensor(
                [
                    index
                    for index, value in enumerate(dataset.system_ids)
                    if value == system_id
                ],
                dtype=torch.long,
            )
            shuffled = members[torch.randperm(len(members), generator=generator)]
            sample_permutation[members] = shuffled
        node_permutation = torch.empty(dataset.sample_count * 2, dtype=torch.long)
        node_permutation[0::2] = sample_permutation * 2
        node_permutation[1::2] = sample_permutation * 2 + 1
        batch = permute_temporal_context_features(
            dataset.batch, node_permutation, indices
        )
    else:
        raise ValueError("unsupported_hydrocontrol_forcing_control")
    return replace(
        dataset,
        batch=batch,
        context_audit={
            **audit,
            "negative_control": mode,
            "negative_control_seed": seed,
        },
    )
