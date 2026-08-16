import json
from copy import deepcopy
from datetime import timedelta

import httpx
import pytest
import yaml
from pydantic import SecretStr, ValidationError

from data_agent import metadata_fabric_ingestion_replay as replay
from data_agent.platform_authorization import (
    AuthorizationEvidenceError,
    build_policy_decision_artifact,
)

EXPECTED_SOURCE_PLAN_SHA256 = "a5c8ef636c03a38d0c6edaacff7d1edeba9c4b8a7f1491c493e9308257c5a94d"
EXPECTED_APPLY_PLAN_SHA256 = "241cb2018c093f76378d265ab8fb617d161c1be7bd4effa6fad361e9db7522c4"
EXPECTED_AUTHORIZATION_SHA256 = "7bc8f577cbdea8d9979b2606278a52176cc2d723a6159c4e1f35ada0f5bb6db0"
EXPECTED_EVIDENCE_SHA256 = "3d5fb07267680520d2f03bf27f354787b7253210eb93ab85aae83d5f5a714dbe"


def _inputs():
    return replay._build_contract_inputs()


def _provider_payloads():
    metadata = json.loads(replay.ingestion.DEFAULT_METADATA_FIXTURE.read_text(encoding="utf-8"))
    return metadata["openmetadata_response"], metadata["gravitino_responses"][0]


class FakeOpenMetadata:
    def __init__(self, table=None, *, fail_apply=False):
        self.table = table
        self.fail_apply = fail_apply
        self.mutations = []
        self.compensated = False

    def get_table(self, _fqn):
        return deepcopy(self.table)

    def apply(self, _plan, _target):
        if self.fail_apply:
            raise replay.ProviderRequestError("OpenMetadata apply failed")
        self.table = deepcopy(_provider_payloads()[0])
        self.mutations.append("openmetadata.table.create")
        return deepcopy(self.table)

    def compensate(self):
        self.table = None
        self.compensated = True
        return True


class FakeGravitino:
    def __init__(self, table=None, *, fail_apply=False, fail_compensation=False):
        self.table = table
        self.fail_apply = fail_apply
        self.fail_compensation = fail_compensation
        self.mutations = []
        self.compensated = False

    def get_table(self, _target):
        return deepcopy(self.table)

    def apply(self, _plan, _target):
        if self.fail_apply:
            raise replay.ProviderRequestError("Gravitino apply failed")
        self.table = deepcopy(_provider_payloads()[1])
        self.mutations.append("gravitino.table.create")
        return deepcopy(self.table)

    def compensate(self):
        if self.fail_compensation:
            raise replay.ProviderRequestError("Gravitino compensation failed")
        self.table = None
        self.compensated = True
        return True


def _apply_once(openmetadata, gravitino, *, authorization=None, at=None):
    profile, plan, run, _target, default_authorization = _inputs()
    return replay.apply_once(
        plan,
        profile,
        authorization or default_authorization,
        run,
        openmetadata=openmetadata,
        gravitino=gravitino,
        at=at or profile.authorization.authorized_at,
    )


def _observation(first, second):
    contract = replay.build_contract_report()
    return {
        "schema": replay.OBSERVATION_SCHEMA,
        "observed_at": "2026-07-28T05:00:00+00:00",
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "source_plan_sha256": EXPECTED_SOURCE_PLAN_SHA256,
            "apply_plan_sha256": EXPECTED_APPLY_PLAN_SHA256,
        },
        "authorization": {
            "authorized": True,
            "authorization_sha256": EXPECTED_AUTHORIZATION_SHA256,
        },
        "cluster": {"context": replay.CONTEXT, "namespace": replay.NAMESPACE},
        "provider_security": {
            "openmetadata": {
                "auth_mode": "local_basic_bootstrap",
                "minimum_privilege_verified": False,
            },
            "gravitino": {
                "auth_mode": "disabled",
                "authentication_verified": False,
            },
        },
        "first_apply": replay._outcome_evidence(first),
        "replay": replay._outcome_evidence(second),
        "runtime_checks": {
            "all_port_forwards_stopped": True,
            "port_forwards": {"openmetadata": True, "gravitino": True},
            "credentials_recorded": False,
            "provider_objects_retained_for_replay": True,
        },
    }


def _rebundle(bundle, *, decision):
    decision_artifact = build_policy_decision_artifact(decision)
    values = {
        "execution_plan_artifact": bundle.execution_plan_artifact,
        "policy_decision_artifact": decision_artifact,
        "approval_artifact": bundle.approval_artifact,
    }
    return replay.ApplyAuthorizationBundle(
        **values,
        authorization_sha256=replay.canonical_json_fingerprint(
            {key: value.model_dump(mode="json") for key, value in values.items()}
        ),
    )


def test_static_contract_plan_and_authorization_are_deterministic():
    profile, plan, run, target, authorization = _inputs()
    contract = replay.build_contract_report()

    assert profile.environment == "local_docker_desktop"
    assert plan.source_plan_sha256 == EXPECTED_SOURCE_PLAN_SHA256
    assert plan.apply_plan_sha256 == EXPECTED_APPLY_PLAN_SHA256
    assert authorization.authorization_sha256 == EXPECTED_AUTHORIZATION_SHA256
    assert target.resource_version_id == plan.resource_version_id
    assert run.run_id == plan.run_id
    assert contract["local_static_contract_verified"] is True
    assert contract["provider_apply_authorized"] is False
    assert contract["local_live_provider_ingestion_verified"] is False


def test_local_apply_uses_natural_targets_not_synthetic_openmetadata_uuid():
    profile, plan, _run, _target, _authorization = _inputs()
    source_target = next(
        item.target_identity for item in plan.projections if item.provider == "openmetadata"
    )

    assert source_target == "table:10000000-0000-4000-8000-000000000001"
    assert plan.openmetadata_fqn == profile.targets.openmetadata.table_fqn
    assert "10000000-0000-4000-8000-000000000001" not in plan.openmetadata_fqn
    assert plan.gravitino_identity == profile.targets.gravitino.identity
    assert plan.writes_to_gda_control is False


def test_exact_policy_and_independent_approval_authorize_local_apply():
    profile, plan, run, _target, authorization = _inputs()

    decision, approval = replay.validate_apply_authorization(
        plan,
        run,
        authorization,
        at=profile.authorization.authorized_at,
    )

    assert decision.action == replay.ACTION
    assert plan.resource_version_id in decision.resource_version_ids
    assert decision.evaluator_subject != (
        f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    )
    assert approval.approver_subject not in {
        decision.evaluator_subject,
        f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}",
    }


def test_policy_scope_effect_expiry_and_approval_binding_fail_closed():
    profile, plan, run, _target, authorization = _inputs()
    decision = replay.parse_policy_decision_artifact(authorization.policy_decision_artifact)

    for changed, message in (
        (
            decision.model_copy(
                update={
                    "resource_version_ids": (
                        plan.definition_version_id,
                        plan.source_resource_version_id,
                    )
                }
            ),
            "exact plan scope",
        ),
        (
            decision.model_copy(update={"effect": replay.PolicyEffect.DENY}),
            "does not allow",
        ),
    ):
        with pytest.raises(AuthorizationEvidenceError, match=message):
            replay.validate_apply_authorization(
                plan,
                run,
                _rebundle(authorization, decision=changed),
                at=profile.authorization.authorized_at,
            )

    with pytest.raises(AuthorizationEvidenceError, match="not active"):
        replay.validate_apply_authorization(
            plan,
            run,
            authorization,
            at=profile.authorization.expires_at + timedelta(seconds=1),
        )

    tampered = authorization.model_copy(
        update={
            "approval_artifact": authorization.approval_artifact.model_copy(
                update={"content_sha256": "f" * 64}
            )
        }
    )
    with pytest.raises(AuthorizationEvidenceError, match="metadata"):
        replay.validate_apply_authorization(
            plan,
            run,
            tampered,
            at=profile.authorization.authorized_at,
        )


def test_first_apply_creates_both_projections_and_second_is_no_op():
    openmetadata = FakeOpenMetadata()
    gravitino = FakeGravitino()

    first = _apply_once(openmetadata, gravitino)
    second = _apply_once(openmetadata, gravitino)

    assert first.status == replay.ApplyStatus.CREATED
    assert first.mutations == (
        "openmetadata.table.create",
        "gravitino.table.create",
    )
    assert second.status == replay.ApplyStatus.NO_OP
    assert second.mutations == ()
    assert first.openmetadata == second.openmetadata
    assert first.gravitino == second.gravitino
    assert first.binding_candidate_sha256 == second.binding_candidate_sha256


def test_partial_provider_inventory_blocks_before_any_mutation():
    openmetadata_payload, _gravitino_payload = _provider_payloads()
    openmetadata = FakeOpenMetadata(openmetadata_payload)
    gravitino = FakeGravitino()

    with pytest.raises(
        replay.MetadataFabricPartialProjectionError,
        match="partially materialized",
    ):
        _apply_once(openmetadata, gravitino)

    assert openmetadata.mutations == []
    assert gravitino.mutations == []


def test_governance_or_gda_identity_drift_blocks_replay():
    openmetadata_payload, gravitino_payload = _provider_payloads()
    openmetadata_payload["owners"][0]["fullyQualifiedName"] = "wrong-owner"
    openmetadata = FakeOpenMetadata(openmetadata_payload)
    gravitino = FakeGravitino(gravitino_payload)

    with pytest.raises(
        replay.MetadataFabricIngestionReplayError,
        match="governance projection drift",
    ):
        _apply_once(openmetadata, gravitino)

    openmetadata_payload, gravitino_payload = _provider_payloads()
    gravitino_payload["table"]["properties"]["gda.content_sha256"] = "0" * 64
    with pytest.raises(
        replay.MetadataFabricIngestionReplayError,
        match="live GDA identity drift",
    ):
        _apply_once(
            FakeOpenMetadata(openmetadata_payload),
            FakeGravitino(gravitino_payload),
        )


def test_second_provider_failure_compensates_new_provider_roots():
    openmetadata = FakeOpenMetadata()
    gravitino = FakeGravitino(fail_apply=True)

    with pytest.raises(replay.ProviderRequestError, match="Gravitino apply failed"):
        _apply_once(openmetadata, gravitino)

    assert openmetadata.compensated is True
    assert gravitino.compensated is True
    assert openmetadata.table is None


def test_incomplete_compensation_replaces_original_failure():
    openmetadata = FakeOpenMetadata()
    gravitino = FakeGravitino(fail_apply=True, fail_compensation=True)

    with pytest.raises(
        replay.MetadataFabricIngestionReplayError,
        match="compensation was incomplete",
    ):
        _apply_once(openmetadata, gravitino)


def test_profile_rejects_embedded_secret_and_production_overclaim(tmp_path):
    profile = yaml.safe_load(replay.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["providers"]["openmetadata"]["password"] = "forbidden"
    profile["claims"]["production_ready"] = True
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile), encoding="utf-8")

    with pytest.raises(
        replay.MetadataFabricIngestionReplayError,
        match="profile is invalid",
    ):
        replay.load_profile(path)


def test_provider_request_error_never_echoes_response_credentials():
    def handler(_request):
        return httpx.Response(
            403,
            json={"message": "token=must-not-escape", "password": "hidden"},
        )

    client = replay.GravitinoApplyClient(
        base_url="https://gravitino.invalid/api",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(replay.ProviderRequestError) as captured:
            client.get_table(_inputs()[0].targets.gravitino)
    finally:
        client.close()

    rendered = str(captured.value)
    assert "must-not-escape" not in rendered
    assert "hidden" not in rendered
    assert "403" in rendered


def test_gravitino_table_lookup_stops_when_parent_is_absent():
    requested_paths = []

    def handler(request):
        requested_paths.append(request.url.path)
        return httpx.Response(404, json={"message": "metalake not found"})

    client = replay.GravitinoApplyClient(
        base_url="https://gravitino.invalid/api",
        transport=httpx.MockTransport(handler),
    )
    target = _inputs()[0].targets.gravitino
    try:
        assert client.get_table(target) is None
    finally:
        client.close()

    assert requested_paths == [f"/api/metalakes/{target.metalake}"]


def test_openmetadata_login_keeps_access_token_out_of_principal_projection():
    def handler(request):
        if request.url.path.endswith("/users/login"):
            return httpx.Response(200, json={"accessToken": "local-secret-token"})
        if request.url.path.endswith("/users/name/admin"):
            assert request.headers["authorization"] == "Bearer local-secret-token"
            return httpx.Response(
                200,
                json={
                    "id": "10000000-0000-4000-8000-000000000099",
                    "name": "admin",
                    "isAdmin": True,
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    client = replay.OpenMetadataApplyClient(
        base_url="https://openmetadata.invalid/api/v1",
        username="admin@open-metadata.org",
        password=SecretStr("admin"),
        transport=httpx.MockTransport(handler),
    )
    try:
        principal = client.authenticated_principal()
    finally:
        client.close()

    assert principal == {
        "id": "10000000-0000-4000-8000-000000000099",
        "name": "admin",
        "is_admin": True,
    }
    assert "token" not in json.dumps(principal).lower()


def test_evidence_verifies_only_local_created_then_no_op_replay():
    openmetadata = FakeOpenMetadata()
    gravitino = FakeGravitino()
    first = _apply_once(openmetadata, gravitino)
    second = _apply_once(openmetadata, gravitino)

    evidence = replay.build_evidence(_observation(first, second))

    assert evidence["status"] == "local_live_ingestion_replay_verified"
    assert evidence["local_live_provider_ingestion_verified"] is True
    assert evidence["deterministic_live_replay_verified"] is True
    assert evidence["provider_mutations_executed"] is True
    assert evidence["provider_minimum_privilege_verified"] is False
    assert evidence["oidc_verified"] is False
    assert evidence["gravitino_authentication_verified"] is False
    assert evidence["binding_persisted_to_gda_control"] is False
    assert evidence["production_ready"] is False
    assert replay.verify_evidence_integrity(evidence) == []


def test_evidence_blocks_replay_mutation_cleanup_failure_and_credentials():
    openmetadata = FakeOpenMetadata()
    gravitino = FakeGravitino()
    first = _apply_once(openmetadata, gravitino)
    second = _apply_once(openmetadata, gravitino)
    observation = _observation(first, second)
    observation["replay"]["status"] = "created"
    observation["replay"]["mutation_count"] = 1
    observation["runtime_checks"]["all_port_forwards_stopped"] = False
    observation["api_token"] = "forbidden"

    evidence = replay.build_evidence(observation)

    assert evidence["status"] == "blocked"
    assert evidence["local_live_provider_ingestion_verified"] is False
    assert "credential-bearing fields" in "\n".join(evidence["errors"])
    assert "zero-mutation replay" in "\n".join(evidence["errors"])
    assert "port-forwards" in "\n".join(evidence["errors"])


def test_evidence_integrity_rejects_production_overclaim_and_tampering():
    openmetadata = FakeOpenMetadata()
    gravitino = FakeGravitino()
    first = _apply_once(openmetadata, gravitino)
    second = _apply_once(openmetadata, gravitino)
    evidence = replay.build_evidence(_observation(first, second))
    tampered = deepcopy(evidence)
    tampered["production_ready"] = True

    errors = replay.verify_evidence_integrity(tampered)

    assert "local ingestion evidence fingerprint does not match" in errors
    assert "local ingestion evidence may not claim production_ready" in errors


def test_committed_live_evidence_is_integrity_checked_and_local_only():
    evidence = json.loads(replay.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))

    assert evidence["evidence_fingerprint"] == EXPECTED_EVIDENCE_SHA256
    assert replay.verify_evidence_integrity(evidence) == []
    assert evidence["local_live_provider_ingestion_verified"] is True
    assert evidence["deterministic_live_replay_verified"] is True
    assert evidence["observation"]["first_apply"]["status"] == "created"
    assert evidence["observation"]["first_apply"]["mutation_count"] > 0
    assert evidence["observation"]["replay"]["status"] == "no_op"
    assert evidence["observation"]["replay"]["mutation_count"] == 0
    for claim in (
        "provider_minimum_privilege_verified",
        "oidc_verified",
        "gravitino_authentication_verified",
        "binding_persisted_to_gda_control",
        "writes_to_gda_control",
        "writes_to_legacy",
        "live_openlineage_emission_verified",
        "production_ingestion_verified",
        "production_ready",
    ):
        assert evidence[claim] is False


def test_validation_accepts_allowlisted_history_when_semantics_match():
    report = replay.build_validation_report()

    assert report["errors"] == []
    assert report["contract_fingerprint_matches_current"] is False
    assert report["semantic_contract_compatibility_verified"] is True
    assert report["historical_contract_compatibility_verified"] is True
    assert report["local_live_provider_ingestion_verified"] is True
    assert report["deterministic_live_replay_verified"] is True


def test_validation_rejects_unknown_history_and_semantic_drift(tmp_path):
    first = _apply_once(FakeOpenMetadata(), FakeGravitino())
    replay_openmetadata = FakeOpenMetadata(_provider_payloads()[0])
    replay_gravitino = FakeGravitino(_provider_payloads()[1])
    second = _apply_once(replay_openmetadata, replay_gravitino)

    for name, mutate, expected in (
        (
            "unknown-contract",
            lambda observation: observation["contract"].__setitem__(
                "contract_fingerprint", "f" * 64
            ),
            "contract fingerprint is unsupported",
        ),
        (
            "semantic-drift",
            lambda observation: (
                observation["contract"].__setitem__(
                    "contract_fingerprint",
                    next(iter(replay.HISTORICAL_EVIDENCE_CONTRACT_FINGERPRINTS)),
                ),
                observation["contract"].__setitem__("source_plan_sha256", "f" * 64),
            ),
            "semantic contract drift",
        ),
    ):
        observation = _observation(first, second)
        mutate(observation)
        evidence = replay.build_evidence(observation)
        evidence_path = tmp_path / f"{name}.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

        report = replay.build_validation_report(evidence_path=evidence_path)

        assert expected in "\n".join(report["errors"])


def test_apply_plan_and_authorization_models_reject_hash_tampering():
    _profile, plan, _run, _target, authorization = _inputs()
    with pytest.raises(ValidationError, match="fingerprint"):
        replay.LocalApplyPlan.model_validate(
            {
                **plan.model_dump(mode="python", by_alias=True),
                "apply_plan_sha256": "f" * 64,
            }
        )
    with pytest.raises(ValidationError, match="fingerprint"):
        replay.ApplyAuthorizationBundle.model_validate(
            {
                **authorization.model_dump(mode="python"),
                "authorization_sha256": "f" * 64,
            }
        )
