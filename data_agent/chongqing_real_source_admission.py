"""Build a fail-closed admission manifest for the full Chongqing sample.

M3-28 profiles the real planning-institute archive as an AR-2 source without
copying source payloads into the repository. The checked evidence is path-free,
content-addressed, and metadata-only. It never authorizes ingestion,
publication, scheduler submission, or provider mutation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
import zipfile
import zlib
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .uwm.local_planning_zip_audit import scan_local_planning_zip_assets

EVIDENCE_SCHEMA = "gda.chongqing_real_source_admission.v1"
VALIDATION_SCHEMA = "gda.chongqing_real_source_admission_validation.v1"
STATUS = "blocked_pending_source_governance"
SOURCE_ID = "chongqing-planning-institute-sample"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_PATH = REPO_ROOT / "docs/evidence/chongqing-real-source-admission-2026-07-31.json"
RESEARCH_INVENTORY_PATH = (
    REPO_ROOT / "data/uwm_public_proxy/chongqing_central/"
    "local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv"
)

EXPECTED_ARCHIVE_SHA256 = "2043b60c2f4f7f32a31388a634fae4ac28534990e205aa86b8df0e4b64dcbbca"
EXPECTED_ARCHIVE_SIZE_BYTES = 468_462_251
EXPECTED_ARCHIVE_ENTRY_COUNT = 533
EXPECTED_ARCHIVE_UNCOMPRESSED_SIZE_BYTES = 694_164_379
EXPECTED_ARCHIVE_SCOPE_ENTRY_COUNT = 532
EXPECTED_ARCHIVE_SCOPE_SIZE_BYTES = 694_147_946
EXPECTED_EXTRACTED_FILE_COUNT = 584
EXPECTED_EXTRACTED_SIZE_BYTES = 700_610_744
EXPECTED_ARCHIVE_EXACT_MATCH_COUNT = 526
EXPECTED_ARCHIVE_MODIFIED_COUNT = 6
EXPECTED_ARCHIVE_MISSING_COUNT = 0
EXPECTED_EXTRACTED_ADDITIONAL_COUNT = 52
EXPECTED_EXTRACTED_PAYLOAD_SHA256 = (
    "e7e81e4f53f9f174792f500fbfdfde6bee30ec03beac8cbd91771fe09f548ea6"
)
EXPECTED_RESEARCH_INVENTORY_SHA256 = (
    "69b4167955f950041988dd174b75ea5376af146ef3e52f815aa57715fd24f70d"
)
EXPECTED_RESEARCH_INVENTORY_ROWS = 16
EXPECTED_RESEARCH_ASSET_IDS_SHA256 = (
    "c7cb765c2b653dbf5619e2fe1cf027d108a5951b752b6dd4bfd60b4c00d91947"
)
EVIDENCE_FILE_SHA256 = "9b5c20369c235f7e0a2f2cb0a21cee77f86981aa273bac196605a4803b05ce83"

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SOURCE_REF_PATTERN = re.compile(rf"^source://{re.escape(SOURCE_ID)}/assets/[a-z0-9][a-z0-9_-]+$")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[-_.])(password|passwd|secret|client[-_.]?secret|private[-_.]?key|"
    r"access[-_.]?key|access[-_.]?token|refresh[-_.]?token|"
    r"authorization[-_.]?header)($|[-_.])",
    re.IGNORECASE,
)

EVIDENCE_INVENTORY = {
    "schema",
    "status",
    "captured_at",
    "source_binding",
    "research_audit_binding",
    "source_groups",
    "asset_profiles",
    "admission_blockers",
    "admission_policy",
    "claims",
    "evidence_sha256",
}
SOURCE_BINDING_INVENTORY = {
    "source_id",
    "archive_sha256",
    "archive_size_bytes",
    "archive_entry_count",
    "archive_uncompressed_size_bytes",
    "archive_source_scope_entry_count",
    "archive_source_scope_size_bytes",
    "archive_original_entry_exact_match_count",
    "archive_original_entry_modified_count",
    "archive_original_entry_missing_count",
    "extracted_additional_file_count",
    "archive_integrity_verified",
    "archive_extracted_entry_multiset_verified",
    "extracted_file_count",
    "extracted_size_bytes",
    "extracted_payload_sha256",
    "logical_group_inventory_sha256",
    "source_payload_in_repository",
    "absolute_source_paths_in_evidence",
}
RESEARCH_AUDIT_INVENTORY = {
    "path",
    "file_sha256",
    "row_count",
    "asset_ids_sha256",
    "authority",
    "admission_authority",
}
SOURCE_GROUP_INVENTORY = {
    "source_group_id",
    "ordinal",
    "file_count",
    "size_bytes",
    "extension_counts",
    "content_manifest_sha256",
    "data_domains",
    "data_classification",
    "license_status",
    "admission_status",
    "metadata_profiled",
    "content_admitted",
    "blockers",
}
ASSET_PROFILE_INVENTORY = {
    "asset_id",
    "source_group_id",
    "source_ref",
    "asset_kind",
    "data_classification",
    "admission_status",
    "record_metrics",
    "spatial_profile",
    "schema_fields",
    "roles",
    "metadata_profiled",
    "source_content_in_evidence",
    "profile_sha256",
}
CLAIMS = {
    "archive_integrity_verified",
    "archive_extracted_entry_multiset_verified",
    "full_source_metadata_profiled",
    "source_governance_approved",
    "source_content_admitted",
    "source_publication_authorized",
    "scheduler_submission_authorized",
    "provider_mutation_authorized",
    "production_ingestion_verified",
    "production_ready",
}
SOURCE_BINDING_BLOCKERS = [
    "source_binding:extraction_derivation_provenance_missing",
]
ADMISSION_POLICY = {
    "metadata_profiling_allowed": True,
    "content_admission_requires_owner_license_retention_and_access_approval": True,
    "restricted_fields_require_privacy_review": True,
    "source_payload_copy_to_repository_forbidden": True,
    "ci_requires_local_source_payload": False,
    "fresh_protected_ingestion_required_after_admission": True,
    "local_profile_is_not_production_admission": True,
}


SOURCE_GROUP_SPECS: tuple[dict[str, Any], ...] = (
    {
        "ordinal": "01",
        "source_group_id": "chongqing-dem-2020",
        "data_domains": ["elevation", "terrain", "raster"],
        "data_classification": "restricted_local_baseline",
        "additional_blockers": ["source_vintage_unverified"],
    },
    {
        "ordinal": "02",
        "source_group_id": "chongqing-osm-roads-2021",
        "data_domains": ["transport_network", "vector"],
        "data_classification": "restricted_local_open_data_copy",
        "additional_blockers": ["odbl_attribution_policy_missing"],
    },
    {
        "ordinal": "03",
        "source_group_id": "chongqing-clcd-2020",
        "data_domains": ["land_cover", "remote_sensing", "raster"],
        "data_classification": "restricted_local_remote_sensing",
        "additional_blockers": ["classification_lineage_unverified"],
    },
    {
        "ordinal": "04",
        "source_group_id": "chongqing-central-buildings-2021",
        "data_domains": ["buildings", "urban_form", "vector"],
        "data_classification": "restricted_local_built_environment",
        "additional_blockers": ["source_vintage_unverified"],
    },
    {
        "ordinal": "05",
        "source_group_id": "chongqing-historic-districts",
        "data_domains": ["cultural_heritage", "planning_constraints", "vector"],
        "data_classification": "restricted_local_cultural_planning",
        "additional_blockers": ["source_vintage_unverified"],
    },
    {
        "ordinal": "07",
        "source_group_id": "bishan-planning-materials",
        "data_domains": ["land_use", "planning", "documents", "vector", "tables"],
        "data_classification": "highly_restricted_planning",
        "additional_blockers": ["planning_sensitivity_review_missing"],
    },
    {
        "ordinal": "08",
        "source_group_id": "chongqing-district-population-2021",
        "data_domains": ["population", "statistics", "table"],
        "data_classification": "restricted_aggregate_population",
        "additional_blockers": ["statistics_vintage_review_missing"],
    },
    {
        "ordinal": "09",
        "source_group_id": "gaode-poi-2024",
        "data_domains": ["poi", "commercial_location", "vector"],
        "data_classification": "highly_restricted_commercial_location",
        "additional_blockers": ["contact_field_privacy_review_missing"],
    },
    {
        "ordinal": "10",
        "source_group_id": "baidu-aoi-2024",
        "data_domains": ["aoi", "commercial_location", "vector"],
        "data_classification": "highly_restricted_commercial_location",
        "additional_blockers": ["contact_field_privacy_review_missing"],
    },
    {
        "ordinal": "11",
        "source_group_id": "unicom-commuting-2023",
        "data_domains": ["mobility", "population", "aggregate_signaling", "table"],
        "data_classification": "highly_restricted_aggregate_mobility",
        "additional_blockers": [
            "privacy_impact_assessment_missing",
            "grid_geometry_dictionary_missing",
        ],
    },
    {
        "ordinal": "12",
        "source_group_id": "baidu-search-index-2023",
        "data_domains": ["search_activity", "intercity_flow", "vector"],
        "data_classification": "highly_restricted_commercial_activity",
        "additional_blockers": ["commercial_terms_review_missing"],
    },
)

GROUP_BY_ORDINAL = {spec["ordinal"]: spec for spec in SOURCE_GROUP_SPECS}
GROUP_BY_ID = {spec["source_group_id"]: spec for spec in SOURCE_GROUP_SPECS}

EXPECTED_ASSET_BASELINES: dict[str, dict[str, Any]] = {
    "chongqing_osm_roads_2021": {
        "source_group_id": "chongqing-osm-roads-2021",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 50_366},
        "geometry_type": "LineString",
        "crs": "EPSG:4326",
    },
    "chongqing_central_buildings_2021": {
        "source_group_id": "chongqing-central-buildings-2021",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 107_452},
        "geometry_type": "Polygon",
        "crs": "EPSG:4326",
    },
    "chongqing_historic_districts_local": {
        "source_group_id": "chongqing-historic-districts",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 20},
        "geometry_type": "Polygon Z",
        "crs": "EPSG:4490",
    },
    "bishan_land_use_dltb_local": {
        "source_group_id": "bishan-planning-materials",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 101_657},
        "geometry_type": "MultiPolygon",
        "crs": "EPSG:4610",
    },
    "gaode_poi_2024": {
        "source_group_id": "gaode-poi-2024",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 1_194_351},
        "geometry_type": "Point",
        "crs": "EPSG:4490",
    },
    "baidu_aoi_2024": {
        "source_group_id": "baidu-aoi-2024",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 26_292},
        "geometry_type": "MultiPolygon",
        "crs": "EPSG:4490",
    },
    "baidu_search_index_2023_local": {
        "source_group_id": "baidu-search-index-2023",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 325},
        "geometry_type": "MultiLineString",
        "crs": "EPSG:4490",
    },
    "bishan_admin_boundary_cjdcq_local": {
        "source_group_id": "bishan-planning-materials",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 1_488},
        "geometry_type": "MultiPolygon",
        "crs": "EPSG:4523+EPSG:5737",
    },
    "bishan_admin_boundary_xzq_local": {
        "source_group_id": "bishan-planning-materials",
        "asset_kind": "vector",
        "record_metrics": {"feature_count": 15},
        "geometry_type": "MultiPolygon",
        "crs": "EPSG:4523+EPSG:5737",
    },
    "fulu_village_planning_database_local": {
        "source_group_id": "bishan-planning-materials",
        "asset_kind": "vector_collection",
        "record_metrics": {
            "feature_count": 8_050,
            "layer_count": 28,
            "nonempty_layer_count": 20,
        },
        "geometry_type": "mixed",
        "crs": "mixed_CGCS2000_GK_zone_35_EPSG4523",
    },
    "chongqing_district_population_stats_2021_local": {
        "source_group_id": "chongqing-district-population-2021",
        "asset_kind": "workbook",
        "record_metrics": {"row_count": 41, "sheet_count": 1},
    },
    "chongqing_unicom_commuting_2023_local": {
        "source_group_id": "unicom-commuting-2023",
        "asset_kind": "table",
        "record_metrics": {"row_count": 2_120, "column_count": 7},
    },
    "clcd_classification_dictionary_local": {
        "source_group_id": "chongqing-clcd-2020",
        "asset_kind": "workbook",
        "record_metrics": {"row_count": 10, "sheet_count": 1},
    },
    "bishan_land_development_ledger_2019_local": {
        "source_group_id": "bishan-planning-materials",
        "asset_kind": "workbook_collection",
        "record_metrics": {"row_count": 1_438, "sheet_count": 4},
    },
    "chongqing_dem_80m": {
        "source_group_id": "chongqing-dem-2020",
        "asset_kind": "raster",
        "record_metrics": {
            "width": 1_766,
            "height": 1_454,
            "band_count": 1,
            "pixel_count": 2_567_764,
        },
        "crs": "EPSG:4490",
    },
    "chongqing_clcd_2020": {
        "source_group_id": "chongqing-clcd-2020",
        "asset_kind": "raster",
        "record_metrics": {
            "width": 18_579,
            "height": 15_082,
            "band_count": 1,
            "pixel_count": 280_208_478,
        },
        "crs": "EPSG:4326",
    },
}


class ChongqingRealSourceAdmissionError(RuntimeError):
    """The full-source admission snapshot failed closed."""


def canonical_json_fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document is not an object")
    return value


def _parse_time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ChongqingRealSourceAdmissionError("captured_at is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ChongqingRealSourceAdmissionError("captured_at must be timezone-aware")
    return parsed.astimezone(UTC)


def _source_group_blockers(spec: Mapping[str, Any]) -> list[str]:
    group_id = str(spec["source_group_id"])
    suffixes = [
        "owner_reference_missing",
        "license_terms_unverified",
        "retention_policy_missing",
        "access_policy_missing",
        *[str(item) for item in spec.get("additional_blockers", [])],
    ]
    return [f"source_group:{group_id}:{suffix}" for suffix in suffixes]


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_mode,
    )


def _hash_regular_file(path: Path) -> tuple[int, str, str]:
    before = path.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ChongqingRealSourceAdmissionError("source payload contains a non-regular file")
    sha256 = hashlib.sha256()
    crc32 = 0
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _stat_identity(opened) != _stat_identity(before):
            raise ChongqingRealSourceAdmissionError(
                "source payload file identity changed before hashing"
            )
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha256.update(chunk)
            crc32 = zlib.crc32(chunk, crc32)
        after = os.fstat(stream.fileno())
    if _stat_identity(after) != _stat_identity(before):
        raise ChongqingRealSourceAdmissionError(
            "source payload file identity changed while hashing"
        )
    return before.st_size, sha256.hexdigest(), f"{crc32 & 0xFFFFFFFF:08x}"


def _scan_payload_files(source_root: Path) -> list[dict[str, Any]]:
    root = source_root.resolve(strict=True)
    root_stat = source_root.lstat()
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ChongqingRealSourceAdmissionError("source root must be a real directory")
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ChongqingRealSourceAdmissionError("source payload contains a symbolic link")
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        ordinal = relative_path.split("/", 1)[0][:2]
        spec = GROUP_BY_ORDINAL.get(ordinal)
        if spec is None:
            raise ChongqingRealSourceAdmissionError(
                f"source payload contains an unknown top-level group: {ordinal}"
            )
        size, sha256, crc32 = _hash_regular_file(path)
        suffix = path.suffix.lower().lstrip(".") or "[no_ext]"
        records.append(
            {
                "relative_path": relative_path,
                "source_group_id": spec["source_group_id"],
                "size_bytes": size,
                "extension": suffix,
                "sha256": sha256,
                "crc32": crc32,
            }
        )
    if not records:
        raise ChongqingRealSourceAdmissionError("source payload is empty")
    return records


def _payload_fingerprint(records: list[Mapping[str, Any]]) -> str:
    material = [
        {
            "relative_path": item["relative_path"],
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
        }
        for item in records
    ]
    return canonical_json_fingerprint(material)


def _build_source_groups(records: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for spec in SOURCE_GROUP_SPECS:
        group_records = [
            item for item in records if item.get("source_group_id") == spec["source_group_id"]
        ]
        if not group_records:
            raise ChongqingRealSourceAdmissionError(
                f"source group is empty: {spec['source_group_id']}"
            )
        manifest = [
            {
                "relative_path": item["relative_path"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
            for item in group_records
        ]
        extensions = Counter(str(item["extension"]) for item in group_records)
        groups.append(
            {
                "source_group_id": spec["source_group_id"],
                "ordinal": spec["ordinal"],
                "file_count": len(group_records),
                "size_bytes": sum(int(item["size_bytes"]) for item in group_records),
                "extension_counts": dict(sorted(extensions.items())),
                "content_manifest_sha256": canonical_json_fingerprint(manifest),
                "data_domains": list(spec["data_domains"]),
                "data_classification": spec["data_classification"],
                "license_status": "unverified_restricted",
                "admission_status": STATUS,
                "metadata_profiled": True,
                "content_admitted": False,
                "blockers": _source_group_blockers(spec),
            }
        )
    return groups


def _archive_binding(
    source_zip: Path,
    payload_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    archive_stat = source_zip.lstat()
    if stat.S_ISLNK(archive_stat.st_mode) or not stat.S_ISREG(archive_stat.st_mode):
        raise ChongqingRealSourceAdmissionError("source archive must be a regular file")
    archive_sha256 = _file_sha256(source_zip)
    with zipfile.ZipFile(source_zip) as archive:
        bad_entry = archive.testzip()
        if bad_entry is not None:
            raise ChongqingRealSourceAdmissionError("source archive CRC validation failed")
        all_entries = [item for item in archive.infolist() if not item.is_dir()]
        scoped_entries = [
            (item, relative_path)
            for item in archive.infolist()
            if not item.is_dir()
            and (relative_path := _source_scope_relative_path(item)) is not None
        ]
    extracted_by_path = {str(item["relative_path"]): item for item in payload_records}
    scoped_paths = {relative_path for _, relative_path in scoped_entries}
    if len(scoped_paths) != len(scoped_entries):
        raise ChongqingRealSourceAdmissionError("source archive scope contains duplicate paths")
    exact_match_count = 0
    modified_count = 0
    missing_count = 0
    for item, relative_path in scoped_entries:
        extracted = extracted_by_path.get(relative_path)
        if extracted is None:
            missing_count += 1
            continue
        if (
            int(extracted["size_bytes"]) == item.file_size
            and str(extracted["crc32"]) == f"{item.CRC & 0xFFFFFFFF:08x}"
        ):
            exact_match_count += 1
        else:
            modified_count += 1
    additional_count = len(set(extracted_by_path) - scoped_paths)
    multiset_verified = not (modified_count or missing_count or additional_count)
    return {
        "archive_sha256": archive_sha256,
        "archive_size_bytes": archive_stat.st_size,
        "archive_entry_count": len(all_entries),
        "archive_uncompressed_size_bytes": sum(item.file_size for item in all_entries),
        "archive_source_scope_entry_count": len(scoped_entries),
        "archive_source_scope_size_bytes": sum(item.file_size for item, _ in scoped_entries),
        "archive_original_entry_exact_match_count": exact_match_count,
        "archive_original_entry_modified_count": modified_count,
        "archive_original_entry_missing_count": missing_count,
        "extracted_additional_file_count": additional_count,
        "archive_integrity_verified": True,
        "archive_extracted_entry_multiset_verified": multiset_verified,
    }


def _source_scope_relative_path(item: zipfile.ZipInfo) -> str | None:
    name = item.filename
    if not item.flag_bits & 0x800:
        try:
            name = name.encode("cp437").decode("gbk")
        except UnicodeError:
            pass
    marker = "/01数据样例/"
    if marker not in name:
        return None
    return name.split(marker, 1)[1]


def _normalise_crs(value: Any) -> str:
    text = str(value or "")
    if text.startswith("COMPD_CS[") and 'AUTHORITY["EPSG","4523"]' in text:
        return "EPSG:4523+EPSG:5737"
    return text


def _source_group_for_profile(profile: Mapping[str, Any], source_root: Path) -> str:
    source_path = Path(str(profile.get("source_path") or ""))
    try:
        relative = source_path.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError as exc:
        raise ChongqingRealSourceAdmissionError("asset profile escaped the source root") from exc
    ordinal = relative.split("/", 1)[0][:2]
    spec = GROUP_BY_ORDINAL.get(ordinal)
    if spec is None:
        raise ChongqingRealSourceAdmissionError("asset profile has an unknown source group")
    return str(spec["source_group_id"])


def _asset_profile(
    raw: Mapping[str, Any],
    *,
    source_root: Path,
) -> dict[str, Any]:
    asset_id = str(raw.get("asset_id") or "")
    source_group_id = _source_group_for_profile(raw, source_root)
    group_spec = GROUP_BY_ID[source_group_id]
    metric_names = (
        "feature_count",
        "row_count",
        "column_count",
        "sheet_count",
        "width",
        "height",
        "band_count",
        "pixel_count",
        "layer_count",
        "nonempty_layer_count",
    )
    metrics = {name: int(raw[name]) for name in metric_names if raw.get(name) is not None}
    crs = _normalise_crs(raw.get("crs"))
    spatial: dict[str, Any] | None = None
    if raw.get("geometry_type") is not None or crs or raw.get("bounds") is not None:
        spatial = {
            "geometry_type": str(raw.get("geometry_type") or ""),
            "crs": crs,
            "bounds": (
                [float(item) for item in raw["bounds"]] if raw.get("bounds") is not None else None
            ),
            "dtype": [str(item) for item in raw.get("dtype", [])],
            "nodata": raw.get("nodata"),
        }
    fields = raw.get("fields") or raw.get("columns") or []
    stable = {
        "asset_id": asset_id,
        "source_group_id": source_group_id,
        "source_ref": f"source://{SOURCE_ID}/assets/{asset_id}",
        "asset_kind": str(raw.get("asset_kind") or ""),
        "data_classification": group_spec["data_classification"],
        "admission_status": STATUS,
        "record_metrics": metrics,
        "spatial_profile": spatial,
        "schema_fields": [str(item) for item in fields],
        "roles": sorted(item for item in str(raw.get("uwm_roles") or "").split(";") if item),
        "metadata_profiled": True,
        "source_content_in_evidence": False,
    }
    return {**stable, "profile_sha256": canonical_json_fingerprint(stable)}


def _asset_profiles(source_root: Path, source_zip: Path, captured_at: str) -> list[dict[str, Any]]:
    report = scan_local_planning_zip_assets(
        source_root=source_root,
        source_zip=source_zip,
        created_at=captured_at,
    )
    raw_profiles = [
        *report.get("vector_profiles", []),
        *report.get("tabular_profiles", []),
        *report.get("raster_profiles", []),
    ]
    profiles = [_asset_profile(raw, source_root=source_root) for raw in raw_profiles]
    return sorted(profiles, key=lambda item: str(item["asset_id"]))


def _research_audit_binding(path: Path = RESEARCH_INVENTORY_PATH) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "file_sha256": _file_sha256(path),
        "row_count": len(rows),
        "asset_ids_sha256": canonical_json_fingerprint(
            sorted(str(row.get("asset_id") or "") for row in rows)
        ),
        "authority": "research_inventory_only",
        "admission_authority": False,
    }


def build_evidence(
    *,
    source_root: Path,
    source_zip: Path,
    captured_at: datetime | None = None,
    research_inventory_path: Path = RESEARCH_INVENTORY_PATH,
) -> dict[str, Any]:
    timestamp = (captured_at or datetime.now(UTC)).astimezone(UTC)
    captured_text = timestamp.isoformat().replace("+00:00", "Z")
    payload_records = _scan_payload_files(source_root)
    groups = _build_source_groups(payload_records)
    archive = _archive_binding(source_zip, payload_records)
    profiles = _asset_profiles(source_root, source_zip, captured_text)
    blockers = sorted(
        [
            *SOURCE_BINDING_BLOCKERS,
            *(blocker for group in groups for blocker in group["blockers"]),
        ]
    )
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": STATUS,
        "captured_at": captured_text,
        "source_binding": {
            "source_id": SOURCE_ID,
            **archive,
            "extracted_file_count": len(payload_records),
            "extracted_size_bytes": sum(int(item["size_bytes"]) for item in payload_records),
            "extracted_payload_sha256": _payload_fingerprint(payload_records),
            "logical_group_inventory_sha256": canonical_json_fingerprint(groups),
            "source_payload_in_repository": False,
            "absolute_source_paths_in_evidence": False,
        },
        "research_audit_binding": _research_audit_binding(research_inventory_path),
        "source_groups": groups,
        "asset_profiles": profiles,
        "admission_blockers": blockers,
        "admission_policy": dict(ADMISSION_POLICY),
        "claims": {
            "archive_integrity_verified": archive["archive_integrity_verified"],
            "archive_extracted_entry_multiset_verified": archive[
                "archive_extracted_entry_multiset_verified"
            ],
            "full_source_metadata_profiled": True,
            "source_governance_approved": False,
            "source_content_admitted": False,
            "source_publication_authorized": False,
            "scheduler_submission_authorized": False,
            "provider_mutation_authorized": False,
            "production_ingestion_verified": False,
            "production_ready": False,
        },
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def _sensitive_paths(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                findings.append(path)
            findings.extend(_sensitive_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_sensitive_paths(item, f"{prefix}[{index}]"))
    return findings


def _asset_baseline_errors(profile: Mapping[str, Any]) -> list[str]:
    asset_id = str(profile.get("asset_id") or "")
    expected = EXPECTED_ASSET_BASELINES.get(asset_id)
    if expected is None:
        return [f"M3-28 asset profile is unknown: {asset_id}"]
    errors: list[str] = []
    for key in ("source_group_id", "asset_kind"):
        if profile.get(key) != expected[key]:
            errors.append(f"M3-28 asset {key} does not match: {asset_id}")
    metrics = profile.get("record_metrics")
    if not isinstance(metrics, Mapping):
        errors.append(f"M3-28 asset record metrics are invalid: {asset_id}")
    else:
        for key, value in expected["record_metrics"].items():
            if metrics.get(key) != value:
                errors.append(f"M3-28 asset metric does not match: {asset_id}.{key}")
    spatial = profile.get("spatial_profile")
    for key in ("geometry_type", "crs"):
        if key not in expected:
            continue
        if not isinstance(spatial, Mapping) or spatial.get(key) != expected[key]:
            errors.append(f"M3-28 asset spatial profile does not match: {asset_id}.{key}")
    return errors


def validate_evidence(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(evidence) != EVIDENCE_INVENTORY:
        errors.append("M3-28 evidence inventory does not match")
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("M3-28 evidence fingerprint does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("status") != STATUS:
        errors.append("M3-28 evidence schema or status does not match")
    try:
        _parse_time(evidence.get("captured_at"))
    except ChongqingRealSourceAdmissionError as exc:
        errors.append(str(exc))

    source = evidence.get("source_binding")
    if not isinstance(source, Mapping):
        errors.append("M3-28 source binding is invalid")
        source = {}
    elif set(source) != SOURCE_BINDING_INVENTORY:
        errors.append("M3-28 source binding inventory does not match")
    expected_source_values = {
        "source_id": SOURCE_ID,
        "archive_sha256": EXPECTED_ARCHIVE_SHA256,
        "archive_size_bytes": EXPECTED_ARCHIVE_SIZE_BYTES,
        "archive_entry_count": EXPECTED_ARCHIVE_ENTRY_COUNT,
        "archive_uncompressed_size_bytes": EXPECTED_ARCHIVE_UNCOMPRESSED_SIZE_BYTES,
        "archive_source_scope_entry_count": EXPECTED_ARCHIVE_SCOPE_ENTRY_COUNT,
        "archive_source_scope_size_bytes": EXPECTED_ARCHIVE_SCOPE_SIZE_BYTES,
        "archive_original_entry_exact_match_count": EXPECTED_ARCHIVE_EXACT_MATCH_COUNT,
        "archive_original_entry_modified_count": EXPECTED_ARCHIVE_MODIFIED_COUNT,
        "archive_original_entry_missing_count": EXPECTED_ARCHIVE_MISSING_COUNT,
        "extracted_additional_file_count": EXPECTED_EXTRACTED_ADDITIONAL_COUNT,
        "archive_integrity_verified": True,
        "archive_extracted_entry_multiset_verified": False,
        "extracted_file_count": EXPECTED_EXTRACTED_FILE_COUNT,
        "extracted_size_bytes": EXPECTED_EXTRACTED_SIZE_BYTES,
        "source_payload_in_repository": False,
        "absolute_source_paths_in_evidence": False,
    }
    for key, value in expected_source_values.items():
        if source.get(key) != value:
            errors.append(f"M3-28 source binding does not match: {key}")
    if (
        EXPECTED_EXTRACTED_PAYLOAD_SHA256
        and source.get("extracted_payload_sha256") != EXPECTED_EXTRACTED_PAYLOAD_SHA256
    ):
        errors.append("M3-28 extracted payload fingerprint does not match")
    for key in (
        "archive_sha256",
        "extracted_payload_sha256",
        "logical_group_inventory_sha256",
    ):
        if not SHA256_PATTERN.fullmatch(str(source.get(key) or "")):
            errors.append(f"M3-28 source fingerprint is invalid: {key}")

    research = evidence.get("research_audit_binding")
    if not isinstance(research, Mapping):
        errors.append("M3-28 research audit binding is invalid")
        research = {}
    if (
        set(research) != RESEARCH_AUDIT_INVENTORY
        or research.get("path") != str(RESEARCH_INVENTORY_PATH.relative_to(REPO_ROOT))
        or research.get("file_sha256") != EXPECTED_RESEARCH_INVENTORY_SHA256
        or research.get("row_count") != EXPECTED_RESEARCH_INVENTORY_ROWS
        or research.get("asset_ids_sha256") != EXPECTED_RESEARCH_ASSET_IDS_SHA256
        or research.get("authority") != "research_inventory_only"
        or research.get("admission_authority") is not False
    ):
        errors.append("M3-28 research audit binding does not match")

    if evidence.get("admission_policy") != ADMISSION_POLICY:
        errors.append("M3-28 admission policy does not match")

    groups_value = evidence.get("source_groups")
    groups = groups_value if isinstance(groups_value, list) else []
    if not isinstance(groups_value, list):
        errors.append("M3-28 source groups are not a list")
    group_ids: list[str] = []
    derived_blockers: list[str] = []
    file_count = 0
    size_bytes = 0
    for group in groups:
        if not isinstance(group, Mapping):
            errors.append("M3-28 source group is not an object")
            continue
        group_id = str(group.get("source_group_id") or "")
        group_ids.append(group_id)
        if set(group) != SOURCE_GROUP_INVENTORY:
            errors.append(f"M3-28 source group inventory does not match: {group_id}")
        spec = GROUP_BY_ID.get(group_id)
        if spec is None:
            errors.append(f"M3-28 source group is unknown: {group_id}")
            continue
        if (
            group.get("ordinal") != spec["ordinal"]
            or group.get("data_domains") != spec["data_domains"]
            or group.get("data_classification") != spec["data_classification"]
            or group.get("blockers") != _source_group_blockers(spec)
        ):
            errors.append(f"M3-28 source group contract does not match: {group_id}")
        for key, expected in (
            ("license_status", "unverified_restricted"),
            ("admission_status", STATUS),
            ("metadata_profiled", True),
            ("content_admitted", False),
        ):
            if group.get(key) != expected:
                errors.append(f"M3-28 source group claim does not match: {group_id}.{key}")
        if not SHA256_PATTERN.fullmatch(str(group.get("content_manifest_sha256") or "")):
            errors.append(f"M3-28 source group fingerprint is invalid: {group_id}")
        extensions = group.get("extension_counts")
        if not isinstance(extensions, Mapping) or sum(
            int(value) for value in extensions.values()
        ) != group.get("file_count"):
            errors.append(f"M3-28 source group extension counts do not match: {group_id}")
        file_count += int(group.get("file_count") or 0)
        size_bytes += int(group.get("size_bytes") or 0)
        derived_blockers.extend(str(item) for item in group.get("blockers", []))
    expected_group_ids = [str(spec["source_group_id"]) for spec in SOURCE_GROUP_SPECS]
    if group_ids != expected_group_ids or len(group_ids) != len(set(group_ids)):
        errors.append("M3-28 source group inventory is incomplete or reordered")
    if file_count != EXPECTED_EXTRACTED_FILE_COUNT or size_bytes != EXPECTED_EXTRACTED_SIZE_BYTES:
        errors.append("M3-28 source group physical totals do not match")
    if source.get("logical_group_inventory_sha256") != canonical_json_fingerprint(groups):
        errors.append("M3-28 logical group inventory fingerprint does not match")

    profiles_value = evidence.get("asset_profiles")
    profiles = profiles_value if isinstance(profiles_value, list) else []
    if not isinstance(profiles_value, list):
        errors.append("M3-28 asset profiles are not a list")
    asset_ids: list[str] = []
    for profile in profiles:
        if not isinstance(profile, Mapping):
            errors.append("M3-28 asset profile is not an object")
            continue
        asset_id = str(profile.get("asset_id") or "")
        asset_ids.append(asset_id)
        if set(profile) != ASSET_PROFILE_INVENTORY:
            errors.append(f"M3-28 asset profile inventory does not match: {asset_id}")
        profile_stable = {key: value for key, value in profile.items() if key != "profile_sha256"}
        if profile.get("profile_sha256") != canonical_json_fingerprint(profile_stable):
            errors.append(f"M3-28 asset profile fingerprint does not match: {asset_id}")
        if not SOURCE_REF_PATTERN.fullmatch(str(profile.get("source_ref") or "")):
            errors.append(f"M3-28 asset source reference is invalid: {asset_id}")
        group_spec = GROUP_BY_ID.get(str(profile.get("source_group_id") or ""))
        if (
            group_spec is None
            or profile.get("data_classification") != group_spec["data_classification"]
            or profile.get("admission_status") != STATUS
            or profile.get("metadata_profiled") is not True
            or profile.get("source_content_in_evidence") is not False
        ):
            errors.append(f"M3-28 asset admission boundary does not match: {asset_id}")
        errors.extend(_asset_baseline_errors(profile))
    expected_asset_ids = sorted(EXPECTED_ASSET_BASELINES)
    if asset_ids != expected_asset_ids or len(asset_ids) != len(set(asset_ids)):
        errors.append("M3-28 asset profile inventory is incomplete or reordered")

    blockers = evidence.get("admission_blockers")
    expected_blockers = sorted([*SOURCE_BINDING_BLOCKERS, *derived_blockers])
    if blockers != expected_blockers or len(expected_blockers) != len(set(expected_blockers)):
        errors.append("M3-28 admission blockers do not match source groups")

    claims = evidence.get("claims")
    if not isinstance(claims, Mapping) or set(claims) != CLAIMS:
        errors.append("M3-28 claims inventory does not match")
    else:
        expected_true = {
            "archive_integrity_verified",
            "full_source_metadata_profiled",
        }
        for claim in CLAIMS:
            expected = claim in expected_true
            if claims.get(claim) is not expected:
                errors.append(f"M3-28 claim does not match: {claim}")
    if _sensitive_paths(evidence):
        errors.append("M3-28 evidence contains credential-bearing fields")
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    for forbidden in ("/Users/", "Downloads/", ".tmp/twm_standard_1128"):
        if forbidden in rendered:
            errors.append("M3-28 evidence contains a local source path")
            break
    return sorted(set(errors))


def build_validation_report(
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    try:
        file_sha256 = _file_sha256(evidence_path)
        evidence = _load_json_object(evidence_path)
        errors = validate_evidence(evidence)
        if EVIDENCE_FILE_SHA256 and file_sha256 != EVIDENCE_FILE_SHA256:
            errors.append("M3-28 evidence file fingerprint does not match")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        evidence = {}
        file_sha256 = None
        errors = [f"M3-28 evidence is unreadable: {type(exc).__name__}"]
    source = evidence.get("source_binding")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "errors": sorted(set(errors)),
        "evidence_file_sha256": file_sha256,
        "evidence_sha256": evidence.get("evidence_sha256"),
        "source_status": evidence.get("status"),
        "extracted_file_count": (
            source.get("extracted_file_count") if isinstance(source, Mapping) else None
        ),
        "source_group_count": len(evidence.get("source_groups", [])),
        "asset_profile_count": len(evidence.get("asset_profiles", [])),
        "admission_blocker_count": len(evidence.get("admission_blockers", [])),
        "source_content_admitted": (
            evidence.get("claims", {}).get("source_content_admitted")
            if isinstance(evidence.get("claims"), Mapping)
            else None
        ),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--source-root", type=Path, required=True)
    snapshot.add_argument("--source-zip", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE_PATH)
    snapshot.add_argument(
        "--research-inventory",
        type=Path,
        default=RESEARCH_INVENTORY_PATH,
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = build_validation_report(args.evidence)
            exit_code = 0 if report["status"] == "valid" else 1
        else:
            report = build_evidence(
                source_root=args.source_root,
                source_zip=args.source_zip,
                research_inventory_path=args.research_inventory,
            )
            errors = validate_evidence(report)
            if errors:
                raise ChongqingRealSourceAdmissionError("; ".join(errors))
            _write_json(args.output, report)
            exit_code = 0
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return exit_code
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        ChongqingRealSourceAdmissionError,
    ) as exc:
        print(f"Chongqing real-source admission: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
