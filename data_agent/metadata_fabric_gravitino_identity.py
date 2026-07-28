"""Rehearse authenticated, bounded Gravitino access in an isolated namespace.

The rehearsal starts a temporary Gravitino 1.3.0 server backed by PostgreSQL,
enables the built-in Basic IdP and deny-by-default authorization, and grants one
named user only the privileges needed to create a table in one schema. It then
proves an allowed table mutation, a denied catalog mutation, login rotation,
revocation, and complete namespace cleanup. This remains local POC evidence,
not protected OIDC or production identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
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


PROFILE_SCHEMA = "gda.metadata_fabric_gravitino_identity_profile.v1"
CONTRACT_SCHEMA = "gda.metadata_fabric_gravitino_identity_contract.v1"
OBSERVATION_SCHEMA = "gda.metadata_fabric_gravitino_identity_observation.v1"
EVIDENCE_SCHEMA = "gda.metadata_fabric_gravitino_identity_evidence.v1"
VALIDATION_SCHEMA = "gda.metadata_fabric_gravitino_identity_validation.v1"

CONTEXT = "docker-desktop"
SOURCE_NAMESPACE = "gda-metadata-sandbox"
REHEARSAL_NAMESPACE = "gda-metadata-identity"
GRAVITINO_SCHEMA_SHA256 = (
    "7a2d605a677a462ca619dba594ce7ebcf500358345560ad084c1b67a25c722df"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-gravitino-identity.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-gravitino-identity-2026-07-28.json"
)
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-gravitino-identity.sh"
MANIFEST_DIR = REPO_ROOT / "k8s/metadata-fabric-gravitino-identity"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]


class MetadataFabricGravitinoIdentityError(RuntimeError):
    """The Gravitino identity contract or live rehearsal failed closed."""


class ProviderRequestError(MetadataFabricGravitinoIdentityError):
    """A Gravitino request failed without exposing response or login material."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClusterProfile(_FrozenModel):
    context: Literal["docker-desktop"]
    source_namespace: Literal["gda-metadata-sandbox"]
    rehearsal_namespace: Literal["gda-metadata-identity"]
    source_schema_configmap: Literal["metadata-gravitino-schema-1-3-0"]


class RuntimeProfile(_FrozenModel):
    manifest: Literal["k8s/metadata-fabric-gravitino-identity"]
    gravitino_version: Literal["1.3.0"]
    gravitino_image: Literal["gda/gravitino:1.3.0-local-arm64"]
    postgresql_version: Literal["16.10-bookworm"]
    postgresql_image: Literal["postgres:16.10-bookworm"]
    service: Literal["gravitino-identity"]
    service_port: Literal[8090]
    authenticator: Literal["basic"]
    idp_extension: Literal["org.apache.gravitino.idp.web.rest.feature"]
    access_control_enabled: Literal[True]
    service_account: Literal["gravitino-identity"]
    service_account_automount_disabled: Literal[True]
    transport: Literal["local_loopback_http"]


class IdentityProfile(_FrozenModel):
    service_admin: Literal["gda-identity-admin"]
    user: Literal["gda-metadata-projection"]
    role: Literal["gda-table-projection"]
    material_delivery: Literal["runtime_generated_ephemeral_kubernetes_object"]
    login_rotation: Literal["administrator_reset"]
    revocation: Literal["idp_user_delete"]


class PrivilegeProfile(_FrozenModel):
    name: Literal["USE_CATALOG", "USE_SCHEMA", "CREATE_TABLE"]
    condition: Literal["ALLOW"]


class SecurableObjectProfile(_FrozenModel):
    full_name: Literal["lakehouse", "lakehouse.published"]
    type: Literal["CATALOG", "SCHEMA"]
    privileges: tuple[PrivilegeProfile, ...]


class ScopeProfile(_FrozenModel):
    metalake: Literal["gda_identity"]
    catalog: Literal["lakehouse"]
    schema_name: Literal["published"] = Field(alias="schema")
    table: Literal["gda_identity_probe"]
    denied_catalog: Literal["unauthorized_catalog"]
    role_securable_objects: tuple[SecurableObjectProfile, ...]


class ClaimProfile(_FrozenModel):
    local_gravitino_basic_identity_verified: Literal[False]
    local_gravitino_minimum_privilege_verified: Literal[False]
    local_gravitino_login_rotation_verified: Literal[False]
    local_gravitino_revocation_verified: Literal[False]
    gravitino_authentication_verified: Literal[False]
    provider_minimum_privilege_verified: Literal[False]
    protected_workload_identity_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    production_identity_verified: Literal[False]
    production_ready: Literal[False]


class GravitinoIdentityProfile(_FrozenModel):
    schema_name: Literal["gda.metadata_fabric_gravitino_identity_profile.v1"] = (
        Field(alias="schema")
    )
    environment: Literal["local_docker_desktop"]
    cluster: ClusterProfile
    runtime: RuntimeProfile
    identity: IdentityProfile
    scope: ScopeProfile
    claims: ClaimProfile


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expected_securable_objects() -> list[dict[str, Any]]:
    return [
        {
            "fullName": "lakehouse",
            "type": "CATALOG",
            "privileges": [{"name": "USE_CATALOG", "condition": "ALLOW"}],
        },
        {
            "fullName": "lakehouse.published",
            "type": "SCHEMA",
            "privileges": [
                {"name": "CREATE_TABLE", "condition": "ALLOW"},
                {"name": "USE_SCHEMA", "condition": "ALLOW"},
            ],
        },
    ]


def _profile_securable_objects(
    profile: GravitinoIdentityProfile,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in profile.scope.role_securable_objects:
        result.append(
            {
                "fullName": item.full_name,
                "type": item.type,
                "privileges": sorted(
                    [entry.model_dump(mode="json") for entry in item.privileges],
                    key=lambda entry: entry["name"],
                ),
            }
        )
    return sorted(result, key=lambda item: item["fullName"])


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> GravitinoIdentityProfile:
    try:
        value = yaml.safe_load(path.resolve().read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Gravitino identity profile must be an object")
        ingestion_replay._reject_sensitive_fields(value)
        profile = GravitinoIdentityProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise MetadataFabricGravitinoIdentityError(
            "Gravitino identity profile is invalid"
        ) from exc
    if _profile_securable_objects(profile) != _expected_securable_objects():
        raise MetadataFabricGravitinoIdentityError(
            "Gravitino identity role exceeds the bounded table-create scope"
        )
    return profile


def _manifest_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in sorted(MANIFEST_DIR.glob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        for value in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(value, dict):
                documents.append(value)
    return documents


def _validate_manifest() -> list[str]:
    errors: list[str] = []
    try:
        documents = _manifest_documents()
    except (OSError, yaml.YAMLError) as exc:
        return [f"Gravitino identity manifest is invalid: {type(exc).__name__}"]
    if any(document.get("kind") == "Secret" for document in documents):
        errors.append("Gravitino identity manifest may not commit Secret values")
    kinds = {str(document.get("kind")) for document in documents}
    if not {"Namespace", "ServiceAccount", "ConfigMap", "Service", "StatefulSet"}.issubset(
        kinds
    ):
        errors.append("Gravitino identity manifest is incomplete")
    rendered = json.dumps(documents, ensure_ascii=True, sort_keys=True)
    for marker in (
        "gravitino.authenticators = basic",
        "gravitino.authorization.enable = true",
        "org.apache.gravitino.idp.web.rest.feature",
        "GRAVITINO_INITIAL_ADMIN_PASSWORD",
        "automountServiceAccountToken",
        "ClusterIP",
        "emptyDir",
    ):
        if marker not in rendered:
            errors.append(f"Gravitino identity manifest is missing marker: {marker}")
    if "gravitino.authenticators = simple" in rendered:
        errors.append("Gravitino identity manifest may not enable the simple authenticator")
    return errors


def build_contract_report(
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: GravitinoIdentityProfile | None = None
    try:
        profile = load_profile(profile_path)
    except MetadataFabricGravitinoIdentityError as exc:
        errors.append(str(exc))
    errors.extend(_validate_manifest())

    try:
        wrapper = wrapper_path.resolve().read_text(encoding="utf-8")
        for marker in ("set -euo pipefail", "metadata_fabric_gravitino_identity"):
            if marker not in wrapper:
                errors.append(f"Gravitino identity wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"Gravitino identity wrapper is invalid: {type(exc).__name__}")

    files: dict[str, dict[str, str]] = {}
    paths = [Path(__file__).resolve(), profile_path.resolve(), wrapper_path.resolve()]
    paths.extend(sorted(MANIFEST_DIR.glob("*.yaml")))
    for path in paths:
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            relative = path.name
        files[relative] = {"path": relative, "sha256": recovery._file_sha256(path)}

    stable = {
        "schema": CONTRACT_SCHEMA,
        "context": CONTEXT,
        "source_namespace": SOURCE_NAMESPACE,
        "rehearsal_namespace": REHEARSAL_NAMESPACE,
        "gravitino_version": "1.3.0",
        "authentication": {
            "authenticator": profile.runtime.authenticator if profile else None,
            "access_control_enabled": (
                profile.runtime.access_control_enabled if profile else None
            ),
            "idp_extension": profile.runtime.idp_extension if profile else None,
            "simple_authenticator_trusted": False,
            "built_in_idp_scope": "local_poc_only",
        },
        "role_securable_objects": (
            _profile_securable_objects(profile) if profile else None
        ),
        "local_static_contract_verified": not errors,
        "local_gravitino_basic_identity_verified": False,
        "local_gravitino_minimum_privilege_verified": False,
        "gravitino_authentication_verified": False,
        "provider_minimum_privilege_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_identity_verified": False,
        "production_ready": False,
        "files": files,
        "errors": errors,
    }
    return {**stable, "contract_fingerprint": recovery._canonical_sha256(stable)}


class _Kubectl:
    def __init__(self, context: str) -> None:
        self.context = context

    def run(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
        expected: frozenset[int] = frozenset({0}),
        timeout: int = 300,
        label: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                ["kubectl", "--context", self.context, *args],
                input=input_text,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MetadataFabricGravitinoIdentityError(
                f"kubectl failed during {label}"
            ) from exc
        if completed.returncode not in expected:
            raise MetadataFabricGravitinoIdentityError(
                f"kubectl returned {completed.returncode} during {label}"
            )
        return completed

    def get_json(
        self,
        args: list[str],
        *,
        allow_not_found: bool = False,
        label: str,
    ) -> dict[str, Any] | None:
        expected = frozenset({0, 1}) if allow_not_found else frozenset({0})
        completed = self.run(
            [*args, "-o", "json"], expected=expected, timeout=60, label=label
        )
        if completed.returncode != 0:
            return None
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise MetadataFabricGravitinoIdentityError(
                f"kubectl returned invalid JSON during {label}"
            ) from exc
        if not isinstance(value, dict):
            raise MetadataFabricGravitinoIdentityError(
                f"kubectl returned a non-object during {label}"
            )
        return value


class IsolatedGravitinoRuntime:
    """Own and remove the temporary namespace used by the identity rehearsal."""

    def __init__(self, profile: GravitinoIdentityProfile) -> None:
        self.profile = profile
        self.kubectl = _Kubectl(profile.cluster.context)
        self.owned_namespace = False
        self.schema_sha256: str | None = None

    def _runtime_inputs(
        self,
        admin_material: SecretStr,
        database_material: SecretStr,
    ) -> str:
        source = self.kubectl.get_json(
            [
                "-n",
                self.profile.cluster.source_namespace,
                "get",
                "configmap",
                self.profile.cluster.source_schema_configmap,
            ],
            label="source schema lookup",
        )
        assert source is not None
        schema_sql = _mapping(source.get("data")).get("001-schema.sql")
        if not isinstance(schema_sql, str):
            raise MetadataFabricGravitinoIdentityError(
                "verified Gravitino PostgreSQL schema is unavailable"
            )
        self.schema_sha256 = _sha256_text(schema_sql)
        if self.schema_sha256 != GRAVITINO_SCHEMA_SHA256:
            raise MetadataFabricGravitinoIdentityError(
                "Gravitino PostgreSQL schema checksum drift"
            )
        resources = {
            "apiVersion": "v1",
            "kind": "List",
            "items": [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {
                        "name": "gravitino-identity-runtime",
                        "namespace": self.profile.cluster.rehearsal_namespace,
                    },
                    "type": "Opaque",
                    "stringData": {
                        "admin-password": admin_material.get_secret_value(),
                        "database-password": database_material.get_secret_value(),
                    },
                },
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": "gravitino-identity-schema",
                        "namespace": self.profile.cluster.rehearsal_namespace,
                    },
                    "data": {"001-schema.sql": schema_sql},
                },
            ],
        }
        return json.dumps(resources, ensure_ascii=True, separators=(",", ":"))

    def start(
        self,
        *,
        admin_material: SecretStr,
        database_material: SecretStr,
    ) -> dict[str, Any]:
        existing = self.kubectl.get_json(
            ["get", "namespace", self.profile.cluster.rehearsal_namespace],
            allow_not_found=True,
            label="rehearsal namespace preflight",
        )
        if existing is not None:
            raise MetadataFabricGravitinoIdentityError(
                "Gravitino identity rehearsal namespace already exists"
            )
        self.kubectl.run(
            ["apply", "-f", str(MANIFEST_DIR / "namespace.yaml")],
            label="rehearsal namespace apply",
        )
        self.owned_namespace = True
        runtime_inputs = self._runtime_inputs(admin_material, database_material)
        self.kubectl.run(
            ["apply", "-f", "-"],
            input_text=runtime_inputs,
            label="ephemeral runtime input apply",
        )
        self.kubectl.run(
            ["apply", "-k", str(MANIFEST_DIR)],
            label="isolated Gravitino runtime apply",
        )
        namespace = self.profile.cluster.rehearsal_namespace
        for workload in (
            "statefulset/gravitino-identity-postgresql",
            "statefulset/gravitino-identity",
        ):
            self.kubectl.run(
                [
                    "-n",
                    namespace,
                    "rollout",
                    "status",
                    workload,
                    "--timeout=10m",
                ],
                timeout=660,
                label=f"{workload} rollout",
            )
        return self.observe()

    def observe(self) -> dict[str, Any]:
        namespace_name = self.profile.cluster.rehearsal_namespace
        namespace = self.kubectl.get_json(
            ["get", "namespace", namespace_name], label="namespace observation"
        )
        service = self.kubectl.get_json(
            ["-n", namespace_name, "get", "service", "gravitino-identity"],
            label="service observation",
        )
        workload = self.kubectl.get_json(
            [
                "-n",
                namespace_name,
                "get",
                "statefulset",
                "gravitino-identity",
            ],
            label="Gravitino workload observation",
        )
        database = self.kubectl.get_json(
            [
                "-n",
                namespace_name,
                "get",
                "statefulset",
                "gravitino-identity-postgresql",
            ],
            label="PostgreSQL workload observation",
        )
        assert namespace is not None and service is not None
        assert workload is not None and database is not None
        workload_spec = _mapping(_mapping(workload.get("spec")).get("template"))
        workload_pod = _mapping(workload_spec.get("spec"))
        containers = workload_pod.get("containers")
        container = _mapping(containers[0]) if isinstance(containers, list) else {}
        database_spec = _mapping(_mapping(database.get("spec")).get("template"))
        database_pod = _mapping(database_spec.get("spec"))
        database_containers = database_pod.get("containers")
        database_container = (
            _mapping(database_containers[0])
            if isinstance(database_containers, list)
            else {}
        )
        data_volume = next(
            (
                _mapping(item)
                for item in database_pod.get("volumes", [])
                if _mapping(item).get("name") == "data"
            ),
            {},
        )
        return {
            "context": self.profile.cluster.context,
            "namespace": {
                "name": _mapping(namespace.get("metadata")).get("name"),
                "uid": _mapping(namespace.get("metadata")).get("uid"),
            },
            "service": {
                "name": _mapping(service.get("metadata")).get("name"),
                "uid": _mapping(service.get("metadata")).get("uid"),
                "type": _mapping(service.get("spec")).get("type"),
            },
            "gravitino": {
                "kind": workload.get("kind"),
                "name": _mapping(workload.get("metadata")).get("name"),
                "uid": _mapping(workload.get("metadata")).get("uid"),
                "image": container.get("image"),
                "service_account": workload_pod.get("serviceAccountName"),
                "service_account_automount_disabled": (
                    workload_pod.get("automountServiceAccountToken") is False
                ),
                "ready_replicas": _mapping(workload.get("status")).get(
                    "readyReplicas", 0
                ),
            },
            "postgresql": {
                "kind": database.get("kind"),
                "name": _mapping(database.get("metadata")).get("name"),
                "uid": _mapping(database.get("metadata")).get("uid"),
                "image": database_container.get("image"),
                "service_account": database_pod.get("serviceAccountName"),
                "service_account_automount_disabled": (
                    database_pod.get("automountServiceAccountToken") is False
                ),
                "ready_replicas": _mapping(database.get("status")).get(
                    "readyReplicas", 0
                ),
                "ephemeral_data_volume": "emptyDir" in data_volume,
            },
            "source_schema_sha256": self.schema_sha256,
        }

    def cleanup(self) -> dict[str, Any]:
        deleted = False
        if self.owned_namespace:
            try:
                self.kubectl.run(
                    [
                        "delete",
                        "namespace",
                        self.profile.cluster.rehearsal_namespace,
                        "--wait=true",
                        "--timeout=5m",
                    ],
                    timeout=330,
                    label="rehearsal namespace cleanup",
                )
                deleted = True
            finally:
                self.owned_namespace = False
        absent = (
            self.kubectl.get_json(
                ["get", "namespace", self.profile.cluster.rehearsal_namespace],
                allow_not_found=True,
                label="rehearsal namespace cleanup verification",
            )
            is None
        )
        return {
            "namespace_delete_completed": deleted,
            "namespace_absent": absent,
            "provider_objects_retained": False,
        }


def _json_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError as exc:
        raise ProviderRequestError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProviderRequestError(f"{label} response is not an object")
    return value


class _BasicApi:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        material: SecretStr,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            auth=httpx.BasicAuth(username, material.get_secret_value()),
            headers={
                "Accept": "application/vnd.gravitino.v1+json",
                "Content-Type": "application/json",
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


def _response_entity(
    payload: Mapping[str, Any] | None, key: str, label: str
) -> dict[str, Any]:
    entity = _mapping(_mapping(payload).get(key))
    if not entity:
        raise ProviderRequestError(f"{label} omitted {key}")
    return dict(entity)


def _normalize_securable_objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        source = _mapping(item)
        privileges = source.get("privileges")
        normalized_privileges = []
        if isinstance(privileges, list):
            for privilege in privileges:
                entry = _mapping(privilege)
                normalized_privileges.append(
                    {
                        "name": str(entry.get("name", "")).upper(),
                        "condition": str(entry.get("condition", "")).upper(),
                    }
                )
        normalized.append(
            {
                "fullName": source.get("fullName"),
                "type": str(source.get("type", "")).upper(),
                "privileges": sorted(
                    normalized_privileges, key=lambda entry: str(entry["name"])
                ),
            }
        )
    return sorted(normalized, key=lambda entry: str(entry["fullName"]))


class GravitinoIdentityRehearsal:
    """Exercise one Basic IdP user with a schema-bounded table-create role."""

    def __init__(
        self,
        *,
        base_url: str,
        admin_name: str,
        admin_material: SecretStr,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.transport = transport
        self.admin = _BasicApi(
            base_url=base_url,
            username=admin_name,
            material=admin_material,
            transport=transport,
        )
        self.clients: list[_BasicApi] = []

    def close(self) -> None:
        for client in self.clients:
            client.close()
        self.clients.clear()
        self.admin.close()

    def _user_api(self, name: str, material: SecretStr) -> _BasicApi:
        client = _BasicApi(
            base_url=self.base_url,
            username=name,
            material=material,
            transport=self.transport,
        )
        self.clients.append(client)
        return client

    @staticmethod
    def _catalog_path(profile: GravitinoIdentityProfile, catalog: str) -> str:
        return f"metalakes/{quote(profile.scope.metalake)}/catalogs/{quote(catalog)}"

    @staticmethod
    def _schema_path(profile: GravitinoIdentityProfile) -> str:
        return (
            f"metalakes/{quote(profile.scope.metalake)}/catalogs/"
            f"{quote(profile.scope.catalog)}/schemas/{quote(profile.scope.schema_name)}"
        )

    @classmethod
    def _table_path(cls, profile: GravitinoIdentityProfile) -> str:
        return f"{cls._schema_path(profile)}/tables/{quote(profile.scope.table)}"

    def execute(
        self,
        profile: GravitinoIdentityProfile,
        *,
        initial_material: SecretStr,
        rotated_material: SecretStr,
    ) -> dict[str, Any]:
        admin_status, version_payload = self.admin.request(
            "GET", "version", label="Gravitino service-admin authentication"
        )
        version = _mapping(_mapping(version_payload).get("version")).get("version")
        if version is None:
            version = _mapping(version_payload).get("version")

        unregistered = self._user_api(profile.identity.user, initial_material)
        unregistered_status, _payload = unregistered.request(
            "GET",
            "version",
            expected=frozenset({200, 401}),
            label="Gravitino unregistered principal probe",
        )

        _status, metalake_payload = self.admin.request(
            "POST",
            "metalakes",
            json_body={
                "name": profile.scope.metalake,
                "comment": "Ephemeral GDA authenticated identity rehearsal",
                "properties": {"gda.environment": "local_identity_rehearsal"},
            },
            label="Gravitino metalake create",
        )
        metalake = _response_entity(metalake_payload, "metalake", "metalake create")
        _status, catalog_payload = self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/catalogs",
            json_body={
                "name": profile.scope.catalog,
                "type": "RELATIONAL",
                "provider": "lakehouse-iceberg",
                "comment": "Ephemeral authenticated table projection catalog",
                "properties": {
                    "catalog-backend": "memory",
                    "uri": "file:///tmp/gda-identity",
                    "warehouse": "file:///tmp/gda-identity",
                },
            },
            label="Gravitino catalog create",
        )
        catalog = _response_entity(catalog_payload, "catalog", "catalog create")
        _status, schema_payload = self.admin.request(
            "POST",
            f"{self._catalog_path(profile, profile.scope.catalog)}/schemas",
            json_body={
                "name": profile.scope.schema_name,
                "comment": "Ephemeral bounded table projection schema",
                "properties": {},
            },
            label="Gravitino schema create",
        )
        schema = _response_entity(schema_payload, "schema", "schema create")

        _status, idp_user_payload = self.admin.request(
            "POST",
            "idp/users",
            json_body={
                "user": profile.identity.user,
                "password": initial_material.get_secret_value(),
            },
            label="Gravitino built-in IdP user create",
        )
        _status, user_payload = self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/users",
            json_body={"name": profile.identity.user},
            label="Gravitino metalake user register",
        )
        user = _response_entity(user_payload, "user", "metalake user register")

        _status, role_payload = self.admin.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/roles",
            json_body={
                "name": profile.identity.role,
                "properties": {"gda.scope": "bounded_table_projection"},
                "securableObjects": _expected_securable_objects(),
            },
            label="Gravitino bounded role create",
        )
        role = _response_entity(role_payload, "role", "role create")
        _status, granted_payload = self.admin.request(
            "PUT",
            (
                f"metalakes/{quote(profile.scope.metalake)}/permissions/users/"
                f"{quote(profile.identity.user)}/grant"
            ),
            json_body={"roleNames": [profile.identity.role]},
            label="Gravitino role grant",
        )
        granted_user = _response_entity(granted_payload, "user", "role grant")
        _status, role_read_payload = self.admin.request(
            "GET",
            (
                f"metalakes/{quote(profile.scope.metalake)}/roles/"
                f"{quote(profile.identity.role)}"
            ),
            label="Gravitino role readback",
        )
        role_read = _response_entity(role_read_payload, "role", "role readback")

        initial_api = self._user_api(profile.identity.user, initial_material)
        initial_status, _initial_payload = initial_api.request(
            "GET", "version", label="Gravitino bounded user authentication"
        )
        create_status, table_payload = initial_api.request(
            "POST",
            f"{self._schema_path(profile)}/tables",
            json_body={
                "name": profile.scope.table,
                "comment": "Ephemeral authenticated table-create probe",
                "columns": [
                    {
                        "name": "probe_id",
                        "type": "string",
                        "nullable": False,
                        "comment": "Identity probe identifier",
                    }
                ],
                "properties": {"gda.identity_probe": "true"},
            },
            label="Gravitino allowed table create probe",
        )
        table = _response_entity(table_payload, "table", "table create")
        read_status, table_read_payload = initial_api.request(
            "GET", self._table_path(profile), label="Gravitino table readback"
        )
        table_read = _response_entity(table_read_payload, "table", "table readback")

        denied_status, _denied_payload = initial_api.request(
            "POST",
            f"metalakes/{quote(profile.scope.metalake)}/catalogs",
            json_body={
                "name": profile.scope.denied_catalog,
                "type": "RELATIONAL",
                "provider": "lakehouse-iceberg",
                "comment": "Must not be created by the bounded user",
                "properties": {
                    "catalog-backend": "memory",
                    "uri": "file:///tmp/gda-identity-denied",
                    "warehouse": "file:///tmp/gda-identity-denied",
                },
            },
            expected=frozenset({200, 403}),
            label="Gravitino denied catalog create probe",
        )

        self.admin.request(
            "PUT",
            f"idp/users/{quote(profile.identity.user)}",
            json_body={"password": rotated_material.get_secret_value()},
            label="Gravitino built-in IdP login rotation",
        )
        old_after_rotation, _payload = initial_api.request(
            "GET",
            "version",
            expected=frozenset({200, 401}),
            label="Gravitino old login after rotation",
        )
        rotated_api = self._user_api(profile.identity.user, rotated_material)
        rotated_status, rotated_table_payload = rotated_api.request(
            "GET",
            self._table_path(profile),
            expected=frozenset({200, 401, 403}),
            label="Gravitino rotated login",
        )
        rotated_table = (
            _response_entity(rotated_table_payload, "table", "rotated table readback")
            if rotated_status == 200
            else {}
        )
        self.admin.request(
            "DELETE",
            f"idp/users/{quote(profile.identity.user)}",
            label="Gravitino built-in IdP user revocation",
        )
        after_revocation, _payload = rotated_api.request(
            "GET",
            "version",
            expected=frozenset({200, 401}),
            label="Gravitino revoked login",
        )
        idp_lookup_status, _payload = self.admin.request(
            "GET",
            f"idp/users/{quote(profile.identity.user)}",
            expected=frozenset({200, 404}),
            label="Gravitino built-in IdP user absence",
        )

        return {
            "version": version,
            "configuration": {
                "authenticator": profile.runtime.authenticator,
                "access_control_enabled": profile.runtime.access_control_enabled,
                "idp_extension": profile.runtime.idp_extension,
                "built_in_idp_scope": "local_poc_only",
                "simple_authenticator_trusted": False,
            },
            "authentication": {
                "service_admin_status": admin_status,
                "unregistered_principal_status": unregistered_status,
                "bounded_user_status": initial_status,
                "material_recorded": False,
            },
            "principal": {
                "name": user.get("name"),
                "granted_name": granted_user.get("name"),
                "roles": sorted(granted_user.get("roles", [])),
                "is_service_admin": False,
            },
            "role": {
                "name": role.get("name"),
                "readback_name": role_read.get("name"),
                "securable_objects": _normalize_securable_objects(
                    role_read.get("securableObjects")
                ),
            },
            "bootstrap": {
                "metalake": metalake.get("name"),
                "catalog": catalog.get("name"),
                "schema": schema.get("name"),
                "service_admin_used": True,
                "minimum_privilege": False,
            },
            "allowed_probe": {
                "operation": "CREATE_TABLE",
                "resource": "SCHEMA",
                "create_status": create_status,
                "read_status": read_status,
                "table": table.get("name"),
                "readback_table": table_read.get("name"),
                "rotated_readback_table": rotated_table.get("name"),
                "full_name": (
                    f"{profile.scope.catalog}.{profile.scope.schema_name}."
                    f"{profile.scope.table}"
                ),
            },
            "denied_probe": {
                "operation": "CREATE_CATALOG",
                "resource": "METALAKE",
                "catalog": profile.scope.denied_catalog,
                "status": denied_status,
            },
            "login_lifecycle": {
                "rotation_mode": profile.identity.login_rotation,
                "old_after_rotation_status": old_after_rotation,
                "rotated_authentication_status": rotated_status,
                "revocation_mode": profile.identity.revocation,
                "after_revocation_status": after_revocation,
                "idp_principal_absent": idp_lookup_status == 404,
                "material_recorded": False,
            },
            "idp_create_response_present": bool(idp_user_payload),
        }


def build_evidence(observation: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        ingestion_replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("Gravitino identity observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("Gravitino identity observation schema does not match")

    contract = _mapping(observation.get("contract"))
    if (
        contract.get("local_static_contract_verified") is not True
        or not _valid_sha256(contract.get("contract_fingerprint"))
    ):
        errors.append("Gravitino identity static contract is not bound")

    runtime = _mapping(observation.get("runtime"))
    gravitino_runtime = _mapping(runtime.get("gravitino"))
    postgresql_runtime = _mapping(runtime.get("postgresql"))
    if (
        runtime.get("context") != CONTEXT
        or _mapping(runtime.get("namespace")).get("name") != REHEARSAL_NAMESPACE
        or not _valid_uuid(_mapping(runtime.get("namespace")).get("uid"))
        or _mapping(runtime.get("service")).get("name") != "gravitino-identity"
        or _mapping(runtime.get("service")).get("type") != "ClusterIP"
        or not _valid_uuid(_mapping(runtime.get("service")).get("uid"))
        or runtime.get("source_schema_sha256") != GRAVITINO_SCHEMA_SHA256
        or gravitino_runtime.get("kind") != "StatefulSet"
        or gravitino_runtime.get("name") != "gravitino-identity"
        or gravitino_runtime.get("image") != "gda/gravitino:1.3.0-local-arm64"
        or gravitino_runtime.get("service_account") != "gravitino-identity"
        or gravitino_runtime.get("service_account_automount_disabled") is not True
        or gravitino_runtime.get("ready_replicas") != 1
        or postgresql_runtime.get("kind") != "StatefulSet"
        or postgresql_runtime.get("name") != "gravitino-identity-postgresql"
        or postgresql_runtime.get("image") != "postgres:16.10-bookworm"
        or postgresql_runtime.get("service_account")
        != "gravitino-identity-postgresql"
        or postgresql_runtime.get("service_account_automount_disabled") is not True
        or postgresql_runtime.get("ready_replicas") != 1
        or postgresql_runtime.get("ephemeral_data_volume") is not True
    ):
        errors.append("isolated Gravitino identity runtime does not match")

    provider = _mapping(observation.get("gravitino"))
    configuration = _mapping(provider.get("configuration"))
    if configuration != {
        "authenticator": "basic",
        "access_control_enabled": True,
        "idp_extension": "org.apache.gravitino.idp.web.rest.feature",
        "built_in_idp_scope": "local_poc_only",
        "simple_authenticator_trusted": False,
    }:
        errors.append("Gravitino Basic IdP configuration does not match")
    if provider.get("version") != "1.3.0":
        errors.append("Gravitino identity provider version does not match")

    authentication = _mapping(provider.get("authentication"))
    if authentication != {
        "service_admin_status": 200,
        "unregistered_principal_status": 401,
        "bounded_user_status": 200,
        "material_recorded": False,
    }:
        errors.append("Gravitino Basic authentication was not enforced")

    principal = _mapping(provider.get("principal"))
    if (
        principal.get("name") != "gda-metadata-projection"
        or principal.get("granted_name") != "gda-metadata-projection"
        or principal.get("roles") != ["gda-table-projection"]
        or principal.get("is_service_admin") is not False
    ):
        errors.append("Gravitino bounded principal does not match")

    role = _mapping(provider.get("role"))
    if (
        role.get("name") != "gda-table-projection"
        or role.get("readback_name") != "gda-table-projection"
        or role.get("securable_objects") != _expected_securable_objects()
    ):
        errors.append("Gravitino role exceeds the bounded table-create scope")

    bootstrap = _mapping(provider.get("bootstrap"))
    if bootstrap != {
        "metalake": "gda_identity",
        "catalog": "lakehouse",
        "schema": "published",
        "service_admin_used": True,
        "minimum_privilege": False,
    }:
        errors.append("Gravitino service-admin bootstrap boundary is missing")

    allowed = _mapping(provider.get("allowed_probe"))
    if (
        allowed.get("operation") != "CREATE_TABLE"
        or allowed.get("resource") != "SCHEMA"
        or allowed.get("create_status") != 200
        or allowed.get("read_status") != 200
        or allowed.get("table") != "gda_identity_probe"
        or allowed.get("readback_table") != "gda_identity_probe"
        or allowed.get("rotated_readback_table") != "gda_identity_probe"
        or allowed.get("full_name") != "lakehouse.published.gda_identity_probe"
    ):
        errors.append("Gravitino allowed table-create probe did not pass")

    denied = _mapping(provider.get("denied_probe"))
    if denied != {
        "operation": "CREATE_CATALOG",
        "resource": "METALAKE",
        "catalog": "unauthorized_catalog",
        "status": 403,
    }:
        errors.append("Gravitino catalog-create denial was not enforced")

    lifecycle = _mapping(provider.get("login_lifecycle"))
    if lifecycle != {
        "rotation_mode": "administrator_reset",
        "old_after_rotation_status": 401,
        "rotated_authentication_status": 200,
        "revocation_mode": "idp_user_delete",
        "after_revocation_status": 401,
        "idp_principal_absent": True,
        "material_recorded": False,
    }:
        errors.append("Gravitino login rotation or revocation did not pass")
    if provider.get("idp_create_response_present") is not True:
        errors.append("Gravitino built-in IdP user creation was not observed")

    runtime_checks = _mapping(observation.get("runtime_checks"))
    if runtime_checks != {
        "namespace_delete_completed": True,
        "namespace_absent": True,
        "provider_objects_retained": False,
        "all_port_forwards_stopped": True,
        "material_recorded": False,
        "kubernetes_service_account_used_for_provider_login": False,
    }:
        errors.append("Gravitino identity runtime cleanup is incomplete")

    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "status": "local_gravitino_basic_identity_verified" if verified else "blocked",
        "observation": dict(observation),
        "errors": errors,
        "local_gravitino_basic_identity_verified": verified,
        "local_gravitino_minimum_privilege_verified": verified,
        "local_gravitino_login_rotation_verified": verified,
        "local_gravitino_revocation_verified": verified,
        "gravitino_authentication_verified": False,
        "provider_minimum_privilege_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_identity_verified": False,
        "production_ready": False,
    }
    return {**stable, "evidence_fingerprint": recovery._canonical_sha256(stable)}


def verify_evidence_integrity(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        errors.append("Gravitino identity evidence schema does not match")
    expected = build_evidence(_mapping(evidence.get("observation")))
    if dict(evidence) != expected:
        errors.append("Gravitino identity evidence content or fingerprint drifted")
    for claim in (
        "gravitino_authentication_verified",
        "provider_minimum_privilege_verified",
        "protected_workload_identity_verified",
        "oidc_verified",
        "tls_verified",
        "production_identity_verified",
        "production_ready",
    ):
        if evidence.get(claim) is not False:
            errors.append(f"Gravitino identity evidence may not claim {claim}")
    if evidence.get("local_gravitino_basic_identity_verified") is not True:
        errors.append("local Gravitino Basic identity is not verified")
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    contract = build_contract_report(profile_path)
    if contract.get("local_static_contract_verified") is not True:
        raise MetadataFabricGravitinoIdentityError(
            "Gravitino identity static contract is invalid"
        )

    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    initial_material = SecretStr(secrets.token_urlsafe(24))
    rotated_material = SecretStr(secrets.token_urlsafe(24))
    runtime = IsolatedGravitinoRuntime(profile)
    forward: provider_metrics._PortForward | None = None
    rehearsal: GravitinoIdentityRehearsal | None = None
    runtime_observation: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    forward_stopped = False
    cleanup: dict[str, Any] = {
        "namespace_delete_completed": False,
        "namespace_absent": False,
        "provider_objects_retained": True,
    }
    try:
        runtime_observation = runtime.start(
            admin_material=admin_material,
            database_material=database_material,
        )
        forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=profile.cluster.context,
            namespace=profile.cluster.rehearsal_namespace,
            service=profile.runtime.service,
            target_port=profile.runtime.service_port,
        )
        forward.start()
        rehearsal = GravitinoIdentityRehearsal(
            base_url=f"http://127.0.0.1:{forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        result = rehearsal.execute(
            profile,
            initial_material=initial_material,
            rotated_material=rotated_material,
        )
    finally:
        if rehearsal is not None:
            rehearsal.close()
        if forward is not None:
            forward_stopped = forward.stop()
        cleanup = runtime.cleanup()

    if runtime_observation is None or result is None:
        raise MetadataFabricGravitinoIdentityError(
            "Gravitino identity rehearsal did not produce an outcome"
        )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_fingerprint": contract["contract_fingerprint"],
            "local_static_contract_verified": True,
        },
        "runtime": runtime_observation,
        "gravitino": result,
        "runtime_checks": {
            **cleanup,
            "all_port_forwards_stopped": forward_stopped,
            "material_recorded": False,
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
            raise TypeError("Gravitino identity evidence must be an object")
        evidence = value
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = _mapping(
            _mapping(evidence.get("observation")).get("contract")
        ).get("contract_fingerprint")
        if observed_contract != contract.get("contract_fingerprint"):
            errors.append("Gravitino identity evidence contract fingerprint drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"Gravitino identity evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "local_static_contract_verified": contract["local_static_contract_verified"],
        "local_gravitino_basic_identity_verified": (
            verified
            and evidence is not None
            and evidence.get("local_gravitino_basic_identity_verified") is True
        ),
        "local_gravitino_minimum_privilege_verified": (
            verified
            and evidence is not None
            and evidence.get("local_gravitino_minimum_privilege_verified") is True
        ),
        "gravitino_authentication_verified": False,
        "provider_minimum_privilege_verified": False,
        "protected_workload_identity_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_identity_verified": False,
        "production_ready": False,
        "contract_fingerprint": contract["contract_fingerprint"],
        "evidence_fingerprint": evidence.get("evidence_fingerprint") if evidence else None,
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
                profile_path=args.profile, evidence_path=args.evidence
            )
            print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
            return 0 if not report["errors"] else 1
        if args.command == "verify":
            value = json.loads(args.evidence.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise TypeError("Gravitino identity evidence must be an object")
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
        MetadataFabricGravitinoIdentityError,
        KeyboardInterrupt,
    ) as exc:
        print(f"metadata fabric Gravitino identity: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
