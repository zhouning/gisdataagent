import base64
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote

import httpx
import yaml
from pydantic import SecretStr

from data_agent import metadata_fabric_gravitino_identity as identity


def _provider_result() -> dict:
    return {
        "version": "1.3.0",
        "configuration": {
            "authenticator": "basic",
            "access_control_enabled": True,
            "idp_extension": "org.apache.gravitino.idp.web.rest.feature",
            "built_in_idp_scope": "local_poc_only",
            "simple_authenticator_trusted": False,
        },
        "authentication": {
            "service_admin_status": 200,
            "unregistered_principal_status": 401,
            "bounded_user_status": 200,
            "material_recorded": False,
        },
        "principal": {
            "name": "gda-metadata-projection",
            "granted_name": "gda-metadata-projection",
            "roles": ["gda-table-projection"],
            "is_service_admin": False,
        },
        "role": {
            "name": "gda-table-projection",
            "readback_name": "gda-table-projection",
            "securable_objects": identity._expected_securable_objects(),
        },
        "bootstrap": {
            "metalake": "gda_identity",
            "catalog": "lakehouse",
            "schema": "published",
            "service_admin_used": True,
            "minimum_privilege": False,
        },
        "allowed_probe": {
            "operation": "CREATE_TABLE",
            "resource": "SCHEMA",
            "create_status": 200,
            "read_status": 200,
            "table": "gda_identity_probe",
            "readback_table": "gda_identity_probe",
            "rotated_readback_table": "gda_identity_probe",
            "full_name": "lakehouse.published.gda_identity_probe",
        },
        "denied_probe": {
            "operation": "CREATE_CATALOG",
            "resource": "METALAKE",
            "catalog": "unauthorized_catalog",
            "status": 403,
        },
        "login_lifecycle": {
            "rotation_mode": "administrator_reset",
            "old_after_rotation_status": 401,
            "rotated_authentication_status": 200,
            "revocation_mode": "idp_user_delete",
            "after_revocation_status": 401,
            "idp_principal_absent": True,
            "material_recorded": False,
        },
        "idp_create_response_present": True,
    }


def _observation() -> dict:
    return {
        "schema": identity.OBSERVATION_SCHEMA,
        "observed_at": "2026-07-28T14:00:00+00:00",
        "contract": {
            "contract_fingerprint": "a" * 64,
            "local_static_contract_verified": True,
        },
        "runtime": {
            "context": identity.CONTEXT,
            "namespace": {
                "name": identity.REHEARSAL_NAMESPACE,
                "uid": "11111111-1111-4111-8111-111111111111",
            },
            "service": {
                "name": "gravitino-identity",
                "uid": "22222222-2222-4222-8222-222222222222",
                "type": "ClusterIP",
            },
            "gravitino": {
                "kind": "StatefulSet",
                "name": "gravitino-identity",
                "uid": "33333333-3333-4333-8333-333333333333",
                "image": "gda/gravitino:1.3.0-local-arm64",
                "service_account": "gravitino-identity",
                "service_account_automount_disabled": True,
                "ready_replicas": 1,
            },
            "postgresql": {
                "kind": "StatefulSet",
                "name": "gravitino-identity-postgresql",
                "uid": "44444444-4444-4444-8444-444444444444",
                "image": "postgres:16.10-bookworm",
                "service_account": "gravitino-identity-postgresql",
                "service_account_automount_disabled": True,
                "ready_replicas": 1,
                "ephemeral_data_volume": True,
            },
            "source_schema_sha256": identity.GRAVITINO_SCHEMA_SHA256,
        },
        "gravitino": _provider_result(),
        "runtime_checks": {
            "namespace_delete_completed": True,
            "namespace_absent": True,
            "provider_objects_retained": False,
            "all_port_forwards_stopped": True,
            "material_recorded": False,
            "kubernetes_service_account_used_for_provider_login": False,
        },
    }


def test_static_contract_is_valid_and_explicitly_local():
    report = identity.build_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["authentication"]["authenticator"] == "basic"
    assert report["authentication"]["simple_authenticator_trusted"] is False
    assert report["gravitino_authentication_verified"] is False
    assert report["protected_workload_identity_verified"] is False
    assert report["production_ready"] is False
    assert all(
        not Path(item["path"]).is_absolute() for item in report["files"].values()
    )


def test_profile_rejects_broad_privileges_and_claim_overreach(tmp_path):
    profile = yaml.safe_load(identity.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["scope"]["role_securable_objects"][1]["privileges"].append(
        {"name": "MODIFY_TABLE", "condition": "ALLOW"}
    )
    profile["claims"]["production_ready"] = True
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = identity.build_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    assert "profile is invalid" in "\n".join(report["errors"])


def test_profile_rejects_inline_sensitive_material(tmp_path):
    profile = yaml.safe_load(identity.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["identity"]["password"] = "must-not-enter-config"
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = identity.build_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False


def test_valid_evidence_proves_only_local_gravitino_basic_identity():
    evidence = identity.build_evidence(_observation())

    assert evidence["status"] == "local_gravitino_basic_identity_verified"
    assert evidence["local_gravitino_basic_identity_verified"] is True
    assert evidence["local_gravitino_minimum_privilege_verified"] is True
    assert evidence["local_gravitino_login_rotation_verified"] is True
    assert evidence["local_gravitino_revocation_verified"] is True
    assert evidence["gravitino_authentication_verified"] is False
    assert evidence["protected_workload_identity_verified"] is False
    assert evidence["oidc_verified"] is False
    assert evidence["production_ready"] is False
    assert identity.verify_evidence_integrity(evidence) == []


def test_evidence_blocks_broad_role_failed_denial_and_incomplete_cleanup():
    observation = _observation()
    observation["gravitino"]["role"]["securable_objects"][1][
        "privileges"
    ].append({"name": "MODIFY_TABLE", "condition": "ALLOW"})
    observation["gravitino"]["denied_probe"]["status"] = 200
    observation["runtime_checks"]["namespace_absent"] = False

    evidence = identity.build_evidence(observation)

    assert evidence["status"] == "blocked"
    rendered = "\n".join(evidence["errors"])
    assert "role exceeds" in rendered
    assert "catalog-create denial" in rendered
    assert "cleanup is incomplete" in rendered


def test_evidence_blocks_login_lifecycle_drift_and_sensitive_fields():
    observation = _observation()
    observation["gravitino"]["login_lifecycle"][
        "old_after_rotation_status"
    ] = 200
    observation["gravitino"]["api_token"] = "must-not-enter-evidence"

    evidence = identity.build_evidence(observation)

    assert evidence["status"] == "blocked"
    rendered = "\n".join(evidence["errors"])
    assert "sensitive material" in rendered
    assert "rotation or revocation" in rendered


def test_evidence_integrity_rejects_claim_and_observation_tampering():
    evidence = identity.build_evidence(_observation())
    tampered = deepcopy(evidence)
    tampered["gravitino_authentication_verified"] = True
    tampered["observation"]["gravitino"]["denied_probe"]["status"] = 200

    errors = identity.verify_evidence_integrity(tampered)

    assert any("content or fingerprint drifted" in error for error in errors)
    assert any("gravitino_authentication_verified" in error for error in errors)


class _GravitinoMock:
    def __init__(self) -> None:
        self.admin_name = "gda-identity-admin"
        self.admin_value = "admin-local-material"
        self.user_name = "gda-metadata-projection"
        self.user_value: str | None = None
        self.user_roles: list[str] = []
        self.role: dict | None = None
        self.table: dict | None = None

    @staticmethod
    def _response(status: int, payload: dict | None = None) -> httpx.Response:
        return (
            httpx.Response(status, json=payload)
            if payload is not None
            else httpx.Response(status)
        )

    @staticmethod
    def _login(request: httpx.Request) -> tuple[str, str] | None:
        value = request.headers.get("Authorization", "")
        if not value.startswith("Basic "):
            return None
        decoded = base64.b64decode(value.removeprefix("Basic ")).decode("utf-8")
        name, material = decoded.split(":", 1)
        return name, material

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/")
        method = request.method
        body = json.loads(request.content) if request.content else {}
        login = self._login(request)
        is_admin = login == (self.admin_name, self.admin_value)
        is_user = login == (self.user_name, self.user_value) and self.user_value is not None

        if path == "version" and method == "GET":
            if not (is_admin or is_user):
                return self._response(401, {"code": 1001})
            return self._response(200, {"code": 0, "version": {"version": "1.3.0"}})

        if not is_admin and not is_user:
            return self._response(401, {"code": 1001})

        if path == "metalakes" and method == "POST" and is_admin:
            return self._response(200, {"code": 0, "metalake": body})
        if path == "metalakes/gda_identity/catalogs" and method == "POST":
            if is_user:
                return self._response(403, {"code": 1002})
            return self._response(200, {"code": 0, "catalog": body})
        if (
            path == "metalakes/gda_identity/catalogs/lakehouse/schemas"
            and method == "POST"
            and is_admin
        ):
            return self._response(200, {"code": 0, "schema": body})
        if path == "idp/users" and method == "POST" and is_admin:
            self.user_value = body["password"]
            return self._response(
                200, {"code": 0, "user": {"name": body["user"]}}
            )
        if (
            path == "metalakes/gda_identity/users"
            and method == "POST"
            and is_admin
        ):
            return self._response(
                200, {"code": 0, "user": {"name": body["name"], "roles": []}}
            )
        if (
            path == "metalakes/gda_identity/roles"
            and method == "POST"
            and is_admin
        ):
            self.role = body
            return self._response(200, {"code": 0, "role": body})
        if (
            path
            == "metalakes/gda_identity/permissions/users/gda-metadata-projection/grant"
            and method == "PUT"
            and is_admin
        ):
            self.user_roles = body["roleNames"]
            return self._response(
                200,
                {
                    "code": 0,
                    "user": {"name": self.user_name, "roles": self.user_roles},
                },
            )
        if (
            path == "metalakes/gda_identity/roles/gda-table-projection"
            and method == "GET"
            and is_admin
        ):
            role = deepcopy(self.role)
            for securable_object in role["securableObjects"]:
                securable_object["type"] = securable_object["type"].lower()
                for privilege in securable_object["privileges"]:
                    privilege["name"] = privilege["name"].lower()
                    privilege["condition"] = privilege["condition"].lower()
            return self._response(200, {"code": 0, "role": role})
        if (
            path == "metalakes/gda_identity/catalogs/lakehouse/schemas/published/tables"
            and method == "POST"
            and is_user
        ):
            self.table = body
            return self._response(200, {"code": 0, "table": body})
        if (
            path
            == "metalakes/gda_identity/catalogs/lakehouse/schemas/published/tables/gda_identity_probe"
            and method == "GET"
            and is_user
        ):
            return self._response(200, {"code": 0, "table": self.table})
        if path == "idp/users/gda-metadata-projection" and method == "PUT" and is_admin:
            self.user_value = body["password"]
            return self._response(200, {"code": 0, "user": {"name": self.user_name}})
        if (
            path == "idp/users/gda-metadata-projection"
            and method == "DELETE"
            and is_admin
        ):
            self.user_value = None
            return self._response(200, {"code": 0, "dropped": True})
        if (
            path == "idp/users/gda-metadata-projection"
            and method == "GET"
            and is_admin
        ):
            return self._response(404, {"code": 1003})
        return self._response(404, {"code": 1003, "path": unquote(path)})


def test_http_rehearsal_enforces_basic_role_rotation_revocation_and_denial():
    profile = identity.load_profile()
    provider = _GravitinoMock()
    rehearsal = identity.GravitinoIdentityRehearsal(
        base_url="http://gravitino.test/api",
        admin_name=provider.admin_name,
        admin_material=SecretStr(provider.admin_value),
        transport=httpx.MockTransport(provider),
    )

    try:
        result = rehearsal.execute(
            profile,
            initial_material=SecretStr("initial-local-material"),
            rotated_material=SecretStr("rotated-local-material"),
        )
    finally:
        rehearsal.close()

    assert result["authentication"]["unregistered_principal_status"] == 401
    assert result["allowed_probe"]["create_status"] == 200
    assert result["denied_probe"]["status"] == 403
    assert result["login_lifecycle"]["old_after_rotation_status"] == 401
    assert result["login_lifecycle"]["rotated_authentication_status"] == 200
    assert result["login_lifecycle"]["after_revocation_status"] == 401
    assert result["login_lifecycle"]["idp_principal_absent"] is True
    rendered = json.dumps(result)
    assert "initial-local-material" not in rendered
    assert "rotated-local-material" not in rendered
    assert provider.admin_value not in rendered
