"""Rehearse bounded OpenMetadata identity and JWT lifecycle locally.

The bootstrap administrator only provisions and removes an ephemeral provider
identity. The identity itself must create and read one table, be denied policy
creation, survive JWT rotation, and fail after revocation. Gravitino 1.3.0
remains explicitly outside the verified identity boundary because the sandbox
has its simple authenticator with access control disabled.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from . import metadata_fabric_ingestion_replay as ingestion_replay
from . import metadata_fabric_provider_metrics as provider_metrics
from . import metadata_fabric_recovery_rehearsal as recovery
from . import metadata_fabric_sandbox as sandbox


PROFILE_SCHEMA = "gda.metadata_fabric_provider_identity_profile.v1"
CONTRACT_SCHEMA = "gda.metadata_fabric_provider_identity_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_provider_identity_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_provider_identity_evidence.v1"
VALIDATION_SCHEMA = "gda.metadata_fabric_provider_identity_validation.v1"
CONTEXT = "docker-desktop"
NAMESPACE = sandbox.NAMESPACE

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-provider-identity.local.yaml"
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-provider-identity-2026-07-28.json"
)
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-provider-identity.sh"
OPENMETADATA_VALUES_PATH = (
    REPO_ROOT / "helm/metadata-fabric-sandbox/openmetadata-values.yaml"
)
GRAVITINO_MANIFEST_PATH = REPO_ROOT / "k8s/metadata-fabric-sandbox/gravitino.yaml"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]


class MetadataFabricProviderIdentityError(RuntimeError):
    """The bounded provider identity contract or rehearsal failed closed."""


class ProviderRequestError(MetadataFabricProviderIdentityError):
    """An allowlisted OpenMetadata request failed without exposing its body."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClusterProfile(_FrozenModel):
    context: Literal["docker-desktop"]
    namespace: Literal["gda-metadata-sandbox"]


class OpenMetadataProfile(_FrozenModel):
    version: Literal["1.13.1"]
    workload: Literal["deployment/openmetadata"]
    service: Literal["openmetadata"]
    service_port: Literal[8585]
    service_account: Literal["openmetadata"]
    auth_mode: Literal["local_basic_bootstrap_provisioner"]
    bootstrap_username_env: Literal["GDA_OPENMETADATA_USERNAME"]
    bootstrap_password_env: Literal["GDA_OPENMETADATA_PASSWORD"]


class GravitinoProfile(_FrozenModel):
    version: Literal["1.3.0"]
    workload: Literal["statefulset/metadata-gravitino"]
    service: Literal["metadata-gravitino"]
    service_port: Literal[8090]
    authenticator: Literal["simple"]
    access_control_enabled: Literal[False]


class ProviderProfiles(_FrozenModel):
    openmetadata: OpenMetadataProfile
    gravitino: GravitinoProfile


class AllowedRule(_FrozenModel):
    name: Literal["GdaMetadataTableCreate"]
    effect: Literal["allow"]
    operations: tuple[Literal["Create"], ...]
    resources: tuple[Literal["table"], ...]


class IdentityProfile(_FrozenModel):
    policy: Literal["GdaMetadataTableProjectionPolicy"]
    role: Literal["GdaMetadataTableProjectionRole"]
    user: Literal["gda-metadata-table-projection"]
    email: Literal["gda-metadata-table-projection@open-metadata.org"]
    bot: Literal["gda-metadata-table-projection-bot"]
    mandatory_default_role: Literal["DefaultBotRole"]
    jwt_expiry: Literal["OneHour"]
    allowed_rule: AllowedRule


class AllowedTableCreateProbe(_FrozenModel):
    database_schema: Literal["gda_lakehouse.land_use.published"]
    table: Literal["gda_provider_identity_probe"]

    @property
    def fully_qualified_name(self) -> str:
        return f"{self.database_schema}.{self.table}"


class DeniedPolicyCreateProbe(_FrozenModel):
    collection: Literal["policies"]
    operation: Literal["Create"]
    name: Literal["GdaUnauthorizedPolicyProbe"]


class ProbeProfile(_FrozenModel):
    allowed_table_create: AllowedTableCreateProbe
    denied_policy_create: DeniedPolicyCreateProbe


class ClaimProfile(_FrozenModel):
    local_openmetadata_bounded_identity_verified: Literal[False]
    local_openmetadata_minimum_privilege_verified: Literal[False]
    local_openmetadata_jwt_rotation_verified: Literal[False]
    local_openmetadata_jwt_revocation_verified: Literal[False]
    provider_minimum_privilege_verified: Literal[False]
    protected_workload_identity_verified: Literal[False]
    oidc_verified: Literal[False]
    gravitino_authentication_verified: Literal[False]
    production_identity_verified: Literal[False]
    production_ready: Literal[False]


class ProviderIdentityProfile(_FrozenModel):
    schema_name: Literal["gda.metadata_fabric_provider_identity_profile.v1"] = Field(
        alias="schema"
    )
    environment: Literal["local_docker_desktop"]
    cluster: ClusterProfile
    providers: ProviderProfiles
    identity: IdentityProfile
    probes: ProbeProfile
    claims: ClaimProfile


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _load_yaml_object(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("provider identity profile must be an object")
    return value


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> ProviderIdentityProfile:
    try:
        value = _load_yaml_object(path.resolve())
        ingestion_replay._reject_sensitive_fields(value)
        profile = ProviderIdentityProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise MetadataFabricProviderIdentityError(
            "provider identity profile is invalid"
        ) from exc
    if (
        profile.identity.allowed_rule.operations != ("Create",)
        or profile.identity.allowed_rule.resources != ("table",)
    ):
        raise MetadataFabricProviderIdentityError(
            "provider identity policy must allow only table Create"
        )
    return profile


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: ProviderIdentityProfile | None = None
    try:
        profile = load_profile(profile_path)
    except MetadataFabricProviderIdentityError as exc:
        errors.append(str(exc))

    try:
        wrapper = wrapper_path.resolve().read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_provider_identity"):
            if marker not in wrapper:
                errors.append(f"provider identity wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"provider identity wrapper is invalid: {type(exc).__name__}")

    static_markers = (
        (
            OPENMETADATA_VALUES_PATH,
            (
                "provider: basic",
                'initialAdmins: ["admin"]',
                "automountServiceAccountToken: false",
            ),
        ),
        (
            GRAVITINO_MANIFEST_PATH,
            (
                "gravitino.authenticators = simple",
                "gravitino.authorization.enable = false",
            ),
        ),
    )
    for path, markers in static_markers:
        try:
            content = path.read_text(encoding="utf-8")
            for marker in markers:
                if marker not in content:
                    errors.append(f"provider identity source is missing marker: {marker}")
        except OSError as exc:
            errors.append(f"provider identity source is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    for path in (
        Path(__file__).resolve(),
        profile_path.resolve(),
        wrapper_path.resolve(),
        OPENMETADATA_VALUES_PATH,
        GRAVITINO_MANIFEST_PATH,
    ):
        if path.is_file():
            try:
                relative = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                relative = path.name
            files[relative] = {
                "path": relative,
                "sha256": recovery._file_sha256(path),
            }

    identity = profile.identity if profile else None
    stable = {
        "schema": CONTRACT_SCHEMA,
        "context": CONTEXT,
        "namespace": NAMESPACE,
        "openmetadata_version": sandbox.OPENMETADATA_VERSION,
        "gravitino_version": sandbox.GRAVITINO_VERSION,
        "identity": (
            {
                "policy": identity.policy,
                "role": identity.role,
                "user": identity.user,
                "bot": identity.bot,
                "mandatory_default_role": identity.mandatory_default_role,
                "allowed_rule": identity.allowed_rule.model_dump(mode="json"),
            }
            if identity
            else None
        ),
        "local_static_contract_verified": not errors,
        "local_openmetadata_bounded_identity_verified": False,
        "local_openmetadata_minimum_privilege_verified": False,
        "provider_minimum_privilege_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "gravitino_authentication_verified": False,
        "production_identity_verified": False,
        "production_ready": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


def _json_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise ProviderRequestError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderRequestError(f"{label} response is not an object")
    return value


class _HttpApi:
    def __init__(
        self,
        *,
        base_url: str,
        bearer: SecretStr,
        transport: httpx.BaseTransport | None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {bearer.get_secret_value()}",
            },
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        expected: frozenset[int] = frozenset({200}),
        label: str,
    ) -> tuple[int, dict[str, Any] | None]:
        try:
            response = self._client.request(
                method,
                path,
                json=dict(json_body) if json_body is not None else None,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise ProviderRequestError(f"{label} request failed") from exc
        if response.status_code not in expected:
            raise ProviderRequestError(
                f"{label} returned unexpected status {response.status_code}"
            )
        if response.status_code in {401, 403, 404} or not response.content:
            return response.status_code, None
        return response.status_code, _json_object(response, label)


class OpenMetadataIdentityRehearsal:
    """Provision, exercise, revoke, and remove one local provider identity."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: SecretStr,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        login = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=30.0,
            transport=transport,
        )
        encoded_password = base64.b64encode(
            password.get_secret_value().encode("utf-8")
        ).decode("ascii")
        try:
            response = login.post(
                "users/login",
                json={"email": username, "password": encoded_password},
            )
        except httpx.HTTPError as exc:
            login.close()
            raise ProviderRequestError("OpenMetadata bootstrap login failed") from exc
        login.close()
        if response.status_code != 200:
            raise ProviderRequestError("OpenMetadata bootstrap login was rejected")
        payload = _json_object(response, "OpenMetadata bootstrap login")
        access = payload.get("accessToken")
        if not isinstance(access, str) or not access:
            raise ProviderRequestError("OpenMetadata bootstrap login omitted access")
        self._base_url = base_url
        self._transport = transport
        self._admin = _HttpApi(
            base_url=base_url,
            bearer=SecretStr(access),
            transport=transport,
        )
        self._created: dict[str, tuple[str, UUID]] = {}
        self._bot_clients: list[_HttpApi] = []

    def close(self) -> None:
        for client in self._bot_clients:
            client.close()
        self._bot_clients.clear()
        self._admin.close()

    @staticmethod
    def _entity_id(payload: Mapping[str, Any], label: str) -> UUID:
        try:
            return UUID(str(payload["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderRequestError(f"{label} omitted provider identity") from exc

    @staticmethod
    def _name_path(collection: str, name: str) -> str:
        return f"{collection}/name/{quote(name, safe='')}"

    def _lookup(
        self, collection: str, name: str, *, fields: str | None = None
    ) -> tuple[int, dict[str, Any] | None]:
        params = {"fields": fields} if fields else None
        return self._admin.request(
            "GET",
            self._name_path(collection, name),
            params=params,
            expected=frozenset({200, 404}),
            label=f"OpenMetadata {collection} lookup",
        )

    def _preflight(self, profile: ProviderIdentityProfile) -> None:
        checks = (
            ("policies", profile.identity.policy),
            ("roles", profile.identity.role),
            ("users", profile.identity.user),
            ("bots", profile.identity.bot),
            ("tables", profile.probes.allowed_table_create.fully_qualified_name),
            ("policies", profile.probes.denied_policy_create.name),
        )
        for collection, name in checks:
            status, _payload = self._lookup(collection, name)
            if status != 404:
                raise MetadataFabricProviderIdentityError(
                    f"OpenMetadata rehearsal target already exists: {collection}/{name}"
                )

    def _create(
        self,
        *,
        key: str,
        collection: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        _status, created = self._admin.request(
            "PUT",
            collection,
            json_body=payload,
            expected=frozenset({200, 201}),
            label=f"OpenMetadata {collection} create",
        )
        assert created is not None
        self._created[key] = (
            collection,
            self._entity_id(created, f"OpenMetadata {collection}"),
        )
        return created

    def _bot_api(self, value: str) -> _HttpApi:
        client = _HttpApi(
            base_url=self._base_url,
            bearer=SecretStr(value),
            transport=self._transport,
        )
        self._bot_clients.append(client)
        return client

    def _current_jwt(self, user_id: UUID) -> str:
        _status, mechanism = self._admin.request(
            "GET",
            f"users/auth-mechanism/{user_id}",
            label="OpenMetadata bot authentication mechanism",
        )
        config = _mapping(_mapping(mechanism).get("config"))
        value = config.get("JWTToken")
        if not isinstance(value, str) or not value:
            raise ProviderRequestError("OpenMetadata bot authentication omitted JWT")
        return value

    def _cleanup(self, profile: ProviderIdentityProfile) -> dict[str, Any]:
        revoke_attempted = False
        user = self._created.get("user")
        if user is not None:
            revoke_attempted = True
            try:
                self._admin.request(
                    "PUT",
                    "users/revokeToken",
                    json_body={"id": str(user[1])},
                    expected=frozenset({200, 400, 404}),
                    label="OpenMetadata bot JWT cleanup revocation",
                )
            except ProviderRequestError:
                pass

        delete_order = ("table", "unauthorized_policy", "bot", "user", "role", "policy")
        delete_statuses: dict[str, int] = {}
        for key in delete_order:
            created = self._created.get(key)
            if created is None:
                continue
            collection, entity_id = created
            try:
                status, _payload = self._admin.request(
                    "DELETE",
                    f"{collection}/{entity_id}",
                    params={"recursive": "true", "hardDelete": "true"},
                    expected=frozenset({200, 204, 404}),
                    label=f"OpenMetadata {key} cleanup",
                )
                delete_statuses[key] = status
            except ProviderRequestError:
                delete_statuses[key] = 0

        absence_checks = (
            ("table", "tables", profile.probes.allowed_table_create.fully_qualified_name),
            ("bot", "bots", profile.identity.bot),
            ("user", "users", profile.identity.user),
            ("role", "roles", profile.identity.role),
            ("policy", "policies", profile.identity.policy),
            (
                "unauthorized_policy",
                "policies",
                profile.probes.denied_policy_create.name,
            ),
        )
        absent: dict[str, bool] = {}
        for key, collection, name in absence_checks:
            try:
                status, _payload = self._lookup(collection, name)
                absent[key] = status == 404
            except ProviderRequestError:
                absent[key] = False
        return {
            "jwt_revocation_attempted": revoke_attempted,
            "delete_statuses": delete_statuses,
            "all_rehearsal_objects_absent": all(absent.values()),
            "absence": absent,
        }

    def execute(self, profile: ProviderIdentityProfile) -> dict[str, Any]:
        self._preflight(profile)
        outcome: dict[str, Any] | None = None
        try:
            rule = profile.identity.allowed_rule
            policy = self._create(
                key="policy",
                collection="policies",
                payload={
                    "name": profile.identity.policy,
                    "description": "Bounded local GDA table projection rehearsal",
                    "enabled": True,
                    "rules": [rule.model_dump(mode="json")],
                },
            )
            policy_id = self._entity_id(policy, "OpenMetadata policy")
            role = self._create(
                key="role",
                collection="roles",
                payload={
                    "name": profile.identity.role,
                    "description": "Bounded local GDA table projection role",
                    "policies": [profile.identity.policy],
                },
            )
            role_id = self._entity_id(role, "OpenMetadata role")
            user = self._create(
                key="user",
                collection="users",
                payload={
                    "name": profile.identity.user,
                    "email": profile.identity.email,
                    "description": "Bounded local GDA metadata table projection identity",
                    "isBot": True,
                    "isAdmin": False,
                    "roles": [str(role_id)],
                    "authenticationMechanism": {
                        "authType": "JWT",
                        "config": {"JWTTokenExpiry": profile.identity.jwt_expiry},
                    },
                },
            )
            user_id = self._entity_id(user, "OpenMetadata user")
            bot = self._create(
                key="bot",
                collection="bots",
                payload={
                    "name": profile.identity.bot,
                    "description": "Bounded local GDA metadata table projection bot",
                    "botUser": profile.identity.user,
                    "provider": "automation",
                },
            )
            bot_id = self._entity_id(bot, "OpenMetadata bot")

            initial_jwt = self._current_jwt(user_id)
            initial_api = self._bot_api(initial_jwt)
            principal_status, principal = initial_api.request(
                "GET",
                "users/loggedInUser",
                params={"fields": "roles"},
                label="OpenMetadata bot principal",
            )
            assert principal is not None
            role_names = sorted(
                str(item.get("name"))
                for item in principal.get("roles", [])
                if isinstance(item, Mapping)
            )

            table_probe = profile.probes.allowed_table_create
            table_status, table = initial_api.request(
                "PUT",
                "tables",
                json_body={
                    "name": table_probe.table,
                    "description": "Ephemeral local minimum privilege probe",
                    "databaseSchema": table_probe.database_schema,
                    "tableType": "Regular",
                    "columns": [
                        {
                            "name": "probe_id",
                            "dataType": "STRING",
                            "constraint": "NOT_NULL",
                        }
                    ],
                },
                expected=frozenset({200, 201}),
                label="OpenMetadata allowed table create probe",
            )
            assert table is not None
            table_id = self._entity_id(table, "OpenMetadata probe table")
            self._created["table"] = ("tables", table_id)
            read_status, readback = initial_api.request(
                "GET",
                self._name_path("tables", table_probe.fully_qualified_name),
                label="OpenMetadata allowed table readback probe",
            )
            assert readback is not None

            denied = profile.probes.denied_policy_create
            denied_status, denied_payload = initial_api.request(
                "PUT",
                denied.collection,
                json_body={
                    "name": denied.name,
                    "enabled": True,
                    "rules": [
                        {
                            "name": "MustNotCreate",
                            "effect": "allow",
                            "operations": ["All"],
                            "resources": ["All"],
                        }
                    ],
                },
                expected=frozenset({200, 201, 403}),
                label="OpenMetadata denied policy create probe",
            )
            if denied_status in {200, 201} and denied_payload is not None:
                self._created["unauthorized_policy"] = (
                    "policies",
                    self._entity_id(
                        denied_payload, "OpenMetadata unauthorized policy probe"
                    ),
                )

            _rotation_status, rotated = self._admin.request(
                "PUT",
                f"users/generateToken/{user_id}",
                json_body={"JWTTokenExpiry": profile.identity.jwt_expiry},
                label="OpenMetadata bot JWT rotation",
            )
            rotated_jwt = _mapping(rotated).get("JWTToken")
            if not isinstance(rotated_jwt, str) or not rotated_jwt:
                raise ProviderRequestError("OpenMetadata rotation omitted JWT")
            old_after_rotation, _payload = initial_api.request(
                "GET",
                "users/loggedInUser",
                expected=frozenset({200, 401, 403}),
                label="OpenMetadata old JWT after rotation",
            )
            rotated_api = self._bot_api(rotated_jwt)
            new_after_rotation, rotated_principal = rotated_api.request(
                "GET",
                "users/loggedInUser",
                params={"fields": "roles"},
                expected=frozenset({200, 401, 403}),
                label="OpenMetadata rotated JWT",
            )
            _revoke_status, _revoked = self._admin.request(
                "PUT",
                "users/revokeToken",
                json_body={"id": str(user_id)},
                label="OpenMetadata bot JWT revocation",
            )
            new_after_revocation, _payload = rotated_api.request(
                "GET",
                "users/loggedInUser",
                expected=frozenset({200, 401, 403}),
                label="OpenMetadata revoked JWT",
            )

            outcome = {
                "provisioner": {
                    "auth_mode": profile.providers.openmetadata.auth_mode,
                    "bootstrap_admin_used": True,
                    "minimum_privilege": False,
                },
                "principal": {
                    "id": str(user_id),
                    "name": principal.get("name"),
                    "is_admin": principal.get("isAdmin"),
                    "is_bot": principal.get("isBot"),
                    "effective_roles": role_names,
                    "provider_mandatory_default_role_inherited": True,
                    "minimum_privilege_scope": (
                        "dedicated_table_create_grant_with_provider_mandatory_default_role"
                    ),
                },
                "policy": {
                    "id": str(policy_id),
                    "name": policy.get("name"),
                    "enabled": policy.get("enabled"),
                    "rules": policy.get("rules"),
                },
                "role": {
                    "id": str(role_id),
                    "name": role.get("name"),
                    "policy_ids": [str(policy_id)],
                    "mandatory_default_role": profile.identity.mandatory_default_role,
                },
                "bot": {
                    "id": str(bot_id),
                    "name": bot.get("name"),
                    "provider": bot.get("provider"),
                },
                "allowed_probe": {
                    "operation": "Create",
                    "resource": "table",
                    "create_status": table_status,
                    "read_status": read_status,
                    "entity_id": str(table_id),
                    "fully_qualified_name": readback.get("fullyQualifiedName"),
                },
                "denied_probe": {
                    "operation": denied.operation,
                    "resource": "policy",
                    "status": denied_status,
                },
                "jwt_lifecycle": {
                    "expiry": profile.identity.jwt_expiry,
                    "initial_authentication_status": principal_status,
                    "old_after_rotation_status": old_after_rotation,
                    "rotated_authentication_status": new_after_rotation,
                    "rotated_principal_matches": (
                        _mapping(rotated_principal).get("id") == str(user_id)
                    ),
                    "after_revocation_status": new_after_revocation,
                    "sensitive_material_recorded": False,
                },
            }
        except BaseException:
            self._cleanup(profile)
            raise

        assert outcome is not None
        outcome["cleanup"] = self._cleanup(profile)
        return outcome


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
        raise MetadataFabricProviderIdentityError("kubectl is unavailable") from exc
    if completed.returncode != 0:
        raise MetadataFabricProviderIdentityError("kubectl identity observation failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MetadataFabricProviderIdentityError(
            "kubectl identity observation is invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise MetadataFabricProviderIdentityError(
            "kubectl identity observation is not an object"
        )
    return value


def _runtime_identity(profile: ProviderIdentityProfile) -> dict[str, Any]:
    namespace = _kubectl_json(["get", "namespace", NAMESPACE, "-o", "json"])
    service = _kubectl_json(
        ["-n", NAMESPACE, "get", "service", "openmetadata", "-o", "json"]
    )
    deployment = _kubectl_json(
        ["-n", NAMESPACE, "get", "deployment", "openmetadata", "-o", "json"]
    )
    pod_spec = _mapping(
        _mapping(_mapping(deployment.get("spec")).get("template")).get("spec")
    )
    containers = (
        pod_spec.get("containers")
        if isinstance(pod_spec.get("containers"), list)
        else []
    )
    container = next(
        (
            _mapping(item)
            for item in containers
            if _mapping(item).get("name") == "openmetadata"
        ),
        {},
    )
    return {
        "context": profile.cluster.context,
        "namespace": {
            "name": _mapping(namespace.get("metadata")).get("name"),
            "uid": _mapping(namespace.get("metadata")).get("uid"),
        },
        "service": {
            "name": _mapping(service.get("metadata")).get("name"),
            "uid": _mapping(service.get("metadata")).get("uid"),
            "type": _mapping(service.get("spec")).get("type"),
        },
        "workload": {
            "kind": deployment.get("kind"),
            "name": _mapping(deployment.get("metadata")).get("name"),
            "uid": _mapping(deployment.get("metadata")).get("uid"),
            "image": container.get("image"),
            "service_account": pod_spec.get("serviceAccountName"),
            "service_account_automount_disabled": (
                pod_spec.get("automountServiceAccountToken") is False
            ),
            "ready_replicas": _mapping(deployment.get("status")).get(
                "readyReplicas", 0
            ),
        },
    }


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        ingestion_replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("provider identity observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("provider identity observation schema does not match")

    contract = _mapping(observation.get("contract"))
    if (
        contract.get("local_static_contract_verified") is not True
        or not _valid_sha256(contract.get("contract_fingerprint"))
    ):
        errors.append("provider identity static contract is not bound")

    runtime = _mapping(observation.get("runtime"))
    workload = _mapping(runtime.get("workload"))
    if (
        runtime.get("context") != CONTEXT
        or _mapping(runtime.get("namespace")).get("name") != NAMESPACE
        or _mapping(runtime.get("service")).get("name") != "openmetadata"
        or _mapping(runtime.get("service")).get("type") != "ClusterIP"
        or workload.get("kind") != "Deployment"
        or workload.get("name") != "openmetadata"
        or workload.get("image")
        != "docker.getcollate.io/openmetadata/server:1.13.1"
        or workload.get("service_account") != "openmetadata"
        or workload.get("service_account_automount_disabled") is not True
        or workload.get("ready_replicas") != 1
    ):
        errors.append("OpenMetadata runtime identity does not match the sandbox")

    provider = _mapping(observation.get("openmetadata"))
    provisioner = _mapping(provider.get("provisioner"))
    if (
        provisioner.get("auth_mode") != "local_basic_bootstrap_provisioner"
        or provisioner.get("bootstrap_admin_used") is not True
        or provisioner.get("minimum_privilege") is not False
    ):
        errors.append("OpenMetadata bootstrap provisioner boundary is missing")

    principal = _mapping(provider.get("principal"))
    expected_roles = ["DefaultBotRole", "GdaMetadataTableProjectionRole"]
    if (
        not _valid_uuid(principal.get("id"))
        or
        principal.get("name") != "gda-metadata-table-projection"
        or principal.get("is_admin") is not False
        or principal.get("is_bot") is not True
        or principal.get("effective_roles") != expected_roles
        or principal.get("provider_mandatory_default_role_inherited") is not True
        or principal.get("minimum_privilege_scope")
        != "dedicated_table_create_grant_with_provider_mandatory_default_role"
    ):
        errors.append("OpenMetadata principal or effective roles do not match")

    policy = _mapping(provider.get("policy"))
    expected_rule = {
        "name": "GdaMetadataTableCreate",
        "effect": "allow",
        "operations": ["Create"],
        "resources": ["table"],
    }
    observed_rules = policy.get("rules")
    normalized_rules = []
    if isinstance(observed_rules, list):
        for item in observed_rules:
            rule = _mapping(item)
            normalized_rules.append(
                {
                    "name": rule.get("name"),
                    "effect": rule.get("effect"),
                    "operations": rule.get("operations"),
                    "resources": rule.get("resources"),
                }
            )
    if (
        not _valid_uuid(policy.get("id"))
        or policy.get("name") != "GdaMetadataTableProjectionPolicy"
        or policy.get("enabled") is not True
        or normalized_rules != [expected_rule]
    ):
        errors.append("OpenMetadata dedicated policy is broader than table Create")

    role = _mapping(provider.get("role"))
    if (
        not _valid_uuid(role.get("id"))
        or role.get("name") != "GdaMetadataTableProjectionRole"
        or role.get("policy_ids") != [policy.get("id")]
        or role.get("mandatory_default_role") != "DefaultBotRole"
    ):
        errors.append("OpenMetadata role does not bind only the dedicated policy")

    bot = _mapping(provider.get("bot"))
    if (
        not _valid_uuid(bot.get("id"))
        or bot.get("name") != "gda-metadata-table-projection-bot"
        or bot.get("provider") != "automation"
    ):
        errors.append("OpenMetadata bot identity does not match")

    allowed = _mapping(provider.get("allowed_probe"))
    if (
        allowed.get("operation") != "Create"
        or allowed.get("resource") != "table"
        or not _valid_uuid(allowed.get("entity_id"))
        or allowed.get("create_status") not in {200, 201}
        or allowed.get("read_status") != 200
        or allowed.get("fully_qualified_name")
        != "gda_lakehouse.land_use.published.gda_provider_identity_probe"
    ):
        errors.append("OpenMetadata allowed table probe did not pass")

    denied = _mapping(provider.get("denied_probe"))
    if (
        denied.get("operation") != "Create"
        or denied.get("resource") != "policy"
        or denied.get("status") != 403
    ):
        errors.append("OpenMetadata policy-create denial was not enforced")

    lifecycle = _mapping(provider.get("jwt_lifecycle"))
    if (
        lifecycle.get("expiry") != "OneHour"
        or lifecycle.get("initial_authentication_status") != 200
        or lifecycle.get("old_after_rotation_status") != 401
        or lifecycle.get("rotated_authentication_status") != 200
        or lifecycle.get("rotated_principal_matches") is not True
        or lifecycle.get("after_revocation_status") != 401
        or lifecycle.get("sensitive_material_recorded") is not False
    ):
        errors.append("OpenMetadata JWT rotation or revocation did not pass")

    cleanup = _mapping(provider.get("cleanup"))
    runtime_checks = _mapping(observation.get("runtime_checks"))
    absence = _mapping(cleanup.get("absence"))
    delete_statuses = _mapping(cleanup.get("delete_statuses"))
    if (
        cleanup.get("all_rehearsal_objects_absent") is not True
        or absence
        != {
            "table": True,
            "bot": True,
            "user": True,
            "role": True,
            "policy": True,
            "unauthorized_policy": True,
        }
        or set(delete_statuses) != {"table", "bot", "user", "role", "policy"}
        or any(status not in {200, 204, 404} for status in delete_statuses.values())
        or runtime_checks.get("all_port_forwards_stopped") is not True
        or runtime_checks.get("provider_objects_retained") is not False
        or runtime_checks.get("sensitive_material_recorded") is not False
        or runtime_checks.get("kubernetes_service_account_used_for_provider_login")
        is not False
    ):
        errors.append("provider identity rehearsal cleanup is incomplete")

    gravitino = _mapping(observation.get("gravitino"))
    if gravitino != {
        "version": "1.3.0",
        "authenticator": "simple",
        "access_control_enabled": False,
        "authentication_verified": False,
    }:
        errors.append("Gravitino blocked identity boundary does not match")

    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": (
            "local_openmetadata_bounded_identity_verified" if verified else "blocked"
        ),
        "observation": dict(observation),
        "errors": errors,
        "local_openmetadata_bounded_identity_verified": verified,
        "local_openmetadata_minimum_privilege_verified": verified,
        "local_openmetadata_jwt_rotation_verified": verified,
        "local_openmetadata_jwt_revocation_verified": verified,
        "provider_minimum_privilege_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "gravitino_authentication_verified": False,
        "production_identity_verified": False,
        "production_ready": False,
    }
    return {**stable, "evidence_fingerprint": recovery._canonical_sha256(stable)}


def verify_evidence_integrity(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("provider identity evidence schema does not match")
    expected = build_evidence(_mapping(evidence.get("observation")))
    if dict(evidence) != expected:
        errors.append("provider identity evidence content or fingerprint drifted")
    for claim in (
        "provider_minimum_privilege_verified",
        "protected_workload_identity_verified",
        "oidc_verified",
        "gravitino_authentication_verified",
        "production_identity_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"provider identity evidence may not claim {claim}")
    if evidence.get("local_openmetadata_bounded_identity_verified") is not True:
        errors.append("local OpenMetadata bounded identity is not verified")
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    contract = build_contract_report(profile_path)
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricProviderIdentityError(
            "provider identity static contract is invalid"
        )
    runtime = _runtime_identity(profile)
    forward = provider_metrics._PortForward(
        kubectl="kubectl",
        context=profile.cluster.context,
        namespace=profile.cluster.namespace,
        service=profile.providers.openmetadata.service,
        target_port=profile.providers.openmetadata.service_port,
    )
    rehearsal: OpenMetadataIdentityRehearsal | None = None
    result: dict[str, Any] | None = None
    stopped = False
    try:
        forward.start()
        try:
            username = os.environ[
                profile.providers.openmetadata.bootstrap_username_env
            ]
            password = SecretStr(
                os.environ[profile.providers.openmetadata.bootstrap_password_env]
            )
        except KeyError as exc:
            raise MetadataFabricProviderIdentityError(
                "OpenMetadata local bootstrap environment is missing"
            ) from exc
        rehearsal = OpenMetadataIdentityRehearsal(
            base_url=f"http://127.0.0.1:{forward.local_port}/api/v1",
            username=username,
            password=password,
        )
        result = rehearsal.execute(profile)
    finally:
        if rehearsal is not None:
            rehearsal.close()
        stopped = forward.stop()
    if result is None:
        raise MetadataFabricProviderIdentityError(
            "provider identity rehearsal did not produce an outcome"
        )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "local_static_contract_verified": True,
        },
        "runtime": runtime,
        "openmetadata": result,
        "gravitino": {
            "version": profile.providers.gravitino.version,
            "authenticator": profile.providers.gravitino.authenticator,
            "access_control_enabled": (
                profile.providers.gravitino.access_control_enabled
            ),
            "authentication_verified": False,
        },
        "runtime_checks": {
            "all_port_forwards_stopped": stopped,
            "provider_objects_retained": False,
            "sensitive_material_recorded": False,
            "kubernetes_service_account_used_for_provider_login": False,
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
        value = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("provider identity evidence must be an object")
        evidence = value
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = _mapping(
            _mapping(evidence.get("observation")).get("contract")
        ).get("contract_fingerprint")
        if observed_contract != contract.get("contract_fingerprint"):
            errors.append("provider identity evidence contract fingerprint drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"provider identity evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "local_static_contract_verified": contract[
            "local_static_contract_verified"
        ],
        "local_openmetadata_bounded_identity_verified": (
            verified
            and evidence is not None
            and evidence.get("local_openmetadata_bounded_identity_verified") is True
        ),
        "local_openmetadata_minimum_privilege_verified": (
            verified
            and evidence is not None
            and evidence.get("local_openmetadata_minimum_privilege_verified") is True
        ),
        "provider_minimum_privilege_verified": False,
        "protected_workload_identity_verified": False,
        "gravitino_authentication_verified": False,
        "production_identity_verified": False,
        "production_ready": False,
        "contract_fingerprint": contract["contract_fingerprint"],
        "evidence_fingerprint": (
            evidence.get("evidence_fingerprint") if evidence else None
        ),
        "errors": errors,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            report = build_validation_report(
                profile_path=args.profile,
                evidence_path=args.evidence,
            )
            print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
            return 0 if not report["errors"] else 1
        if args.command == "verify":
            value = json.loads(args.evidence.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError("provider identity evidence must be an object")
            errors = verify_evidence_integrity(value)
            print(json.dumps({"verified": not errors, "errors": errors}, indent=2))
            return 0 if not errors else 1
        evidence = run_live_rehearsal(args.profile)
        _write_json(args.evidence_out, evidence)
        print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not evidence["errors"] else 1
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        MetadataFabricProviderIdentityError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata fabric provider identity: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
