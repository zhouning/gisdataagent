from __future__ import annotations

import copy
import csv
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    BoundaryOperator,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    CausalDischargeObservation,
    CausalManningDischargeStateUpdater,
    CausalObservationUpdateConfig,
    ConservativeFluxConfig,
    ConservativeFluxOperator,
    DirectedReachNetwork,
    EdgeFlux,
    EvaluationSplit,
    EvidenceStructure,
    ForcingFlux,
    GeoComplex,
    GeoTransportEvaluationSeries,
    HierarchyOperator,
    HoldoutReachDomain,
    HourlyReachInput,
    LinearReferencedPath,
    MetricStructure,
    ModeledTributaryBoundaryFlux,
    NwmQlatPlan,
    NwmStreamflowSchema,
    NwmVelocitySchema,
    NwmZarrSchema,
    NonlinearManningReachTransportOperator,
    NonlinearReachTransportConfig,
    ObservationField,
    ObservedInternalBoundaryReplacement,
    ReachHydraulicGeometry,
    ReachHydraulicState,
    ReachForcingSupport,
    ReachTransportConfig,
    SourceSinkFlux,
    StockState,
    StateDependentReachTransportOperator,
    TemporalSupport,
    TrouteMuskingumCungeAdapter,
    TrouteMuskingumCungeParameters,
    TrouteMuskingumCungeState,
    TravelTimePrior,
    TributaryConfluence,
    build_metadata_requests,
    build_nwm_q_lateral_plan,
    build_value_requests,
    evaluate_geotransport,
    evaluate_reservoir_conservation,
    extract_nwm_q_lateral,
    extract_nwm_streamflow,
    extract_nwm_velocity,
    load_public_data_registry,
    load_nwm_zarr_schema,
    load_nwm_streamflow_schema,
    validate_public_data_registry,
    execute_holdout_rollout,
    score_holdout_rollout,
)
from scripts.probe_geotransport_nldi_paths import summarize_path
from scripts.audit_geotransport_nwm_q_lateral_smoke import audit as audit_nwm_smoke
from scripts.build_geotransport_center_hill_smoke_panel import compile_panel
from scripts.build_geotransport_center_hill_672h_development_panel import (
    compile_panel as compile_development_panel,
)
from scripts.build_geotransport_center_hill_672h_reach_transport_rollout import (
    compile_rollout as compile_reach_transport_rollout,
)
from scripts.build_geotransport_center_hill_reach_transport_smoke import (
    compile_smoke as compile_reach_transport_smoke,
)
from scripts.build_geotransport_center_hill_travel_time_prior import compile_prior
from scripts.freeze_geotransport_center_hill_evaluation_protocol import (
    compile_protocol as compile_center_hill_evaluation_protocol,
)
from scripts.acquire_geotransport_center_hill_evaluation_nwm import (
    compile_plan as compile_center_hill_evaluation_nwm_plan,
)
from scripts.acquire_geotransport_center_hill_initial_state_v3 import (
    _compile_initial_state,
    _compound_area_at_depth,
    _depth_for_compound_area,
    compile_plan as compile_center_hill_initial_state_plan,
)
from scripts.audit_geotransport_center_hill_terminal_forcing_support import (
    NHDPLUS_ARCHIVE_SHA256,
    NHDPLUS_ARCHIVE_SIZE,
    compile_plan as compile_center_hill_terminal_support_plan,
)
from scripts.build_geotransport_center_hill_evaluation_panel import (
    compile_panel as compile_center_hill_evaluation_panel,
)
from scripts.diagnose_geotransport_center_hill_v1_zero_action import (
    compile_invariant as compile_center_hill_v1_zero_action_invariant,
)
from scripts.acquire_geotransport_public_route_link_audit import (
    compile_plan as compile_public_route_link_audit_plan,
)
from scripts.acquire_geotransport_troute_mc_source import (
    compile_plan as compile_troute_mc_source_plan,
)
from scripts.build_geotransport_kernel_v2_nonlinear_manning_invariants import (
    compile_invariants as compile_kernel_v2_nonlinear_manning_invariants,
)
from scripts.build_geotransport_kernel_v2_causal_support_invariants import (
    compile_invariants as compile_kernel_v2_causal_support_invariants,
)
import scripts.extract_geotransport_nwm_q_lateral as nwm_extraction_script
from scripts.run_geotransport_center_hill_v2_outcome_free import (
    ACTION_MANIFEST_SCHEMA as CENTER_HILL_V2_ACTION_MANIFEST_SCHEMA,
    FORCING_MANIFEST_SCHEMA as CENTER_HILL_V2_FORCING_MANIFEST_SCHEMA,
    _validate_input_manifests as validate_center_hill_v2_input_manifests,
    compile_domain as compile_center_hill_v2_domain,
)
from scripts.freeze_geotransport_center_hill_v2_d3_protocol import (
    compile_protocol as compile_center_hill_v2_d3_protocol,
)
from scripts.reproduce_geotransport_center_hill_v2_d3_score import (
    compile_reproduced_score as compile_center_hill_v2_d3_score,
)
from scripts.audit_geotransport_center_hill_v2_d4_topology import (
    compile_report as compile_center_hill_v2_d4_topology,
)
from scripts.acquire_geotransport_center_hill_v2_d4_tributary_boundary import (
    compile_plan as compile_center_hill_v2_d4_boundary_plan,
)
from scripts.run_geotransport_center_hill_v2_d4_boundary_outcome_free import (
    compile_rollout as compile_center_hill_v2_d4_boundary_rollout,
)
from scripts.score_geotransport_center_hill_v2_d4_boundary_diagnostic import (
    compile_score as compile_center_hill_v2_d4_boundary_score,
)


def _complex(*, admitted: tuple[bool, bool] = (True, True)) -> GeoComplex:
    return GeoComplex(
        B=BoundaryOperator(
            node_keys=("reservoir", "reach-1", "gauge"),
            edge_keys=("release-reach", "reach-gauge"),
            source_indices=(0, 1),
            target_indices=(1, 2),
        ),
        H=HierarchyOperator(
            parent_keys=("basin",),
            node_parent_indices=(0, 0, 0),
            aggregation_weights=(1.0, 1.0, 1.0),
        ),
        M=MetricStructure(
            node_measure=(1.0, 1.0, 1.0),
            edge_capacity_per_second=(5.0, 5.0),
            edge_travel_time_seconds=(3600.0, 7200.0),
        ),
        E=EvidenceStructure(
            edge_admitted=admitted,
            edge_source_ids=("nldi:1", "nldi:2"),
            evidence_level=("authoritative", "authoritative"),
        ),
        crs="EPSG:5070",
    )


def _operator(complex_: GeoComplex | None = None) -> ConservativeFluxOperator:
    return ConservativeFluxOperator(
        complex_ or _complex(),
        ConservativeFluxConfig(
            stock_unit="m3",
            flux_unit="m3 s-1",
            timestep_seconds=1.0,
        ),
    )


def _branching_network() -> DirectedReachNetwork:
    return DirectedReachNetwork(
        network_id="synthetic-y",
        feature_ids=(30, 10, 20),
        downstream_feature_ids=(None, 30, 30),
        full_lengths_m=(100.0, 100.0, 100.0),
        effective_lengths_m=(100.0, 100.0, 100.0),
        action_entry_feature_ids=(10,),
        provenance_id="synthetic:topology",
        evidence_level="derived",
        admitted=True,
    )


def _branching_geometry() -> ReachHydraulicGeometry:
    return ReachHydraulicGeometry(
        feature_ids=(30, 10, 20),
        bottom_width_m=(10.0, 10.0, 10.0),
        side_slope_horizontal_per_vertical=(2.0, 2.0, 2.0),
        bed_slope=(0.001, 0.001, 0.001),
        manning_n=(0.04, 0.04, 0.04),
        provenance_id="synthetic:geometry",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def _external_confluence() -> TributaryConfluence:
    return TributaryConfluence(
        tributary_feature_id=99,
        receiving_feature_id=30,
        longitude=-85.0,
        latitude=36.0,
        upstream_network_compiled=False,
        provenance_id="synthetic:nldi",
        evidence_level="derived",
        admitted=True,
    )


def test_directed_reach_network_compiles_branch_order_and_rejects_cycles():
    network = _branching_network()

    assert network.topological_feature_ids == (10, 20, 30)
    assert network.source_feature_ids == (10, 20)
    assert network.confluence_feature_ids == (30,)
    assert network.outlet_feature_id == 30

    with pytest.raises(ValueError, match="directed_reach_network_cycle_detected"):
        replace(
            network,
            downstream_feature_ids=(None, 20, 10),
        )


def test_branching_network_confluence_transition_is_globally_conservative():
    network = _branching_network()
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=60.0,
            integration_substep_seconds=30.0,
            operator_form_admitted=True,
        ),
        external_confluences=(_external_confluence(),),
    )
    boundary = ModeledTributaryBoundaryFlux(
        feature_ids=network.feature_ids,
        values=(3.0, 0.0, 0.0),
        unit="m3 s-1",
        provenance_id="nwm:streamflow:test",
    )

    result = operator.step(
        operator.zero_state(provenance_id="synthetic:cold-start"),
        _branching_geometry(),
        action=ActionBoundaryFlux(
            (0.0, 1.0, 0.0), "m3 s-1", "synthetic:dam-action"
        ),
        forcing=ForcingFlux(
            (0.0, 0.0, 2.0),
            "m3 s-1",
            "synthetic:q-lateral",
            modeled=True,
        ),
        tributary_boundary=boundary,
    )

    assert result.action_input_volume_m3 == pytest.approx(60.0)
    assert result.distributed_forcing_volume_m3 == pytest.approx(120.0)
    assert result.modeled_tributary_boundary_volume_m3 == pytest.approx(180.0)
    assert result.total_input_volume_m3 == pytest.approx(360.0)
    assert result.final_network_storage_m3 + result.outlet_volume_m3 == pytest.approx(
        360.0
    )
    assert abs(result.global_mass_balance_residual_m3) < 1e-8
    assert result.nonlinear_transport_admitted is True
    assert result.modeled_tributary_boundary_used is True
    assert result.tributary_boundary_ground_truth is False
    assert result.tributary_boundary_possible_nudging is True
    assert result.independent_end_to_end_prediction is False

    with pytest.raises(
        ValueError, match="modeled_tributary_boundary_flux_ground_truth_forbidden"
    ):
        replace(boundary, ground_truth=True)
    with pytest.raises(
        ValueError, match="branching_network_boundary_outside_confluence"
    ):
        operator.step(
            operator.zero_state(provenance_id="synthetic:cold-start"),
            _branching_geometry(),
            tributary_boundary=replace(boundary, values=(0.0, 0.0, 1.0)),
        )

    partial_operator = BranchingManningNetworkTransportOperator(
        replace(network, full_lengths_m=(200.0, 100.0, 100.0)),
        BranchingNetworkTransportConfig(
            timestep_seconds=60.0,
            operator_form_admitted=True,
        ),
    )
    with pytest.raises(
        ValueError,
        match="branching_network_partial_forcing_requires_spatial_support",
    ):
        partial_operator.step(
            partial_operator.zero_state(provenance_id="synthetic:cold-start"),
            _branching_geometry(),
            forcing=ForcingFlux(
                (1.0, 0.0, 0.0),
                "m3 s-1",
                "synthetic:q-lateral",
                modeled=True,
            ),
        )


def test_observed_internal_boundary_replaces_upstream_transfer_with_paired_ledger():
    network = _branching_network()
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=60.0,
            integration_substep_seconds=30.0,
            operator_form_admitted=True,
        ),
    )
    boundary = ObservedInternalBoundaryReplacement(
        feature_ids=(30,),
        values=(4.0,),
        unit="m3 s-1",
        provenance_id="usgs:synthetic:interval-mean",
        evidence_level="derived",
        admitted=True,
        archive_revised=False,
        operational_vintage_verified=True,
    )
    initial = StockState(
        values=(0.0, 5000.0, 6000.0),
        unit="m3",
        provenance_id="synthetic:upstream-storage",
    )

    result = operator.step(
        initial,
        _branching_geometry(),
        internal_boundary=boundary,
    )

    assert result.observed_internal_boundary_input_volume_m3 == pytest.approx(240.0)
    assert result.displaced_upstream_outflow_volume_m3 > 0.0
    assert result.internal_boundary_net_analysis_volume_m3 == pytest.approx(
        240.0 - result.displaced_upstream_outflow_volume_m3
    )
    assert (
        result.final_network_storage_m3
        + result.outlet_volume_m3
        + result.displaced_upstream_outflow_volume_m3
    ) == pytest.approx(11000.0 + 240.0)
    assert abs(result.global_mass_balance_residual_m3) < 1e-8
    assert result.observed_internal_boundary_replacement_used is True
    assert result.internal_boundary_operational_vintage_verified is True
    assert result.independent_end_to_end_prediction is False
    assert result.nonlinear_transport_admitted is True

    zero_result = operator.step(
        initial,
        _branching_geometry(),
        internal_boundary=replace(boundary, values=(0.0,)),
    )
    assert zero_result.observed_internal_boundary_input_volume_m3 == 0.0
    assert zero_result.displaced_upstream_outflow_volume_m3 > 0.0
    assert zero_result.observed_internal_boundary_replacement_used is True
    assert (
        zero_result.final_network_storage_m3
        + zero_result.outlet_volume_m3
        + zero_result.displaced_upstream_outflow_volume_m3
    ) == pytest.approx(11000.0)

    with pytest.raises(ValueError, match="internal_boundary_requires_compiled_upstream"):
        operator.step(
            initial,
            _branching_geometry(),
            internal_boundary=replace(boundary, feature_ids=(20,)),
        )
    with pytest.raises(ValueError, match="observed_internal_boundary_admission_invalid"):
        replace(
            boundary,
            evidence_level="candidate",
            operational_vintage_verified=False,
        )


def test_center_hill_d4_topology_compiles_19_direct_nwm_boundaries(tmp_path: Path):
    report = compile_center_hill_v2_d4_topology(
        network_path=tmp_path / "branching_boundary_network.json"
    )

    assert report["status"] == "pass_direct_confluence_boundary_ready"
    assert report["data_isolation"]["d3_outcome_values_loaded"] is False
    assert report["domain"]["active_mainstem_feature_count"] == 26
    assert report["domain"]["direct_off_path_tributary_count"] == 19
    assert report["domain"]["receiving_mainstem_feature_count"] == 19
    assert report["nwm_boundary_crosswalk"][
        "all_direct_tributaries_present"
    ] is True
    assert report["nwm_boundary_crosswalk"][
        "streamflow_feature_chunk_indices"
    ] == [63, 87]
    assert report["adjudication"]["selected_first_executable_mode"] == (
        "modeled_tributary_boundary_flux"
    )
    assert report["claim_boundary"]["full_subnetwork_routing_ready"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_center_hill_d4_boundary_plan_and_rollout_remain_outcome_free(
    tmp_path: Path,
):
    plan, _, _, plan_report = compile_center_hill_v2_d4_boundary_plan()

    assert plan.time_count == 672
    assert len(plan.feature_ids) == 19
    assert plan.feature_chunk_indices == (63, 87)
    assert plan_report["semantic_contract"] == {
        "variable_role": "modeled_tributary_boundary_flux",
        "modeled": True,
        "ground_truth": False,
        "possible_nudging": True,
        "evaluation_outcome": False,
        "conservation_oracle": False,
    }
    output_path = tmp_path / "d4_boundary_predictions.csv"
    csv_body, rollout = compile_center_hill_v2_d4_boundary_rollout(
        output_path=output_path
    )
    assert rollout["status"] == "outcome_free_boundary_rollout_complete"
    assert rollout["prediction_artifact"]["sha256"] == hashlib.sha256(
        csv_body
    ).hexdigest()
    assert rollout["invariants"]["d3_mainstem_reference_reproduced"] is True
    assert rollout["invariants"]["boundary_conservation_passed"] is True
    assert rollout["data_isolation"]["outcome_values_loaded"] is False
    assert rollout["claim_boundary"]["independent_end_to_end_prediction"] is False


def test_center_hill_d4_post_hoc_score_has_no_activation_gate():
    report = compile_center_hill_v2_d4_boundary_score()

    assert report["status"] == "post_hoc_diagnostic_complete_no_activation_gate"
    assert report["window_role"]["prospective_holdout"] is False
    assert report["window_role"]["model_selection_allowed"] is False
    assert report["non_gating_diagnostics"]["d4_beats_d3_central_rmse"] is True
    assert report["non_gating_diagnostics"]["d4_beats_persistence_rmse"] is False
    assert report["claim_boundary"]["d4_predictive_improvement_validated"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_temporal_support_keeps_eop_label_separate_from_interval_bounds():
    support = TemporalSupport(
        kind="interval_mean",
        duration_seconds=3600.0,
        timestamp_position="end",
        provenance_id="official:test",
        evidence_level="authoritative",
    )
    label = datetime(2022, 1, 1, 1, tzinfo=timezone.utc)

    assert support.bounds(label) == (label - timedelta(hours=1), label)
    assert support.as_dict()["schema"] == "gwm.geospatial_kernel.temporal_support.v1"
    with pytest.raises(
        ValueError, match="instantaneous_support_requires_zero_duration_instant_label"
    ):
        TemporalSupport(
            kind="instantaneous",
            duration_seconds=3600.0,
            timestamp_position="end",
            provenance_id="invalid",
            evidence_level="derived",
        )


def test_linear_reference_and_travel_prior_keep_physical_quantity_explicit():
    path = LinearReferencedPath(
        path_id="action:gauge",
        feature_ids=(10, 11),
        full_lengths_m=(100.0, 200.0),
        entry_offsets_m=(100.0, 0.0),
        exit_offsets_m=(100.0, 80.0),
        provenance_id="nldi:test",
        evidence_level="derived",
    )
    assert path.effective_lengths_m == (0.0, 80.0)
    assert path.total_effective_length_m == pytest.approx(80.0)

    prior = TravelTimePrior(
        path_id=path.path_id,
        quantity="advective_residence_time",
        method="length_over_velocity",
        lower_seconds=60.0,
        central_seconds=90.0,
        upper_seconds=120.0,
        state_dependent=True,
        outcome_calibrated=False,
        admitted_as_flood_wave_lag=False,
        provenance_id="nwm:test",
        evidence_level="candidate",
    )
    assert prior.as_dict()["admitted_as_flood_wave_lag"] is False
    with pytest.raises(
        ValueError, match="only_flood_wave_quantity_may_be_admitted_as_lag"
    ):
        replace(prior, admitted_as_flood_wave_lag=True)
    with pytest.raises(
        ValueError, match="only_wave_celerity_quantity_may_be_admitted"
    ):
        ReachHydraulicState(
            feature_ids=(11,),
            propagation_speed_mps=(1.0,),
            quantity="river_velocity_proxy",
            provenance_id="nwm:test",
            evidence_level="derived",
            admitted_as_flood_wave_celerity=True,
        )


def test_reach_transport_matches_single_reservoir_analytic_solution():
    path = LinearReferencedPath(
        path_id="single",
        feature_ids=(11,),
        full_lengths_m=(100.0,),
        entry_offsets_m=(0.0,),
        exit_offsets_m=(100.0,),
        provenance_id="geometry:test",
        evidence_level="derived",
    )
    operator = StateDependentReachTransportOperator(
        path,
        ReachTransportConfig(
            timestep_seconds=10.0,
            path_admitted=True,
            operator_form_admitted=True,
        ),
    )
    hydraulics = ReachHydraulicState(
        feature_ids=(11,),
        propagation_speed_mps=(10.0,),
        quantity="flood_wave_celerity",
        provenance_id="hydraulics:test",
        evidence_level="authoritative",
        admitted_as_flood_wave_celerity=True,
    )

    result = operator.step(
        StockState((100.0,), "m3", "initial:test"),
        hydraulics,
    )

    expected_stock = 100.0 * np.exp(-1.0)
    assert result.next_stock.values == pytest.approx((expected_stock,))
    assert result.outlet_volume_m3 == pytest.approx(100.0 - expected_stock)
    assert result.reach_residence_time_seconds == pytest.approx((10.0,))
    assert result.global_mass_balance_residual_m3 == pytest.approx(0.0, abs=1e-10)
    assert result.flood_wave_transport_admitted is True
    assert result.diagnostic_only is False


def test_reach_transport_candidate_hydraulics_fail_closed_without_diagnostic_mode():
    path = LinearReferencedPath(
        path_id="candidate",
        feature_ids=(11,),
        full_lengths_m=(100.0,),
        entry_offsets_m=(0.0,),
        exit_offsets_m=(100.0,),
        provenance_id="geometry:test",
        evidence_level="derived",
    )
    hydraulics = ReachHydraulicState(
        feature_ids=(11,),
        propagation_speed_mps=(1.0,),
        quantity="river_velocity_proxy",
        provenance_id="nwm:test",
        evidence_level="candidate",
        admitted_as_flood_wave_celerity=False,
    )
    operator = StateDependentReachTransportOperator(
        path,
        ReachTransportConfig(timestep_seconds=3600.0),
    )

    with pytest.raises(
        ValueError,
        match=(
            "unadmitted_reach_transport_components_require_explicit_diagnostic_mode"
        ),
    ):
        operator.step(operator.zero_state(provenance_id="cold-start"), hydraulics)

    diagnostic = StateDependentReachTransportOperator(
        path,
        ReachTransportConfig(
            timestep_seconds=3600.0,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    ).step(
        StockState((1.0,), "m3", "initial:test"),
        hydraulics,
    )
    assert diagnostic.flood_wave_transport_admitted is False
    assert diagnostic.diagnostic_only is True


def test_reach_transport_is_directional_state_dependent_and_conservative():
    path = LinearReferencedPath(
        path_id="zero-action-reach:two-active-reaches",
        feature_ids=(10, 11, 12),
        full_lengths_m=(50.0, 100.0, 200.0),
        entry_offsets_m=(50.0, 0.0, 0.0),
        exit_offsets_m=(50.0, 100.0, 200.0),
        provenance_id="geometry:test",
        evidence_level="derived",
    )
    config = ReachTransportConfig(
        timestep_seconds=60.0,
        allow_unadmitted_components_for_diagnostics=True,
    )
    operator = StateDependentReachTransportOperator(path, config)
    slow = ReachHydraulicState(
        feature_ids=(11, 12),
        propagation_speed_mps=(1.0, 1.0),
        quantity="river_velocity_proxy",
        provenance_id="nwm:slow",
        evidence_level="candidate",
        admitted_as_flood_wave_celerity=False,
    )
    fast = replace(
        slow,
        propagation_speed_mps=(10.0, 10.0),
        provenance_id="nwm:fast",
    )
    action = ActionBoundaryFlux((2.0, 0.0), "m3 s-1", "release:test")
    forcing = ForcingFlux(
        (0.0, 1.0),
        "m3 s-1",
        "lateral:test",
        modeled=True,
    )
    initial = operator.zero_state(provenance_id="cold-start")

    slow_result = operator.step(
        initial,
        slow,
        action=action,
        forcing=forcing,
    )
    fast_result = operator.step(
        initial,
        fast,
        action=action,
        forcing=forcing,
    )

    assert slow_result.active_feature_ids == (11, 12)
    assert slow_result.excluded_zero_length_feature_ids == (10,)
    assert slow_result.input_volume_m3 == pytest.approx(180.0)
    assert (
        sum(slow_result.next_stock.values) + slow_result.outlet_volume_m3
    ) == pytest.approx(180.0)
    assert abs(slow_result.global_mass_balance_residual_m3) < 1e-9
    assert abs(fast_result.global_mass_balance_residual_m3) < 1e-9
    assert fast_result.outlet_volume_m3 > slow_result.outlet_volume_m3
    assert sum(fast_result.next_stock.values) < sum(slow_result.next_stock.values)

    with pytest.raises(
        ValueError, match="reach_transport_action_must_enter_path_boundary"
    ):
        operator.step(
            initial,
            slow,
            action=ActionBoundaryFlux(
                (0.0, 2.0), "m3 s-1", "invalid-downstream-action"
            ),
        )


def test_frozen_v1_zero_action_failure_is_an_outcome_free_numeric_invariant():
    report = compile_center_hill_v1_zero_action_invariant().report

    assert report["status"] == "frozen_v1_failure_reproduced"
    assert report["data_isolation"] == {
        "outcome_values_loaded": False,
        "action_values_loaded": False,
        "panel_artifacts_loaded": False,
        "transition_inputs": [
            "linear_referenced_path",
            "nwm_q_lateral_modeled_forcing",
            "nwm_river_velocity_proxy",
        ],
    }
    failure = report["first_failure"]
    assert failure["support_start_utc"] == "2021-12-14T11:00:00Z"
    assert failure["operator_error"] == "reach_transport_global_mass_balance_exceeded"
    assert failure["failure_stage"] == "post_componentwise_near_zero_cleanup"
    assert abs(failure["raw_mass_balance_residual_m3"]) <= failure[
        "numeric_tolerance_m3"
    ]
    assert abs(failure["cleaned_mass_balance_residual_m3"]) > failure[
        "numeric_tolerance_m3"
    ]
    assert report["diagnosis"]["scientific_adjudication_changed"] is False
    assert report["v2_invariant_lock"]["outcome_access_permitted"] is False


def test_public_route_link_acquisition_plan_is_fixed_bounded_and_fail_closed():
    plan = compile_public_route_link_audit_plan()

    assert plan["mode"] == "plan"
    assert len(plan["requests"]) == 5
    assert {item["repository"] for item in plan["requests"]} == {
        "NCAR/wrf_hydro_nwm_public",
        "NOAA-OWP/t-route",
    }
    assert all(len(item["commit"]) == 40 for item in plan["requests"])
    boundary = plan["request_boundary"]
    assert boundary["planned_maximum_bytes"] <= boundary["maximum_total_bytes"]
    assert plan["required_parameter_contract"][
        "no_default_parameter_substitution"
    ] is True
    assert plan["claim_boundary"]["center_hill_muskingum_cunge_admitted"] is False


def test_troute_mc_source_plan_is_fixed_bounded_and_runtime_fail_closed():
    plan = compile_troute_mc_source_plan()

    assert plan["mode"] == "plan"
    assert len(plan["requests"]) == 8
    assert {item["repository"] for item in plan["requests"]} == {
        "NOAA-OWP/t-route"
    }
    assert {item["commit"] for item in plan["requests"]} == {plan["commit"]}
    assert plan["request_boundary"]["planned_maximum_bytes"] <= plan[
        "request_boundary"
    ]["maximum_total_bytes"]
    assert plan["runtime_contract"]["entrypoint"] == "c_muskingcungenwm"
    assert plan["claim_boundary"]["runtime_built"] is False
    assert plan["claim_boundary"]["center_hill_execution_admitted"] is False


class _EquationConsistentMcKernel:
    source_commit = "12a8eae0cdfed437143c590659fa7077605a5e70"

    def __init__(self) -> None:
        self.calls: list[dict[str, float]] = []

    def step_segment(self, **values: float) -> tuple[float, ...]:
        self.calls.append(dict(values))
        # K=dt and X=0.25 give C1/C2/C3/C4 = 0.6/0.2/0.2/0.8.
        qdc = (
            0.6 * values["qup"]
            + 0.2 * values["quc"]
            + 0.2 * values["qdp"]
            + 0.8 * values["ql"]
        )
        return qdc, 1.0, 0.5, values["dx"] / values["dt"], 1.0, 0.25


def _troute_mc_parameters() -> TrouteMuskingumCungeParameters:
    return TrouteMuskingumCungeParameters(
        feature_ids=(101, 102),
        length_m=(300.0, 600.0),
        bottom_width_m=(10.0, 20.0),
        top_width_m=(12.0, 25.0),
        compound_top_width_m=(30.0, 50.0),
        manning_n=(0.03, 0.04),
        compound_manning_n=(0.06, 0.08),
        channel_side_slope_chslp=(0.5, 0.25),
        bed_slope=(0.01, 0.001),
        provenance_id="route-link:test",
    )


def test_troute_mc_adapter_preserves_official_qvd_order_and_path_recursion():
    kernel = _EquationConsistentMcKernel()
    parameters = _troute_mc_parameters()
    adapter = TrouteMuskingumCungeAdapter(
        parameters, kernel, timestep_seconds=300.0
    )
    result = adapter.step(
        adapter.zero_state(provenance_id="cold:test"),
        boundary_previous_m3s=0.0,
        boundary_current_m3s=10.0,
        lateral_inflow_m3s=(1.0, 2.0),
        provenance_id="step:test",
    )

    assert result.next_state.discharge_m3s == pytest.approx((2.8, 2.16))
    assert result.next_state.velocity_mps == (1.0, 1.0)
    assert result.next_state.depth_m == (0.5, 0.5)
    assert kernel.calls[1]["qup"] == 0.0
    assert kernel.calls[1]["quc"] == pytest.approx(2.8)
    assert parameters.side_slope_horizontal_per_vertical == (2.0, 4.0)
    assert abs(result.network_reconstructed_equation_residual_m3) < 1e-10
    assert (
        result.returned_ck_x_authoritative_for_equation_reconstruction is False
    )


def test_troute_mc_adapter_rejects_wrong_commit_and_feature_axis():
    kernel = _EquationConsistentMcKernel()
    kernel.source_commit = "0" * 40
    with pytest.raises(ValueError, match="t_route_mc_kernel_commit_mismatch"):
        TrouteMuskingumCungeAdapter(
            _troute_mc_parameters(), kernel, timestep_seconds=300.0
        )

    valid = _EquationConsistentMcKernel()
    adapter = TrouteMuskingumCungeAdapter(
        _troute_mc_parameters(), valid, timestep_seconds=300.0
    )
    wrong_state = replace(
        adapter.zero_state(provenance_id="cold:test"), feature_ids=(102, 101)
    )
    with pytest.raises(ValueError, match="t_route_mc_state_feature_axis_mismatch"):
        adapter.step(
            wrong_state,
            boundary_previous_m3s=0.0,
            boundary_current_m3s=1.0,
            provenance_id="invalid:test",
        )


def _holdout_domain() -> HoldoutReachDomain:
    path = LinearReferencedPath(
        path_id="holdout:test",
        feature_ids=(101, 102),
        full_lengths_m=(300.0, 800.0),
        entry_offsets_m=(0.0, 0.0),
        exit_offsets_m=(300.0, 600.0),
        provenance_id="path:test",
        evidence_level="derived",
    )
    geometry = ReachHydraulicGeometry(
        feature_ids=(101, 102),
        bottom_width_m=(10.0, 20.0),
        side_slope_horizontal_per_vertical=(2.0, 4.0),
        bed_slope=(0.01, 0.001),
        manning_n=(0.03, 0.04),
        provenance_id="geometry:test",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )

    def support(terminal_fraction: float, suffix: str) -> ReachForcingSupport:
        return ReachForcingSupport(
            feature_ids=(101, 102),
            coverage_fractions=(1.0, terminal_fraction),
            support_method=f"area_fraction:{suffix}",
            provenance_id=f"support:test:{suffix}",
            evidence_level="derived",
            admitted_as_spatial_support=True,
        )

    return HoldoutReachDomain(
        path=path,
        geometry=geometry,
        initial_stock=StockState((1000.0, 2000.0), "m3", "state:test"),
        forcing_support_central=support(0.5, "central"),
        forcing_support_lower=support(0.4, "lower"),
        forcing_support_upper=support(0.6, "upper"),
        t_route_parameters=_troute_mc_parameters(),
        t_route_initial_state=TrouteMuskingumCungeState(
            feature_ids=(101, 102),
            discharge_m3s=(1.0, 1.0),
            velocity_mps=(1.0, 1.0),
            depth_m=(0.5, 0.5),
            provenance_id="t-route-state:test",
        ),
        provenance_id="holdout-domain:test",
    )


def test_outcome_free_holdout_rollout_executes_fixed_scenarios_and_conserves():
    start = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
    inputs = tuple(
        HourlyReachInput(
            support_start_utc=start + timedelta(hours=index),
            support_end_utc=start + timedelta(hours=index + 1),
            action_release_m3s=5.0 + index,
            q_lateral_m3s=(1.0, 2.0),
            provenance_id=f"hour:{index}",
        )
        for index in range(3)
    )
    kernel = _EquationConsistentMcKernel()
    rollout = execute_holdout_rollout(inputs, _holdout_domain(), kernel)

    assert len(rollout.rows) == 3
    assert set(rollout.nonlinear_conservation) == {
        "nonlinear_central",
        "nonlinear_support_lower",
        "nonlinear_support_upper",
        "zero_action",
        "no_forcing",
        "state_only",
        "reversed_topology",
    }
    assert all(
        result["passed"] is True
        for result in rollout.nonlinear_conservation.values()
    )
    assert rollout.rows[0]["nonlinear_support_lower_m3s"] < rollout.rows[0][
        "nonlinear_support_upper_m3s"
    ]
    assert rollout.rows[0]["direct_release_m3s"] == 5.0
    assert len(kernel.calls) == 3 * 12 * 2
    assert kernel.calls[0]["qup"] == kernel.calls[0]["quc"] == 5.0
    assert kernel.calls[1]["ql"] == pytest.approx(1.0)
    assert rollout.as_dict()["outcome_values_loaded"] is False


def test_holdout_rollout_rejects_noncontiguous_inputs():
    start = datetime(2022, 2, 3, 1, tzinfo=timezone.utc)
    inputs = (
        HourlyReachInput(start, start + timedelta(hours=1), 1.0, (1.0, 1.0), "a"),
        HourlyReachInput(
            start + timedelta(hours=2),
            start + timedelta(hours=3),
            1.0,
            (1.0, 1.0),
            "b",
        ),
    )
    with pytest.raises(ValueError, match="inputs_must_be_contiguous"):
        execute_holdout_rollout(inputs, _holdout_domain(), _EquationConsistentMcKernel())


def test_independent_holdout_scorer_applies_registered_gates_without_selection():
    starts = [
        datetime(2022, 2, 3, 1, tzinfo=timezone.utc) + timedelta(hours=index)
        for index in range(3)
    ]
    observed_values = (10.0, 20.0, 30.0)
    rows = []
    for index, start in enumerate(starts):
        central = observed_values[index]
        rows.append(
            {
                "support_start_utc": start.isoformat(),
                "support_end_utc": (start + timedelta(hours=1)).isoformat(),
                "nonlinear_central_m3s": central,
                "nonlinear_support_lower_m3s": central - 0.5,
                "nonlinear_support_upper_m3s": central + 0.5,
                "zero_action_m3s": central + 5.0,
                "no_forcing_m3s": central - 5.0,
                "state_only_m3s": central + 8.0,
                "reversed_topology_m3s": central + 10.0,
                "t_route_mc_m3s": central - 3.0,
                "direct_release_m3s": central + 4.0,
            }
        )
    outcomes = {
        row["support_end_utc"]: observed
        for row, observed in zip(rows, observed_values, strict=True)
    }
    conservation = {
        name: {"passed": True}
        for name in (
            "nonlinear_central",
            "nonlinear_support_lower",
            "nonlinear_support_upper",
            "zero_action",
            "no_forcing",
            "state_only",
            "reversed_topology",
        )
    }
    report = score_holdout_rollout(
        rows,
        outcomes,
        prior_observation_m3s=5.0,
        nonlinear_conservation=conservation,
    )

    assert report["status"] == "pass"
    assert report["registered_gates"]["all_registered_gates_passed"] is True
    assert report["support_uncertainty"]["selection_rule"] == (
        "central_is_preselected;lower_and_upper_are_report_only"
    )
    assert report["claim_boundary"]["outcome_used_by_executor"] is False


def test_center_hill_v2_executor_manifest_rejects_outcome_metadata():
    action = {
        "schema": CENTER_HILL_V2_ACTION_MANIFEST_SCHEMA,
        "variable_role": "boundary_action",
        "outcome_included": False,
    }
    forcing = {
        "schema": CENTER_HILL_V2_FORCING_MANIFEST_SCHEMA,
        "variable_role": "modeled_forcing",
        "ground_truth": False,
        "time_chunk_indices": [561],
        "feature_chunk_indices": [63],
    }
    validate_center_hill_v2_input_manifests(action, forcing)
    forcing["usgs_observation"] = "forbidden"
    with pytest.raises(ValueError, match="manifest_contains_outcome_role"):
        validate_center_hill_v2_input_manifests(action, forcing)


def test_center_hill_v2_domain_compiles_d0_d1_d2_without_d3_values():
    domain, artifacts = compile_center_hill_v2_domain()
    assert len(domain.geometry.feature_ids) == 26
    assert domain.geometry.feature_ids[-1] == 18421703
    assert domain.t_route_parameters.length_m[0] == pytest.approx(1.5214577067411046)
    assert domain.t_route_parameters.length_m[-1] == pytest.approx(938.4308239178366)
    assert domain.forcing_support_lower.coverage_fractions[-1] == pytest.approx(
        0.8272045786997515
    )
    assert domain.forcing_support_upper.coverage_fractions[-1] == pytest.approx(
        0.9366451910995578
    )
    assert "initial_state_manifest" in artifacts


def test_center_hill_v2_d3_protocol_is_frozen_before_chunk_561_and_outcomes():
    protocol_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/geotransport_v0_1/center_hill_v2_d3_protocol.json"
    )
    frozen = json.loads(protocol_path.read_bytes())
    assert frozen == compile_center_hill_v2_d3_protocol()
    assert frozen["status"] == "frozen_before_d3_value_access"
    assert frozen["window"]["hour_count"] == 672
    assert frozen["window"]["warmup_hours"] == 0
    assert frozen["input_acquisition"]["modeled_forcing"][
        "time_chunk_indices"
    ] == [561]
    assert frozen["data_isolation_at_freeze"] == {
        "compile_protocol_reads_d0_d1_d2_only": True,
        "chunk_561_loaded": False,
        "q_lateral_561_63_values_loaded": False,
        "d3_action_values_loaded": False,
        "d3_outcome_values_loaded": False,
        "old_v1_prediction_or_score_loaded": False,
    }
    assert frozen["scenarios"]["preselected_candidate"] == "nonlinear_central"
    assert frozen["scoring"]["no_scenario_selection_after_outcome_access"] is True


def test_center_hill_v2_d3_failed_score_is_reproducible_without_value_changes():
    report_path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/geotransport_v0_1/center_hill_v2_d3_scoring_report.json"
    )
    frozen = json.loads(report_path.read_bytes())
    assert frozen == compile_center_hill_v2_d3_score()
    assert frozen["status"] == "fail"
    assert frozen["evaluation"]["scored_hour_count"] == 672
    assert frozen["evaluation"]["registered_gates"] == {
        "central_beats_persistence_rmse": False,
        "central_beats_t_route_mc_rmse": True,
        "state_only_is_worse_rmse": True,
        "zero_action_degrades_rmse": True,
        "no_forcing_degrades_rmse": True,
        "reversed_topology_degrades_rmse": False,
        "all_nonlinear_scenarios_conserve_mass": True,
        "all_registered_gates_passed": False,
    }
    assert all(value is False for value in (
        frozen["runtime_adapters"]["prediction_values_changed"],
        frozen["runtime_adapters"]["outcome_values_changed"],
        frozen["runtime_adapters"]["metrics_or_thresholds_changed"],
    ))


def _nonlinear_path(*, partial_last_reach: bool = False) -> LinearReferencedPath:
    return LinearReferencedPath(
        path_id="nonlinear:test",
        feature_ids=(101, 102),
        full_lengths_m=(1000.0, 2000.0),
        entry_offsets_m=(0.0, 0.0),
        exit_offsets_m=(1000.0, 1500.0 if partial_last_reach else 2000.0),
        provenance_id="geometry:path:test",
        evidence_level="derived",
    )


def _nonlinear_geometry(*, reverse: bool = False) -> ReachHydraulicGeometry:
    rows = [
        (101, 4.0, 0.5, 0.01, 0.035),
        (102, 25.0, 1.5, 0.0002, 0.06),
    ]
    if reverse:
        rows.reverse()
    return ReachHydraulicGeometry(
        feature_ids=tuple(row[0] for row in rows),
        bottom_width_m=tuple(row[1] for row in rows),
        side_slope_horizontal_per_vertical=tuple(row[2] for row in rows),
        bed_slope=tuple(row[3] for row in rows),
        manning_n=tuple(row[4] for row in rows),
        provenance_id="route-link:test",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )


def test_nonlinear_reach_transport_zero_state_and_mass_conservation():
    operator = NonlinearManningReachTransportOperator(
        _nonlinear_path(),
        NonlinearReachTransportConfig(
            timestep_seconds=3600.0,
            path_admitted=True,
            operator_form_admitted=True,
            integration_substep_seconds=300.0,
        ),
    )
    zero = operator.step(
        operator.zero_state(provenance_id="zero:test"),
        _nonlinear_geometry(),
    )
    assert zero.next_stock.values == (0.0, 0.0)
    assert zero.reach_mean_outflow_m3s == (0.0, 0.0)
    assert zero.global_mass_balance_residual_m3 == 0.0

    action = ActionBoundaryFlux((10.0, 0.0), "m3 s-1", "action:test")
    result = operator.step(
        operator.zero_state(provenance_id="cold:test"),
        _nonlinear_geometry(),
        action=action,
    )
    assert all(value >= 0.0 for value in result.next_stock.values)
    assert all(value >= 0.0 for value in result.reach_end_depth_m)
    assert result.input_volume_m3 == pytest.approx(36_000.0)
    assert (
        sum(result.next_stock.values) + result.outlet_volume_m3
    ) == pytest.approx(result.input_volume_m3, abs=result.numeric_mass_tolerance_m3)
    assert abs(result.global_mass_balance_residual_m3) <= (
        result.numeric_mass_tolerance_m3
    )
    assert result.nonlinear_transport_admitted is True
    assert result.diagnostic_only is False


def test_nonlinear_reach_transport_is_noncommutative_for_heterogeneous_geometry():
    config = NonlinearReachTransportConfig(
        timestep_seconds=3600.0,
        path_admitted=True,
        operator_form_admitted=True,
        integration_substep_seconds=300.0,
    )
    forward = NonlinearManningReachTransportOperator(_nonlinear_path(), config)
    reverse_path = LinearReferencedPath(
        path_id="nonlinear:reversed:test",
        feature_ids=(102, 101),
        full_lengths_m=(2000.0, 1000.0),
        entry_offsets_m=(0.0, 0.0),
        exit_offsets_m=(2000.0, 1000.0),
        provenance_id="geometry:path:reversed:test",
        evidence_level="derived",
    )
    reverse = NonlinearManningReachTransportOperator(reverse_path, config)
    action = ActionBoundaryFlux((10.0, 0.0), "m3 s-1", "action:test")

    forward_result = forward.step(
        forward.zero_state(provenance_id="cold:forward"),
        _nonlinear_geometry(),
        action=action,
    )
    reverse_result = reverse.step(
        reverse.zero_state(provenance_id="cold:reverse"),
        _nonlinear_geometry(reverse=True),
        action=action,
    )

    assert forward_result.outlet_mean_flow_m3s != pytest.approx(
        reverse_result.outlet_mean_flow_m3s, rel=1e-3, abs=1e-6
    )
    assert abs(forward_result.global_mass_balance_residual_m3) <= (
        forward_result.numeric_mass_tolerance_m3
    )
    assert abs(reverse_result.global_mass_balance_residual_m3) <= (
        reverse_result.numeric_mass_tolerance_m3
    )


def test_nonlinear_reach_transport_blocks_partial_forcing_without_support():
    operator = NonlinearManningReachTransportOperator(
        _nonlinear_path(partial_last_reach=True),
        NonlinearReachTransportConfig(
            timestep_seconds=3600.0,
            path_admitted=True,
            operator_form_admitted=True,
        ),
    )
    with pytest.raises(
        ValueError, match="partial_reach_forcing_requires_admitted_spatial_support"
    ):
        operator.step(
            operator.zero_state(provenance_id="cold:partial"),
            _nonlinear_geometry(),
            forcing=ForcingFlux(
                (0.0, 1.0), "m3 s-1", "forcing:full-reach", modeled=True
            ),
        )


def test_nonlinear_reach_transport_projects_admitted_partial_forcing_support():
    operator = NonlinearManningReachTransportOperator(
        _nonlinear_path(partial_last_reach=True),
        NonlinearReachTransportConfig(
            timestep_seconds=3600.0,
            path_admitted=True,
            operator_form_admitted=True,
        ),
    )
    support = ReachForcingSupport(
        feature_ids=(101, 102),
        coverage_fractions=(1.0, 0.4),
        support_method="authoritative_catchment_intersection",
        provenance_id="gis:partial-support:test",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    result = operator.step(
        operator.zero_state(provenance_id="cold:partial"),
        _nonlinear_geometry(),
        forcing=ForcingFlux(
            (0.0, 1.0), "m3 s-1", "forcing:full-reach", modeled=True
        ),
        forcing_support=support,
    )

    assert result.forcing_support_required is True
    assert result.forcing_support_admitted is True
    assert result.forcing_coverage_fractions == (1.0, 0.4)
    assert result.raw_forcing_volume_m3 == pytest.approx(3600.0)
    assert result.applied_forcing_volume_m3 == pytest.approx(1440.0)
    assert result.excluded_forcing_volume_m3 == pytest.approx(2160.0)
    assert result.input_volume_m3 == pytest.approx(1440.0)
    assert abs(result.global_mass_balance_residual_m3) <= (
        result.numeric_mass_tolerance_m3
    )
    assert result.nonlinear_transport_admitted is True


def test_nonlinear_reach_transport_allows_full_reach_only_forcing_on_partial_path():
    operator = NonlinearManningReachTransportOperator(
        _nonlinear_path(partial_last_reach=True),
        NonlinearReachTransportConfig(
            timestep_seconds=3600.0,
            path_admitted=True,
            operator_form_admitted=True,
        ),
    )
    result = operator.step(
        operator.zero_state(provenance_id="cold:partial"),
        _nonlinear_geometry(),
        forcing=ForcingFlux(
            (1.0, 0.0), "m3 s-1", "forcing:full-reach-only", modeled=True
        ),
    )

    assert result.forcing_support_required is False
    assert result.forcing_support_admitted is True
    assert result.raw_forcing_volume_m3 == pytest.approx(3600.0)
    assert result.applied_forcing_volume_m3 == pytest.approx(3600.0)
    assert result.excluded_forcing_volume_m3 == 0.0
    assert abs(result.global_mass_balance_residual_m3) <= (
        result.numeric_mass_tolerance_m3
    )


def test_nonlinear_reach_transport_rejects_unadmitted_or_misaligned_support():
    operator = NonlinearManningReachTransportOperator(
        _nonlinear_path(partial_last_reach=True),
        NonlinearReachTransportConfig(
            timestep_seconds=3600.0,
            path_admitted=True,
            operator_form_admitted=True,
        ),
    )
    forcing = ForcingFlux(
        (0.0, 1.0), "m3 s-1", "forcing:full-reach", modeled=True
    )
    candidate = ReachForcingSupport(
        feature_ids=(101, 102),
        coverage_fractions=(1.0, 0.5),
        support_method="length_fraction_assumption",
        provenance_id="candidate:partial-support:test",
        evidence_level="candidate",
        admitted_as_spatial_support=False,
    )
    with pytest.raises(
        ValueError,
        match=(
            "unadmitted_partial_reach_forcing_support_requires_explicit_"
            "diagnostic_mode"
        ),
    ):
        operator.step(
            operator.zero_state(provenance_id="cold:partial"),
            _nonlinear_geometry(),
            forcing=forcing,
            forcing_support=candidate,
        )

    misaligned = replace(candidate, coverage_fractions=(0.9, 0.5))
    with pytest.raises(
        ValueError, match="full_reach_forcing_support_fraction_must_equal_one"
    ):
        operator.step(
            operator.zero_state(provenance_id="cold:partial"),
            _nonlinear_geometry(),
            forcing=forcing,
            forcing_support=misaligned,
        )


def _manning_q_for_test(
    storage_m3: float,
    *,
    length_m: float,
    bottom_width_m: float,
    side_slope: float,
    bed_slope: float,
    manning_n: float,
) -> float:
    area = storage_m3 / length_m
    depth = (
        -bottom_width_m
        + math.sqrt(bottom_width_m**2 + 4.0 * side_slope * area)
    ) / (2.0 * side_slope)
    perimeter = bottom_width_m + 2.0 * depth * math.sqrt(1.0 + side_slope**2)
    radius = area / perimeter
    return area * radius ** (2.0 / 3.0) * math.sqrt(bed_slope) / manning_n


def _causal_observation(
    *,
    valid_at: datetime,
    available_at: datetime,
    target_storage_m3: float = 9000.0,
    quality_status: str = "approved",
) -> CausalDischargeObservation:
    return CausalDischargeObservation(
        feature_id=102,
        discharge_m3s=_manning_q_for_test(
            target_storage_m3,
            length_m=2000.0,
            bottom_width_m=25.0,
            side_slope=1.5,
            bed_slope=0.0002,
            manning_n=0.06,
        ),
        valid_at=valid_at,
        available_at=available_at,
        quality_status=quality_status,
        provenance_id="gauge:historical:test",
        evidence_level="authoritative",
    )


def test_causal_observation_update_inverts_manning_state_and_accounts_increment():
    analysis_time = datetime(2022, 1, 1, 13, tzinfo=timezone.utc)
    updater = CausalManningDischargeStateUpdater(
        _nonlinear_path(),
        CausalObservationUpdateConfig(
            analysis_gain=1.0,
            maximum_observation_age_seconds=7200.0,
        ),
    )
    observation = _causal_observation(
        valid_at=datetime(2022, 1, 1, 12, tzinfo=timezone.utc),
        available_at=datetime(2022, 1, 1, 12, 5, tzinfo=timezone.utc),
    )
    forecast = StockState((1000.0, 2000.0), "m3", "forecast:test")
    result = updater.update(
        forecast,
        _nonlinear_geometry(),
        observation,
        analysis_time=analysis_time,
    )

    assert result.updated_stock.values[0] == forecast.values[0]
    assert result.observation_equivalent_storage_m3 == pytest.approx(9000.0)
    assert result.updated_stock.values[1] == pytest.approx(9000.0)
    assert result.analysis_increment_m3 == pytest.approx(7000.0)
    assert result.analysis_discharge_m3s == pytest.approx(
        observation.discharge_m3s
    )
    assert result.observation_age_seconds == 3600.0
    assert result.causal_state_update_admitted is True
    assert (
        result.as_dict()["mass_accounting_role"]
        == "external_analysis_increment_not_transition_flux"
    )


def test_causal_observation_update_rejects_future_unavailable_and_stale_values():
    analysis_time = datetime(2022, 1, 1, 13, tzinfo=timezone.utc)
    updater = CausalManningDischargeStateUpdater(
        _nonlinear_path(),
        CausalObservationUpdateConfig(
            analysis_gain=0.5,
            maximum_observation_age_seconds=3600.0,
        ),
    )
    forecast = StockState((1000.0, 2000.0), "m3", "forecast:test")
    future_availability = _causal_observation(
        valid_at=datetime(2022, 1, 1, 12, 30, tzinfo=timezone.utc),
        available_at=datetime(2022, 1, 1, 13, 5, tzinfo=timezone.utc),
    )
    with pytest.raises(
        ValueError, match="observation_not_yet_available_at_analysis_time"
    ):
        updater.update(
            forecast,
            _nonlinear_geometry(),
            future_availability,
            analysis_time=analysis_time,
        )

    stale = _causal_observation(
        valid_at=datetime(2022, 1, 1, 11, 59, tzinfo=timezone.utc),
        available_at=datetime(2022, 1, 1, 12, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="causal_observation_exceeds_maximum_age"):
        updater.update(
            forecast,
            _nonlinear_geometry(),
            stale,
            analysis_time=analysis_time,
        )

    with pytest.raises(
        ValueError, match="causal_observation_role_must_be_historical_state_update"
    ):
        replace(
            stale,
            role="evaluation_outcome",
        )


def test_causal_observation_quality_policy_is_explicit_and_fail_closed():
    analysis_time = datetime(2022, 1, 1, 13, tzinfo=timezone.utc)
    observation = _causal_observation(
        valid_at=datetime(2022, 1, 1, 12, tzinfo=timezone.utc),
        available_at=datetime(2022, 1, 1, 12, 5, tzinfo=timezone.utc),
        quality_status="provisional",
    )
    forecast = StockState((1000.0, 2000.0), "m3", "forecast:test")
    strict = CausalManningDischargeStateUpdater(
        _nonlinear_path(),
        CausalObservationUpdateConfig(
            analysis_gain=0.5,
            maximum_observation_age_seconds=7200.0,
        ),
    )
    with pytest.raises(
        ValueError,
        match="unadmitted_causal_observation_components_require_explicit_"
        "diagnostic_mode",
    ):
        strict.update(
            forecast,
            _nonlinear_geometry(),
            observation,
            analysis_time=analysis_time,
        )

    provisional = CausalManningDischargeStateUpdater(
        _nonlinear_path(),
        CausalObservationUpdateConfig(
            analysis_gain=0.5,
            maximum_observation_age_seconds=7200.0,
            accepted_quality_statuses=("approved", "provisional"),
        ),
    ).update(
        forecast,
        _nonlinear_geometry(),
        observation,
        analysis_time=analysis_time,
    )
    assert provisional.analysis_storage_m3 == pytest.approx(5500.0)
    assert provisional.analysis_increment_m3 == pytest.approx(3500.0)
    assert provisional.causal_state_update_admitted is True


def test_official_route_link_nonlinear_manning_invariants_pass_without_outcome():
    report = compile_kernel_v2_nonlinear_manning_invariants()

    assert report["status"] == "pass"
    assert report["operator_schema"].endswith(".v2")
    assert report["data_isolation"]["outcome_values_loaded"] is False
    assert report["fixture"]["topology_consecutive"] is True
    assert report["fixture"]["center_hill_parameter_fixture"] is False
    assert report["fixture"]["channel_side_slope_compilation"].startswith(
        "horizontal_per_vertical=1/RouteLink_ChSlp"
    )
    assert report["gates"]["all_invariants_passed"] is True
    assert report["direction_diagnostics"]["heterogeneous_official_fixture"][
        "relative_l1_difference"
    ] >= report["registered_thresholds"][
        "heterogeneous_direction_relative_l1_minimum"
    ]
    assert report["claim_boundary"]["center_hill_execution_admitted"] is False


def test_kernel_v2_causal_support_invariants_pass_without_outcome():
    report = compile_kernel_v2_causal_support_invariants()

    assert report["status"] == "pass"
    assert report["data_isolation"]["outcome_values_loaded"] is False
    assert report["data_isolation"]["center_hill_chunk_561_loaded"] is False
    assert report["fixture"]["center_hill_parameter_fixture"] is False
    assert report["gates"]["all_invariants_passed"] is True
    assert report["observation_update_probe"][
        "analysis_increment_accounting_passed"
    ] is True
    forcing = report["partial_forcing_probe"]
    assert forcing["forcing_ledger_passed"] is True
    assert forcing["projected_conservation_passed"] is True
    assert report["claim_boundary"]["real_observation_update_validated"] is False
    assert report["claim_boundary"]["real_forcing_support_validated"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_center_hill_nwm_v3_route_link_manifest_passes_only_parameter_gate():
    root = Path(__file__).resolve().parents[1]
    manifest_path = (
        root
        / "data/geotransport_v0_1/route_link_nwm_v3_center_hill/"
        "acquisition_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = manifest["source_route_link_audit"]
    subset = manifest["subset"]
    subset_path = root / subset["path"]
    subset_body = subset_path.read_bytes()

    assert manifest["status"] == "pass"
    assert manifest["source"]["archive_local_path_retained"] is False
    assert manifest["source"]["route_link_member_path"] == (
        "v3.0_par/RouteLink_CONUS.nc"
    )
    assert audit["requested_feature_coverage_count"] == 27
    assert audit["active_feature_coverage_count"] == 26
    assert audit["active_topology_consecutive"] is True
    assert audit["required_parameter_fields_missing"] == []
    assert hashlib.sha256(subset_body).hexdigest() == subset["sha256"]
    assert len(subset_body) == subset["size_bytes"]
    assert manifest["adjudication"][
        "center_hill_active_feature_coverage_complete"
    ] is True
    assert manifest["adjudication"][
        "retrospective_parameter_identity_verified"
    ] is False
    assert manifest["claim_boundary"][
        "center_hill_transition_execution_admitted"
    ] is False
    assert manifest["claim_boundary"]["geospatial_kernel_validated"] is False


def test_t_route_mc_professional_baseline_report_keeps_claims_fail_closed():
    path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/geotransport_v0_1/"
        "t_route_mc_professional_baseline_report.json"
    )
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["status"] == "pass_with_conservation_limitation"
    assert report["official_reference_conformance"]["passed"] is True
    assert report["official_zero_state_invariant"]["passed"] is True
    assert report["gates"]["all_professional_baseline_invariants_passed"] is True
    assert report["direction_diagnostics"]["t_route_mc"][
        "relative_l1_difference"
    ] > report["registered_protocol"][
        "direction_relative_l1_numeric_minimum"
    ]
    assert report["scientific_limitations"][
        "official_mc_conservation_verified"
    ] is False
    assert report["claim_boundary"]["official_t_route_kernel_executed"] is True
    assert report["claim_boundary"]["center_hill_execution_admitted"] is False
    assert report["claim_boundary"]["geospatial_kernel_validated"] is False


def test_conservative_flux_keeps_semantic_channels_and_global_balance():
    result = _operator().step(
        StockState((10.0, 0.0, 0.0), "m3", "observed-stock"),
        EdgeFlux((4.0, 0.0), "m3 s-1", "routing-policy"),
        action=ActionBoundaryFlux((1.0, 0.0, 0.0), "m3 s-1", "dam-release"),
        forcing=ForcingFlux(
            (0.0, 1.0, 0.0), "m3 s-1", "nwm-q-lateral", modeled=True
        ),
        source_sink=SourceSinkFlux(
            (0.0, 0.0, -0.5), "m3 s-1", "observed-withdrawal"
        ),
    )

    assert result.next_stock.values == pytest.approx((7.0, 5.0, 0.0))
    assert result.applied_action_flux == (1.0, 0.0, 0.0)
    assert result.applied_forcing_flux == (0.0, 1.0, 0.0)
    assert result.unmet_external_withdrawal == (0.0, 0.0, 0.5)
    assert result.global_mass_balance_residual == pytest.approx(0.0)
    assert np.max(np.abs(result.node_balance_residual)) < 1e-12


def test_conservative_flux_projects_capacity_and_available_stock():
    result = _operator().step(
        StockState((4.0, 0.0, 0.0), "m3", "stock"),
        EdgeFlux((10.0, 10.0), "m3 s-1", "proposal"),
    )

    assert result.applied_edge_flux == pytest.approx((4.0, 0.0))
    assert result.capacity_limited_edges == (True, True)
    assert result.stock_limited_edges == (True, True)
    assert result.next_stock.values == pytest.approx((0.0, 4.0, 0.0))


def test_conservative_flux_fails_closed_on_unadmitted_edge():
    with pytest.raises(ValueError, match="nonzero_flux_on_unadmitted_edge"):
        _operator(_complex(admitted=(True, False))).step(
            StockState((1.0, 1.0, 0.0), "m3", "stock"),
            EdgeFlux((0.0, 0.5), "m3 s-1", "proposal"),
        )


def test_observation_cannot_be_used_as_action_boundary_flux():
    observation = ObservationField((1.0, 0.0, 0.0), "m3 s-1", "usgs")
    with pytest.raises(TypeError, match="action_boundary_flux_required"):
        _operator().step(
            StockState((1.0, 0.0, 0.0), "m3", "stock"),
            EdgeFlux((0.0, 0.0), "m3 s-1", "proposal"),
            action=observation,  # type: ignore[arg-type]
        )


def test_authoritative_direction_changes_the_state_transition():
    forward = _operator().step(
        StockState((2.0, 0.0, 0.0), "m3", "stock"),
        EdgeFlux((1.0, 0.0), "m3 s-1", "proposal"),
    )
    reversed_complex = replace(
        _complex(),
        B=BoundaryOperator(
            node_keys=("reservoir", "reach-1", "gauge"),
            edge_keys=("release-reach", "reach-gauge"),
            source_indices=(1, 2),
            target_indices=(0, 1),
        ),
    )
    reverse = _operator(reversed_complex).step(
        StockState((2.0, 0.0, 0.0), "m3", "stock"),
        EdgeFlux((1.0, 0.0), "m3 s-1", "proposal"),
    )

    assert forward.next_stock.values == pytest.approx((1.0, 1.0, 0.0))
    assert reverse.next_stock.values == pytest.approx((2.0, 0.0, 0.0))


def test_public_registry_freezes_minimal_cohort_and_semantic_roles():
    registry = load_public_data_registry()
    systems = registry.systems()

    assert len(systems) == 9
    assert [system["track"] for system in systems].count("GeoTransport-H") == 3
    assert [system["track"] for system in systems].count("GeoTransport-D") == 4
    assert [system["track"] for system in systems].count("GeoConservation-D") == 2
    for system in systems:
        assert system["action"]["role"] == "boundary_action"
        if system["track"].startswith("GeoTransport"):
            assert system["action"]["operator_sign"] == 1
            assert system["forcing"]["role"] == "modeled_forcing"
            assert system["forcing"]["ground_truth"] is False
            assert system["outcome"]["role"] == "independent_observation"
            assert len(system["forcing"]["feature_ids"]) == len(
                system["forcing"]["feature_indices"]
            )
            assert system["forcing"]["q_lateral_feature_chunk_indices"] == sorted(
                {index // 30000 for index in system["forcing"]["feature_indices"]}
            )
        else:
            assert system["action"]["operator_sign"] == -1


def test_public_registry_rejects_inconsistent_nwm_chunk_crosswalk():
    payload = copy.deepcopy(load_public_data_registry().payload)
    center_hill = next(
        system for system in payload["systems"] if system["system_id"] == "center_hill"
    )
    center_hill["forcing"]["q_lateral_feature_chunk_indices"] = [0]

    with pytest.raises(ValueError, match="nwm_feature_chunk_indices_mismatch:center_hill"):
        validate_public_data_registry(payload)


def test_public_registry_verifies_crosswalk_evidence_hashes(tmp_path: Path):
    registry = load_public_data_registry()
    payload = copy.deepcopy(registry.payload)
    payload["crosswalk_evidence"]["nldi_path_report"]["sha256"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="crosswalk_evidence_hash_mismatch"):
        load_public_data_registry(path)


def test_public_registry_verifies_nwm_smoke_evidence_hash(tmp_path: Path):
    registry = load_public_data_registry()
    payload = copy.deepcopy(registry.payload)
    payload["nwm_q_lateral_smoke_evidence"]["report"]["sha256"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="crosswalk_evidence_hash_mismatch"):
        load_public_data_registry(path)


def test_public_registry_verifies_smoke_panel_evidence_hash(tmp_path: Path):
    registry = load_public_data_registry()
    payload = copy.deepcopy(registry.payload)
    payload["center_hill_smoke_panel_evidence"]["report"]["sha256"] = "0" * 64
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="crosswalk_evidence_hash_mismatch"):
        load_public_data_registry(path)


def test_public_registry_verifies_travel_time_prior_evidence_hash(tmp_path: Path):
    registry = load_public_data_registry()
    payload = copy.deepcopy(registry.payload)
    payload["center_hill_travel_time_prior_evidence"]["report"]["sha256"] = (
        "0" * 64
    )
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="crosswalk_evidence_hash_mismatch"):
        load_public_data_registry(path)


def test_public_registry_rejects_smoke_panel_acquisition_lineage_tamper(
    tmp_path: Path,
):
    registry = load_public_data_registry()
    payload = copy.deepcopy(registry.payload)
    payload["center_hill_smoke_panel_evidence"]["acquisition_registry_sha256"] = (
        "0" * 64
    )
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        ValueError, match="smoke_panel_acquisition_registry_lineage_mismatch"
    ):
        load_public_data_registry(path)


def test_metadata_requests_are_bounded_to_official_sources_and_deduplicate_nwm():
    requests = build_metadata_requests(load_public_data_registry())
    hosts = {urlparse(request.url).hostname for request in requests}

    assert hosts == {
        "api.water.usgs.gov",
        "cwms-data.usace.army.mil",
        "data.usbr.gov",
        "noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com",
        "waterservices.usgs.gov",
    }
    assert sum(request.request_id == "nwm-q-lateral-zarray" for request in requests) == 1
    assert sum(request.request_id == "nwm-q-lateral-zattrs" for request in requests) == 1
    assert sum(request.variable_role == "boundary_action_location" for request in requests) == 3


def test_nldi_path_summary_stops_at_gauge_reach():
    navigation = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": comid,
                "properties": {"nhdplus_comid": comid},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-85.0 + index * 0.01, 36.0], [-84.99 + index * 0.01, 36.0]],
                },
            }
            for index, comid in enumerate((10, 11, 12))
        ],
    }

    summary = summarize_path(navigation, action_comid=10, gauge_comid=11)

    assert summary["gauge_reachable"] is True
    assert summary["feature_ids"] == [10, 11]
    assert summary["path_feature_count"] == 2


def test_transport_value_plan_fails_without_nwm_feature_crosswalk():
    registry = load_public_data_registry()
    payload = copy.deepcopy(registry.payload)
    center_hill = next(
        system for system in payload["systems"] if system["system_id"] == "center_hill"
    )
    center_hill["forcing"]["feature_ids"] = []
    center_hill["forcing"]["feature_indices"] = []
    center_hill["forcing"]["q_lateral_feature_chunk_indices"] = []
    center_hill["forcing"]["crosswalk_status"] = "pending"
    with pytest.raises(ValueError, match="nwm_feature_crosswalk_required:center_hill"):
        build_value_requests(
            replace(registry, payload=payload),
            start="2022-01-01T00:00:00Z",
            end="2022-01-03T00:00:00Z",
            system_ids=("center_hill",),
        )


def test_generic_value_plan_routes_nwm_to_dedicated_extractor():
    with pytest.raises(
        ValueError, match="nwm_values_require_dedicated_extractor:center_hill"
    ):
        build_value_requests(
            load_public_data_registry(),
            start="2022-01-01T00:00:00Z",
            end="2022-01-03T00:00:00Z",
            system_ids=("center_hill",),
        )


def test_transport_companion_plan_requires_matching_nwm_value_evidence():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (
            root
            / "data/geotransport_v0_1/nwm_q_lateral/extraction_manifest.json"
        ).read_text(encoding="utf-8")
    )

    requests = build_value_requests(
        load_public_data_registry(),
        start="2022-01-01T00:00:00Z",
        end="2022-01-02T00:00:00Z",
        system_ids=("center_hill",),
        nwm_extraction_manifest=manifest,
    )

    assert len(requests) == 4
    assert [request.variable_role for request in requests] == [
        "boundary_action",
        "stock",
        "context_not_independent_forcing",
        "independent_observation",
    ]
    assert {urlparse(request.url).hostname for request in requests} == {
        "cwms-data.usace.army.mil",
        "waterservices.usgs.gov",
    }
    usgs = next(request for request in requests if request.source == "usgs_water_data")
    query = parse_qs(urlparse(usgs.url).query)
    assert query["startDT"] == ["2021-12-31T23:00:00Z"]
    assert query["endDT"] == ["2022-01-02T01:00:00Z"]


def test_transport_companion_plan_rejects_nwm_evidence_from_other_system():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (
            root
            / "data/geotransport_v0_1/nwm_q_lateral/extraction_manifest.json"
        ).read_text(encoding="utf-8")
    )

    with pytest.raises(ValueError, match="nwm_values_manifest_system_missing"):
        build_value_requests(
            load_public_data_registry(),
            start="2022-01-01T00:00:00Z",
            end="2022-01-02T00:00:00Z",
            system_ids=("j_percy_priest",),
            nwm_extraction_manifest=manifest,
        )


def test_nwm_extraction_plan_is_bounded_to_crosswalked_chunks():
    registry = load_public_data_registry()
    schema = load_nwm_zarr_schema(
        Path(__file__).resolve().parents[1] / "data/geotransport_v0_1/metadata"
    )

    plan = build_nwm_q_lateral_plan(
        registry,
        schema,
        system_id="glen_canyon",
        start="2022-01-01T00:00:00Z",
        end="2022-01-02T00:00:00Z",
    )

    assert plan.time_count == 24
    assert plan.feature_chunk_indices == (11, 72)
    assert len(plan.time_chunk_indices) == 1
    assert plan.q_chunk_keys == (
        (plan.time_chunk_indices[0], 11),
        (plan.time_chunk_indices[0], 72),
    )


def test_nwm_extractor_decodes_cross_chunk_features_and_fill_before_scaling():
    zstd = shutil.which("zstd")
    if zstd is None:
        pytest.skip("zstd executable is required")
    schema = NwmZarrSchema(
        q_shape=(6, 8),
        q_chunks=(4, 4),
        q_dtype=np.dtype("<i4"),
        q_fill_value=-99990,
        scale_factor=0.1,
        add_offset=0.0,
        valid_range=(0, 500000),
        time_shape=6,
        time_chunk_size=4,
        time_dtype=np.dtype("<i8"),
        time_origin=datetime(2022, 1, 1, tzinfo=timezone.utc),
        metadata_sha256={},
    )
    plan = NwmQlatPlan(
        system_id="synthetic",
        start=datetime(2022, 1, 1, 2, tzinfo=timezone.utc),
        end=datetime(2022, 1, 1, 6, tzinfo=timezone.utc),
        start_time_index=2,
        end_time_index=6,
        feature_ids=(101, 102, 103),
        feature_indices=(1, 6, 4),
        time_chunk_indices=(0, 1),
        feature_chunk_indices=(0, 1),
        q_chunk_keys=((0, 0), (0, 1), (1, 0), (1, 1)),
    )
    q00 = np.arange(16, dtype="<i4").reshape(4, 4)
    q01 = (100 + np.arange(16, dtype="<i4")).reshape(4, 4)
    q10 = (200 + np.arange(8, dtype="<i4")).reshape(2, 4)
    q11 = (300 + np.arange(8, dtype="<i4")).reshape(2, 4)
    q01[2, 2] = schema.q_fill_value

    result = extract_nwm_q_lateral(
        plan,
        schema,
        time_chunks={
            0: _zstd(np.arange(4, dtype="<i8"), zstd),
            1: _zstd(np.arange(4, 6, dtype="<i8"), zstd),
        },
        q_chunks={
            (0, 0): _zstd(q00, zstd),
            (0, 1): _zstd(q01, zstd),
            (1, 0): _zstd(q10, zstd),
            (1, 1): _zstd(q11, zstd),
        },
        zstd_executable=zstd,
    )

    assert result.timestamps == (
        "2022-01-01T02:00:00Z",
        "2022-01-01T03:00:00Z",
        "2022-01-01T04:00:00Z",
        "2022-01-01T05:00:00Z",
    )
    assert result.values_m3s[:, 0] == pytest.approx((0.9, 1.3, 20.1, 20.5))
    assert np.isnan(result.values_m3s[0, 1])
    assert result.values_m3s[1:, 1] == pytest.approx((11.4, 30.2, 30.6))
    assert result.values_m3s[:, 2] == pytest.approx((10.8, 11.2, 30.0, 30.4))
    assert result.fill_value_count == 1
    assert result.variable_role == "modeled_forcing"
    assert result.ground_truth is False


def test_nwm_velocity_extractor_preserves_modeled_state_role_and_fill():
    zstd = shutil.which("zstd")
    if zstd is None:
        pytest.skip("zstd executable is required")
    base = NwmZarrSchema(
        q_shape=(4, 4),
        q_chunks=(4, 4),
        q_dtype=np.dtype("<i4"),
        q_fill_value=-99990,
        scale_factor=0.1,
        add_offset=0.0,
        valid_range=(0, 500000),
        time_shape=4,
        time_chunk_size=4,
        time_dtype=np.dtype("<i8"),
        time_origin=datetime(2022, 1, 1, tzinfo=timezone.utc),
        metadata_sha256={},
    )
    schema = NwmVelocitySchema(
        base=base,
        velocity_shape=(4, 4),
        velocity_chunks=(4, 4),
        velocity_dtype=np.dtype("<i4"),
        velocity_fill_value=-999900,
        scale_factor=0.001,
        add_offset=0.0,
        valid_range=(0, np.iinfo(np.int32).max),
        metadata_sha256={},
    )
    plan = NwmQlatPlan(
        system_id="synthetic",
        start=datetime(2022, 1, 1, 1, tzinfo=timezone.utc),
        end=datetime(2022, 1, 1, 3, tzinfo=timezone.utc),
        start_time_index=1,
        end_time_index=3,
        feature_ids=(101, 102),
        feature_indices=(1, 3),
        time_chunk_indices=(0,),
        feature_chunk_indices=(0,),
        q_chunk_keys=((0, 0),),
    )
    raw = np.arange(16, dtype="<i4").reshape(4, 4) * 1000
    raw[2, 3] = schema.velocity_fill_value

    result = extract_nwm_velocity(
        plan,
        schema,
        time_chunks={0: _zstd(np.arange(4, dtype="<i8"), zstd)},
        velocity_chunks={(0, 0): _zstd(raw, zstd)},
        zstd_executable=zstd,
    )

    assert result.timestamps == (
        "2022-01-01T01:00:00Z",
        "2022-01-01T02:00:00Z",
    )
    assert result.values_ms[:, 0] == pytest.approx((5.0, 9.0))
    assert result.values_ms[0, 1] == pytest.approx(7.0)
    assert np.isnan(result.values_ms[1, 1])
    assert result.fill_value_count == 1
    assert result.variable_role == "modeled_state_context"
    assert result.ground_truth is False


def test_nwm_streamflow_schema_and_extractor_preserve_initial_state_role():
    zstd = shutil.which("zstd")
    if zstd is None:
        pytest.skip("zstd executable is required")
    metadata_root = (
        Path(__file__).resolve().parents[1]
        / "data/geotransport_v0_1/metadata"
    )
    official = load_nwm_streamflow_schema(metadata_root)
    assert official.streamflow_shape == (385704, 2776734)
    assert official.streamflow_chunks == (672, 30000)
    assert official.streamflow_fill_value == -999900
    assert official.scale_factor == pytest.approx(0.01)
    assert official.valid_range_attribute_present is False

    base = NwmZarrSchema(
        q_shape=(4, 4),
        q_chunks=(4, 4),
        q_dtype=np.dtype("<i4"),
        q_fill_value=-99990,
        scale_factor=0.1,
        add_offset=0.0,
        valid_range=(0, 500000),
        time_shape=4,
        time_chunk_size=4,
        time_dtype=np.dtype("<i8"),
        time_origin=datetime(2022, 1, 1, tzinfo=timezone.utc),
        metadata_sha256={},
    )
    schema = NwmStreamflowSchema(
        base=base,
        streamflow_shape=(4, 4),
        streamflow_chunks=(4, 4),
        streamflow_dtype=np.dtype("<i4"),
        streamflow_fill_value=-999900,
        scale_factor=0.01,
        add_offset=0.0,
        valid_range=(0, 5000000),
        valid_range_attribute_present=True,
        metadata_sha256={},
    )
    plan = NwmQlatPlan(
        system_id="synthetic",
        start=datetime(2022, 1, 1, 1, tzinfo=timezone.utc),
        end=datetime(2022, 1, 1, 3, tzinfo=timezone.utc),
        start_time_index=1,
        end_time_index=3,
        feature_ids=(101, 102),
        feature_indices=(1, 3),
        time_chunk_indices=(0,),
        feature_chunk_indices=(0,),
        q_chunk_keys=((0, 0),),
    )
    raw = np.arange(16, dtype="<i4").reshape(4, 4) * 100
    raw[2, 3] = schema.streamflow_fill_value
    result = extract_nwm_streamflow(
        plan,
        schema,
        time_chunks={0: _zstd(np.arange(4, dtype="<i8"), zstd)},
        streamflow_chunks={(0, 0): _zstd(raw, zstd)},
        zstd_executable=zstd,
    )

    assert result.timestamps == (
        "2022-01-01T01:00:00Z",
        "2022-01-01T02:00:00Z",
    )
    assert result.values_m3s[:, 0] == pytest.approx((5.0, 9.0))
    assert result.values_m3s[0, 1] == pytest.approx(7.0)
    assert np.isnan(result.values_m3s[1, 1])
    assert result.fill_value_count == 1
    assert result.variable_role == "modeled_initial_state"
    assert result.ground_truth is False


def test_frozen_nwm_value_smoke_is_reproducible_from_raw_chunks():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/nwm_q_lateral_smoke_report.json"
        ).read_text(encoding="utf-8")
    )
    recomputed = audit_nwm_smoke()

    for key in (
        "schema",
        "status",
        "input_registry_sha256",
        "extraction_manifest",
        "source_semantics",
        "window",
        "spatial_selection",
        "artifacts",
        "value_summary",
        "checks",
        "claim_boundary",
    ):
        assert frozen[key] == recomputed[key]


def test_nwm_raw_chunk_reuse_verifies_identity_and_fails_closed_on_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(nwm_extraction_script, "REPO_ROOT", tmp_path)
    time_body = b"verified-time-chunk"
    q_body = b"verified-q-lateral-chunk"
    time_path = tmp_path / "raw/time/559.zst"
    q_path = tmp_path / "raw/q_lateral/559.63.zst"
    time_path.parent.mkdir(parents=True)
    q_path.parent.mkdir(parents=True)
    time_path.write_bytes(time_body)
    q_path.write_bytes(q_body)
    manifest_path = tmp_path / "source-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "gwm.geotransport.nwm_q_lateral_extract.v1",
                "mode": "values",
                "source_semantics": {
                    "source": "noaa_nwm_v3_retrospective",
                    "variable": "q_lateral",
                    "ground_truth": False,
                },
                "raw_chunk_artifacts": [
                    {
                        "url": nwm_extraction_script.nwm_chunk_url("time", "559"),
                        "variable": "time",
                        "path": "raw/time/559.zst",
                        "sha256": hashlib.sha256(time_body).hexdigest(),
                        "size_bytes": len(time_body),
                    },
                    {
                        "url": nwm_extraction_script.nwm_chunk_url(
                            "q_lateral", "559.63"
                        ),
                        "variable": "q_lateral",
                        "path": "raw/q_lateral/559.63.zst",
                        "sha256": hashlib.sha256(q_body).hexdigest(),
                        "size_bytes": len(q_body),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    time_chunks, q_chunks, artifacts = (
        nwm_extraction_script.load_reused_raw_chunks(
            manifest_path,
            time_chunk_indices=(559,),
            q_chunk_keys=((559, 63),),
        )
    )

    assert time_chunks == {559: time_body}
    assert q_chunks == {(559, 63): q_body}
    assert all(row["reused_without_download"] is True for row in artifacts)
    q_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="nwm_reuse_chunk_identity_mismatch"):
        nwm_extraction_script.load_reused_raw_chunks(
            manifest_path,
            time_chunk_indices=(559,),
            q_chunk_keys=((559, 63),),
        )


def test_center_hill_672h_nwm_values_are_reproducible_from_reused_raw_chunks():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "data/geotransport_v0_1/nwm_q_lateral_672h/extraction_manifest.json"
        ).read_text(encoding="utf-8")
    )
    source_manifest = (
        root / "data/geotransport_v0_1/nwm_q_lateral/extraction_manifest.json"
    )
    time_chunks, q_chunks, artifacts = (
        nwm_extraction_script.load_reused_raw_chunks(
            source_manifest,
            time_chunk_indices=(559,),
            q_chunk_keys=((559, 63),),
        )
    )
    registry = load_public_data_registry()
    schema = load_nwm_zarr_schema(root / "data/geotransport_v0_1/metadata")
    plan = build_nwm_q_lateral_plan(
        registry,
        schema,
        system_id="center_hill",
        start="2021-12-09T01:00:00Z",
        end="2022-01-06T01:00:00Z",
    )
    result = extract_nwm_q_lateral(
        plan,
        schema,
        time_chunks=time_chunks,
        q_chunks=q_chunks,
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["timestamp_utc", "feature_id", "q_lateral_m3s", "source_role"])
    for row, timestamp in enumerate(result.timestamps):
        for column, feature_id in enumerate(result.feature_ids):
            value = result.values_m3s[row, column]
            writer.writerow(
                [
                    timestamp,
                    feature_id,
                    "" if math.isnan(value) else format(value, ".10g"),
                    result.variable_role,
                ]
            )
    csv_body = output.getvalue().encode("utf-8")

    assert result.values_m3s.shape == (672, 27)
    assert result.fill_value_count == 0
    assert hashlib.sha256(csv_body).hexdigest() == frozen["value_artifacts"][0][
        "sha256"
    ]
    assert frozen["raw_chunk_lineage"]["sha256"] == hashlib.sha256(
        source_manifest.read_bytes()
    ).hexdigest()
    assert all(row["reused_without_download"] is True for row in artifacts)
    assert frozen["claim_boundary"]["raw_chunks_reused_without_download"] is True
    assert frozen["claim_boundary"]["benchmark_validated"] is False
    assert frozen["claim_boundary"]["geospatial_kernel_validated"] is False


def test_center_hill_smoke_panel_is_reproducible_and_claims_stay_closed():
    root = Path(__file__).resolve().parents[1]
    report_path = (
        root
        / "benchmarks/geotransport_v0_1/center_hill_smoke_panel_report.json"
    )
    frozen = json.loads(report_path.read_text(encoding="utf-8"))
    recomputed = compile_panel()

    for key in (
        "schema",
        "status",
        "registry_sha256",
        "source_manifests",
        "source_artifacts",
        "window",
        "panel_artifact",
        "channel_semantics",
        "quality_summary",
        "value_summary",
        "checks",
        "claim_boundary",
    ):
        assert frozen[key] == recomputed.report[key]
    assert frozen["window"]["row_count"] == 24
    assert frozen["quality_summary"]["usgs_all_samples_approved"] is True
    rows = list(
        csv.DictReader(io.StringIO(recomputed.csv_body.decode("utf-8")))
    )
    assert rows[0]["support_start_utc"] == "2022-01-01T00:00:00Z"
    assert rows[0]["support_end_utc"] == "2022-01-01T01:00:00Z"
    assert rows[0]["action_timestamp_utc"] == rows[0]["support_end_utc"]
    assert rows[0]["nwm_valid_time_utc"] == rows[0]["support_start_utc"]
    assert rows[-1]["support_end_utc"] == "2022-01-02T00:00:00Z"
    assert rows[-1]["action_timestamp_utc"] == rows[-1]["support_end_utc"]
    assert rows[-1]["nwm_valid_time_utc"] == rows[-1]["support_start_utc"]
    assert frozen["claim_boundary"][
        "cwms_interval_timestamp_semantics_admitted"
    ] is True
    assert frozen["claim_boundary"]["flood_wave_travel_time_admitted"] is False
    assert frozen["claim_boundary"]["training_or_evaluation_panel_ready"] is False


def test_center_hill_672h_development_panel_is_reproducible_without_imputation():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_672h_development_panel_report.json"
        ).read_text(encoding="utf-8")
    )
    recomputed = compile_development_panel()

    for key, value in recomputed.report.items():
        assert frozen[key] == value
    assert hashlib.sha256(recomputed.csv_body).hexdigest() == frozen[
        "panel_artifact"
    ]["sha256"]
    rows = list(csv.DictReader(io.StringIO(recomputed.csv_body.decode("utf-8"))))
    missing = [row for row in rows if row["outcome_available"] == "false"]
    assert len(rows) == 672
    assert sum(row["split_role"] == "warmup" for row in rows) == 168
    assert sum(row["split_role"] == "development" for row in rows) == 504
    assert rows[0]["support_start_utc"] == "2021-12-09T01:00:00Z"
    assert rows[167]["split_role"] == "warmup"
    assert rows[168]["split_role"] == "development"
    assert rows[-1]["support_end_utc"] == "2022-01-06T01:00:00Z"
    assert [row["support_end_utc"] for row in missing] == [
        "2022-01-03T05:00:00Z",
        "2022-01-03T06:00:00Z",
        "2022-01-03T07:00:00Z",
    ]
    assert [row["outcome_half_hour_sample_count"] for row in missing] == [
        "1",
        "0",
        "1",
    ]
    assert all(row["outcome_discharge_interval_sample_mean_m3s"] == "" for row in missing)
    assert frozen["quality_summary"]["input_channel_missing_value_count"] == 0
    assert frozen["quality_summary"]["outcome_imputed_hour_count"] == 0
    assert frozen["window"]["evaluation_hours"] == 0
    for claim in (
        "training_or_evaluation_panel_ready",
        "benchmark_validated",
        "flood_wave_transport_admitted",
        "geospatial_kernel_validated",
    ):
        assert frozen["claim_boundary"][claim] is False


def test_center_hill_travel_time_prior_is_reproducible_and_not_a_wave_lag():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
        ).read_text(encoding="utf-8")
    )
    recomputed = compile_prior()

    for key, value in recomputed.report.items():
        assert frozen[key] == value
    assert hashlib.sha256(recomputed.velocity_csv_body).hexdigest() == frozen[
        "source_artifacts"
    ]["selected_velocity"]["sha256"]
    assert hashlib.sha256(recomputed.travel_time_csv_body).hexdigest() == frozen[
        "source_artifacts"
    ]["advective_travel_time"]["sha256"]
    assert frozen["advective_travel_time_prior"]["quantity"] == (
        "advective_residence_time"
    )
    assert frozen["advective_travel_time_prior"][
        "admitted_as_flood_wave_lag"
    ] is False
    assert frozen["claim_boundary"]["flood_wave_travel_time_admitted"] is False


def test_center_hill_reach_transport_smoke_is_reproducible_and_diagnostic_only():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_reach_transport_smoke_report.json"
        ).read_text(encoding="utf-8")
    )
    recomputed = compile_reach_transport_smoke()

    for key, value in recomputed.report.items():
        assert frozen[key] == value
    assert hashlib.sha256(recomputed.csv_body).hexdigest() == frozen[
        "output_artifact"
    ]["sha256"]
    assert set(frozen["checks"].values()) == {True, False}
    assert frozen["checks"]["outcome_values_used"] is False
    assert frozen["checks"][
        "all_step_mass_balance_residuals_within_tolerance"
    ] is True
    assert frozen["checks"][
        "horizon_mass_balance_residual_within_tolerance"
    ] is True
    assert frozen["claim_boundary"]["flood_wave_transport_admitted"] is False
    assert frozen["claim_boundary"]["outcome_calibrated"] is False
    assert frozen["claim_boundary"]["geospatial_kernel_validated"] is False


def test_center_hill_672h_reach_transport_rollout_is_reproducible_and_unscored():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_672h_reach_transport_rollout_report.json"
        ).read_text(encoding="utf-8")
    )
    recomputed = compile_reach_transport_rollout()

    for key, value in recomputed.report.items():
        assert frozen[key] == value
    assert hashlib.sha256(recomputed.csv_body).hexdigest() == frozen[
        "output_artifact"
    ]["sha256"]
    assert sum(recomputed.final_stock_values_m3) == pytest.approx(
        frozen["diagnostics"]["final_reach_storage_m3"]
    )
    reader = csv.DictReader(io.StringIO(recomputed.csv_body.decode("utf-8")))
    rows = list(reader)
    assert len(rows) == 672
    assert sum(row["split_role"] == "warmup" for row in rows) == 168
    assert sum(row["split_role"] == "development" for row in rows) == 504
    assert not any("outcome" in field for field in (reader.fieldnames or []))
    assert float(rows[167]["reach_storage_end_m3"]) == pytest.approx(
        frozen["diagnostics"]["development"]["initial_reach_storage_m3"],
        rel=1e-11,
    )
    assert frozen["diagnostics"]["warmup"]["mass_balance_residual_m3"] < (
        frozen["diagnostics"]["warmup"][
            "cumulative_step_numeric_mass_tolerance_m3"
        ]
    )
    assert frozen["diagnostics"]["development"][
        "mass_balance_residual_m3"
    ] < frozen["diagnostics"]["development"][
        "cumulative_step_numeric_mass_tolerance_m3"
    ]
    for check in (
        "all_step_mass_balance_residuals_within_tolerance",
        "warmup_mass_balance_residual_within_tolerance",
        "development_mass_balance_residual_within_tolerance",
        "horizon_mass_balance_residual_within_tolerance",
        "warmup_state_carried_into_development_without_reset",
    ):
        assert frozen["checks"][check] is True
    for check in (
        "outcome_values_used",
        "outcome_values_used_for_calibration",
        "outcome_values_scored",
    ):
        assert frozen["checks"][check] is False
    for claim in (
        "river_velocity_admitted_as_flood_wave_celerity",
        "linear_reservoir_cascade_hydrodynamically_validated",
        "flood_wave_transport_admitted",
        "outcome_calibrated",
        "training_or_evaluation_panel_ready",
        "benchmark_validated",
        "geospatial_kernel_validated",
    ):
        assert frozen["claim_boundary"][claim] is False


def test_center_hill_temporal_holdout_protocol_is_frozen_before_label_access():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_protocol_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert frozen == compile_center_hill_evaluation_protocol()
    assert frozen["status"] == "frozen_before_evaluation_outcome_acquisition"
    assert frozen["label_access_at_freeze"][
        "evaluation_window_outcome_acquired"
    ] is False
    assert frozen["temporal_split"] == {
        "acquisition_start_inclusive": "2022-01-06T01:00:00Z",
        "scored_start_inclusive": "2022-01-13T01:00:00Z",
        "end_exclusive": "2022-02-03T01:00:00Z",
        "time_step": "PT1H",
        "acquisition_hours": 672,
        "evaluation_warmup_hours": 168,
        "maximum_scored_hours": 504,
        "evaluation_warmup_role": "state_update_and_baseline_history_only",
        "scored_role": "external_temporal_holdout",
        "development_rows_reassigned_to_evaluation": False,
    }
    assert frozen["nwm_acquisition"]["time_chunk_indices"] == [560]
    assert frozen["nwm_acquisition"]["q_lateral_chunk_keys"] == [[560, 63]]
    assert frozen["metric_and_gate_lock"][
        "score_once_without_post_label_operator_revision"
    ] is True
    assert frozen["operator_lock"][
        "parameter_fitting_on_evaluation_outcome"
    ] is False
    for claim in (
        "evaluation_values_acquired",
        "evaluation_scored",
        "flood_wave_transport_admitted",
        "benchmark_validated",
        "multi_system_generalization_validated",
        "geospatial_kernel_validated",
    ):
        assert frozen["claim_boundary"][claim] is False


def test_center_hill_evaluation_nwm_manifest_is_protocol_bounded_and_fail_closed():
    root = Path(__file__).resolve().parents[1]
    path = (
        root
        / "data/geotransport_v0_1/center_hill_evaluation/nwm/acquisition_manifest.json"
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    plan, nwm_plan, _ = compile_center_hill_evaluation_nwm_plan(values_mode=True)

    for key in (
        "schema",
        "mode",
        "evaluation_protocol",
        "registry",
        "metadata_root",
        "metadata_sha256",
        "system_id",
        "window",
        "feature_ids",
        "feature_indices",
        "requests",
        "source_semantics",
        "claim_boundary",
    ):
        assert manifest[key] == plan[key]
    assert nwm_plan.time_chunk_indices == (560,)
    assert nwm_plan.q_chunk_keys == ((560, 63),)
    assert manifest["result"] == {
        "time_count": 672,
        "feature_count": 27,
        "q_lateral_value_count": 18144,
        "velocity_value_count": 18144,
        "q_lateral_fill_value_count": 0,
        "velocity_fill_value_count": 0,
    }
    for descriptor in manifest["raw_artifacts"]:
        body = (root / descriptor["path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == descriptor["sha256"]
        assert len(body) == descriptor["size_bytes"]
    requests = build_value_requests(
        load_public_data_registry(),
        start="2022-01-06T01:00:00Z",
        end="2022-02-03T01:00:00Z",
        system_ids=("center_hill",),
        nwm_extraction_manifest=manifest,
    )
    assert len(requests) == 4
    tampered = copy.deepcopy(manifest)
    tampered["result"]["q_lateral_fill_value_count"] = 1
    with pytest.raises(
        ValueError, match="evaluation_nwm_values_manifest_result_invalid"
    ):
        build_value_requests(
            load_public_data_registry(),
            start="2022-01-06T01:00:00Z",
            end="2022-02-03T01:00:00Z",
            system_ids=("center_hill",),
            nwm_extraction_manifest=tampered,
        )


def test_center_hill_initial_state_plan_reads_only_pre_holdout_chunk():
    manifest, plan, streamflow_schema, velocity_schema = (
        compile_center_hill_initial_state_plan()
    )

    assert manifest["mode"] == "plan"
    assert manifest["request"] == {
        "variable": "streamflow",
        "key": "560.63",
        "url": (
            "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/"
            "CONUS/zarr/chrtout.zarr/streamflow/560.63"
        ),
        "maximum_bytes": 100_000_000,
    }
    assert manifest["initial_state_support"] == {
        "valid_at": "2022-02-03T00:00:00Z",
        "next_window_start": "2022-02-03T01:00:00Z",
        "lead_time_to_next_window_seconds": 3600,
        "time_chunk_indices_read": [560],
        "time_chunk_indices_forbidden": [561],
        "chunk_561_accessed": False,
    }
    assert plan.time_chunk_indices == (560,)
    assert plan.q_chunk_keys == ((560, 63),)
    assert streamflow_schema.base == velocity_schema.base
    assert manifest["claim_boundary"]["request_plan_only"] is True
    assert manifest["claim_boundary"]["streamflow_object_acquired"] is False
    assert manifest["claim_boundary"]["evaluation_outcome_loaded"] is False
    assert manifest["claim_boundary"]["chunk_561_loaded"] is False


@pytest.mark.parametrize(
    ("depth_m", "bottom_width_m", "top_width_m", "compound_top_width_m", "side_slope"),
    (
        (1.0, 10.0, 30.0, 50.0, 2.0),
        (7.0, 10.0, 30.0, 50.0, 2.0),
        (3.0, 10.0, 10.0, 50.0, 2.0),
    ),
)
def test_center_hill_initial_state_compound_area_depth_roundtrip(
    depth_m: float,
    bottom_width_m: float,
    top_width_m: float,
    compound_top_width_m: float,
    side_slope: float,
):
    area_m2 = _compound_area_at_depth(
        depth_m=depth_m,
        bottom_width_m=bottom_width_m,
        top_width_m=top_width_m,
        compound_top_width_m=compound_top_width_m,
        side_slope_horizontal_per_vertical=side_slope,
    )
    reconstructed_depth = _depth_for_compound_area(
        area_m2=area_m2,
        bottom_width_m=bottom_width_m,
        top_width_m=top_width_m,
        compound_top_width_m=compound_top_width_m,
        side_slope_horizontal_per_vertical=side_slope,
    )

    assert reconstructed_depth == pytest.approx(depth_m)


def test_center_hill_initial_state_excludes_only_zero_length_velocity_gap():
    root = Path(__file__).resolve().parents[1]
    travel = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
        ).read_text(encoding="utf-8")
    )
    feature_ids = tuple(travel["linear_referenced_path"]["feature_ids"])
    discharge = np.ones(len(feature_ids), dtype=float)
    velocity = np.ones(len(feature_ids), dtype=float)
    velocity[0] = 0.0
    route_link = (
        root
        / "data/geotransport_v0_1/route_link_nwm_v3_center_hill/"
        "RouteLink_CONUS_NWMv3_CenterHill.nc"
    )

    compiled = _compile_initial_state(
        feature_ids=feature_ids,
        discharge_m3s=discharge,
        velocity_ms=velocity,
        route_link_path=route_link,
        travel=travel,
        available_at="2026-07-27T00:00:00Z",
    )

    assert compiled["excluded_zero_length_feature_ids"] == [feature_ids[0]]
    assert compiled["excluded_positive_flow_zero_velocity_feature_ids"] == [
        feature_ids[0]
    ]
    assert compiled["active_feature_count"] == len(feature_ids) - 1
    assert compiled["diagnostics"][
        "positive_flow_zero_velocity_excluded_feature_count"
    ] == 1

    velocity[1] = 0.0
    with pytest.raises(
        ValueError,
        match="initial_state_active_positive_flow_requires_positive_velocity",
    ):
        _compile_initial_state(
            feature_ids=feature_ids,
            discharge_m3s=discharge,
            velocity_ms=velocity,
            route_link_path=route_link,
            travel=travel,
            available_at="2026-07-27T00:00:00Z",
        )


def test_center_hill_initial_state_manifest_is_causal_and_reproducible():
    root = Path(__file__).resolve().parents[1]
    manifest_path = (
        root
        / "data/geotransport_v0_1/center_hill_initial_state_nwm_v3/"
        "acquisition_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned, plan, _, _ = compile_center_hill_initial_state_plan(values_mode=True)

    for key in (
        "schema",
        "mode",
        "system_id",
        "initial_state_support",
        "feature_ids",
        "feature_indices",
        "request",
        "reused_inputs",
        "source_artifacts",
        "metadata_root",
        "metadata_sha256",
        "source_semantics",
    ):
        assert manifest[key] == planned[key]
    assert plan.time_chunk_indices == (560,)
    assert plan.q_chunk_keys == ((560, 63),)
    assert manifest["decoded_source"] == {
        "timestamps": ["2022-02-03T00:00:00Z"],
        "feature_count": 27,
        "feature_axis_coverage": "27/27",
        "streamflow_fill_value_count": 0,
        "velocity_fill_value_count": 0,
        "active_feature_count": 26,
    }
    raw = manifest["streamflow_raw_artifact"]
    assert raw["sha256"] == (
        "588759a8445fc4880a4f77ad2817a59673eb8ff4616718442911460853ba70ed"
    )
    raw_body = (root / raw["path"]).read_bytes()
    assert len(raw_body) == raw["size_bytes"] == 16_161_378
    assert hashlib.sha256(raw_body).hexdigest() == raw["sha256"]

    state = manifest["decoded_state"]
    assert state["feature_count"] == 27
    assert state["state_feature_count"] == state["active_feature_count"] == 26
    assert state["excluded_zero_length_feature_ids"] == [18434275]
    assert state["excluded_positive_flow_zero_velocity_feature_ids"] == [
        18434275
    ]
    assert state["terminal_partial_reach_state"]["feature_id"] == 18421703
    assert state["terminal_partial_reach_state"][
        "path_effective_length_m"
    ] == pytest.approx(938.4308239178366)
    assert state["terminal_partial_reach_state"][
        "kernel_effective_storage_m3"
    ] == pytest.approx(837627.712915329)

    state_descriptor = manifest["initial_state_artifact"]
    state_body = (root / state_descriptor["path"]).read_bytes()
    assert hashlib.sha256(state_body).hexdigest() == state_descriptor["sha256"]
    rows = list(csv.DictReader(io.StringIO(state_body.decode("utf-8"))))
    assert len(rows) == 26
    assert all(row["active_path_feature"] == "True" for row in rows)
    assert {int(row["feature_id"]) for row in rows} == set(
        state["active_feature_ids"]
    )
    assert all(float(row["velocity_ms"]) > 0.0 for row in rows)
    assert all(float(row["compound_depth_m"]) >= 0.0 for row in rows)
    assert all(float(row["kernel_effective_storage_m3"]) >= 0.0 for row in rows)

    assert manifest["claim_boundary"] == {
        "request_plan_only": False,
        "streamflow_object_acquired": True,
        "retrospective_modeled_initial_state_available": True,
        "operational_online_initial_state_available": False,
        "evaluation_outcome_loaded": False,
        "chunk_561_loaded": False,
        "center_hill_transition_execution_admitted": False,
        "benchmark_validated": False,
        "geospatial_kernel_validated": False,
    }


def test_center_hill_terminal_forcing_support_plan_is_outcome_isolated():
    plan = compile_center_hill_terminal_support_plan()

    source = plan["sources"]["nhdplus_fdr_fac_archive"]
    assert source["size_bytes"] == NHDPLUS_ARCHIVE_SIZE == 100_777_847
    assert source["sha256"] == NHDPLUS_ARCHIVE_SHA256
    assert source["archive_redistributed"] is False
    assert plan["terminal_feature_id"] == 18421703
    assert plan["frozen_method"]["coverage"].startswith(
        "area(intersection(splitCatchment, catchment))"
    )
    assert plan["data_isolation"] == {
        "evaluation_outcome_loaded": False,
        "evaluation_action_values_loaded": False,
        "evaluation_forcing_values_loaded": False,
        "center_hill_chunk_561_loaded": False,
    }


def test_center_hill_terminal_forcing_support_manifest_passes_d2_with_bracket():
    root = Path(__file__).resolve().parents[1]
    output_root = (
        root
        / "data/geotransport_v0_1/"
        "center_hill_terminal_forcing_support_nhdplus_v21"
    )
    manifest = json.loads(
        (output_root / "acquisition_manifest.json").read_text(encoding="utf-8")
    )
    support = json.loads(
        (output_root / "forcing_support.json").read_text(encoding="utf-8")
    )

    assert manifest["status"] == "pass_with_30m_quantization_bracket"
    assert manifest["archive_audit"]["size_bytes"] == NHDPLUS_ARCHIVE_SIZE
    assert manifest["archive_audit"]["sha256"] == NHDPLUS_ARCHIVE_SHA256
    assert manifest["selected_main_channel_cell"]["row"] == 11747
    assert manifest["selected_main_channel_cell"]["col"] == 10831
    assert manifest["selected_main_channel_cell"][
        "fac_cell_count"
    ] == 7_109_846
    assert manifest["selected_main_channel_cell"][
        "distance_to_measure_m"
    ] == pytest.approx(19.638957482551415)

    coverage = manifest["coverage_adjudication"]
    assert coverage["central_fraction"] == pytest.approx(0.8429738154993436)
    assert coverage["upstream_adjacent_fraction"] == pytest.approx(
        0.8272045786997515
    )
    assert coverage["downstream_adjacent_fraction"] == pytest.approx(
        0.9366451910995578
    )
    assert coverage["quantization_is_zero"] is False
    assert coverage["single_fraction_without_bracket_permitted"] is False
    chain = manifest["main_channel_chain"]
    assert len(chain) == 9
    assert [row["coverage_fraction"] for row in chain] == sorted(
        row["coverage_fraction"] for row in chain
    )
    assert chain[2]["role"] == "selected_nearest_main_channel_cell"
    assert manifest["gates"] == {
        key: True for key in manifest["gates"]
    }

    assert support["feature_ids"][-1] == 18421703
    assert len(support["feature_ids"]) == len(support["coverage_fractions"]) == 26
    assert support["coverage_fractions"][:-1] == [1.0] * 25
    assert support["coverage_fractions"][-1] == pytest.approx(
        coverage["central_fraction"]
    )
    ReachForcingSupport(
        feature_ids=tuple(support["feature_ids"]),
        coverage_fractions=tuple(support["coverage_fractions"]),
        support_method=support["support_method"],
        provenance_id=support["provenance_id"],
        evidence_level=support["evidence_level"],
        admitted_as_spatial_support=support["admitted_as_spatial_support"],
    )
    assert support["allocation_semantics"][
        "subcatchment_q_lateral_values_observed"
    ] is False
    assert manifest["negative_controls"]["unsnapped_raw_usgs_coordinate"][
        "split_geometry_valid"
    ] is False

    selected_descriptor = manifest["source_artifacts"]["chain_02"]
    selected_body = (root / selected_descriptor["path"]).read_bytes()
    assert len(selected_body) == selected_descriptor["size_bytes"]
    assert hashlib.sha256(selected_body).hexdigest() == selected_descriptor["sha256"]
    assert selected_descriptor["sha256"] == manifest["source_artifacts"][
        "selected_repeat"
    ]["sha256"]
    assert selected_descriptor["sha256"] == manifest["source_artifacts"][
        "nearest_centerline"
    ]["sha256"]

    claims = manifest["claim_boundary"]
    assert claims["center_hill_d2_action_forcing_gate_passed"] is True
    assert claims[
        "center_hill_retrospective_transition_input_execution_admitted"
    ] is True
    assert claims["center_hill_chunk_561_loaded"] is False
    assert claims["evaluation_outcome_loaded"] is False
    assert claims["operational_online_execution_admitted"] is False
    assert claims["benchmark_validated"] is False
    assert claims["geospatial_kernel_validated"] is False


def test_center_hill_temporal_holdout_panel_preserves_auxiliary_gap():
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_panel_report.json"
        ).read_text(encoding="utf-8")
    )
    csv_body, report = compile_center_hill_evaluation_panel()
    for key, value in report.items():
        assert frozen[key] == value
    rows = list(csv.DictReader(io.StringIO(csv_body.decode("utf-8"))))
    assert len(rows) == 672
    assert sum(row["split_role"] == "evaluation_warmup" for row in rows) == 168
    assert sum(row["split_role"] == "evaluation" for row in rows) == 504
    assert all(row["outcome_available"] == "true" for row in rows)
    missing_context = [row for row in rows if row["inflow_context_m3s"] == ""]
    assert [row["support_end_utc"] for row in missing_context] == [
        "2022-01-26T19:00:00Z"
    ]
    assert frozen["quality_summary"]["operator_input_missing_value_count"] == 0
    assert frozen["quality_summary"]["auxiliary_context_missing_value_count"] == 1
    assert frozen["quality_summary"]["outcome_missing_hour_count"] == 0
    assert frozen["claim_boundary"]["evaluation_scored"] is False
    assert frozen["claim_boundary"]["auxiliary_context_complete"] is False


def test_center_hill_frozen_temporal_holdout_records_candidate_failure():
    root = Path(__file__).resolve().parents[1]
    report = json.loads(
        (
            root
            / "benchmarks/geotransport_v0_1/center_hill_temporal_holdout_evaluation_report.json"
        ).read_text(encoding="utf-8")
    )
    output_path = root / report["output_artifact"]["path"]
    body = output_path.read_bytes()
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    assert hashlib.sha256(body).hexdigest() == report["output_artifact"]["sha256"]
    assert len(rows) == 504
    assert all(row["zero_action_m3s"] == "" for row in rows)
    observed = np.asarray([float(row["observed_m3s"]) for row in rows])
    for name, column in (
        ("candidate", "candidate_m3s"),
        ("persistence", "persistence_m3s"),
        ("direct_release", "direct_release_m3s"),
        ("no_forcing", "no_forcing_m3s"),
        ("reversed_topology", "reversed_topology_m3s"),
    ):
        predicted = np.asarray([float(row[column]) for row in rows])
        rmse = float(np.sqrt(np.mean((predicted - observed) ** 2)))
        assert rmse == pytest.approx(report["metrics"][name]["rmse_m3s"])
    assert report["overall_gate_status"] == "fail"
    assert report["gate_statuses"] == {
        "accuracy_better_than_persistence": "fail",
        "accuracy_better_than_direct_release": "pass",
        "zero_action_degrades_accuracy_and_changes_prediction": "fail",
        "no_forcing_degrades_accuracy_and_changes_prediction": "pass",
        "reversed_topology_degrades_accuracy_and_changes_prediction": "fail",
        "all_scenarios_conservative": "fail",
    }
    assert report["metrics"]["candidate"]["rmse_m3s"] > 10 * report[
        "metrics"
    ]["persistence"]["rmse_m3s"]
    assert report["metrics"]["reversed_topology"]["rmse_m3s"] < report[
        "metrics"
    ]["candidate"]["rmse_m3s"]
    assert report["scenario_failures"]["zero_action"]["phase"] == (
        "development_recompute"
    )
    for claim in (
        "registered_single_system_temporal_holdout_passed",
        "empirical_support_for_candidate_operator",
        "identified_causal_action_effect",
        "river_velocity_admitted_as_flood_wave_celerity",
        "flood_wave_transport_admitted",
        "hydrodynamically_validated",
        "benchmark_validated",
        "multi_system_generalization_validated",
        "geospatial_kernel_validated",
    ):
        assert report["claim_boundary"][claim] is False


def _zstd(values: np.ndarray, executable: str) -> bytes:
    result = subprocess.run(
        [executable, "--compress", "--stdout", "--quiet"],
        input=values.tobytes(order="C"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def test_conservation_value_plan_uses_date_bounded_rise_queries():
    requests = build_value_requests(
        load_public_data_registry(),
        start="2022-01-01T00:00:00Z",
        end="2022-01-03T00:00:00Z",
        system_ids=("blue_mesa_conservation",),
    )

    assert len(requests) == 5
    for request in requests:
        query = parse_qs(urlparse(request.url).query)
        assert query["dateTime[after]"] == ["2022-01-01T00:00:00Z"]
        assert query["dateTime[before]"] == ["2022-01-03T00:00:00Z"]
        assert request.paginated is True


def test_geotransport_evaluator_requires_all_mechanism_gates():
    report = evaluate_geotransport(
        GeoTransportEvaluationSeries(
            system_ids=("held-out",) * 4,
            observed=(1.0, 2.0, 3.0, 4.0),
            predicted=(1.1, 2.0, 2.9, 4.0),
            persistence=(0.0, 1.0, 2.0, 3.0),
            state_only=(0.2, 1.2, 2.2, 3.2),
            domain_baseline=(0.5, 1.5, 2.5, 3.5),
            zero_action_prediction=(0.0, 0.0, 0.0, 0.0),
            no_forcing_prediction=(4.0, 4.0, 4.0, 4.0),
            reversed_topology_prediction=(4.0, 3.0, 2.0, 1.0),
            mass_balance_residual=(0.0, 1e-9, -1e-9, 0.0),
        ),
        split=EvaluationSplit(("train-a", "train-b"), ("held-out",)),
    )

    assert report["overall_gate_status"] == "pass"
    assert set(report["gate_statuses"].values()) == {"pass"}
    assert report["claim_boundary"]["identified_causal_action_effect"] is False


def test_geotransport_evaluator_does_not_let_accuracy_hide_missing_ablation():
    report = evaluate_geotransport(
        GeoTransportEvaluationSeries(
            system_ids=("held-out", "held-out"),
            observed=(1.0, 2.0),
            predicted=(1.0, 2.0),
            persistence=(0.0, 1.0),
            state_only=(0.5, 1.5),
            mass_balance_residual=(0.0, 0.0),
        ),
        split=EvaluationSplit(("train",), ("held-out",)),
    )

    assert report["gate_statuses"][
        "accuracy_better_than_persistence_and_state_only"
    ] == "pass"
    assert report["overall_gate_status"] == "indeterminate"


def test_reservoir_conservation_reports_unclosed_balance():
    report = evaluate_reservoir_conservation(
        observed_stock_change=(7.0, 5.0),
        inflow_volume=(10.0, 10.0),
        release_volume=(2.0, 3.0),
        evaporation_volume=(1.0, 1.0),
        tolerance=0.5,
    )

    assert report["gate"]["gate_status"] == "fail"
    assert report["residual"]["maximum_absolute"] == pytest.approx(1.0)
