"""AR-0 legacy inventory, evidence-gated crosswalk, and golden-slice checks.

This module is deliberately read-only. It inventories known legacy writers,
validates explicit target contract payloads, and reports whether a proposed
crosswalk is eligible, blocked, or prohibited. It never backfills a database.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from .platform_contracts import (
    Artifact,
    FrameworkAttemptObservation,
    LineageEvent,
    PlatformDefinitionVersion,
    PlatformRun,
    Resource,
    ResourceVersion,
    SubjectContext,
    canonical_json_bytes,
    canonical_json_fingerprint,
    validate_run_transition,
)


CROSSWALK_SCHEMA_VERSION = "gda.platform_crosswalk.v1"
GOLDEN_FIXTURE_SCHEMA = "gda.land_use_parcel_golden.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLDEN_FIXTURE = (
    Path(__file__).resolve().parent
    / "test_data"
    / "platform"
    / "land_use_parcel_golden.json"
)

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class MappingPolicy(str, Enum):
    EVIDENCE_REQUIRED = "evidence_required"
    PROHIBITED = "prohibited"


class MappingDisposition(str, Enum):
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    PROHIBITED = "prohibited"


@dataclass(frozen=True)
class SourceMarker:
    path: str
    marker: str
    role: str


@dataclass(frozen=True)
class CrosswalkRule:
    target_contract: str
    policy: MappingPolicy
    required_target_fields: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class LegacyTableSpec:
    table_name: str
    fact_domain: str
    current_semantics: str
    schema_markers: tuple[SourceMarker, ...]
    writer_markers: tuple[SourceMarker, ...]
    endpoint_markers: tuple[SourceMarker, ...]
    write_tokens: tuple[str, ...]
    rules: tuple[CrosswalkRule, ...]
    blockers: tuple[str, ...]


def _marker(path: str, marker: str, role: str) -> SourceMarker:
    return SourceMarker(path=path, marker=marker, role=role)


LEGACY_TABLE_SPECS = (
    LegacyTableSpec(
        table_name="agent_data_assets",
        fact_domain="resource_identity",
        current_semantics=(
            "Mutable four-layer metadata row; owner and asset name are not a "
            "tenant-scoped immutable resource identity."
        ),
        schema_markers=(
            _marker(
                "data_agent/migrations/044_metadata_system.sql",
                "CREATE TABLE IF NOT EXISTS agent_data_assets",
                "schema",
            ),
            _marker(
                "data_agent/migrations/048_unify_data_assets.sql",
                "CREATE OR REPLACE VIEW agent_data_catalog",
                "compatibility_view",
            ),
            _marker(
                "data_agent/migrations/056_cross_system_lineage.sql",
                "ADD COLUMN IF NOT EXISTS external_system",
                "schema_extension",
            ),
        ),
        writer_markers=(
            _marker(
                "data_agent/data_catalog.py",
                "INSERT INTO agent_data_assets",
                "catalog_writer",
            ),
            _marker(
                "data_agent/metadata_manager.py",
                "INSERT INTO agent_data_assets",
                "metadata_writer",
            ),
            _marker(
                "data_agent/data_classification.py",
                "UPDATE agent_data_assets",
                "classification_writer",
            ),
            _marker(
                "data_agent/lite_mode.py",
                "INSERT INTO agent_data_assets",
                "lite_seed_writer",
            ),
            _marker(
                "data_agent/data_versioning.py",
                "UPDATE {T_DATA_CATALOG}",
                "compatibility_view_version_writer",
            ),
        ),
        endpoint_markers=(
            _marker(
                "data_agent/api/metadata_routes.py",
                'Route("/api/metadata/{asset_id:int}", '
                'endpoint=_api_metadata_update, methods=["PUT"])',
                "metadata_mutation_api",
            ),
            _marker(
                "data_agent/api/lineage_routes.py",
                'Route("/api/external-assets"',
                "external_asset_api",
            ),
        ),
        write_tokens=(
            "agent_data_assets",
            "agent_data_catalog",
            "{T_DATA_CATALOG}",
        ),
        rules=(
            CrosswalkRule(
                target_contract="resource",
                policy=MappingPolicy.EVIDENCE_REQUIRED,
                required_target_fields=(
                    "tenant_id",
                    "resource_urn",
                    "resource_kind",
                    "authority_system",
                    "authority_locator",
                    "owner_ref",
                ),
                rationale=(
                    "The legacy row can seed a Resource only after tenant, kind, "
                    "stable authority identity, and owner are independently proven."
                ),
            ),
            CrosswalkRule(
                target_contract="resource_version",
                policy=MappingPolicy.EVIDENCE_REQUIRED,
                required_target_fields=(
                    "tenant_id",
                    "resource_urn",
                    "resource_version_id",
                    "version_key",
                    "content_sha256",
                    "authority_version_ref",
                    "created_by",
                    "created_at",
                ),
                rationale=(
                    "A mutable asset row is not a version unless immutable content "
                    "and authority revision evidence are supplied."
                ),
            ),
        ),
        blockers=(
            "No tenant_id column.",
            "Metadata and location fields are mutable.",
            "No required content checksum or authority revision.",
            "asset_name/owner_username is not a stable global identity.",
        ),
    ),
    LegacyTableSpec(
        table_name="agent_asset_versions",
        fact_domain="resource_version",
        current_semantics=(
            "Local snapshot history keyed by integer asset_id and version number."
        ),
        schema_markers=(
            _marker(
                "data_agent/migrations/034_data_versioning.sql",
                "CREATE TABLE IF NOT EXISTS agent_asset_versions",
                "schema",
            ),
        ),
        writer_markers=(
            _marker(
                "data_agent/data_versioning.py",
                "INSERT INTO {T_ASSET_VERSIONS}",
                "snapshot_writer",
            ),
        ),
        endpoint_markers=(),
        write_tokens=("{T_ASSET_VERSIONS}",),
        rules=(
            CrosswalkRule(
                target_contract="resource_version",
                policy=MappingPolicy.EVIDENCE_REQUIRED,
                required_target_fields=(
                    "tenant_id",
                    "resource_urn",
                    "resource_version_id",
                    "version_key",
                    "content_sha256",
                    "authority_version_ref",
                    "created_by",
                    "created_at",
                ),
                rationale=(
                    "snapshot_path and size are insufficient; the adapter must read "
                    "the snapshot, hash it, resolve its Resource, and prove authority."
                ),
            ),
        ),
        blockers=(
            "No foreign key to the current asset authority table.",
            "No tenant_id or content checksum.",
            "snapshot_path may be empty, relative, mutable, or missing.",
            "Rollback mutates compatibility state rather than publishing a new version.",
        ),
    ),
    LegacyTableSpec(
        table_name="agent_workflows",
        fact_domain="platform_definition",
        current_semantics=(
            "Mutable workflow editor document with embedded schedule and provider-"
            "specific execution fields."
        ),
        schema_markers=(
            _marker(
                "data_agent/migrations/017_create_workflows.sql",
                "CREATE TABLE IF NOT EXISTS agent_workflows",
                "schema",
            ),
        ),
        writer_markers=(
            _marker(
                "data_agent/workflow_engine.py",
                "INSERT INTO {T_WORKFLOWS}",
                "workflow_writer",
            ),
            _marker(
                "data_agent/workflow_templates.py",
                "INSERT INTO {T_WORKFLOWS}",
                "template_clone_writer",
            ),
        ),
        endpoint_markers=(
            _marker(
                "data_agent/api/workflow_routes.py",
                'Route("/api/workflows", workflows_create, methods=["POST"])',
                "workflow_create_api",
            ),
            _marker(
                "data_agent/api/workflow_routes.py",
                'Route("/api/workflows/{id:int}", workflow_update, methods=["PUT"])',
                "workflow_update_api",
            ),
            _marker(
                "data_agent/api/workflow_routes.py",
                'Route("/api/workflows/{id:int}", workflow_delete, methods=["DELETE"])',
                "workflow_delete_api",
            ),
        ),
        write_tokens=("{T_WORKFLOWS}",),
        rules=(
            CrosswalkRule(
                target_contract="platform_definition_version",
                policy=MappingPolicy.EVIDENCE_REQUIRED,
                required_target_fields=(
                    "tenant_id",
                    "definition_urn",
                    "definition_version_id",
                    "orchestration_class",
                    "capability_id",
                    "portability_class",
                    "definition_document",
                    "input_contract",
                    "output_contract",
                    "definition_sha256",
                ),
                rationale=(
                    "The mutable editor row must be normalized into a complete logical "
                    "definition and hashed; cron/webhook state is not the definition."
                ),
            ),
        ),
        blockers=(
            "No tenant_id or immutable definition version.",
            "Input/output contracts and portability class are absent.",
            "Rows can be updated and deleted in place.",
            "pipeline_type does not uniquely determine orchestration_class.",
        ),
    ),
    LegacyTableSpec(
        table_name="agent_workflow_runs",
        fact_domain="framework_attempt",
        current_semantics=(
            "Mutable process-local workflow execution projection and checkpoint store."
        ),
        schema_markers=(
            _marker(
                "data_agent/migrations/017_create_workflows.sql",
                "CREATE TABLE IF NOT EXISTS agent_workflow_runs",
                "schema",
            ),
            _marker(
                "data_agent/migrations/014_workflow_checkpoints.sql",
                "ADD COLUMN IF NOT EXISTS node_checkpoints",
                "checkpoint_extension",
            ),
        ),
        writer_markers=(
            _marker(
                "data_agent/workflow_engine.py",
                "INSERT INTO {T_WORKFLOW_RUNS}",
                "run_writer",
            ),
            _marker(
                "data_agent/workflow_engine.py",
                "UPDATE {T_WORKFLOW_RUNS}",
                "run_state_writer",
            ),
        ),
        endpoint_markers=(
            _marker(
                "data_agent/api/workflow_routes.py",
                'Route("/api/workflows/{id:int}/execute"',
                "workflow_execute_api",
            ),
            _marker(
                "data_agent/api/workflow_routes.py",
                'Route("/api/workflows/{id:int}/runs/{run_id:int}/retry"',
                "workflow_retry_api",
            ),
            _marker(
                "data_agent/api/workflow_routes.py",
                'Route("/api/workflows/{id:int}/runs/{run_id:int}/resume"',
                "workflow_resume_api",
            ),
        ),
        write_tokens=("{T_WORKFLOW_RUNS}",),
        rules=(
            CrosswalkRule(
                target_contract="framework_attempt_observation",
                policy=MappingPolicy.EVIDENCE_REQUIRED,
                required_target_fields=(
                    "tenant_id",
                    "observation_id",
                    "run_id",
                    "attempt_no",
                    "framework_kind",
                    "external_namespace",
                    "external_run_id",
                    "observed_state",
                    "observation_sha256",
                    "observed_at",
                ),
                rationale=(
                    "A row may become an observation only when an existing PlatformRun "
                    "correlation and immutable observation envelope are supplied."
                ),
            ),
            CrosswalkRule(
                target_contract="platform_run",
                policy=MappingPolicy.PROHIBITED,
                required_target_fields=(),
                rationale=(
                    "Legacy run status is provider/process evidence and must never "
                    "fabricate the platform final-state authority."
                ),
            ),
        ),
        blockers=(
            "No tenant_id, UUID run identity, definition version, or idempotency key.",
            "Status is updated by process-local retry/resume/checkpoint code.",
            "Provider success is not an artifact/quality/policy verdict.",
            "Naive timestamps and integer IDs are insufficient correlation evidence.",
        ),
    ),
    LegacyTableSpec(
        table_name="agent_asset_lineage",
        fact_domain="lineage_evidence",
        current_semantics=(
            "Mutable asset-level internal/external edge without version endpoints."
        ),
        schema_markers=(
            _marker(
                "data_agent/migrations/056_cross_system_lineage.sql",
                "CREATE TABLE IF NOT EXISTS agent_asset_lineage",
                "schema",
            ),
        ),
        writer_markers=(
            _marker(
                "data_agent/data_catalog.py",
                "INSERT INTO agent_asset_lineage",
                "lineage_writer",
            ),
            _marker(
                "data_agent/data_catalog.py",
                "DELETE FROM agent_asset_lineage",
                "lineage_delete_writer",
            ),
        ),
        endpoint_markers=(
            _marker(
                "data_agent/api/lineage_routes.py",
                'Route("/api/catalog/{id:int}/lineage"',
                "lineage_create_api",
            ),
            _marker(
                "data_agent/api/lineage_routes.py",
                'Route("/api/lineage/{id:int}"',
                "lineage_delete_api",
            ),
        ),
        write_tokens=("agent_asset_lineage",),
        rules=(
            CrosswalkRule(
                target_contract="lineage_event",
                policy=MappingPolicy.EVIDENCE_REQUIRED,
                required_target_fields=(
                    "tenant_id",
                    "lineage_event_id",
                    "event_type",
                    "source_resource_version_id",
                    "target_resource_version_id",
                    "producer",
                    "event_sha256",
                    "occurred_at",
                ),
                rationale=(
                    "Both asset endpoints must resolve to immutable ResourceVersions; "
                    "external-only endpoints need explicit technical object crosswalks."
                ),
            ),
        ),
        blockers=(
            "Edges reference assets, not immutable versions.",
            "No tenant_id or event checksum.",
            "Rows can be deleted and relationship vocabulary is not normalized.",
            "pipeline_run_id is free text and not a PlatformRun correlation.",
        ),
    ),
)

LEGACY_TABLES = {spec.table_name: spec for spec in LEGACY_TABLE_SPECS}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ResourceCrosswalkPayload = Resource


class CrosswalkCandidate(StrictModel):
    schema_version: str = CROSSWALK_SCHEMA_VERSION
    source_table: NonEmptyText
    legacy_key: NonEmptyText
    source_row_sha256: Sha256
    extracted_at: datetime
    adapter_id: NonEmptyText
    target_contract: NonEmptyText
    target_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != CROSSWALK_SCHEMA_VERSION:
            raise ValueError("unsupported crosswalk schema_version")
        return value

    @field_validator("extracted_at")
    @classmethod
    def _aware_extracted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("extracted_at must include a timezone")
        return value.astimezone(timezone.utc)


TARGET_MODELS: dict[str, type[BaseModel]] = {
    "resource": Resource,
    "resource_version": ResourceVersion,
    "platform_definition_version": PlatformDefinitionVersion,
    "framework_attempt_observation": FrameworkAttemptObservation,
    "lineage_event": LineageEvent,
}


def _source_text(root: Path, marker: SourceMarker) -> str | None:
    path = root / marker.path
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _discover_writer_paths(root: Path, spec: LegacyTableSpec) -> set[str]:
    token_pattern = "|".join(re.escape(token) for token in spec.write_tokens)
    write_pattern = re.compile(
        rf"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:{token_pattern})",
        re.IGNORECASE,
    )
    discovered: set[str] = set()
    data_agent_root = root / "data_agent"
    for path in data_agent_root.rglob("*.py"):
        if path.name.startswith("test_") or "tests" in path.parts:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        if write_pattern.search(text):
            discovered.add(path.relative_to(root).as_posix())
    return discovered


def build_inventory_report(root: Path | None = None) -> dict[str, Any]:
    repository_root = (root or REPOSITORY_ROOT).resolve()
    errors: list[str] = []
    tables: list[dict[str, Any]] = []

    for spec in LEGACY_TABLE_SPECS:
        missing_markers: list[dict[str, str]] = []
        all_markers = (
            spec.schema_markers + spec.writer_markers + spec.endpoint_markers
        )
        for marker in all_markers:
            source = _source_text(repository_root, marker)
            if source is None or marker.marker not in source:
                missing_markers.append(asdict(marker))

        declared_writers = {marker.path for marker in spec.writer_markers}
        discovered_writers = _discover_writer_paths(repository_root, spec)
        unregistered_writers = sorted(discovered_writers - declared_writers)
        if missing_markers:
            errors.append(f"{spec.table_name} has missing source markers")
        if unregistered_writers:
            errors.append(f"{spec.table_name} has unregistered writer paths")

        table = {
            "table_name": spec.table_name,
            "fact_domain": spec.fact_domain,
            "current_semantics": spec.current_semantics,
            "schema_markers": [asdict(item) for item in spec.schema_markers],
            "writer_markers": [asdict(item) for item in spec.writer_markers],
            "endpoint_markers": [asdict(item) for item in spec.endpoint_markers],
            "discovered_writer_paths": sorted(discovered_writers),
            "unregistered_writer_paths": unregistered_writers,
            "missing_markers": missing_markers,
            "rules": [
                {
                    **asdict(rule),
                    "policy": rule.policy.value,
                }
                for rule in spec.rules
            ],
            "blockers": list(spec.blockers),
        }
        tables.append(table)

    inventory_fingerprint = canonical_json_fingerprint(tables)
    return {
        "schema": CROSSWALK_SCHEMA_VERSION,
        "status": "valid" if not errors else "invalid",
        "table_count": len(tables),
        "inventory_fingerprint": inventory_fingerprint,
        "tables": tables,
        "errors": errors,
    }


def _validation_issues(error: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "field": ".".join(str(part) for part in item["loc"]),
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]


def plan_crosswalk(candidate: CrosswalkCandidate | dict[str, Any]) -> dict[str, Any]:
    parsed = (
        candidate
        if isinstance(candidate, CrosswalkCandidate)
        else CrosswalkCandidate.model_validate(candidate)
    )
    source_spec = LEGACY_TABLES.get(parsed.source_table)
    plan_id = canonical_json_fingerprint(parsed.model_dump(mode="json"))
    base = {
        "schema": CROSSWALK_SCHEMA_VERSION,
        "plan_id": plan_id,
        "source_table": parsed.source_table,
        "legacy_key": parsed.legacy_key,
        "source_row_sha256": parsed.source_row_sha256,
        "target_contract": parsed.target_contract,
        "mutates_database": False,
    }
    if source_spec is None:
        return {
            **base,
            "disposition": MappingDisposition.PROHIBITED.value,
            "reason": "source table is outside the frozen legacy inventory",
            "issues": [],
        }

    rule = next(
        (
            item
            for item in source_spec.rules
            if item.target_contract == parsed.target_contract
        ),
        None,
    )
    if rule is None:
        return {
            **base,
            "disposition": MappingDisposition.PROHIBITED.value,
            "reason": "target contract is not allowed for this legacy table",
            "issues": [],
        }
    if rule.policy == MappingPolicy.PROHIBITED:
        return {
            **base,
            "disposition": MappingDisposition.PROHIBITED.value,
            "reason": rule.rationale,
            "issues": [],
        }

    target_model = TARGET_MODELS[parsed.target_contract]
    try:
        target = target_model.model_validate(parsed.target_payload)
    except ValidationError as exc:
        return {
            **base,
            "disposition": MappingDisposition.BLOCKED.value,
            "reason": "target payload does not satisfy the frozen contract",
            "required_target_fields": list(rule.required_target_fields),
            "issues": _validation_issues(exc),
        }

    return {
        **base,
        "disposition": MappingDisposition.ELIGIBLE.value,
        "reason": rule.rationale,
        "required_target_fields": list(rule.required_target_fields),
        "target_payload": target.model_dump(mode="json"),
        "issues": [],
    }


def plan_crosswalk_file(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    candidates = document if isinstance(document, list) else [document]
    plans: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        try:
            plans.append(plan_crosswalk(candidate))
        except ValidationError as exc:
            errors.append({"index": index, "issues": _validation_issues(exc)})
    return {
        "schema": CROSSWALK_SCHEMA_VERSION,
        "status": "valid" if not errors else "invalid",
        "candidate_count": len(candidates),
        "plans": plans,
        "errors": errors,
    }


def _geometry_structure_valid(geometry: Any) -> bool:
    if not isinstance(geometry, dict):
        return False
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    return geometry_type in {"Polygon", "MultiPolygon"} and bool(coordinates)


def _dataset_quality(dataset: dict[str, Any], required_fields: list[str]) -> dict[str, Any]:
    features = dataset.get("features")
    if not isinstance(features, list):
        return {
            "feature_count": 0,
            "geometry_structure_errors": 1,
            "required_field_missing_count": len(required_fields),
            "duplicate_bsm_count": 0,
            "total_area": "0.00",
        }

    missing = 0
    geometry_errors = 0
    identifiers: list[str] = []
    total_area = Decimal("0")
    for feature in features:
        if not isinstance(feature, dict):
            geometry_errors += 1
            missing += len(required_fields)
            continue
        if not _geometry_structure_valid(feature.get("geometry")):
            geometry_errors += 1
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            missing += len(required_fields)
            continue
        for field in required_fields:
            if properties.get(field) in (None, ""):
                missing += 1
        if properties.get("BSM") not in (None, ""):
            identifiers.append(str(properties["BSM"]))
        try:
            total_area += Decimal(str(properties.get("TBMJ", 0)))
        except Exception:
            missing += 1

    duplicate_count = len(identifiers) - len(set(identifiers))
    return {
        "feature_count": len(features),
        "geometry_structure_errors": geometry_errors,
        "required_field_missing_count": missing,
        "duplicate_bsm_count": duplicate_count,
        "total_area": f"{total_area:.2f}",
    }


def validate_golden_fixture(path: Path | None = None) -> dict[str, Any]:
    fixture_path = (path or DEFAULT_GOLDEN_FIXTURE).resolve()
    errors: list[str] = []
    if not fixture_path.is_file():
        return {
            "schema": GOLDEN_FIXTURE_SCHEMA,
            "status": "invalid",
            "path": fixture_path.as_posix(),
            "errors": ["golden fixture is missing"],
        }

    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema": GOLDEN_FIXTURE_SCHEMA,
            "status": "invalid",
            "path": fixture_path.as_posix(),
            "errors": [f"golden fixture cannot be parsed: {exc}"],
        }

    if fixture.get("schema") != GOLDEN_FIXTURE_SCHEMA:
        errors.append("fixture schema is unsupported")
    if fixture.get("synthetic") is not True:
        errors.append("fixture must be explicitly synthetic")
    if fixture.get("not_for_production") is not True:
        errors.append("fixture must be explicitly marked not_for_production")

    standard = fixture.get("standard_evidence", {})
    standard_path = (REPOSITORY_ROOT / str(standard.get("path", ""))).resolve()
    try:
        standard_path.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        errors.append("standard evidence path escapes the repository")
    else:
        if not standard_path.is_file():
            errors.append("standard evidence file is missing")
        elif str(standard.get("marker", "")) not in standard_path.read_text(
            encoding="utf-8"
        ):
            errors.append("standard evidence marker is missing")

    input_dataset = fixture.get("input_dataset", {})
    output_dataset = fixture.get("expected_output_dataset", {})
    input_sha256 = canonical_json_fingerprint(input_dataset)
    output_sha256 = canonical_json_fingerprint(output_dataset)
    output_size_bytes = len(canonical_json_bytes(output_dataset))
    contracts = fixture.get("contracts", {})

    parsed_contracts: dict[str, BaseModel] = {}
    contract_models: tuple[tuple[str, type[BaseModel]], ...] = (
        ("subject_context", SubjectContext),
        ("definition_resource_version", ResourceVersion),
        ("source_resource_version", ResourceVersion),
        ("target_resource_version", ResourceVersion),
        ("definition", PlatformDefinitionVersion),
        ("run", PlatformRun),
        ("attempt_observation", FrameworkAttemptObservation),
        ("artifact", Artifact),
        ("lineage_event", LineageEvent),
    )
    for name, model in contract_models:
        try:
            parsed_contracts[name] = model.model_validate(contracts.get(name, {}))
        except ValidationError as exc:
            errors.append(f"{name} contract is invalid: {_validation_issues(exc)}")

    resources = contracts.get("resources", [])
    parsed_resources: list[ResourceCrosswalkPayload] = []
    if not isinstance(resources, list) or len(resources) != 3:
        errors.append("fixture must define exactly three resources")
    else:
        for index, resource in enumerate(resources):
            try:
                parsed_resources.append(
                    ResourceCrosswalkPayload.model_validate(resource)
                )
            except ValidationError as exc:
                errors.append(
                    f"resources[{index}] is invalid: {_validation_issues(exc)}"
                )

    source = parsed_contracts.get("source_resource_version")
    target = parsed_contracts.get("target_resource_version")
    definition_resource = parsed_contracts.get("definition_resource_version")
    definition = parsed_contracts.get("definition")
    run = parsed_contracts.get("run")
    observation = parsed_contracts.get("attempt_observation")
    artifact = parsed_contracts.get("artifact")
    lineage = parsed_contracts.get("lineage_event")
    subject = parsed_contracts.get("subject_context")

    if isinstance(source, ResourceVersion) and source.content_sha256 != input_sha256:
        errors.append("source ResourceVersion hash does not match input_dataset")
    if isinstance(target, ResourceVersion) and target.content_sha256 != output_sha256:
        errors.append("target ResourceVersion hash does not match expected output")
    if isinstance(definition, PlatformDefinitionVersion) and isinstance(
        definition_resource, ResourceVersion
    ):
        if definition_resource.resource_urn != definition.definition_urn:
            errors.append("definition ResourceVersion URN does not match definition")
        if definition_resource.resource_version_id != definition.definition_version_id:
            errors.append("definition ResourceVersion ID does not match definition")
        if definition_resource.content_sha256 != definition.definition_sha256:
            errors.append("definition ResourceVersion hash does not match definition")
    if (
        isinstance(source, ResourceVersion)
        and isinstance(target, ResourceVersion)
        and isinstance(definition_resource, ResourceVersion)
    ):
        expected_resource_urns = {
            definition_resource.resource_urn,
            source.resource_urn,
            target.resource_urn,
        }
        actual_resource_urns = {
            resource.resource_urn for resource in parsed_resources
        }
        if actual_resource_urns != expected_resource_urns:
            errors.append("fixture Resource identities do not match contract versions")
    if isinstance(run, PlatformRun):
        if isinstance(subject, SubjectContext) and run.subject_context != subject:
            errors.append("run SubjectContext does not match fixture SubjectContext")
        if isinstance(definition, PlatformDefinitionVersion) and (
            run.definition_version_id != definition.definition_version_id
        ):
            errors.append("run definition binding does not match definition")
        if isinstance(source, ResourceVersion) and (
            not run.input_bindings
            or run.input_bindings[0].resource_version_id
            != source.resource_version_id
        ):
            errors.append("run input binding does not match source version")
        previous = run.status
        for next_status in fixture.get("expected_run_transitions", []):
            try:
                validate_run_transition(previous, next_status)
            except ValueError as exc:
                errors.append(f"invalid expected run transition: {exc}")
                break
            previous = next_status
    if isinstance(observation, FrameworkAttemptObservation) and isinstance(
        run, PlatformRun
    ):
        if observation.run_id != run.run_id:
            errors.append("attempt observation does not match run")
        expected_observation_sha = canonical_json_fingerprint(observation.evidence)
        if observation.observation_sha256 != expected_observation_sha:
            errors.append("attempt observation hash does not match evidence")
    if isinstance(artifact, Artifact):
        if isinstance(run, PlatformRun) and artifact.run_id != run.run_id:
            errors.append("artifact does not match run")
        if isinstance(target, ResourceVersion) and (
            artifact.resource_version_id != target.resource_version_id
            or artifact.content_sha256 != target.content_sha256
        ):
            errors.append("artifact does not match target ResourceVersion")
        if artifact.size_bytes != output_size_bytes:
            errors.append("artifact size does not match expected output")
    if isinstance(lineage, LineageEvent):
        if isinstance(source, ResourceVersion) and (
            lineage.source_resource_version_id != source.resource_version_id
        ):
            errors.append("lineage source does not match source ResourceVersion")
        if isinstance(target, ResourceVersion) and (
            lineage.target_resource_version_id != target.resource_version_id
        ):
            errors.append("lineage target does not match target ResourceVersion")
        if isinstance(run, PlatformRun) and lineage.run_id != run.run_id:
            errors.append("lineage does not match run")
        if isinstance(definition, PlatformDefinitionVersion) and (
            lineage.definition_version_id != definition.definition_version_id
        ):
            errors.append("lineage does not match definition")
        if isinstance(artifact, Artifact) and lineage.artifact_id != artifact.artifact_id:
            errors.append("lineage does not match artifact")
        lineage_evidence = {
            "event_type": lineage.event_type.value,
            "source_resource_version_id": str(lineage.source_resource_version_id),
            "target_resource_version_id": str(lineage.target_resource_version_id),
            "run_id": str(lineage.run_id),
            "definition_version_id": str(lineage.definition_version_id),
            "artifact_id": str(lineage.artifact_id),
            "producer": lineage.producer,
            "facets": lineage.facets,
            "occurred_at": lineage.occurred_at.isoformat().replace("+00:00", "Z"),
        }
        if lineage.event_sha256 != canonical_json_fingerprint(lineage_evidence):
            errors.append("lineage event hash does not match event evidence")

    required_fields = fixture.get("required_fields", [])
    actual_quality = _dataset_quality(output_dataset, required_fields)
    expected_quality = fixture.get("quality_expectations", {})
    if actual_quality != expected_quality:
        errors.append("expected output quality does not match quality expectations")

    acceptance = fixture.get("acceptance", {})
    for required in ("owner", "rollback_point", "consumers"):
        if not acceptance.get(required):
            errors.append(f"acceptance.{required} is required")
    slo = acceptance.get("slo", {})
    if not isinstance(slo, dict) or not slo.get("max_runtime_seconds"):
        errors.append("acceptance.slo.max_runtime_seconds is required")

    return {
        "schema": GOLDEN_FIXTURE_SCHEMA,
        "status": "valid" if not errors else "invalid",
        "path": fixture_path.as_posix(),
        "fixture_fingerprint": canonical_json_fingerprint(fixture),
        "input_sha256": input_sha256,
        "output_sha256": output_sha256,
        "output_size_bytes": output_size_bytes,
        "resource_count": len(parsed_resources),
        "contract_count": len(parsed_contracts),
        "quality": actual_quality,
        "errors": errors,
    }


def build_validation_report() -> dict[str, Any]:
    inventory = build_inventory_report()
    golden = validate_golden_fixture()
    errors = list(inventory["errors"]) + list(golden["errors"])

    for spec in LEGACY_TABLE_SPECS:
        for rule in spec.rules:
            if (
                rule.policy == MappingPolicy.EVIDENCE_REQUIRED
                and rule.target_contract not in TARGET_MODELS
            ):
                errors.append(
                    f"{spec.table_name} references unknown target {rule.target_contract}"
                )
    run_spec = LEGACY_TABLES["agent_workflow_runs"]
    run_rule = next(
        rule for rule in run_spec.rules if rule.target_contract == "platform_run"
    )
    if run_rule.policy != MappingPolicy.PROHIBITED:
        errors.append("legacy workflow runs must not map directly to PlatformRun")

    return {
        "schema": CROSSWALK_SCHEMA_VERSION,
        "status": "valid" if not errors else "invalid",
        "inventory": inventory,
        "golden": golden,
        "errors": errors,
    }


def _print_json(value: Any, output: str | None = None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "inventory", "golden"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--output")
    golden_parser = subparsers.choices["golden"]
    golden_parser.add_argument("--fixture", default=str(DEFAULT_GOLDEN_FIXTURE))
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("input")
    plan_parser.add_argument("--output")
    args = parser.parse_args(argv)

    if args.command == "inventory":
        report = build_inventory_report()
    elif args.command == "golden":
        report = validate_golden_fixture(Path(args.fixture))
    elif args.command == "plan":
        report = plan_crosswalk_file(Path(args.input))
    else:
        report = build_validation_report()
    _print_json(report, args.output)
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
