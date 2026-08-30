"""Authenticated real-data executor for controlled DolphinScheduler tasks."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import stat
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import uvicorn
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .data_products.central_buildings_ods_dataops import (
    CentralBuildingsOdsCommand,
    CentralBuildingsOdsExecutor,
    CentralBuildingsOdsExecutorConfig,
)
from .data_products.chongqing_dem_ods_dataops import (
    ChongqingDemOdsCommand,
    ChongqingDemOdsExecutor,
    ChongqingDemOdsExecutorConfig,
)
from .data_products.osm_roads_dataops import (
    OsmRoadsDataOpsCommand,
    OsmRoadsDataOpsExecutor,
    OsmRoadsExecutorConfig,
)
from .data_products.osm_roads_lakehouse_dataops import (
    OsmRoadsLakehouseCommand,
    OsmRoadsLakehouseExecutor,
    OsmRoadsLakehouseExecutorConfig,
)
from .jqdltb_transformation_executor import (
    JqdltbTransformationCommand,
    JqdltbTransformationExecutor,
    JqdltbTransformationExecutorConfig,
)
from .platform_contracts import (
    Artifact,
    ArtifactRole,
    PlatformRun,
    QualityResult,
    RunStatus,
    canonical_json_bytes,
    quality_result_fingerprint,
)
from .platform_gateway import GatewayNotFoundError, PlatformGateway
from .standards_platform.application.source_onboarding import (
    evaluate_vector_source_onboarding,
)

EXECUTOR_SCHEMA = "gda.jqdltb_dataops_executor.v1"
EVIDENCE_SCHEMA = "gda.jqdltb_authoritative_quality_evidence.v1"
QUALITY_RULE_REF = "gda://local-dev/quality_rule/chongqing-jqdltb-full-audit:v1"
QUALITY_EVALUATOR = "workload:jqdltb-quality-evaluator"
EXPECTED_RUN_SUBJECT = "workload:dolphinscheduler-gda-dataops"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JqdltbAuditCommand(_FrozenModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    run_id: UUID
    source_resource_version_id: UUID


class JqdltbAuditResult(_FrozenModel):
    schema_name: str = Field(default=EXECUTOR_SCHEMA, alias="schema")
    status: str
    run_id: UUID
    source_resource_version_id: UUID
    quality_result_id: UUID
    evidence_artifact_id: UUID
    verdict: str
    records_scanned: int = Field(ge=0)
    failed_check_ids: tuple[str, ...]
    blocked_check_ids: tuple[str, ...]
    replayed: bool = False
    data_product_version_created: bool = False


class ExecutorConfig(_FrozenModel):
    token_file: Path
    dataset_root: Path
    protocol_path: Path
    evidence_root: Path

    def validate_runtime(self) -> None:
        for path, label in (
            (self.token_file, "token file"),
            (self.protocol_path, "protocol file"),
        ):
            if not path.is_absolute() or not path.is_file():
                raise ValueError(f"{label} must be an existing absolute file")
        if stat.S_IMODE(self.token_file.stat().st_mode) & 0o077:
            raise ValueError("executor token file must not be group/world accessible")
        if not self.dataset_root.is_absolute() or not self.dataset_root.is_dir():
            raise ValueError("dataset root must be an existing absolute directory")
        if not self.evidence_root.is_absolute():
            raise ValueError("evidence root must be absolute")


def _actor_ref(run: PlatformRun) -> str:
    return f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"


def _quality_identity(run_id: UUID) -> UUID:
    return uuid5(run_id, f"quality:{QUALITY_RULE_REF}")


def _artifact_identity(run_id: UUID) -> UUID:
    return uuid5(run_id, f"artifact:{EVIDENCE_SCHEMA}")


def _report_findings(report: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    checks = report["quality"]["checks"]
    failed = tuple(sorted(str(check["id"]) for check in checks if check["status"] == "failed"))
    blocked = tuple(
        sorted(str(check["id"]) for check in checks if check["status"] == "blocked")
    )
    return failed, blocked


def _quality_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    failed, blocked = _report_findings(report)
    return {
        "protocol_id": report["protocol_id"],
        "records_scanned": report["evaluation_policy"]["records_scanned"],
        "full_dataset_validated": report["evaluation_policy"][
            "full_dataset_validated"
        ],
        "source_quality_verdict": report["quality"]["source_quality_verdict"],
        "standardization_status": report["standardization"]["status"],
        "check_summary": report["quality"]["summary"],
        "failed_check_ids": list(failed),
        "blocked_check_ids": list(blocked),
        "missing_target_fields": list(report["standardization"]["missing_target_fields"]),
    }


class JqdltbDataOpsExecutor:
    def __init__(
        self,
        config: ExecutorConfig,
        *,
        gateway: PlatformGateway | None = None,
        evaluator: Callable[..., dict[str, Any]] = evaluate_vector_source_onboarding,
        clock: Callable[[], datetime] | None = None,
    ):
        config.validate_runtime()
        self.config = config
        self.gateway = gateway or PlatformGateway()
        self.evaluator = evaluator
        self.clock = clock or (lambda: datetime.now(UTC))

    def _load_protocol(self) -> dict[str, Any]:
        value = json.loads(self.config.protocol_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JQDLTB protocol must be a JSON object")
        return value

    @staticmethod
    def _validate_run(run: PlatformRun, command: JqdltbAuditCommand) -> None:
        if run.orchestration_class.value != "dataops":
            raise ValueError("JQDLTB executor only accepts DataOps runs")
        if _actor_ref(run) != EXPECTED_RUN_SUBJECT:
            raise ValueError("run workload identity does not match the executor contract")
        if run.status not in {
            RunStatus.DISPATCHING,
            RunStatus.RUNNING,
            RunStatus.RECONCILING,
        }:
            raise ValueError("run is not in an executable state")
        bindings = {binding.binding_name: binding for binding in run.input_bindings}
        source = bindings.get("source")
        if source is None or source.resource_version_id != command.source_resource_version_id:
            raise ValueError("source binding does not match the immutable PlatformRun input")

    def _existing_result(
        self, command: JqdltbAuditCommand
    ) -> JqdltbAuditResult | None:
        try:
            quality = self.gateway.get_quality_result(
                command.tenant_id, _quality_identity(command.run_id)
            )
        except GatewayNotFoundError:
            return None
        if quality.run_id != command.run_id:
            raise ValueError("stored QualityResult does not match the requested run")
        metrics = quality.metrics
        return JqdltbAuditResult(
            status="completed",
            run_id=command.run_id,
            source_resource_version_id=quality.resource_version_id,
            quality_result_id=quality.quality_result_id,
            evidence_artifact_id=quality.evidence_artifact_id,
            verdict=quality.verdict.value,
            records_scanned=int(metrics["records_scanned"]),
            failed_check_ids=tuple(metrics.get("failed_check_ids") or ()),
            blocked_check_ids=tuple(metrics.get("blocked_check_ids") or ()),
            replayed=True,
        )

    def execute(self, command: JqdltbAuditCommand) -> JqdltbAuditResult:
        run = self.gateway.get_run(command.tenant_id, command.run_id)
        self._validate_run(run, command)
        if replay := self._existing_result(command):
            return replay

        report = self.evaluator(
            protocol=self._load_protocol(), dataset_root=self.config.dataset_root
        )
        failed, blocked = _report_findings(report)
        metrics = _quality_metrics(report)
        verdict = (
            "passed"
            if not failed
            and not blocked
            and report["quality"]["source_quality_verdict"] == "passed"
            and report["standardization"]["status"] == "ready"
            else "failed"
        )
        evaluated_at = self.clock()
        evidence_document = {
            "schema": EVIDENCE_SCHEMA,
            "run_id": str(run.run_id),
            "definition_version_id": str(run.definition_version_id),
            "source_resource_version_id": str(command.source_resource_version_id),
            "authoritative_quality_result": True,
            "quality_rule_ref": QUALITY_RULE_REF,
            "quality_evaluator": QUALITY_EVALUATOR,
            "verdict": verdict,
            "metrics": metrics,
            "source_scan": report,
            "data_product_version_created": False,
            "evaluated_at": evaluated_at.isoformat(),
        }
        content = canonical_json_bytes(evidence_document)
        evidence_path = (
            self.config.evidence_root
            / command.tenant_id
            / str(command.run_id)
            / "jqdltb-quality-evidence.json"
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = evidence_path.with_name(f".{evidence_path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(content)
        temporary.chmod(0o640)
        os.replace(temporary, evidence_path)

        artifact_id = _artifact_identity(run.run_id)
        artifact = Artifact(
            tenant_id=run.tenant_id,
            artifact_id=artifact_id,
            artifact_key=f"jqdltb-quality-{run.run_id.hex[:16]}",
            artifact_role=ArtifactRole.EVIDENCE,
            storage_uri=evidence_path.resolve().as_uri(),
            media_type="application/vnd.gda.authoritative-quality-evidence+json",
            content_sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            run_id=run.run_id,
            resource_version_id=command.source_resource_version_id,
            manifest={
                "schema": EVIDENCE_SCHEMA,
                "protocol_id": report["protocol_id"],
                "authoritative_quality_result": True,
                "verdict": verdict,
                "records_scanned": metrics["records_scanned"],
                "failed_check_ids": list(failed),
                "blocked_check_ids": list(blocked),
                "data_product_version_created": False,
            },
            created_by=QUALITY_EVALUATOR,
            created_at=evaluated_at,
        )
        self.gateway.record_artifact(artifact)

        quality_id = _quality_identity(run.run_id)
        quality = QualityResult(
            tenant_id=run.tenant_id,
            quality_result_id=quality_id,
            run_id=run.run_id,
            resource_version_id=command.source_resource_version_id,
            rule_version_ref=QUALITY_RULE_REF,
            verdict=verdict,
            metrics=metrics,
            evidence_artifact_id=artifact_id,
            result_sha256=quality_result_fingerprint(
                tenant_id=run.tenant_id,
                run_id=run.run_id,
                resource_version_id=command.source_resource_version_id,
                rule_version_ref=QUALITY_RULE_REF,
                verdict=verdict,
                metrics=metrics,
                evidence_artifact_id=artifact_id,
                evaluated_by=QUALITY_EVALUATOR,
                evaluated_at=evaluated_at,
            ),
            evaluated_by=QUALITY_EVALUATOR,
            evaluated_at=evaluated_at,
        )
        self.gateway.record_quality_result(quality)
        return JqdltbAuditResult(
            status="completed",
            run_id=run.run_id,
            source_resource_version_id=command.source_resource_version_id,
            quality_result_id=quality_id,
            evidence_artifact_id=artifact_id,
            verdict=verdict,
            records_scanned=int(metrics["records_scanned"]),
            failed_check_ids=failed,
            blocked_check_ids=blocked,
        )


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization") or ""
    prefix = "Bearer "
    return value[len(prefix) :] if value.startswith(prefix) else None


def create_app(
    service: JqdltbDataOpsExecutor,
    osm_service: OsmRoadsDataOpsExecutor | None = None,
    lakehouse_service: OsmRoadsLakehouseExecutor | None = None,
    building_ods_service: CentralBuildingsOdsExecutor | None = None,
    dem_ods_service: ChongqingDemOdsExecutor | None = None,
    jqdltb_transformation_service: JqdltbTransformationExecutor | None = None,
) -> Starlette:
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "schema": EXECUTOR_SCHEMA,
                "source_configured": True,
                "osm_roads_configured": osm_service is not None,
                "default_lakehouse_configured": lakehouse_service is not None,
                "building_ods_configured": building_ods_service is not None,
                "dem_ods_configured": dem_ods_service is not None,
                "jqdltb_transformation_configured": jqdltb_transformation_service is not None,
                "database_authority": "gda-control-postgresql",
            }
        )

    async def execute(request: Request) -> JSONResponse:
        expected = service.config.token_file.read_text(encoding="utf-8").strip()
        actual = _bearer_token(request)
        if actual is None or not hmac.compare_digest(actual, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            payload = await request.json()
            command = JqdltbAuditCommand.model_validate(payload)
            result = await asyncio.to_thread(service.execute, command)
        except Exception as exc:
            return JSONResponse(
                {"error": "execution_failed", "error_type": type(exc).__name__},
                status_code=422,
            )
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    async def execute_osm_roads(request: Request) -> JSONResponse:
        if osm_service is None:
            return JSONResponse(
                {"error": "osm_roads_executor_not_configured"}, status_code=503
            )
        expected = service.config.token_file.read_text(encoding="utf-8").strip()
        actual = _bearer_token(request)
        if actual is None or not hmac.compare_digest(actual, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            payload = await request.json()
            command = OsmRoadsDataOpsCommand.model_validate(payload)
            result = await asyncio.to_thread(osm_service.execute, command)
        except Exception as exc:
            return JSONResponse(
                {"error": "execution_failed", "error_type": type(exc).__name__},
                status_code=422,
            )
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    async def execute_osm_roads_lakehouse(request: Request) -> JSONResponse:
        if lakehouse_service is None:
            return JSONResponse(
                {"error": "osm_roads_lakehouse_executor_not_configured"},
                status_code=503,
            )
        expected = service.config.token_file.read_text(encoding="utf-8").strip()
        actual = _bearer_token(request)
        if actual is None or not hmac.compare_digest(actual, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            payload = await request.json()
            command = OsmRoadsLakehouseCommand.model_validate(payload)
            result = await asyncio.to_thread(lakehouse_service.execute, command)
        except Exception as exc:
            return JSONResponse(
                {"error": "execution_failed", "error_type": type(exc).__name__},
                status_code=422,
            )
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    async def execute_central_buildings_ods(request: Request) -> JSONResponse:
        if building_ods_service is None:
            return JSONResponse(
                {"error": "central_buildings_ods_executor_not_configured"},
                status_code=503,
            )
        expected = service.config.token_file.read_text(encoding="utf-8").strip()
        actual = _bearer_token(request)
        if actual is None or not hmac.compare_digest(actual, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            payload = await request.json()
            command = CentralBuildingsOdsCommand.model_validate(payload)
            result = await asyncio.to_thread(building_ods_service.execute, command)
        except Exception as exc:
            return JSONResponse(
                {"error": "execution_failed", "error_type": type(exc).__name__},
                status_code=422,
            )
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    async def execute_chongqing_dem_ods(request: Request) -> JSONResponse:
        if dem_ods_service is None:
            return JSONResponse(
                {"error": "chongqing_dem_ods_executor_not_configured"},
                status_code=503,
            )
        expected = service.config.token_file.read_text(encoding="utf-8").strip()
        actual = _bearer_token(request)
        if actual is None or not hmac.compare_digest(actual, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            payload = await request.json()
            command = ChongqingDemOdsCommand.model_validate(payload)
            result = await asyncio.to_thread(dem_ods_service.execute, command)
        except Exception as exc:
            return JSONResponse(
                {"error": "execution_failed", "error_type": type(exc).__name__},
                status_code=422,
            )
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    async def execute_chongqing_jqdltb_transformation(request: Request) -> JSONResponse:
        if jqdltb_transformation_service is None:
            return JSONResponse(
                {"error": "chongqing_jqdltb_transformation_executor_not_configured"},
                status_code=503,
            )
        expected = service.config.token_file.read_text(encoding="utf-8").strip()
        actual = _bearer_token(request)
        if actual is None or not hmac.compare_digest(actual, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            payload = await request.json()
            command = JqdltbTransformationCommand.model_validate(payload)
            result = await asyncio.to_thread(jqdltb_transformation_service.execute, command)
        except Exception as exc:
            return JSONResponse(
                {"error": "execution_failed", "error_type": type(exc).__name__},
                status_code=422,
            )
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/v1/execute/chongqing-jqdltb-audit", execute, methods=["POST"]),
            Route(
                "/v1/execute/chongqing-osm-roads-layered-publish",
                execute_osm_roads,
                methods=["POST"],
            ),
            Route(
                "/v1/execute/chongqing-osm-roads-default-lakehouse",
                execute_osm_roads_lakehouse,
                methods=["POST"],
            ),
            Route(
                "/v1/execute/chongqing-central-buildings-ods",
                execute_central_buildings_ods,
                methods=["POST"],
            ),
            Route(
                "/v1/execute/chongqing-dem-ods",
                execute_chongqing_dem_ods,
                methods=["POST"],
            ),
            Route(
                "/v1/execute/chongqing-jqdltb-transformation",
                execute_chongqing_jqdltb_transformation,
                methods=["POST"],
            ),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--osm-source", type=Path)
    parser.add_argument("--osm-output-root", type=Path)
    parser.add_argument("--osm-lakehouse-repo-root", type=Path)
    parser.add_argument("--osm-lakehouse-report-root", type=Path)
    parser.add_argument(
        "--osm-lakehouse-runtime-image",
        default="gisdataagent/mmfe-spark-runtime:local",
    )
    parser.add_argument(
        "--osm-lakehouse-docker-network",
        default="gisdataagent_agent-net",
    )
    parser.add_argument(
        "--osm-lakehouse-java-home",
        default="/usr/lib/jvm/java-17-openjdk-arm64",
    )
    parser.add_argument("--building-ods-repo-root", type=Path)
    parser.add_argument("--building-ods-report-root", type=Path)
    parser.add_argument(
        "--building-ods-runtime-image",
        default="gisdataagent/mmfe-spark-runtime:local",
    )
    parser.add_argument(
        "--building-ods-docker-network",
        default="gisdataagent_agent-net",
    )
    parser.add_argument(
        "--building-ods-java-home",
        default="/usr/lib/jvm/java-17-openjdk-arm64",
    )
    parser.add_argument("--dem-ods-source", type=Path)
    parser.add_argument("--dem-ods-output-root", type=Path)
    parser.add_argument("--dem-ods-report-root", type=Path)
    parser.add_argument("--jqdltb-transformation-source", type=Path)
    parser.add_argument("--jqdltb-transformation-output-root", type=Path)
    parser.add_argument("--jqdltb-transformation-diagnostic", type=Path)
    parser.add_argument("--jqdltb-transformation-semantic-audit", type=Path)
    parser.add_argument("--jqdltb-transformation-correction", type=Path)
    parser.add_argument("--jqdltb-transformation-archive-sha256")
    parser.add_argument("--jqdltb-transformation-bundle-sha256")
    parser.add_argument("--jqdltb-transformation-standard-version-ref")
    parser.add_argument("--jqdltb-transformation-standard-fingerprint")
    parser.add_argument("--jqdltb-transformation-sjnf-rule", type=Path)
    parser.add_argument("--jqdltb-transformation-mssm-rule", type=Path)
    parser.add_argument("--jqdltb-transformation-geometry-area-rule", type=Path)
    parser.add_argument(
        "--dem-ods-endpoint-url",
        default=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:9000"),
    )
    parser.add_argument(
        "--dem-ods-access-key-id",
        default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"),
    )
    parser.add_argument(
        "--dem-ods-secret-access-key",
        default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ExecutorConfig(
        token_file=args.token_file.resolve(),
        dataset_root=args.dataset_root.resolve(),
        protocol_path=args.protocol.resolve(),
        evidence_root=args.evidence_root.resolve(),
    )
    if (args.osm_source is None) != (args.osm_output_root is None):
        raise ValueError("--osm-source and --osm-output-root must be supplied together")
    osm_service = None
    if args.osm_source is not None:
        osm_service = OsmRoadsDataOpsExecutor(
            OsmRoadsExecutorConfig(
                source_path=args.osm_source.resolve(),
                output_root=args.osm_output_root.resolve(),
            )
        )
    if (args.osm_lakehouse_repo_root is None) != (
        args.osm_lakehouse_report_root is None
    ):
        raise ValueError(
            "--osm-lakehouse-repo-root and --osm-lakehouse-report-root "
            "must be supplied together"
        )
    lakehouse_service = None
    if args.osm_lakehouse_repo_root is not None:
        lakehouse_service = OsmRoadsLakehouseExecutor(
            OsmRoadsLakehouseExecutorConfig(
                repo_root=args.osm_lakehouse_repo_root.resolve(),
                report_root=args.osm_lakehouse_report_root.resolve(),
                runtime_image=args.osm_lakehouse_runtime_image,
                docker_network=args.osm_lakehouse_docker_network,
                java_home=args.osm_lakehouse_java_home,
            )
        )
    if (args.building_ods_repo_root is None) != (
        args.building_ods_report_root is None
    ):
        raise ValueError(
            "--building-ods-repo-root and --building-ods-report-root "
            "must be supplied together"
        )
    building_ods_service = None
    if args.building_ods_repo_root is not None:
        building_ods_service = CentralBuildingsOdsExecutor(
            CentralBuildingsOdsExecutorConfig(
                repo_root=args.building_ods_repo_root.resolve(),
                report_root=args.building_ods_report_root.resolve(),
                runtime_image=args.building_ods_runtime_image,
                docker_network=args.building_ods_docker_network,
                java_home=args.building_ods_java_home,
            )
        )
    dem_paths = (
        args.dem_ods_source,
        args.dem_ods_output_root,
        args.dem_ods_report_root,
    )
    if any(path is not None for path in dem_paths) and not all(
        path is not None for path in dem_paths
    ):
        raise ValueError(
            "--dem-ods-source, --dem-ods-output-root and --dem-ods-report-root "
            "must be supplied together"
        )
    dem_ods_service = None
    if args.dem_ods_source is not None:
        dem_ods_service = ChongqingDemOdsExecutor(
            ChongqingDemOdsExecutorConfig(
                source_path=args.dem_ods_source.resolve(),
                output_root=args.dem_ods_output_root.resolve(),
                report_root=args.dem_ods_report_root.resolve(),
                endpoint_url=args.dem_ods_endpoint_url,
                access_key_id=args.dem_ods_access_key_id,
                secret_access_key=args.dem_ods_secret_access_key,
            )
        )
    transformation_paths = (
        args.jqdltb_transformation_source,
        args.jqdltb_transformation_output_root,
        args.jqdltb_transformation_diagnostic,
    )
    if any(path is not None for path in transformation_paths) and not all(
        path is not None for path in transformation_paths
    ):
        raise ValueError(
            "--jqdltb-transformation-source, --jqdltb-transformation-output-root and "
            "--jqdltb-transformation-diagnostic must be supplied together"
        )
    jqdltb_transformation_service = None
    if args.jqdltb_transformation_source is not None:
        jqdltb_transformation_service = JqdltbTransformationExecutor(
            JqdltbTransformationExecutorConfig(
                source_path=args.jqdltb_transformation_source.resolve(),
                output_root=args.jqdltb_transformation_output_root.resolve(),
                diagnostic_path=args.jqdltb_transformation_diagnostic.resolve(),
                semantic_candidate_audit_path=(
                    args.jqdltb_transformation_semantic_audit.resolve()
                    if args.jqdltb_transformation_semantic_audit is not None
                    else None
                ),
                correction_path=(
                    args.jqdltb_transformation_correction.resolve()
                    if args.jqdltb_transformation_correction is not None
                    else None
                ),
                archive_sha256=args.jqdltb_transformation_archive_sha256,
                bundle_sha256=args.jqdltb_transformation_bundle_sha256,
                standard_version_ref=args.jqdltb_transformation_standard_version_ref,
                standard_fingerprint=args.jqdltb_transformation_standard_fingerprint,
                derivation_contract_paths={
                    target: path.resolve()
                    for target, path in {
                        "SJNF": args.jqdltb_transformation_sjnf_rule,
                        "MSSM": args.jqdltb_transformation_mssm_rule,
                    }.items()
                    if path is not None
                },
                geometry_area_rule_path=(
                    args.jqdltb_transformation_geometry_area_rule.resolve()
                    if args.jqdltb_transformation_geometry_area_rule is not None
                    else None
                ),
            )
        )
    app = create_app(
        JqdltbDataOpsExecutor(config),
        osm_service,
        lakehouse_service,
        building_ods_service,
        dem_ods_service,
        jqdltb_transformation_service,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
