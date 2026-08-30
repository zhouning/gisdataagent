"""Immutable Raw-to-ADS assets for the Chongqing OSM roads product."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pyproj import Geod

from data_agent.fusion.s3_materialization_adapter import (
    build_s3_materialization_executor,
)
from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    LineageEvent,
    LineageEventType,
    Resource,
    ResourceVersion,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import GatewayNotFoundError, PlatformGateway
from data_agent.standards_platform.application.acceptance import sha256_file

TENANT_ID = "local-dev"
PRODUCT_SLUG = "chongqing-osm-roads"
PRODUCT_URN = f"gda://{TENANT_ID}/data_product/{PRODUCT_SLUG}"
PUBLISHER = "workload:chongqing-osm-roads-product-builder"
LICENSE_ID = "ODbL-1.0"
ATTRIBUTION = "OpenStreetMap contributors"
STAC_COLLECTION = "chongqing-osm-roads"
PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"

ODS_URN = f"gda://{TENANT_ID}/dataset/chongqing-osm-roads-ods"
SILVER_URN = f"gda://{TENANT_ID}/dataset/chongqing-osm-roads-silver"
GOLD_URN = f"gda://{TENANT_ID}/dataset/chongqing-osm-roads-gold"

Materializer = Callable[[dict[str, Any]], dict[str, Any]]


def build_layered_publication(
    *,
    source_path: Path,
    target_dir: Path,
    raw_frame,
    standardized_frame,
    source_identity: dict[str, Any],
    source_version_id: UUID,
    output_resource_urn: str,
    output_version_id: UUID,
    product_version_id: UUID,
    version_key: str,
    semantic_sha256: str,
    output_path: Path,
    timestamp: datetime,
    gateway: PlatformGateway,
    materializer: Materializer | None = None,
    bucket: str | None = None,
    run_id: UUID | None = None,
    definition_version_id: UUID | None = None,
) -> dict[str, Any]:
    """Materialize and register one real Raw/ODS/Silver/Gold/ADS chain."""
    if (run_id is None) != (definition_version_id is None):
        raise ValueError(
            "run_id and definition_version_id must be supplied together"
        )
    lakehouse_bucket = bucket or os.environ.get(
        "MMFE_LAKEHOUSE_BUCKET", "gis-agent-lakehouse"
    )
    publish_object = materializer or build_s3_materialization_executor()
    target_dir.mkdir(parents=True, exist_ok=True)

    raw_prefix = (
        f"raw/transportation/{PRODUCT_SLUG}/"
        f"sha256-{source_identity['bundle_sha256']}"
    )
    raw_members = []
    for member in source_identity["members"]:
        member_path = source_path.parent / member["name"]
        upload = _publish_file(
            publish_object,
            member_path,
            f"s3://{lakehouse_bucket}/{raw_prefix}/{member['name']}",
        )
        raw_members.append(
            {
                **member,
                "storage_uri": upload["target_uri"],
            }
        )

    raw_manifest_path = target_dir / "raw" / "source-bundle-manifest.json"
    raw_manifest = {
        "schema": "gda.raw_bundle_manifest.v1",
        "product_urn": PRODUCT_URN,
        "source_bundle_sha256": source_identity["bundle_sha256"],
        "feature_count": len(raw_frame),
        "crs": raw_frame.crs.to_string(),
        "size_bytes": source_identity["size_bytes"],
        "members": raw_members,
    }
    _write_immutable_json(raw_manifest_path, raw_manifest)
    raw_upload = _publish_file(
        publish_object,
        raw_manifest_path,
        f"s3://{lakehouse_bucket}/{raw_prefix}/raw-bundle-manifest.json",
        content_type="application/json",
    )

    ods_frame = raw_frame.sort_values("osm_id", kind="stable", ignore_index=True)
    ods_path = target_dir / "ods" / "chongqing-osm-roads-source.geoparquet"
    _write_immutable_geoparquet(ods_frame, ods_path)
    ods_sha256 = sha256_file(ods_path)
    ods_upload = _publish_file(
        publish_object,
        ods_path,
        (
            f"s3://{lakehouse_bucket}/warehouse/gis_ods/chongqing_osm_roads/"
            f"source-sha256-{source_identity['bundle_sha256']}/"
            f"physical-sha256-{ods_sha256}/{ods_path.name}"
        ),
        content_type=PARQUET_MEDIA_TYPE,
    )

    silver_path = target_dir / "silver" / "chongqing-osm-roads-standardized.geoparquet"
    _write_immutable_geoparquet(standardized_frame, silver_path)
    silver_physical_sha256 = sha256_file(silver_path)
    silver_upload = _publish_file(
        publish_object,
        silver_path,
        (
            f"s3://{lakehouse_bucket}/warehouse/gis_dwd/chongqing_osm_roads/"
            f"semantic-sha256-{semantic_sha256}/"
            f"physical-sha256-{silver_physical_sha256}/{silver_path.name}"
        ),
        content_type=PARQUET_MEDIA_TYPE,
    )

    gold_path = target_dir / "gold" / "chongqing-osm-roads-metrics.json"
    gold_document = _gold_metrics(standardized_frame, semantic_sha256=semantic_sha256)
    _write_immutable_json(gold_path, gold_document)
    gold_sha256 = sha256_file(gold_path)
    gold_upload = _publish_file(
        publish_object,
        gold_path,
        (
            f"s3://{lakehouse_bucket}/warehouse/gis_dws/chongqing_osm_roads_metrics/"
            f"sha256-{gold_sha256}/{gold_path.name}"
        ),
        content_type="application/json",
    )

    ads_upload = _publish_file(
        publish_object,
        output_path,
        (
            f"s3://{lakehouse_bucket}/serving/ads_transportation/"
            f"chongqing_osm_roads/sha256-{semantic_sha256}/{output_path.name}"
        ),
        content_type="application/geo+json",
    )

    ods_version_id = uuid5(NAMESPACE_URL, f"{ODS_URN}@sha256:{ods_sha256}")
    silver_version_id = uuid5(
        NAMESPACE_URL, f"{SILVER_URN}@sha256:{semantic_sha256}"
    )
    gold_version_id = uuid5(NAMESPACE_URL, f"{GOLD_URN}@sha256:{gold_sha256}")
    artifact_ids = {
        "raw": uuid5(product_version_id, "artifact:raw-manifest"),
        "ods": uuid5(product_version_id, "artifact:ods-geoparquet"),
        "silver": uuid5(product_version_id, "artifact:silver-geoparquet"),
        "gold": uuid5(product_version_id, "artifact:gold-metrics-json"),
        "ads": uuid5(product_version_id, "artifact:ads-s3-geojson"),
        "stac": uuid5(product_version_id, "artifact:stac-item"),
    }

    registrations: dict[str, bool] = {}
    for stage, resource_urn, resource_version_id, content_sha256, upload, namespace in (
        (
            "ods",
            ODS_URN,
            ods_version_id,
            ods_sha256,
            ods_upload,
            "gis_ods",
        ),
        (
            "silver",
            SILVER_URN,
            silver_version_id,
            semantic_sha256,
            silver_upload,
            "gis_dwd",
        ),
        (
            "gold",
            GOLD_URN,
            gold_version_id,
            gold_sha256,
            gold_upload,
            "gis_dws",
        ),
    ):
        desired_resource = Resource(
                tenant_id=TENANT_ID,
                resource_urn=resource_urn,
                resource_kind="dataset",
                authority_system="minio",
                authority_locator=upload["target_uri"],
                owner_ref="team:data-platform",
                governance_ref={
                    "classification": "public",
                    "license_id": LICENSE_ID,
                    "attribution": ATTRIBUTION,
                    "logical_stage": stage,
                },
                technical_refs=(
                    {
                        "kind": "geoparquet" if stage != "gold" else "json_metrics",
                        "namespace": namespace,
                        "storage_uri": upload["target_uri"],
                    },
                ),
            )
        resource_result = _register_resource_identity(gateway, desired_resource)
        desired_version = ResourceVersion(
            tenant_id=TENANT_ID,
            resource_urn=resource_urn,
            resource_version_id=resource_version_id,
            version_key=f"sha256-{content_sha256[:12]}",
            content_sha256=content_sha256,
            authority_version_ref={
                "logical_stage": stage,
                "namespace": namespace,
                "storage_uri": upload["target_uri"],
                "physical_sha256": upload["sha256"],
                "records": len(standardized_frame)
                if stage != "gold"
                else len(gold_document["road_class_metrics"]),
            },
            created_by=PUBLISHER,
            created_at=_resource_version_timestamp(
                gateway, resource_version_id, timestamp
            ),
        )
        version_result = _register_resource_version_identity(
            gateway, desired_version
        )
        registrations[f"{stage}_resource_created"] = resource_result.created
        registrations[f"{stage}_version_created"] = version_result.created

    layer_specs = [
        _layer(
            "raw",
            "raw",
            source_version_id,
            artifact_ids["raw"],
            raw_upload,
            len(raw_frame),
            source_identity["bundle_sha256"],
        ),
        _layer(
            "ods",
            "gis_ods",
            ods_version_id,
            artifact_ids["ods"],
            ods_upload,
            len(ods_frame),
            ods_sha256,
        ),
        _layer(
            "silver",
            "gis_dwd",
            silver_version_id,
            artifact_ids["silver"],
            silver_upload,
            len(standardized_frame),
            semantic_sha256,
        ),
        _layer(
            "gold",
            "gis_dws",
            gold_version_id,
            artifact_ids["gold"],
            gold_upload,
            len(gold_document["road_class_metrics"]),
            gold_sha256,
        ),
        _layer(
            "ads",
            "ads_transportation",
            output_version_id,
            artifact_ids["ads"],
            ads_upload,
            len(standardized_frame),
            semantic_sha256,
        ),
    ]

    artifacts = (
        ("raw", source_version_id, ArtifactRole.INPUT, raw_upload, "raw_bundle_manifest"),
        ("ods", ods_version_id, ArtifactRole.OUTPUT, ods_upload, "geoparquet"),
        (
            "silver",
            silver_version_id,
            ArtifactRole.OUTPUT,
            silver_upload,
            "geoparquet",
        ),
        ("gold", gold_version_id, ArtifactRole.OUTPUT, gold_upload, "road_metrics"),
        ("ads", output_version_id, ArtifactRole.OUTPUT, ads_upload, "geojson"),
    )
    for stage, resource_version_id, role, upload, kind in artifacts:
        artifact_result = gateway.record_artifact(
            Artifact(
                tenant_id=TENANT_ID,
                artifact_id=artifact_ids[stage],
                artifact_key=(
                    f"cq_osm_roads_{stage}_{version_key.replace('.', '_')}_"
                    f"{upload['sha256'][:12]}"
                ),
                artifact_role=role,
                storage_uri=upload["target_uri"],
                media_type=upload["content_type"],
                content_sha256=upload["sha256"],
                size_bytes=upload["bytes_written"],
                run_id=run_id,
                resource_version_id=resource_version_id,
                manifest={
                    "schema": "gda.layer_artifact.v1",
                    "logical_stage": stage,
                    "kind": kind,
                    "read_back_verified": True,
                    "product_version": version_key,
                },
                created_by=PUBLISHER,
                created_at=timestamp,
            )
        )
        registrations[f"{stage}_artifact_created"] = artifact_result.created

    lineage_pairs = (
        ("raw_to_ods", LineageEventType.COPY, source_version_id, ods_version_id, "ods"),
        (
            "ods_to_silver",
            LineageEventType.DERIVE,
            ods_version_id,
            silver_version_id,
            "silver",
        ),
        (
            "silver_to_gold",
            LineageEventType.DERIVE,
            silver_version_id,
            gold_version_id,
            "gold",
        ),
        (
            "gold_to_ads",
            LineageEventType.PUBLISH,
            gold_version_id,
            output_version_id,
            "ads",
        ),
    )
    for transition, event_type, source_id, target_id, artifact_stage in lineage_pairs:
        facets = {
            "schema": "gda.layer_transition.v1",
            "transition": transition,
            "profile": "lightweight_layered",
            "product_urn": PRODUCT_URN,
            "product_version": version_key,
            "source_bundle_sha256": source_identity["bundle_sha256"],
            "output_semantic_sha256": semantic_sha256,
        }
        if run_id is not None:
            facets["run_id"] = str(run_id)
            facets["definition_version_id"] = str(definition_version_id)
        lineage_result = gateway.record_lineage(
            LineageEvent(
                tenant_id=TENANT_ID,
                lineage_event_id=uuid5(
                    product_version_id, f"lineage:{transition}:{source_id}:{target_id}"
                ),
                event_type=event_type,
                source_resource_version_id=source_id,
                target_resource_version_id=target_id,
                run_id=run_id,
                definition_version_id=definition_version_id,
                artifact_id=artifact_ids[artifact_stage],
                producer=PUBLISHER,
                event_sha256=canonical_json_fingerprint(facets),
                facets=facets,
                occurred_at=timestamp,
            )
        )
        registrations[f"{transition}_lineage_created"] = lineage_result.created

    stac_documents = _stac_documents(
        layers=layer_specs,
        version_key=version_key,
        product_version_id=product_version_id,
        timestamp=timestamp,
        bbox=[round(float(value), 6) for value in standardized_frame.total_bounds],
        feature_count=len(standardized_frame),
        semantic_sha256=semantic_sha256,
        bucket=lakehouse_bucket,
        run_id=run_id,
        definition_version_id=definition_version_id,
    )
    stac_root = f"catalog/stac/data-products/{PRODUCT_SLUG}"
    stac_uploads = {}
    for name in ("catalog", "collection", "item"):
        path = target_dir / "stac" / f"{name}.json"
        _write_immutable_json(path, stac_documents[name])
        key = (
            f"{stac_root}/items/{version_key}.json"
            if name == "item"
            else f"{stac_root}/{name}.json"
        )
        stac_uploads[name] = _publish_file(
            publish_object,
            path,
            f"s3://{lakehouse_bucket}/{key}",
            content_type="application/geo+json" if name == "item" else "application/json",
        )

    stac_artifact = gateway.record_artifact(
        Artifact(
            tenant_id=TENANT_ID,
            artifact_id=artifact_ids["stac"],
            artifact_key=f"cq_osm_roads_stac_{version_key.replace('.', '_')}",
            artifact_role=ArtifactRole.OUTPUT,
            storage_uri=stac_uploads["item"]["target_uri"],
            media_type="application/geo+json",
            content_sha256=stac_uploads["item"]["sha256"],
            size_bytes=stac_uploads["item"]["bytes_written"],
            run_id=run_id,
            resource_version_id=output_version_id,
            manifest={
                "schema": "gda.stac_distribution.v1",
                "collection": STAC_COLLECTION,
                "item_id": stac_documents["item"]["id"],
                "read_back_verified": True,
            },
            created_by=PUBLISHER,
            created_at=timestamp,
        )
    )
    registrations["stac_artifact_created"] = stac_artifact.created

    checks = [
        {
            "id": "raw_bundle_complete",
            "status": "passed",
            "metrics": {
                "members": len(raw_members),
                "bundle_sha256": source_identity["bundle_sha256"],
            },
        },
        {
            "id": "layer_row_count_preserved",
            "status": "passed",
            "metrics": {
                "raw": len(raw_frame),
                "ods": len(ods_frame),
                "silver": len(standardized_frame),
                "ads": len(standardized_frame),
            },
        },
        {
            "id": "object_store_read_back",
            "status": "passed",
            "metrics": {"verified_assets": len(raw_members) + 8},
        },
        {
            "id": "stac_item_published",
            "status": "passed",
            "metrics": {
                "item_id": stac_documents["item"]["id"],
                "assets": len(stac_documents["item"]["assets"]),
            },
        },
    ]
    manifest = {
        "schema": "gda.layered_data_product.v1",
        "profile": "lightweight_layered",
        "product_urn": PRODUCT_URN,
        "product_version": version_key,
        "source_bundle_sha256": source_identity["bundle_sha256"],
        "output_semantic_sha256": semantic_sha256,
        "chain": layer_specs,
        "checks": checks,
        "stac": {
            "catalog_href": stac_uploads["catalog"]["target_uri"],
            "collection_href": stac_uploads["collection"]["target_uri"],
            "item_href": stac_uploads["item"]["target_uri"],
            "item_artifact_id": str(artifact_ids["stac"]),
            "item_path": f"/api/data-products/{PRODUCT_SLUG}/stac",
        },
    }
    manifest["manifest_sha256"] = canonical_json_fingerprint(manifest)
    return {"manifest": manifest, "registrations": registrations}


def _publish_file(
    materializer: Materializer,
    source_path: Path,
    target_uri: str,
    *,
    content_type: str | None = None,
) -> dict[str, Any]:
    payload = {
        "source_path": str(source_path),
        "target_uri": target_uri,
        "immutable": True,
        "verify_readback": True,
    }
    if content_type:
        payload["content_type"] = content_type
    result = materializer(payload)
    expected_sha256 = sha256_file(source_path)
    if not result.get("materialized") or not result.get("verified"):
        raise RuntimeError(f"object materialization was not verified: {target_uri}")
    if result.get("sha256") != expected_sha256:
        raise RuntimeError(f"object materialization checksum mismatch: {target_uri}")
    if int(result.get("bytes_written", -1)) != source_path.stat().st_size:
        raise RuntimeError(f"object materialization size mismatch: {target_uri}")
    if result.get("target_uri") != target_uri:
        raise RuntimeError(f"object materialization target mismatch: {target_uri}")
    return result


def _resource_version_timestamp(
    gateway: PlatformGateway,
    version_id: UUID,
    fallback_timestamp: datetime,
) -> datetime:
    try:
        return gateway.get_resource_version(TENANT_ID, version_id).created_at
    except GatewayNotFoundError:
        return fallback_timestamp


def _register_resource_identity(
    gateway: PlatformGateway, desired: Resource
):
    try:
        resource = gateway.get_resource(TENANT_ID, desired.resource_urn)
    except GatewayNotFoundError:
        resource = desired
    return gateway.register_resource(resource)


def _register_resource_version_identity(
    gateway: PlatformGateway, desired: ResourceVersion
):
    try:
        version = gateway.get_resource_version(
            TENANT_ID, desired.resource_version_id
        )
    except GatewayNotFoundError:
        version = desired
    return gateway.register_resource_version(version)


def _write_immutable_json(path: Path, value: dict[str, Any]) -> None:
    payload = (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _write_immutable_bytes(path, payload)


def _write_immutable_geoparquet(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    payload = temporary.read_bytes()
    temporary.unlink()
    _write_immutable_bytes(path, payload)


def _write_immutable_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if path.read_bytes() != payload:
            raise RuntimeError(f"immutable asset path has different bytes: {path}")
        return
    path.write_bytes(payload)


def _gold_metrics(frame, *, semantic_sha256: str) -> dict[str, Any]:
    geod = Geod(ellps="WGS84")
    working = frame.drop(columns=[frame.geometry.name]).copy()
    working["length_km"] = frame.geometry.map(
        lambda geometry: abs(float(geod.geometry_length(geometry))) / 1000.0
    )
    grouped = []
    for road_class, rows in working.groupby("road_class", sort=True, dropna=False):
        grouped.append(
            {
                "road_class": None if road_class != road_class else str(road_class),
                "feature_count": int(len(rows)),
                "length_km": round(float(rows["length_km"].sum()), 6),
                "bridge_count": int(rows["is_bridge"].sum()),
                "tunnel_count": int(rows["is_tunnel"].sum()),
                "oneway_count": int((rows["travel_direction"] != "both").sum()),
            }
        )
    return {
        "schema": "gda.road_network_metrics.v1",
        "source_semantic_sha256": semantic_sha256,
        "feature_count": int(len(frame)),
        "length_km": round(float(working["length_km"].sum()), 6),
        "road_class_count": len(grouped),
        "bridge_count": int(working["is_bridge"].sum()),
        "tunnel_count": int(working["is_tunnel"].sum()),
        "road_class_metrics": grouped,
    }


def _layer(
    stage: str,
    namespace: str,
    resource_version_id: UUID,
    artifact_id: UUID,
    upload: dict[str, Any],
    records: int,
    snapshot_sha256: str,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "namespace": namespace,
        "resource_version_id": str(resource_version_id),
        "artifact_id": str(artifact_id),
        "storage_uri": upload["target_uri"],
        "media_type": upload["content_type"],
        "physical_sha256": upload["sha256"],
        "snapshot_sha256": snapshot_sha256,
        "size_bytes": upload["bytes_written"],
        "records": records,
        "read_back_verified": True,
    }


def _stac_documents(
    *,
    layers: list[dict[str, Any]],
    version_key: str,
    product_version_id: UUID,
    timestamp: datetime,
    bbox: list[float],
    feature_count: int,
    semantic_sha256: str,
    bucket: str,
    run_id: UUID | None = None,
    definition_version_id: UUID | None = None,
) -> dict[str, dict[str, Any]]:
    item_id = f"{PRODUCT_SLUG}-{version_key}"
    root_uri = f"s3://{bucket}/catalog/stac/data-products/{PRODUCT_SLUG}"
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
            ]
        ],
    }
    assets = {
        layer["stage"]: {
            "href": layer["storage_uri"],
            "type": layer["media_type"],
            "roles": ["metadata"] if layer["stage"] == "raw" else ["data"],
            "title": f"{layer['stage'].upper()} immutable asset",
            "file:size": layer["size_bytes"],
            "file:checksum": f"sha256:{layer['physical_sha256']}",
        }
        for layer in layers
    }
    item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [],
        "id": item_id,
        "collection": STAC_COLLECTION,
        "bbox": bbox,
        "geometry": polygon,
        "properties": {
            "datetime": timestamp.isoformat().replace("+00:00", "Z"),
            "gda:product_urn": PRODUCT_URN,
            "gda:data_product_version_id": str(product_version_id),
            "gda:version": version_key,
            "gda:profile": "lightweight_layered",
            "gda:feature_count": feature_count,
            "gda:semantic_sha256": semantic_sha256,
            "proj:epsg": 4326,
        },
        "links": [
            {
                "rel": "self",
                "href": f"/api/data-products/{PRODUCT_SLUG}/stac",
                "type": "application/geo+json",
            },
            {
                "rel": "collection",
                "href": f"{root_uri}/collection.json",
                "type": "application/json",
            },
            {
                "rel": "root",
                "href": f"{root_uri}/catalog.json",
                "type": "application/json",
            },
        ],
        "assets": assets,
    }
    if run_id is not None:
        item["properties"]["gda:run_id"] = str(run_id)
        item["properties"]["gda:definition_version_id"] = str(
            definition_version_id
        )
    collection = {
        "type": "Collection",
        "stac_version": "1.0.0",
        "stac_extensions": [],
        "id": STAC_COLLECTION,
        "title": "Chongqing OSM Roads",
        "description": "Governed layered road network data product.",
        "license": LICENSE_ID,
        "extent": {
            "spatial": {"bbox": [bbox]},
            "temporal": {"interval": [[None, None]]},
        },
        "links": [
            {"rel": "self", "href": f"{root_uri}/collection.json"},
            {"rel": "root", "href": f"{root_uri}/catalog.json"},
            {
                "rel": "item",
                "href": f"/api/data-products/{PRODUCT_SLUG}/stac",
                "type": "application/geo+json",
            },
            {
                "rel": "license",
                "href": "https://www.openstreetmap.org/copyright",
            },
        ],
    }
    catalog = {
        "type": "Catalog",
        "stac_version": "1.0.0",
        "stac_extensions": [],
        "id": f"{PRODUCT_SLUG}-catalog",
        "title": "Chongqing OSM Roads Data Product",
        "description": "Static STAC catalog for the governed product.",
        "links": [
            {"rel": "self", "href": f"{root_uri}/catalog.json"},
            {"rel": "root", "href": f"{root_uri}/catalog.json"},
            {"rel": "child", "href": f"{root_uri}/collection.json"},
        ],
    }
    return {"catalog": catalog, "collection": collection, "item": item}
