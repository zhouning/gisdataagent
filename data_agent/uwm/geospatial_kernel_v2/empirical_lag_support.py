"""Typed empirical lag-support sets for geospatial response relations."""

from __future__ import annotations

from dataclasses import dataclass
import math


SCHEMA = "gwm.geospatial.empirical_lag_support.v1"
RELATION_SCHEMA = "gwm.geospatial.empirical_graph_relation_lag_support.v1"
LAG_CANDIDATES_HOURS = tuple(range(13))
MINIMUM_PEARSON_R = 0.8
MAXIMUM_BEST_LOSS_PEARSON_R = 0.02
MINIMUM_PAIR_COUNT = 60


@dataclass(frozen=True)
class LagCorrelationEvidence:
    lag_hours: int
    pair_count: int
    pearson_r: float | None

    def __post_init__(self) -> None:
        if (
            self.lag_hours not in LAG_CANDIDATES_HOURS
            or self.pair_count < 0
            or (
                self.pearson_r is not None
                and (
                    not math.isfinite(self.pearson_r)
                    or not -1.0 <= self.pearson_r <= 1.0
                )
            )
        ):
            raise ValueError("empirical_lag_correlation_evidence_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "lag_hours": self.lag_hours,
            "pair_count": self.pair_count,
            "pearson_r": self.pearson_r,
        }


@dataclass(frozen=True)
class EmpiricalLagSupport:
    candidates: tuple[LagCorrelationEvidence, ...]
    best_lag_hours: int
    best_pearson_r: float
    supported_lags_hours: tuple[int, ...]
    response_rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            tuple(value.lag_hours for value in self.candidates)
            != LAG_CANDIDATES_HOURS
            or self.best_lag_hours not in LAG_CANDIDATES_HOURS
            or not math.isfinite(self.best_pearson_r)
            or tuple(sorted(set(self.supported_lags_hours)))
            != self.supported_lags_hours
        ):
            raise ValueError("empirical_lag_support_invalid")
        if bool(self.response_rejection_reasons) == bool(
            self.supported_lags_hours
        ):
            raise ValueError("empirical_lag_support_admission_inconsistent")

    @property
    def response_detectable(self) -> bool:
        return not self.response_rejection_reasons

    @property
    def exact_hour_resolved(self) -> bool:
        return len(self.supported_lags_hours) == 1

    @property
    def support_is_contiguous(self) -> bool:
        if not self.supported_lags_hours:
            return False
        return self.supported_lags_hours == tuple(
            range(
                self.supported_lags_hours[0],
                self.supported_lags_hours[-1] + 1,
            )
        )

    @property
    def support_interval_hours(self) -> tuple[int, int] | None:
        if not self.supported_lags_hours or not self.support_is_contiguous:
            return None
        return self.supported_lags_hours[0], self.supported_lags_hours[-1]

    def require_empirical_support_set(self) -> tuple[int, ...]:
        if not self.response_detectable:
            raise ValueError("empirical_lag_support_response_not_detectable")
        return self.supported_lags_hours

    def require_exact_hour(self) -> int:
        if not self.exact_hour_resolved:
            raise ValueError("empirical_lag_support_exact_hour_not_resolved")
        return self.supported_lags_hours[0]

    def require_physical_travel_time(self) -> None:
        raise ValueError("empirical_lag_support_is_not_physical_travel_time")

    def promote_to_runtime_delay(self) -> None:
        raise ValueError("empirical_lag_support_runtime_delay_unadmitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "lag_candidates_hours": list(LAG_CANDIDATES_HOURS),
            "thresholds": {
                "minimum_pearson_r": MINIMUM_PEARSON_R,
                "maximum_best_loss_pearson_r": (
                    MAXIMUM_BEST_LOSS_PEARSON_R
                ),
                "minimum_pair_count": MINIMUM_PAIR_COUNT,
                "best_lag_must_be_interior": True,
            },
            "candidates": [value.as_dict() for value in self.candidates],
            "best_lag_hours": self.best_lag_hours,
            "best_pearson_r": self.best_pearson_r,
            "response_detectable": self.response_detectable,
            "response_rejection_reasons": list(
                self.response_rejection_reasons
            ),
            "supported_lags_hours": list(self.supported_lags_hours),
            "support_is_contiguous": self.support_is_contiguous,
            "support_interval_hours": (
                None
                if self.support_interval_hours is None
                else list(self.support_interval_hours)
            ),
            "exact_hour_resolved": self.exact_hour_resolved,
            "physical_travel_time_admitted": False,
            "runtime_delay_admitted": False,
        }


@dataclass(frozen=True)
class EmpiricalGraphRelationLagSupport:
    source_boundary_id: str
    source_spatial_role: str
    target_site_id: str
    target_comid: int
    relation_role: str
    evidence_event_id: str
    lag_support: EmpiricalLagSupport

    def __post_init__(self) -> None:
        if (
            not self.source_boundary_id
            or self.source_spatial_role != "operational_tailwater_zone"
            or not self.target_site_id
            or self.target_comid <= 0
            or self.relation_role != "empirical_downstream_response"
            or not self.evidence_event_id
            or not self.lag_support.response_detectable
        ):
            raise ValueError("empirical_graph_relation_lag_support_invalid")

    def require_hydraulic_edge_travel_time(self) -> None:
        raise ValueError(
            "empirical_graph_relation_support_is_not_hydraulic_edge_time"
        )

    def promote_to_runtime_transition(self) -> None:
        raise ValueError(
            "empirical_graph_relation_runtime_transition_unadmitted"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": RELATION_SCHEMA,
            "source": {
                "boundary_id": self.source_boundary_id,
                "spatial_role": self.source_spatial_role,
                "same_sensor_as_target": False,
            },
            "target": {
                "site_id": self.target_site_id,
                "comid": self.target_comid,
                "spatial_role": "observed_outlet_node",
            },
            "relation_role": self.relation_role,
            "evidence_event_id": self.evidence_event_id,
            "lag_support": self.lag_support.as_dict(),
            "admitted_consumers": [
                "empirical_graph_relation_diagnostic",
                "support_aware_temporal_reasoning",
            ],
            "forbidden_consumers": [
                "hydraulic_edge_travel_time",
                "deterministic_runtime_transition",
            ],
        }


def compile_empirical_lag_support(
    candidates: tuple[LagCorrelationEvidence, ...],
) -> EmpiricalLagSupport:
    if (
        len(candidates) != len(LAG_CANDIDATES_HOURS)
        or tuple(value.lag_hours for value in candidates)
        != LAG_CANDIDATES_HOURS
    ):
        raise ValueError("empirical_lag_support_thirteen_ordered_lags_required")
    eligible = [value for value in candidates if value.pearson_r is not None]
    if not eligible:
        raise ValueError("empirical_lag_support_finite_correlation_required")
    best = max(
        eligible,
        key=lambda value: (float(value.pearson_r), -value.lag_hours),
    )
    reasons = []
    if float(best.pearson_r) < MINIMUM_PEARSON_R:
        reasons.append("best_lag_pearson_below_0_8")
    if best.lag_hours in {0, 12}:
        reasons.append("best_lag_is_search_boundary")
    if best.pair_count < MINIMUM_PAIR_COUNT:
        reasons.append("best_lag_pair_count_below_60")
    supported = ()
    if not reasons:
        supported = tuple(
            value.lag_hours
            for value in candidates
            if value.pearson_r is not None
            and value.pair_count >= MINIMUM_PAIR_COUNT
            and float(value.pearson_r) >= MINIMUM_PEARSON_R
            and float(best.pearson_r) - float(value.pearson_r)
            <= MAXIMUM_BEST_LOSS_PEARSON_R
        )
    return EmpiricalLagSupport(
        candidates,
        best.lag_hours,
        float(best.pearson_r),
        supported,
        tuple(reasons),
    )
