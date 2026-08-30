from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from data_agent.dataops_executor import (
    ExecutorConfig,
    JqdltbAuditCommand,
    JqdltbDataOpsExecutor,
)
from data_agent.platform_contracts import PlatformRun, RunStatus, SubjectContext
from data_agent.platform_gateway import GatewayNotFoundError, GatewayWriteResult

RUN_ID = UUID("d1000000-0000-4000-8000-000000000001")
DEFINITION_ID = UUID("d1000000-0000-4000-8000-000000000002")
SOURCE_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
NOW = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


class FakeGateway:
    def __init__(self):
        self.quality = None
        self.artifact = None
        self.run = PlatformRun(
            tenant_id="local-dev",
            run_id=RUN_ID,
            definition_version_id=DEFINITION_ID,
            orchestration_class="dataops",
            subject_context=SubjectContext(
                tenant_id="local-dev",
                subject_id="dolphinscheduler-gda-dataops",
                subject_type="workload",
                roles=("platform_operator",),
                purpose="audit the immutable JQDLTB source",
            ),
            input_bindings=(
                {
                    "binding_name": "source",
                    "resource_version_id": SOURCE_ID,
                    "semantic_type": "gis.land_use.parcel.source",
                },
            ),
            idempotency_key="jqdltb-audit-test",
            status=RunStatus.DISPATCHING,
            state_version=1,
            submitted_at=NOW,
        )

    def get_run(self, tenant_id, run_id):
        assert tenant_id == "local-dev"
        assert run_id == RUN_ID
        return self.run

    def get_quality_result(self, tenant_id, quality_result_id):
        if self.quality is None:
            raise GatewayNotFoundError("not found")
        return self.quality

    def record_artifact(self, artifact):
        self.artifact = artifact
        return GatewayWriteResult(artifact, True)

    def record_quality_result(self, quality):
        self.quality = quality
        return GatewayWriteResult(quality, True)


def _report():
    return {
        "protocol_id": "cq-jqdltb-v1",
        "evaluation_policy": {
            "records_scanned": 1555,
            "full_dataset_validated": True,
        },
        "quality": {
            "source_quality_verdict": "failed",
            "summary": {"passed": 6, "failed": 3, "blocked": 1},
            "checks": [
                {"id": "primary_key_unique", "status": "failed"},
                {"id": "numeric_constraints_satisfied", "status": "failed"},
                {"id": "standard_required_fields_covered", "status": "blocked"},
            ],
        },
        "standardization": {
            "status": "blocked",
            "missing_target_fields": ["MSSM", "SJNF"],
        },
    }


def test_executor_records_failed_authoritative_quality_without_product(tmp_path):
    token = tmp_path / "token"
    token.write_text("executor-token", encoding="utf-8")
    token.chmod(0o600)
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"schema": "test"}), encoding="utf-8")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    gateway = FakeGateway()
    calls = []

    def evaluator(**kwargs):
        calls.append(kwargs)
        return _report()

    executor = JqdltbDataOpsExecutor(
        ExecutorConfig(
            token_file=token,
            dataset_root=dataset,
            protocol_path=protocol,
            evidence_root=tmp_path / "evidence",
        ),
        gateway=gateway,
        evaluator=evaluator,
        clock=lambda: NOW,
    )
    command = JqdltbAuditCommand(
        tenant_id="local-dev",
        run_id=RUN_ID,
        source_resource_version_id=SOURCE_ID,
    )

    result = executor.execute(command)
    replay = executor.execute(command)

    assert result.verdict == "failed"
    assert result.records_scanned == 1555
    assert result.failed_check_ids == (
        "numeric_constraints_satisfied",
        "primary_key_unique",
    )
    assert result.blocked_check_ids == ("standard_required_fields_covered",)
    assert result.data_product_version_created is False
    assert replay.replayed is True
    assert len(calls) == 1
    assert gateway.quality.verdict.value == "failed"
    assert gateway.artifact.manifest["authoritative_quality_result"] is True
    assert gateway.artifact.manifest["data_product_version_created"] is False
    evidence = json.loads(
        (tmp_path / "evidence/local-dev" / str(RUN_ID) / "jqdltb-quality-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["source_scan"]["evaluation_policy"]["records_scanned"] == 1555
