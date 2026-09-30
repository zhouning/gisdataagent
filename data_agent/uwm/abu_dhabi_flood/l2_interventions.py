"""L2 intervention registry and fail-closed 1D/2D model binding contract.

The registry separates an intervention's operational level (L2) from its
hydraulic representation.  It creates a reviewable model-binding manifest; it
does not admit an intervention to a customer model until the required
geometry, hydraulic parameters, connectivity, state and evidence are present.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from typing import Any, Iterable


SCHEMA = "gwm.abu_dhabi_flood.l2_interventions.v1"
LEVEL = "L2"

ASSET_TYPES = (
    "pond", "ditch", "surface_pipeline", "spillway", "geocell",
    "bund", "barrier", "stationed_pump",
)

MODEL_REPRESENTATIONS = {
    "pond": ("1d_storage_node", "2d_storage_area", "1d_2d_storage_exchange"),
    "ditch": ("1d_open_channel", "2d_surface_flow", "1d_2d_channel_exchange"),
    "surface_pipeline": ("1d_conduit", "1d_pressure_conduit", "1d_2d_discharge_exchange"),
    "spillway": ("1d_weir", "2d_line_structure", "1d_2d_overflow_exchange"),
    "geocell": ("2d_infiltration_storage", "2d_roughness_zone", "2d_porosity_storage"),
    "bund": ("2d_line_structure", "2d_terrain_breakline", "1d_2d_embankment_exchange"),
    "barrier": ("2d_line_structure", "2d_terrain_breakline", "1d_2d_embankment_exchange"),
    "stationed_pump": ("1d_pump", "1d_pump_to_2d_source", "1d_pump_to_1d_outfall"),
}

# A required item is satisfied when any alias in the tuple is supplied by the
# source schema or by a normalized intervention record.
REQUIRED_PARAMETERS = {
    "pond": {
        "geometry", "vertical_reference", "rim_or_crest_elevation",
        "stage_area_storage_curve", "inlet_connection", "outlet_or_overflow",
        "initial_water_level", "maintenance_state",
    },
    "ditch": {
        "geometry", "vertical_reference", "longitudinal_profile",
        "cross_sections", "roughness", "inlet_connection", "outlet_connection",
        "maintenance_state",
    },
    "surface_pipeline": {
        "geometry", "vertical_reference", "diameter_or_section",
        "invert_profile", "roughness_or_material", "upstream_connection",
        "downstream_connection", "losses_or_fittings", "maintenance_state",
    },
    "spillway": {
        "geometry", "vertical_reference", "crest_elevation", "width_or_section",
        "hydraulic_coefficient", "tailwater_or_receiving_node", "maintenance_state",
    },
    "geocell": {
        "geometry", "vertical_reference", "thickness_or_storage_depth",
        "porosity_or_storage_curve", "infiltration_or_permeability", "roughness",
        "maintenance_state",
    },
    "bund": {
        "geometry", "vertical_reference", "crest_elevation", "side_slopes",
        "overtopping_rule", "breach_or_failure_state", "maintenance_state",
    },
    "barrier": {
        "geometry", "vertical_reference", "crest_elevation", "deployment_state",
        "overtopping_rule", "breach_or_failure_state", "maintenance_state",
    },
    "stationed_pump": {
        "geometry", "vertical_reference", "pump_qh_curve", "suction_connection",
        "discharge_connection", "control_rule", "power_or_fuel_state",
        "tailwater_or_receiving_node", "maintenance_state",
    },
}

DEFAULT_TARGET = {
    "pond": "2d_storage_area",
    "ditch": "1d_open_channel",
    "surface_pipeline": "1d_conduit",
    "spillway": "1d_weir",
    "geocell": "2d_infiltration_storage",
    "bund": "2d_line_structure",
    "barrier": "2d_line_structure",
    "stationed_pump": "1d_pump",
}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"l2_{name}_invalid")
    return float(value)


@dataclass(frozen=True)
class L2Intervention:
    asset_id: str
    asset_type: str
    geometry: dict[str, Any] | None = None
    source_ref: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    model_representation: str | None = None
    operating_state: str = "planned"
    classification_status: str = "pending"
    evidence_reference: str | None = None
    approval_reference: str | None = None

    def __post_init__(self):
        if not isinstance(self.asset_id, str) or not self.asset_id.strip():
            raise ValueError("l2_asset_id_required")
        if self.asset_type not in ASSET_TYPES:
            raise ValueError("l2_asset_type_invalid")
        if self.model_representation is not None and self.model_representation not in MODEL_REPRESENTATIONS[self.asset_type]:
            raise ValueError("l2_model_representation_invalid")
        if self.operating_state not in {"planned", "ready", "operating", "derated", "failed", "unknown"}:
            raise ValueError("l2_operating_state_invalid")
        if self.classification_status not in {"pending", "proposed", "confirmed"}:
            raise ValueError("l2_classification_status_invalid")
        if not isinstance(self.parameters, dict):
            raise ValueError("l2_parameters_invalid")


def normalize_parameter_names(parameters: dict[str, Any]) -> set[str]:
    """Return normalized names accepted by the contract.

    Source-specific aliases are resolved by the ingestion layer; this function
    intentionally only handles common spelling/case variations.
    """
    aliases = {
        "geom": "geometry", "shape": "geometry", "vertical_datum": "vertical_reference",
        "vertical_ref": "vertical_reference", "crest_level": "crest_elevation",
        "crest": "crest_elevation", "rim_level": "rim_or_crest_elevation",
        "storage_curve": "stage_area_storage_curve", "stage_curve": "stage_area_storage_curve",
        "inlet": "inlet_connection", "outlet": "outlet_or_overflow",
        "overflow": "outlet_or_overflow", "upstream": "upstream_connection",
        "downstream": "downstream_connection", "section": "cross_sections",
        "cross_section": "cross_sections", "manning_n": "roughness",
        "roughness_n": "roughness", "diameter": "diameter_or_section",
        "invert": "invert_profile", "qh_curve": "pump_qh_curve", "pump_curve": "pump_qh_curve",
        "suction": "suction_connection", "discharge": "discharge_connection",
        "controls": "control_rule", "control": "control_rule", "tailwater": "tailwater_or_receiving_node",
        "receiving_node": "tailwater_or_receiving_node", "power_state": "power_or_fuel_state",
        "deployment": "deployment_state", "failure_state": "breach_or_failure_state",
        "side_slope": "side_slopes", "storage_depth": "thickness_or_storage_depth",
        "porosity": "porosity_or_storage_curve", "permeability": "infiltration_or_permeability",
        "initial_level": "initial_water_level", "initial_water_depth": "initial_water_level",
        "maintenance": "maintenance_state",
    }
    result: set[str] = set()
    for key in parameters:
        normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
        result.add(aliases.get(normalized, normalized))
    if parameters.get("geometry") is not None or parameters.get("geom") is not None:
        result.add("geometry")
    return result


def validate_intervention(asset: L2Intervention) -> dict[str, Any]:
    """Validate data completeness without granting engineering admission."""
    supplied = normalize_parameter_names(asset.parameters)
    if asset.geometry is not None:
        supplied.add("geometry")
    required = REQUIRED_PARAMETERS[asset.asset_type]
    missing = sorted(required - supplied)
    warnings: list[str] = []
    if asset.classification_status != "confirmed":
        warnings.append("classification_not_confirmed")
    if asset.approval_reference is None:
        warnings.append("approval_reference_missing")
    if asset.evidence_reference is None:
        warnings.append("evidence_reference_missing")
    if asset.operating_state == "unknown":
        warnings.append("operating_state_unknown")
    representation = asset.model_representation or DEFAULT_TARGET[asset.asset_type]
    return {
        "asset_id": asset.asset_id,
        "asset_type": asset.asset_type,
        "measure_level": LEVEL,
        "model_representation": representation,
        "required_parameters": sorted(required),
        "supplied_parameters": sorted(supplied),
        "missing_parameters": missing,
        "warnings": warnings,
        "hydraulic_model_ready": not missing,
        "engineering_admitted": False,
    }


def compile_l2_model_bindings(assets: Iterable[L2Intervention], *, scenario_id: str = "S1_L1_L2") -> dict[str, Any]:
    """Compile normalized L2 records into reviewable 1D/2D binding metadata."""
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("l2_scenario_id_required")
    records = list(assets)
    seen: set[str] = set()
    bindings = []
    for asset in records:
        if asset.asset_id in seen:
            raise ValueError("l2_duplicate_asset_id")
        seen.add(asset.asset_id)
        check = validate_intervention(asset)
        bindings.append({
            "asset": asdict(asset),
            "validation": check,
            "binding": {
                "scenario_id": scenario_id,
                "measure_level": LEVEL,
                "model_representation": check["model_representation"],
                "unique_storage_owner_required": asset.asset_type == "pond",
                "exchange_required": asset.asset_type in {"pond", "ditch", "spillway", "bund", "barrier", "stationed_pump"},
                "activation": {"operating_state": asset.operating_state, "pre_event_ready_required": True},
            },
        })
    ready = sum(b["validation"]["hydraulic_model_ready"] for b in bindings)
    return {
        "schema": SCHEMA,
        "scenario_id": scenario_id,
        "measure_level": LEVEL,
        "bindings": bindings,
        "summary": {"asset_count": len(bindings), "hydraulic_model_ready_count": ready,
                     "blocked_count": len(bindings) - ready},
        "engineering_admitted": False,
        "customer_catchment_simulation_executed": False,
    }


def load_json_assets(path) -> list[L2Intervention]:
    """Load a small normalized JSON list for CLI and reproducible tests."""
    payload = json.loads(path.read_text())
    if isinstance(payload, dict):
        payload = payload.get("assets")
    if not isinstance(payload, list):
        raise ValueError("l2_asset_json_list_required")
    return [L2Intervention(**row) for row in payload]
