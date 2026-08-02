from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import torch

from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_adapter import (
    HYDROCONTROL_DAM_GK_ADAPTER_SCHEMA,
    build_hydrocontrol_dam_gk_dataset,
    inverse_signed_log_state,
    prepare_hydrocontrol_targets,
    select_hydrocontrol_samples,
    signed_log_state,
)
from data_agent.uwm.dam_geospatial_kernel.hydrocontrol_forcing_adapter import (
    HYDROCONTROL_FORCING_ADAPTER_SCHEMA,
    attach_hydrocontrol_forcing_context,
    with_hydrocontrol_forcing_control,
)
from data_agent.uwm.dam_geospatial_kernel.forcing_admission import (
    GWM_FORCING_ADMISSION_GATES,
    evaluate_gwm_forcing_admission,
)
from data_agent.uwm.dam_geospatial_kernel.forcing_normalization import (
    GWMForcingMissingnessContract,
    GWMForcingSplitContract,
    fit_gwm_forcing_normalizer,
)


def _panel() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=9, freq="h")
    rows = []
    for system_index, system_id in enumerate(("alpha", "beta")):
        for index, timestamp in enumerate(timestamps):
            rows.append(
                {
                    "system_id": system_id,
                    "timestamp": timestamp,
                    "temporal_split": "train",
                    "effective_release_cfs": 100.0 + system_index + index,
                    "effective_release_change_cfs": float(index - 4),
                    "downstream_flow_cfs": 200.0 + 10 * system_index + index,
                    "admitted_current_state_action": True,
                    "dst_transition_day": False,
                }
            )
    return pd.DataFrame(rows)


def _normalizer(feature_names: tuple[str, ...]):
    contract = GWMForcingSplitContract(
        contract_id="hydro-test",
        feature_names=feature_names,
        entity_columns=("system_id",),
        train_start=pd.Timestamp("2022-01-01T00:00:00Z"),
        train_end_exclusive=pd.Timestamp("2025-01-01T00:00:00Z"),
        evaluation_start=pd.Timestamp("2025-01-01T00:00:00Z"),
        evaluation_end_exclusive=pd.Timestamp("2026-01-01T00:00:00Z"),
        expected_frequency="PT1H",
        normalization_scope="per_entity_feature",
    )
    rows = []
    for feature_index, feature_name in enumerate(feature_names):
        rows.extend(
            [
                {
                    "system_id": "alpha",
                    "timestamp": "2022-01-01T00:00:00Z",
                    "valid_time": "2022-01-01T00:00:00Z",
                    "feature_name": feature_name,
                    "value": float(feature_index + 1),
                },
                {
                    "system_id": "alpha",
                    "timestamp": "2024-12-31T23:00:00Z",
                    "valid_time": "2024-12-31T23:00:00Z",
                    "feature_name": feature_name,
                    "value": float(feature_index + 3),
                },
            ]
        )
    artifact = fit_gwm_forcing_normalizer(
        pd.DataFrame(rows),
        contract,
        training_coverage_verified=True,
        time_column="timestamp",
    )
    return contract, artifact


def test_adapter_uses_exact_future_system_timestamp_and_source_only_action():
    dataset = build_hydrocontrol_dam_gk_dataset(
        _panel(), horizon_hours=3, systems=["alpha"], temporal_split="train"
    )

    assert dataset.schema == HYDROCONTROL_DAM_GK_ADAPTER_SCHEMA
    assert dataset.sample_count == 6
    assert dataset.system_ids == ("alpha",) * 6
    assert dataset.input_timestamps[0] == pd.Timestamp("2024-01-01T00:00:00")
    assert dataset.target_timestamps[0] == pd.Timestamp("2024-01-01T03:00:00")
    assert dataset.target_flow_cfs[0].item() == pytest.approx(203.0)
    source, target = dataset.batch.edge_index
    assert torch.equal(source, torch.arange(0, 12, 2))
    assert torch.equal(target, torch.arange(1, 12, 2))
    assert torch.count_nonzero(dataset.batch.node_action[target]) == 0
    assert torch.count_nonzero(dataset.batch.node_action[source]) > 0


def test_adapter_never_uses_row_offset_when_an_hour_is_missing():
    panel = _panel()
    missing = (panel["system_id"] == "alpha") & (
        panel["timestamp"] == pd.Timestamp("2024-01-01T03:00:00")
    )
    prepared = prepare_hydrocontrol_targets(
        panel.loc[~missing], horizon_hours=3
    )
    row = prepared.loc[
        (prepared["system_id"] == "alpha")
        & (prepared["timestamp"] == pd.Timestamp("2024-01-01T00:00:00"))
    ].iloc[0]

    assert pd.isna(row["target_flow_cfs"])


def test_adapter_excludes_dst_and_unadmitted_samples_fail_closed():
    panel = _panel()
    panel.loc[0, "dst_transition_day"] = True
    panel.loc[1, "admitted_current_state_action"] = False
    dataset = build_hydrocontrol_dam_gk_dataset(
        panel, horizon_hours=3, systems=["alpha"], temporal_split="train"
    )

    assert pd.Timestamp("2024-01-01T00:00:00") not in dataset.input_timestamps
    assert pd.Timestamp("2024-01-01T01:00:00") not in dataset.input_timestamps


def test_sample_selection_reindexes_disjoint_graphs_without_cross_sample_edges():
    dataset = build_hydrocontrol_dam_gk_dataset(
        _panel(), horizon_hours=3, temporal_split="train"
    )
    selected = select_hydrocontrol_samples(dataset, [1, 7, 3])

    assert selected.sample_count == 3
    assert selected.system_ids == (
        dataset.system_ids[1],
        dataset.system_ids[7],
        dataset.system_ids[3],
    )
    assert torch.equal(
        selected.batch.edge_index,
        torch.tensor([[0, 2, 4], [1, 3, 5]], dtype=torch.long),
    )
    assert torch.equal(selected.target_node_index, torch.tensor([1, 3, 5]))


def test_signed_log_state_round_trips_positive_and_negative_values():
    values = torch.tensor([-1000.0, -1.0, 0.0, 1.0, 1000.0])
    restored = inverse_signed_log_state(signed_log_state(values))

    assert torch.allclose(restored, values, atol=1e-3)


def test_adapter_rejects_undeclared_horizon():
    with pytest.raises(ValueError, match="unsupported_hydrocontrol_horizon"):
        build_hydrocontrol_dam_gk_dataset(_panel(), horizon_hours=2)


def test_forcing_adapter_uses_shared_gwm_evidence_gate_and_preserves_base_context():
    dataset = build_hydrocontrol_dam_gk_dataset(
        _panel(), horizon_hours=3, systems=["alpha"], temporal_split="train"
    )
    rows = []
    for timestamp in dataset.input_timestamps:
        evidence_timestamp = timestamp.tz_localize("UTC")
        for feature_name, value in (("past_rain", 0.2), ("tributary_flow", 1.5)):
            rows.append(
                {
                    "system_id": "alpha",
                    "timestamp": timestamp,
                    "step_index": 0,
                    "feature_name": feature_name,
                    "value": value,
                    "valid_time": evidence_timestamp,
                    "available_at": evidence_timestamp,
                    "evidence_class": "observed",
                    "admission_status": "admitted",
                    "source_id": "official-source",
                    "source_artifact_sha256": "a" * 64,
                }
            )

    certificate = evaluate_gwm_forcing_admission(
        source_id="official-source",
        feature_names=("past_rain", "tributary_flow"),
        checks={gate: True for gate in GWM_FORCING_ADMISSION_GATES},
    )
    split_contract, normalizer_artifact = _normalizer(
        ("past_rain", "tributary_flow")
    )
    augmented, compilation = attach_hydrocontrol_forcing_context(
        dataset,
        pd.DataFrame(rows),
        feature_names=("past_rain", "tributary_flow"),
        admission_certificate=certificate,
        split_contract=split_contract,
        normalizer_artifact=normalizer_artifact,
        timestamp_timezone="UTC",
    )

    assert augmented.schema == HYDROCONTROL_FORCING_ADAPTER_SCHEMA
    assert augmented.context_feature_names == (
        "hour_sin",
        "hour_cos",
        "past_rain",
        "tributary_flow",
    )
    assert augmented.batch.node_context.shape == (12, 4)
    assert augmented.batch.node_context_by_step.shape == (12, 1, 4)
    assert torch.allclose(
        augmented.batch.node_context[:, :2], dataset.batch.node_context
    )
    assert augmented.batch.node_context[0, 2:].tolist() == pytest.approx([-1.8, -1.5])
    assert augmented.batch.node_context[1, 2:].tolist() == pytest.approx([-1.8, -1.5])
    assert compilation.audit["publication_time_leakage_count"] == 0
    assert augmented.context_audit["normalization_contract"] == (
        "pre_fitted_training_only_values_required"
    )
    assert augmented.context_audit["normalizer_artifact_sha256"] == (
        normalizer_artifact["artifact_sha256"]
    )
    assert augmented.context_audit["normalization_applied_by_adapter"] is True
    assert normalizer_artifact["time_column"] == "timestamp"

    selected = select_hydrocontrol_samples(augmented, [4, 1])
    assert selected.batch.node_context_by_step.shape == (4, 1, 4)
    assert torch.equal(
        selected.batch.node_context,
        selected.batch.node_context_by_step[:, 0],
    )
    assert selected.context_feature_names == augmented.context_feature_names

    zero = with_hydrocontrol_forcing_control(augmented, mode="zero")
    assert torch.count_nonzero(zero.batch.node_context[:, 2:]) == 0
    assert torch.equal(
        zero.batch.node_context[:, :2], augmented.batch.node_context[:, :2]
    )
    shuffled = with_hydrocontrol_forcing_control(
        augmented, mode="shuffle_within_system", seed=17
    )
    assert torch.equal(
        shuffled.batch.node_context[:, :2], augmented.batch.node_context[:, :2]
    )
    assert shuffled.context_audit["negative_control"] == "shuffle_within_system"


def test_forcing_adapter_encodes_explicit_missingness_without_forging_observation():
    dataset = build_hydrocontrol_dam_gk_dataset(
        _panel(), horizon_hours=3, systems=["alpha"], temporal_split="train"
    )
    rows = []
    for index, timestamp in enumerate(dataset.input_timestamps):
        evidence_timestamp = timestamp.tz_localize("UTC")
        is_missing = index == 0
        rows.append(
            {
                "system_id": "alpha",
                "timestamp": timestamp,
                "step_index": 0,
                "feature_name": "past_rain",
                "value": None if is_missing else 1.0,
                "valid_time": evidence_timestamp,
                "available_at": evidence_timestamp,
                "evidence_class": "observed",
                "admission_status": "admitted",
                "source_id": "official-source",
                "source_artifact_sha256": "a" * 64,
                "observation_status": "missing" if is_missing else "present",
                "missing_reason": "source_object_absent" if is_missing else "",
            }
        )
    certificate = evaluate_gwm_forcing_admission(
        source_id="official-source",
        feature_names=("past_rain",),
        checks={gate: True for gate in GWM_FORCING_ADMISSION_GATES},
    )
    split_contract, normalizer_artifact = _normalizer(("past_rain",))
    missingness_contract = GWMForcingMissingnessContract(
        contract_id="hydro-test-missingness",
        feature_names=("past_rain",),
        missing_reasons=("source_object_absent",),
    )

    with pytest.raises(ValueError, match="missingness_contract_required"):
        attach_hydrocontrol_forcing_context(
            dataset,
            pd.DataFrame(rows),
            feature_names=("past_rain",),
            admission_certificate=certificate,
            split_contract=split_contract,
            normalizer_artifact=normalizer_artifact,
            timestamp_timezone="UTC",
            missingness_policy="explicit_training_mean_mask",
        )

    augmented, compilation = attach_hydrocontrol_forcing_context(
        dataset,
        pd.DataFrame(rows),
        feature_names=("past_rain",),
        admission_certificate=certificate,
        split_contract=split_contract,
        normalizer_artifact=normalizer_artifact,
        timestamp_timezone="UTC",
        missingness_policy="explicit_training_mean_mask",
        missingness_contract=missingness_contract,
    )

    assert compilation.feature_names == (
        "past_rain",
        "past_rain__observed_mask",
        "past_rain__imputation_uncertainty",
    )
    assert augmented.context_feature_names == (
        "hour_sin",
        "hour_cos",
        *compilation.feature_names,
    )
    assert augmented.batch.node_context[0, 2:].tolist() == [0.0, 0.0, 1.0]
    assert augmented.batch.node_context[1, 2:].tolist() == [0.0, 0.0, 1.0]
    assert augmented.batch.node_context[2, 2:].tolist() == [-1.0, 1.0, 0.0]
    assert compilation.audit["explicit_missing_record_count"] == 2
    assert augmented.context_audit["missingness_policy"] == (
        "explicit_training_mean_mask"
    )
    assert augmented.context_audit["forcing_base_feature_names"] == ["past_rain"]

    zero = with_hydrocontrol_forcing_control(augmented, mode="zero")
    assert torch.count_nonzero(zero.batch.node_context[:, 2:]) == 0

    with pytest.raises(ValueError, match="missingness_policy_unsupported"):
        attach_hydrocontrol_forcing_context(
            dataset,
            pd.DataFrame(rows),
            feature_names=("past_rain",),
            admission_certificate=certificate,
            split_contract=split_contract,
            normalizer_artifact=normalizer_artifact,
            timestamp_timezone="UTC",
            missingness_policy="implicit_fill",
        )


def test_forcing_adapter_rejects_self_labeled_records_without_passing_certificate():
    dataset = build_hydrocontrol_dam_gk_dataset(
        _panel(), horizon_hours=3, systems=["alpha"], temporal_split="train"
    )
    certificate = evaluate_gwm_forcing_admission(
        source_id="candidate",
        feature_names=("tributary_flow",),
        checks={gate: False for gate in GWM_FORCING_ADMISSION_GATES},
    )
    split_contract, normalizer_artifact = _normalizer(("tributary_flow",))
    with pytest.raises(ValueError, match="forcing_admission_blocked"):
        attach_hydrocontrol_forcing_context(
            dataset,
            pd.DataFrame(columns=[
                "system_id", "timestamp", "step_index", "feature_name",
                "value", "valid_time", "available_at", "evidence_class",
                "admission_status", "source_id", "source_artifact_sha256",
            ]),
            feature_names=("tributary_flow",),
            admission_certificate=certificate,
            split_contract=split_contract,
            normalizer_artifact=normalizer_artifact,
            timestamp_timezone="UTC",
        )


def test_forcing_adapter_requires_explicit_timezone_for_naive_hydro_timestamps():
    dataset = build_hydrocontrol_dam_gk_dataset(
        _panel(), horizon_hours=3, systems=["alpha"], temporal_split="train"
    )
    certificate = evaluate_gwm_forcing_admission(
        source_id="candidate",
        feature_names=("rain",),
        checks={gate: True for gate in GWM_FORCING_ADMISSION_GATES},
    )
    split_contract, normalizer_artifact = _normalizer(("rain",))
    with pytest.raises(ValueError, match="timestamp_timezone_required"):
        attach_hydrocontrol_forcing_context(
            dataset,
            pd.DataFrame(),
            feature_names=("rain",),
            admission_certificate=certificate,
            split_contract=split_contract,
            normalizer_artifact=normalizer_artifact,
            timestamp_timezone="",
        )


def test_forcing_adapter_normalizes_non_utc_origins_across_dst_jump():
    timestamps = pd.DatetimeIndex(
        [
            "2024-03-10T00:00:00",
            "2024-03-10T01:00:00",
            "2024-03-10T03:00:00",
            "2024-03-10T04:00:00",
            "2024-03-10T06:00:00",
            "2024-03-10T07:00:00",
            "2024-03-10T09:00:00",
            "2024-03-10T10:00:00",
        ]
    )
    panel = pd.DataFrame(
        {
            "system_id": "alpha",
            "timestamp": timestamps,
            "temporal_split": "train",
            "effective_release_cfs": np.arange(len(timestamps)) + 100.0,
            "effective_release_change_cfs": np.arange(len(timestamps)) - 4.0,
            "downstream_flow_cfs": np.arange(len(timestamps)) + 200.0,
            "admitted_current_state_action": True,
            "dst_transition_day": False,
        }
    )
    dataset = build_hydrocontrol_dam_gk_dataset(
        panel, horizon_hours=3, systems=["alpha"], temporal_split="train"
    )
    rows = []
    for timestamp in dataset.input_timestamps:
        aware_timestamp = timestamp.tz_localize(
            "America/Los_Angeles", ambiguous="raise", nonexistent="raise"
        )
        rows.append(
            {
                "system_id": "alpha",
                "timestamp": timestamp,
                "step_index": 0,
                "feature_name": "rain",
                "value": 1.0,
                "valid_time": aware_timestamp,
                "available_at": aware_timestamp,
                "evidence_class": "observed",
                "admission_status": "admitted",
                "source_id": "official-source",
                "source_artifact_sha256": "a" * 64,
            }
        )
    certificate = evaluate_gwm_forcing_admission(
        source_id="official-source",
        feature_names=("rain",),
        checks={gate: True for gate in GWM_FORCING_ADMISSION_GATES},
    )
    split_contract, normalizer_artifact = _normalizer(("rain",))

    _, compilation = attach_hydrocontrol_forcing_context(
        dataset,
        pd.DataFrame(rows),
        feature_names=("rain",),
        admission_certificate=certificate,
        split_contract=split_contract,
        normalizer_artifact=normalizer_artifact,
        timestamp_timezone="America/Los_Angeles",
    )

    distinct_origins = compilation.forecast_origins[::2]
    assert distinct_origins[0] == pd.Timestamp("2024-03-10T08:00:00Z")
    assert distinct_origins[1] == pd.Timestamp("2024-03-10T09:00:00Z")
    assert distinct_origins[2] == pd.Timestamp("2024-03-10T10:00:00Z")
    assert distinct_origins[2] - distinct_origins[1] == pd.Timedelta(hours=1)
