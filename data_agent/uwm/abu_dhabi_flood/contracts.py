"""Typed contracts for the Abu Dhabi urban-flood candidate adapter.

The adapter keeps the spatial graph, hydraulic priors, rainfall forcing and
operational actions separate.  This is deliberately a candidate contract:
real-data admission and predictive validation are independent gates.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

FLOOD_NETWORK_SCHEMA = "gwm.abu_dhabi_flood.network.v1"
RAINFALL_FORCING_SCHEMA = "gwm.abu_dhabi_flood.rainfall_forcing.v1"
FLOOD_ACTION_SCHEMA = "gwm.abu_dhabi_flood.action.v1"
FLOOD_STATE_SCHEMA = "gwm.abu_dhabi_flood.state.v1"

_EVIDENCE_LEVELS = frozenset(("authoritative", "derived", "candidate"))


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name}_must_be_finite")
    return result


def _finite_tuple(values: Iterable[float], name: str) -> tuple[float, ...]:
    result = tuple(_finite(value, name) for value in values)
    if not result:
        raise ValueError(f"{name}_must_be_nonempty")
    return result


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}_required")
    return value.strip()


@dataclass(frozen=True)
class SurfacePatch:
    """A 2-D control volume representing a surface drainage catchment."""

    patch_id: str
    area_m2: float
    runoff_coefficient: float
    infiltration_capacity_mm_per_h: float
    ground_elevation_m: float
    provenance_id: str
    evidence_level: str = "candidate"

    def __post_init__(self) -> None:
        _required_text(self.patch_id, "patch_id")
        area = _finite(self.area_m2, "patch_area")
        if area <= 0.0:
            raise ValueError("patch_area_must_be_positive")
        runoff = _finite(self.runoff_coefficient, "runoff_coefficient")
        if not 0.0 <= runoff <= 1.0:
            raise ValueError("runoff_coefficient_must_be_between_zero_and_one")
        infiltration = _finite(
            self.infiltration_capacity_mm_per_h,
            "infiltration_capacity",
        )
        if infiltration < 0.0:
            raise ValueError("infiltration_capacity_must_be_nonnegative")
        _finite(self.ground_elevation_m, "ground_elevation")
        _required_text(self.provenance_id, "patch_provenance_id")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_patch_evidence_level")
        object.__setattr__(self, "patch_id", self.patch_id.strip())
        object.__setattr__(self, "provenance_id", self.provenance_id.strip())
        object.__setattr__(self, "area_m2", area)
        object.__setattr__(self, "runoff_coefficient", runoff)
        object.__setattr__(self, "infiltration_capacity_mm_per_h", infiltration)
        object.__setattr__(self, "ground_elevation_m", float(self.ground_elevation_m))

    def as_dict(self) -> dict[str, object]:
        return {
            "patch_id": self.patch_id,
            "area_m2": self.area_m2,
            "runoff_coefficient": self.runoff_coefficient,
            "infiltration_capacity_mm_per_h": self.infiltration_capacity_mm_per_h,
            "ground_elevation_m": self.ground_elevation_m,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


@dataclass(frozen=True)
class DrainageLink:
    """A directed drainage link, optionally ending at an external outfall."""

    link_id: str
    source_patch_id: str
    target_patch_id: str | None
    capacity_m3s: float
    travel_time_seconds: float
    provenance_id: str
    evidence_level: str = "candidate"
    admitted: bool = False

    def __post_init__(self) -> None:
        _required_text(self.link_id, "link_id")
        _required_text(self.source_patch_id, "link_source_patch_id")
        if self.target_patch_id is not None:
            _required_text(self.target_patch_id, "link_target_patch_id")
        capacity = _finite(self.capacity_m3s, "link_capacity")
        travel = _finite(self.travel_time_seconds, "link_travel_time")
        if capacity < 0.0:
            raise ValueError("link_capacity_must_be_nonnegative")
        if travel <= 0.0:
            raise ValueError("link_travel_time_must_be_positive")
        _required_text(self.provenance_id, "link_provenance_id")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_link_evidence_level")
        if not isinstance(self.admitted, bool):
            raise ValueError("link_admitted_must_be_boolean")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_link_cannot_be_admitted")
        object.__setattr__(self, "link_id", self.link_id.strip())
        object.__setattr__(self, "source_patch_id", self.source_patch_id.strip())
        if self.target_patch_id is not None:
            object.__setattr__(self, "target_patch_id", self.target_patch_id.strip())
        object.__setattr__(self, "capacity_m3s", capacity)
        object.__setattr__(self, "travel_time_seconds", travel)
        object.__setattr__(self, "provenance_id", self.provenance_id.strip())

    def as_dict(self) -> dict[str, object]:
        return {
            "link_id": self.link_id,
            "source_patch_id": self.source_patch_id,
            "target_patch_id": self.target_patch_id,
            "capacity_m3s": self.capacity_m3s,
            "travel_time_seconds": self.travel_time_seconds,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
        }


@dataclass(frozen=True)
class FloodNetwork:
    """Compiled surface-patch and drainage-link graph."""

    network_id: str
    patches: tuple[SurfacePatch, ...]
    links: tuple[DrainageLink, ...]
    crs: str
    provenance_id: str
    evidence_level: str = "candidate"
    admitted: bool = False

    def __post_init__(self) -> None:
        _required_text(self.network_id, "network_id")
        _required_text(self.crs, "network_crs")
        _required_text(self.provenance_id, "network_provenance_id")
        if not self.patches:
            raise ValueError("network_requires_patches")
        if len({patch.patch_id for patch in self.patches}) != len(self.patches):
            raise ValueError("network_patch_ids_must_be_unique")
        if len({link.link_id for link in self.links}) != len(self.links):
            raise ValueError("network_link_ids_must_be_unique")
        patch_ids = {patch.patch_id for patch in self.patches}
        for link in self.links:
            if link.source_patch_id not in patch_ids:
                raise ValueError("link_source_patch_missing_from_network")
            if link.target_patch_id is not None and link.target_patch_id not in patch_ids:
                raise ValueError("link_target_patch_missing_from_network")
            if link.target_patch_id == link.source_patch_id:
                raise ValueError("network_self_loop_not_supported")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_network_evidence_level")
        if not isinstance(self.admitted, bool):
            raise ValueError("network_admitted_must_be_boolean")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_network_cannot_be_admitted")
        object.__setattr__(self, "network_id", self.network_id.strip())
        object.__setattr__(self, "crs", self.crs.strip())
        object.__setattr__(self, "provenance_id", self.provenance_id.strip())

    @property
    def patch_ids(self) -> tuple[str, ...]:
        return tuple(patch.patch_id for patch in self.patches)

    @property
    def link_ids(self) -> tuple[str, ...]:
        return tuple(link.link_id for link in self.links)

    @property
    def patch_index(self) -> dict[str, int]:
        return {patch.patch_id: index for index, patch in enumerate(self.patches)}

    @property
    def link_index(self) -> dict[str, int]:
        return {link.link_id: index for index, link in enumerate(self.links)}

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FLOOD_NETWORK_SCHEMA,
            "network_id": self.network_id,
            "patches": [patch.as_dict() for patch in self.patches],
            "links": [link.as_dict() for link in self.links],
            "crs": self.crs,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
        }


@dataclass(frozen=True)
class RainfallForcing:
    """A spatially supported rainfall interval in millimetres per hour."""

    intensity_mm_per_h: tuple[float, ...]
    duration_seconds: float
    timestamp_s: float
    provenance_id: str
    evidence_level: str = "candidate"
    is_forecast: bool = True

    def __post_init__(self) -> None:
        intensities = _finite_tuple(self.intensity_mm_per_h, "rainfall_intensity")
        if any(value < 0.0 for value in intensities):
            raise ValueError("rainfall_intensity_must_be_nonnegative")
        duration = _finite(self.duration_seconds, "rainfall_duration")
        timestamp = _finite(self.timestamp_s, "rainfall_timestamp")
        if duration <= 0.0:
            raise ValueError("rainfall_duration_must_be_positive")
        _required_text(self.provenance_id, "rainfall_provenance_id")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_rainfall_evidence_level")
        if not isinstance(self.is_forecast, bool):
            raise ValueError("rainfall_is_forecast_must_be_boolean")
        object.__setattr__(self, "intensity_mm_per_h", intensities)
        object.__setattr__(self, "duration_seconds", duration)
        object.__setattr__(self, "timestamp_s", timestamp)
        object.__setattr__(self, "provenance_id", self.provenance_id.strip())

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": RAINFALL_FORCING_SCHEMA,
            "intensity_mm_per_h": list(self.intensity_mm_per_h),
            "duration_seconds": self.duration_seconds,
            "timestamp_s": self.timestamp_s,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "is_forecast": self.is_forecast,
        }


@dataclass(frozen=True)
class FloodAction:
    """Operational action applied during one transition."""

    action_id: str
    drainage_capacity_multipliers: tuple[float, ...]
    pump_capacity_m3s: tuple[float, ...]
    provenance_id: str
    evidence_level: str = "candidate"

    def __post_init__(self) -> None:
        multipliers = _finite_tuple(
            self.drainage_capacity_multipliers,
            "drainage_capacity_multipliers",
        )
        pumps = _finite_tuple(self.pump_capacity_m3s, "pump_capacity")
        if any(value < 0.0 for value in multipliers):
            raise ValueError("drainage_capacity_multipliers_must_be_nonnegative")
        if any(value < 0.0 for value in pumps):
            raise ValueError("pump_capacity_must_be_nonnegative")
        _required_text(self.action_id, "action_id")
        _required_text(self.provenance_id, "action_provenance_id")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_action_evidence_level")
        object.__setattr__(self, "action_id", self.action_id.strip())
        object.__setattr__(self, "provenance_id", self.provenance_id.strip())
        object.__setattr__(self, "drainage_capacity_multipliers", multipliers)
        object.__setattr__(self, "pump_capacity_m3s", pumps)

    @classmethod
    def noop(
        cls,
        *,
        link_count: int,
        patch_count: int,
        provenance_id: str = "action:noop",
    ) -> FloodAction:
        if link_count <= 0 and patch_count <= 0:
            raise ValueError("noop_action_requires_network_dimensions")
        return cls(
            action_id="noop",
            drainage_capacity_multipliers=(1.0,) * max(1, link_count),
            pump_capacity_m3s=(0.0,) * max(1, patch_count),
            provenance_id=provenance_id,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FLOOD_ACTION_SCHEMA,
            "action_id": self.action_id,
            "drainage_capacity_multipliers": list(
                self.drainage_capacity_multipliers
            ),
            "pump_capacity_m3s": list(self.pump_capacity_m3s),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


@dataclass(frozen=True)
class FloodState:
    """Conservative extensive state: surface water plus in-link water."""

    surface_volume_m3: tuple[float, ...]
    link_storage_m3: tuple[float, ...]
    timestamp_s: float
    provenance_id: str

    def __post_init__(self) -> None:
        surface = _finite_tuple(self.surface_volume_m3, "surface_volume")
        links = tuple(_finite(value, "link_storage") for value in self.link_storage_m3)
        if any(value < 0.0 for value in surface) or any(value < 0.0 for value in links):
            raise ValueError("flood_state_volumes_must_be_nonnegative")
        _finite(self.timestamp_s, "flood_state_timestamp")
        _required_text(self.provenance_id, "flood_state_provenance_id")
        object.__setattr__(self, "surface_volume_m3", surface)
        object.__setattr__(self, "link_storage_m3", links)
        object.__setattr__(self, "provenance_id", self.provenance_id.strip())

    @property
    def total_storage_m3(self) -> float:
        return float(sum(self.surface_volume_m3) + sum(self.link_storage_m3))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FLOOD_STATE_SCHEMA,
            "surface_volume_m3": list(self.surface_volume_m3),
            "link_storage_m3": list(self.link_storage_m3),
            "timestamp_s": self.timestamp_s,
            "provenance_id": self.provenance_id,
            "total_storage_m3": self.total_storage_m3,
        }
