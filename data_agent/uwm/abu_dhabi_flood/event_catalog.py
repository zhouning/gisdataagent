"""Auditable event definition for the April 2024 UAE extreme rainfall.

The national rainfall-record statement is useful event context, but it is not
an interchangeable rainfall time series for Abu Dhabi city.  This module keeps
that distinction machine-readable so downstream runners cannot silently use
the Al Ain record value as a city forcing or calibration observation.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

APRIL_2024_EVENT_SCHEMA = "gwm.abu_dhabi_flood.event_catalog.v1"
APRIL_2024_EVENT_ID = "uae-april-2024-extreme-rainfall"


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _forcing_candidate(value: dict[str, Any], source_id: str) -> dict[str, object]:
    required = (
        "source",
        "source_file",
        "file_sha256",
        "time_standard",
        "hourly_interval_count",
        "total_precipitation_mm",
        "maximum_hourly_precipitation_mm",
    )
    missing = [key for key in required if key not in value]
    if missing:
        raise ValueError(f"event_catalog_{source_id}_missing_fields:{','.join(missing)}")
    interval_count = value["hourly_interval_count"]
    if isinstance(interval_count, bool) or interval_count != 72:
        raise ValueError(f"event_catalog_{source_id}_72_hourly_intervals_required")
    for field in ("total_precipitation_mm", "maximum_hourly_precipitation_mm"):
        amount = value[field]
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(float(amount))
            or float(amount) < 0.0
        ):
            raise ValueError(f"event_catalog_{source_id}_{field}_invalid")
    optional = {
        key: value[key]
        for key in ("latitude", "longitude", "source_elevation_m")
        if key in value
    }
    return {key: value[key] for key in required} | optional | {
        "spatial_role": "abu_dhabi_city_point_public_proxy",
        "evidence_class": "reanalysis_candidate",
        "diagnostic_forcing_admitted": True,
        "calibration_observation_admitted": False,
    }


def build_april_2024_event_catalog(
    *,
    openmeteo: dict[str, Any],
    nasa_power_merra2: dict[str, Any],
) -> dict[str, object]:
    """Build the deterministic April 2024 event and forcing ledger."""

    payload: dict[str, object] = {
        "schema": APRIL_2024_EVENT_SCHEMA,
        "event_id": APRIL_2024_EVENT_ID,
        "status": "event_context_corroborated_public_forcings_diagnostic_only",
        "event_window": {
            "calendar_dates": ["2024-04-15", "2024-04-16", "2024-04-17"],
            "model_interval_count": 72,
            "clock_alignment_status": "source_native_not_event_time_aligned",
        },
        "record_claim": {
            "normalized_statement": (
                "The UAE recorded its highest 24-hour rainfall since national "
                "meteorological records began in 1949, reported as the highest "
                "in 75 years."
            ),
            "claim_scope": "united_arab_emirates_national_meteorological_record",
            "record_period_start_year": 1949,
            "reported_record_period_years": 75,
            "customer_context_interpretation": (
                "The event affected Abu Dhabi Emirate and the reported record "
                "station was in Al Ain within the emirate."
            ),
            "explicitly_not_claimed": [
                "abu_dhabi_city_centre_station_75_year_record",
                "uniform_254_8_mm_rainfall_across_abu_dhabi_city_or_emirate",
            ],
            "independent_verification_status": (
                "corroborated_by_public_reporting_pending_official_ncm_record_bundle"
            ),
        },
        "reported_peak_station": {
            "location_name": "Khatm Al Shakla, Al Ain",
            "administrative_scope": "Abu Dhabi Emirate",
            "reported_depth_mm": 254.8,
            "reported_duration": "less_than_24_hours",
            "reported_attribution": "UAE National Centre of Meteorology",
            "used_as_abu_dhabi_city_model_forcing": False,
            "used_as_calibration_observation": False,
        },
        "claim_evidence": [
            {
                "evidence_id": "customer-context-2026-08-19",
                "source_class": "customer_provided_context",
                "statement": (
                    "In April 2024 Abu Dhabi experienced an extreme rainstorm "
                    "described as the largest in 75 years."
                ),
                "model_admission": "context_only",
            },
            {
                "evidence_id": "khaleej-times-2024-04-17-record-report",
                "source_class": "public_reporting_attributing_ncm",
                "title": "UAE witnesses record-breaking rains, highest in 75 years",
                "source_url": (
                    "https://www.khaleejtimes.com/uae/"
                    "uae-witnesses-record-breaking-rains-highest-in-75-years"
                ),
                "archive_url": (
                    "https://web.archive.org/web/20240417035625/"
                    "https://www.khaleejtimes.com/uae/"
                    "uae-witnesses-record-breaking-rains-highest-in-75-years"
                ),
                "publication_date": "2024-04-17",
                "model_admission": "event_context_and_station_record_only",
            },
            {
                "evidence_id": "the-national-2024-04-16-abu-dhabi-impact",
                "source_class": "public_event_reporting",
                "title": (
                    "Dubai flights: All arrivals diverted away from airport amid "
                    "floods and rain in UAE"
                ),
                "source_url": (
                    "https://www.thenationalnews.com/news/uae/2024/04/16/"
                    "abu-dhabi-and-dubai-lashed-by-heavy-rain-thunder-and-lightning/"
                ),
                "archive_url": (
                    "https://web.archive.org/web/20240416175635/"
                    "https://www.thenationalnews.com/news/uae/2024/04/16/"
                    "abu-dhabi-and-dubai-lashed-by-heavy-rain-thunder-and-lightning/"
                ),
                "publication_date": "2024-04-16",
                "model_admission": "event_context_only",
            },
        ],
        "forcing_candidates": {
            "openmeteo": _forcing_candidate(openmeteo, "openmeteo"),
            "nasa_power_merra2": _forcing_candidate(
                nasa_power_merra2,
                "nasa_power_merra2",
            ),
        },
        "forcing_use_boundary": {
            "reported_peak_station_depth_is_a_forcing_time_series": False,
            "public_point_products_may_drive_diagnostic_sensitivity_runs": True,
            "public_point_products_may_calibrate_or_validate_city_flood_depth": False,
            "hourly_pointwise_product_comparison_admitted": False,
            "direct_product_averaging_admitted": False,
        },
        "customer_authoritative_data": {
            "local_gauge_or_radar_event_forcing_available": False,
            "event_tide_and_storm_surge_available": False,
            "event_pump_gate_operations_available": False,
            "timed_inundation_depth_extent_and_recession_available": False,
            "calibration_admitted": False,
            "required_next": [
                "quality_controlled_local_gauge_and_radar_rainfall_with_one_time_standard",
                "coincident_tide_storm_surge_and_outfall_boundary_levels",
                "pump_gate_storage_and_failure_operation_logs",
                "timed_inundation_depth_extent_recession_and_road_impact_observations",
            ],
        },
    }
    payload["catalog_sha256"] = _sha256_json(payload)
    return payload


def verify_april_2024_event_catalog(payload: dict[str, object]) -> None:
    """Verify immutable content and the record/forcing admission boundary."""

    if payload.get("schema") != APRIL_2024_EVENT_SCHEMA:
        raise ValueError("april_2024_event_catalog_schema_invalid")
    claimed = payload.get("catalog_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise ValueError("april_2024_event_catalog_sha256_invalid")
    content = dict(payload)
    content.pop("catalog_sha256")
    if claimed != _sha256_json(content):
        raise ValueError("april_2024_event_catalog_sha256_mismatch")
    record = payload.get("record_claim")
    station = payload.get("reported_peak_station")
    boundary = payload.get("forcing_use_boundary")
    customer = payload.get("customer_authoritative_data")
    if not isinstance(record, dict) or record.get("claim_scope") != (
        "united_arab_emirates_national_meteorological_record"
    ):
        raise ValueError("april_2024_event_catalog_record_scope_invalid")
    if not isinstance(station, dict) or any(
        station.get(key) is not False
        for key in (
            "used_as_abu_dhabi_city_model_forcing",
            "used_as_calibration_observation",
        )
    ):
        raise ValueError("april_2024_event_catalog_station_admission_invalid")
    if not isinstance(boundary, dict) or any(
        boundary.get(key) is not False
        for key in (
            "reported_peak_station_depth_is_a_forcing_time_series",
            "public_point_products_may_calibrate_or_validate_city_flood_depth",
            "hourly_pointwise_product_comparison_admitted",
            "direct_product_averaging_admitted",
        )
    ):
        raise ValueError("april_2024_event_catalog_forcing_boundary_invalid")
    if not isinstance(customer, dict) or customer.get("calibration_admitted") is not False:
        raise ValueError("april_2024_event_catalog_calibration_boundary_invalid")
