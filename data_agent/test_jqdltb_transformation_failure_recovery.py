from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_agent.jqdltb_transformation_executor import JqdltbTransformationCommand
from data_agent.platform_contracts import compile_jqdltb_executable_contract
from data_agent.test_jqdltb_transformation_executor import (
    RUN_ID,
    SOURCE_ID,
    _approved,
    _executor,
    _proposal,
)


def test_platform_evidence_failure_is_recorded_and_candidate_is_retryable(
    tmp_path: Path,
) -> None:
    # Reuse the test authority behavior without coupling production code to a
    # database-backed ApprovalCase in this failure-path test.
    from data_agent.test_jqdltb_transformation_executor import _Authority

    authority = _Authority()
    proposal = _proposal()
    case = _approved(proposal)
    authority.cases[case.approval_case_ref] = case
    executor = _executor(tmp_path, authority)
    executable = compile_jqdltb_executable_contract(
        proposal,
        approval_case=case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    command = JqdltbTransformationCommand(
        tenant_id="local-dev",
        run_id=RUN_ID,
        source_resource_version_id=SOURCE_ID,
        contract=executable,
    )

    def fail_platform_evidence(**_kwargs):
        raise RuntimeError("gateway unavailable")

    executor._record_platform_evidence = fail_platform_evidence
    with pytest.raises(RuntimeError, match="gateway unavailable"):
        executor.execute(command)

    output_dir = tmp_path / "outputs" / "local-dev" / str(RUN_ID)
    candidates = list(output_dir.glob("jqdltb-transform-*"))
    assert len(candidates) == 1
    evidence = json.loads(
        (candidates[0] / "transformation-evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["platform_evidence"] == {
        "status": "failed",
        "error_type": "RuntimeError",
    }
    assert evidence["result"]["status"] == "failed"

    executor._record_platform_evidence = lambda **_kwargs: (None, None, None, None)
    result = executor.execute(command)
    assert result.status == "completed"
    final_evidence = json.loads(
        (Path(result.output_root) / "transformation-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    assert final_evidence["result"]["status"] == "completed"
    assert "platform_evidence" not in final_evidence
