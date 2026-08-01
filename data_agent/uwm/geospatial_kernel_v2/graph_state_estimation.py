"""Frozen low-rank graph update directions for causal network-state analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

GRAPH_STATE_UPDATE_PARAMETERS_SCHEMA = "gwm.geospatial_kernel.graph_state_update_parameters.v1"
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}
REGRESSION_GAIN_SEMANTICS = (
    "bounded regression in normalized log storage on disjoint authoritative-DAG upstream support"
)
DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS = (
    "deterministic unit gain in normalized log storage on an authoritative mainstem path"
)
DETERMINISTIC_DISTANCE_LOCALIZED_GAIN_SEMANTICS = (
    "deterministic path-distance-localized gain in normalized log storage on an "
    "authoritative mainstem path"
)
_GAIN_SEMANTICS = {
    REGRESSION_GAIN_SEMANTICS,
    DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS,
    DETERMINISTIC_DISTANCE_LOCALIZED_GAIN_SEMANTICS,
}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class GraphStateUpdateParameters:
    """A disjoint, low-rank log-storage update basis keyed by gauge feature."""

    feature_ids: tuple[int, ...]
    observation_feature_ids: tuple[int, ...]
    reference_storage_m3: tuple[float, ...]
    log_storage_gain_rows: tuple[tuple[float, ...], ...]
    training_system_ids: tuple[str, ...]
    training_data_start: datetime
    training_data_end: datetime
    provenance_id: str
    evidence_level: str
    admitted: bool
    modeled_state_based: bool
    possible_nudging: bool
    outcome_calibrated: bool
    gain_semantics: str = REGRESSION_GAIN_SEMANTICS

    def __post_init__(self) -> None:
        if (
            not self.feature_ids
            or len(self.feature_ids) != len(set(self.feature_ids))
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
                for value in self.feature_ids
            )
        ):
            raise ValueError("graph_state_update_feature_ids_invalid")
        if (
            not self.observation_feature_ids
            or len(self.observation_feature_ids) != len(set(self.observation_feature_ids))
            or not set(self.observation_feature_ids).issubset(self.feature_ids)
        ):
            raise ValueError("graph_state_update_observation_features_invalid")
        reference = np.asarray(self.reference_storage_m3, dtype=float)
        if (
            reference.shape != (len(self.feature_ids),)
            or not np.isfinite(reference).all()
            or bool((reference <= 0.0).any())
        ):
            raise ValueError("graph_state_update_reference_storage_invalid")
        gains = np.asarray(self.log_storage_gain_rows, dtype=float)
        expected_shape = (len(self.observation_feature_ids), len(self.feature_ids))
        if (
            gains.shape != expected_shape
            or not np.isfinite(gains).all()
            or bool((gains < 0.0).any())
            or bool((gains > 1.0).any())
        ):
            raise ValueError("graph_state_update_gain_matrix_invalid")
        feature_index = {feature_id: index for index, feature_id in enumerate(self.feature_ids)}
        for row_index, _observation_feature_id in enumerate(self.observation_feature_ids):
            if any(
                gains[row_index, feature_index[feature_id]] != 0.0
                for feature_id in self.observation_feature_ids
            ):
                raise ValueError("graph_state_update_gauge_columns_must_be_zero")
            if not bool((gains[row_index] > 0.0).any()):
                raise ValueError("graph_state_update_nonempty_spatial_support_required")
        if bool(((gains > 0.0).sum(axis=0) > 1).any()):
            raise ValueError("graph_state_update_support_rows_must_be_disjoint")
        object.__setattr__(
            self,
            "reference_storage_m3",
            tuple(float(value) for value in reference),
        )
        object.__setattr__(
            self,
            "log_storage_gain_rows",
            tuple(tuple(float(value) for value in row) for row in gains),
        )
        if (
            not self.training_system_ids
            or len(self.training_system_ids) != len(set(self.training_system_ids))
            or any(not value.strip() for value in self.training_system_ids)
        ):
            raise ValueError("graph_state_update_training_system_ids_required")
        if not _aware(self.training_data_start) or not _aware(self.training_data_end):
            raise ValueError("graph_state_update_training_times_must_be_aware")
        if self.training_data_end < self.training_data_start:
            raise ValueError("graph_state_update_training_window_reversed")
        if not self.provenance_id.strip():
            raise ValueError("graph_state_update_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("graph_state_update_evidence_level_invalid")
        flags = (
            self.admitted,
            self.modeled_state_based,
            self.possible_nudging,
            self.outcome_calibrated,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise ValueError("graph_state_update_flags_must_be_boolean")
        if not self.modeled_state_based:
            raise ValueError("graph_state_update_modeled_state_basis_required")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_graph_state_update_cannot_be_admitted")
        if self.gain_semantics not in _GAIN_SEMANTICS:
            raise ValueError("graph_state_update_gain_semantics_invalid")
        if (
            self.gain_semantics
            in {
                DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS,
                DETERMINISTIC_DISTANCE_LOCALIZED_GAIN_SEMANTICS,
            }
            and self.outcome_calibrated
        ):
            raise ValueError("deterministic_graph_state_update_cannot_be_outcome_calibrated")

    @property
    def rank(self) -> int:
        return len(self.observation_feature_ids)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": GRAPH_STATE_UPDATE_PARAMETERS_SCHEMA,
            "feature_ids": list(self.feature_ids),
            "observation_feature_ids": list(self.observation_feature_ids),
            "reference_storage_m3": list(self.reference_storage_m3),
            "log_storage_gain_rows": [list(row) for row in self.log_storage_gain_rows],
            "rank": self.rank,
            "training_system_ids": list(self.training_system_ids),
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "modeled_state_based": self.modeled_state_based,
            "possible_nudging": self.possible_nudging,
            "outcome_calibrated": self.outcome_calibrated,
            "gain_semantics": self.gain_semantics,
        }
