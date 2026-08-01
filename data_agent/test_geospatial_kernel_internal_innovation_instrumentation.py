from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2.branching_kinematic_wave import (
    BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
    BranchingFiniteVolumeKinematicWaveOperator,
    BranchingKinematicWaveConfig,
)
from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
    ObservedInternalBoundaryReplacement,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachHydraulicGeometry,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.internal_innovation_instrumentation import (
    EDGE_AXIS_SCHEMA,
    EDGE_FLUX_SCHEMA,
    FEATURE_AXIS_SCHEMA,
    REACH_STATE_SCHEMA,
    STEP_MASS_LEDGER_SCHEMA,
    InternalInnovationTelemetryConfig,
    InternalInnovationTelemetryRecorder,
    write_hash_bound_internal_innovation_artifacts,
)
from scripts import assess_geospatial_kernel_internal_innovation_readiness as readiness

ISSUE = datetime(2024, 1, 1, tzinfo=UTC)
START = ISSUE + timedelta(hours=1)
END = START + timedelta(hours=1)


def _network() -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="internal-telemetry-y",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(1000.0, 800.0, 900.0),
        effective_lengths_m=(1000.0, 800.0, 900.0),
        action_entry_feature_ids=(10, 20),
        provenance_id="internal-telemetry:network",
        evidence_level="derived",
        admitted=True,
    )


def _geometry() -> ReachHydraulicGeometry:
    return ReachHydraulicGeometry(
        feature_ids=(30, 10, 20),
        bottom_width_m=(10.0, 8.0, 9.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.001, 0.0015, 0.0012),
        manning_n=(0.04, 0.045, 0.042),
        provenance_id="internal-telemetry:geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _config(operator_schema: str) -> InternalInnovationTelemetryConfig:
    return InternalInnovationTelemetryConfig(
        system_id="test_system",
        forecast_issue_time=ISSUE,
        operator_schema=operator_schema,
        provenance_id="internal-telemetry:test",
        evidence_level="derived",
        admitted=True,
    )


def test_manning_step_compiles_five_aligned_internal_artifacts() -> None:
    network = _network()
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    initial = StockState((8000.0, 5000.0, 6000.0), "m3", "initial")
    result = operator.step(
        initial,
        _geometry(),
        action=ActionBoundaryFlux(
            (0.0, 1.0, 2.0),
            "m3 s-1",
            "action",
        ),
        forcing=ForcingFlux(
            (0.1, 0.2, 0.3),
            "m3 s-1",
            "forcing",
            modeled=True,
        ),
    )
    recorder = InternalInnovationTelemetryRecorder(
        network,
        _config(BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA),
    )

    recorder.record_step(
        initial,
        result,
        support_start=START,
        support_end=END,
        inputs_available_at=ISSUE,
        input_provenance_ids=("action", "forcing"),
    )
    bundle = recorder.compile()

    assert bundle.step_count == 1
    assert bundle.source_steps_admitted is True
    assert bundle.diagnostic_only is False
    assert set(bundle.artifacts) == set(readiness.REQUIRED_INTERNAL_ARTIFACTS)
    assert bundle.artifacts["feature_axis_artifact"]["schema"] == FEATURE_AXIS_SCHEMA
    assert bundle.artifacts["edge_axis_artifact"]["schema"] == EDGE_AXIS_SCHEMA
    assert bundle.artifacts["reach_state_artifact"]["schema"] == REACH_STATE_SCHEMA
    assert bundle.artifacts["edge_flux_artifact"]["schema"] == EDGE_FLUX_SCHEMA
    assert bundle.artifacts["step_mass_ledger_artifact"]["schema"] == STEP_MASS_LEDGER_SCHEMA
    assert [row["edge_key"] for row in bundle.artifacts["edge_axis_artifact"]["edges"]] == [
        "reach:10->reach:30",
        "reach:20->reach:30",
    ]
    assert [
        row["base_mean_flux_m3s"] for row in bundle.artifacts["edge_flux_artifact"]["rows"]
    ] == pytest.approx(result.reach_mean_outflow_m3s[1:])
    assert all(bundle.alignment_assertions.values())


def test_kinematic_cells_are_aggregated_to_the_immutable_reach_axis() -> None:
    network = _network()
    operator = BranchingFiniteVolumeKinematicWaveOperator(
        network,
        _geometry(),
        BranchingKinematicWaveConfig(
            timestep_seconds=3600.0,
            target_cell_length_m=500.0,
            operator_form_admitted=True,
        ),
    )
    initial = operator.discharge_state(
        (3.0, 1.0, 2.0),
        provenance_id="kinematic-initial",
    )
    result = operator.step(
        initial,
        action=ActionBoundaryFlux(
            (0.0, 1.0, 2.0),
            "m3 s-1",
            "action",
        ),
        provenance_id="kinematic-next",
    )
    recorder = InternalInnovationTelemetryRecorder(
        network,
        _config(BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA),
    )

    recorder.record_step(
        initial,
        result,
        support_start=START,
        support_end=END,
        inputs_available_at=ISSUE,
        input_provenance_ids=("action",),
    )
    bundle = recorder.compile()

    rows = bundle.artifacts["reach_state_artifact"]["rows"]
    assert len(rows) == len(network.feature_ids)
    assert sum(float(row["initial_stock_m3"]) for row in rows) == pytest.approx(
        result.initial_network_storage_m3
    )
    assert sum(float(row["final_stock_m3"]) for row in rows) == pytest.approx(
        result.final_network_storage_m3
    )
    assert all(row["ground_truth"] is False for row in rows)
    assert bundle.artifacts["edge_flux_artifact"]["claim_boundary"] == {
        "physical_base_flux": True,
        "observed_flux_truth": False,
        "innovation_values_included": False,
    }


def test_time_leakage_and_operator_substitution_fail_closed() -> None:
    network = _network()
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    initial = StockState((8000.0, 5000.0, 6000.0), "m3", "initial")
    result = operator.step(initial, _geometry())
    recorder = InternalInnovationTelemetryRecorder(
        network,
        _config(BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA),
    )

    with pytest.raises(ValueError, match="inputs_unavailable_at_issue"):
        recorder.record_step(
            initial,
            result,
            support_start=START,
            support_end=END,
            inputs_available_at=ISSUE + timedelta(seconds=1),
            input_provenance_ids=("state-only",),
        )


def test_discontinuous_state_and_unobservable_internal_replacement_fail_closed() -> None:
    network = _network()
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    initial = StockState((8000.0, 5000.0, 6000.0), "m3", "initial")
    result = operator.step(initial, _geometry())
    recorder = InternalInnovationTelemetryRecorder(
        network,
        _config(BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA),
    )
    recorder.record_step(
        initial,
        result,
        support_start=START,
        support_end=END,
        inputs_available_at=ISSUE,
        input_provenance_ids=("state-only",),
    )
    disconnected = StockState((1.0, 2.0, 3.0), "m3", "disconnected")
    disconnected_result = operator.step(disconnected, _geometry())

    with pytest.raises(ValueError, match="state_transition_discontinuity"):
        recorder.record_step(
            disconnected,
            disconnected_result,
            support_start=END,
            support_end=END + timedelta(hours=1),
            inputs_available_at=ISSUE,
            input_provenance_ids=("state-only",),
        )

    replacement_result = operator.step(
        initial,
        _geometry(),
        internal_boundary=ObservedInternalBoundaryReplacement(
            feature_ids=(30,),
            values=(1.0,),
            unit="m3 s-1",
            provenance_id="observed-internal-boundary",
            evidence_level="authoritative",
            admitted=True,
            archive_revised=False,
            operational_vintage_verified=True,
        ),
    )
    with pytest.raises(ValueError, match="edge_flux_unobservable"):
        InternalInnovationTelemetryRecorder(
            network,
            _config(BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA),
        ).record_step(
            initial,
            replacement_result,
            support_start=START,
            support_end=END,
            inputs_available_at=ISSUE,
            input_provenance_ids=("observed-internal-boundary",),
        )

    kinematic_config = replace(
        _config(BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA),
        operator_schema=BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
    )
    with pytest.raises(TypeError, match="kinematic_step_required"):
        InternalInnovationTelemetryRecorder(network, kinematic_config).record_step(
            initial,
            result,
            support_start=START,
            support_end=END,
            inputs_available_at=ISSUE,
            input_provenance_ids=("state-only",),
        )


def test_writer_is_hash_bound_immutable_and_readiness_compatible(
    tmp_path: Path,
) -> None:
    network = _network()
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    initial = StockState((8000.0, 5000.0, 6000.0), "m3", "initial")
    result = operator.step(initial, _geometry())
    recorder = InternalInnovationTelemetryRecorder(
        network,
        _config(BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA),
    )
    recorder.record_step(
        initial,
        result,
        support_start=START,
        support_end=END,
        inputs_available_at=ISSUE,
        input_provenance_ids=("state-only",),
    )
    output = tmp_path / "telemetry"

    descriptors = write_hash_bound_internal_innovation_artifacts(
        recorder.compile(),
        output,
        repo_root=tmp_path,
    )

    for artifact_name, schema in readiness.REQUIRED_INTERNAL_ARTIFACTS.items():
        descriptor = descriptors[artifact_name]
        path = tmp_path / str(descriptor["path"])
        body = path.read_bytes()
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]
        assert json.loads(body)["schema"] == schema

    prediction = tmp_path / "prediction.csv"
    prediction.write_text("time,prediction\n", encoding="utf-8")
    prediction_body = prediction.read_bytes()
    combination = readiness._assess_combination(
        root=tmp_path,
        rollout_id="test",
        system_id="test_system",
        system={
            "system_id": "test_system",
            "prediction_artifact": {
                "path": prediction.relative_to(tmp_path).as_posix(),
                "sha256": hashlib.sha256(prediction_body).hexdigest(),
                "size_bytes": len(prediction_body),
            },
            "registered_execution": {"operator": "fixture"},
            "invariants": {"actual_conservation_passed": True},
            "internal_innovation_artifacts": descriptors,
        },
        source_identity_matches=True,
        report_contract_matches=True,
    )
    assert combination["internal_innovation_fit_ready"] is True

    feature_axis = output / "feature_axis.json"
    feature_axis.write_text("changed\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="artifact_conflict"):
        write_hash_bound_internal_innovation_artifacts(
            recorder.compile(),
            output,
            repo_root=tmp_path,
        )

    conflict_output = tmp_path / "preflight-conflict"
    conflict_output.mkdir()
    (conflict_output / "step_mass_ledger.json").write_text(
        "changed\n",
        encoding="utf-8",
    )
    with pytest.raises(FileExistsError, match="artifact_conflict"):
        write_hash_bound_internal_innovation_artifacts(
            recorder.compile(),
            conflict_output,
            repo_root=tmp_path,
        )
    assert not (conflict_output / "feature_axis.json").exists()
