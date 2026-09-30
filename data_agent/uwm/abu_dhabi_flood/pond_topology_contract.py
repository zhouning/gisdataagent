"""Fail-closed pond topology and 1-D/2-D volume-ownership contract.

This module is intentionally small.  It is the gate in front of a SWMM/
ANUGA compiler, not a hydraulic solver.  A pond cannot be compiled until its
physical form, canonical water-volume owner, DTM policy and directed
connections are explicit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA = "gwm.abu_dhabi_flood.pond_topology_contract.v1"

POND_FORMS = {"1D_STORAGE", "2D_DEPRESSION", "HYBRID_1D_2D"}
VOLUME_OWNERS = {"ONE_D_STORAGE", "TWO_D_BASIN"}
DTM_POLICIES = {"NONE", "LOCAL_BATHYMETRY", "DESIGN_DTM"}
CONNECTION_KINDS = {"pipe", "force_main", "open_channel", "pump", "weir", "orifice", "overflow", "surface_exchange"}


@dataclass(frozen=True)
class PondConnection:
    connection_id: str
    source_id: str
    target_id: str
    kind: str
    direction: str = "forward"
    capacity_m3s: float | None = None
    activation: str = "always"
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PondTopologyContract:
    pond_id: str
    pond_form: str
    volume_owner: str
    dtm_policy: str
    engineering_admitted: bool = False
    storage_curve_ref: str | None = None
    bathymetry_ref: str | None = None
    exchange_zone_ref: str | None = None
    connections: tuple[PondConnection, ...] = ()
    initial_water_level_m: float | None = None
    overflow_level_m: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def validate_pond_contract(contract: PondTopologyContract) -> dict[str, Any]:
    """Return a reviewable validation receipt; never grants engineering admission."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(contract.pond_id, str) or not contract.pond_id.strip():
        errors.append("pond_id_required")
    if contract.pond_form not in POND_FORMS:
        errors.append("pond_form_invalid")
    if contract.volume_owner not in VOLUME_OWNERS:
        errors.append("volume_owner_invalid")
    if contract.dtm_policy not in DTM_POLICIES:
        errors.append("dtm_policy_invalid")

    if contract.pond_form == "1D_STORAGE":
        if contract.volume_owner != "ONE_D_STORAGE":
            errors.append("1d_storage_requires_one_d_volume_owner")
        if contract.dtm_policy != "NONE":
            errors.append("1d_storage_must_not_modify_dtm")
        if not contract.storage_curve_ref:
            errors.append("1d_storage_curve_required")
        if contract.bathymetry_ref or contract.exchange_zone_ref:
            errors.append("1d_storage_cannot_claim_2d_bathymetry_or_exchange")
    elif contract.pond_form == "2D_DEPRESSION":
        if contract.volume_owner != "TWO_D_BASIN":
            errors.append("2d_depression_requires_two_d_volume_owner")
        if contract.dtm_policy not in {"LOCAL_BATHYMETRY", "DESIGN_DTM"}:
            errors.append("2d_depression_requires_design_bathymetry")
        if not contract.bathymetry_ref:
            errors.append("2d_depression_bathymetry_required")
        if contract.storage_curve_ref:
            errors.append("2d_depression_cannot_have_duplicate_storage_curve")
    elif contract.pond_form == "HYBRID_1D_2D":
        if contract.volume_owner != "TWO_D_BASIN":
            errors.append("hybrid_requires_two_d_basin_volume_owner")
        if contract.dtm_policy not in {"LOCAL_BATHYMETRY", "DESIGN_DTM"}:
            errors.append("hybrid_requires_design_bathymetry")
        if not contract.bathymetry_ref:
            errors.append("hybrid_bathymetry_required")
        if not contract.exchange_zone_ref:
            errors.append("hybrid_exchange_zone_required")
        if contract.storage_curve_ref:
            errors.append("hybrid_cannot_have_duplicate_full_storage_curve")

    seen: set[str] = set()
    for edge in contract.connections:
        if edge.connection_id in seen:
            errors.append("duplicate_connection_id")
        seen.add(edge.connection_id)
        if edge.kind not in CONNECTION_KINDS:
            errors.append(f"connection_kind_invalid:{edge.connection_id}")
        if not edge.source_id or not edge.target_id:
            errors.append(f"connection_endpoints_required:{edge.connection_id}")
        if edge.capacity_m3s is not None and edge.capacity_m3s < 0:
            errors.append(f"connection_capacity_negative:{edge.connection_id}")

    if contract.overflow_level_m is None:
        warnings.append("overflow_level_missing")
    if not any(e.kind == "overflow" for e in contract.connections):
        warnings.append("overflow_connection_missing")
    if contract.engineering_admitted:
        warnings.append("engineering_admission_must_be_granted_by_external_approval")

    return {
        "schema": SCHEMA,
        "pond_id": contract.pond_id,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "engineering_admitted": False,
        "unique_volume_owner": contract.volume_owner,
        "dtm_policy": contract.dtm_policy,
    }


def compile_pond_binding(contract: PondTopologyContract, *, scenario_id: str) -> dict[str, Any]:
    """Compile only validated topology metadata for downstream model adapters."""
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("scenario_id_required")
    receipt = validate_pond_contract(contract)
    if not receipt["valid"]:
        raise ValueError({"pond_topology_contract_invalid": receipt})
    payload = asdict(contract)
    payload["connections"] = [asdict(edge) for edge in contract.connections]
    return {
        "schema": SCHEMA,
        "scenario_id": scenario_id,
        "pond": payload,
        "validation": receipt,
        "compiler_directives": {
            "canonical_volume_owner": contract.volume_owner,
            "modify_dtm": contract.dtm_policy != "NONE",
            "create_duplicate_swmm_storage": False,
            "require_exchange_links": contract.pond_form == "HYBRID_1D_2D",
            "accounting": {
                "storage_state": "Vpond",
                "inflows": ["1D_to_pond", "2D_to_pond", "rain_on_pond"],
                "outflows": ["pond_to_1D", "pond_to_2D", "pump_out", "overflow", "verified_infiltration"],
            },
        },
        "engineering_admitted": False,
    }
