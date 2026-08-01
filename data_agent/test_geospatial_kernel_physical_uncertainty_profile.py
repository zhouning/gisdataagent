from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.physical_uncertainty_profile import (
    PHYSICAL_UNCERTAINTY_PROFILE_SCHEMA,
    FeatureAlignedPhysicalUncertaintyProfile,
    PhysicalUncertaintySource,
)

EVALUATION_START = datetime(2022, 4, 28, 1, tzinfo=UTC)


def _source(name: str, **overrides) -> PhysicalUncertaintySource:
    values = {
        "source_name": name,
        "semantic_role": f"{name}_diagnostic_proxy",
        "provenance_ids": (f"sha256:{name}",),
        "evidence_window_end_utc": EVALUATION_START,
    }
    values.update(overrides)
    return PhysicalUncertaintySource(**values)


def _profile(**overrides) -> FeatureAlignedPhysicalUncertaintyProfile:
    values = {
        "profile_id": "synthetic:feature-profile",
        "feature_ids": (30, 10, 20),
        "initial_storage_fraction_by_feature": (0.1, 0.2, 0.3),
        "manning_n_fraction_by_feature": (1.0 / 3.0,) * 3,
        "modeled_forcing_fraction_by_feature": (0.0, 0.2, 0.4),
        "initial_storage_source": _source("initial_storage"),
        "manning_n_source": _source("manning_n"),
        "modeled_forcing_source": _source("modeled_forcing"),
        "evaluation_window_start_utc": EVALUATION_START,
    }
    values.update(overrides)
    return FeatureAlignedPhysicalUncertaintyProfile(**values)


def test_feature_profile_preserves_axis_provenance_and_claim_boundary() -> None:
    profile = _profile()
    payload = profile.as_dict()

    assert payload["schema"] == PHYSICAL_UNCERTAINTY_PROFILE_SCHEMA
    assert payload["feature_ids"] == [30, 10, 20]
    assert payload["fractions_by_feature"]["modeled_forcing"] == [0.0, 0.2, 0.4]
    assert payload["sources"]["initial_storage"]["evaluation_outcome_derived"] is False
    assert payload["claim_boundary"] == {
        "feature_aligned_amplitudes_compiled": True,
        "evaluation_outcome_used": False,
        "calibrated_probability_distribution": False,
        "forecast_skill_evidence_produced": False,
    }


def test_feature_profile_fails_closed_on_outcome_or_evaluation_window_leakage() -> None:
    with pytest.raises(ValueError, match="outcome_derived_forbidden"):
        _source("initial_storage", evaluation_outcome_derived=True)

    with pytest.raises(ValueError, match="evidence_crosses_evaluation_window"):
        _profile(
            initial_storage_source=_source(
                "initial_storage",
                evidence_window_end_utc=EVALUATION_START + timedelta(hours=1),
            )
        )


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"modeled_forcing_fraction_by_feature": (0.1, 0.2)}, "axis_mismatch"),
        ({"initial_storage_fraction_by_feature": (0.0, 0.0, 0.0)}, "no_variation"),
        ({"manning_n_fraction_by_feature": (0.2, 1.0, 0.3)}, "outside_half_open"),
        (
            {
                "manning_n_source": _source(
                    "manning_n", admitted_as_calibrated_uncertainty=True
                )
            },
            "sources_must_be_uncalibrated",
        ),
        ({"admitted": True}, "must_remain_diagnostic"),
    ),
)
def test_feature_profile_rejects_invalid_amplitudes_or_claims(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _profile(**override)
