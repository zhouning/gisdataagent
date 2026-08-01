"""Typed state-dependent Manning path-response diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .branching_network import DirectedReachNetwork
from .contracts import ReachHydraulicGeometry, TravelTimePrior
from .kinematic_wave import _area_for_discharge, _manning_celerity


MANNING_PATH_RESPONSE_SCHEMA = (
    "gwm.geospatial_kernel.manning_path_response_diagnostic.v1"
)
MANNING_PATH_RESPONSE_METHOD = (
    "sum_RouteLink_effective_length_over_state_dependent_Manning_dQ_dA_celerity"
)
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


@dataclass(frozen=True)
class ManningReachResponse:
    feature_id: int
    effective_length_m: float
    discharge_m3s: float
    manning_area_m2: float
    manning_dq_da_celerity_mps: float
    travel_time_seconds: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "effective_length_m": self.effective_length_m,
            "discharge_m3s": self.discharge_m3s,
            "manning_area_m2": self.manning_area_m2,
            "manning_dq_da_celerity_mps": self.manning_dq_da_celerity_mps,
            "travel_time_seconds": self.travel_time_seconds,
        }


@dataclass(frozen=True)
class ManningPathResponse:
    path_id: str
    start_feature_id: int
    end_feature_id: int
    feature_ids: tuple[int, ...]
    reaches: tuple[ManningReachResponse, ...]
    total_effective_length_m: float
    total_travel_time_seconds: float | None
    effective_celerity_mps: float | None
    nonpropagating_feature_ids: tuple[int, ...]
    state_dependent: bool
    outcome_calibrated: bool
    admitted_as_flood_wave_lag: bool
    diagnostic_only: bool
    provenance_id: str
    evidence_level: str

    @property
    def finite_travel_time_available(self) -> bool:
        return self.total_travel_time_seconds is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": MANNING_PATH_RESPONSE_SCHEMA,
            "path_id": self.path_id,
            "start_feature_id": self.start_feature_id,
            "end_feature_id": self.end_feature_id,
            "feature_ids": list(self.feature_ids),
            "reach_count": len(self.reaches),
            "reaches": [value.as_dict() for value in self.reaches],
            "total_effective_length_m": self.total_effective_length_m,
            "total_travel_time_seconds": self.total_travel_time_seconds,
            "effective_celerity_mps": self.effective_celerity_mps,
            "nonpropagating_feature_ids": list(
                self.nonpropagating_feature_ids
            ),
            "finite_travel_time_available": self.finite_travel_time_available,
            "celerity_quantity": "Manning_kinematic_wave_dQ_dA",
            "state_dependent": self.state_dependent,
            "outcome_calibrated": self.outcome_calibrated,
            "admitted_as_flood_wave_lag": self.admitted_as_flood_wave_lag,
            "diagnostic_only": self.diagnostic_only,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }

    def travel_time_prior(
        self,
        *,
        method: str = MANNING_PATH_RESPONSE_METHOD,
    ) -> TravelTimePrior:
        if self.total_travel_time_seconds is None:
            raise ValueError("manning_path_response_finite_travel_time_required")
        return TravelTimePrior(
            path_id=self.path_id,
            quantity="flood_wave_travel_time",
            method=method,
            lower_seconds=self.total_travel_time_seconds,
            central_seconds=self.total_travel_time_seconds,
            upper_seconds=self.total_travel_time_seconds,
            state_dependent=True,
            outcome_calibrated=self.outcome_calibrated,
            admitted_as_flood_wave_lag=False,
            provenance_id=self.provenance_id,
            evidence_level=self.evidence_level,
        )


class ManningPathResponseDiagnostic:
    """Evaluate state-dependent kinematic celerity along a directed path."""

    def __init__(
        self,
        network: DirectedReachNetwork,
        geometry: ReachHydraulicGeometry,
    ) -> None:
        if geometry.feature_ids != network.feature_ids:
            raise ValueError("manning_path_response_geometry_axis_mismatch")
        self.network = network
        self.geometry = geometry
        self._index = {
            feature: index for index, feature in enumerate(network.feature_ids)
        }
        self._downstream = dict(
            zip(
                network.feature_ids,
                network.downstream_feature_ids,
                strict=True,
            )
        )

    def analyze(
        self,
        reach_discharge_m3s: tuple[float, ...],
        *,
        start_feature_id: int,
        end_feature_id: int | None = None,
        path_id: str,
        provenance_id: str,
        evidence_level: str,
        outcome_calibrated: bool,
    ) -> ManningPathResponse:
        discharge = np.asarray(reach_discharge_m3s, dtype=float)
        if (
            discharge.shape != (len(self.network.feature_ids),)
            or not np.isfinite(discharge).all()
            or (discharge < 0.0).any()
        ):
            raise ValueError("manning_path_response_discharge_axis_invalid")
        if not path_id.strip() or not provenance_id.strip():
            raise ValueError("manning_path_response_identity_required")
        if evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("manning_path_response_evidence_level_invalid")
        if not isinstance(outcome_calibrated, bool):
            raise ValueError("manning_path_response_outcome_flag_invalid")
        target = (
            self.network.outlet_feature_id
            if end_feature_id is None
            else end_feature_id
        )
        path = self._trace_path(start_feature_id, target)

        reaches: list[ManningReachResponse] = []
        nonpropagating: list[int] = []
        for feature in path:
            index = self._index[feature]
            flow = float(discharge[index])
            area = _area_for_discharge(
                flow,
                bottom_width_m=float(self.geometry.bottom_width_m[index]),
                side_slope=float(
                    self.geometry.side_slope_horizontal_per_vertical[index]
                ),
                bed_slope=float(self.geometry.bed_slope[index]),
                manning_n=float(self.geometry.manning_n[index]),
            )
            celerity = float(
                _manning_celerity(
                    np.asarray([area]),
                    np.asarray([self.geometry.bottom_width_m[index]]),
                    np.asarray(
                        [
                            self.geometry.side_slope_horizontal_per_vertical[
                                index
                            ]
                        ]
                    ),
                    np.asarray([self.geometry.bed_slope[index]]),
                    np.asarray([self.geometry.manning_n[index]]),
                )[0]
            )
            length = float(self.network.effective_lengths_m[index])
            if celerity <= 0.0:
                nonpropagating.append(feature)
                travel_time = None
            else:
                travel_time = float(length / celerity)
            reaches.append(
                ManningReachResponse(
                    feature_id=feature,
                    effective_length_m=length,
                    discharge_m3s=flow,
                    manning_area_m2=float(area),
                    manning_dq_da_celerity_mps=celerity,
                    travel_time_seconds=travel_time,
                )
            )

        total_length = float(sum(value.effective_length_m for value in reaches))
        if nonpropagating:
            total_time = None
            effective_celerity = None
        else:
            total_time = float(
                sum(
                    value.travel_time_seconds
                    for value in reaches
                    if value.travel_time_seconds is not None
                )
            )
            effective_celerity = float(total_length / total_time)
        return ManningPathResponse(
            path_id=path_id,
            start_feature_id=start_feature_id,
            end_feature_id=target,
            feature_ids=path,
            reaches=tuple(reaches),
            total_effective_length_m=total_length,
            total_travel_time_seconds=total_time,
            effective_celerity_mps=effective_celerity,
            nonpropagating_feature_ids=tuple(nonpropagating),
            state_dependent=True,
            outcome_calibrated=outcome_calibrated,
            admitted_as_flood_wave_lag=False,
            diagnostic_only=True,
            provenance_id=provenance_id,
            evidence_level=evidence_level,
        )

    def _trace_path(
        self,
        start_feature_id: int,
        end_feature_id: int,
    ) -> tuple[int, ...]:
        if (
            start_feature_id not in self._index
            or end_feature_id not in self._index
        ):
            raise ValueError("manning_path_response_feature_outside_network")
        path: list[int] = []
        current: int | None = start_feature_id
        while current is not None:
            if current in path:
                raise ValueError("manning_path_response_path_cycle")
            path.append(current)
            if current == end_feature_id:
                return tuple(path)
            current = self._downstream[current]
        raise ValueError("manning_path_response_target_not_downstream")
