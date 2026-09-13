"""Public data acquisition planning for UWM data foundation."""

from __future__ import annotations

from typing import Any


UWM_PUBLIC_SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "era5_meteorology_chongqing": {
        "manifest_dataset_id": "era5_meteorology_chongqing",
        "role": "meteorology",
        "official_url": "https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_HOURLY",
        "gee_asset": "ECMWF/ERA5/HOURLY",
        "status": "downloadable_via_gee_authenticated",
        "credential_or_setup": "Use local Google Earth Engine authentication; no Copernicus CDS token is required for this proxy path.",
        "reason_not_downloaded": "Download/sampling must run against the locally authenticated GEE account.",
    },
    "cams_air_pollution_proxy": {
        "manifest_dataset_id": "cams_air_pollution_proxy",
        "role": "air_pollution_exposure",
        "official_url": "https://developers.google.com/earth-engine/datasets/catalog/ECMWF_CAMS_NRT",
        "gee_asset": "ECMWF/CAMS/NRT",
        "status": "downloadable_via_gee_authenticated",
        "credential_or_setup": "Use local Google Earth Engine authentication; CAMS/NRT is sampled through GEE for the UWM proxy.",
        "reason_not_downloaded": "Download/sampling must run against the locally authenticated GEE account.",
    },
    "openaq_air_quality_proxy": {
        "manifest_dataset_id": "openaq_air_quality_proxy",
        "role": "air_pollution_exposure",
        "official_url": "https://openaq.org/",
        "status": "downloadable_with_runtime_secret",
        "credential_or_setup": "OpenAQ v3 API requires an X-API-Key supplied at runtime; the key must not be stored in repository artifacts.",
        "reason_not_downloaded": "Provide X-API-Key at runtime before scripted download; do not persist the secret.",
    },
    "openmeteo_weather_current_proxy": {
        "manifest_dataset_id": "openmeteo_weather_current_proxy",
        "role": "meteorology",
        "official_url": "https://api.open-meteo.com/v1/forecast",
        "status": "downloadable_public",
        "credential_or_setup": "Keyless public API; suitable for live current weather proxy and smoke validation.",
        "reason_not_downloaded": "Live API is reachable, but current data must be archived locally before holdout use.",
        "current_fields": [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "surface_pressure",
            "wind_speed_10m",
        ],
    },
    "openmeteo_weather_historical_point_proxy": {
        "manifest_dataset_id": "openmeteo_weather_historical_point_proxy",
        "role": "meteorology",
        "official_url": "https://archive-api.open-meteo.com/v1/archive",
        "status": "downloadable_public",
        "credential_or_setup": "Keyless public archive API; suitable as a reproducible point-history proxy.",
        "reason_not_downloaded": "",
        "history_fields": {
            "daily": [
                "temperature_2m_mean",
                "precipitation_sum",
                "wind_speed_10m_max",
            ],
            "hourly": [
                "relative_humidity_2m",
                "surface_pressure",
            ],
        },
    },
    "openmeteo_air_quality_current_proxy": {
        "manifest_dataset_id": "openmeteo_air_quality_current_proxy",
        "role": "air_pollution_exposure",
        "official_url": "https://air-quality-api.open-meteo.com/v1/air-quality",
        "status": "downloadable_public",
        "credential_or_setup": "Keyless public API; suitable for live air-quality proxy and smoke validation.",
        "reason_not_downloaded": "Live API is reachable, but modeled/current data cannot replace station-calibrated holdout.",
        "current_fields": [
            "pm10",
            "pm2_5",
            "carbon_monoxide",
            "nitrogen_dioxide",
            "sulphur_dioxide",
            "ozone",
        ],
    },
    "openmeteo_air_quality_historical_point_proxy": {
        "manifest_dataset_id": "openmeteo_air_quality_historical_point_proxy",
        "role": "air_pollution_exposure",
        "official_url": "https://air-quality-api.open-meteo.com/v1/air-quality",
        "status": "downloadable_public",
        "credential_or_setup": "Keyless public API; suitable as a reproducible modeled point-history proxy.",
        "reason_not_downloaded": "",
        "history_fields": {
            "hourly": [
                "pm10",
                "pm2_5",
                "carbon_monoxide",
                "nitrogen_dioxide",
                "sulphur_dioxide",
                "ozone",
            ],
        },
    },
    "worldpop_population_chongqing_proxy": {
        "manifest_dataset_id": "worldpop_population_chongqing_proxy",
        "role": "population_vulnerability",
        "official_url": "https://www.worldpop.org/",
        "status": "downloadable_public",
        "credential_or_setup": "Public data portal; choose age/sex/vulnerability layers and years.",
        "reason_not_downloaded": "",
    },
    "ghsl_population_built_chongqing_proxy": {
        "manifest_dataset_id": "ghsl_population_built_chongqing_proxy",
        "role": "population_vulnerability",
        "official_url": "https://ghsl.jrc.ec.europa.eu/",
        "status": "downloadable_public",
        "credential_or_setup": "Public JRC GHSL download; select GHS-POP/GHS-BUILT products and years.",
        "reason_not_downloaded": "",
    },
    "osm_services_chongqing_public_proxy": {
        "manifest_dataset_id": "osm_services_chongqing_public_proxy",
        "role": "service_accessibility",
        "official_url": "https://www.openstreetmap.org/",
        "status": "downloadable_public",
        "credential_or_setup": "Use OSM extracts or Overpass; verify ODbL attribution and feature completeness.",
        "reason_not_downloaded": "",
    },
}

_ROLE_SOURCE_PREFERENCE = {
    "meteorology": [
        "era5_meteorology_chongqing",
        "openmeteo_weather_current_proxy",
        "openmeteo_weather_historical_point_proxy",
    ],
    "air_pollution_exposure": [
        "cams_air_pollution_proxy",
        "openaq_air_quality_proxy",
        "openmeteo_air_quality_current_proxy",
        "openmeteo_air_quality_historical_point_proxy",
    ],
    "population_vulnerability": [
        "worldpop_population_chongqing_proxy",
        "ghsl_population_built_chongqing_proxy",
    ],
    "service_accessibility": ["osm_services_chongqing_public_proxy"],
}


def build_uwm_public_data_acquisition_plan(
    *,
    requested_roles: list[str],
    source_registry: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a source-level acquisition plan without pretending data is downloaded."""

    source_registry = source_registry or UWM_PUBLIC_SOURCE_REGISTRY
    role_plan = {}
    selected_sources: dict[str, dict[str, Any]] = {}
    for role in requested_roles:
        candidates = _ROLE_SOURCE_PREFERENCE.get(role, [])
        for source_id in candidates:
            if source_id in source_registry:
                selected_sources[source_id] = source_registry[source_id]
        role_plan[role] = _role_plan(role, candidates, source_registry)
    return {
        "schema": "uwm.public_data_acquisition_plan.v1",
        "requested_roles": requested_roles,
        "roles": role_plan,
        "sources": selected_sources,
        "no_silent_substitution": True,
    }


def summarize_acquisition_blockers(plan: dict[str, Any]) -> dict[str, Any]:
    """Summarize what can be downloaded and what needs user-provided access."""

    sources = plan.get("sources") or {}
    requires_credentials = [
        source_id
        for source_id, source in sources.items()
        if source.get("status") in {"requires_credentials", "requires_credentials_or_public_archive"}
    ]
    requires_runtime_secrets = [
        source_id
        for source_id, source in sources.items()
        if source.get("status") == "downloadable_with_runtime_secret"
    ]
    can_attempt_public = [
        source_id
        for source_id, source in sources.items()
        if _is_download_attemptable(source.get("status"))
    ]
    requires_source_decision = [
        role
        for role, role_info in (plan.get("roles") or {}).items()
        if role_info.get("status") == "requires_source_choice"
    ]
    return {
        "schema": "uwm.public_data_acquisition_blockers.v1",
        "requires_user_credentials": requires_credentials,
        "requires_runtime_secrets": requires_runtime_secrets,
        "requires_source_decision": requires_source_decision,
        "can_attempt_public_download": can_attempt_public,
        "no_silent_substitution": bool(plan.get("no_silent_substitution")),
        "messages": _blocker_messages(
            requires_credentials,
            requires_runtime_secrets,
            requires_source_decision,
            can_attempt_public,
            sources,
        ),
    }


def _role_plan(
    role: str,
    candidates: list[str],
    source_registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    available_candidates = [source_id for source_id in candidates if source_id in source_registry]
    if not available_candidates:
        return {
            "role": role,
            "status": "no_registered_source",
            "preferred_source": None,
            "candidate_sources": [],
        }
    statuses = {source_registry[source_id]["status"] for source_id in available_candidates}
    if role == "air_pollution_exposure" and len(available_candidates) > 1:
        status = "requires_source_choice"
    elif any(_is_download_attemptable(status) for status in statuses):
        status = "downloadable_public"
    elif "requires_credentials" in statuses:
        status = "requires_credentials"
    else:
        status = "manual_review_required"
    return {
        "role": role,
        "status": status,
        "preferred_source": available_candidates[0],
        "candidate_sources": available_candidates,
    }


def _blocker_messages(
    requires_credentials: list[str],
    requires_runtime_secrets: list[str],
    requires_source_decision: list[str],
    can_attempt_public: list[str],
    sources: dict[str, dict[str, Any]],
) -> list[str]:
    messages = []
    for source_id in requires_credentials:
        source = sources[source_id]
        messages.append(f"{source_id}: {source.get('reason_not_downloaded')}")
    for source_id in requires_runtime_secrets:
        source = sources[source_id]
        messages.append(f"{source_id}: {source.get('credential_or_setup')}")
    for role in requires_source_decision:
        messages.append(f"{role}: choose and validate a proxy source before using it for claims")
    for source_id in can_attempt_public:
        source = sources[source_id]
        if source.get("reason_not_downloaded"):
            messages.append(f"{source_id}: {source.get('reason_not_downloaded')}")
    return messages


def _is_download_attemptable(status: Any) -> bool:
    return str(status) in {
        "downloadable_public",
        "downloadable_via_gee_authenticated",
        "downloadable_with_runtime_secret",
    }
