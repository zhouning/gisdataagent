"""Approval-gated JQDLTB source-to-layer materialization.

The executor deliberately owns only the first vertical slice.  It turns an
approved, immutable transformation contract into reproducible JSON layer
artifacts and evidence.  It does not publish a DataProductVersion; that is a
later quality and serving gate.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .dolphinscheduler_adapter import (
    DolphinSchedulerContractError,
    parse_dolphinscheduler_jqdltb_transformation_plan_artifact,
)
from .jqdltb_transformation_approval import JqdltbTransformationApprovalService
from .object_materialization import (
    ObjectMaterializationContract,
    ObjectMaterializationEvidence,
    ObjectMaterializationRecorder,
)
from .platform_authorization import parse_policy_decision_artifact
from .platform_contracts import (
    Artifact,
    ArtifactRole,
    JqdltbAreaDeviationPolicy,
    JqdltbAreaPolicy,
    JqdltbTransformationContract,
    PlatformRun,
    RunStatus,
    canonical_json_bytes,
    canonical_json_fingerprint,
)
from .platform_gateway import PlatformGateway, PlatformGatewayError
from .standards_platform.application.acceptance import bundle_identity

TRANSFORM_EXECUTOR_SCHEMA = "gda.jqdltb_transformation_executor.v1"
TRANSFORM_QUALITY_RULE = "gda://local-dev/quality_rule/chongqing-jqdltb-transformation:v1"
TRANSFORM_WORKLOAD = "workload:dolphinscheduler-gda-dataops"
TRANSFORM_QUALITY_EVALUATOR = "workload:jqdltb-transformation-quality-evaluator"
JQDLTB_DECLARED_AREA_FIELDS = ("TBMJ", "TBDLMJ")


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JqdltbTransformationCommand(_FrozenModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    run_id: UUID
    source_resource_version_id: UUID
    contract: JqdltbTransformationContract


class JqdltbTransformationResult(_FrozenModel):
    schema_name: str = Field(default=TRANSFORM_EXECUTOR_SCHEMA, alias="schema")
    status: str
    run_id: UUID
    source_resource_version_id: UUID
    output_resource_version_id: UUID | None = None
    output_artifact_id: UUID | None = None
    quality_result_id: UUID | None = None
    lineage_event_id: UUID | None = None
    output_root: str | None = None
    records_read: int = Field(ge=0)
    records_materialized: int = Field(ge=0)
    records_quarantined: int = Field(ge=0)
    quality_verdict: str
    promotion_ready: bool = False
    data_product_version_created: bool = False
    replayed: bool = False


class JqdltbTransformationExecutorConfig(_FrozenModel):
    source_path: Path
    output_root: Path
    diagnostic_path: Path
    semantic_candidate_audit_path: Path | None = None
    archive_sha256: str | None = None
    bundle_sha256: str | None = None
    standard_version_ref: str | None = None
    standard_fingerprint: str | None = None
    correction_path: Path | None = None
    derivation_contract_paths: dict[str, Path] = Field(default_factory=dict)
    geometry_area_rule_path: Path | None = None

    @model_validator(mode="after")
    def _valid_paths(self) -> JqdltbTransformationExecutorConfig:
        if not self.source_path.is_absolute() or not self.source_path.exists():
            raise ValueError("JQDLTB source must be an existing absolute file or directory")
        if not self.output_root.is_absolute():
            raise ValueError("JQDLTB transformation output root must be absolute")
        if not self.diagnostic_path.is_absolute() or not self.diagnostic_path.is_file():
            raise ValueError("JQDLTB diagnostic must be an existing absolute file")
        if self.semantic_candidate_audit_path is not None and (
            not self.semantic_candidate_audit_path.is_absolute()
            or not self.semantic_candidate_audit_path.is_file()
        ):
            raise ValueError("JQDLTB semantic candidate audit must be an existing absolute file")
        if self.correction_path is not None and (
            not self.correction_path.is_absolute() or not self.correction_path.is_file()
        ):
            raise ValueError("JQDLTB correction file must be an existing absolute file")
        if any(
            not path.is_absolute() or not path.is_file()
            for path in self.derivation_contract_paths.values()
        ):
            raise ValueError("JQDLTB derivation contract paths must be existing absolute files")
        if self.geometry_area_rule_path is not None and (
            not self.geometry_area_rule_path.is_absolute()
            or not self.geometry_area_rule_path.is_file()
        ):
            raise ValueError("JQDLTB geometry area rule must be an existing absolute file")
        for value, label in (
            (self.archive_sha256, "archive_sha256"),
            (self.bundle_sha256, "bundle_sha256"),
            (self.standard_fingerprint, "standard_fingerprint"),
        ):
            if value is not None and (
                len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError(f"{label} must be a lowercase SHA-256 fingerprint")
        return self


def _actor_ref(run: PlatformRun) -> str:
    return f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"


def _json_value(value: Any) -> Any:
    """Convert numpy/shapely scalar values without making the source mutable."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _read_json_features(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        features = payload.get("features", [])
    elif isinstance(payload, list):
        features = payload
    elif isinstance(payload, dict) and payload.get("type") == "Feature":
        features = [payload]
    else:
        raise ValueError("JQDLTB JSON source must be a FeatureCollection or feature list")
    result: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise ValueError(f"JQDLTB feature {index} is not an object")
        properties = feature.get("properties")
        if not isinstance(properties, Mapping):
            properties = {key: value for key, value in feature.items() if key != "geometry"}
        result.append(
            {
                "type": "Feature",
                "id": _json_value(feature.get("id", index)),
                "properties": _json_value(dict(properties)),
                "geometry": _json_value(feature.get("geometry")),
            }
        )
    return result


def _read_csv_features(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {"type": "Feature", "id": index, "properties": dict(row), "geometry": None}
        for index, row in enumerate(rows)
    ]


def _read_features(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if path.is_file() and path.suffix.lower() in {".json", ".geojson"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        crs_value = payload.get("crs") if isinstance(payload, Mapping) else None
        crs = None
        if isinstance(crs_value, Mapping):
            properties = crs_value.get("properties")
            if isinstance(properties, Mapping) and _non_blank(properties.get("name")):
                crs = str(properties["name"])
        return _read_json_features(path), crs
    if path.is_file() and path.suffix.lower() == ".csv":
        return _read_csv_features(path), None
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - only exercised outside the runtime image
        raise RuntimeError("GeoPandas is required for Shapefile/FileGDB JQDLTB input") from exc
    frame = gpd.read_file(path)
    payload = json.loads(frame.to_json(drop_id=False))
    return (
        _read_json_features_from_payload(payload),
        frame.crs.to_string() if frame.crs else None,
    )


def _read_json_features_from_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("vector source did not return a FeatureCollection")
    result = []
    for index, feature in enumerate(features):
        if not isinstance(feature, Mapping):
            raise ValueError(f"vector feature {index} is not an object")
        result.append(
            {
                "type": "Feature",
                "id": _json_value(feature.get("id", index)),
                "properties": _json_value(dict(feature.get("properties") or {})),
                "geometry": _json_value(feature.get("geometry")),
            }
        )
    return result


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _geometry_area(geometry: Any) -> float | None:
    if not geometry:
        return None
    try:
        from shapely.geometry import shape

        area = float(shape(geometry).area)
    except (ImportError, TypeError, ValueError, AttributeError):
        return None
    return area if area == area and abs(area) != float("inf") else None


def _non_blank(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _first_source_value(properties: Mapping[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        value = properties.get(field)
        if _non_blank(value):
            return value
    return None


def _read_bound_json(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{label} content does not match approved SHA-256")
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return dict(payload)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o640)


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _expected_rule_bindings(
    contract: JqdltbTransformationContract,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    derivations = {
        item.target_field: {
            "semantic_contract_ref": item.semantic_contract_ref,
            "semantic_contract_sha256": item.semantic_contract_sha256,
            "method": item.method,
        }
        for item in contract.derivation_contracts
    }
    geometry = (
        {
            "rule_ref": contract.geometry_area_rule_ref,
            "rule_sha256": contract.geometry_area_rule_sha256,
            "method": "planar_geometry_area_in_source_crs",
        }
        if contract.area_deviation_policy is JqdltbAreaDeviationPolicy.USE_GEOMETRY
        else None
    )
    return derivations, geometry


class JqdltbTransformationExecutor:
    """Materialize one approved JQDLTB contract with a fail-closed admission gate."""

    def __init__(
        self,
        config: JqdltbTransformationExecutorConfig,
        *,
        gateway: PlatformGateway | None = None,
        approval_service: JqdltbTransformationApprovalService | None = None,
        clock: Any | None = None,
    ) -> None:
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.approval_service = approval_service or JqdltbTransformationApprovalService()
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _validate_run(run: PlatformRun, command: JqdltbTransformationCommand) -> None:
        if run.orchestration_class.value != "dataops":
            raise ValueError("JQDLTB transformation only accepts DataOps runs")
        if _actor_ref(run) != TRANSFORM_WORKLOAD:
            raise ValueError("run workload identity does not match the transformation")
        if run.status not in {
            RunStatus.DISPATCHING,
            RunStatus.RUNNING,
            RunStatus.RECONCILING,
        }:
            raise ValueError("run is not in an executable state")
        source = {item.binding_name: item for item in run.input_bindings}.get("source")
        if source is None or source.resource_version_id != command.source_resource_version_id:
            raise ValueError("source binding does not match the immutable PlatformRun input")

    def _validate_scheduler_plan(
        self,
        run: PlatformRun,
        contract: JqdltbTransformationContract,
    ) -> None:
        """Require the run's execution plan to carry this exact approved contract."""
        # Unit-level executors may intentionally use a lightweight gateway. Real
        # dispatched runs always carry policy references and therefore take this
        # platform-backed admission path.
        if run.policy_refs is None:
            return
        if not hasattr(self.gateway, "get_artifact"):
            raise ValueError("transformation run cannot validate its execution plan")
        try:
            policy_artifact = self.gateway.get_artifact(
                run.tenant_id,
                run.policy_refs.policy_decision_artifact_id,
            )
            decision = parse_policy_decision_artifact(policy_artifact)
            plan_artifact = self.gateway.get_artifact(
                run.tenant_id,
                decision.execution_plan_artifact_id,
            )
            binding, persisted_contract = (
                parse_dolphinscheduler_jqdltb_transformation_plan_artifact(plan_artifact)
            )
        except (DolphinSchedulerContractError, PlatformGatewayError, ValueError, KeyError) as exc:
            raise ValueError("transformation execution plan is invalid") from exc
        if (
            decision.run_id != run.run_id
            or decision.definition_version_id != run.definition_version_id
            or decision.action != "dolphinscheduler.dispatch"
            or decision.effect.value != "allow"
        ):
            raise ValueError("transformation execution plan policy scope is invalid")
        if binding.definition_version_id != run.definition_version_id:
            raise ValueError("transformation execution plan definition drifted")
        if persisted_contract != contract:
            raise ValueError("transformation contract does not match execution plan")

    def _expected(self, contract: JqdltbTransformationContract) -> tuple[str, str, str, str]:
        return (
            self.config.archive_sha256 or contract.archive_sha256,
            self.config.bundle_sha256 or contract.bundle_sha256,
            self.config.standard_version_ref or contract.standard_version_ref,
            self.config.standard_fingerprint or contract.standard_fingerprint,
        )

    @staticmethod
    def _validate_source_bundle_identity(
        source_path: Path, expected_bundle_sha256: str
    ) -> dict[str, Any]:
        """Re-read the real Shapefile bundle identity before materialization.

        JSON/CSV files are deliberately treated as test/fixture sources because
        they do not have a Shapefile sidecar bundle.  Real ``.shp`` execution
        must prove that the bytes being read are the same bundle bound by the
        approved contract.
        """

        if source_path.suffix.lower() != ".shp":
            return {
                "verification": "not_applicable_non_shapefile_fixture",
                "expected_bundle_sha256": expected_bundle_sha256,
            }
        identity_before = bundle_identity(source_path.resolve(strict=True))
        identity_after = bundle_identity(source_path.resolve(strict=True))
        if identity_before != identity_after:
            raise ValueError("JQDLTB source bundle changed while it was being read")
        if identity_after["bundle_sha256"] != expected_bundle_sha256:
            raise ValueError("JQDLTB source bundle does not match the approved contract")
        return {
            "verification": "shapefile_sidecar_bundle_verified",
            "expected_bundle_sha256": expected_bundle_sha256,
            "observed_bundle_sha256": identity_after["bundle_sha256"],
            "size_bytes": identity_after["size_bytes"],
            "member_count": len(identity_after["members"]),
        }

    @staticmethod
    def _quality_checks(
        *,
        features: list[dict[str, Any]],
        materialized: list[dict[str, Any]],
        quarantined: list[dict[str, Any]],
        stats: Mapping[str, Any],
        contract: JqdltbTransformationContract,
    ) -> list[dict[str, Any]]:
        """Evaluate the full post-transformation candidate quality contract."""

        def _passed(check_id: str, passed: bool, **metrics: Any) -> dict[str, Any]:
            return {"id": check_id, "status": "passed" if passed else "failed", **metrics}

        materialized_properties = [dict(item.get("properties") or {}) for item in materialized]
        keys = [str(item.get(contract.canonical_key)) for item in materialized_properties]
        key_complete = bool(materialized_properties) and all(
            _non_blank(item.get(contract.canonical_key)) for item in materialized_properties
        )
        area_failures = {
            field: sum(
                1
                for item in materialized_properties
                if (_as_number(item.get(field)) is None or _as_number(item.get(field)) <= 0)
            )
            for field in JQDLTB_DECLARED_AREA_FIELDS
        }
        derivation_failures = {
            target: sum(1 for item in materialized_properties if not _non_blank(item.get(target)))
            for target in ("SJNF", "MSSM")
        }
        geometry_failures = 0
        for item in materialized:
            geometry = item.get("geometry")
            if not geometry:
                geometry_failures += 1
                continue
            try:
                from shapely.geometry import shape

                candidate = shape(geometry)
                if candidate.is_empty or not candidate.is_valid:
                    geometry_failures += 1
            except (ImportError, TypeError, ValueError, AttributeError):
                geometry_failures += 1
        reason_values = {
            str(item.get("quarantine_reason")) for item in quarantined
        }
        observed_area_deviation_quarantined = sum(
            1
            for item in quarantined
            if item.get("quarantine_reason") == "area_deviation_outside_tolerance"
        )
        observed_area_deviation_annotated = sum(
            1
            for item in materialized_properties
            if _non_blank(item.get("gda_area_deviation_relative_error"))
        )
        observed_area_deviation_replaced = sum(
            1
            for item in materialized_properties
            if _non_blank(item.get("gda_area_rule_ref"))
        )
        # The materialized/quarantine collections do not retain all policy
        # applications (for example, a row can be quarantined for a second
        # reason after an area deviation was handled).  Prefer the explicit
        # counters emitted by _materialize_features; retain the derived values
        # for direct unit callers that provide only the legacy stats shape.
        area_deviation_quarantined = int(
            stats.get("area_deviation_quarantined_count", observed_area_deviation_quarantined)
        )
        area_deviation_annotated = int(
            stats.get("area_deviation_preserved_count", observed_area_deviation_annotated)
        )
        area_deviation_replaced = int(
            stats.get("area_deviation_replaced_count", observed_area_deviation_replaced)
        )
        allowed_reasons = {
            "nonpositive_declared_area",
            "area_deviation_outside_tolerance",
            "missing_business_correction",
            "canonical_key_blank",
            "canonical_key_duplicate",
            "sjnf_derivation_missing",
            "mssm_derivation_missing",
        }
        return [
            _passed(
                "records_reconciled",
                len(features) == len(materialized) + len(quarantined),
                records_read=len(features),
                records_materialized=len(materialized),
                records_quarantined=len(quarantined),
            ),
            _passed(
                "materialized_records_nonzero",
                bool(materialized),
                records_materialized=len(materialized),
            ),
            _passed(
                "canonical_key_complete_unique",
                key_complete and len(set(keys)) == len(keys),
                field=contract.canonical_key,
                duplicate_count=len(keys) - len(set(keys)),
            ),
            _passed(
                "declared_areas_positive",
                not any(area_failures.values()),
                failures=area_failures,
            ),
            _passed(
                "approved_derivations_complete",
                not any(derivation_failures.values()) and stats["derived_missing_count"] == 0,
                failures=derivation_failures,
            ),
            _passed(
                "approved_business_corrections_complete",
                stats["missing_business_correction_count"] == 0,
                missing_business_correction_count=stats["missing_business_correction_count"],
            ),
            _passed(
                "geometry_valid_nonempty",
                geometry_failures == 0,
                invalid_or_missing_count=geometry_failures,
            ),
            _passed(
                "standardization_fields_complete",
                not any(derivation_failures.values()),
                failures=derivation_failures,
            ),
            _passed(
                "quarantine_reason_codes_valid",
                reason_values.issubset(allowed_reasons),
                observed_reason_codes=sorted(reason_values),
            ),
            _passed(
                "area_policy_applied",
                (
                    stats["area_deviation_count"] == 0
                    or (
                        contract.area_deviation_policy.value == "quarantine"
                        and area_deviation_quarantined == stats["area_deviation_count"]
                    )
                    or (
                        contract.area_deviation_policy.value == "preserve_source"
                        and area_deviation_annotated == stats["area_deviation_count"]
                    )
                    or (
                        contract.area_deviation_policy.value == "use_geometry"
                        and area_deviation_replaced == stats["area_deviation_count"]
                    )
                ),
                area_deviation_policy=contract.area_deviation_policy.value,
                area_deviation_count=stats["area_deviation_count"],
                area_deviation_quarantined=area_deviation_quarantined,
                area_deviation_annotated=area_deviation_annotated,
                area_deviation_replaced=area_deviation_replaced,
            ),
        ]

    def _load_diagnostic(self) -> dict[str, Any]:
        value = json.loads(self.config.diagnostic_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JQDLTB diagnostic must be a JSON object")
        return value

    def _load_semantic_candidate_audit(
        self, contract: JqdltbTransformationContract
    ) -> dict[str, Any] | None:
        if contract.semantic_candidate_audit_sha256 is None:
            return None
        path = self.config.semantic_candidate_audit_path
        if path is None:
            raise ValueError("approved JQDLTB plan requires semantic candidate audit at execution")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JQDLTB semantic candidate audit must be a JSON object")
        return value

    def _output_dir(self, command: JqdltbTransformationCommand) -> Path:
        return (
            self.config.output_root.resolve()
            / command.tenant_id
            / str(command.run_id)
            / f"jqdltb-transform-{command.contract.plan_sha256[:16]}"
        )

    def _replayed(
        self, output_dir: Path, command: JqdltbTransformationCommand
    ) -> JqdltbTransformationResult | None:
        report_path = output_dir / "transformation-evidence.json"
        if not report_path.is_file():
            return None
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("contract_sha256") != command.contract.contract_sha256:
            raise ValueError("existing JQDLTB output has a different contract")
        if (
            not isinstance(report.get("result"), Mapping)
            or report["result"].get("status") != "completed"
        ):
            return None
        expected_derivations, expected_geometry = _expected_rule_bindings(command.contract)
        records = report.get("records")
        if (
            not isinstance(records, Mapping)
            or records.get("derivation_rule_bindings") != expected_derivations
            or records.get("geometry_area_rule_binding") != expected_geometry
        ):
            raise ValueError("existing JQDLTB output rule bindings do not match contract")
        return JqdltbTransformationResult.model_validate(report["result"] | {"replayed": True})

    def _load_corrections(
        self, contract: JqdltbTransformationContract
    ) -> dict[str, Mapping[str, Any]]:
        if contract.nonpositive_area_policy is not JqdltbAreaPolicy.BUSINESS_CORRECTION:
            return {}
        if self.config.correction_path is None:
            raise ValueError("business correction policy requires correction_path at execution")
        content = self.config.correction_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != contract.business_correction_sha256:
            raise ValueError("business correction content does not match approved SHA-256")
        payload = json.loads(content.decode("utf-8"))
        rows = payload.get("records") if isinstance(payload, Mapping) else payload
        if not isinstance(rows, list):
            raise ValueError("business correction file must contain a records list")
        indexed = {}
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or not _non_blank(row.get("TBBH")):
                raise ValueError(f"business correction row {index} requires TBBH")
            key = str(row["TBBH"])
            if key in indexed:
                raise ValueError(f"business correction contains duplicate TBBH: {key}")
            indexed[key] = row
        return indexed

    def _load_derivation_rules(
        self, contract: JqdltbTransformationContract
    ) -> dict[str, dict[str, Any]]:
        rules: dict[str, dict[str, Any]] = {}
        for derivation in contract.derivation_contracts:
            path = self.config.derivation_contract_paths.get(derivation.target_field)
            if path is None:
                raise ValueError(
                    f"approved {derivation.target_field} derivation requires a bound rule artifact"
                )
            if derivation.semantic_contract_sha256 is None:
                raise ValueError(
                    f"approved {derivation.target_field} derivation has no rule fingerprint"
                )
            payload = _read_bound_json(
                path,
                derivation.semantic_contract_sha256,
                f"{derivation.target_field} derivation contract",
            )
            if payload.get("schema") != "gda.jqdltb_derivation_rule.v1":
                raise ValueError(f"{derivation.target_field} derivation rule schema is invalid")
            if payload.get("target_field") != derivation.target_field:
                raise ValueError(f"{derivation.target_field} derivation rule target drifted")
            if tuple(sorted(str(item) for item in payload.get("source_fields") or [])) != (
                derivation.source_fields
            ):
                raise ValueError(f"{derivation.target_field} derivation source fields drifted")
            if payload.get("semantic_contract_ref") != derivation.semantic_contract_ref:
                raise ValueError(f"{derivation.target_field} derivation reference drifted")
            if payload.get("method") != derivation.method:
                raise ValueError(f"{derivation.target_field} derivation method drifted")
            if derivation.method not in {
                "first non-blank approved source value",
                "first_non_blank_approved_source_value",
            }:
                raise ValueError(f"{derivation.target_field} derivation method is unsupported")
            rules[derivation.target_field] = payload
        return rules

    def _load_geometry_area_rule(
        self,
        contract: JqdltbTransformationContract,
        *,
        source_crs: str | None,
    ) -> dict[str, Any] | None:
        if contract.area_deviation_policy is not JqdltbAreaDeviationPolicy.USE_GEOMETRY:
            return None
        path = self.config.geometry_area_rule_path
        if path is None or contract.geometry_area_rule_sha256 is None:
            raise ValueError("use-geometry policy requires a bound area rule artifact")
        payload = _read_bound_json(
            path,
            contract.geometry_area_rule_sha256,
            "geometry area rule",
        )
        if payload.get("schema") != "gda.jqdltb_geometry_area_rule.v1":
            raise ValueError("geometry area rule schema is invalid")
        if payload.get("rule_ref") != contract.geometry_area_rule_ref:
            raise ValueError("geometry area rule reference drifted")
        if payload.get("method") != "planar_geometry_area_in_source_crs":
            raise ValueError("geometry area rule method is unsupported")
        if payload.get("source_crs") != source_crs or source_crs is None:
            raise ValueError("geometry area rule CRS does not match the source")
        if payload.get("target_field") != "TBMJ":
            raise ValueError("geometry area rule target field is unsupported")
        if payload.get("output_unit") != "square_metre":
            raise ValueError("geometry area rule output unit is unsupported")
        if payload.get("comparison_tolerance") != 0.01:
            raise ValueError("geometry area rule tolerance differs from the frozen quality rule")
        return payload

    def _materialize_features(
        self,
        features: list[dict[str, Any]],
        contract: JqdltbTransformationContract,
        *,
        derivation_rules: Mapping[str, Mapping[str, Any]],
        geometry_area_rule: Mapping[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        derivations = {item.target_field: item for item in contract.derivation_contracts}
        corrections = self._load_corrections(contract)
        materialized: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        area_deviation_count = 0
        area_deviation_quarantined_count = 0
        area_deviation_preserved_count = 0
        area_deviation_replaced_count = 0
        derived_missing_count = 0
        missing_business_correction_count = 0
        used_correction_keys: set[str] = set()
        for index, feature in enumerate(features):
            source_properties = dict(feature.get("properties") or {})
            properties = dict(source_properties)
            key = properties.get(contract.canonical_key)
            reason: str | None = None
            if not _non_blank(key):
                reason = "canonical_key_blank"
            elif str(key) in seen_keys:
                reason = "canonical_key_duplicate"
            else:
                seen_keys.add(str(key))

            source_declared_areas = {
                field: _as_number(properties.get(field))
                for field in JQDLTB_DECLARED_AREA_FIELDS
            }
            declared_areas = dict(source_declared_areas)
            source_requires_correction = any(
                value is None or value <= 0 for value in source_declared_areas.values()
            )
            correction = corrections.get(str(key))
            if correction is not None:
                if not source_requires_correction:
                    raise ValueError(
                        f"business correction targets a source record that already passes: {key}"
                    )
                used_correction_keys.add(str(key))
                for field in JQDLTB_DECLARED_AREA_FIELDS:
                    if _non_blank(correction.get(field)):
                        properties[f"{field}_source"] = properties.get(field)
                        declared_areas[field] = _as_number(correction[field])
                        properties[field] = correction[field]
                properties["gda_area_correction_resource_version_id"] = str(
                    contract.business_correction_resource_version_id
                )
            if any(value is None or value <= 0 for value in declared_areas.values()):
                if contract.nonpositive_area_policy is JqdltbAreaPolicy.QUARANTINE:
                    reason = reason or "nonpositive_declared_area"
                else:
                    missing_business_correction_count += 1
                    reason = reason or "missing_business_correction"

            geometry_area = _geometry_area(feature.get("geometry"))
            outside_tolerance = False
            declared_area = declared_areas["TBMJ"]
            if geometry_area is not None and declared_area is not None and declared_area > 0:
                outside_tolerance = abs(geometry_area - declared_area) / abs(declared_area) > 0.01
            if outside_tolerance:
                area_deviation_count += 1
                if contract.area_deviation_policy is JqdltbAreaDeviationPolicy.QUARANTINE:
                    area_deviation_quarantined_count += 1
                    reason = reason or "area_deviation_outside_tolerance"
                elif contract.area_deviation_policy is JqdltbAreaDeviationPolicy.USE_GEOMETRY:
                    if geometry_area_rule is None:  # pragma: no cover - guarded above
                        raise ValueError("geometry area rule is not loaded")
                    properties["TBMJ_source"] = properties.get("TBMJ")
                    properties["TBMJ"] = geometry_area
                    properties["gda_area_rule_ref"] = contract.geometry_area_rule_ref
                    properties["gda_area_rule_sha256"] = contract.geometry_area_rule_sha256
                    area_deviation_replaced_count += 1
                else:
                    properties["gda_area_deviation_relative_error"] = round(
                        abs(geometry_area - declared_area) / abs(declared_area), 8
                    )
                    area_deviation_preserved_count += 1

            for target, derivation in derivations.items():
                if target in source_properties:
                    properties[f"{target}_source"] = source_properties[target]
                if target not in derivation_rules:  # pragma: no cover - guarded above
                    raise ValueError(f"missing bound derivation rule: {target}")
                value = _first_source_value(source_properties, derivation.source_fields)
                properties[target] = value
                properties[f"{target}_derivation_status"] = derivation.status.value
                properties[f"{target}_derivation_contract_ref"] = derivation.semantic_contract_ref
                if value is None:
                    derived_missing_count += 1
                    reason = reason or f"{target.lower()}_derivation_missing"

            transformed = {
                "type": "Feature",
                "id": feature.get("id", index),
                "properties": _json_value(properties),
                "geometry": _json_value(feature.get("geometry")),
            }
            if reason is not None:
                quarantined.append(
                    {
                        **transformed,
                        "quarantine_reason": reason,
                        "quarantine_source_index": index,
                        "source_properties": _json_value(source_properties),
                    }
                )
            else:
                materialized.append(transformed)
        unused_correction_keys = set(corrections) - used_correction_keys
        if unused_correction_keys:
            raise ValueError(
                "business correction keys do not exist in the source: "
                + ", ".join(sorted(unused_correction_keys))
            )
        stats = {
            "records_read": len(features),
            "records_materialized": len(materialized),
            "records_quarantined": len(quarantined),
            "area_deviation_count": area_deviation_count,
            "area_deviation_quarantined_count": area_deviation_quarantined_count,
            "area_deviation_preserved_count": area_deviation_preserved_count,
            "area_deviation_replaced_count": area_deviation_replaced_count,
            "derived_missing_count": derived_missing_count,
            "missing_business_correction_count": missing_business_correction_count,
            "derivation_rule_bindings": _expected_rule_bindings(contract)[0],
            "geometry_area_rule_binding": _expected_rule_bindings(contract)[1],
            "semantic_candidate_audit_sha256": contract.semantic_candidate_audit_sha256,
        }
        return materialized, quarantined, stats

    def _record_platform_evidence(
        self,
        *,
        run: PlatformRun,
        output_dir: Path,
        report: dict[str, Any],
        contract: JqdltbTransformationContract,
        quality_verdict: str,
        ads_path: Path,
        layer_manifest_path: Path,
    ) -> tuple[UUID | None, UUID | None, UUID | None, UUID | None]:
        """Record the common graph when a full PlatformGateway is available."""
        required = (
            "register_resource",
            "register_resource_version",
            "record_artifact",
            "record_lineage",
            "record_quality_result",
        )
        if not all(hasattr(self.gateway, name) for name in required):
            return None, None, None, None
        output_resource_urn = f"gda://{run.tenant_id}/dataset/chongqing-bizhu-jqdltb-canonical"
        materialization = ObjectMaterializationContract(
            output_resource_urn=output_resource_urn,
            output_resource_kind="dataset",
            authority_system="gis-data-agent",
            authority_locator=ads_path.resolve().as_uri(),
            source_resource_version_id=contract.source_resource_version_id,
            workload_subject=TRANSFORM_WORKLOAD,
            quality_evaluator=TRANSFORM_QUALITY_EVALUATOR,
            quality_rule_version=TRANSFORM_QUALITY_RULE,
            governance_ref={
                "approval_case_ref": (
                    contract.approval_case.approval_case_ref if contract.approval_case else None
                )
            },
            technical_refs=(
                {
                    "contract_sha256": contract.contract_sha256,
                    "plan_sha256": contract.plan_sha256,
                    "semantic_candidate_audit_sha256": (
                        contract.semantic_candidate_audit_sha256
                    ),
                },
            ),
            output_artifact_identity="artifact:jqdltb-ads:v1",
            evidence_artifact_identity="artifact:jqdltb-transformation-evidence:v1",
            lineage_event_identity="lineage:jqdltb-source-to-ads:v1",
            output_artifact_key_prefix="cq_jqdltb_ads",
            evidence_artifact_key_prefix="cq_jqdltb_transform_quality",
            evidence_media_type="application/vnd.gda.jqdltb-transformation-evidence+json",
        )
        layer_manifest = report["layers"]
        output_bundle_sha = canonical_json_fingerprint(layer_manifest)
        evidence = ObjectMaterializationEvidence(
            evidence_document=report,
            output_manifest={
                "schema": TRANSFORM_EXECUTOR_SCHEMA,
                "layers": layer_manifest,
                "bundle_sha256": output_bundle_sha,
            },
            lineage_facets={
                "schema": "gda.jqdltb_transformation_lineage.v1",
                "plan_sha256": contract.plan_sha256,
                "contract_sha256": contract.contract_sha256,
                "semantic_candidate_audit_sha256": (
                    contract.semantic_candidate_audit_sha256
                ),
                "layers": layer_manifest,
            },
            quality_metrics=report["quality"],
            quality_verdict=quality_verdict,
        )
        record = ObjectMaterializationRecorder(materialization, gateway=self.gateway).record(
            run=run,
            bundle_sha256=output_bundle_sha,
            member_count=int(report["records"]["records_materialized"]),
            size_bytes=layer_manifest_path.stat().st_size,
            primary_storage_uri=layer_manifest_path.resolve().as_uri(),
            authority_version_ref={
                "plan_sha256": contract.plan_sha256,
                "contract_sha256": contract.contract_sha256,
            },
            evidence_path=output_dir / "quality-evidence.json",
            evidence=evidence,
        )
        quarantine = output_dir / "quarantine" / "jqdltb.json"
        if quarantine.is_file() and report["records"]["records_quarantined"]:
            quarantine_content = quarantine.read_bytes()
            self.gateway.record_artifact(
                Artifact(
                    tenant_id=run.tenant_id,
                    artifact_id=uuid5(run.run_id, "artifact:jqdltb-quarantine:v1"),
                    artifact_key=f"cq_jqdltb_quarantine_{run.run_id.hex[:12]}",
                    artifact_role=ArtifactRole.QUARANTINE,
                    storage_uri=quarantine.resolve().as_uri(),
                    media_type="application/geo+json",
                    content_sha256=hashlib.sha256(quarantine_content).hexdigest(),
                    size_bytes=len(quarantine_content),
                    run_id=run.run_id,
                    resource_version_id=record.output_resource_version_id,
                    manifest={"records_quarantined": report["records"]["records_quarantined"]},
                    created_by=TRANSFORM_WORKLOAD,
                    created_at=self.clock(),
                )
            )
        return (
            record.output_resource_version_id,
            record.output_artifact_id,
            record.quality_result_id,
            record.lineage_event_id,
        )

    def execute(self, command: JqdltbTransformationCommand) -> JqdltbTransformationResult:
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        self._validate_run(run, command)
        contract = command.contract
        if (
            contract.tenant_id != command.tenant_id
            or contract.source_resource_version_id != command.source_resource_version_id
        ):
            raise ValueError("transformation contract does not match command source")
        self._validate_scheduler_plan(run, contract)
        diagnostic = self._load_diagnostic()
        semantic_candidate_audit = self._load_semantic_candidate_audit(contract)
        archive_sha, bundle_sha, standard_ref, standard_fp = self._expected(contract)
        # This is intentionally before _output_dir creation or any source-derived write.
        self.approval_service.validate_execution(
            contract,
            diagnostic=diagnostic,
            archive_sha256=archive_sha,
            bundle_sha256=bundle_sha,
            standard_version_ref=standard_ref,
            standard_fingerprint=standard_fp,
            source_resource_version_id=command.source_resource_version_id,
            semantic_candidate_audit=semantic_candidate_audit,
            now=self.clock(),
        )
        source_identity_before = self._validate_source_bundle_identity(
            self.config.source_path,
            bundle_sha,
        )
        features, source_crs = _read_features(self.config.source_path)
        source_identity_after = self._validate_source_bundle_identity(
            self.config.source_path,
            bundle_sha,
        )
        if source_identity_before != source_identity_after:
            raise ValueError("JQDLTB source bundle changed while it was being read")
        source_identity = source_identity_after
        derivation_rules = self._load_derivation_rules(contract)
        geometry_area_rule = self._load_geometry_area_rule(
            contract,
            source_crs=source_crs,
        )
        output_dir = self._output_dir(command)
        if replay := self._replayed(output_dir, command):
            return replay
        if output_dir.exists():
            existing = output_dir / "transformation-evidence.json"
            if not existing.is_file():
                raise ValueError("existing JQDLTB output has no transformation evidence")
            existing_report = json.loads(existing.read_text(encoding="utf-8"))
            if existing_report.get("contract_sha256") != contract.contract_sha256:
                raise ValueError("existing JQDLTB output has a different contract")
            # A failed platform-evidence commit is retryable. Remove only this
            # content-addressed candidate after the contract gate has passed.
            if (
                not isinstance(existing_report.get("result"), Mapping)
                or existing_report["result"].get("status") != "completed"
            ):
                shutil.rmtree(output_dir)

        materialized, quarantined, stats = self._materialize_features(
            features,
            contract,
            derivation_rules=derivation_rules,
            geometry_area_rule=geometry_area_rule,
        )
        quality_checks = self._quality_checks(
            features=features,
            materialized=materialized,
            quarantined=quarantined,
            stats=stats,
            contract=contract,
        )
        quality_verdict = (
            "passed" if all(item["status"] == "passed" for item in quality_checks) else "failed"
        )
        now = self.clock()
        layer_data = {
            "raw": _feature_collection(features),
            "ods": _feature_collection(materialized),
            "dim": _feature_collection(materialized),
            "dwd": _feature_collection(materialized),
            "ads": _feature_collection(materialized),
            "quarantine": _feature_collection(quarantined),
        }
        layers = {
            name: {
                "relative_path": f"{name}/jqdltb.json",
                "records": len(value["features"]),
                "sha256": canonical_json_fingerprint(value),
            }
            for name, value in layer_data.items()
        }
        lineage_document = {
            "schema": "gda.jqdltb_transformation_lineage.v1",
            "source_resource_version_id": str(contract.source_resource_version_id),
            "contract_sha256": contract.contract_sha256,
            "semantic_candidate_audit_sha256": contract.semantic_candidate_audit_sha256,
            "events": [
                {"event_type": "copy", "from": "source", "to": "raw"},
                {"event_type": "derive", "from": "raw", "to": "ods"},
                {"event_type": "derive", "from": "ods", "to": "dim"},
                {"event_type": "derive", "from": "ods", "to": "dwd"},
                {"event_type": "publish_candidate", "from": "dwd", "to": "ads"},
            ],
        }
        transformation_artifact = {
            "schema": "gda.jqdltb_transformation_artifact.v1",
            "plan_sha256": contract.plan_sha256,
            "contract_sha256": contract.contract_sha256,
            "semantic_candidate_audit_sha256": contract.semantic_candidate_audit_sha256,
            "approval_case_ref": (
                contract.approval_case.approval_case_ref if contract.approval_case else None
            ),
            "source_resource_version_id": str(contract.source_resource_version_id),
            "layer_manifest": layers,
        }
        report: dict[str, Any] = {
            "schema": "gda.jqdltb_transformation_evidence.v1",
            "contract_sha256": contract.contract_sha256,
            "plan_sha256": contract.plan_sha256,
            "semantic_candidate_audit_sha256": contract.semantic_candidate_audit_sha256,
            "approval_case_ref": (
                contract.approval_case.approval_case_ref if contract.approval_case else None
            ),
            "source_resource_version_id": str(contract.source_resource_version_id),
            "source_identity": source_identity,
            "evaluated_at": now.isoformat(),
            "records": stats,
            "layers": layers,
            "quality": {
                "scope": "post_transformation_candidate_full_dataset",
                "rule_version": TRANSFORM_QUALITY_RULE,
                "verdict": quality_verdict,
                "checks": quality_checks,
                "promotion_ready": False,
                "data_product_version_created": False,
            },
            "lineage": lineage_document,
            "transformation_artifact": transformation_artifact,
            "result": {},
        }
        staging = output_dir.parent / f".{output_dir.name}.{os.getpid()}.tmp"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            for name, value in layer_data.items():
                target = staging / name / "jqdltb.json"
                target.parent.mkdir(parents=True)
                _write_json(target, value)
            _write_json(staging / "lineage" / "jqdltb.json", lineage_document)
            _write_json(staging / "transformation-artifact.json", transformation_artifact)
            _write_json(staging / "layer-manifest.json", layers)
            _write_json(staging / "transformation-evidence.json", report)
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            if output_dir.exists():
                existing = output_dir / "transformation-evidence.json"
                if (
                    not existing.is_file()
                    or existing.read_bytes()
                    != (staging / "transformation-evidence.json").read_bytes()
                ):
                    raise ValueError("existing JQDLTB output conflicts with this contract")
                shutil.rmtree(staging)
            else:
                os.replace(staging, output_dir)
            ads_path = output_dir / "ads" / "jqdltb.json"
            try:
                (
                    output_version_id,
                    output_artifact_id,
                    quality_id,
                    lineage_id,
                ) = self._record_platform_evidence(
                    run=run,
                    output_dir=output_dir,
                    report=report,
                    contract=contract,
                    quality_verdict=quality_verdict,
                    ads_path=ads_path,
                    layer_manifest_path=output_dir / "layer-manifest.json",
                )
            except Exception as exc:
                # Keep the candidate for diagnosis, but make its state explicit so
                # a retry can safely replace it and no caller mistakes it for a
                # completed materialization.
                report["platform_evidence"] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
                report["result"] = {
                    "status": "failed",
                    "run_id": str(run.run_id),
                    "source_resource_version_id": str(command.source_resource_version_id),
                    "quality_verdict": quality_verdict,
                    "records_read": stats["records_read"],
                    "records_materialized": stats["records_materialized"],
                    "records_quarantined": stats["records_quarantined"],
                    "promotion_ready": False,
                    "data_product_version_created": False,
                }
                _write_json(output_dir / "transformation-evidence.json", report)
                raise
            result = JqdltbTransformationResult(
                status="completed",
                run_id=run.run_id,
                source_resource_version_id=command.source_resource_version_id,
                output_resource_version_id=output_version_id,
                output_artifact_id=output_artifact_id,
                quality_result_id=quality_id,
                lineage_event_id=lineage_id,
                output_root=str(output_dir),
                records_read=stats["records_read"],
                records_materialized=stats["records_materialized"],
                records_quarantined=stats["records_quarantined"],
                quality_verdict=quality_verdict,
                promotion_ready=False,
                data_product_version_created=False,
            )
            report["result"] = result.model_dump(mode="json", by_alias=True)
            _write_json(output_dir / "transformation-evidence.json", report)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return result


__all__ = [
    "JqdltbTransformationCommand",
    "JqdltbTransformationExecutor",
    "JqdltbTransformationExecutorConfig",
    "JqdltbTransformationResult",
]
