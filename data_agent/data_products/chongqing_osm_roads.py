"""Real Chongqing OSM roads product: standardize, validate, and publish."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import inspect, text

from data_agent.data_product_registry import (
    DataProductNotFoundError,
    DataProductRegistry,
    DataProductSpec,
    DataProductVersionSpec,
    data_product_manifest_fingerprint,
)
from data_agent.db_engine import get_engine
from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    LineageEvent,
    LineageEventType,
    Resource,
    ResourceVersion,
    canonical_json_bytes,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import GatewayNotFoundError, PlatformGateway
from data_agent.standards_platform.application.acceptance import (
    bundle_identity,
    profile_vector_dataset,
    sha256_file,
)
from data_agent.standards_platform.application.contracts import (
    StandardDataElement,
    propose_standard_mapping,
)

TENANT_ID = "local-dev"
PRODUCT_SLUG = "chongqing-osm-roads"
PRODUCT_URN = f"gda://{TENANT_ID}/data_product/{PRODUCT_SLUG}"
SOURCE_URN = f"gda://{TENANT_ID}/dataset/chongqing-osm-roads-source"
OUTPUT_URN = f"gda://{TENANT_ID}/dataset/chongqing-osm-roads-standardized"
STANDARD_VERSION_REF = "gda://local-dev/standard/osm-road-core:v1"
QUALITY_RULE_VERSION = "gda.cq.osm-roads.quality.v1"
PUBLISHER = "workload:chongqing-osm-roads-product-builder"
MAPPING_APPROVER = "workload:approved-standard-profile"
SOURCE_VINTAGE = 2021
LICENSE_ID = "ODbL-1.0"
ATTRIBUTION = "OpenStreetMap contributors"
LICENSE_URL = "https://www.openstreetmap.org/copyright"
TARGET_TABLE = "road_segment"

FIELD_DEFINITIONS = (
    ("road_id", "道路标识码", "string", "mandatory", ("osm_id",)),
    ("road_class_code", "道路分类代码", "integer", "mandatory", ("code",)),
    ("road_class", "道路分类", "string", "mandatory", ("fclass",)),
    ("road_name", "道路名称", "string", "optional", ("name",)),
    ("route_ref", "路线编号", "string", "optional", ("ref",)),
    ("travel_direction", "通行方向", "string", "mandatory", ("oneway",)),
    ("max_speed_kph", "最高速度", "integer", "optional", ("maxspeed",)),
    ("layer_level", "道路层级", "integer", "mandatory", ("layer",)),
    ("is_bridge", "是否桥梁", "boolean", "mandatory", ("bridge",)),
    ("is_tunnel", "是否隧道", "boolean", "mandatory", ("tunnel",)),
)
EXPECTED_MAPPING = {aliases[0]: target for target, _, _, _, aliases in FIELD_DEFINITIONS}


class ProductQualityError(RuntimeError):
    """Full-dataset quality did not pass, so publication is blocked."""


def build_and_publish(
    *,
    source_path: Path,
    output_root: Path,
    version_key: str = "v1.0.0",
    published_at: datetime | None = None,
    publication_profile: str = "lightweight",
    object_materializer=None,
    gateway: PlatformGateway | None = None,
    registry: DataProductRegistry | None = None,
    run_id: UUID | None = None,
    definition_version_id: UUID | None = None,
    quality_evaluator: str | None = None,
) -> dict[str, Any]:
    """Create the first governed product version from the real source bundle."""
    if publication_profile not in {"lightweight", "lightweight_layered"}:
        raise ValueError(
            "publication_profile must be lightweight or lightweight_layered"
        )
    if (run_id is None) != (definition_version_id is None):
        raise ValueError(
            "run_id and definition_version_id must be supplied together"
        )
    evidence_actor = quality_evaluator or PUBLISHER
    if quality_evaluator is not None and not quality_evaluator.startswith("workload:"):
        raise ValueError("quality_evaluator must use workload identity")
    source = source_path.resolve(strict=True)
    target_dir = output_root.resolve() / PRODUCT_SLUG / version_key
    target_dir.mkdir(parents=True, exist_ok=True)
    report_path = target_dir / "quality-and-standardization-report.json"
    timestamp = _publication_timestamp(report_path, published_at)

    source_identity = bundle_identity(source)
    source_profile, source_fields = profile_vector_dataset(source)
    standard_elements = _standard_elements()
    proposal = propose_standard_mapping(
        source_fields=source_fields,
        standard_version_id=STANDARD_VERSION_REF,
        elements=standard_elements,
        target_table=TARGET_TABLE,
        recommendation_threshold=0.80,
        review_threshold=0.58,
        ambiguity_margin=0.08,
    )
    _require_unambiguous_mapping(proposal)

    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import MultiLineString

    raw = gpd.read_file(source)
    standardized = gpd.GeoDataFrame(
        {
            "road_id": raw["osm_id"].astype(str),
            "road_class_code": raw["code"].astype("int64"),
            "road_class": _optional_text(raw["fclass"]),
            "road_name": _optional_text(raw["name"]),
            "route_ref": _optional_text(raw["ref"]),
            "travel_direction": raw["oneway"].map(
                {"B": "both", "F": "forward", "T": "reverse"}
            ),
            "max_speed_kph": pd.to_numeric(raw["maxspeed"], errors="coerce")
            .replace(0, pd.NA)
            .astype("Int64"),
            "layer_level": raw["layer"].astype("int64"),
            "is_bridge": raw["bridge"].map({"T": True, "F": False}),
            "is_tunnel": raw["tunnel"].map({"T": True, "F": False}),
            "source_vintage": SOURCE_VINTAGE,
        },
        geometry=raw.geometry.map(
            lambda geometry: MultiLineString([geometry])
            if geometry is not None and geometry.geom_type == "LineString"
            else geometry
        ),
        crs=raw.crs,
    ).sort_values("road_id", kind="stable", ignore_index=True)

    semantic_sha256 = _semantic_fingerprint(standardized)
    output_path = target_dir / f"chongqing-osm-roads-{semantic_sha256[:12]}.geojson"
    _write_canonical_geojson(standardized, output_path)
    output_file_sha256 = sha256_file(output_path)
    quality_contract = _quality_contract(raw, standardized, source_profile)
    if quality_contract["verdict"] != "passed":
        blocked_report = _report(
            timestamp=timestamp,
            source_identity=source_identity,
            source_profile=source_profile,
            proposal=proposal,
            mapping_contract=_mapping_contract(proposal),
            quality_contract=quality_contract,
            semantic_sha256=semantic_sha256,
            output_path=output_path,
            product_version_id=None,
            publication_status="blocked",
            run_id=run_id,
            definition_version_id=definition_version_id,
        )
        _write_report(report_path, blocked_report)
        raise ProductQualityError(
            "full-dataset quality failed; no DataProductVersion was created"
        )

    source_version_id = uuid5(
        NAMESPACE_URL,
        f"{SOURCE_URN}@sha256:{source_identity['bundle_sha256']}",
    )
    output_version_id = uuid5(NAMESPACE_URL, f"{OUTPUT_URN}@sha256:{semantic_sha256}")
    product_version_id = uuid5(
        NAMESPACE_URL,
        f"{PRODUCT_URN}@{version_key}:sha256:{semantic_sha256}",
    )
    output_artifact_id = (
        uuid5(output_version_id, "artifact:canonical-geojson")
        if version_key == "v1.0.0"
        else uuid5(product_version_id, "artifact:canonical-geojson")
    )
    quality_artifact_id = uuid5(product_version_id, f"quality:{QUALITY_RULE_VERSION}")
    mapping_contract = _mapping_contract(proposal)
    postgis_table = f"chongqing_osm_roads_{semantic_sha256[:12]}"
    _materialize_postgis(standardized, postgis_table)

    platform_gateway = gateway or PlatformGateway()
    product_registry = registry or DataProductRegistry()
    product_created_at, predecessor_version_id = _publication_context(
        product_registry, version_key, timestamp
    )
    source_registration = _register_source(
        platform_gateway, source_identity, source_profile, source_version_id, timestamp
    )
    output_registration = _register_output(
        platform_gateway,
        semantic_sha256,
        output_version_id,
        postgis_table,
        timestamp,
    )
    layered = None
    if publication_profile == "lightweight_layered":
        from data_agent.data_products.layered_osm_roads import (
            build_layered_publication,
        )

        layered = build_layered_publication(
            source_path=source,
            target_dir=target_dir,
            raw_frame=raw,
            standardized_frame=standardized,
            source_identity=source_identity,
            source_version_id=source_version_id,
            output_resource_urn=OUTPUT_URN,
            output_version_id=output_version_id,
            product_version_id=product_version_id,
            version_key=version_key,
            semantic_sha256=semantic_sha256,
            output_path=output_path,
            timestamp=timestamp,
            gateway=platform_gateway,
            materializer=object_materializer,
            run_id=run_id,
            definition_version_id=definition_version_id,
        )

    report = _report(
        timestamp=timestamp,
        source_identity=source_identity,
        source_profile=source_profile,
        proposal=proposal,
        mapping_contract=mapping_contract,
        quality_contract=quality_contract,
        semantic_sha256=semantic_sha256,
        output_path=output_path,
        product_version_id=product_version_id,
        publication_status="approved",
        layered_manifest=layered["manifest"] if layered else None,
        run_id=run_id,
        definition_version_id=definition_version_id,
    )
    _write_report(report_path, report)
    report_file_sha256 = sha256_file(report_path)
    distribution: dict[str, Any] = {
        "schema": (
            "gda.data_product_distribution.v2"
            if layered
            else "gda.data_product_distribution.v1"
        ),
        "formats": [
            {
                "kind": "GeoJSON",
                "media_type": "application/geo+json",
                "artifact_id": str(output_artifact_id),
                "content_sha256": output_file_sha256,
                "size_bytes": output_path.stat().st_size,
                "download_path": f"/api/data-products/{PRODUCT_SLUG}/download",
            },
            {
                "kind": "PostGIS",
                "schema": "data_products",
                "table": postgis_table,
                "geometry_column": "geometry",
                "srid": 4326,
                "feature_count": len(standardized),
                "features_path": f"/api/data-products/{PRODUCT_SLUG}/features",
            },
        ],
        "map_path": f"/data-products/{PRODUCT_SLUG}",
    }
    if layered:
        distribution["profile"] = publication_profile
        layers = layered["manifest"]["chain"]
        ads_layer = next(item for item in layers if item["stage"] == "ads")
        stac = layered["manifest"]["stac"]
        distribution["layers"] = layers
        distribution["layer_checks"] = layered["manifest"]["checks"]
        distribution["layer_manifest_sha256"] = layered["manifest"][
            "manifest_sha256"
        ]
        distribution["stac"] = stac
        distribution["formats"].extend(
            [
                {
                    "kind": "S3GeoJSON",
                    "media_type": ads_layer["media_type"],
                    "artifact_id": ads_layer["artifact_id"],
                    "content_sha256": ads_layer["physical_sha256"],
                    "size_bytes": ads_layer["size_bytes"],
                    "storage_uri": ads_layer["storage_uri"],
                },
                {
                    "kind": "STAC",
                    "media_type": "application/geo+json",
                    "artifact_id": stac["item_artifact_id"],
                    "item_path": stac["item_path"],
                    "storage_uri": stac["item_href"],
                },
            ]
        )
    if run_id is not None:
        distribution["orchestration"] = {
            "schema": "gda.data_product_run_binding.v1",
            "run_id": str(run_id),
            "definition_version_id": str(definition_version_id),
        }
    output_artifact_registration = platform_gateway.record_artifact(
        Artifact(
            tenant_id=TENANT_ID,
            artifact_id=output_artifact_id,
            artifact_key=(
                f"cq_osm_roads_geojson_{semantic_sha256[:12]}"
                if version_key == "v1.0.0"
                else f"cq_osm_roads_geojson_{version_key.replace('.', '_')}_{semantic_sha256[:12]}"
            ),
            artifact_role=ArtifactRole.OUTPUT,
            storage_uri=output_path.as_uri(),
            media_type="application/geo+json",
            content_sha256=output_file_sha256,
            size_bytes=output_path.stat().st_size,
            run_id=run_id,
            resource_version_id=output_version_id,
            manifest={
                "schema": "gda.canonical_geojson.v1",
                "semantic_sha256": semantic_sha256,
                "feature_count": len(standardized),
                "crs": "EPSG:4326",
            },
            created_by=PUBLISHER,
            created_at=timestamp,
        )
    )
    quality_artifact_registration = platform_gateway.record_artifact(
        Artifact(
            tenant_id=TENANT_ID,
            artifact_id=quality_artifact_id,
            artifact_key=(
                f"cq_osm_roads_quality_{semantic_sha256[:12]}"
                if version_key == "v1.0.0"
                else f"cq_osm_roads_quality_{version_key.replace('.', '_')}_{semantic_sha256[:12]}"
            ),
            artifact_role=ArtifactRole.EVIDENCE,
            storage_uri=report_path.as_uri(),
            media_type="application/json",
            content_sha256=report_file_sha256,
            size_bytes=report_path.stat().st_size,
            run_id=run_id,
            resource_version_id=output_version_id,
            manifest={
                "schema": report["schema"],
                "evidence_sha256": report["evidence_sha256"],
                "rule_version": QUALITY_RULE_VERSION,
                "verdict": "passed",
            },
            created_by=evidence_actor,
            created_at=timestamp,
        )
    )
    lineage_created = False
    if not layered:
        lineage_event_id = uuid5(
            output_version_id, f"derive:{source_version_id}:{semantic_sha256}"
        )
        lineage_facets = {
            "schema": "gda.data_product_lineage.v1",
            "standard_version_ref": STANDARD_VERSION_REF,
            "mapping_sha256": mapping_contract["mapping_sha256"],
            "quality_rule_version": QUALITY_RULE_VERSION,
            "quality_evidence_artifact_id": str(quality_artifact_id),
            "source_bundle_sha256": source_identity["bundle_sha256"],
            "output_semantic_sha256": semantic_sha256,
        }
        lineage_created = platform_gateway.record_lineage(
            LineageEvent(
                tenant_id=TENANT_ID,
                lineage_event_id=lineage_event_id,
                event_type=LineageEventType.PUBLISH,
                source_resource_version_id=source_version_id,
                target_resource_version_id=output_version_id,
                run_id=run_id,
                definition_version_id=definition_version_id,
                artifact_id=output_artifact_id,
                producer=PUBLISHER,
                event_sha256=canonical_json_fingerprint(lineage_facets),
                facets=lineage_facets,
                occurred_at=timestamp,
            )
        ).created

    product = DataProductSpec(
        tenant_id=TENANT_ID,
        product_urn=PRODUCT_URN,
        product_slug=PRODUCT_SLUG,
        title="重庆市 OSM 道路网络",
        description="经标准映射和全量质量门禁发布的重庆市道路网络数据产品。",
        domain="transportation",
        owner_ref="team:data-platform",
        governance_ref={
            "classification": "public",
            "visibility": "public",
            "license_id": LICENSE_ID,
            "license_url": LICENSE_URL,
            "attribution": ATTRIBUTION,
            "business_steward": "team:spatial-data-governance",
        },
        created_at=product_created_at,
    )
    version_payload = {
        "tenant_id": TENANT_ID,
        "data_product_version_id": product_version_id,
        "product_urn": PRODUCT_URN,
        "version_key": version_key,
        "predecessor_version_id": predecessor_version_id,
        "source_resource_version_id": source_version_id,
        "output_resource_version_id": output_version_id,
        "standard_version_ref": STANDARD_VERSION_REF,
        "mapping_contract": mapping_contract,
        "quality_contract": quality_contract,
        "quality_evidence_artifact_id": quality_artifact_id,
        "distribution_manifest": distribution,
        "published_by": PUBLISHER,
        "published_at": timestamp,
    }
    version_payload["manifest_sha256"] = data_product_manifest_fingerprint(version_payload)
    version = DataProductVersionSpec.model_validate(version_payload)
    publication = product_registry.publish(
        product,
        version,
        idempotency_key=f"publish:{version_key}:{semantic_sha256}",
        reason="real Chongqing OSM roads passed standardization and full quality gates",
    )
    registrations = {
        "source_resource_created": source_registration[0],
        "source_version_created": source_registration[1],
        "output_resource_created": output_registration[0],
        "output_version_created": output_registration[1],
        "output_artifact_created": output_artifact_registration.created,
        "quality_artifact_created": quality_artifact_registration.created,
        "lineage_created": lineage_created,
        "data_product_created": publication["product_created"],
        "data_product_version_created": publication["version_created"],
        "current_pointer_changed": publication["pointer_changed"],
    }
    if layered:
        registrations.update(layered["registrations"])
    return {
        "schema": "gda.chongqing_osm_roads_publication_receipt.v1",
        "product_slug": PRODUCT_SLUG,
        "product_urn": PRODUCT_URN,
        "version_key": version_key,
        "publication_profile": publication_profile,
        "predecessor_version_id": (
            str(predecessor_version_id) if predecessor_version_id else None
        ),
        "data_product_version_id": str(product_version_id),
        "feature_count": len(standardized),
        "quality_verdict": quality_contract["verdict"],
        "mapping": mapping_contract["summary"],
        "semantic_sha256": semantic_sha256,
        "source_bundle_sha256": source_identity["bundle_sha256"],
        "postgis_table": f"data_products.{postgis_table}",
        "source_resource_version_id": str(source_version_id),
        "output_resource_version_id": str(output_version_id),
        "output_artifact_id": str(output_artifact_id),
        "quality_evidence_artifact_id": str(quality_artifact_id),
        "published_at": timestamp.isoformat(),
        "run_id": str(run_id) if run_id else None,
        "definition_version_id": (
            str(definition_version_id) if definition_version_id else None
        ),
        "map_path": distribution["map_path"],
        "api_path": f"/api/data-products/{PRODUCT_SLUG}",
        "layered_manifest": layered["manifest"] if layered else None,
        "registrations": registrations,
        "idempotent": not any(registrations.values()),
    }


def _publication_context(
    registry: DataProductRegistry,
    version_key: str,
    fallback_timestamp: datetime,
) -> tuple[datetime, UUID | None]:
    try:
        product = registry.get_product(TENANT_ID, PRODUCT_SLUG)
    except DataProductNotFoundError:
        return fallback_timestamp, None
    created_at = datetime.fromisoformat(
        str(product["created_at"]).replace("Z", "+00:00")
    ).astimezone(UTC)
    existing = next(
        (item for item in product["versions"] if item["version_key"] == version_key),
        None,
    )
    if existing is not None:
        predecessor = existing.get("predecessor_version_id")
        return created_at, UUID(predecessor) if predecessor else None
    return created_at, UUID(product["current_version_id"])


def _resource_version_timestamp(
    gateway: PlatformGateway,
    version_id: UUID,
    fallback_timestamp: datetime,
) -> datetime:
    try:
        return gateway.get_resource_version(TENANT_ID, version_id).created_at
    except GatewayNotFoundError:
        return fallback_timestamp


def _standard_elements() -> tuple[StandardDataElement, ...]:
    return tuple(
        StandardDataElement(
            id=str(uuid5(NAMESPACE_URL, f"{STANDARD_VERSION_REF}:{target}")),
            document_version_id=STANDARD_VERSION_REF,
            code=target.upper(),
            name_zh=name_zh,
            datatype=datatype,
            obligation=obligation,
            bound_table=TARGET_TABLE,
            bound_column=target,
            aliases=aliases,
        )
        for target, name_zh, datatype, obligation, aliases in FIELD_DEFINITIONS
    )


def _require_unambiguous_mapping(proposal: dict[str, Any]) -> None:
    if proposal["mapping"] != EXPECTED_MAPPING:
        raise ProductQualityError(
            "intelligent mapping was ambiguous or incomplete; publication is blocked"
        )
    if proposal["summary"]["recommended"] != len(EXPECTED_MAPPING):
        raise ProductQualityError("not every source field received a recommended mapping")
    if any(proposal["summary"][key] for key in ("review_required", "unmatched", "conflicts")):
        raise ProductQualityError("mapping proposal still contains unresolved decisions")


def _mapping_contract(proposal: dict[str, Any]) -> dict[str, Any]:
    decisions = [
        {
            "source_field": item["source_field"],
            "target_field": item["candidates"][0]["target_field"],
            "confidence": item["candidates"][0]["confidence"],
            "match_method": item["candidates"][0]["match_method"],
            "matched_on": item["candidates"][0]["evidence"]["matched_on"],
            "decision": "approved",
        }
        for item in proposal["proposals"]
    ]
    contract = {
        "schema": "gda.approved_standard_mapping.v1",
        "standard_version_ref": STANDARD_VERSION_REF,
        "target_table": TARGET_TABLE,
        "source_profile_hash": proposal["source_profile_hash"],
        "mapping": proposal["mapping"],
        "decisions": decisions,
        "approval": {
            "status": "approved",
            "mode": "approved_profile_policy",
            "approved_by": MAPPING_APPROVER,
            "policy": "all fields exact-alias, type-compatible and unambiguous",
            "automatic_authoritative_write": False,
        },
        "summary": {
            "source_fields": proposal["summary"]["source_fields"],
            "mapped_fields": len(proposal["mapping"]),
            "review_required": proposal["summary"]["review_required"],
            "unmatched": proposal["summary"]["unmatched"],
            "conflicts": proposal["summary"]["conflicts"],
            "minimum_confidence": min(item["confidence"] for item in decisions),
        },
    }
    contract["mapping_sha256"] = canonical_json_fingerprint(contract)
    return contract


def _quality_contract(raw, standardized, source_profile: dict[str, Any]) -> dict[str, Any]:
    bounds = [round(float(value), 6) for value in standardized.total_bounds]
    speeds = standardized["max_speed_kph"].dropna()
    checks = [
        _check("source_nonempty", len(raw) > 0, {"records": len(raw)}),
        _check(
            "row_count_preserved",
            len(raw) == len(standardized),
            {"source_records": len(raw), "output_records": len(standardized)},
        ),
        _check(
            "crs_is_wgs84",
            source_profile["crs"] == "EPSG:4326" and standardized.crs.to_string() == "EPSG:4326",
            {"source_crs": source_profile["crs"], "output_crs": standardized.crs.to_string()},
        ),
        _check(
            "geometry_valid_complete",
            int(standardized.geometry.isna().sum()) == 0
            and int(standardized.geometry.is_empty.sum()) == 0
            and int((~standardized.geometry.is_valid).sum()) == 0,
            {
                "null": int(standardized.geometry.isna().sum()),
                "empty": int(standardized.geometry.is_empty.sum()),
                "invalid": int((~standardized.geometry.is_valid).sum()),
                "types": {
                    str(key): int(value)
                    for key, value in standardized.geometry.geom_type.value_counts().items()
                },
            },
        ),
        _check(
            "road_id_unique_complete",
            int(standardized["road_id"].isna().sum()) == 0
            and int(standardized["road_id"].duplicated(keep=False).sum()) == 0,
            {
                "null": int(standardized["road_id"].isna().sum()),
                "duplicate_rows": int(
                    standardized["road_id"].duplicated(keep=False).sum()
                ),
                "distinct": int(standardized["road_id"].nunique()),
            },
        ),
        _check(
            "mandatory_semantics_complete",
            all(
                int(standardized[field].isna().sum()) == 0
                for field in (
                    "road_class_code",
                    "road_class",
                    "travel_direction",
                    "layer_level",
                    "is_bridge",
                    "is_tunnel",
                )
            ),
            {
                field: int(standardized[field].isna().sum())
                for field in (
                    "road_class_code",
                    "road_class",
                    "travel_direction",
                    "layer_level",
                    "is_bridge",
                    "is_tunnel",
                )
            },
        ),
        _check(
            "controlled_values_valid",
            set(standardized["travel_direction"].dropna().unique())
            <= {"both", "forward", "reverse"}
            and bool(((speeds > 0) & (speeds <= 130)).all()),
            {
                "travel_direction_values": sorted(
                    str(value) for value in standardized["travel_direction"].unique()
                ),
                "known_speed_count": int(len(speeds)),
                "unknown_speed_count": int(standardized["max_speed_kph"].isna().sum()),
                "minimum_known_speed": int(speeds.min()) if len(speeds) else None,
                "maximum_known_speed": int(speeds.max()) if len(speeds) else None,
            },
        ),
        _check(
            "chongqing_extent_plausible",
            105.0 <= bounds[0] <= bounds[2] <= 111.0
            and 28.0 <= bounds[1] <= bounds[3] <= 33.0,
            {"bounds": bounds},
        ),
        _check(
            "license_and_attribution_present",
            bool(LICENSE_ID and ATTRIBUTION and LICENSE_URL),
            {
                "license_id": LICENSE_ID,
                "attribution": ATTRIBUTION,
                "license_url": LICENSE_URL,
            },
        ),
    ]
    verdict = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    contract = {
        "schema": "gda.data_product_quality.v1",
        "rule_version": QUALITY_RULE_VERSION,
        "mode": "full_dataset",
        "records_scanned": len(standardized),
        "verdict": verdict,
        "checks": checks,
        "summary": {
            "passed": sum(check["status"] == "passed" for check in checks),
            "failed": sum(check["status"] == "failed" for check in checks),
            "optional_name_nulls": int(standardized["road_name"].isna().sum()),
            "optional_route_ref_nulls": int(standardized["route_ref"].isna().sum()),
        },
    }
    contract["quality_sha256"] = canonical_json_fingerprint(contract)
    return contract


def _check(check_id: str, passed: bool, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "passed" if passed else "failed",
        "severity": "critical",
        "metrics": metrics,
    }


def _optional_text(series):
    stripped = series.astype("string").str.strip()
    return stripped.mask(stripped.eq(""))


def _semantic_fingerprint(frame) -> str:
    digest = hashlib.sha256()
    property_columns = [column for column in frame.columns if column != frame.geometry.name]
    for row in frame.itertuples(index=False, name=None):
        properties = {
            column: _json_ready(value)
            for column, value in zip(property_columns, row[:-1], strict=True)
        }
        digest.update(canonical_json_bytes(properties))
        digest.update(b"\0")
        digest.update(row[-1].wkb)
        digest.update(b"\n")
    return digest.hexdigest()


def _write_canonical_geojson(frame, path: Path) -> None:
    from shapely.geometry import mapping

    property_columns = [column for column in frame.columns if column != frame.geometry.name]
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write('{"type":"FeatureCollection","name":"chongqing-osm-roads",')
        stream.write('"crs":{"type":"name","properties":{"name":"urn:ogc:def:crs:OGC:1.3:CRS84"}},')
        stream.write('"features":[')
        for index, row in enumerate(frame.itertuples(index=False, name=None)):
            if index:
                stream.write(",")
            feature = {
                "type": "Feature",
                "id": str(row[0]),
                "properties": {
                    column: _json_ready(value)
                    for column, value in zip(property_columns, row[:-1], strict=True)
                },
                "geometry": mapping(row[-1]),
            }
            stream.write(
                json.dumps(
                    feature,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        stream.write("]}")
    if path.is_file():
        if sha256_file(temporary) != sha256_file(path):
            temporary.unlink()
            raise RuntimeError("immutable GeoJSON path is already bound to different bytes")
        temporary.unlink()
    else:
        temporary.replace(path)


def _materialize_postgis(frame, table_name: str) -> None:
    engine = get_engine()
    if engine is None or engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL is required for product materialization")
    if inspect(engine).has_table(table_name, schema="data_products"):
        with engine.connect() as connection:
            observed = connection.execute(
                text(
                    f"""
                    SELECT count(*) AS records,
                           count(DISTINCT road_id) AS distinct_ids,
                           count(*) FILTER (
                               WHERE geometry IS NULL OR ST_IsEmpty(geometry)
                                  OR NOT ST_IsValid(geometry)
                           ) AS invalid_geometries
                      FROM data_products."{table_name}"
                    """
                )
            ).mappings().one()
        if (
            int(observed["records"]) != len(frame)
            or int(observed["distinct_ids"]) != len(frame)
            or int(observed["invalid_geometries"]) != 0
        ):
            raise RuntimeError("existing immutable PostGIS projection failed verification")
        return
    frame.to_postgis(
        table_name,
        engine,
        schema="data_products",
        if_exists="fail",
        index=False,
        chunksize=2000,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                f'CREATE UNIQUE INDEX "{table_name}_road_id_idx" '
                f'ON data_products."{table_name}" (road_id)'
            )
        )
        connection.execute(
            text(
                f'CREATE INDEX "{table_name}_geometry_gix" '
                f'ON data_products."{table_name}" USING GIST (geometry)'
            )
        )


def _register_source(
    gateway: PlatformGateway,
    identity: dict[str, Any],
    profile: dict[str, Any],
    version_id: UUID,
    timestamp: datetime,
) -> tuple[bool, bool]:
    resource = gateway.register_resource(
        Resource(
            tenant_id=TENANT_ID,
            resource_urn=SOURCE_URN,
            resource_kind="dataset",
            authority_system="source-archive",
            authority_locator=f"sha256:{identity['bundle_sha256']}",
            owner_ref="team:data-platform",
            governance_ref={
                "classification": "public",
                "license_id": LICENSE_ID,
                "license_url": LICENSE_URL,
                "attribution": ATTRIBUTION,
            },
            technical_refs=(
                {
                    "kind": "shapefile_bundle",
                    "feature_count": profile["feature_count"],
                    "crs": profile["crs"],
                },
            ),
        )
    )
    version_timestamp = _resource_version_timestamp(gateway, version_id, timestamp)
    version = gateway.register_resource_version(
        ResourceVersion(
            tenant_id=TENANT_ID,
            resource_urn=SOURCE_URN,
            resource_version_id=version_id,
            version_key=f"sha256-{identity['bundle_sha256'][:12]}",
            content_sha256=identity["bundle_sha256"],
            authority_version_ref={
                "bundle_sha256": identity["bundle_sha256"],
                "members": [
                    {
                        "name": member["name"],
                        "sha256": member["sha256"],
                        "size_bytes": member["size_bytes"],
                    }
                    for member in identity["members"]
                ],
                "source_vintage": SOURCE_VINTAGE,
            },
            created_by=PUBLISHER,
            created_at=version_timestamp,
        )
    )
    return resource.created, version.created


def _register_output(
    gateway: PlatformGateway,
    semantic_sha256: str,
    version_id: UUID,
    postgis_table: str,
    timestamp: datetime,
) -> tuple[bool, bool]:
    resource = gateway.register_resource(
        Resource(
            tenant_id=TENANT_ID,
            resource_urn=OUTPUT_URN,
            resource_kind="dataset",
            authority_system="gis-data-agent",
            authority_locator=f"product:{PRODUCT_URN}",
            owner_ref="team:data-platform",
            governance_ref={
                "classification": "public",
                "standard_version_ref": STANDARD_VERSION_REF,
                "license_id": LICENSE_ID,
                "attribution": ATTRIBUTION,
            },
            technical_refs=({"kind": "postgis", "schema": "data_products"},),
        )
    )
    version_timestamp = _resource_version_timestamp(gateway, version_id, timestamp)
    version = gateway.register_resource_version(
        ResourceVersion(
            tenant_id=TENANT_ID,
            resource_urn=OUTPUT_URN,
            resource_version_id=version_id,
            version_key=f"sha256-{semantic_sha256[:12]}",
            content_sha256=semantic_sha256,
            authority_version_ref={
                "semantic_sha256": semantic_sha256,
                "postgis_table": f"data_products.{postgis_table}",
                "standard_version_ref": STANDARD_VERSION_REF,
            },
            created_by=PUBLISHER,
            created_at=version_timestamp,
        )
    )
    return resource.created, version.created


def _report(
    *,
    timestamp: datetime,
    source_identity: dict[str, Any],
    source_profile: dict[str, Any],
    proposal: dict[str, Any],
    mapping_contract: dict[str, Any],
    quality_contract: dict[str, Any],
    semantic_sha256: str,
    output_path: Path,
    product_version_id: UUID | None,
    publication_status: str,
    layered_manifest: dict[str, Any] | None = None,
    run_id: UUID | None = None,
    definition_version_id: UUID | None = None,
) -> dict[str, Any]:
    report = {
        "schema": "gda.chongqing_osm_roads_evidence.v1",
        "evaluated_at": timestamp.isoformat(),
        "source": {
            "bundle": source_identity,
            "profile": source_profile,
            "license_id": LICENSE_ID,
            "license_url": LICENSE_URL,
            "attribution": ATTRIBUTION,
        },
        "standardization": {
            "proposal_schema": proposal["schema"],
            "mapping_contract": mapping_contract,
            "output_semantic_sha256": semantic_sha256,
            "output_name": output_path.name,
        },
        "quality": quality_contract,
        "publication": {
            "status": publication_status,
            "product_urn": PRODUCT_URN,
            "data_product_version_id": str(product_version_id)
            if product_version_id
            else None,
            "gate_policy": "create DataProductVersion only when every critical check passes",
        },
    }
    if layered_manifest is not None:
        report["lakehouse"] = layered_manifest
        report["schema"] = "gda.chongqing_osm_roads_evidence.v2"
    if run_id is not None:
        report["orchestration"] = {
            "schema": "gda.data_product_run_binding.v1",
            "run_id": str(run_id),
            "definition_version_id": str(definition_version_id),
        }
    report["evidence_sha256"] = canonical_json_fingerprint(report)
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    payload = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if path.is_file():
        if path.read_bytes() != payload:
            raise RuntimeError("immutable evidence path is already bound to different bytes")
        return
    path.write_bytes(payload)


def _publication_timestamp(path: Path, value: datetime | None) -> datetime:
    if value is not None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must include a timezone")
        return value.astimezone(UTC)
    if path.is_file():
        previous = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(previous["evaluated_at"].replace("Z", "+00:00")).astimezone(
            UTC
        )
    return datetime.now(UTC)


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if value == value else None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if type(value).__name__ == "NAType":
        return None
    if hasattr(value, "item"):
        return _json_ready(value.item())
    return str(value)
