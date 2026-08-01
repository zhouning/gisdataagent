import csv
import inspect
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from data_agent.uwm.geospatial_kernel_v2 import ReachForcingSupport, StockState
from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_MODES,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)
from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_rollout import (
    execute_horizon_assimilation_issue,
)
from scripts.evaluate_geospatial_kernel_issue_state_assimilation import (
    _iso,
    _mainstem_ids,
)
from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
    _geometry,
    _network,
    _read_npy,
)
from scripts.run_geotransport_v2_blind_validation_outcome_free import (
    _parse_actions,
    _read_verified,
)
from scripts.score_geotransport_v2_blind_validation import _outcome_values

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_protocol.json"
)
INPUT_PATH = ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_inputs_report.json"
)
OUTCOME_PATH = ROOT / (
    "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_outcomes_report.json"
)
POLICY_PATH = ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_policy_freeze.json"
)
EXPECTED_PATH = ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_distance_localized_assimilation_posthoc/predictions.csv"
)


@pytest.fixture(scope="module")
def real_issue_inputs():
    protocol = json.loads(PROTOCOL_PATH.read_bytes())
    inputs = json.loads(INPUT_PATH.read_bytes())
    outcomes = json.loads(OUTCOME_PATH.read_bytes())
    policy = HorizonAssimilationPolicy.from_dict(
        json.loads(POLICY_PATH.read_bytes())["policy"]
    )
    expected_rows = list(csv.DictReader(EXPECTED_PATH.open(encoding="utf-8")))
    result = {}
    for system_id in ("center_hill", "j_percy_priest"):
        lock = protocol["systems"][system_id]
        system_inputs = inputs["systems"][system_id]
        topology = json.loads(_read_verified(lock["topology_report"]))
        network_payload = json.loads(
            _read_verified(topology["artifacts"]["full_subnetwork"])
        )
        network = _network(network_payload["network"])
        mainstem_ids, _ = _mainstem_ids(
            system_id=system_id,
            topology=topology,
            network_payload=network_payload,
            network=network,
        )
        arrays = {
            name: _read_npy(descriptor)
            for name, descriptor in system_inputs["decoded_arrays"].items()
        }
        feature_ids = tuple(int(value) for value in arrays["feature_ids"])
        initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
        route_link_descriptor = topology["artifacts"]["route_link_subset"]
        route_link_body = _read_verified(route_link_descriptor)
        geometry = _geometry(
            ROOT / route_link_descriptor["path"],
            network,
            route_link_body,
        )
        actions = _parse_actions(_read_verified(system_inputs["action_values"]))
        issue_time = min(actions)
        observations = _outcome_values(
            _read_verified(outcomes["systems"][system_id]["outcome_values"])
        )
        terminal_fraction = float(
            lock["forcing_support"]["partial_terminal_reach_fraction"]
        )
        forcing_support = ReachForcingSupport(
            feature_ids=feature_ids,
            coverage_fractions=tuple(
                terminal_fraction if value == network.outlet_feature_id else 1.0
                for value in feature_ids
            ),
            support_method=str(
                lock["forcing_support"]["partial_terminal_reach_method"]
            ),
            provenance_id=f"test:{system_id}:forcing-support",
            evidence_level="derived",
            admitted_as_spatial_support=True,
        )
        reference_floor = np.maximum(
            np.asarray(network.effective_lengths_m, dtype=float)
            * np.asarray(geometry.bottom_width_m, dtype=float)
            * 0.01,
            1.0,
        )
        reference_storage = np.where(
            initial_storage > 0.0,
            initial_storage,
            reference_floor,
        )
        kwargs = {
            "system_id": system_id,
            "policy": policy,
            "network": network,
            "geometry": geometry,
            "modeled_stock": StockState(
                values=tuple(float(value) for value in initial_storage),
                unit="m3",
                provenance_id=f"test:{system_id}:modeled-stock",
            ),
            "reference_storage_m3": tuple(
                float(value) for value in reference_storage
            ),
            "mainstem_feature_ids": mainstem_ids,
            "reference_time": issue_time - timedelta(hours=1),
            "issue_time": issue_time,
            "issue_observed_outlet_m3s": observations[_iso(issue_time)],
            "observation_available_at": issue_time,
            "action_release_m3s_by_step": tuple(
                actions[issue_time + timedelta(hours=offset)]
                for offset in range(12)
            ),
            "q_lateral_m3s_by_step": tuple(
                tuple(float(value) for value in arrays["q_lateral_m3s"][offset])
                for offset in range(12)
            ),
            "forcing_support": forcing_support,
        }
        result[system_id] = {
            "kwargs": kwargs,
            "expected": {
                (row["mode"], int(row["horizon_hours"])): float(
                    row["predicted_outlet_m3s"]
                )
                for row in expected_rows
                if row["system_id"] == system_id and row["issue_index"] == "0"
            },
        }
    return result


@pytest.fixture(scope="module")
def real_rollouts(real_issue_inputs):
    return {
        system_id: execute_horizon_assimilation_issue(**payload["kwargs"])
        for system_id, payload in real_issue_inputs.items()
    }


def test_outcome_free_core_replays_both_real_systems_exactly(
    real_issue_inputs,
    real_rollouts,
) -> None:
    for system_id, rollout in real_rollouts.items():
        expected = real_issue_inputs[system_id]["expected"]
        for mode in HORIZON_ASSIMILATION_MODES:
            for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
                assert rollout.mode_rollout(mode).prediction_for_horizon(
                    horizon
                ) == pytest.approx(expected[(mode, horizon)], abs=1e-12)


def test_policy_routes_real_predictions_without_changing_constituents(
    real_issue_inputs,
    real_rollouts,
) -> None:
    for system_id, rollout in real_rollouts.items():
        expected = real_issue_inputs[system_id]["expected"]
        for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
            mode = rollout.policy.mode_for_horizon(horizon)
            assert rollout.selected_prediction_for_horizon(horizon) == pytest.approx(
                expected[(mode, horizon)],
                abs=1e-12,
            )


def test_real_rollouts_close_all_ledgers_and_expose_no_score(real_rollouts) -> None:
    parameter_names = set(inspect.signature(execute_horizon_assimilation_issue).parameters)
    assert not parameter_names.intersection({"target", "outcome", "score", "loss"})
    for rollout in real_rollouts.values():
        encoded = rollout.as_dict()
        assert rollout.all_analysis_ledgers_passed is True
        assert rollout.all_physical_mass_balances_passed is True
        assert rollout.localized_updates_preserved_all_branch_states is True
        assert sum(
            value.physical_mass_balance_check_count
            for value in rollout.mode_rollouts
        ) == 48
        assert encoded["data_isolation"] == {
            "future_target_argument_accepted": False,
            "score_or_loss_argument_accepted": False,
            "future_target_used": False,
            "scores_computed": False,
        }


def test_negative_issue_observation_falls_back_to_nominal(real_issue_inputs) -> None:
    kwargs = dict(real_issue_inputs["j_percy_priest"]["kwargs"])
    kwargs["issue_observed_outlet_m3s"] = -1.0
    rollout = execute_horizon_assimilation_issue(**kwargs)
    nominal = rollout.mode_rollout("nominal")

    for mode in HORIZON_ASSIMILATION_MODES[1:]:
        candidate = rollout.mode_rollout(mode)
        assert candidate.observation_assimilated is False
        assert candidate.observation_fallback_reason == (
            "negative_discharge_outside_forward_manning_domain"
        )
        assert candidate.predictions_m3s == pytest.approx(nominal.predictions_m3s)


def test_observation_not_available_at_issue_is_rejected(real_issue_inputs) -> None:
    kwargs = dict(real_issue_inputs["j_percy_priest"]["kwargs"])
    kwargs["observation_available_at"] = kwargs["issue_time"] + timedelta(seconds=1)

    with pytest.raises(ValueError, match="horizon_assimilation_issue_inputs_invalid"):
        execute_horizon_assimilation_issue(**kwargs)
