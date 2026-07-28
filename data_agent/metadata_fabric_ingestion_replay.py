"""Run the bounded M3-2 local Metadata Fabric ingestion/replay rehearsal.

This module turns the deterministic M3-1 projection into a local provider
materialization. It requires content-bound PolicyDecision and Approval
artifacts before any mutation, creates provider objects by stable natural key,
reads the provider-assigned OpenMetadata UUID back into a binding candidate,
and proves that a second pass performs zero mutations.

The local OpenMetadata profile uses its bootstrap Basic administrator and the
local Gravitino profile has authentication disabled. Those limitations remain
explicitly false production claims; no credential is written to evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import quote
from uuid import UUID, uuid5

import httpx
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from . import metadata_fabric_bridge as bridge
from . import metadata_fabric_ingestion as ingestion
from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery
from .platform_authorization import (
    AuthorizationEvidenceError,
    build_approval_artifact,
    build_policy_decision_artifact,
    parse_approval_artifact,
    parse_policy_decision_artifact,
)
from .platform_contracts import (
    ApprovalRecord,
    Artifact,
    ArtifactRole,
    PlatformRun,
    PolicyDecision,
    PolicyEffect,
    ResourceVersion,
    Sha256,
    canonical_json_bytes,
    canonical_json_fingerprint,
)

PROFILE_SCHEMA = "gda.metadata_fabric_local_ingestion_profile.v1"
APPLY_PLAN_SCHEMA = "gda.metadata_fabric_local_apply_plan.v1"
EXECUTION_PLAN_SCHEMA = "gda.metadata_fabric_local_apply_execution_plan.v1"
CONTRACT_SCHEMA = "gda.metadata_fabric_local_ingestion_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_local_ingestion_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_local_ingestion_evidence.v1"
ACTION = "metadata_fabric.apply"
CONTEXT = "docker-desktop"
NAMESPACE = "gda-metadata-sandbox"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-ingestion-replay.local.yaml"
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-ingestion-replay.sh"
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-ingestion-replay-2026-07-28.json"
)

DNS_LABEL_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,254}$")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(^|[-_.])(password|passwd|secret|token|private[-_.]?key|"
    r"access[-_.]?key|authorization|credential)($|[-_.])",
    re.IGNORECASE,
)
GDA_CUSTOM_PROPERTIES = {
    "gdaResourceUrn": "Canonical GDA ResourceURN",
    "gdaResourceVersionId": "Immutable GDA ResourceVersion UUID",
    "gdaContentSha256": "Canonical GDA content SHA-256",
}
SAFE_SECURITY_FIELD_NAMES = {
    "authorization",
    "authorization_sha256",
    "credentials_recorded",
}

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
ProviderName = Literal["openmetadata", "gravitino"]


class MetadataFabricIngestionReplayError(RuntimeError):
    """The bounded local ingestion/replay rehearsal failed closed."""


class MetadataFabricPartialProjectionError(MetadataFabricIngestionReplayError):
    """Only one provider contains the target projection."""


class ProviderRequestError(MetadataFabricIngestionReplayError):
    """A provider rejected or failed an allowlisted request."""


class ApplyStatus(str, Enum):
    CREATED = "created"
    NO_OP = "no_op"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClusterProfile(_FrozenModel):
    context: Literal["docker-desktop"]
    namespace: Literal["gda-metadata-sandbox"]


class OpenMetadataProviderProfile(_FrozenModel):
    version: Literal["1.13.1"]
    service: Literal["openmetadata"]
    service_port: Literal[8585]
    auth_mode: Literal["local_basic_bootstrap"]
    username_env: Literal["GDA_OPENMETADATA_USERNAME"]
    password_env: Literal["GDA_OPENMETADATA_PASSWORD"]


class GravitinoProviderProfile(_FrozenModel):
    version: Literal["1.3.0"]
    service: Literal["metadata-gravitino"]
    service_port: Literal[8090]
    auth_mode: Literal["disabled"]


class ProviderProfiles(_FrozenModel):
    openmetadata: OpenMetadataProviderProfile
    gravitino: GravitinoProviderProfile


class OpenMetadataTarget(_FrozenModel):
    service: NonEmptyText
    service_type: Literal["CustomDatabase"]
    database: NonEmptyText
    schema_name: NonEmptyText = Field(alias="schema")
    table: NonEmptyText
    owner_team: NonEmptyText
    domain: NonEmptyText
    classification: NonEmptyText
    classification_tag: NonEmptyText
    glossary: NonEmptyText
    glossary_term: NonEmptyText

    @field_validator("*")
    @classmethod
    def _safe_names(cls, value: Any) -> Any:
        if isinstance(value, str) and not DNS_LABEL_PATTERN.fullmatch(value):
            raise ValueError("OpenMetadata target name is not provider-safe")
        return value

    @property
    def table_fqn(self) -> str:
        return f"{self.service}.{self.database}.{self.schema_name}.{self.table}"


class GravitinoTarget(_FrozenModel):
    metalake: NonEmptyText
    catalog: NonEmptyText
    schema_name: NonEmptyText = Field(alias="schema")
    table: NonEmptyText
    catalog_type: Literal["RELATIONAL"]
    catalog_provider: Literal["lakehouse-iceberg"]
    catalog_backend: Literal["memory"]
    uri: Literal["file:///tmp/gda-m3-local"]
    warehouse: Literal["file:///tmp/gda-m3-local"]

    @field_validator("metalake", "catalog", "schema_name", "table")
    @classmethod
    def _safe_names(cls, value: str) -> str:
        if not DNS_LABEL_PATTERN.fullmatch(value):
            raise ValueError("Gravitino target name is not provider-safe")
        return value

    @property
    def identity(self) -> str:
        return f"{self.metalake}.{self.catalog}.{self.schema_name}.{self.table}"


class ProviderTargets(_FrozenModel):
    openmetadata: OpenMetadataTarget
    gravitino: GravitinoTarget


class AuthorizationProfile(_FrozenModel):
    action: Literal["metadata_fabric.apply"]
    policy_version_ref: NonEmptyText
    evaluator_subject: NonEmptyText
    approver_subject: NonEmptyText
    approval_reason: NonEmptyText
    decided_at: datetime
    approval_decided_at: datetime
    authorized_at: datetime
    approval_expires_at: datetime
    expires_at: datetime

    @field_validator(
        "decided_at",
        "approval_decided_at",
        "authorized_at",
        "approval_expires_at",
        "expires_at",
    )
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authorization timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _ordered_and_separated(self) -> Self:
        if not self.evaluator_subject.startswith("workload:"):
            raise ValueError("policy evaluator must be a workload")
        if not self.approver_subject.startswith("human:"):
            raise ValueError("approver must be a human")
        if not (
            self.decided_at
            <= self.approval_decided_at
            <= self.authorized_at
            < self.approval_expires_at
            <= self.expires_at
        ):
            raise ValueError("authorization timestamps are not ordered")
        return self


class ClaimBoundary(_FrozenModel):
    provider_minimum_privilege_verified: Literal[False]
    oidc_verified: Literal[False]
    gravitino_authentication_verified: Literal[False]
    binding_persisted_to_gda_control: Literal[False]
    live_openlineage_emission_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class LocalIngestionProfile(_FrozenModel):
    profile_schema: Literal["gda.metadata_fabric_local_ingestion_profile.v1"] = Field(
        alias="schema"
    )
    environment: Literal["local_docker_desktop"]
    cluster: ClusterProfile
    providers: ProviderProfiles
    targets: ProviderTargets
    authorization: AuthorizationProfile
    claims: ClaimBoundary


class LocalApplyPlan(_FrozenModel):
    apply_schema: Literal["gda.metadata_fabric_local_apply_plan.v1"] = Field(
        default=APPLY_PLAN_SCHEMA,
        alias="schema",
    )
    source_plan_sha256: Sha256
    tenant_id: NonEmptyText
    run_id: UUID
    definition_version_id: UUID
    source_resource_version_id: UUID
    resource_urn: NonEmptyText
    resource_version_id: UUID
    content_sha256: Sha256
    openmetadata_fqn: NonEmptyText
    gravitino_identity: NonEmptyText
    projections: tuple[ingestion.ProviderProjection, ...]
    provider_apply_authorized: Literal[False] = False
    writes_to_gda_control: Literal[False] = False
    writes_to_legacy: Literal[False] = False
    apply_plan_sha256: Sha256

    @model_validator(mode="after")
    def _content_bound(self) -> Self:
        providers = [item.provider for item in self.projections]
        if providers != ["openmetadata", "gravitino"]:
            raise ValueError("local apply plan requires the two ordered providers")
        expected_identity = (
            self.resource_urn,
            str(self.resource_version_id),
            self.content_sha256,
        )
        for projection in self.projections:
            observed = tuple(
                projection.desired_state[key]
                for key in (
                    "resource_urn",
                    "resource_version_id",
                    "content_sha256",
                )
            )
            if observed != expected_identity:
                raise ValueError("local projection identity does not match plan")
        stable = self.model_dump(
            mode="json", by_alias=True, exclude={"apply_plan_sha256"}
        )
        if self.apply_plan_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("local apply plan fingerprint does not match")
        return self


class ApplyAuthorizationBundle(_FrozenModel):
    execution_plan_artifact: Artifact
    policy_decision_artifact: Artifact
    approval_artifact: Artifact
    authorization_sha256: Sha256

    @model_validator(mode="after")
    def _fingerprint(self) -> Self:
        stable = self.model_dump(mode="json", exclude={"authorization_sha256"})
        if self.authorization_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("apply authorization fingerprint does not match")
        return self


class ApplyOutcome(_FrozenModel):
    status: ApplyStatus
    mutations: tuple[NonEmptyText, ...] = ()
    openmetadata: bridge.OpenMetadataObservation
    gravitino: bridge.GravitinoObservation
    binding_candidate_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_status(self) -> Self:
        if (self.status == ApplyStatus.NO_OP) != (not self.mutations):
            raise ValueError("no-op apply outcome must have no mutations")
        return self


def _load_yaml_object(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MetadataFabricIngestionReplayError("profile must be a YAML object")
    return payload


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> LocalIngestionProfile:
    try:
        payload = _load_yaml_object(path.resolve())
        _reject_sensitive_fields(payload)
        return LocalIngestionProfile.model_validate(payload)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise MetadataFabricIngestionReplayError(
            "local ingestion profile is invalid"
        ) from exc


def _reject_sensitive_fields(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if (
                SENSITIVE_KEY_PATTERN.search(normalized)
                and not normalized.endswith("_env")
                and normalized not in SAFE_SECURITY_FIELD_NAMES
            ):
                raise ValueError(f"{path}.{key} is credential-bearing")
            _reject_sensitive_fields(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_sensitive_fields(item, path=f"{path}[{index}]")


def build_local_apply_plan(
    source: ingestion.MetadataFabricIngestionPlan,
    profile: LocalIngestionProfile,
) -> LocalApplyPlan:
    if profile.targets.openmetadata.table_fqn != (
        "gda_lakehouse.land_use.published.land_use_parcels"
    ):
        raise MetadataFabricIngestionReplayError(
            "OpenMetadata natural target does not match the M3-1 slice"
        )
    if profile.targets.gravitino.identity != (
        "gda_lakehouse.iceberg.land_use.land_use_parcels"
    ):
        raise MetadataFabricIngestionReplayError(
            "Gravitino natural target does not match the M3-1 slice"
        )
    values: dict[str, Any] = {
        "source_plan_sha256": source.plan_sha256,
        "tenant_id": source.tenant_id,
        "run_id": source.run_id,
        "definition_version_id": source.definition_version_id,
        "source_resource_version_id": source.source_resource_version_id,
        "resource_urn": source.resource_urn,
        "resource_version_id": source.resource_version_id,
        "content_sha256": source.content_sha256,
        "openmetadata_fqn": profile.targets.openmetadata.table_fqn,
        "gravitino_identity": profile.targets.gravitino.identity,
        "projections": source.projections,
    }
    stable = {
        "schema": APPLY_PLAN_SCHEMA,
        **{
            key: (
                [item.model_dump(mode="json") for item in value]
                if key == "projections"
                else str(value)
                if isinstance(value, UUID)
                else value
            )
            for key, value in values.items()
        },
        "provider_apply_authorized": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
    }
    return LocalApplyPlan(
        **values,
        apply_plan_sha256=canonical_json_fingerprint(stable),
    )


def build_execution_plan_artifact(
    plan: LocalApplyPlan,
    *,
    created_by: str,
    created_at: datetime,
) -> Artifact:
    manifest = {
        "schema": EXECUTION_PLAN_SCHEMA,
        "plan": plan.model_dump(mode="json", by_alias=True),
    }
    artifact_id = uuid5(plan.run_id, f"metadata-fabric-apply:{plan.apply_plan_sha256}")
    return Artifact(
        tenant_id=plan.tenant_id,
        artifact_id=artifact_id,
        artifact_key=f"metadata-fabric-apply:{artifact_id}",
        artifact_role=ArtifactRole.EXECUTION_PLAN,
        storage_uri=(
            f"postgresql://gda-control/execution-plans/{plan.tenant_id}/{artifact_id}"
        ),
        media_type="application/vnd.gda.metadata-fabric-apply-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(canonical_json_bytes(manifest)),
        run_id=None,
        resource_version_id=plan.definition_version_id,
        manifest=manifest,
        created_by=created_by,
        created_at=created_at,
    )


def build_apply_authorization(
    plan: LocalApplyPlan,
    run: PlatformRun,
    profile: LocalIngestionProfile,
) -> ApplyAuthorizationBundle:
    auth = profile.authorization
    actor = f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    execution_plan = build_execution_plan_artifact(
        plan,
        created_by=actor,
        created_at=auth.decided_at,
    )
    decision = PolicyDecision(
        tenant_id=plan.tenant_id,
        run_id=plan.run_id,
        subject_context=run.subject_context,
        action=auth.action,
        definition_version_id=plan.definition_version_id,
        resource_version_ids=(
            plan.definition_version_id,
            plan.source_resource_version_id,
            plan.resource_version_id,
        ),
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect=PolicyEffect.ALLOW,
        policy_version_ref=auth.policy_version_ref,
        evaluator_subject=auth.evaluator_subject,
        requires_approval=True,
        obligations=(),
        decided_at=auth.decided_at,
        expires_at=auth.expires_at,
    )
    decision_artifact = build_policy_decision_artifact(decision)
    approval = ApprovalRecord(
        tenant_id=plan.tenant_id,
        run_id=plan.run_id,
        definition_version_id=plan.definition_version_id,
        policy_decision_artifact_id=decision_artifact.artifact_id,
        policy_decision_sha256=decision_artifact.content_sha256,
        verdict="approved",
        approver_subject=auth.approver_subject,
        reason=auth.approval_reason,
        decided_at=auth.approval_decided_at,
        expires_at=auth.approval_expires_at,
    )
    approval_artifact = build_approval_artifact(approval)
    values = {
        "execution_plan_artifact": execution_plan,
        "policy_decision_artifact": decision_artifact,
        "approval_artifact": approval_artifact,
    }
    stable = {key: value.model_dump(mode="json") for key, value in values.items()}
    bundle = ApplyAuthorizationBundle(
        **values,
        authorization_sha256=canonical_json_fingerprint(stable),
    )
    validate_apply_authorization(plan, run, bundle, at=auth.authorized_at)
    return bundle


def validate_apply_authorization(
    plan: LocalApplyPlan,
    run: PlatformRun,
    bundle: ApplyAuthorizationBundle,
    *,
    at: datetime,
) -> tuple[PolicyDecision, ApprovalRecord]:
    if at.tzinfo is None or at.utcoffset() is None:
        raise AuthorizationEvidenceError("authorization time must include a timezone")
    decision = parse_policy_decision_artifact(bundle.policy_decision_artifact)
    approval = parse_approval_artifact(bundle.approval_artifact)
    expected_scope = tuple(
        sorted(
            {
                plan.definition_version_id,
                plan.source_resource_version_id,
                plan.resource_version_id,
            },
            key=str,
        )
    )
    actor = f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    execution_plan = bundle.execution_plan_artifact
    expected_execution_plan = build_execution_plan_artifact(
        plan,
        created_by=actor,
        created_at=decision.decided_at,
    )
    scope_matches = (
        decision.tenant_id == plan.tenant_id == run.tenant_id
        and decision.run_id == plan.run_id == run.run_id
        and decision.subject_context == run.subject_context
        and decision.action == ACTION
        and decision.definition_version_id == plan.definition_version_id
        and decision.resource_version_ids == expected_scope
        and decision.execution_plan_artifact_id == execution_plan.artifact_id
        and execution_plan == expected_execution_plan
    )
    if not scope_matches:
        raise AuthorizationEvidenceError(
            "metadata apply authorization does not match the exact plan scope"
        )
    if decision.effect != PolicyEffect.ALLOW or decision.obligations:
        raise AuthorizationEvidenceError("metadata apply policy does not allow apply")
    if decision.evaluator_subject == actor:
        raise AuthorizationEvidenceError("policy evaluator is not independent")
    if not (decision.decided_at <= at < decision.expires_at):
        raise AuthorizationEvidenceError("metadata apply policy is not active")
    approval_matches = (
        decision.requires_approval
        and approval.tenant_id == plan.tenant_id
        and approval.run_id == plan.run_id
        and approval.definition_version_id == plan.definition_version_id
        and approval.policy_decision_artifact_id
        == bundle.policy_decision_artifact.artifact_id
        and approval.policy_decision_sha256
        == bundle.policy_decision_artifact.content_sha256
        and approval.verdict.value == "approved"
        and approval.approver_subject not in {actor, decision.evaluator_subject}
        and decision.decided_at <= approval.decided_at <= at
        and at < approval.expires_at <= decision.expires_at
    )
    if not approval_matches:
        raise AuthorizationEvidenceError(
            "metadata apply approval does not authorize the policy decision"
        )
    return decision, approval


def _build_contract_inputs(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> tuple[
    LocalIngestionProfile,
    LocalApplyPlan,
    PlatformRun,
    ResourceVersion,
    ApplyAuthorizationBundle,
]:
    profile = load_profile(profile_path)
    values = ingestion._load_contract_inputs(
        ingestion.DEFAULT_PLATFORM_FIXTURE,
        ingestion.DEFAULT_METADATA_FIXTURE,
    )
    source_plan = ingestion.build_ingestion_plan(
        metadata_resource=values[2],
        target=values[3],
        binding=values[4],
        definition=values[5],
        run=values[6],
        source=values[7],
        artifact=values[8],
        quality=values[9],
        lineage=values[10],
        success=values[11],
        openmetadata=values[12],
        gravitino=values[13],
    )
    plan = build_local_apply_plan(source_plan, profile)
    run = values[6]
    target = values[3]
    authorization = build_apply_authorization(plan, run, profile)
    return profile, plan, run, target, authorization


class _ProviderHttpClient:
    provider_name = "provider"

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers=dict(headers),
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        try:
            response = self._client.request(
                method,
                path,
                json=json_body,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise ProviderRequestError(
                f"{self.provider_name} {method} request failed"
            ) from exc
        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code >= 400:
            raise ProviderRequestError(
                f"{self.provider_name} rejected {method} request "
                f"with status {response.status_code}"
            )
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderRequestError(
                f"{self.provider_name} returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderRequestError(
                f"{self.provider_name} response is not an object"
            )
        return payload


class OpenMetadataApplyClient(_ProviderHttpClient):
    provider_name = "OpenMetadata"

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: SecretStr,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        login_client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=30.0,
            transport=transport,
        )
        encoded = base64.b64encode(password.get_secret_value().encode("utf-8")).decode(
            "ascii"
        )
        try:
            response = login_client.post(
                "users/login",
                json={"email": username, "password": encoded},
            )
        except httpx.HTTPError as exc:
            login_client.close()
            raise ProviderRequestError("OpenMetadata login request failed") from exc
        login_client.close()
        if response.status_code != 200:
            raise ProviderRequestError("OpenMetadata rejected local bootstrap login")
        try:
            token = SecretStr(response.json()["accessToken"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderRequestError(
                "OpenMetadata login did not return an access token"
            ) from exc
        super().__init__(
            base_url=base_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token.get_secret_value()}",
            },
            transport=transport,
        )
        self.mutations: list[str] = []
        self.created_entities: list[tuple[str, UUID]] = []

    @staticmethod
    def _name(value: str) -> str:
        return quote(value, safe="")

    def authenticated_principal(self) -> dict[str, Any]:
        user = self._request("GET", "users/name/admin")
        assert user is not None
        return {
            "id": user.get("id"),
            "name": user.get("name"),
            "is_admin": user.get("isAdmin"),
        }

    def _get_named(
        self,
        collection: str,
        name: str,
        *,
        fields: str | None = None,
    ) -> dict[str, Any] | None:
        params = {"fields": fields} if fields else None
        return self._request(
            "GET",
            f"{collection}/name/{self._name(name)}",
            params=params,
            allow_not_found=True,
        )

    def _ensure_named(
        self,
        *,
        collection: str,
        name: str,
        payload: dict[str, Any],
        operation: str,
    ) -> tuple[dict[str, Any], bool]:
        existing = self._get_named(collection, name)
        if existing is not None:
            return existing, False
        created = self._request("PUT", collection, json_body=payload)
        assert created is not None
        self.mutations.append(operation)
        self.created_entities.append((collection, UUID(str(created["id"]))))
        return created, True

    def get_table(self, fqn: str) -> dict[str, Any] | None:
        return self._get_named(
            "tables",
            fqn,
            fields="owners,domains,tags,extension",
        )

    def _ensure_custom_properties(self) -> None:
        table_type = self._request(
            "GET",
            "metadata/types/name/table",
            params={"fields": "customProperties"},
        )
        string_type = self._request("GET", "metadata/types/name/string")
        assert table_type is not None and string_type is not None
        existing = {
            item.get("name"): item
            for item in table_type.get("customProperties", [])
            if isinstance(item, dict)
        }
        for name, description in GDA_CUSTOM_PROPERTIES.items():
            if name in existing:
                property_type = existing[name].get("propertyType") or {}
                if property_type.get("name") != "string":
                    raise MetadataFabricIngestionReplayError(
                        f"OpenMetadata custom property type drift: {name}"
                    )
                continue
            self._request(
                "PUT",
                f"metadata/types/{table_type['id']}",
                json_body={
                    "name": name,
                    "description": description,
                    "propertyType": {
                        "id": string_type["id"],
                        "type": "type",
                    },
                },
            )
            self.mutations.append(f"openmetadata.custom_property.create:{name}")

    def apply(
        self,
        plan: LocalApplyPlan,
        target: OpenMetadataTarget,
    ) -> dict[str, Any]:
        self._ensure_custom_properties()
        team, _ = self._ensure_named(
            collection="teams",
            name=target.owner_team,
            payload={
                "name": target.owner_team,
                "teamType": "Group",
                "description": "GDA local metadata projection owner",
            },
            operation="openmetadata.team.create",
        )
        domain, _ = self._ensure_named(
            collection="domains",
            name=target.domain,
            payload={
                "name": target.domain,
                "domainType": "Source-aligned",
                "description": "GDA local natural-resources domain",
            },
            operation="openmetadata.domain.create",
        )
        self._ensure_named(
            collection="classifications",
            name=target.classification,
            payload={
                "name": target.classification,
                "description": "GDA local sensitivity classification",
                "provider": "automation",
            },
            operation="openmetadata.classification.create",
        )
        self._ensure_named(
            collection="tags",
            name=f"{target.classification}.{target.classification_tag}",
            payload={
                "name": target.classification_tag,
                "classification": target.classification,
                "description": "Internal-use metadata projection",
                "provider": "automation",
            },
            operation="openmetadata.classification_tag.create",
        )
        self._ensure_named(
            collection="glossaries",
            name=target.glossary,
            payload={
                "name": target.glossary,
                "description": "GDA local land-use glossary",
                "provider": "automation",
            },
            operation="openmetadata.glossary.create",
        )
        self._ensure_named(
            collection="glossaryTerms",
            name=f"{target.glossary}.{target.glossary_term}",
            payload={
                "name": target.glossary_term,
                "glossary": target.glossary,
                "description": "Land-use parcel term",
                "provider": "automation",
            },
            operation="openmetadata.glossary_term.create",
        )
        _service, _ = self._ensure_named(
            collection="services/databaseServices",
            name=target.service,
            payload={
                "name": target.service,
                "serviceType": target.service_type,
                "description": "GDA local Metadata Fabric projection service",
            },
            operation="openmetadata.database_service.create",
        )
        database, _ = self._ensure_named(
            collection="databases",
            name=f"{target.service}.{target.database}",
            payload={"name": target.database, "service": target.service},
            operation="openmetadata.database.create",
        )
        schema, _ = self._ensure_named(
            collection="databaseSchemas",
            name=f"{target.service}.{target.database}.{target.schema_name}",
            payload={
                "name": target.schema_name,
                "database": database["fullyQualifiedName"],
            },
            operation="openmetadata.database_schema.create",
        )
        projection = next(
            item for item in plan.projections if item.provider == "openmetadata"
        )
        table = self.get_table(target.table_fqn)
        if table is None:
            table = self._request(
                "PUT",
                "tables",
                json_body={
                    "name": target.table,
                    "description": "GDA local M3 land-use projection",
                    "databaseSchema": schema["fullyQualifiedName"],
                    "tableType": "Iceberg",
                    "columns": [
                        {
                            "name": "BSM",
                            "dataType": "STRING",
                            "constraint": "NOT_NULL",
                        },
                        {
                            "name": "geometry",
                            "dataType": "BINARY",
                            "dataLength": 1,
                            "constraint": "NOT_NULL",
                        },
                    ],
                    "owners": [{"id": team["id"], "type": "team"}],
                    "domains": [domain["fullyQualifiedName"]],
                    "tags": [
                        {
                            "tagFQN": (
                                f"{target.classification}.{target.classification_tag}"
                            ),
                            "source": "Classification",
                            "labelType": "Manual",
                            "state": "Confirmed",
                        },
                        {
                            "tagFQN": f"{target.glossary}.{target.glossary_term}",
                            "source": "Glossary",
                            "labelType": "Manual",
                            "state": "Confirmed",
                        },
                    ],
                    "extension": {
                        "gdaResourceUrn": projection.desired_state["resource_urn"],
                        "gdaResourceVersionId": projection.desired_state[
                            "resource_version_id"
                        ],
                        "gdaContentSha256": projection.desired_state["content_sha256"],
                    },
                },
            )
            assert table is not None
            self.mutations.append("openmetadata.table.create")
            self.created_entities.append(("tables", UUID(str(table["id"]))))
        observed = self.get_table(target.table_fqn)
        assert observed is not None
        return observed

    def compensate(self) -> bool:
        errors: list[str] = []
        for collection, entity_id in reversed(self.created_entities):
            try:
                self._request(
                    "DELETE",
                    f"{collection}/{entity_id}",
                    params={"recursive": "true", "hardDelete": "true"},
                    allow_not_found=True,
                )
            except MetadataFabricIngestionReplayError:
                errors.append(f"{collection}:{entity_id}")
        self.created_entities.clear()
        if errors:
            raise MetadataFabricIngestionReplayError(
                "OpenMetadata compensation left created entities"
            )
        return True


class GravitinoApplyClient(_ProviderHttpClient):
    provider_name = "Gravitino"

    def __init__(
        self,
        *,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            headers={"Accept": "application/vnd.gravitino.v1+json"},
            transport=transport,
        )
        self.mutations: list[str] = []
        self.created_metalake: str | None = None
        self.created_resources: list[tuple[str, str]] = []

    def version(self) -> str:
        payload = self._request("GET", "version")
        assert payload is not None
        version = payload.get("version")
        if isinstance(version, dict):
            version = version.get("version")
        if version != "1.3.0":
            raise MetadataFabricIngestionReplayError("Gravitino version drift")
        return str(version)

    @staticmethod
    def _table_path(target: GravitinoTarget) -> str:
        return (
            f"metalakes/{target.metalake}/catalogs/{target.catalog}/schemas/"
            f"{target.schema_name}/tables/{target.table}"
        )

    def get_table(self, target: GravitinoTarget) -> dict[str, Any] | None:
        parent_paths = (
            f"metalakes/{target.metalake}",
            f"metalakes/{target.metalake}/catalogs/{target.catalog}",
            (
                f"metalakes/{target.metalake}/catalogs/{target.catalog}/schemas/"
                f"{target.schema_name}"
            ),
        )
        for path in parent_paths:
            if self._request("GET", path, allow_not_found=True) is None:
                return None
        return self._request(
            "GET",
            self._table_path(target),
            allow_not_found=True,
        )

    def _get_or_create(
        self,
        *,
        get_path: str,
        create_path: str,
        payload: dict[str, Any],
        operation: str,
    ) -> tuple[dict[str, Any], bool]:
        existing = self._request("GET", get_path, allow_not_found=True)
        if existing is not None:
            return existing, False
        created = self._request("POST", create_path, json_body=payload)
        assert created is not None
        self.mutations.append(operation)
        return created, True

    def apply(
        self,
        plan: LocalApplyPlan,
        target: GravitinoTarget,
    ) -> dict[str, Any]:
        _, metalake_created = self._get_or_create(
            get_path=f"metalakes/{target.metalake}",
            create_path="metalakes",
            payload={
                "name": target.metalake,
                "comment": "GDA local M3 Metadata Fabric projection",
                "properties": {"gda.environment": "local_docker_desktop"},
            },
            operation="gravitino.metalake.create",
        )
        if metalake_created:
            self.created_metalake = target.metalake
            self.created_resources.append(("metalake", f"metalakes/{target.metalake}"))
        _, catalog_created = self._get_or_create(
            get_path=f"metalakes/{target.metalake}/catalogs/{target.catalog}",
            create_path=f"metalakes/{target.metalake}/catalogs",
            payload={
                "name": target.catalog,
                "type": target.catalog_type,
                "provider": target.catalog_provider,
                "comment": "GDA local in-memory Iceberg catalog",
                "properties": {
                    "catalog-backend": target.catalog_backend,
                    "uri": target.uri,
                    "warehouse": target.warehouse,
                },
            },
            operation="gravitino.catalog.create",
        )
        if catalog_created:
            self.created_resources.append(
                (
                    "catalog",
                    f"metalakes/{target.metalake}/catalogs/{target.catalog}",
                )
            )
        _, schema_created = self._get_or_create(
            get_path=(
                f"metalakes/{target.metalake}/catalogs/{target.catalog}/schemas/"
                f"{target.schema_name}"
            ),
            create_path=(
                f"metalakes/{target.metalake}/catalogs/{target.catalog}/schemas"
            ),
            payload={
                "name": target.schema_name,
                "comment": "GDA local land-use schema",
                "properties": {},
            },
            operation="gravitino.schema.create",
        )
        if schema_created:
            self.created_resources.append(
                (
                    "schema",
                    (
                        f"metalakes/{target.metalake}/catalogs/{target.catalog}/"
                        f"schemas/{target.schema_name}"
                    ),
                )
            )
        projection = next(
            item for item in plan.projections if item.provider == "gravitino"
        )
        table = self.get_table(target)
        if table is None:
            table = self._request(
                "POST",
                (
                    f"metalakes/{target.metalake}/catalogs/{target.catalog}/"
                    f"schemas/{target.schema_name}/tables"
                ),
                json_body={
                    "name": target.table,
                    "comment": "GDA local M3 land-use projection",
                    "columns": [
                        {
                            "name": "BSM",
                            "type": "string",
                            "nullable": False,
                            "comment": "Parcel code",
                        },
                        {
                            "name": "geometry",
                            "type": "binary",
                            "nullable": False,
                            "comment": "Geometry bytes",
                        },
                    ],
                    "properties": {
                        "gda.resource_urn": projection.desired_state["resource_urn"],
                        "gda.resource_version_id": projection.desired_state[
                            "resource_version_id"
                        ],
                        "gda.content_sha256": projection.desired_state[
                            "content_sha256"
                        ],
                        "gda.provider_revision": projection.desired_state[
                            "provider_revision"
                        ],
                    },
                },
            )
            assert table is not None
            self.mutations.append("gravitino.table.create")
            self.created_resources.append(("table", self._table_path(target)))
        observed = self.get_table(target)
        assert observed is not None
        return observed

    def compensate(self) -> bool:
        if self.created_metalake is not None:
            self._request(
                "DELETE",
                f"metalakes/{self.created_metalake}",
                params={"force": "true"},
                allow_not_found=True,
            )
            self.created_resources.clear()
            self.created_metalake = None
            return True
        errors: list[str] = []
        params_by_kind = {
            "table": {"purge": "true"},
            "schema": {"cascade": "false"},
            "catalog": {"force": "true"},
            "metalake": {"force": "true"},
        }
        for kind, path in reversed(self.created_resources):
            try:
                self._request(
                    "DELETE",
                    path,
                    params=params_by_kind[kind],
                    allow_not_found=True,
                )
            except MetadataFabricIngestionReplayError:
                errors.append(f"{kind}:{path}")
        self.created_resources.clear()
        self.created_metalake = None
        if errors:
            raise MetadataFabricIngestionReplayError(
                "Gravitino compensation left created entities"
            )
        return True


def _binding_candidate_sha256(
    plan: LocalApplyPlan,
    openmetadata: bridge.OpenMetadataObservation,
    gravitino: bridge.GravitinoObservation,
) -> str:
    return bridge.metadata_fabric_binding_fingerprint(
        tenant_id=plan.tenant_id,
        resource_urn=plan.resource_urn,
        resource_version_id=plan.resource_version_id,
        content_sha256=plan.content_sha256,
        openmetadata=openmetadata.ref,
        gravitino=(gravitino.ref,),
    )


def _verify_provider_state(
    plan: LocalApplyPlan,
    profile: LocalIngestionProfile,
    openmetadata_payload: dict[str, Any],
    gravitino_payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> tuple[
    bridge.OpenMetadataObservation,
    bridge.GravitinoObservation,
    str,
]:
    openmetadata_ref = bridge.OpenMetadataTableRef(
        entity_id=UUID(str(openmetadata_payload["id"])),
        fully_qualified_name=profile.targets.openmetadata.table_fqn,
        entity_version=str(openmetadata_payload["version"]),
        server_version=profile.providers.openmetadata.version,
    )
    gravitino_projection = next(
        item for item in plan.projections if item.provider == "gravitino"
    )
    gravitino_ref = bridge.GravitinoTableRef(
        metalake=profile.targets.gravitino.metalake,
        catalog=profile.targets.gravitino.catalog,
        schema_name=profile.targets.gravitino.schema_name,
        table_name=profile.targets.gravitino.table,
        provider_revision=gravitino_projection.desired_state["provider_revision"],
        server_version=profile.providers.gravitino.version,
    )
    governance = bridge.parse_openmetadata_table_observation(
        openmetadata_ref,
        openmetadata_payload,
        observed_at=observed_at,
    )
    technical = bridge.parse_gravitino_table_observation(
        gravitino_ref,
        gravitino_payload,
        observed_at=observed_at,
    )
    expected = (
        plan.resource_urn,
        plan.resource_version_id,
        plan.content_sha256,
    )
    if (
        governance.resource_urn,
        governance.resource_version_id,
        governance.content_sha256,
    ) != expected or (
        technical.resource_urn,
        technical.resource_version_id,
        technical.content_sha256,
    ) != expected:
        raise MetadataFabricIngestionReplayError("live GDA identity drift")
    openmetadata_projection = next(
        item for item in plan.projections if item.provider == "openmetadata"
    )
    desired = openmetadata_projection.desired_state
    if (
        sorted(governance.owner_refs) != desired["owner_refs"]
        or sorted(governance.domain_refs) != desired["domain_refs"]
        or sorted(governance.tag_refs) != desired["tag_refs"]
    ):
        raise MetadataFabricIngestionReplayError(
            "live OpenMetadata governance projection drift"
        )
    if (
        technical.provider_revision
        != gravitino_projection.desired_state["provider_revision"]
    ):
        raise MetadataFabricIngestionReplayError(
            "live Gravitino provider revision drift"
        )
    return (
        governance,
        technical,
        _binding_candidate_sha256(plan, governance, technical),
    )


def apply_once(
    plan: LocalApplyPlan,
    profile: LocalIngestionProfile,
    authorization: ApplyAuthorizationBundle,
    run: PlatformRun,
    *,
    openmetadata: OpenMetadataApplyClient,
    gravitino: GravitinoApplyClient,
    at: datetime,
) -> ApplyOutcome:
    validate_apply_authorization(plan, run, authorization, at=at)
    openmetadata_before = openmetadata.get_table(profile.targets.openmetadata.table_fqn)
    gravitino_before = gravitino.get_table(profile.targets.gravitino)
    if (openmetadata_before is None) != (gravitino_before is None):
        raise MetadataFabricPartialProjectionError(
            "provider target inventory is partially materialized"
        )
    start_om = len(openmetadata.mutations)
    start_grav = len(gravitino.mutations)
    if openmetadata_before is None:
        try:
            openmetadata_payload = openmetadata.apply(
                plan, profile.targets.openmetadata
            )
            gravitino_payload = gravitino.apply(plan, profile.targets.gravitino)
        except Exception:
            compensation_errors = []
            for provider in (gravitino, openmetadata):
                try:
                    provider.compensate()
                except MetadataFabricIngestionReplayError as exc:
                    compensation_errors.append(type(exc).__name__)
            if compensation_errors:
                raise MetadataFabricIngestionReplayError(
                    "provider apply failed and compensation was incomplete"
                )
            raise
    else:
        openmetadata_payload = openmetadata_before
        gravitino_payload = gravitino_before
    governance, technical, binding_sha = _verify_provider_state(
        plan,
        profile,
        openmetadata_payload,
        gravitino_payload,
        observed_at=at,
    )
    mutations = (
        *openmetadata.mutations[start_om:],
        *gravitino.mutations[start_grav:],
    )
    return ApplyOutcome(
        status=ApplyStatus.CREATED if mutations else ApplyStatus.NO_OP,
        mutations=mutations,
        openmetadata=governance,
        gravitino=technical,
        binding_candidate_sha256=binding_sha,
    )


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: LocalIngestionProfile | None = None
    plan: LocalApplyPlan | None = None
    authorization: ApplyAuthorizationBundle | None = None
    try:
        profile, plan, _run, _target, authorization = _build_contract_inputs(
            profile_path
        )
    except (
        AuthorizationEvidenceError,
        MetadataFabricIngestionReplayError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        errors.append(f"local ingestion contract is invalid: {type(exc).__name__}")
    wrapper = wrapper_path.resolve()
    try:
        text = wrapper.read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_ingestion_replay"):
            if marker not in text:
                errors.append(f"local ingestion wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"local ingestion wrapper is invalid: {type(exc).__name__}")
    files: dict[str, dict[str, str]] = {}
    for path in (
        Path(__file__).resolve(),
        Path(ingestion.__file__).resolve(),
        profile_path.resolve(),
        wrapper,
    ):
        if path.is_file():
            relative = path.relative_to(REPO_ROOT).as_posix()
            files[relative] = {
                "path": relative,
                "sha256": recovery._file_sha256(path),
            }
    stable = {
        "schema": CONTRACT_SCHEMA,
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "profile_schema": profile.profile_schema if profile else None,
        "source_plan_sha256": plan.source_plan_sha256 if plan else None,
        "apply_plan_sha256": plan.apply_plan_sha256 if plan else None,
        "authorization_sha256": (
            authorization.authorization_sha256 if authorization else None
        ),
        "local_static_contract_verified": not errors,
        "provider_apply_authorized": False,
        "local_live_provider_ingestion_verified": False,
        "production_ingestion_verified": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": canonical_json_fingerprint(stable)}


def _kubectl_json(args: list[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["kubectl", "--context", CONTEXT, *args],
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MetadataFabricIngestionReplayError("kubectl is unavailable") from exc
    if completed.returncode != 0:
        raise MetadataFabricIngestionReplayError("kubectl observation failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MetadataFabricIngestionReplayError(
            "kubectl observation is invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise MetadataFabricIngestionReplayError("kubectl observation is not an object")
    return payload


def _provider_runtime_identity(profile: LocalIngestionProfile) -> dict[str, Any]:
    namespace = _kubectl_json(["get", "namespace", NAMESPACE, "-o", "json"])
    services = {}
    workloads = {}
    for name, provider in (
        ("openmetadata", profile.providers.openmetadata),
        ("gravitino", profile.providers.gravitino),
    ):
        service = _kubectl_json(
            ["-n", NAMESPACE, "get", "service", provider.service, "-o", "json"]
        )
        workload_kind = "deployment" if name == "openmetadata" else "statefulset"
        workload_name = (
            "openmetadata" if name == "openmetadata" else "metadata-gravitino"
        )
        workload = _kubectl_json(
            [
                "-n",
                NAMESPACE,
                "get",
                workload_kind,
                workload_name,
                "-o",
                "json",
            ]
        )
        services[name] = {
            "name": service["metadata"]["name"],
            "uid": service["metadata"]["uid"],
            "type": service["spec"].get("type", "ClusterIP"),
        }
        workloads[name] = {
            "kind": workload["kind"],
            "name": workload["metadata"]["name"],
            "uid": workload["metadata"]["uid"],
            "ready_replicas": workload.get("status", {}).get("readyReplicas", 0),
        }
    return {
        "context": CONTEXT,
        "namespace": {
            "name": namespace["metadata"]["name"],
            "uid": namespace["metadata"]["uid"],
        },
        "services": services,
        "workloads": workloads,
    }


def _outcome_evidence(outcome: ApplyOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status.value,
        "mutation_count": len(outcome.mutations),
        "mutations": list(outcome.mutations),
        "binding_candidate_sha256": outcome.binding_candidate_sha256,
        "openmetadata": {
            "entity_id": str(outcome.openmetadata.ref.entity_id),
            "fully_qualified_name": outcome.openmetadata.ref.fully_qualified_name,
            "entity_version": outcome.openmetadata.ref.entity_version,
            "resource_urn": outcome.openmetadata.resource_urn,
            "resource_version_id": str(outcome.openmetadata.resource_version_id),
            "content_sha256": outcome.openmetadata.content_sha256,
            "owner_refs": list(outcome.openmetadata.owner_refs),
            "domain_refs": list(outcome.openmetadata.domain_refs),
            "tag_refs": list(outcome.openmetadata.tag_refs),
            "snapshot_sha256": outcome.openmetadata.snapshot_sha256,
        },
        "gravitino": {
            "identity": outcome.gravitino.ref.identity,
            "resource_urn": outcome.gravitino.resource_urn,
            "resource_version_id": str(outcome.gravitino.resource_version_id),
            "content_sha256": outcome.gravitino.content_sha256,
            "provider_revision": outcome.gravitino.provider_revision,
            "snapshot_sha256": outcome.gravitino.snapshot_sha256,
        },
    }


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        _reject_sensitive_fields(observation)
    except ValueError:
        errors.append("observation contains credential-bearing fields")
    first = observation.get("first_apply")
    replay = observation.get("replay")
    runtime = observation.get("runtime_checks")
    if not isinstance(first, Mapping) or not isinstance(replay, Mapping):
        errors.append("apply outcomes are missing")
    else:
        if first.get("status") != "created" or first.get("mutation_count", 0) <= 0:
            errors.append("first apply did not execute bounded provider mutations")
        if replay.get("status") != "no_op" or replay.get("mutation_count") != 0:
            errors.append("second apply was not a zero-mutation replay")
        for key in (
            "binding_candidate_sha256",
            "openmetadata",
            "gravitino",
        ):
            if first.get(key) != replay.get(key):
                errors.append(f"provider read-back drifted across replay: {key}")
    if (
        not isinstance(runtime, Mapping)
        or runtime.get("all_port_forwards_stopped") is not True
    ):
        errors.append("loopback port-forwards were not fully stopped")
    if observation.get("authorization", {}).get("authorized") is not True:
        errors.append("provider mutations lack validated authorization evidence")
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": ("local_live_ingestion_replay_verified" if verified else "blocked"),
        "observation": dict(observation),
        "errors": errors,
        "local_live_provider_ingestion_verified": verified,
        "deterministic_live_replay_verified": verified,
        "provider_mutations_executed": verified,
        "provider_minimum_privilege_verified": False,
        "oidc_verified": False,
        "gravitino_authentication_verified": False,
        "binding_persisted_to_gda_control": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
        "live_openlineage_emission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }
    return {**stable, "evidence_fingerprint": canonical_json_fingerprint(stable)}


def verify_evidence_integrity(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    stable = {
        key: value for key, value in evidence.items() if key != "evidence_fingerprint"
    }
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("local ingestion evidence schema does not match")
    if evidence.get("evidence_fingerprint") != canonical_json_fingerprint(stable):
        errors.append("local ingestion evidence fingerprint does not match")
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
        if evidence.get(claim) is not False:
            errors.append(f"local ingestion evidence may not claim {claim}")
    if evidence.get("local_live_provider_ingestion_verified") is not True:
        errors.append("local provider ingestion is not verified")
    try:
        _reject_sensitive_fields(evidence)
    except ValueError:
        errors.append("local ingestion evidence contains credential-bearing fields")
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile, plan, run, _target, authorization = _build_contract_inputs(profile_path)
    now = datetime.now(UTC)
    validate_apply_authorization(plan, run, authorization, at=now)
    contract = build_contract_report(profile_path)
    if contract["local_static_contract_verified"] is not True:
        raise MetadataFabricIngestionReplayError("static ingestion contract is invalid")
    runtime_identity = _provider_runtime_identity(profile)
    openmetadata_forward = provider_metrics._PortForward(
        kubectl="kubectl",
        context=profile.cluster.context,
        namespace=profile.cluster.namespace,
        service=profile.providers.openmetadata.service,
        target_port=profile.providers.openmetadata.service_port,
    )
    gravitino_forward = provider_metrics._PortForward(
        kubectl="kubectl",
        context=profile.cluster.context,
        namespace=profile.cluster.namespace,
        service=profile.providers.gravitino.service,
        target_port=profile.providers.gravitino.service_port,
    )
    openmetadata_client: OpenMetadataApplyClient | None = None
    gravitino_client: GravitinoApplyClient | None = None
    first: ApplyOutcome | None = None
    replay: ApplyOutcome | None = None
    principal: dict[str, Any] | None = None
    gravitino_version: str | None = None
    stopped = {"openmetadata": False, "gravitino": False}
    try:
        openmetadata_forward.start()
        gravitino_forward.start()
        try:
            username = os.environ[profile.providers.openmetadata.username_env]
            password = SecretStr(
                os.environ[profile.providers.openmetadata.password_env]
            )
        except KeyError as exc:
            raise MetadataFabricIngestionReplayError(
                "OpenMetadata local bootstrap credential environment is missing"
            ) from exc
        openmetadata_client = OpenMetadataApplyClient(
            base_url=(f"http://127.0.0.1:{openmetadata_forward.local_port}/api/v1"),
            username=username,
            password=password,
        )
        gravitino_client = GravitinoApplyClient(
            base_url=f"http://127.0.0.1:{gravitino_forward.local_port}/api"
        )
        principal = openmetadata_client.authenticated_principal()
        gravitino_version = gravitino_client.version()
        first = apply_once(
            plan,
            profile,
            authorization,
            run,
            openmetadata=openmetadata_client,
            gravitino=gravitino_client,
            at=now,
        )
        replay = apply_once(
            plan,
            profile,
            authorization,
            run,
            openmetadata=openmetadata_client,
            gravitino=gravitino_client,
            at=datetime.now(UTC),
        )
    finally:
        if openmetadata_client is not None:
            openmetadata_client.close()
        if gravitino_client is not None:
            gravitino_client.close()
        stopped["openmetadata"] = openmetadata_forward.stop()
        stopped["gravitino"] = gravitino_forward.stop()
    if first is None or replay is None or principal is None:
        raise MetadataFabricIngestionReplayError(
            "local ingestion rehearsal did not produce complete outcomes"
        )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "source_plan_sha256": plan.source_plan_sha256,
            "apply_plan_sha256": plan.apply_plan_sha256,
        },
        "authorization": {
            "authorized": True,
            "authorization_sha256": authorization.authorization_sha256,
            "execution_plan_artifact_id": str(
                authorization.execution_plan_artifact.artifact_id
            ),
            "policy_decision_artifact_id": str(
                authorization.policy_decision_artifact.artifact_id
            ),
            "approval_artifact_id": str(authorization.approval_artifact.artifact_id),
            "executor_subject": (
                f"{run.subject_context.subject_type.value}:"
                f"{run.subject_context.subject_id}"
            ),
            "evaluator_subject": profile.authorization.evaluator_subject,
            "approver_subject": profile.authorization.approver_subject,
        },
        "cluster": runtime_identity,
        "provider_security": {
            "openmetadata": {
                "auth_mode": profile.providers.openmetadata.auth_mode,
                "authenticated_principal": principal,
                "minimum_privilege_verified": False,
            },
            "gravitino": {
                "auth_mode": profile.providers.gravitino.auth_mode,
                "version": gravitino_version,
                "authentication_verified": False,
            },
        },
        "first_apply": _outcome_evidence(first),
        "replay": _outcome_evidence(replay),
        "runtime_checks": {
            "all_port_forwards_stopped": all(stopped.values()),
            "port_forwards": stopped,
            "credentials_recorded": False,
            "provider_objects_retained_for_replay": True,
        },
    }
    return build_evidence(observation)


def build_validation_report(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    contract = build_contract_report(profile_path)
    errors = list(contract["errors"])
    evidence: dict[str, Any] | None = None
    try:
        loaded = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError("evidence must be an object")
        evidence = loaded
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = (
            evidence.get("observation", {})
            .get("contract", {})
            .get("contract_fingerprint")
        )
        if observed_contract != contract["contract_fingerprint"]:
            errors.append("local ingestion evidence contract fingerprint drift")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"local ingestion evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": "gda.metadata_fabric_local_ingestion_validation.v1",
        "m3_2_contract_verified": contract["local_static_contract_verified"],
        "local_live_provider_ingestion_verified": (
            verified
            and evidence is not None
            and evidence.get("local_live_provider_ingestion_verified") is True
        ),
        "deterministic_live_replay_verified": (
            verified
            and evidence is not None
            and evidence.get("deterministic_live_replay_verified") is True
        ),
        "provider_minimum_privilege_verified": False,
        "oidc_verified": False,
        "gravitino_authentication_verified": False,
        "binding_persisted_to_gda_control": False,
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
        "live_openlineage_emission_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "contract_fingerprint": contract["contract_fingerprint"],
        "evidence_fingerprint": (
            evidence.get("evidence_fingerprint") if evidence else None
        ),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = build_validation_report(
                profile_path=args.profile,
                evidence_path=args.evidence,
            )
            print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
            return 0 if not report["errors"] else 1
        evidence = run_live_rehearsal(args.profile)
        args.evidence_out.write_text(
            json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not evidence["errors"] else 1
    except (
        AuthorizationEvidenceError,
        MetadataFabricIngestionReplayError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"metadata fabric local ingestion replay: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
