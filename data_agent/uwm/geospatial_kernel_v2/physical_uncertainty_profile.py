"""Typed feature-aligned uncertainty profiles for diagnostic physical ensembles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

PHYSICAL_UNCERTAINTY_PROFILE_SCHEMA = (
    "gwm.geospatial_kernel.feature_aligned_physical_uncertainty_profile.v1"
)
PHYSICAL_UNCERTAINTY_SOURCE_NAMES = (
    "initial_storage",
    "manning_n",
    "modeled_forcing",
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class PhysicalUncertaintySource:
    """Provenance and claim semantics for one uncertainty amplitude source."""

    source_name: str
    semantic_role: str
    provenance_ids: tuple[str, ...]
    evidence_window_end_utc: datetime | None = None
    evaluation_outcome_derived: bool = False
    admitted_as_calibrated_uncertainty: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_name, str)
            or self.source_name not in PHYSICAL_UNCERTAINTY_SOURCE_NAMES
        ):
            raise ValueError("physical_uncertainty_source_name_invalid")
        if not isinstance(self.semantic_role, str) or not self.semantic_role.strip():
            raise ValueError("physical_uncertainty_source_semantic_role_required")
        if (
            not self.provenance_ids
            or len(self.provenance_ids) != len(set(self.provenance_ids))
            or any(
                not isinstance(value, str) or not value.strip()
                for value in self.provenance_ids
            )
        ):
            raise ValueError("physical_uncertainty_source_provenance_invalid")
        if self.evidence_window_end_utc is not None and not _aware(
            self.evidence_window_end_utc
        ):
            raise ValueError("physical_uncertainty_source_evidence_time_must_be_aware")
        if not isinstance(self.evaluation_outcome_derived, bool) or not isinstance(
            self.admitted_as_calibrated_uncertainty, bool
        ):
            raise ValueError("physical_uncertainty_source_claim_flags_invalid")
        if self.evaluation_outcome_derived:
            raise ValueError("physical_uncertainty_source_outcome_derived_forbidden")

    def as_dict(self) -> dict[str, object]:
        return {
            "source_name": self.source_name,
            "semantic_role": self.semantic_role,
            "provenance_ids": list(self.provenance_ids),
            "evidence_window_end_utc": (
                self.evidence_window_end_utc.isoformat()
                if self.evidence_window_end_utc is not None
                else None
            ),
            "evaluation_outcome_derived": self.evaluation_outcome_derived,
            "admitted_as_calibrated_uncertainty": (
                self.admitted_as_calibrated_uncertainty
            ),
        }


@dataclass(frozen=True)
class FeatureAlignedPhysicalUncertaintyProfile:
    """Three physical amplitude fields aligned to one directed reach network."""

    profile_id: str
    feature_ids: tuple[int, ...]
    initial_storage_fraction_by_feature: tuple[float, ...]
    manning_n_fraction_by_feature: tuple[float, ...]
    modeled_forcing_fraction_by_feature: tuple[float, ...]
    initial_storage_source: PhysicalUncertaintySource
    manning_n_source: PhysicalUncertaintySource
    modeled_forcing_source: PhysicalUncertaintySource
    evaluation_window_start_utc: datetime
    diagnostic_only: bool = True
    admitted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError("physical_uncertainty_profile_identity_required")
        if (
            not self.feature_ids
            or len(self.feature_ids) != len(set(self.feature_ids))
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in self.feature_ids
            )
        ):
            raise ValueError("physical_uncertainty_profile_feature_ids_invalid")
        if not _aware(self.evaluation_window_start_utc):
            raise ValueError("physical_uncertainty_profile_evaluation_time_must_be_aware")
        if self.diagnostic_only is not True or self.admitted is not False:
            raise ValueError("physical_uncertainty_profile_must_remain_diagnostic")

        fields = {
            "initial_storage": np.asarray(
                self.initial_storage_fraction_by_feature, dtype=float
            ),
            "manning_n": np.asarray(self.manning_n_fraction_by_feature, dtype=float),
            "modeled_forcing": np.asarray(
                self.modeled_forcing_fraction_by_feature, dtype=float
            ),
        }
        count = len(self.feature_ids)
        if any(value.shape != (count,) for value in fields.values()):
            raise ValueError("physical_uncertainty_profile_feature_axis_mismatch")
        if any(not np.isfinite(value).all() for value in fields.values()):
            raise ValueError("physical_uncertainty_profile_fraction_nonfinite")
        if any(
            bool((value < 0.0).any()) or bool((value >= 1.0).any())
            for value in fields.values()
        ):
            raise ValueError(
                "physical_uncertainty_profile_fraction_outside_half_open_unit_interval"
            )
        if any(not bool((value > 0.0).any()) for value in fields.values()):
            raise ValueError("physical_uncertainty_profile_source_has_no_variation")

        sources = {
            "initial_storage": self.initial_storage_source,
            "manning_n": self.manning_n_source,
            "modeled_forcing": self.modeled_forcing_source,
        }
        if any(source.source_name != name for name, source in sources.items()):
            raise ValueError("physical_uncertainty_profile_source_binding_invalid")
        if any(
            source.admitted_as_calibrated_uncertainty
            for source in sources.values()
        ):
            raise ValueError("physical_uncertainty_profile_sources_must_be_uncalibrated")
        if any(
            source.evidence_window_end_utc is not None
            and source.evidence_window_end_utc > self.evaluation_window_start_utc
            for source in sources.values()
        ):
            raise ValueError("physical_uncertainty_profile_evidence_crosses_evaluation_window")

        for name, value in fields.items():
            attribute = {
                "initial_storage": "initial_storage_fraction_by_feature",
                "manning_n": "manning_n_fraction_by_feature",
                "modeled_forcing": "modeled_forcing_fraction_by_feature",
            }[name]
            object.__setattr__(self, attribute, tuple(float(item) for item in value))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PHYSICAL_UNCERTAINTY_PROFILE_SCHEMA,
            "profile_id": self.profile_id,
            "feature_ids": list(self.feature_ids),
            "fractions_by_feature": {
                "initial_storage": list(
                    self.initial_storage_fraction_by_feature
                ),
                "manning_n": list(self.manning_n_fraction_by_feature),
                "modeled_forcing": list(
                    self.modeled_forcing_fraction_by_feature
                ),
            },
            "sources": {
                "initial_storage": self.initial_storage_source.as_dict(),
                "manning_n": self.manning_n_source.as_dict(),
                "modeled_forcing": self.modeled_forcing_source.as_dict(),
            },
            "evaluation_window_start_utc": (
                self.evaluation_window_start_utc.isoformat()
            ),
            "diagnostic_only": self.diagnostic_only,
            "admitted": self.admitted,
            "claim_boundary": {
                "feature_aligned_amplitudes_compiled": True,
                "evaluation_outcome_used": False,
                "calibrated_probability_distribution": False,
                "forecast_skill_evidence_produced": False,
            },
        }
