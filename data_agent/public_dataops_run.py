"""Run a small public Landing through the lightweight DataOps profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, field_validator, model_validator

from .platform_contracts import (
    Artifact,
    FrameworkAttemptObservation,
    FrozenContract,
    LineageEvent,
    PlatformDefinitionVersion,
    PlatformRun,
    QualityResult,
    Resource,
    ResourceBinding,
    ResourceVersion,
    RunSuccessEvidence,
    SubjectContext,
    canonical_json_bytes,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from .platform_gateway import DefinitionRegistration, PlatformGateway
from .public_source_landing import (
    PublicSourceLandingResult,
    _install_immutable_bytes,
    verify_public_source_landing,
)

PUBLIC_DATAOPS_SCHEMA = "gda.public_dataops_run.v1"
DEFINITION_SCHEMA = "gda.public_dataops_definition.v1"
QUALITY_SCHEMA = "gda.public_dataops_quality.v1"
ATTEMPT_SCHEMA = "gda.public_dataops_attempt.v1"
LINEAGE_SCHEMA = "gda.public_dataops_lineage.v1"
QUALITY_RULE_VERSION = "gda://public-open/quality-rule/geojson-v1"
DEFINITION_PUBLISHED_BY = "workload:gda-release"
DEFINITION_PUBLISHED_AT = datetime(2026, 8, 17, tzinfo=UTC)
_DATASET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")

DatasetId = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$"),
]


class PublicDataOpsError(RuntimeError):
    """The public lightweight DataOps run cannot proceed safely."""


class PublicDataOpsRequest(FrozenContract):
    schema_id = "public_dataops_request"

    executor: str
    quality_evaluator: str
    output_dataset_id: DatasetId
    executed_at: datetime
    min_feature_count: int = Field(default=1, ge=1, le=10_000_000)

    @field_validator("executor", "quality_evaluator")
    @classmethod
    def _workload_identity(cls, value: str) -> str:
        if not value.startswith("workload:") or not value.removeprefix("workload:"):
            raise ValueError("DataOps actors must use workload identities")
        return value

    @field_validator("executed_at")
    @classmethod
    def _utc_executed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("executed_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _independent_quality(self) -> PublicDataOpsRequest:
        if self.executor == self.quality_evaluator:
            raise ValueError("quality evaluator must be independent from executor")
        return self


class PublicDataOpsResult(FrozenContract):
    schema_id = PUBLIC_DATAOPS_SCHEMA

    landing: PublicSourceLandingResult
    definition_registration: DefinitionRegistration
    run: PlatformRun
    target_resource: Resource
    target_version: ResourceVersion
    output_artifact: Artifact
    quality_evidence_artifact: Artifact
    quality_result: QualityResult
    lineage_event: LineageEvent
    attempt_observation: FrameworkAttemptObservation
    success_evidence: RunSuccessEvidence
    output_path: str
    quality_path: str
    output_created: bool
    quality_created: bool
    final_run: PlatformRun | None = None
    ledger_completed: bool | None = None

    @model_validator(mode="after")
    def _consistent_bundle(self) -> PublicDataOpsResult:
        tenant = self.landing.registration.resource.tenant_id
        if self.run.tenant_id != tenant:
            raise ValueError("DataOps bundle tenants must match")
        if self.run.orchestration_class.value != "synchronous":
            raise ValueError("public lightweight run must use synchronous orchestration")
        if self.target_resource.tenant_id != tenant:
            raise ValueError("target Resource tenant must match bundle")
        if self.target_resource.resource_urn != self.target_version.resource_urn:
            raise ValueError("target ResourceVersion must bind target Resource")
        if self.target_version.content_sha256 != self.output_artifact.content_sha256:
            raise ValueError("output Artifact must bind target ResourceVersion hash")
        if self.output_artifact.artifact_role.value != "output":
            raise ValueError("DataOps output Artifact must use output role")
        if self.output_artifact.run_id != self.run.run_id:
            raise ValueError("output Artifact must bind the PlatformRun")
        if self.output_artifact.resource_version_id != self.target_version.resource_version_id:
            raise ValueError("output Artifact must bind target ResourceVersion")
        if self.quality_evidence_artifact.artifact_role.value != "evidence":
            raise ValueError("quality Artifact must use evidence role")
        if self.quality_evidence_artifact.run_id != self.run.run_id:
            raise ValueError("quality Artifact must bind the PlatformRun")
        if (
            self.quality_evidence_artifact.resource_version_id
            != self.target_version.resource_version_id
        ):
            raise ValueError("quality Artifact must bind target ResourceVersion")
        if self.quality_result.run_id != self.run.run_id:
            raise ValueError("QualityResult must bind the PlatformRun")
        if self.quality_result.resource_version_id != self.target_version.resource_version_id:
            raise ValueError("QualityResult must bind target ResourceVersion")
        if self.quality_result.evidence_artifact_id != self.quality_evidence_artifact.artifact_id:
            raise ValueError("QualityResult must bind quality Artifact")
        if self.lineage_event.run_id != self.run.run_id:
            raise ValueError("LineageEvent must bind the PlatformRun")
        if self.lineage_event.definition_version_id != self.run.definition_version_id:
            raise ValueError("LineageEvent must bind the definition version")
        if self.lineage_event.target_resource_version_id != self.target_version.resource_version_id:
            raise ValueError("LineageEvent must bind target ResourceVersion")
        if self.lineage_event.artifact_id != self.output_artifact.artifact_id:
            raise ValueError("LineageEvent must bind output Artifact")
        if self.attempt_observation.run_id != self.run.run_id:
            raise ValueError("attempt observation must bind the PlatformRun")
        if self.attempt_observation.framework_kind.value != "legacy":
            raise ValueError("local inline attempt must use legacy framework kind")
        if self.attempt_observation.evidence.get("execution_mode") != "local_inline":
            raise ValueError("local inline attempt evidence is required")
        if self.success_evidence.run_id != self.run.run_id:
            raise ValueError("success evidence must bind the PlatformRun")
        if self.success_evidence.output_artifact_id != self.output_artifact.artifact_id:
            raise ValueError("success evidence must bind output Artifact")
        if self.success_evidence.quality_result_id != self.quality_result.quality_result_id:
            raise ValueError("success evidence must bind QualityResult")
        if self.success_evidence.lineage_event_id != self.lineage_event.lineage_event_id:
            raise ValueError("success evidence must bind LineageEvent")
        if not Path(self.output_path).is_absolute() or not Path(self.quality_path).is_absolute():
            raise ValueError("serving paths must be absolute")
        return self


def _safe_json_document(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicDataOpsError("GeoJSON input is unreadable") from exc
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise PublicDataOpsError("GeoJSON input must be a FeatureCollection")
    return value


def _normalize_features(features: Any) -> list[dict[str, Any]]:
    if not isinstance(features, list):
        raise PublicDataOpsError("GeoJSON features must be an array")
    normalized: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise PublicDataOpsError("GeoJSON features must be Feature objects")
        properties = feature.get("properties")
        if properties is None:
            properties = {}
        if not isinstance(properties, dict):
            raise PublicDataOpsError("GeoJSON feature properties must be objects")
        item: dict[str, Any] = {
            "geometry": feature.get("geometry"),
            "properties": properties,
            "type": "Feature",
        }
        if isinstance(feature.get("id"), (int, str)):
            item["id"] = feature["id"]
        normalized.append(item)
    return normalized


def _safe_extract_zip(payload_path: Path, extraction_root: Path) -> list[Path]:
    extracted: list[Path] = []
    try:
        archive = zipfile.ZipFile(payload_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PublicDataOpsError("Landing ZIP is unreadable") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > 256:
            raise PublicDataOpsError("Landing ZIP has an unsupported entry count")
        total_size = sum(info.file_size for info in infos)
        if total_size > 512 * 1024 * 1024:
            raise PublicDataOpsError("Landing ZIP exceeds the lightweight size limit")
        for info in infos:
            name = PurePosixPath(info.filename)
            if (
                name.is_absolute()
                or not info.filename
                or ".." in name.parts
                or "\\" in info.filename
                or "\x00" in info.filename
                or (info.flag_bits & 0x1)
            ):
                raise PublicDataOpsError("Landing ZIP contains an unsafe entry")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise PublicDataOpsError("Landing ZIP contains a symbolic link")
            destination = extraction_root.joinpath(*name.parts)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o750)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            try:
                with archive.open(info, "r") as source, destination.open("xb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise PublicDataOpsError("Landing ZIP extraction failed") from exc
            extracted.append(destination)
    return extracted


def _read_landing_features(
    payload_path: Path, media_type: str, scratch_root: Path
) -> list[dict[str, Any]]:
    if media_type == "application/geo+json" or payload_path.suffix.lower() in {".json", ".geojson"}:
        return _normalize_features(_safe_json_document(payload_path).get("features"))
    if media_type != "application/zip" and payload_path.suffix.lower() != ".zip":
        raise PublicDataOpsError("lightweight DataOps supports GeoJSON or ZIP input")
    extracted = _safe_extract_zip(payload_path, scratch_root)
    candidates = sorted(
        item for item in extracted if item.suffix.lower() in {".geojson", ".json", ".shp", ".gpkg"}
    )
    if not candidates:
        raise PublicDataOpsError("Landing ZIP contains no supported geospatial dataset")
    candidate = next((item for item in candidates if item.suffix.lower() == ".shp"), candidates[0])
    if candidate.suffix.lower() in {".json", ".geojson"}:
        return _normalize_features(_safe_json_document(candidate).get("features"))
    try:
        import geopandas as gpd

        frame = gpd.read_file(candidate)
    except Exception as exc:
        raise PublicDataOpsError("Landing vector dataset could not be read") from exc
    if frame.crs is None:
        raise PublicDataOpsError("Landing vector dataset has no declared CRS")
    try:
        frame = frame.to_crs("EPSG:4326")
        return _normalize_features(list(frame.iterfeatures(drop_id=True)))
    except Exception as exc:
        raise PublicDataOpsError("Landing vector dataset could not be normalized") from exc


def _quality_metrics(features: list[dict[str, Any]]) -> dict[str, Any]:
    from shapely.geometry import shape

    null_geometry_count = 0
    empty_geometry_count = 0
    invalid_geometry_count = 0
    geometry_types: dict[str, int] = {}
    bbox: list[float] | None = None
    for feature in features:
        geometry = feature.get("geometry")
        if geometry is None:
            null_geometry_count += 1
            continue
        try:
            parsed = shape(geometry)
        except Exception:
            invalid_geometry_count += 1
            continue
        geometry_types[parsed.geom_type] = geometry_types.get(parsed.geom_type, 0) + 1
        if parsed.is_empty:
            empty_geometry_count += 1
        if not parsed.is_valid:
            invalid_geometry_count += 1
        if not parsed.is_empty:
            bounds = parsed.bounds
            if bbox is None:
                bbox = list(bounds)
            else:
                bbox = [
                    min(bbox[0], bounds[0]),
                    min(bbox[1], bounds[1]),
                    max(bbox[2], bounds[2]),
                    max(bbox[3], bounds[3]),
                ]
    return {
        "feature_count": len(features),
        "null_geometry_count": null_geometry_count,
        "empty_geometry_count": empty_geometry_count,
        "invalid_geometry_count": invalid_geometry_count,
        "geometry_types": dict(sorted(geometry_types.items())),
        "bbox_epsg4326": bbox,
    }


def _definition_registration(
    request: PublicDataOpsRequest, landing: PublicSourceLandingResult
) -> DefinitionRegistration:
    tenant = landing.registration.resource.tenant_id
    definition_urn = f"gda://{tenant}/definition/public-geojson-materialize"
    definition_document = {
        "schema": DEFINITION_SCHEMA,
        "operation": "materialize_public_geojson",
        "execution_mode": "local_inline",
        "input_admission_class": "public_open",
        "quality_rule_version": QUALITY_RULE_VERSION,
        "output_media_type": "application/geo+json",
    }
    input_contract = {
        "binding_name": "source",
        "resource_kind": "dataset",
        "media_types": ["application/geo+json", "application/zip"],
        "content_admission": "public_open",
    }
    output_contract = {
        "resource_kind": "dataset",
        "media_type": "application/geo+json",
        "serving_profile": "lightweight",
        "crs": "EPSG:4326",
    }
    definition_sha256 = platform_definition_fingerprint(
        orchestration_class="synchronous",
        capability_id="public.geojson.materialize",
        portability_class="portable",
        definition_document=definition_document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    definition_version_id = uuid5(NAMESPACE_URL, f"{definition_urn}@sha256:{definition_sha256}")
    return DefinitionRegistration(
        resource=Resource(
            tenant_id=tenant,
            resource_urn=definition_urn,
            resource_kind="definition",
            authority_system="gda",
            authority_locator="definition/public-geojson-materialize",
            owner_ref=landing.registration.resource.owner_ref,
            governance_ref={"profile": "public_open_lightweight"},
        ),
        resource_version=ResourceVersion(
            tenant_id=tenant,
            resource_urn=definition_urn,
            resource_version_id=definition_version_id,
            version_key=f"sha256:{definition_sha256[:16]}",
            content_sha256=definition_sha256,
            authority_version_ref={"schema": DEFINITION_SCHEMA, "revision": 1},
            created_by=DEFINITION_PUBLISHED_BY,
            created_at=DEFINITION_PUBLISHED_AT,
        ),
        definition=PlatformDefinitionVersion(
            tenant_id=tenant,
            definition_urn=definition_urn,
            definition_version_id=definition_version_id,
            orchestration_class="synchronous",
            capability_id="public.geojson.materialize",
            portability_class="portable",
            definition_document=definition_document,
            input_contract=input_contract,
            output_contract=output_contract,
            definition_sha256=definition_sha256,
        ),
    )


def materialize_public_dataops(
    landing: PublicSourceLandingResult,
    request: PublicDataOpsRequest,
    *,
    serving_root: Path,
) -> PublicDataOpsResult:
    """Materialize, quality-check, and build an idempotent control bundle."""
    verify_public_source_landing(landing)
    if landing.registration.resource.tenant_id != landing.registration.artifact.tenant_id:
        raise PublicDataOpsError("Landing tenant binding is invalid")
    if serving_root.is_symlink():
        raise PublicDataOpsError("serving root cannot be a symbolic link")
    serving_root = serving_root.resolve()
    serving_root.mkdir(parents=True, exist_ok=True, mode=0o750)
    staging_root = serving_root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="public-dataops-", dir=staging_root) as scratch:
        features = _read_landing_features(
            Path(landing.payload_path), landing.registration.artifact.media_type, Path(scratch)
        )
    metrics = _quality_metrics(features)
    if (
        metrics["feature_count"] < request.min_feature_count
        or metrics["null_geometry_count"]
        or metrics["empty_geometry_count"]
        or metrics["invalid_geometry_count"]
    ):
        raise PublicDataOpsError(f"GeoJSON quality gate failed: {metrics}")
    normalized = {"features": features, "type": "FeatureCollection"}
    output_bytes = canonical_json_bytes(normalized) + b"\n"
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    target_urn = (
        f"gda://{landing.registration.resource.tenant_id}/dataset/{request.output_dataset_id}"
    )
    target_version_id = uuid5(NAMESPACE_URL, f"{target_urn}@sha256:{output_sha256}")
    definition_registration = _definition_registration(request, landing)
    run_id = uuid5(
        NAMESPACE_URL,
        f"{definition_registration.resource_version.resource_version_id}:run:"
        f"{landing.registration.resource_version.resource_version_id}:{request.output_dataset_id}",
    )
    output_root = (
        serving_root
        / landing.registration.resource.tenant_id
        / request.output_dataset_id
        / "sha256"
        / output_sha256
    )
    output_path = output_root / "data.geojson"
    output_created = _install_immutable_bytes(output_path, output_bytes)
    target_resource = Resource(
        tenant_id=landing.registration.resource.tenant_id,
        resource_urn=target_urn,
        resource_kind="dataset",
        authority_system="gda_lightweight_serving",
        authority_locator=f"{landing.registration.resource.tenant_id}/{request.output_dataset_id}",
        owner_ref=landing.registration.resource.owner_ref,
        governance_ref={
            "profile": "public_open_lightweight",
            "source_resource_urn": landing.registration.resource.resource_urn,
            "production_ready": False,
        },
    )
    target_version = ResourceVersion(
        tenant_id=target_resource.tenant_id,
        resource_urn=target_urn,
        resource_version_id=target_version_id,
        version_key=f"sha256:{output_sha256[:16]}",
        content_sha256=output_sha256,
        authority_version_ref={
            "authority_system": "gda_lightweight_serving",
            "object_key": output_path.relative_to(serving_root).as_posix(),
            "source_resource_version_id": str(
                landing.registration.resource_version.resource_version_id
            ),
        },
        created_by=request.executor,
        created_at=request.executed_at,
    )
    run = PlatformRun(
        tenant_id=target_resource.tenant_id,
        run_id=run_id,
        definition_version_id=definition_registration.resource_version.resource_version_id,
        orchestration_class="synchronous",
        subject_context=SubjectContext(
            tenant_id=target_resource.tenant_id,
            subject_id=request.executor.removeprefix("workload:"),
            subject_type="workload",
            roles=("platform_operator",),
            purpose="materialize public Landing into lightweight GeoJSON serving",
        ),
        input_bindings=(
            ResourceBinding(
                binding_name="source",
                resource_version_id=landing.registration.resource_version.resource_version_id,
                semantic_type="geo.public_source",
            ),
        ),
        idempotency_key=f"public-geojson:{landing.registration.resource_version.resource_version_id}:{request.output_dataset_id}",
        config_fingerprint=canonical_json_fingerprint(
            {
                "min_feature_count": request.min_feature_count,
                "quality_rule_version": QUALITY_RULE_VERSION,
            }
        ),
        submitted_at=request.executed_at,
    )
    output_manifest = {
        "schema": "gda.public_dataops_output.v1",
        "run_id": str(run_id),
        "source_resource_version_id": str(
            landing.registration.resource_version.resource_version_id
        ),
        "target_resource_version_id": str(target_version_id),
        "content_sha256": output_sha256,
        "size_bytes": len(output_bytes),
        "feature_count": metrics["feature_count"],
        "crs": "EPSG:4326",
        "profile": "public_open_lightweight",
        "production_ready": False,
    }
    output_artifact_id = uuid5(NAMESPACE_URL, f"{run_id}:output:{output_sha256}")
    output_artifact = Artifact(
        tenant_id=run.tenant_id,
        artifact_id=output_artifact_id,
        artifact_key=f"public-geojson-output:{request.output_dataset_id}:{output_sha256[:12]}",
        artifact_role="output",
        storage_uri=output_path.as_uri(),
        media_type="application/geo+json",
        content_sha256=output_sha256,
        size_bytes=len(output_bytes),
        run_id=run_id,
        resource_version_id=target_version_id,
        manifest=output_manifest,
        created_by=request.executor,
        created_at=request.executed_at,
    )
    quality_metrics = {**metrics, "output_sha256": output_sha256, "crs": "EPSG:4326"}
    quality_result_id = uuid5(NAMESPACE_URL, f"{run_id}:quality:{output_sha256}")
    quality_document = {
        "schema": QUALITY_SCHEMA,
        "run_id": str(run_id),
        "resource_version_id": str(target_version_id),
        "rule_version_ref": QUALITY_RULE_VERSION,
        "verdict": "passed",
        "metrics": quality_metrics,
        "evaluated_by": request.quality_evaluator,
        "evaluated_at": request.executed_at.isoformat().replace("+00:00", "Z"),
    }
    quality_bytes = canonical_json_bytes(quality_document) + b"\n"
    quality_sha256 = hashlib.sha256(quality_bytes).hexdigest()
    quality_path = (
        serving_root
        / landing.registration.resource.tenant_id
        / request.output_dataset_id
        / "evidence"
        / "sha256"
        / quality_sha256
        / "quality.json"
    )
    quality_created = _install_immutable_bytes(quality_path, quality_bytes)
    quality_artifact_id = uuid5(NAMESPACE_URL, f"{run_id}:quality-artifact:{quality_sha256}")
    quality_artifact = Artifact(
        tenant_id=run.tenant_id,
        artifact_id=quality_artifact_id,
        artifact_key=f"public-geojson-quality:{request.output_dataset_id}:{quality_sha256[:12]}",
        artifact_role="evidence",
        storage_uri=quality_path.as_uri(),
        media_type="application/vnd.gda.public-dataops-quality+json",
        content_sha256=quality_sha256,
        size_bytes=len(quality_bytes),
        run_id=run_id,
        resource_version_id=target_version_id,
        manifest=quality_document,
        created_by=request.quality_evaluator,
        created_at=request.executed_at,
    )
    quality_result = QualityResult(
        tenant_id=run.tenant_id,
        quality_result_id=quality_result_id,
        run_id=run_id,
        resource_version_id=target_version_id,
        rule_version_ref=QUALITY_RULE_VERSION,
        verdict="passed",
        metrics=quality_metrics,
        evidence_artifact_id=quality_artifact_id,
        result_sha256=quality_result_fingerprint(
            tenant_id=run.tenant_id,
            run_id=run_id,
            resource_version_id=target_version_id,
            rule_version_ref=QUALITY_RULE_VERSION,
            verdict="passed",
            metrics=quality_metrics,
            evidence_artifact_id=quality_artifact_id,
            evaluated_by=request.quality_evaluator,
            evaluated_at=request.executed_at,
        ),
        evaluated_by=request.quality_evaluator,
        evaluated_at=request.executed_at,
    )
    lineage_event_id = uuid5(NAMESPACE_URL, f"{run_id}:lineage:{output_sha256}")
    lineage_facets = {
        "schema": LINEAGE_SCHEMA,
        "operation": "materialize_public_geojson",
        "input_media_type": landing.registration.artifact.media_type,
        "output_media_type": "application/geo+json",
        "output_sha256": output_sha256,
    }
    lineage_event = LineageEvent(
        tenant_id=run.tenant_id,
        lineage_event_id=lineage_event_id,
        event_type="materialize",
        source_resource_version_id=landing.registration.resource_version.resource_version_id,
        target_resource_version_id=target_version_id,
        producer=request.executor,
        event_sha256=canonical_json_fingerprint(
            {
                "source_resource_version_id": str(
                    landing.registration.resource_version.resource_version_id
                ),
                "target_resource_version_id": str(target_version_id),
                "run_id": str(run_id),
                "facets": lineage_facets,
            }
        ),
        run_id=run_id,
        definition_version_id=run.definition_version_id,
        artifact_id=output_artifact_id,
        facets=lineage_facets,
        occurred_at=request.executed_at,
    )
    attempt_id = uuid5(NAMESPACE_URL, f"{run_id}:attempt:1:success")
    attempt_evidence = {
        "schema": ATTEMPT_SCHEMA,
        "execution_mode": "local_inline",
        "executor": request.executor,
        "output_sha256": output_sha256,
        "quality_result_id": str(quality_result_id),
    }
    attempt = FrameworkAttemptObservation(
        tenant_id=run.tenant_id,
        observation_id=attempt_id,
        run_id=run_id,
        attempt_no=1,
        framework_kind="legacy",
        external_namespace="gda-public-lightweight",
        external_run_id=str(run_id),
        external_attempt_id="1",
        observed_state="success",
        observation_sha256=canonical_json_fingerprint(attempt_evidence),
        evidence=attempt_evidence,
        observed_at=request.executed_at,
    )
    success_evidence = RunSuccessEvidence(
        tenant_id=run.tenant_id,
        run_id=run_id,
        attempt_observation_id=attempt_id,
        output_artifact_id=output_artifact_id,
        quality_result_id=quality_result_id,
        lineage_event_id=lineage_event_id,
        evidence_sha256=run_success_evidence_fingerprint(
            tenant_id=run.tenant_id,
            run_id=run_id,
            attempt_observation_id=attempt_id,
            output_artifact_id=output_artifact_id,
            quality_result_id=quality_result_id,
            lineage_event_id=lineage_event_id,
        ),
    )
    return PublicDataOpsResult(
        landing=landing,
        definition_registration=definition_registration,
        run=run,
        target_resource=target_resource,
        target_version=target_version,
        output_artifact=output_artifact,
        quality_evidence_artifact=quality_artifact,
        quality_result=quality_result,
        lineage_event=lineage_event,
        attempt_observation=attempt,
        success_evidence=success_evidence,
        output_path=str(output_path),
        quality_path=str(quality_path),
        output_created=output_created,
        quality_created=quality_created,
    )


def register_public_dataops(
    result: PublicDataOpsResult, gateway: PlatformGateway
) -> PublicDataOpsResult:
    """Replayably register the bundle and finalize the synchronous Run."""
    gateway.register_landing(result.landing.registration)
    gateway.register_definition(result.definition_registration)
    gateway.register_resource(result.target_resource)
    gateway.register_resource_version(result.target_version)
    gateway.submit_run(result.run, request_dispatch=False)
    current = gateway.get_run(result.run.tenant_id, result.run.run_id)
    actor = (
        result.run.subject_context.subject_type.value + ":" + result.run.subject_context.subject_id
    )
    if current.status.value == "accepted":
        current = gateway.transition_run(
            result.run.tenant_id,
            result.run.run_id,
            0,
            "dispatching",
            actor,
            "local lightweight profile accepted Run",
        )
    if current.status.value == "dispatching":
        current = gateway.transition_run(
            result.run.tenant_id,
            result.run.run_id,
            1,
            "running",
            actor,
            "local lightweight executor started Run",
        )
    if current.status.value not in {"running", "succeeded"}:
        raise PublicDataOpsError(f"cannot finalize Run in status {current.status.value}")
    gateway.record_artifact(result.output_artifact)
    gateway.record_artifact(result.quality_evidence_artifact)
    gateway.record_attempt(result.attempt_observation)
    gateway.record_quality_result(result.quality_result)
    gateway.record_lineage(result.lineage_event)
    final_run = gateway.finalize_run_success(
        result.success_evidence,
        expected_state_version=2,
        actor_subject=actor,
        reason="public lightweight GeoJSON materialization passed content and quality gates",
    )
    return result.model_copy(update={"final_run": final_run, "ledger_completed": True})


def verify_public_dataops_result(result: PublicDataOpsResult) -> None:
    verify_public_source_landing(result.landing)
    output = Path(result.output_path)
    quality = Path(result.quality_path)
    if output.is_symlink() or quality.is_symlink() or not output.is_file() or not quality.is_file():
        raise PublicDataOpsError("serving output or quality evidence is missing")
    output_bytes = output.read_bytes()
    if hashlib.sha256(output_bytes).hexdigest() != result.target_version.content_sha256:
        raise PublicDataOpsError("serving output does not match target ResourceVersion")
    if output.as_uri() != result.output_artifact.storage_uri:
        raise PublicDataOpsError("output Artifact URI does not match serving output")
    quality_bytes = quality.read_bytes()
    if hashlib.sha256(quality_bytes).hexdigest() != result.quality_evidence_artifact.content_sha256:
        raise PublicDataOpsError("quality evidence does not match its Artifact hash")
    quality_document = json.loads(quality_bytes)
    if quality_document != result.quality_evidence_artifact.manifest:
        raise PublicDataOpsError("quality evidence does not match its Artifact")
    if quality.as_uri() != result.quality_evidence_artifact.storage_uri:
        raise PublicDataOpsError("quality Artifact URI does not match evidence file")
    if result.final_run is not None and result.final_run.status.value != "succeeded":
        raise PublicDataOpsError("registered DataOps Run is not succeeded")


def _write_result(result: PublicDataOpsResult, output: Path | None) -> None:
    rendered = json.dumps(
        result.model_dump(mode="json"), ensure_ascii=True, indent=2, sort_keys=True
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--landing-result", type=Path, required=True)
    run_parser.add_argument("--serving-root", type=Path, required=True)
    run_parser.add_argument("--output-dataset-id", required=True)
    run_parser.add_argument("--executor", default="workload:public-dataops")
    run_parser.add_argument("--quality-evaluator", default="workload:public-quality")
    run_parser.add_argument("--executed-at", type=_parse_time, required=True)
    run_parser.add_argument("--min-feature-count", type=int, default=1)
    run_parser.add_argument("--database-url")
    run_parser.add_argument("--output", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        landing = PublicSourceLandingResult.model_validate_json(
            args.landing_result.read_text(encoding="utf-8")
        )
        request = PublicDataOpsRequest(
            executor=args.executor,
            quality_evaluator=args.quality_evaluator,
            output_dataset_id=args.output_dataset_id,
            executed_at=args.executed_at,
            min_feature_count=args.min_feature_count,
        )
        result = materialize_public_dataops(landing, request, serving_root=args.serving_root)
        if args.database_url:
            from sqlalchemy import create_engine

            result = register_public_dataops(
                result, PlatformGateway(create_engine(args.database_url))
            )
        verify_public_dataops_result(result)
        _write_result(result, args.output)
        return 0
    result = PublicDataOpsResult.model_validate_json(args.input.read_text(encoding="utf-8"))
    verify_public_dataops_result(result)
    print(
        json.dumps(
            {
                "valid": True,
                "run_id": str(result.run.run_id),
                "output_sha256": result.output_artifact.content_sha256,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
