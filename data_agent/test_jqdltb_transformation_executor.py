from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from data_agent.jqdltb_transformation_approval import JqdltbTransformationApprovalService
from data_agent.jqdltb_transformation_executor import (
    JqdltbTransformationCommand,
    JqdltbTransformationExecutor,
    JqdltbTransformationExecutorConfig,
)
from data_agent.platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    JqdltbAreaDeviationPolicy,
    JqdltbAreaPolicy,
    JqdltbDerivationContract,
    JqdltbDerivationStatus,
    JqdltbTransformationContract,
    JqdltbTransformationStrategy,
    PlatformRun,
    RunStatus,
    SubjectContext,
    canonical_json_fingerprint,
    compile_jqdltb_executable_contract,
)
from scripts.manage_chongqing_jqdltb_transformation_approval import _build_approval

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
DIAGNOSTIC = (
    ROOT / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)
RUN_ID = UUID("d1000000-0000-4000-8000-000000000051")
DEFINITION_ID = UUID("d1000000-0000-4000-8000-000000000052")
SOURCE_ID = UUID("34441c77-2cf0-5ca2-83bf-81dd6a488d5b")
NOW = datetime(2026, 8, 23, 4, tzinfo=UTC)
DERIVATION_RULES = {
    "SJNF": {
        "schema": "gda.jqdltb_derivation_rule.v1",
        "target_field": "SJNF",
        "source_fields": ["JQDLMC"],
        "semantic_contract_ref": "gda://local-dev/semantic_rule/sjnf-v1",
        "method": "first non-blank approved source value",
    },
    "MSSM": {
        "schema": "gda.jqdltb_derivation_rule.v1",
        "target_field": "MSSM",
        "source_fields": ["JQDLMC"],
        "semantic_contract_ref": "gda://local-dev/semantic_rule/mssm-v1",
        "method": "first non-blank approved source value",
    },
}


def _rule_bytes(target: str) -> bytes:
    return json.dumps(
        DERIVATION_RULES[target],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _accepted_semantic_audit_path(tmp_path: Path) -> Path:
    audit = json.loads(
        (ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json").read_text(
            encoding="utf-8"
        )
    )
    for target in ("SJNF", "MSSM"):
        for candidate in audit["candidates"][target]:
            if candidate["field"] == "JQDLMC":
                candidate["status"] = "accepted"
        audit["decisions"][target] = "accepted_candidate_available"
    audit.pop("report_sha256")
    audit["report_sha256"] = canonical_json_fingerprint(audit)
    path = tmp_path / "semantic-candidate-audit.json"
    path.write_text(json.dumps(audit, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _derivations() -> tuple[JqdltbDerivationContract, ...]:
    return tuple(
        JqdltbDerivationContract(
            target_field=target,
            status=JqdltbDerivationStatus.PROPOSED,
            source_fields=("JQDLMC",),
            semantic_contract_ref=str(rule["semantic_contract_ref"]),
            semantic_contract_sha256=hashlib.sha256(_rule_bytes(target)).hexdigest(),
            method=str(rule["method"]),
        )
        for target, rule in DERIVATION_RULES.items()
    )


class _Authority:
    def __init__(self) -> None:
        self.cases: dict[str, ApprovalCase] = {}

    def create(self, case: ApprovalCase, *, owner_ref: str):
        self.cases[case.approval_case_ref] = case
        return SimpleNamespace(approval_case=case)

    def get(self, tenant_id: str, approval_case_ref: str) -> ApprovalCase:
        case = self.cases[approval_case_ref]
        assert case.tenant_id == tenant_id
        return case


class _Gateway:
    def __init__(self) -> None:
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
                purpose="execute approved JQDLTB transformation",
            ),
            input_bindings=(
                {
                    "binding_name": "source",
                    "resource_version_id": SOURCE_ID,
                    "semantic_type": "gis.land_use.parcel.source",
                },
            ),
            idempotency_key="jqdltb-transformation-test",
            status=RunStatus.DISPATCHING,
            state_version=1,
            submitted_at=NOW,
        )

    def get_run(self, tenant_id: str, run_id: UUID) -> PlatformRun:
        assert tenant_id == "local-dev"
        assert run_id == RUN_ID
        return self.run


def _proposal(
    *,
    nonpositive_area_policy: JqdltbAreaPolicy = JqdltbAreaPolicy.QUARANTINE,
    business_correction_resource_version_id: UUID | None = None,
    business_correction_sha256: str | None = None,
    area_deviation_policy: JqdltbAreaDeviationPolicy = (
        JqdltbAreaDeviationPolicy.PRESERVE_SOURCE
    ),
    geometry_area_rule_ref: str | None = None,
    geometry_area_rule_sha256: str | None = None,
    semantic_candidate_audit_sha256: str | None = None,
) -> JqdltbTransformationContract:
    baseline = JqdltbTransformationContract.model_validate_json(BASELINE.read_text())
    proposal, _case = _build_approval(
        baseline=baseline,
        strategy=JqdltbTransformationStrategy(
            canonical_key="TBBH",
            nonpositive_area_policy=nonpositive_area_policy,
            business_correction_resource_version_id=(
                business_correction_resource_version_id
            ),
            business_correction_sha256=business_correction_sha256,
            area_deviation_policy=area_deviation_policy,
            geometry_area_rule_ref=geometry_area_rule_ref,
            geometry_area_rule_sha256=geometry_area_rule_sha256,
            derivation_contracts=_derivations(),
        ),
        case_id="jqdltb-executor-test",
        requester_subject="workload:ar0-contract-builder",
        request_reason="test approved JQDLTB execution",
        created_by="workload:ar0-contract-builder",
        proposed_at=datetime(2026, 8, 23, 1, tzinfo=UTC),
        requested_at=datetime(2026, 8, 23, 1, 1, tzinfo=UTC),
        expires_at=datetime(2026, 9, 23, tzinfo=UTC),
        semantic_candidate_audit_sha256=semantic_candidate_audit_sha256,
    )
    return proposal


def _approved(proposal: JqdltbTransformationContract) -> ApprovalCase:
    from data_agent.platform_contracts import build_jqdltb_transformation_approval_case

    pending = build_jqdltb_transformation_approval_case(
        proposal,
        case_id="jqdltb-executor-test",
        requester_subject="workload:ar0-contract-builder",
        request_reason="test approved JQDLTB execution",
        requested_at=datetime(2026, 8, 23, 1, 1, tzinfo=UTC),
        expires_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    value = pending.model_dump(mode="json")
    value.update(
        {
            "status": ApprovalCaseStatus.APPROVED,
            "state_version": 1,
            "decided_by": "human:business-steward",
            "decision_reason": "approved test proposal",
            "decided_at": "2026-08-23T02:00:00Z",
        }
    )
    return ApprovalCase.model_validate(value)


def _executor(
    tmp_path: Path,
    authority: _Authority,
    *,
    correction_path: Path | None = None,
    geometry_area_rule_path: Path | None = None,
    semantic_candidate_audit_path: Path | None = None,
) -> JqdltbTransformationExecutor:
    source = tmp_path / "JQDLTB.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4523"}},
                "features": [
                    {
                        "type": "Feature",
                        "id": "a",
                        "properties": {
                            "TBBH": "A",
                            "TBMJ": 1,
                            "TBDLMJ": 1,
                            "JQDLMC": "耕地",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                        },
                    },
                    {
                        "type": "Feature",
                        "id": "b",
                        "properties": {
                            "TBBH": "B",
                            "TBMJ": 0,
                            "TBDLMJ": 0,
                            "JQDLMC": "林地",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                        },
                    },
                    {
                        "type": "Feature",
                        "id": "c",
                        "properties": {
                            "TBBH": "C",
                            "TBMJ": 2,
                            "TBDLMJ": 2,
                            "JQDLMC": "草地",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]],
                        },
                    },
                    {
                        "type": "Feature",
                        "id": "d",
                        "properties": {
                            "TBBH": "D",
                            "TBMJ": 4,
                            "TBDLMJ": 0,
                            "JQDLMC": "园地",
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    derivation_paths = {}
    for target in DERIVATION_RULES:
        rule_path = tmp_path / f"{target.lower()}-rule.json"
        rule_path.write_bytes(_rule_bytes(target))
        derivation_paths[target] = rule_path.resolve()
    service = JqdltbTransformationApprovalService(authority)
    return JqdltbTransformationExecutor(
        JqdltbTransformationExecutorConfig(
            source_path=source.resolve(),
            output_root=(tmp_path / "outputs").resolve(),
            diagnostic_path=DIAGNOSTIC.resolve(),
            semantic_candidate_audit_path=(
                semantic_candidate_audit_path.resolve()
                if semantic_candidate_audit_path
                else None
            ),
            correction_path=correction_path.resolve() if correction_path else None,
            derivation_contract_paths=derivation_paths,
            geometry_area_rule_path=(
                geometry_area_rule_path.resolve() if geometry_area_rule_path else None
            ),
        ),
        gateway=_Gateway(),
        approval_service=service,
        clock=lambda: NOW,
    )


def test_execution_gate_rejects_before_creating_output(tmp_path: Path) -> None:
    authority = _Authority()
    proposal = _proposal()
    executor = _executor(tmp_path, authority)
    command = JqdltbTransformationCommand(
        tenant_id="local-dev",
        run_id=RUN_ID,
        source_resource_version_id=SOURCE_ID,
        contract=proposal,
    )
    with pytest.raises(ValueError, match="ApprovalCase"):
        executor.execute(command)
    assert not (tmp_path / "outputs").exists()


def test_shapefile_source_bundle_identity_must_match_before_materialization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "JQDLTB.shp"
    source.write_bytes(b"frozen-source-bytes")
    from data_agent.standards_platform.application.acceptance import bundle_identity

    identity = bundle_identity(source)
    assert JqdltbTransformationExecutor._validate_source_bundle_identity(
        source, identity["bundle_sha256"]
    )["verification"] == "shapefile_sidecar_bundle_verified"
    with pytest.raises(ValueError, match="does not match the approved contract"):
        JqdltbTransformationExecutor._validate_source_bundle_identity(source, "0" * 64)


def test_shapefile_source_bundle_change_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "JQDLTB.shp"
    source.write_bytes(b"source")
    observations = iter(
        (
            {"bundle_sha256": "a" * 64, "size_bytes": 6, "members": []},
            {"bundle_sha256": "b" * 64, "size_bytes": 7, "members": []},
        )
    )
    monkeypatch.setattr(
        "data_agent.jqdltb_transformation_executor.bundle_identity",
        lambda _path: next(observations),
    )
    with pytest.raises(ValueError, match="changed while it was being read"):
        JqdltbTransformationExecutor._validate_source_bundle_identity(source, "a" * 64)


def test_post_transformation_quality_does_not_pass_an_all_quarantined_candidate() -> None:
    contract = _proposal()
    checks = JqdltbTransformationExecutor._quality_checks(
        features=[{"properties": {}, "geometry": None}],
        materialized=[],
        quarantined=[
            {
                "properties": {},
                "geometry": None,
                "quarantine_reason": "nonpositive_declared_area",
            }
        ],
        stats={
            "derived_missing_count": 0,
            "missing_business_correction_count": 0,
            "area_deviation_count": 0,
        },
        contract=contract,
    )
    by_id = {item["id"]: item for item in checks}
    assert by_id["records_reconciled"]["status"] == "passed"
    assert by_id["materialized_records_nonzero"]["status"] == "failed"


def test_post_transformation_quality_rejects_unaccounted_area_deviation() -> None:
    contract = _proposal()
    feature = {
        "properties": {
            "TBBH": "A",
            "TBMJ": 1,
            "TBDLMJ": 1,
            "SJNF": "2026",
            "MSSM": "01",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        },
    }
    checks = JqdltbTransformationExecutor._quality_checks(
        features=[feature],
        materialized=[feature],
        quarantined=[],
        stats={
            "derived_missing_count": 0,
            "missing_business_correction_count": 0,
            "area_deviation_count": 1,
            "area_deviation_quarantined_count": 0,
            "area_deviation_preserved_count": 0,
            "area_deviation_replaced_count": 0,
        },
        contract=contract,
    )
    by_id = {item["id"]: item for item in checks}
    assert by_id["area_policy_applied"] == {
        "id": "area_policy_applied",
        "status": "failed",
        "area_deviation_policy": "preserve_source",
        "area_deviation_count": 1,
        "area_deviation_quarantined": 0,
        "area_deviation_annotated": 0,
        "area_deviation_replaced": 0,
    }


def test_execution_rejects_missing_semantic_audit_before_creating_output(
    tmp_path: Path,
) -> None:
    authority = _Authority()
    semantic_sha256 = json.loads(
        (ROOT / "docs/reports/jqdltb_semantic_candidate_audit_2026-08-26.json").read_text(
            encoding="utf-8"
        )
    )["report_sha256"]
    proposal = _proposal(semantic_candidate_audit_sha256=semantic_sha256)
    case = _approved(proposal)
    authority.cases[case.approval_case_ref] = case
    executor = _executor(tmp_path, authority)
    executable = compile_jqdltb_executable_contract(
        proposal,
        approval_case=case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="semantic candidate audit"):
        executor.execute(
            JqdltbTransformationCommand(
                tenant_id="local-dev",
                run_id=RUN_ID,
                source_resource_version_id=SOURCE_ID,
                contract=executable,
            )
        )
    assert not (tmp_path / "outputs").exists()


def test_approved_execution_materializes_layers_and_replays(tmp_path: Path) -> None:
    authority = _Authority()
    semantic_audit_path = _accepted_semantic_audit_path(tmp_path)
    semantic_sha256 = json.loads(semantic_audit_path.read_text(encoding="utf-8"))["report_sha256"]
    proposal = _proposal(semantic_candidate_audit_sha256=semantic_sha256)
    authority.cases["gda://local-dev/approval_case/jqdltb-executor-test"] = _approved(proposal)
    executor = _executor(
        tmp_path,
        authority,
        semantic_candidate_audit_path=semantic_audit_path,
    )
    executable = compile_jqdltb_executable_contract(
        proposal,
        approval_case=authority.cases["gda://local-dev/approval_case/jqdltb-executor-test"],
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    result = executor.execute(
        JqdltbTransformationCommand(
            tenant_id="local-dev",
            run_id=RUN_ID,
            source_resource_version_id=SOURCE_ID,
            contract=executable,
        )
    )
    assert result.quality_verdict == "passed"
    assert result.records_read == 4
    assert result.records_materialized == 2
    assert result.records_quarantined == 2
    output = Path(result.output_root)
    assert (output / "raw/jqdltb.json").is_file()
    assert (output / "ods/jqdltb.json").is_file()
    assert (output / "dim/jqdltb.json").is_file()
    assert (output / "dwd/jqdltb.json").is_file()
    assert (output / "ads/jqdltb.json").is_file()
    assert (output / "quarantine/jqdltb.json").is_file()
    assert (output / "lineage/jqdltb.json").is_file()
    assert (output / "layer-manifest.json").is_file()
    assert (output / "transformation-artifact.json").is_file()
    evidence = json.loads((output / "transformation-evidence.json").read_text())
    assert evidence["semantic_candidate_audit_sha256"] == semantic_sha256
    assert evidence["records"]["semantic_candidate_audit_sha256"] == semantic_sha256
    assert evidence["source_identity"]["verification"] == (
        "not_applicable_non_shapefile_fixture"
    )
    assert evidence["quality"]["scope"] == (
        "post_transformation_candidate_full_dataset"
    )
    assert evidence["records"]["area_deviation_count"] == 2
    assert evidence["records"]["area_deviation_preserved_count"] == 2
    assert len(evidence["quality"]["checks"]) == 10
    assert hashlib.sha256((output / "layer-manifest.json").read_bytes()).hexdigest() == (
        canonical_json_fingerprint(evidence["layers"])
    )
    assert evidence["quality"]["data_product_version_created"] is False
    replay = executor.execute(
        JqdltbTransformationCommand(
            tenant_id="local-dev",
            run_id=RUN_ID,
            source_resource_version_id=SOURCE_ID,
            contract=executable,
        )
    )
    assert replay.replayed is True


def _execute(
    *,
    proposal: JqdltbTransformationContract,
    executor: JqdltbTransformationExecutor,
    authority: _Authority,
):
    case = _approved(proposal)
    authority.cases[case.approval_case_ref] = case
    executable = compile_jqdltb_executable_contract(
        proposal,
        approval_case=case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )
    result = executor.execute(
        JqdltbTransformationCommand(
            tenant_id="local-dev",
            run_id=RUN_ID,
            source_resource_version_id=SOURCE_ID,
            contract=executable,
        )
    )
    return result, executable


def test_business_correction_materializes_only_exact_bound_nonpositive_rows(
    tmp_path: Path,
) -> None:
    correction_id = UUID("d1000000-0000-4000-8000-000000000061")
    correction_path = tmp_path / "corrections.json"
    correction_path.write_bytes(
        json.dumps(
            {
                "records": [
                    {"TBBH": "B", "TBMJ": 10, "TBDLMJ": 10},
                    {"TBBH": "D", "TBMJ": 4, "TBDLMJ": 4},
                ]
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    proposal = _proposal(
        nonpositive_area_policy=JqdltbAreaPolicy.BUSINESS_CORRECTION,
        business_correction_resource_version_id=correction_id,
        business_correction_sha256=hashlib.sha256(correction_path.read_bytes()).hexdigest(),
    )
    authority = _Authority()
    executor = _executor(
        tmp_path,
        authority,
        correction_path=correction_path,
    )

    result, _contract = _execute(
        proposal=proposal,
        executor=executor,
        authority=authority,
    )

    assert result.quality_verdict == "passed"
    assert result.records_materialized == 4
    assert result.records_quarantined == 0
    ads = json.loads((Path(result.output_root) / "ads/jqdltb.json").read_text())
    by_key = {item["properties"]["TBBH"]: item["properties"] for item in ads["features"]}
    assert by_key["B"]["TBMJ_source"] == 0
    assert by_key["B"]["TBDLMJ_source"] == 0
    assert by_key["B"]["TBMJ"] == 10
    assert by_key["B"]["gda_area_correction_resource_version_id"] == str(correction_id)


def test_incomplete_business_correction_fails_quality_without_silent_success(
    tmp_path: Path,
) -> None:
    correction_path = tmp_path / "corrections.json"
    correction_path.write_bytes(
        json.dumps(
            {"records": [{"TBBH": "B", "TBMJ": 10, "TBDLMJ": 10}]},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    proposal = _proposal(
        nonpositive_area_policy=JqdltbAreaPolicy.BUSINESS_CORRECTION,
        business_correction_resource_version_id=UUID(
            "d1000000-0000-4000-8000-000000000062"
        ),
        business_correction_sha256=hashlib.sha256(correction_path.read_bytes()).hexdigest(),
    )
    authority = _Authority()
    executor = _executor(tmp_path, authority, correction_path=correction_path)

    result, _contract = _execute(
        proposal=proposal,
        executor=executor,
        authority=authority,
    )

    assert result.quality_verdict == "failed"
    assert result.records_materialized == 3
    assert result.records_quarantined == 1
    evidence = json.loads(
        (Path(result.output_root) / "transformation-evidence.json").read_text()
    )
    correction_check = next(
        item
        for item in evidence["quality"]["checks"]
        if item["id"] == "approved_business_corrections_complete"
    )
    assert correction_check["status"] == "failed"


def test_use_geometry_executes_only_the_exact_bound_area_rule(tmp_path: Path) -> None:
    area_rule_ref = "gda://local-dev/quality_rule/jqdltb-planar-area-v1"
    area_rule_path = tmp_path / "geometry-area-rule.json"
    area_rule_path.write_bytes(
        json.dumps(
            {
                "schema": "gda.jqdltb_geometry_area_rule.v1",
                "rule_ref": area_rule_ref,
                "method": "planar_geometry_area_in_source_crs",
                "source_crs": "EPSG:4523",
                "target_field": "TBMJ",
                "output_unit": "square_metre",
                "comparison_tolerance": 0.01,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    area_rule_sha256 = hashlib.sha256(area_rule_path.read_bytes()).hexdigest()
    proposal = _proposal(
        area_deviation_policy=JqdltbAreaDeviationPolicy.USE_GEOMETRY,
        geometry_area_rule_ref=area_rule_ref,
        geometry_area_rule_sha256=area_rule_sha256,
    )
    authority = _Authority()
    executor = _executor(
        tmp_path,
        authority,
        geometry_area_rule_path=area_rule_path,
    )

    result, _contract = _execute(
        proposal=proposal,
        executor=executor,
        authority=authority,
    )

    assert result.quality_verdict == "passed"
    assert result.records_materialized == 2
    ads = json.loads((Path(result.output_root) / "ads/jqdltb.json").read_text())
    by_key = {item["properties"]["TBBH"]: item["properties"] for item in ads["features"]}
    assert by_key["A"]["TBMJ_source"] == 1
    assert by_key["A"]["TBMJ"] == 0.5
    assert by_key["A"]["gda_area_rule_ref"] == area_rule_ref
    assert by_key["A"]["gda_area_rule_sha256"] == area_rule_sha256
    evidence = json.loads(
        (Path(result.output_root) / "transformation-evidence.json").read_text()
    )
    assert evidence["records"]["area_deviation_count"] == 2
    assert evidence["records"]["area_deviation_replaced_count"] == 2


def test_area_deviation_quarantine_is_distinct_from_nonpositive_quarantine(
    tmp_path: Path,
) -> None:
    proposal = _proposal(
        area_deviation_policy=JqdltbAreaDeviationPolicy.QUARANTINE,
    )
    authority = _Authority()
    executor = _executor(tmp_path, authority)

    result, _contract = _execute(
        proposal=proposal,
        executor=executor,
        authority=authority,
    )

    assert result.quality_verdict == "passed"
    assert result.records_materialized == 1
    assert result.records_quarantined == 3
    quarantine = json.loads(
        (Path(result.output_root) / "quarantine/jqdltb.json").read_text()
    )
    reasons = {
        item["properties"]["TBBH"]: item["quarantine_reason"]
        for item in quarantine["features"]
    }
    assert reasons == {
        "A": "area_deviation_outside_tolerance",
        "B": "nonpositive_declared_area",
        "D": "nonpositive_declared_area",
    }
    evidence = json.loads(
        (Path(result.output_root) / "transformation-evidence.json").read_text()
    )
    assert evidence["records"]["area_deviation_count"] == 2
    assert evidence["records"]["area_deviation_quarantined_count"] == 2


def test_derivation_rule_drift_is_rejected_before_creating_outputs(tmp_path: Path) -> None:
    proposal = _proposal()
    authority = _Authority()
    executor = _executor(tmp_path, authority)
    executor.config.derivation_contract_paths["SJNF"].write_text(
        '{"schema":"tampered"}',
        encoding="utf-8",
    )
    case = _approved(proposal)
    authority.cases[case.approval_case_ref] = case
    executable = compile_jqdltb_executable_contract(
        proposal,
        approval_case=case,
        created_by="workload:ar0-contract-compiler",
        created_at=datetime(2026, 8, 23, 3, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="does not match approved SHA-256"):
        executor.execute(
            JqdltbTransformationCommand(
                tenant_id="local-dev",
                run_id=RUN_ID,
                source_resource_version_id=SOURCE_ID,
                contract=executable,
            )
        )
    assert not (tmp_path / "outputs").exists()


def test_replay_rejects_completed_output_without_exact_rule_binding_evidence(
    tmp_path: Path,
) -> None:
    proposal = _proposal()
    authority = _Authority()
    executor = _executor(tmp_path, authority)
    result, executable = _execute(
        proposal=proposal,
        executor=executor,
        authority=authority,
    )
    evidence_path = Path(result.output_root) / "transformation-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["records"].pop("derivation_rule_bindings")
    evidence_path.write_bytes(
        json.dumps(evidence, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )

    with pytest.raises(ValueError, match="rule bindings do not match contract"):
        executor.execute(
            JqdltbTransformationCommand(
                tenant_id="local-dev",
                run_id=RUN_ID,
                source_resource_version_id=SOURCE_ID,
                contract=executable,
            )
        )
