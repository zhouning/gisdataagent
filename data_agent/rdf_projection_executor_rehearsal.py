"""Isolated Fuseki and PostgreSQL rehearsal for RDF projection repair."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import Field, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from .cross_store_projection_authority import (
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityConfigurationError,
)
from .cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from .cross_store_projection_recovery import InMemoryProjectionRecoveryLedger
from .cross_store_projection_recovery_worker import (
    ProjectionProviderFailure,
    ProjectionRecoveryWorker,
    RegisteredExecutorProjectionProvider,
)
from .ontology.package_reader import OntologyPackageReader
from .platform_contracts import FrozenContract, canonical_json_fingerprint
from .rdf_projection_executor import (
    RDFProjectionExecutionError,
    RDFProjectionRepairExecutor,
    RDFProjectionTarget,
    RDFProjectionTargetRegistry,
)
from .rdf_projection_service import (
    RDFProjectionRepairRequest,
    RDFProjectionServiceConfigurationError,
    RDFProjectionServiceConflictError,
    execute_rdf_projection_repair,
)

_MIGRATIONS = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "169_cross_store_projection_checkpoint_authority.sql",
)
_DEFAULT_IMAGE = "gisdataagent-ontology-fuseki:5.5.0-nr-2.3.0"
_DEFAULT_PACKAGE = (
    Path(__file__).resolve().parent / "ontology" / "packages" / "natural_resource_one_map" / "2.3.0"
)
_FUSEKI_CONFIG = (
    Path(__file__).resolve().parents[1] / "docker" / "ontology-fuseki" / "rehearsal-config.ttl"
)


class RDFProjectionExecutorRehearsalReport(FrozenContract):
    schema_id: str = "gda.rdf-projection-executor-rehearsal.v2"
    checked_at: datetime
    database_scope: str = "temporary_database_only"
    fuseki_scope: str = "temporary_container_and_volume_only"
    atomicity_scope: str = (
        "fuseki_target_and_receipt_single_update_request_checkpoint_authority_separate"
    )
    fuseki_image: str
    fuseki_image_id: str
    migration_ids: tuple[str, ...]
    ontology_key: str
    ontology_semantic_version: str
    ontology_package_id: str
    ontology_package_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rdf_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rdf_triple_count: int = Field(ge=1)
    checks: dict[str, bool]
    passed: bool
    failure_reasons: tuple[str, ...]
    technical_baseline_status: str = "technical_baseline_unreviewed"
    decision_status: str = "assisted_precheck_not_for_production_decision"
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _hash(self) -> RDFProjectionExecutorRehearsalReport:
        payload = self.model_dump(mode="json")
        expected = canonical_json_fingerprint(
            {key: value for key, value in payload.items() if key != "report_sha256"}
        )
        if self.report_sha256 != expected:
            raise ValueError("RDF executor rehearsal report fingerprint is invalid")
        return self


class _TemporaryPostgres:
    def __init__(self, admin_url: str) -> None:
        parsed = make_url(admin_url)
        self.maintenance_url = parsed.set(database=parsed.database or "postgres")
        self.database = f"gda_rdf_exec_{uuid4().hex[:12]}"
        self.admin_engine: Engine | None = None
        self.engine: Engine | None = None

    def create(self) -> None:
        self.admin_engine = create_engine(
            self.maintenance_url,
            isolation_level="AUTOCOMMIT",
        )
        with self.admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{self.database}"')
        self.engine = create_engine(self.maintenance_url.set(database=self.database))
        for filename in _MIGRATIONS:
            migration = Path(__file__).resolve().parent / "migrations" / filename
            with self.engine.begin() as connection:
                connection.exec_driver_sql(migration.read_text(encoding="utf-8").replace("%", "%%"))

    def drop_and_verify(self) -> bool:
        if self.engine is not None:
            self.engine.dispose()
        verifier = self.admin_engine or create_engine(
            self.maintenance_url,
            isolation_level="AUTOCOMMIT",
        )
        try:
            with verifier.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database AND pid <> pg_backend_pid()"
                    ),
                    {"database": self.database},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{self.database}"')
                remaining = connection.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname = :database"),
                    {"database": self.database},
                ).scalar_one()
            return remaining == 0
        finally:
            verifier.dispose()


class _TemporaryFuseki:
    def __init__(self, image: str) -> None:
        suffix = uuid4().hex[:12]
        self.image = image
        self.container = f"gda-rdf-exec-{suffix}"
        self.volume = f"gda-rdf-exec-{suffix}"
        self.endpoint: str | None = None
        self.update_endpoint: str | None = None
        self.image_id = ""

    @staticmethod
    def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("docker", *arguments),
            check=check,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def start(self) -> None:
        if not _FUSEKI_CONFIG.is_file():
            raise RuntimeError("isolated Fuseki rehearsal config is missing")
        image = self._docker("image", "inspect", self.image, "--format", "{{.Id}}")
        self.image_id = image.stdout.strip()
        self._docker("volume", "create", self.volume)
        self._docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            self.container,
            "--publish",
            "127.0.0.1::3030",
            "--mount",
            f"type=volume,source={self.volume},target=/fuseki",
            "--mount",
            (f"type=bind,source={_FUSEKI_CONFIG},target=/tmp/gda-rehearsal-config.ttl,readonly"),
            "--entrypoint",
            "/opt/fuseki/fuseki-server",
            self.image,
            "--config=/tmp/gda-rehearsal-config.ttl",
            "--port=3030",
        )
        port = self._docker("port", self.container, "3030/tcp").stdout.strip()
        host_port = port.rsplit(":", 1)[-1]
        base_url = f"http://127.0.0.1:{host_port}"
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{base_url}/$/ping", timeout=2)
                if response.is_success:
                    self.endpoint = f"{base_url}/ontology/data?default"
                    self.update_endpoint = f"{base_url}/ontology/update"
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        logs = self._docker("logs", self.container, check=False).stdout[-4000:]
        raise RuntimeError(f"isolated Fuseki did not become ready: {logs}")

    def stop_and_verify(self) -> tuple[bool, bool]:
        self._docker("rm", "--force", self.container, check=False)
        container_absent = (
            self._docker("container", "inspect", self.container, check=False).returncode != 0
        )
        self._docker("volume", "rm", self.volume, check=False)
        volume_absent = self._docker("volume", "inspect", self.volume, check=False).returncode != 0
        return container_absent, volume_absent


def _request(plan: Any) -> RDFProjectionRepairRequest:
    return RDFProjectionRepairRequest(
        plan=plan,
        checkpointed_by="workload:rdf-rehearsal",
    )


def _desired(
    target: RDFProjectionTarget,
    *,
    target_content_sha256: str,
    triple_count: int,
    source_content_sha256: str,
    source_version: str,
) -> ProjectionDesiredState:
    return ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=(
            f"gda://{target.tenant_id}/ontology/{target.ontology_key}/{source_version}"
        ),
        source_content_sha256=source_content_sha256,
        target_engine=ProjectionEngine.RDF,
        target_ref=target.target_ref,
        target_exists=True,
        expected_target_content_sha256=target_content_sha256,
        expected_row_count=triple_count,
    )


def _registered_target(
    package_dir: Path,
    endpoint: str,
    update_endpoint: str,
) -> RDFProjectionTarget:
    reader = OntologyPackageReader(
        package_dir,
        verify=True,
        ontology_key="natural-resource-one-map",
    )
    manifest = reader.manifest
    artifact = manifest.artifacts["rdf"]
    return RDFProjectionTarget(
        tenant_id="cq-rdf-rehearsal",
        projection_id="cq.natural_resource_ontology",
        target_ref="rdf://temporary/ontology/default",
        graph_store_endpoint=endpoint,
        sparql_update_endpoint=update_endpoint,
        package_dir=str(package_dir),
        ontology_key=manifest.ontology_key,
        semantic_version=manifest.semantic_version,
        package_id=manifest.package_id,
        package_content_sha256=manifest.content_sha256,
        rdf_artifact_sha256=artifact.sha256,
        expected_triple_count=int(manifest.stats["rdf_triple_count"]),
    )


def run_rehearsal(
    admin_url: str,
    *,
    image: str = _DEFAULT_IMAGE,
    package_dir: Path = _DEFAULT_PACKAGE,
) -> RDFProjectionExecutorRehearsalReport:
    checked_at = datetime.now(UTC)
    checks: dict[str, bool] = {}
    failures: list[str] = []
    temporary_database = _TemporaryPostgres(admin_url)
    temporary_fuseki = _TemporaryFuseki(image)
    target: RDFProjectionTarget | None = None
    try:
        temporary_database.create()
        temporary_fuseki.start()
        assert temporary_database.engine is not None
        assert temporary_fuseki.endpoint is not None
        assert temporary_fuseki.update_endpoint is not None
        target = _registered_target(
            package_dir,
            temporary_fuseki.endpoint,
            temporary_fuseki.update_endpoint,
        )
        executor = RDFProjectionRepairExecutor(
            RDFProjectionTargetRegistry((target,)),
            timeout_seconds=600,
        )
        authority = PostgresProjectionCheckpointAuthority(temporary_database.engine)
        turtle, target_sha256, triple_count = executor._load_package(target)
        initial = executor.observe(target)
        desired = _desired(
            target,
            target_content_sha256=target_sha256,
            triple_count=triple_count,
            source_content_sha256=target.package_content_sha256,
            source_version=target.semantic_version,
        )
        rebuild_plan = build_projection_repair_plan(desired, initial, None)
        first_result = execute_rdf_projection_repair(
            _request(rebuild_plan),
            executor=executor,
            authority=authority,
        )
        first = first_result.receipt
        checks["rebuild_graph_store_and_content_verification"] = (
            first.status == "completed"
            and first.target_content_sha256 == target_sha256
            and first.target_row_count == triple_count
        )
        checks["rebuild_receipt_automatically_checkpointed"] = (
            first_result.checkpoint_created
            and first_result.checkpoint.checkpoint_version == 1
            and first_result.checkpoint.target_commit_ref == first.provider_commit_ref
            and first.provider_commit_ref.get("provider") == "rdf_fuseki"
        )
        recovered_first = executor.recover_receipt(rebuild_plan)
        checks["provider_receipt_graph_is_atomic_and_plan_bound"] = (
            recovered_first is not None
            and recovered_first.provider_commit_ref == first.provider_commit_ref
            and recovered_first.provider_commit_ref.get("provider_atomicity")
            == "single_fuseki_update_request"
            and recovered_first.provider_commit_ref.get("receipt_graph")
            == executor._receipt_graph_uri(rebuild_plan)
        )
        with httpx.Client(timeout=60) as client:
            stage_response = client.get(
                executor._graph_endpoint(
                    target,
                    executor._stage_graph_uri(rebuild_plan),
                ),
                headers={"Accept": "application/n-triples"},
            )
        checks["staging_graph_removed_after_atomic_commit"] = (
            stage_response.status_code == 404
        )
        replay_result = execute_rdf_projection_repair(
            _request(rebuild_plan),
            executor=executor,
            authority=authority,
        )
        checks["rebuild_replay_is_idempotent"] = (
            replay_result.status == "replayed"
            and not replay_result.checkpoint_created
            and replay_result.checkpoint == first_result.checkpoint
        )

        with httpx.Client(timeout=60) as client:
            drift = client.put(
                target.graph_store_endpoint,
                content=b"<urn:gda:drift> <urn:gda:predicate> <urn:gda:value> .\n",
                headers={"Content-Type": "text/turtle"},
            )
            drift.raise_for_status()
        try:
            executor.execute(rebuild_plan, observed_at=checked_at + timedelta(seconds=2))
        except Exception:
            checks["sealed_observation_rejects_target_drift"] = True
        else:
            checks["sealed_observation_rejects_target_drift"] = False
        try:
            execute_rdf_projection_repair(
                _request(rebuild_plan),
                executor=executor,
                authority=authority,
            )
        except RDFProjectionServiceConflictError:
            checks["checkpoint_replay_reobserves_and_rejects_target_drift"] = True
        else:
            checks["checkpoint_replay_reobserves_and_rejects_target_drift"] = False
        with httpx.Client(timeout=600) as client:
            restored = client.put(
                target.graph_store_endpoint,
                content=turtle,
                headers={"Content-Type": "text/turtle; charset=utf-8"},
            )
            restored.raise_for_status()

        post = executor.observe(target)
        advanced_desired = _desired(
            target,
            target_content_sha256=target_sha256,
            triple_count=triple_count,
            source_content_sha256="b" * 64,
            source_version="2.3.0-checkpoint",
        )
        checkpoint_plan = build_projection_repair_plan(
            advanced_desired,
            post,
            first_result.checkpoint,
        )
        class FailOnceAuthority:
            def __init__(self) -> None:
                self.failed = False

            def current(self, **identity):
                return authority.current(**identity)

            def history(self, **identity):
                return authority.history(**identity)

            def record(self, checkpoint, *, previous_checkpoint_sha256=None):
                if not self.failed:
                    self.failed = True
                    raise ProjectionCheckpointAuthorityConfigurationError(
                        "simulated checkpoint authority outage"
                    )
                return authority.record(
                    checkpoint,
                    previous_checkpoint_sha256=previous_checkpoint_sha256,
                )

        class CountingProvider:
            def __init__(self) -> None:
                self.registry = executor.registry
                self.execute_count = 0
                self.recover_count = 0

            def execute(self, submitted_plan):
                self.execute_count += 1
                return executor.execute(submitted_plan)

            def observe(self, observed_target):
                return executor.observe(observed_target)

            def recover_receipt(self, submitted_plan):
                self.recover_count += 1
                return executor.recover_receipt(submitted_plan)

        checkpoint_authority = FailOnceAuthority()
        checkpoint_provider = CountingProvider()
        try:
            execute_rdf_projection_repair(
                _request(checkpoint_plan),
                executor=checkpoint_provider,
                authority=checkpoint_authority,
            )
        except RDFProjectionServiceConfigurationError:
            pass
        else:
            failures.append("checkpoint authority outage was not surfaced")
        checkpoint_result = execute_rdf_projection_repair(
            _request(checkpoint_plan),
            executor=checkpoint_provider,
            authority=checkpoint_authority,
        )
        checks["checkpoint_action_rechecks_without_rebuild"] = (
            checkpoint_result.receipt.status == "checkpointed"
            and checkpoint_result.checkpoint_created
            and checkpoint_result.checkpoint.checkpoint_version == 2
        )
        checks["authority_outage_recovers_receipt_without_provider_replay"] = (
            checkpoint_provider.execute_count == 1
            and checkpoint_provider.recover_count == 2
            and checkpoint_result.checkpoint.target_commit_ref
            == checkpoint_result.receipt.provider_commit_ref
        )

        stale_desired = _desired(
            target,
            target_content_sha256=target_sha256,
            triple_count=triple_count,
            source_content_sha256="d" * 64,
            source_version="stale",
        )
        stale_plan = build_projection_repair_plan(stale_desired, initial, None)
        before_stale_attempt = executor.observe(target)
        try:
            execute_rdf_projection_repair(
                _request(stale_plan),
                executor=executor,
                authority=authority,
            )
        except RDFProjectionServiceConflictError:
            after_stale_attempt = executor.observe(target)
            checks["stale_predecessor_rejected_before_provider_mutation"] = (
                before_stale_attempt.target_exists == after_stale_attempt.target_exists
                and before_stale_attempt.observed_content_sha256
                == after_stale_attempt.observed_content_sha256
                and before_stale_attempt.observed_row_count
                == after_stale_attempt.observed_row_count
            )
        else:
            checks["stale_predecessor_rejected_before_provider_mutation"] = False

        delete_desired = ProjectionDesiredState(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            source_resource_version_ref=(
                "gda://cq-rdf-rehearsal/ontology/natural-resource-one-map/deleted"
            ),
            source_content_sha256="c" * 64,
            target_engine=ProjectionEngine.RDF,
            target_ref=target.target_ref,
            target_exists=False,
            expected_target_content_sha256=None,
            expected_row_count=0,
        )
        delete_plan = build_projection_repair_plan(
            delete_desired,
            post,
            checkpoint_result.checkpoint,
        )
        delete_result = execute_rdf_projection_repair(
            _request(delete_plan),
            executor=executor,
            authority=authority,
        )
        deleted = delete_result.receipt
        checks["delete_graph_store_and_absence_verification"] = (
            deleted.status == "deleted"
            and not deleted.target_exists
            and deleted.target_row_count == 0
        )
        checks["delete_receipt_automatically_checkpointed"] = (
            delete_result.checkpoint_created
            and delete_result.checkpoint.checkpoint_version == 3
            and not delete_result.checkpoint.target_exists
            and delete_result.checkpoint.target_commit_ref == deleted.provider_commit_ref
        )
        recovered_delete = executor.recover_receipt(delete_plan)
        checks["delete_provider_receipt_recovers_verified_absence"] = (
            recovered_delete is not None
            and recovered_delete.status == "deleted"
            and not recovered_delete.target_exists
            and recovered_delete.target_row_count == 0
        )
        delete_replay = execute_rdf_projection_repair(
            _request(delete_plan),
            executor=executor,
            authority=authority,
        )
        checks["delete_replay_is_idempotent"] = (
            delete_replay.status == "replayed"
            and not delete_replay.checkpoint_created
            and delete_replay.checkpoint == delete_result.checkpoint
        )
        history = authority.history(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.RDF,
            target_ref=target.target_ref,
        )
        checks["checkpoint_history_is_append_only_and_sequential"] = (
            tuple(item.checkpoint_version for item in history) == (1, 2, 3)
            and history[0].checkpoint_sha256 == first_result.checkpoint.checkpoint_sha256
            and history[1].checkpoint_sha256 == checkpoint_result.checkpoint.checkpoint_sha256
            and history[2].checkpoint_sha256 == delete_result.checkpoint.checkpoint_sha256
        )

        crash_target = target.model_copy(
            update={
                "projection_id": "cq.natural_resource_ontology.commit_unknown",
                "target_ref": "rdf://temporary/ontology/commit-unknown",
            }
        )
        crash_missing = ProjectionTargetObservation(
            tenant_id=crash_target.tenant_id,
            projection_id=crash_target.projection_id,
            target_engine=ProjectionEngine.RDF,
            target_ref=crash_target.target_ref,
            target_exists=False,
            observed_content_sha256=None,
            observed_row_count=0,
            observed_by="workload:rdf-fault-rehearsal",
            observed_at=checked_at,
        )
        crash_desired = _desired(
            crash_target,
            target_content_sha256=target_sha256,
            triple_count=triple_count,
            source_content_sha256=crash_target.package_content_sha256,
            source_version=crash_target.semantic_version,
        )
        crash_plan = build_projection_repair_plan(
            crash_desired,
            crash_missing,
            None,
        )
        crash_registry = RDFProjectionTargetRegistry((crash_target,))

        class CommitUnknownExecutor(RDFProjectionRepairExecutor):
            commit_count = 0

            def _commit_receipt(self, *args, **kwargs):
                super()._commit_receipt(*args, **kwargs)
                self.commit_count += 1
                raise RDFProjectionExecutionError(
                    "client connection lost after Fuseki commit"
                )

        crash_executor = CommitUnknownExecutor(
            crash_registry,
            timeout_seconds=600,
        )
        crash_delegate = RegisteredExecutorProjectionProvider(
            executor=crash_executor,
            registry=crash_registry,
        )
        crash_ledger = InMemoryProjectionRecoveryLedger()
        crash_authority = InMemoryProjectionCheckpointLedger()
        crash_first = ProjectionRecoveryWorker(
            crash_plan,
            checkpointed_by="workload:rdf-fault-rehearsal",
            provider=crash_delegate,
            authority=crash_authority,
            ledger=crash_ledger,
        ).run_once()
        restarted_executor = RDFProjectionRepairExecutor(
            crash_registry,
            timeout_seconds=600,
        )
        restarted_delegate = RegisteredExecutorProjectionProvider(
            executor=restarted_executor,
            registry=crash_registry,
        )

        class RecoveryProvider:
            execute_count = 0
            recover_count = 0

            def execute(self, submitted_plan):
                self.execute_count += 1
                return restarted_delegate.execute(submitted_plan)

            def observe(self, submitted_plan):
                return restarted_delegate.observe(submitted_plan)

            def recover_receipt(self, submitted_plan):
                self.recover_count += 1
                return restarted_delegate.recover_receipt(submitted_plan)

        recovery_provider = RecoveryProvider()
        crash_recovered = ProjectionRecoveryWorker(
            crash_plan,
            checkpointed_by="workload:rdf-fault-rehearsal",
            provider=recovery_provider,
            authority=crash_authority,
            ledger=crash_ledger,
        ).run_once()
        checks["unknown_commit_recovers_after_restart_without_provider_replay"] = (
            crash_first.action_taken == "reobserve_target"
            and crash_executor.commit_count == 1
            and crash_recovered.snapshot.state.value == "authority_committed"
            and crash_recovered.checkpoint is not None
            and recovery_provider.recover_count == 1
            and recovery_provider.execute_count == 0
        )

        with httpx.Client(timeout=60) as client:
            drift = client.put(
                crash_target.graph_store_endpoint,
                content=b"<urn:gda:drift> <urn:gda:predicate> <urn:gda:value> .\n",
                headers={"Content-Type": "text/turtle"},
            )
            drift.raise_for_status()

        class UnknownAfterPriorCommitProvider:
            execute_count = 0

            def execute(self, _submitted_plan):
                self.execute_count += 1
                raise ProjectionProviderFailure(
                    "client_connection_lost_after_commit",
                    outcome_known=False,
                )

            def observe(self, submitted_plan):
                return restarted_delegate.observe(submitted_plan)

        drift_ledger = InMemoryProjectionRecoveryLedger()
        drift_authority = InMemoryProjectionCheckpointLedger()
        drift_unknown_provider = UnknownAfterPriorCommitProvider()
        ProjectionRecoveryWorker(
            crash_plan,
            checkpointed_by="workload:rdf-fault-rehearsal",
            provider=drift_unknown_provider,
            authority=drift_authority,
            ledger=drift_ledger,
        ).run_once()
        drift_recovery_provider = RecoveryProvider()
        drift_result = ProjectionRecoveryWorker(
            crash_plan,
            checkpointed_by="workload:rdf-fault-rehearsal",
            provider=drift_recovery_provider,
            authority=drift_authority,
            ledger=drift_ledger,
        ).run_once()
        checks["receipt_target_mismatch_stays_manual_and_uncheckpointed"] = (
            drift_unknown_provider.execute_count == 1
            and drift_result.action_taken == "await_operator"
            and drift_result.snapshot.state.value == "compensation_required"
            and drift_recovery_provider.execute_count == 0
            and not drift_authority.history(
                tenant_id=crash_plan.tenant_id,
                projection_id=crash_plan.projection_id,
                target_engine=crash_plan.target_engine,
                target_ref=crash_plan.target_ref,
            )
        )
    except Exception as exc:  # pragma: no cover - surfaced in the signed report
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            container_removed, volume_removed = temporary_fuseki.stop_and_verify()
        except Exception as exc:  # pragma: no cover - external runtime failure
            container_removed = False
            volume_removed = False
            failures.append(f"FusekiCleanupError: {exc}")
        try:
            database_removed = temporary_database.drop_and_verify()
        except Exception as exc:  # pragma: no cover - external runtime failure
            database_removed = False
            failures.append(f"PostgresCleanupError: {exc}")
        checks["temporary_fuseki_container_removed"] = container_removed
        checks["temporary_fuseki_volume_removed"] = volume_removed
        checks["temporary_checkpoint_database_removed"] = database_removed

    failures.extend(key for key, value in checks.items() if not value)
    if target is None:
        reader = OntologyPackageReader(
            package_dir,
            verify=True,
            ontology_key="natural-resource-one-map",
        )
        manifest = reader.manifest
        artifact = manifest.artifacts["rdf"]
    else:
        manifest = OntologyPackageReader(
            Path(target.package_dir),
            verify=True,
            ontology_key=target.ontology_key,
        ).manifest
        artifact = manifest.artifacts["rdf"]
    payload = {
        "schema_id": "gda.rdf-projection-executor-rehearsal.v2",
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "database_scope": "temporary_database_only",
        "fuseki_scope": "temporary_container_and_volume_only",
        "atomicity_scope": (
            "fuseki_target_and_receipt_single_update_request_checkpoint_authority_separate"
        ),
        "fuseki_image": image,
        "fuseki_image_id": temporary_fuseki.image_id or "unavailable",
        "migration_ids": _MIGRATIONS,
        "ontology_key": manifest.ontology_key,
        "ontology_semantic_version": manifest.semantic_version,
        "ontology_package_id": manifest.package_id,
        "ontology_package_content_sha256": manifest.content_sha256,
        "rdf_artifact_sha256": artifact.sha256,
        "rdf_triple_count": int(manifest.stats["rdf_triple_count"]),
        "checks": checks,
        "passed": not failures and bool(checks),
        "failure_reasons": tuple(sorted(set(failures))),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    return RDFProjectionExecutorRehearsalReport(
        **payload,
        report_sha256=canonical_json_fingerprint(payload),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--admin-url",
        default="postgresql://postgres:postgres@localhost:5433/gis_agent",
    )
    parser.add_argument("--image", default=_DEFAULT_IMAGE)
    parser.add_argument("--package-dir", type=Path, default=_DEFAULT_PACKAGE)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = run_rehearsal(
        args.admin_url,
        image=args.image,
        package_dir=args.package_dir,
    )
    document = report.model_dump(mode="json")
    output = json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
