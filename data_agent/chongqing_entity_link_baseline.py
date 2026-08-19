"""Version-locked entity/link baseline for the Chongqing customer dataset."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from shapely import __version__ as SHAPELY_VERSION
from shapely import normalize, to_wkb
from shapely.errors import GEOSException
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .entity_link_authority import (
    EntityResolutionMethod,
    EntitySourceBindingDraft,
    InstanceLinkAssertionDraft,
    InstanceLinkKind,
    InstanceLinkLifecycle,
    InstanceLinkMutationKind,
    InstanceLinkReviewStatus,
    InstanceLinkTypeDraft,
)
from .ontology.package_reader import OntologyPackageReader
from .temporal_entity_authority import (
    TemporalEntityAssertionDraft,
    TemporalLifecycleState,
    TemporalMutationKind,
)

CUSTOMER_BUNDLE_DIR = (
    Path(__file__).resolve().parent
    / "demo_data"
    / "natural_resource_ontology_customer_v1"
)
ONTOLOGY_PACKAGE_DIR = (
    Path(__file__).resolve().parent
    / "ontology"
    / "packages"
    / "natural_resource_one_map"
    / "2.3.0"
)

ONTOLOGY_PACKAGE_ID = "natural-resource-one-map:2.3.0:587915868b1221af"
ONTOLOGY_PACKAGE_SHA256 = (
    "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"
)
ONTOLOGY_NAMESPACE = (
    "https://ontology.gis-data-agent.local/natural-resource/one-map/"
)
LAND_PARCEL_CLASS_URI = f"{ONTOLOGY_NAMESPACE}class/LandParcel"
CONTROL_BOUNDARY_CLASS_URI = f"{ONTOLOGY_NAMESPACE}class/ControlBoundary"
SF_INTERSECTS = "http://www.opengis.net/ont/geosparql#sfIntersects"

DEFAULT_TENANT = "chongqing-customer"
DEFAULT_OWNER = "team:natural-resource-governance"
DEFAULT_ACTOR = "agent:chongqing-baseline-builder"
DECISION_SCOPE = "辅助预审，不替代法定审批或行政决定"
TECHNICAL_STATUS = "technical_baseline_unreviewed"
USAGE_STATUS = "assisted_precheck_not_for_production_decision"
BASELINE_SCHEMA_ID = "gda.chongqing-entity-link-baseline.v2"
PRECISION_POLICY = "positive_intersection_area_gt_1e-15_source_crs_units"
MIN_INTERSECTION_AREA_SOURCE_UNITS = 1e-15
SOURCE_COORDINATE_REFERENCE = "RFC7946_default_WGS84_longitude_latitude"


class ChongqingBaselineError(ValueError):
    """The customer data or ontology baseline is inconsistent."""


class ChongqingEntityLinkBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    schema_id: Literal["gda.chongqing-entity-link-baseline.v2"] = (
        "gda.chongqing-entity-link-baseline.v2"
    )
    tenant_id: str
    customer_bundle_id: str
    customer_bundle_version: str
    ontology_package_id: str
    ontology_package_sha256: str
    ontology_review_status: Literal["technical_baseline_unreviewed"]
    usage_status: Literal["assisted_precheck_not_for_production_decision"]
    decision_scope: str
    parcel_record_count: int
    parcel_identity_count: int
    constraint_feature_count: int
    constraint_identity_count: int
    constraint_name_count: int
    constraint_scope_count: int
    link_evidence_observation_count: int
    exact_intersection_observation_count: int
    excluded_precision_sliver_count: int
    precision_policy: Literal[
        "positive_intersection_area_gt_1e-15_source_crs_units"
    ]
    link_identity_count: int
    temporal_entity_drafts: tuple[TemporalEntityAssertionDraft, ...]
    source_binding_drafts: tuple[EntitySourceBindingDraft, ...]
    link_type_draft: InstanceLinkTypeDraft
    link_assertion_drafts: tuple[InstanceLinkAssertionDraft, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChongqingBaselineError(f"cannot read customer artifact {path.name}") from exc
    if not isinstance(value, dict):
        raise ChongqingBaselineError(f"customer artifact {path.name} must be an object")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _document_sha256(document: Any) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _feature_geometry(
    feature: dict[str, Any],
    *,
    artifact_name: str,
    feature_index: int,
) -> BaseGeometry:
    geometry_document = feature.get("geometry")
    if not isinstance(geometry_document, dict):
        raise ChongqingBaselineError(
            f"{artifact_name} feature {feature_index} lacks geometry"
        )
    try:
        geometry = shape(geometry_document)
    except (GEOSException, TypeError, ValueError) as exc:
        raise ChongqingBaselineError(
            f"{artifact_name} feature {feature_index} has invalid geometry"
        ) from exc
    if (
        geometry.is_empty
        or not geometry.is_valid
        or geometry.geom_type not in {"Polygon", "MultiPolygon"}
    ):
        raise ChongqingBaselineError(
            f"{artifact_name} feature {feature_index} must be a valid area geometry"
        )
    return geometry


def _geometry_document_sha256(feature: dict[str, Any]) -> str:
    return _document_sha256(feature["geometry"])


def _intersection_sha256(geometry: BaseGeometry) -> str:
    canonical = normalize(geometry)
    payload = to_wkb(
        canonical,
        hex=False,
        output_dimension=2,
        byte_order=1,
        include_srid=False,
    )
    return hashlib.sha256(payload).hexdigest()


def _source_object_id(value: Any, *, name: str) -> str:
    if isinstance(value, bool) or value is None:
        raise ChongqingBaselineError(f"{name} lacks a stable source identifier")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not value.is_integer():
            raise ChongqingBaselineError(f"{name} source identifier is not integral")
        return str(int(value))
    resolved = str(value).strip()
    if not resolved:
        raise ChongqingBaselineError(f"{name} lacks a stable source identifier")
    return resolved


def _token(prefix: str, *parts: Any) -> str:
    document = json.dumps(
        parts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{prefix}-{hashlib.sha256(document.encode('utf-8')).hexdigest()[:24]}"


def _features(document: dict[str, Any], name: str) -> list[dict[str, Any]]:
    features = document.get("features")
    if document.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ChongqingBaselineError(f"{name} must be a GeoJSON FeatureCollection")
    if any(not isinstance(feature, dict) for feature in features):
        raise ChongqingBaselineError(f"{name} contains a non-object feature")
    return features


def _artifact_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in manifest.get("files") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        digest = str(item.get("sha256") or "")
        if name and Path(name).name == name:
            hashes[name] = digest
    return hashes


def _verify_inputs(
    bundle_dir: Path,
    ontology_package_dir: Path,
) -> tuple[dict[str, Any], dict[str, str], datetime]:
    manifest = _read_json(bundle_dir / "manifest.json")
    bundle = manifest.get("bundle") or {}
    ontology = manifest.get("ontology") or {}
    if bundle.get("id") != "natural-resource-ontology-customer-demo-v1":
        raise ChongqingBaselineError("unexpected Chongqing customer bundle identity")
    if bundle.get("decision_scope") != DECISION_SCOPE:
        raise ChongqingBaselineError("customer bundle decision scope changed")
    if ontology.get("version") != "2.3.0":
        raise ChongqingBaselineError("customer bundle is not pinned to ontology 2.3.0")
    if ontology.get("package_id") != ONTOLOGY_PACKAGE_ID:
        raise ChongqingBaselineError("customer bundle ontology package ID changed")
    if ontology.get("sha256") != ONTOLOGY_PACKAGE_SHA256:
        raise ChongqingBaselineError("customer bundle ontology hash changed")

    artifact_hashes = _artifact_hashes(manifest)
    for name in ("heping_changed_parcels.geojson", "heping_constraints.geojson"):
        expected = artifact_hashes.get(name)
        path = bundle_dir / name
        if expected is None or not path.is_file() or _file_sha256(path) != expected:
            raise ChongqingBaselineError(f"customer artifact hash mismatch: {name}")

    reader = OntologyPackageReader(
        package_dir=ontology_package_dir,
        verify=True,
        ontology_key="natural-resource-one-map",
    )
    if reader.manifest.semantic_version != "2.3.0":
        raise ChongqingBaselineError("ontology package semantic version changed")
    if reader.manifest.package_id != ONTOLOGY_PACKAGE_ID:
        raise ChongqingBaselineError("ontology package ID changed")
    if reader.manifest.content_sha256 != ONTOLOGY_PACKAGE_SHA256:
        raise ChongqingBaselineError("ontology package content hash changed")

    generated_at = datetime.fromisoformat(str(bundle["generated_at"]).replace("Z", "+00:00"))
    if generated_at.tzinfo is None:
        raise ChongqingBaselineError("customer bundle generated_at lacks a timezone")
    return manifest, artifact_hashes, generated_at


def build_chongqing_entity_link_baseline(
    *,
    tenant_id: str = DEFAULT_TENANT,
    bundle_dir: str | Path = CUSTOMER_BUNDLE_DIR,
    ontology_package_dir: str | Path = ONTOLOGY_PACKAGE_DIR,
) -> ChongqingEntityLinkBaseline:
    """Build deterministic entity/link drafts without claiming domain approval."""
    bundle_path = Path(bundle_dir).resolve()
    ontology_path = Path(ontology_package_dir).resolve()
    manifest, artifact_hashes, valid_from = _verify_inputs(
        bundle_path,
        ontology_path,
    )

    parcels_document = _read_json(bundle_path / "heping_changed_parcels.geojson")
    constraints_document = _read_json(bundle_path / "heping_constraints.geojson")
    parcel_features = _features(parcels_document, "heping_changed_parcels.geojson")
    constraint_features = _features(constraints_document, "heping_constraints.geojson")

    constraint_names: set[tuple[str, str]] = set()
    constraint_metadata: dict[int, dict[str, Any]] = {}
    constraint_indexes_by_name: dict[tuple[str, str], list[int]] = defaultdict(list)
    constraint_source_keys: set[tuple[str, str]] = set()
    for feature_index, feature in enumerate(constraint_features):
        properties = feature.get("properties") or {}
        layer = str(properties.get("layer") or "").strip()
        name = str(properties.get("GZMC") or "").strip()
        if not layer or not name:
            raise ChongqingBaselineError("constraint feature lacks layer or GZMC")
        source_object_id = _source_object_id(
            properties.get("BSM"),
            name=f"constraint feature {feature_index}",
        )
        source_key = (layer, source_object_id)
        if source_key in constraint_source_keys:
            raise ChongqingBaselineError("constraint layer and BSM are not unique")
        constraint_source_keys.add(source_key)
        geometry = _feature_geometry(
            feature,
            artifact_name="heping_constraints.geojson",
            feature_index=feature_index,
        )
        ontology_class = str(properties.get("ontology_class") or "").strip()
        if not ontology_class:
            raise ChongqingBaselineError("constraint feature lacks ontology_class")
        ontology_class_uri = f"{ONTOLOGY_NAMESPACE}class/{ontology_class}"
        entity_token = _token("constraint-feature", layer, source_object_id)
        constraint_metadata[feature_index] = {
            "feature_index": feature_index,
            "layer": layer,
            "name": name,
            "source_object_id": source_object_id,
            "source_key": source_key,
            "entity_token": entity_token,
            "ontology_class_uri": ontology_class_uri,
            "geometry": geometry,
            "geometry_type": geometry.geom_type,
            "geometry_bounds": [round(value, 12) for value in geometry.bounds],
            "geometry_sha256": _geometry_document_sha256(feature),
            "constraint_type": str(properties.get("constraint_type") or "").strip(),
            "rule": str(properties.get("rule") or "").strip(),
            "severity": str(properties.get("severity") or "").strip(),
            "jasm_area_ha": properties.get("JSMJ"),
        }
        constraint_names.add((layer, name))
        constraint_indexes_by_name[(layer, name)].append(feature_index)

    parcel_records: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    scope_metadata: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    link_observations: dict[
        tuple[str, int],
        list[dict[str, Any]],
    ] = defaultdict(list)
    excluded_precision_slivers: list[dict[str, Any]] = []
    customer_observation_count = 0

    for feature_index, feature in enumerate(parcel_features):
        properties = feature.get("properties") or {}
        parcel_id = str(properties.get("parcel_id") or "").strip()
        evidence = properties.get("evidence") or {}
        hits = evidence.get("constraint_hits") or []
        if not parcel_id or not isinstance(hits, list) or not hits:
            raise ChongqingBaselineError(
                f"parcel feature {feature_index} lacks identity or constraint evidence"
            )
        parcel_records[parcel_id].append((feature_index, properties))
        parcel_geometry = _feature_geometry(
            feature,
            artifact_name="heping_changed_parcels.geojson",
            feature_index=feature_index,
        )
        parcel_geometry_sha256 = _geometry_document_sha256(feature)
        exact_intersections: dict[int, BaseGeometry] = {}
        for constraint_index, metadata in constraint_metadata.items():
            try:
                intersection = parcel_geometry.intersection(metadata["geometry"])
            except GEOSException as exc:
                raise ChongqingBaselineError(
                    "cannot intersect customer parcel and constraint geometry"
                ) from exc
            if intersection.is_empty or intersection.area <= 0:
                continue
            if intersection.area <= MIN_INTERSECTION_AREA_SOURCE_UNITS:
                excluded_precision_slivers.append(
                    {
                        "parcel_feature_index": feature_index,
                        "parcel_id": parcel_id,
                        "constraint_feature_index": constraint_index,
                        "constraint_layer": metadata["layer"],
                        "constraint_source_object_id": metadata["source_object_id"],
                        "intersection_area_source_units": intersection.area,
                    }
                )
                continue
            exact_intersections[constraint_index] = intersection

        represented_intersections: set[int] = set()
        for hit_index, hit in enumerate(hits):
            if not isinstance(hit, dict):
                raise ChongqingBaselineError("constraint hit must be an object")
            customer_observation_count += 1
            layer = str(hit.get("layer") or "").strip()
            names = tuple(
                sorted(
                    {
                        str(name).strip()
                        for name in hit.get("names") or []
                        if str(name).strip()
                    }
                )
            )
            if not layer or not names:
                raise ChongqingBaselineError("constraint hit lacks layer or names")
            if any((layer, name) not in constraint_names for name in names):
                raise ChongqingBaselineError("constraint hit is absent from customer constraints")
            scope_key = (layer, names)
            ontology = hit.get("ontology") or {}
            class_uri = str(ontology.get("uri") or "").strip()
            if not class_uri.startswith(ONTOLOGY_NAMESPACE):
                raise ChongqingBaselineError("constraint hit uses an unpinned ontology URI")
            metadata = {
                "layer": layer,
                "names": names,
                "label": str(hit.get("label") or "").strip(),
                "rule": str(hit.get("rule") or "").strip(),
                "severity": str(hit.get("severity") or "").strip(),
                "ontology_class_uri": class_uri,
            }
            existing_metadata = scope_metadata.setdefault(scope_key, metadata)
            if existing_metadata != metadata:
                raise ChongqingBaselineError("constraint scope has inconsistent semantics")
            candidate_indexes = sorted(
                constraint_index
                for name in names
                for constraint_index in constraint_indexes_by_name[(layer, name)]
                if constraint_index in exact_intersections
            )
            if not candidate_indexes:
                raise ChongqingBaselineError(
                    "customer constraint hit does not map to an exact geometry feature"
                )
            if represented_intersections.intersection(candidate_indexes):
                raise ChongqingBaselineError(
                    "an exact geometry intersection maps to multiple customer hits"
                )
            represented_intersections.update(candidate_indexes)
            candidate_refs = [
                (
                    f"gda://{tenant_id}/entity/"
                    f"{constraint_metadata[index]['entity_token']}"
                )
                for index in candidate_indexes
            ]
            for constraint_index in candidate_indexes:
                constraint = constraint_metadata[constraint_index]
                intersection = exact_intersections[constraint_index]
                link_observations[(parcel_id, constraint_index)].append(
                    {
                        "parcel_feature_index": feature_index,
                        "hit_index": hit_index,
                        "parcel_id": parcel_id,
                        "parcel_geometry_sha256": parcel_geometry_sha256,
                        "constraint_feature_index": constraint_index,
                        "constraint_layer": constraint["layer"],
                        "constraint_name": constraint["name"],
                        "constraint_source_object_id": constraint["source_object_id"],
                        "constraint_geometry_sha256": constraint["geometry_sha256"],
                        "intersection_geometry_sha256": _intersection_sha256(
                            intersection
                        ),
                        "intersection_area_source_units": round(
                            intersection.area,
                            18,
                        ),
                        "customer_scope_names": list(names),
                        "customer_scope_candidate_entity_refs": candidate_refs,
                        "customer_scope_candidate_count": len(candidate_indexes),
                        "customer_scope_intersection_area_ha": hit.get(
                            "intersection_area_ha"
                        ),
                        "customer_scope_area_allocation": (
                            "direct_single_feature"
                            if len(candidate_indexes) == 1
                            else "scope_total_not_allocated_per_feature"
                        ),
                        "rule": hit.get("rule"),
                        "severity": hit.get("severity"),
                        "review_status": properties.get("review_status"),
                    }
                )
        unrepresented = sorted(set(exact_intersections) - represented_intersections)
        if unrepresented:
            raise ChongqingBaselineError(
                "exact geometry intersections are absent from customer hit evidence"
            )

    parcel_version_ref = (
        f"gda://{tenant_id}/resource_version/"
        f"heping-changed-parcels-{artifact_hashes['heping_changed_parcels.geojson'][:16]}"
    )
    constraint_version_ref = (
        f"gda://{tenant_id}/resource_version/"
        f"heping-constraints-{artifact_hashes['heping_constraints.geojson'][:16]}"
    )
    parcel_system_ref = f"gda://{tenant_id}/resource/heping-changed-parcels"
    constraint_system_ref = f"gda://{tenant_id}/resource/heping-constraints"
    owner = DEFAULT_OWNER
    actor = DEFAULT_ACTOR

    temporal_drafts: list[TemporalEntityAssertionDraft] = []
    binding_drafts: list[EntitySourceBindingDraft] = []
    parcel_entity_refs: dict[str, str] = {}
    for parcel_id in sorted(parcel_records):
        rows = parcel_records[parcel_id]
        entity_token = _token("parcel", parcel_id)
        entity_ref = f"gda://{tenant_id}/entity/{entity_token}"
        parcel_entity_refs[parcel_id] = entity_ref
        target_codes = sorted({str(row[1].get("GHDLDM") or "") for row in rows})
        temporal_drafts.append(
            TemporalEntityAssertionDraft(
                tenant_id=tenant_id,
                entity_ref=entity_ref,
                object_type="natural_resource.land_parcel",
                lifecycle_state=TemporalLifecycleState.ACTIVE,
                attributes={
                    "parcel_id": parcel_id,
                    "bsm": rows[0][1].get("BSM"),
                    "tbbh": rows[0][1].get("TBBH"),
                    "record_count": len(rows),
                    "feature_indexes": [row[0] for row in rows],
                    "target_land_use_codes": target_codes,
                    "total_area_ha": round(
                        sum(float(row[1].get("area_ha") or 0.0) for row in rows),
                        12,
                    ),
                    "ontology_class_uri": LAND_PARCEL_CLASS_URI,
                },
                valid_from=valid_from,
                source_version_refs=(parcel_version_ref,),
                mutation_kind=TemporalMutationKind.INITIAL,
                idempotency_key=f"cq.parcel.{entity_token}.initial",
                owner_subject=owner,
                recorded_by=actor,
                reason="register Chongqing customer parcel identity",
            )
        )
        binding_drafts.append(
            EntitySourceBindingDraft(
                tenant_id=tenant_id,
                source_identity_ref=(
                    f"gda://{tenant_id}/source_identity/{entity_token}"
                ),
                source_system_ref=parcel_system_ref,
                source_object_type="natural_resource.land_parcel",
                source_object_id=parcel_id,
                entity_ref=entity_ref,
                entity_object_type="natural_resource.land_parcel",
                ontology_class_uri=LAND_PARCEL_CLASS_URI,
                source_version_ref=parcel_version_ref,
                valid_from=valid_from,
                resolution_method=EntityResolutionMethod.AUTHORITATIVE_IDENTIFIER,
                confidence_basis_points=10_000,
                evidence={
                    "artifact": "heping_changed_parcels.geojson",
                    "artifact_sha256": artifact_hashes[
                        "heping_changed_parcels.geojson"
                    ],
                    "identity_field": "parcel_id",
                    "record_count": len(rows),
                },
                idempotency_key=f"cq.source.{entity_token}.v1",
                owner_subject=owner,
                recorded_by=actor,
                reason="bind customer parcel identifier to stable entity",
            )
        )

    constraint_entity_refs: dict[int, str] = {}
    for constraint_index in sorted(constraint_metadata):
        metadata = constraint_metadata[constraint_index]
        layer = metadata["layer"]
        name = metadata["name"]
        entity_token = metadata["entity_token"]
        entity_ref = f"gda://{tenant_id}/entity/{entity_token}"
        constraint_entity_refs[constraint_index] = entity_ref
        source_object_id = json.dumps(
            {"BSM": metadata["source_object_id"], "layer": layer},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        scope_class_uris = {
            scope["ontology_class_uri"]
            for (scope_layer, scope_names), scope in scope_metadata.items()
            if scope_layer == layer and name in scope_names
        }
        if scope_class_uris and scope_class_uris != {metadata["ontology_class_uri"]}:
            raise ChongqingBaselineError(
                "constraint feature ontology class conflicts with customer hit evidence"
            )
        temporal_drafts.append(
            TemporalEntityAssertionDraft(
                tenant_id=tenant_id,
                entity_ref=entity_ref,
                object_type="natural_resource.constraint_feature",
                lifecycle_state=TemporalLifecycleState.ACTIVE,
                attributes={
                    "source_feature_index": constraint_index,
                    "layer": layer,
                    "bsm": metadata["source_object_id"],
                    "name": name,
                    "constraint_type": metadata["constraint_type"],
                    "rule": metadata["rule"],
                    "severity": metadata["severity"],
                    "jasm_area_ha": metadata["jasm_area_ha"],
                    "ontology_class_uri": metadata["ontology_class_uri"],
                    "identity_semantics": "layer_plus_BSM",
                    "geometry_type": metadata["geometry_type"],
                    "geometry_bounds": metadata["geometry_bounds"],
                    "geometry_sha256": metadata["geometry_sha256"],
                    "source_coordinate_reference": SOURCE_COORDINATE_REFERENCE,
                },
                valid_from=valid_from,
                source_version_refs=(constraint_version_ref,),
                mutation_kind=TemporalMutationKind.INITIAL,
                idempotency_key=f"cq.constraint.{entity_token}.initial",
                owner_subject=owner,
                recorded_by=actor,
                reason="register exact customer constraint feature identity",
            )
        )
        binding_drafts.append(
            EntitySourceBindingDraft(
                tenant_id=tenant_id,
                source_identity_ref=(
                    f"gda://{tenant_id}/source_identity/{entity_token}"
                ),
                source_system_ref=constraint_system_ref,
                source_object_type="natural_resource.constraint_feature",
                source_object_id=source_object_id,
                entity_ref=entity_ref,
                entity_object_type="natural_resource.constraint_feature",
                ontology_class_uri=metadata["ontology_class_uri"],
                source_version_ref=constraint_version_ref,
                valid_from=valid_from,
                resolution_method=EntityResolutionMethod.AUTHORITATIVE_COMPOSITE_KEY,
                confidence_basis_points=10_000,
                evidence={
                    "artifact": "heping_constraints.geojson",
                    "artifact_sha256": artifact_hashes[
                        "heping_constraints.geojson"
                    ],
                    "identity_fields": ["layer", "BSM"],
                    "source_feature_index": constraint_index,
                    "geometry_sha256": metadata["geometry_sha256"],
                },
                idempotency_key=f"cq.source.{entity_token}.v2",
                owner_subject=owner,
                recorded_by=actor,
                reason="bind exact customer constraint feature to stable entity",
            )
        )

    link_type_ref = (
        f"gda://{tenant_id}/link_type/geosparql-sfintersects-constraint-feature-v2"
    )
    link_type = InstanceLinkTypeDraft(
        tenant_id=tenant_id,
        link_type_ref=link_type_ref,
        predicate_uri=SF_INTERSECTS,
        link_kind=InstanceLinkKind.SPATIAL,
        source_object_type="natural_resource.land_parcel",
        target_object_type="natural_resource.constraint_feature",
        source_ontology_class_uri=LAND_PARCEL_CLASS_URI,
        target_ontology_class_uri=CONTROL_BOUNDARY_CLASS_URI,
        ontology_package_id=ONTOLOGY_PACKAGE_ID,
        ontology_package_sha256=ONTOLOGY_PACKAGE_SHA256,
        ontology_review_status=(
            InstanceLinkReviewStatus.TECHNICAL_BASELINE_UNREVIEWED
        ),
        directed=True,
        allow_self=False,
        owner_subject=owner,
        created_by=actor,
        reason="register exact feature-level customer spatial relation baseline",
    )

    link_drafts: list[InstanceLinkAssertionDraft] = []
    source_versions = tuple(sorted((parcel_version_ref, constraint_version_ref)))
    for parcel_id, constraint_index in sorted(link_observations):
        observations = sorted(
            link_observations[(parcel_id, constraint_index)],
            key=lambda item: (item["parcel_feature_index"], item["hit_index"]),
        )
        constraint = constraint_metadata[constraint_index]
        link_token = _token(
            "intersects-feature",
            parcel_id,
            constraint["layer"],
            constraint["source_object_id"],
        )
        link_drafts.append(
            InstanceLinkAssertionDraft(
                tenant_id=tenant_id,
                link_ref=f"gda://{tenant_id}/entity_link/{link_token}",
                link_type_ref=link_type_ref,
                source_entity_ref=parcel_entity_refs[parcel_id],
                target_entity_ref=constraint_entity_refs[constraint_index],
                lifecycle_state=InstanceLinkLifecycle.ACTIVE,
                attributes={
                    "predicate_uri": SF_INTERSECTS,
                    "constraint_feature_index": constraint_index,
                    "constraint_layer": constraint["layer"],
                    "constraint_bsm": constraint["source_object_id"],
                    "constraint_name": constraint["name"],
                    "constraint_geometry_sha256": constraint["geometry_sha256"],
                    "target_semantics": "exact_constraint_feature",
                    "observation_count": len(observations),
                },
                valid_from=valid_from,
                source_version_refs=source_versions,
                mutation_kind=InstanceLinkMutationKind.INITIAL,
                confidence_basis_points=9_000,
                evidence={
                    "evidence_kind": (
                        "customer_hit_reconciled_to_exact_geometry_feature"
                    ),
                    "observations": observations,
                    "precision_policy": PRECISION_POLICY,
                    "minimum_intersection_area_source_units": (
                        MIN_INTERSECTION_AREA_SOURCE_UNITS
                    ),
                    "source_coordinate_reference": SOURCE_COORDINATE_REFERENCE,
                    "topology_engine": f"shapely-{SHAPELY_VERSION}",
                    "scope_area_allocation_policy": (
                        "preserve_customer_scope_total_without_synthetic_feature_split"
                    ),
                    "ontology_review_status": TECHNICAL_STATUS,
                    "decision_scope": DECISION_SCOPE,
                },
                idempotency_key=f"cq.link.{link_token}.v2.initial",
                owner_subject=owner,
                recorded_by=actor,
                reason="record exact customer parcel-to-constraint-feature intersection",
            )
        )

    exact_observation_count = sum(len(value) for value in link_observations.values())
    bundle = manifest["bundle"]
    return ChongqingEntityLinkBaseline(
        tenant_id=tenant_id,
        customer_bundle_id=bundle["id"],
        customer_bundle_version=bundle["version"],
        ontology_package_id=ONTOLOGY_PACKAGE_ID,
        ontology_package_sha256=ONTOLOGY_PACKAGE_SHA256,
        ontology_review_status=TECHNICAL_STATUS,
        usage_status=USAGE_STATUS,
        decision_scope=DECISION_SCOPE,
        parcel_record_count=len(parcel_features),
        parcel_identity_count=len(parcel_records),
        constraint_feature_count=len(constraint_features),
        constraint_identity_count=len(constraint_metadata),
        constraint_name_count=len(constraint_names),
        constraint_scope_count=len(scope_metadata),
        link_evidence_observation_count=customer_observation_count,
        exact_intersection_observation_count=exact_observation_count,
        excluded_precision_sliver_count=len(excluded_precision_slivers),
        precision_policy=PRECISION_POLICY,
        link_identity_count=len(link_drafts),
        temporal_entity_drafts=tuple(temporal_drafts),
        source_binding_drafts=tuple(binding_drafts),
        link_type_draft=link_type,
        link_assertion_drafts=tuple(link_drafts),
    )
