from __future__ import annotations

import inspect
import json

import pytest

from scripts.compile_geospatial_kernel_external_uncertainty_profiles import (
    DEFAULT_OUTPUT,
    SYSTEM_IDS,
    compile_external_uncertainty_profiles,
)


@pytest.fixture(scope="module")
def profile_report():
    return compile_external_uncertainty_profiles()


def test_external_profile_report_replays_committed_artifact(profile_report) -> None:
    assert profile_report == json.loads(DEFAULT_OUTPUT.read_bytes())
    assert profile_report["execution_gates"] == {
        "system_count": 2,
        "all_system_gates_passed": True,
    }


def test_external_profile_compiler_has_no_outcome_or_score_input(profile_report) -> None:
    parameters = set(inspect.signature(compile_external_uncertainty_profiles).parameters)
    assert not parameters.intersection(
        {"outcome_path", "target", "future_target", "score", "loss", "observation"}
    )
    assert profile_report["data_isolation"]["evaluation_outcome_loaded"] is False
    assert profile_report["data_isolation"]["evaluation_score_loaded"] is False
    assert profile_report["data_isolation"]["issue_observation_loaded"] is False
    assert profile_report["claim_boundary"]["amplitudes_outcome_independent"] is True
    assert (
        profile_report["claim_boundary"]["amplitudes_calibrated_as_forecast_error"]
        is False
    )


def test_real_profiles_close_prior_state_and_preserve_source_semantics(
    profile_report,
) -> None:
    expected_features = {"center_hill": 435, "j_percy_priest": 43}
    for system_id in SYSTEM_IDS:
        system = profile_report["systems"][system_id]
        profile = system["profile"]
        assert system["feature_count"] == expected_features[system_id]
        assert system["execution_gates"]["all_passed"] is True
        assert system["state_closure"]["transition_count"] == 672
        assert (
            system["state_closure"]["maximum_mass_residual_to_tolerance_ratio"]
            <= 1.0
        )
        assert profile["sources"]["initial_storage"]["semantic_role"] == (
            "model_closure_discrepancy"
        )
        assert profile["sources"]["manning_n"]["semantic_role"] == (
            "hydraulic_structural_contrast"
        )
        assert profile["sources"]["modeled_forcing"]["semantic_role"] == (
            "forcing_change_proxy"
        )
        assert all(
            source["evaluation_outcome_derived"] is False
            for source in profile["sources"].values()
        )
        assert profile["admitted"] is False


def test_real_profile_amplitudes_are_feature_aligned_and_not_fixed_priors(
    profile_report,
) -> None:
    for system_id in SYSTEM_IDS:
        system = profile_report["systems"][system_id]
        count = system["feature_count"]
        fractions = system["profile"]["fractions_by_feature"]
        assert all(len(values) == count for values in fractions.values())
        assert system["amplitude_summary"]["initial_storage"]["p90"] > 0.9
        assert system["amplitude_summary"]["manning_n"]["median"] == pytest.approx(
            1.0 / 3.0
        )
        assert (
            system["amplitude_summary"]["modeled_forcing"][
                "nonzero_feature_count"
            ]
            > 0
        )
