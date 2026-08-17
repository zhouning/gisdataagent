import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote
from uuid import UUID

import httpx
import yaml
from pydantic import SecretStr

from data_agent import metadata_fabric_provider_identity as identity


POLICY_ID = UUID("11111111-1111-4111-8111-111111111111")
ROLE_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_ID = UUID("33333333-3333-4333-8333-333333333333")
BOT_ID = UUID("44444444-4444-4444-8444-444444444444")
TABLE_ID = UUID("55555555-5555-4555-8555-555555555555")


def _provider_result() -> dict:
    return {
        "provisioner": {
            "auth_mode": "local_basic_bootstrap_provisioner",
            "bootstrap_admin_used": True,
            "minimum_privilege": False,
        },
        "principal": {
            "id": str(USER_ID),
            "name": "gda-metadata-table-projection",
            "is_admin": False,
            "is_bot": True,
            "effective_roles": [
                "DefaultBotRole",
                "GdaMetadataTableProjectionRole",
            ],
            "provider_mandatory_default_role_inherited": True,
            "minimum_privilege_scope": (
                "dedicated_table_create_grant_with_provider_mandatory_default_role"
            ),
        },
        "policy": {
            "id": str(POLICY_ID),
            "name": "GdaMetadataTableProjectionPolicy",
            "enabled": True,
            "rules": [
                {
                    "name": "GdaMetadataTableCreate",
                    "description": "bounded",
                    "effect": "allow",
                    "operations": ["Create"],
                    "resources": ["table"],
                }
            ],
        },
        "role": {
            "id": str(ROLE_ID),
            "name": "GdaMetadataTableProjectionRole",
            "policy_ids": [str(POLICY_ID)],
            "mandatory_default_role": "DefaultBotRole",
        },
        "bot": {
            "id": str(BOT_ID),
            "name": "gda-metadata-table-projection-bot",
            "provider": "automation",
        },
        "allowed_probe": {
            "operation": "Create",
            "resource": "table",
            "create_status": 201,
            "read_status": 200,
            "entity_id": str(TABLE_ID),
            "fully_qualified_name": (
                "gda_lakehouse.land_use.published.gda_provider_identity_probe"
            ),
        },
        "denied_probe": {
            "operation": "Create",
            "resource": "policy",
            "status": 403,
        },
        "jwt_lifecycle": {
            "expiry": "OneHour",
            "initial_authentication_status": 200,
            "old_after_rotation_status": 401,
            "rotated_authentication_status": 200,
            "rotated_principal_matches": True,
            "after_revocation_status": 401,
            "sensitive_material_recorded": False,
        },
        "cleanup": {
            "jwt_revocation_attempted": True,
            "delete_statuses": {
                "table": 200,
                "bot": 200,
                "user": 404,
                "role": 200,
                "policy": 200,
            },
            "all_rehearsal_objects_absent": True,
            "absence": {
                "table": True,
                "bot": True,
                "user": True,
                "role": True,
                "policy": True,
                "unauthorized_policy": True,
            },
        },
    }


def _observation() -> dict:
    return {
        "schema": identity.OBSERVATION_SCHEMA,
        "observed_at": "2026-07-28T12:00:00+00:00",
        "contract": {
            "contract_fingerprint": "a" * 64,
            "local_static_contract_verified": True,
        },
        "runtime": {
            "context": identity.CONTEXT,
            "namespace": {"name": identity.NAMESPACE, "uid": "namespace-uid"},
            "service": {
                "name": "openmetadata",
                "uid": "service-uid",
                "type": "ClusterIP",
            },
            "workload": {
                "kind": "Deployment",
                "name": "openmetadata",
                "uid": "workload-uid",
                "image": "docker.getcollate.io/openmetadata/server:1.13.1",
                "service_account": "openmetadata",
                "service_account_automount_disabled": True,
                "ready_replicas": 1,
            },
        },
        "openmetadata": _provider_result(),
        "gravitino": {
            "version": "1.3.0",
            "authenticator": "simple",
            "access_control_enabled": False,
            "authentication_verified": False,
        },
        "runtime_checks": {
            "all_port_forwards_stopped": True,
            "provider_objects_retained": False,
            "sensitive_material_recorded": False,
            "kubernetes_service_account_used_for_provider_login": False,
        },
    }


def test_static_provider_identity_contract_is_valid_and_explicitly_local():
    report = identity.build_contract_report()

    assert report["local_static_contract_verified"] is True
    assert report["errors"] == []
    assert report["local_openmetadata_bounded_identity_verified"] is False
    assert report["provider_minimum_privilege_verified"] is False
    assert report["protected_workload_identity_verified"] is False
    assert report["gravitino_authentication_verified"] is False
    assert report["production_ready"] is False
    assert all(
        not Path(item["path"]).is_absolute() for item in report["files"].values()
    )


def test_profile_rejects_broad_policy_and_claim_overreach(tmp_path):
    profile = yaml.safe_load(identity.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["identity"]["allowed_rule"]["operations"] = ["Create", "EditAll"]
    profile["identity"]["allowed_rule"]["resources"] = ["All"]
    profile["claims"]["production_ready"] = True
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = identity.build_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False
    assert "profile is invalid" in "\n".join(report["errors"])


def test_profile_rejects_inline_sensitive_material(tmp_path):
    profile = yaml.safe_load(identity.DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    profile["providers"]["openmetadata"]["password"] = "must-not-enter-config"
    target = tmp_path / "profile.yaml"
    target.write_text(yaml.safe_dump(profile), encoding="utf-8")

    report = identity.build_contract_report(profile_path=target)

    assert report["local_static_contract_verified"] is False


def test_valid_evidence_proves_only_bounded_local_openmetadata_identity():
    evidence = identity.build_evidence(_observation())

    assert evidence["status"] == "local_openmetadata_bounded_identity_verified"
    assert evidence["local_openmetadata_bounded_identity_verified"] is True
    assert evidence["local_openmetadata_minimum_privilege_verified"] is True
    assert evidence["local_openmetadata_jwt_rotation_verified"] is True
    assert evidence["local_openmetadata_jwt_revocation_verified"] is True
    assert evidence["provider_minimum_privilege_verified"] is False
    assert evidence["protected_workload_identity_verified"] is False
    assert evidence["gravitino_authentication_verified"] is False
    assert evidence["production_ready"] is False
    assert identity.verify_evidence_integrity(evidence) == []


def test_evidence_blocks_broad_role_failed_denial_and_incomplete_cleanup():
    observation = _observation()
    observation["openmetadata"]["principal"]["effective_roles"].append(
        "IngestionBotRole"
    )
    observation["openmetadata"]["policy"]["rules"][0]["operations"].append(
        "EditAll"
    )
    observation["openmetadata"]["denied_probe"]["status"] = 200
    observation["openmetadata"]["cleanup"][
        "all_rehearsal_objects_absent"
    ] = False

    evidence = identity.build_evidence(observation)

    assert evidence["status"] == "blocked"
    rendered = "\n".join(evidence["errors"])
    assert "principal or effective roles" in rendered
    assert "broader than table Create" in rendered
    assert "policy-create denial" in rendered
    assert "cleanup is incomplete" in rendered


def test_evidence_blocks_jwt_lifecycle_drift_and_sensitive_fields():
    observation = _observation()
    observation["openmetadata"]["jwt_lifecycle"][
        "old_after_rotation_status"
    ] = 200
    observation["openmetadata"]["api_token"] = "must-not-enter-evidence"

    evidence = identity.build_evidence(observation)

    assert evidence["status"] == "blocked"
    rendered = "\n".join(evidence["errors"])
    assert "sensitive material" in rendered
    assert "rotation or revocation" in rendered


def test_evidence_integrity_rejects_claim_and_observation_tampering():
    evidence = identity.build_evidence(_observation())
    tampered = deepcopy(evidence)
    tampered["provider_minimum_privilege_verified"] = True
    tampered["observation"]["openmetadata"]["denied_probe"]["status"] = 200
    tampered["observation"]["openmetadata"]["role"]["policy_ids"] = [
        str(BOT_ID)
    ]

    errors = identity.verify_evidence_integrity(tampered)

    assert any("content or fingerprint drifted" in error for error in errors)
    assert any("provider_minimum_privilege_verified" in error for error in errors)


class _OpenMetadataMock:
    def __init__(self) -> None:
        self.current_jwt = "local-jwt-one"
        self.revoked = False
        self.entities: dict[str, dict[str, dict]] = {
            name: {} for name in ("policies", "roles", "users", "bots", "tables")
        }
        self.ids = {
            "policies": POLICY_ID,
            "roles": ROLE_ID,
            "users": USER_ID,
            "bots": BOT_ID,
            "tables": TABLE_ID,
        }

    @staticmethod
    def _response(status: int, payload: dict | None = None) -> httpx.Response:
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1/")
        method = request.method
        auth = request.headers.get("Authorization", "")
        body = json.loads(request.content) if request.content else {}

        if path == "users/login" and method == "POST":
            return self._response(200, {"accessToken": "bootstrap-access"})
        is_admin = auth == "Bearer bootstrap-access"
        is_bot = auth == f"Bearer {self.current_jwt}" and not self.revoked

        if path == "users/loggedInUser" and method == "GET":
            if not is_bot:
                return self._response(401, {"code": 401})
            return self._response(
                200,
                {
                    "id": str(USER_ID),
                    "name": "gda-metadata-table-projection",
                    "isAdmin": False,
                    "isBot": True,
                    "roles": [
                        {"id": "default", "name": "DefaultBotRole"},
                        {"id": str(ROLE_ID), "name": "GdaMetadataTableProjectionRole"},
                    ],
                },
            )
        if path == f"users/auth-mechanism/{USER_ID}" and method == "GET" and is_admin:
            return self._response(
                200,
                {
                    "authType": "JWT",
                    "config": {
                        "JWTToken": self.current_jwt,
                        "JWTTokenExpiry": "OneHour",
                    },
                },
            )
        if path == f"users/generateToken/{USER_ID}" and method == "PUT" and is_admin:
            self.current_jwt = "local-jwt-two"
            self.revoked = False
            return self._response(
                200,
                {"JWTToken": self.current_jwt, "JWTTokenExpiry": "OneHour"},
            )
        if path == "users/revokeToken" and method == "PUT" and is_admin:
            self.revoked = True
            return self._response(200, {"JWTTokenExpiry": "OneHour"})

        if "/name/" in path and method == "GET" and (is_admin or is_bot):
            collection, encoded_name = path.split("/name/", 1)
            entity = self.entities.get(collection, {}).get(unquote(encoded_name))
            return self._response(200, entity) if entity else self._response(404, {"code": 404})

        if path == "policies" and method == "PUT" and is_bot:
            return self._response(403, {"code": 403})
        if path == "tables" and method == "PUT" and is_bot:
            entity = {
                "id": str(TABLE_ID),
                "name": body["name"],
                "fullyQualifiedName": (
                    f"{body['databaseSchema']}.{body['name']}"
                ),
                "version": 0.1,
            }
            self.entities["tables"][entity["fullyQualifiedName"]] = entity
            return self._response(201, entity)

        if method == "PUT" and path in self.entities and is_admin:
            entity_id = self.ids[path]
            entity = {**body, "id": str(entity_id)}
            if path == "users":
                entity["roles"] = [
                    {"id": "default", "name": "DefaultBotRole"},
                    {"id": str(ROLE_ID), "name": "GdaMetadataTableProjectionRole"},
                ]
            if path == "bots":
                entity["botUser"] = {
                    "id": str(USER_ID),
                    "name": "gda-metadata-table-projection",
                }
            self.entities[path][body["name"]] = entity
            return self._response(201, entity)

        if method == "DELETE" and is_admin:
            collection, entity_id = path.split("/", 1)
            for name, entity in list(self.entities.get(collection, {}).items()):
                if entity.get("id") == entity_id:
                    del self.entities[collection][name]
                    return self._response(200, {})
            return self._response(404, {"code": 404})
        return self._response(404, {"code": 404})


def test_http_rehearsal_uses_bounded_identity_rotates_revokes_and_cleans_up():
    profile = identity.load_profile()
    provider = _OpenMetadataMock()
    rehearsal = identity.OpenMetadataIdentityRehearsal(
        base_url="http://openmetadata.test/api/v1",
        username="admin@open-metadata.org",
        password=SecretStr("local-bootstrap"),
        transport=httpx.MockTransport(provider),
    )

    try:
        result = rehearsal.execute(profile)
    finally:
        rehearsal.close()

    assert result["allowed_probe"]["create_status"] == 201
    assert result["denied_probe"]["status"] == 403
    assert result["jwt_lifecycle"]["old_after_rotation_status"] == 401
    assert result["jwt_lifecycle"]["rotated_authentication_status"] == 200
    assert result["jwt_lifecycle"]["after_revocation_status"] == 401
    assert result["cleanup"]["all_rehearsal_objects_absent"] is True
    rendered = json.dumps(result)
    assert "local-jwt-one" not in rendered
    assert "local-jwt-two" not in rendered
    assert "bootstrap-access" not in rendered
