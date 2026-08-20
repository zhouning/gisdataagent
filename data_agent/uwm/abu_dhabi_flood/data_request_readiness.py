"""Fail-closed readiness audit for the Abu Dhabi stormwater request register.

The register describes customer or authority-owned deliveries.  Public files
are useful proxies, but their presence must never be interpreted as receipt of
the authoritative artifact or as model admission.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DATA_REQUEST_READINESS_SCHEMA = (
    "gwm.abu_dhabi_stormwater.data_request_readiness.v1"
)

_PUBLIC_PROXY_MAP: dict[str, tuple[str, ...]] = {
    "engineering-surface-vertical-datum": (
        "online/terrain/Copernicus_DSM_COG_10_N24_00_E054_00_DEM.tif",
        "online/terrain/abu_dhabi_copernicus_30m_epsg32640.tif",
        "online/smartmakani/contour_2017_mapserver.json",
    ),
    "drainage-network-topology-units": (
        "derived/smartmakani/abu_dhabi_stormwater_network.gpkg",
        "derived/makani_registered/registered_stormwater_pipelines.parquet",
        "derived/makani_registered/registered_stormwater_nodes.parquet",
        "derived/makani_registered/registered_network_candidate_audit.json",
    ),
    "event-rainfall-forcing": (
        "online/weather/chirps_daily_05deg_2024_04/chirps-v2.0.2024.04.15.tif.gz",
        "online/weather/chirps_daily_05deg_2024_04/chirps-v2.0.2024.04.16.tif.gz",
        "online/weather/chirps_daily_05deg_2024_04/chirps-v2.0.2024.04.17.tif.gz",
        "derived/public_supporting_context/chirps_abu_dhabi_point_summary.json",
        "online/remote_catalogs/gpm_imerg_v07_april_2024_event_cmr.json",
    ),
    "coastal-boundary-time-series": (),
    "pump-gate-operation-history": (),
    "timed-inundation-observations": (
        "online/smartmakani/rain_incidents_layer_30.json",
        "online/smartmakani/rain_incidents_layer_30_date_stats.json",
        "online/remote_catalogs/sentinel1_grd_april_2024_bbox_search.json",
    ),
    "common-geography-overlay-rule": (
        "online/supporting_context/are_admin_boundaries.geojson.zip",
    ),
    "liveability-exposure-semantics": (
        "derived/liveability_pg_audit/liveability_source_audit.json",
        "derived/liveability_pg_audit/dictionary_to_database_mapping.json",
    ),
    "landcover-infiltration-parameters": (),
    "roads-curbs-obstacles-buildings": (
        "online/supporting_context/hotosm_are_waterways_osm_gpkg.zip",
        "online/smartmakani/contour_2017_mapserver.json",
    ),
    "historical-events-design-storms": (
        "derived/events/april_2024_event_catalog.json",
        "online/weather/chirps_daily_05deg_2024_04/chirps-v2.0.2024.04.15.tif.gz",
        "online/weather/chirps_daily_05deg_2024_04/chirps-v2.0.2024.04.16.tif.gz",
        "online/weather/chirps_daily_05deg_2024_04/chirps-v2.0.2024.04.17.tif.gz",
    ),
    "maintenance-blockage-asset-condition": (),
}

_PROXY_ADMISSION = {
    "diagnostic_sensitivity_only",
    "context_and_spatial_crosswalk_only",
    "spatial_clip_and_impact_aggregation_only",
    "metadata_only",
    "event_observation_candidate_not_downloaded",
    "no_admission_effect",
}

_REQUIRED_DELIVERY_METADATA = (
    "source_owner",
    "version_or_snapshot",
    "acquisition_or_valid_time",
    "crs_or_vertical_datum",
    "units",
    "quality_flags",
    "license_or_reuse_authority",
    "sha256",
)


def _metadata_completeness(artifact: dict[str, Any]) -> dict[str, Any]:
    """Check the register's metadata contract without inspecting data rows."""

    aliases = {
        "source_owner": ("source_owner", "source"),
        "version_or_snapshot": ("version", "snapshot", "snapshot_id"),
        "acquisition_or_valid_time": (
            "acquisition_time",
            "valid_time",
            "time_range",
            "datetime",
        ),
        "crs_or_vertical_datum": ("crs", "target_crs", "vertical_datum"),
        "units": ("units",),
        "quality_flags": ("quality_flags",),
        "license_or_reuse_authority": ("license_or_terms", "license"),
        "sha256": ("sha256",),
    }
    present = [
        field
        for field in _REQUIRED_DELIVERY_METADATA
        if any(artifact.get(alias) not in (None, "", []) for alias in aliases[field])
    ]
    missing = [field for field in _REQUIRED_DELIVERY_METADATA if field not in present]
    return {
        "required_fields": list(_REQUIRED_DELIVERY_METADATA),
        "present_fields": present,
        "missing_fields": missing,
        "complete": not missing,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _manifest_artifacts(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact in manifest.get("artifacts", []):
        path = artifact.get("path")
        if isinstance(path, str) and path:
            artifacts[path] = artifact
    return artifacts


def _proxy_evidence(
    root: Path,
    artifact_index: dict[str, dict[str, Any]],
    request_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    for relative_path in _PUBLIC_PROXY_MAP[request_id]:
        artifact = artifact_index.get(relative_path)
        path = root / relative_path
        if artifact is None:
            if path.is_file():
                # Older candidate artifacts predate the public acquisition
                # manifest.  Record them, but do not admit them without the
                # required source/unit/licence metadata receipt.
                evidence.append(
                    {
                        "path": relative_path,
                        "exists": True,
                        "manifest_registered": False,
                        "status": "local_candidate_not_registered",
                        "source": None,
                        "model_admission": "unregistered_candidate",
                        "size_bytes": path.stat().st_size,
                        "sha256": _sha256(path),
                        "size_matches_manifest": False,
                        "sha256_matches_manifest": False,
                        "usable_proxy": False,
                        "metadata_completeness": _metadata_completeness({
                            "sha256": _sha256(path),
                        }),
                    }
                )
            else:
                missing.append(relative_path)
            continue
        exists = path.is_file()
        hash_matches = False
        size_matches = False
        if exists:
            expected_hash = artifact.get("sha256")
            expected_size = artifact.get("size_bytes")
            hash_matches = isinstance(expected_hash, str) and _sha256(path) == expected_hash
            size_matches = isinstance(expected_size, int) and path.stat().st_size == expected_size
        admission = artifact.get("model_admission")
        if admission not in _PROXY_ADMISSION:
            raise ValueError(f"data_request_readiness_unknown_proxy_admission:{relative_path}")
        integrity_verified = exists and size_matches and hash_matches
        usable_proxy = integrity_verified and admission not in {
            "metadata_only",
            "event_observation_candidate_not_downloaded",
        }
        evidence.append(
            {
                "path": relative_path,
                "exists": exists,
                "manifest_registered": True,
                "status": artifact.get("status"),
                "source": artifact.get("source"),
                "model_admission": admission,
                "size_bytes": artifact.get("size_bytes"),
                "sha256": artifact.get("sha256"),
                "size_matches_manifest": size_matches,
                "sha256_matches_manifest": hash_matches,
                "integrity_verified": integrity_verified,
                "usable_proxy": usable_proxy,
                "metadata_completeness": _metadata_completeness(artifact),
            }
        )
    return evidence, missing


def _proxy_status(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "no_public_proxy"
    usable = [item for item in evidence if item["usable_proxy"]]
    if not usable:
        if any(
            item.get("integrity_verified")
            and item.get("model_admission")
            in {"metadata_only", "event_observation_candidate_not_downloaded"}
            for item in evidence
        ):
            return "metadata_only_proxy"
        if any(item.get("exists") for item in evidence):
            return "local_candidate_unregistered"
        return "proxy_manifest_or_file_missing"
    admissions = {item["model_admission"] for item in usable}
    if admissions <= {"metadata_only", "event_observation_candidate_not_downloaded"}:
        return "metadata_only_proxy"
    return "available_public_proxy"


def build_data_request_readiness(
    dataset_root: Path,
    *,
    register_path: Path | None = None,
    public_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Audit the v2 register against local files without changing admission."""

    root = dataset_root.resolve()
    register_file = register_path or root / "derived/abu_dhabi_data_request_register_v2.json"
    manifest_file = public_manifest_path or root / "derived/public_data_acquisition_manifest.json"
    register = json.loads(register_file.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if register.get("schema") != "gwm.abu_dhabi_stormwater.data_request_register.v2":
        raise ValueError("data_request_readiness_register_schema_invalid")
    if manifest.get("schema") != "gwm.abu_dhabi_public_data_acquisition_manifest.v1":
        raise ValueError("data_request_readiness_manifest_schema_invalid")
    required_ids = set(_PUBLIC_PROXY_MAP)
    register_ids = {item.get("request_id") for item in register.get("requests", [])}
    if register_ids != required_ids:
        missing = sorted(required_ids - register_ids)
        extra = sorted(register_ids - required_ids)
        raise ValueError(
            "data_request_readiness_request_ids_invalid:"
            f"missing={','.join(missing)}:extra={','.join(str(item) for item in extra)}"
        )

    artifact_index = _manifest_artifacts(root, manifest)
    requests: list[dict[str, Any]] = []
    for item in sorted(
        register["requests"],
        key=lambda value: (value["priority"], value["request_id"]),
    ):
        request_id = item["request_id"]
        evidence, missing = _proxy_evidence(root, artifact_index, request_id)
        usable_count = sum(bool(entry["usable_proxy"]) for entry in evidence)
        requests.append(
            {
                "request_id": request_id,
                "priority": item["priority"],
                "domain": item["domain"],
                "required_artifact": item["required_artifact"],
                "customer_authoritative_status": item["status"],
                "customer_authoritative_available": False,
                "readiness_status": "blocked_waiting_customer_or_authority",
                "public_proxy_status": _proxy_status(evidence),
                "public_proxy_usable_artifact_count": usable_count,
                "public_proxy_missing_manifest_paths": missing,
                "public_proxy_evidence": evidence,
                "public_proxy_is_not_authoritative": True,
                "blocks": item["blocks"],
                "acceptance_checks": item["acceptance_checks"],
            }
        )

    public_proxy_count = sum(
        item["public_proxy_status"] == "available_public_proxy" for item in requests
    )
    metadata_only_count = sum(
        item["public_proxy_status"] == "metadata_only_proxy" for item in requests
    )
    local_candidate_count = sum(
        item["public_proxy_status"] == "local_candidate_unregistered"
        for item in requests
    )
    metadata_complete_proxy_count = sum(
        1
        for item in requests
        for evidence in item["public_proxy_evidence"]
        if evidence.get("usable_proxy")
        and evidence.get("metadata_completeness", {}).get("complete") is True
    )
    no_proxy_count = sum(item["public_proxy_status"] == "no_public_proxy" for item in requests)
    return {
        "schema": DATA_REQUEST_READINESS_SCHEMA,
        "register_id": register["register_id"],
        "register_sha256": _sha256(register_file),
        "public_manifest_sha256": _sha256(manifest_file),
        # Keep generated receipts portable and safe to publish; never persist
        # a developer's absolute filesystem path in a repository artifact.
        "dataset_root": root.name,
        "summary": {
            "request_count": len(requests),
            "customer_authoritative_available_count": 0,
            "blocked_waiting_customer_or_authority_count": len(requests),
            "available_public_proxy_count": public_proxy_count,
            "metadata_only_proxy_count": metadata_only_count,
            "local_candidate_unregistered_count": local_candidate_count,
            "metadata_complete_proxy_count": metadata_complete_proxy_count,
            "no_public_proxy_count": no_proxy_count,
        },
        "requests": requests,
        "model_gate_summary": {
            "k0_opened": False,
            "traditional_model_admitted": False,
            "gwm_training_admitted": False,
            "hybrid_planner_admitted": False,
            "city_scale_prediction_claim_allowed": False,
            "diagnostic_sensitivity_allowed": True,
            "admission_effect": "none_readiness_audit_only",
        },
        "claim_boundary": [
            "public_proxy_presence_is_not_customer_authoritative_delivery",
            "metadata_only_or_restricted_catalogs_are_not_observations",
            "file_receipt_does_not_open_k0_or_admit_any_model",
            "no_customer_database_rows_or_credentials_consumed",
        ],
    }


def write_data_request_readiness(
    dataset_root: Path,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    root = dataset_root.resolve()
    destination = output_path or root / "derived/abu_dhabi_data_request_readiness_v2.json"
    payload = build_data_request_readiness(root)
    _write_json(destination, payload)
    payload["output"] = {
        "path": _relative(destination.resolve(), root),
        "sha256": _sha256(destination),
        "size_bytes": destination.stat().st_size,
    }
    return payload


def render_data_request_readiness_markdown(payload: dict[str, Any]) -> str:
    """Render a concise customer-facing summary from an audited payload."""

    summary = payload["summary"]
    lines = [
        "# Abu Dhabi Stormwater Data Request Readiness",
        "",
        "This audit checks the v2 data-request register against local public artifacts. "
        "It does not consume customer database rows and does not open any model gate.",
        "",
        f"- Requests: **{summary['request_count']}**",
        "- Customer/authority deliveries received: "
        f"**{summary['customer_authoritative_available_count']}**",
        f"- Requests still blocked: **{summary['blocked_waiting_customer_or_authority_count']}**",
        f"- Requests with usable public proxies: **{summary['available_public_proxy_count']}**",
        "- Requests with metadata-only/restricted catalog evidence: "
        f"**{summary['metadata_only_proxy_count']}**",
        "- Requests with local but unregistered candidates: "
        f"**{summary['local_candidate_unregistered_count']}**",
        "- Admissible proxy files with all delivery metadata present: "
        f"**{summary['metadata_complete_proxy_count']}**",
        f"- Requests with no public proxy: **{summary['no_public_proxy_count']}**",
        "",
            "| Priority | Request | Customer status | Public evidence | Model use |",
        "|---|---|---|---|---|",
    ]
    for item in payload["requests"]:
        lines.append(
            "| {priority} | `{request_id}` | `{customer_authoritative_status}` | "
            "`{public_proxy_status}` ({count} admissible proxy file(s)) | "
            "blocked: {blocks} |".format(
                priority=item["priority"],
                request_id=item["request_id"],
                customer_authoritative_status=item["customer_authoritative_status"],
                public_proxy_status=item["public_proxy_status"],
                count=item["public_proxy_usable_artifact_count"],
                blocks=", ".join(item["blocks"]),
            )
        )
    lines.extend(
        [
            "",
            "## Gate state",
            "",
            "K0, traditional-model admission, GWM training, hybrid planner and "
            "city-scale prediction claims remain closed. Public files are limited "
            "to diagnostic sensitivity, context, or catalog evidence until the "
            "customer/authority acceptance checks are completed.",
            "",
        ]
    )
    return "\n".join(lines)


def write_data_request_readiness_markdown(
    payload: dict[str, Any],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(render_data_request_readiness_markdown(payload), encoding="utf-8")
    temporary.replace(destination)
