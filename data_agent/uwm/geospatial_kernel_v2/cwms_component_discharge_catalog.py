"""Typed catalog evidence for Center Hill component discharge sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

SCHEMA = "gwm.geospatial.cwms_component_discharge_catalog.v1"
EXPECTED_COMPONENTS = ("orifice", "sluice", "spillway", "turbine")
EXPECTED_SERIES_IDS = {
    "orifice": ("CETT1-CENTER_HILL.Flow-Orifice.Ave.1Hour.1Hour.man-rev"),
    "sluice": "CETT1-CENTER_HILL.Flow-Sluice.Ave.1Hour.1Hour.man-rev",
    "spillway": ("CETT1-CENTER_HILL.Flow-Spillway.Ave.1Hour.1Hour.man-rev"),
    "turbine": ("CETT1-CENTER_HILL.Flow-Turbine.Ave.1Hour.1Hour.man-rev"),
}
EXPECTED_DISPLAY_ALIASES = {
    "orifice": "Orifice Flow",
    "sluice": "Sluice Gate Flow",
    "spillway": "Spillway Flow",
    "turbine": "Turbine Flow",
}


@dataclass(frozen=True)
class CWMSComponentDischargeSourceIdentity:
    """A catalog identity, not a value series or operational command."""

    component: str
    series_id: str
    display_alias: str
    office: str
    units: str
    interval: str
    interval_offset: int
    time_zone: str
    earliest_time_utc: str
    latest_time_utc: str
    last_update_utc: str
    extent_record_count: int
    unique_extent_count: int
    aliases: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        expected_series = EXPECTED_SERIES_IDS.get(self.component)
        expected_alias = EXPECTED_DISPLAY_ALIASES.get(self.component)
        alias_values = {value for _, value in self.aliases}
        timestamps = (
            self.earliest_time_utc,
            self.latest_time_utc,
            self.last_update_utc,
        )
        parsed = tuple(_parse_timestamp(value) for value in timestamps)
        if (
            self.component not in EXPECTED_COMPONENTS
            or self.series_id != expected_series
            or self.display_alias != expected_alias
            or self.display_alias not in alias_values
            or self.series_id not in alias_values
            or self.office != "LRN"
            or self.units != "cms"
            or self.interval != "1Hour"
            or self.interval_offset != 0
            or self.time_zone != "US/Central"
            or not self.series_id.endswith(".man-rev")
            or self.extent_record_count < 1
            or self.unique_extent_count not in range(1, self.extent_record_count + 1)
            or not self.aliases
            or parsed[0] > parsed[1]
            or parsed[1] > parsed[2]
        ):
            raise ValueError("cwms_component_discharge_identity_invalid")

    @property
    def manually_revised(self) -> bool:
        return self.series_id.endswith(".man-rev")

    def as_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "series_id": self.series_id,
            "display_alias": self.display_alias,
            "office": self.office,
            "units": self.units,
            "interval": self.interval,
            "interval_offset": self.interval_offset,
            "time_zone": self.time_zone,
            "earliest_time_utc": self.earliest_time_utc,
            "latest_time_utc": self.latest_time_utc,
            "last_update_utc": self.last_update_utc,
            "extent_record_count": self.extent_record_count,
            "unique_extent_count": self.unique_extent_count,
            "aliases": [{"name": name, "value": value} for name, value in self.aliases],
            "manually_revised": self.manually_revised,
            "catalog_identity_only": True,
            "values_acquired": False,
            "coverage_continuity_verified": False,
            "gate_command_admitted": False,
            "human_action_admitted": False,
            "causal_intervention_admitted": False,
            "runtime_operator_admitted": False,
        }


@dataclass(frozen=True)
class CWMSComponentDischargeCatalogEvidence:
    """The four component identities selected from one frozen catalog page."""

    catalog_total: int
    page_size: int
    entry_count: int
    next_page_token_present: bool
    components: tuple[CWMSComponentDischargeSourceIdentity, ...]

    def __post_init__(self) -> None:
        if (
            self.catalog_total != 37
            or self.page_size != 500
            or self.entry_count != 37
            or self.next_page_token_present
            or tuple(value.component for value in self.components) != EXPECTED_COMPONENTS
            or tuple(value.series_id for value in self.components)
            != tuple(EXPECTED_SERIES_IDS[key] for key in EXPECTED_COMPONENTS)
        ):
            raise ValueError("cwms_component_discharge_catalog_invalid")

    def require_historical_values(self) -> None:
        raise ValueError("cwms_catalog_identity_does_not_admit_historical_values")

    def require_continuous_coverage(self) -> None:
        raise ValueError("cwms_catalog_extent_does_not_admit_continuous_coverage")

    def require_gate_command(self) -> None:
        raise ValueError("cwms_catalog_identity_does_not_admit_gate_command")

    def require_human_action(self) -> None:
        raise ValueError("cwms_catalog_identity_does_not_admit_human_action")

    def require_causal_intervention(self) -> None:
        raise ValueError("cwms_catalog_identity_does_not_admit_causal_intervention")

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("cwms_catalog_identity_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "role": "public_component_discharge_source_catalog_identity",
            "catalog_summary": {
                "office": "LRN",
                "catalog_type": "TIMESERIES",
                "catalog_total": self.catalog_total,
                "page_size": self.page_size,
                "entry_count": self.entry_count,
                "next_page_token_present": self.next_page_token_present,
                "pagination_followed": False,
                "selected_component_count": len(self.components),
            },
            "components": [value.as_dict() for value in self.components],
            "claim_boundary": {
                "catalog_metadata_only": True,
                "component_discharge_source_identities_admitted": True,
                "historical_values_acquired": False,
                "value_availability_admitted": False,
                "coverage_continuity_admitted": False,
                "gate_commands_admitted": False,
                "human_actions_admitted": False,
                "causal_interventions_admitted": False,
                "runtime_operators_admitted": False,
            },
        }


def compile_cwms_component_discharge_catalog(
    catalog: Mapping[str, object],
) -> CWMSComponentDischargeCatalogEvidence:
    """Select exact hourly manual-revision identities from catalog metadata."""

    entries_value = catalog.get("entries")
    if not isinstance(entries_value, list):
        raise ValueError("cwms_catalog_entries_required")
    total = catalog.get("total")
    page_size = catalog.get("page-size")
    if type(total) is not int or type(page_size) is not int:
        raise ValueError("cwms_catalog_integer_metadata_required")
    if "values" in catalog:
        raise ValueError("cwms_catalog_values_not_permitted")

    entries: list[Mapping[str, object]] = []
    for value in entries_value:
        if not isinstance(value, Mapping):
            raise ValueError("cwms_catalog_entry_object_required")
        if "values" in value:
            raise ValueError("cwms_catalog_entry_values_not_permitted")
        entries.append(value)

    components = tuple(_compile_component(component, entries) for component in EXPECTED_COMPONENTS)
    return CWMSComponentDischargeCatalogEvidence(
        total,
        page_size,
        len(entries),
        bool(catalog.get("next-page")),
        components,
    )


def _compile_component(
    component: str,
    entries: list[Mapping[str, object]],
) -> CWMSComponentDischargeSourceIdentity:
    series_id = EXPECTED_SERIES_IDS[component]
    matches = [value for value in entries if value.get("name") == series_id]
    if len(matches) != 1:
        raise ValueError("cwms_component_discharge_series_not_unique")
    entry = matches[0]
    extents = _compile_extents(entry.get("extents"))
    aliases = _compile_aliases(entry.get("aliases"))
    if entry.get("versioned") is not False:
        raise ValueError("cwms_component_discharge_versioning_invalid")
    return CWMSComponentDischargeSourceIdentity(
        component=component,
        series_id=series_id,
        display_alias=EXPECTED_DISPLAY_ALIASES[component],
        office=_require_string(entry, "office"),
        units=_require_string(entry, "units"),
        interval=_require_string(entry, "interval"),
        interval_offset=_require_integer(entry, "interval-offset"),
        time_zone=_require_string(entry, "time-zone"),
        earliest_time_utc=min(value[0] for value in extents),
        latest_time_utc=max(value[1] for value in extents),
        last_update_utc=max(value[2] for value in extents),
        extent_record_count=len(extents),
        unique_extent_count=len(set(extents)),
        aliases=aliases,
    )


def _compile_extents(
    value: object,
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("cwms_component_discharge_extents_required")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("cwms_component_discharge_extent_object_required")
        extent = (
            _require_string(item, "earliest-time"),
            _require_string(item, "latest-time"),
            _require_string(item, "last-update"),
        )
        parsed = tuple(_parse_timestamp(timestamp) for timestamp in extent)
        if parsed[0] > parsed[1] or parsed[1] > parsed[2]:
            raise ValueError("cwms_component_discharge_extent_invalid")
        result.append(extent)
    return tuple(result)


def _compile_aliases(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("cwms_component_discharge_aliases_required")
    aliases = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("cwms_component_discharge_alias_object_required")
        aliases.append((_require_string(item, "name"), _require_string(item, "value")))
    return tuple(sorted(aliases))


def _require_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"cwms_catalog_{key}_string_required")
    return result


def _require_integer(value: Mapping[str, object], key: str) -> int:
    result = value.get(key)
    if type(result) is not int:
        raise ValueError(f"cwms_catalog_{key}_integer_required")
    return result


def _parse_timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("cwms_catalog_timestamp_invalid") from exc
    if result.tzinfo is None:
        raise ValueError("cwms_catalog_timestamp_timezone_required")
    return result
