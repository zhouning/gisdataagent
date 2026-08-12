from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.migration_runner import catalog_fingerprint, discover_migrations
from data_agent.platform_runtime.deployment_profile import (
    DeploymentProfile,
    load_deployment_profile,
)
from data_agent.platform_runtime.runtime_probe import (
    CommandResult,
    DeploymentProfileVerifier,
    HttpResult,
    VerificationCheck,
    canonical_compose_fingerprint,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = REPO_ROOT / "config" / "deployment_profiles"


@pytest.mark.parametrize("profile_name", ["main-compose-dev.json", "gemma4-demo-dev.json"])
def test_versioned_profiles_are_strict_and_non_secret(profile_name: str) -> None:
    profile_path = PROFILE_DIR / profile_name
    profile = load_deployment_profile(profile_path)

    assert profile.environment == "dev"
    migrations = discover_migrations()
    assert profile.migrations.count == len(migrations)
    assert profile.migrations.fingerprint == catalog_fingerprint(migrations)
    assert profile.governance.status == "in_progress"
    raw = profile_path.read_text(encoding="utf-8")
    assert "/Users/" not in raw
    assert "password" not in raw.lower()
    assert "secret" not in raw.lower()


def test_profile_rejects_unknown_fields_and_absolute_compose_paths() -> None:
    payload = json.loads(
        (PROFILE_DIR / "main-compose-dev.json").read_text(encoding="utf-8")
    )
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="unexpected"):
        DeploymentProfile.model_validate(payload)

    payload.pop("unexpected")
    payload["compose"]["files"] = ["/private/repository/docker-compose.yml"]
    with pytest.raises(ValidationError, match="repository-relative"):
        DeploymentProfile.model_validate(payload)


def test_compose_fingerprint_redacts_secrets_and_host_paths() -> None:
    first = {
        "name": "gisdataagent",
        "services": {
            "app": {
                "image": "example:v1",
                "environment": {
                    "POSTGRES_PASSWORD": "first-secret",
                    "DATABASE_URL": "postgresql://user:first@db:5432/gis",
                },
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/Users/first/private-data",
                        "target": "/app/data",
                    }
                ],
            }
        },
    }
    second = deepcopy(first)
    second["services"]["app"]["environment"]["POSTGRES_PASSWORD"] = "second-secret"
    second["services"]["app"]["environment"]["DATABASE_URL"] = (
        "postgresql://other:second@db:5432/gis"
    )
    second["services"]["app"]["volumes"][0]["source"] = "/private/other-data"

    first_hash = canonical_compose_fingerprint(first, REPO_ROOT)
    assert first_hash == canonical_compose_fingerprint(second, REPO_ROOT)

    second["services"]["app"]["image"] = "example:v2"
    assert first_hash != canonical_compose_fingerprint(second, REPO_ROOT)


@pytest.mark.parametrize("contaminated", [False, True])
def test_runtime_verifier_detects_profile_contamination(contaminated: bool) -> None:
    migrations = discover_migrations()
    migration_hash = catalog_fingerprint(migrations)
    compose_model = {
        "name": "gisdataagent",
        "networks": {"agent-net": {"name": "gisdataagent_agent-net"}},
        "services": {
            "app": {"networks": {"agent-net": None}},
            "redis": {
                "networks": {"agent-net": None},
                "volumes": [
                    {"type": "volume", "source": "redis-data", "target": "/data"}
                ],
            },
        },
        "volumes": {"redis-data": {"name": "gisdataagent_redis-data"}},
    }
    profile = DeploymentProfile.model_validate({
        "schema": "gis-data-agent.deployment-profile.v1",
        "profile_id": "unit-compose-dev",
        "environment": "dev",
        "deployment_type": "compose",
        "llm_mode": "disabled",
        "base_url": "http://127.0.0.1:8000",
        "compose": {
            "project_name": "gisdataagent",
            "files": ["docker-compose.yml"],
            "network": "agent-net",
            "baseline_probe_service": "app",
            "config_sha256": canonical_compose_fingerprint(compose_model, REPO_ROOT),
            "services": [
                {
                    "name": "app",
                    "source_file": "docker-compose.yml",
                    "runtime": "required",
                },
                {
                    "name": "redis",
                    "source_file": "docker-compose.yml",
                    "runtime": "required",
                    "health_required": True,
                },
            ],
            "volumes": [
                {"service": "redis", "target": "/data", "logical_name": "redis-data"}
            ],
        },
        "migrations": {"count": len(migrations), "fingerprint": migration_hash},
        "released_standard": {
            "doc_code": "STANDARD",
            "version_label": "v1",
            "element_count": 1,
            "elements_sha256": "b" * 64,
        },
        "capabilities": [
            {
                "capability": "redis",
                "configured_service": "redis",
                "internal_fact": "redis",
                "runtime": "required",
            },
            {
                "capability": "gda_mvt",
                "configured_route": "/api/tiles/{layer_id}/{z:int}/{x:int}/{y:int}.pbf",
                "runtime": "http_probe",
            },
        ],
        "http_probes": [
            {
                "capability": "gda_mvt",
                "path": "/api/tiles/runtime-probe/0/0/0.pbf",
                "expected_status": [401],
                "content_type_prefix": "application/json",
            }
        ],
        "governance": {
            "platform_owner": "data-platform",
            "status": "in_progress",
            "promotion_blockers": ["owner"],
        },
    })

    correct_labels = {
        "com.docker.compose.project.config_files": str(REPO_ROOT / "docker-compose.yml")
    }
    redis_labels = dict(correct_labels)
    redis_network = "gisdataagent_agent-net"
    redis_volume = "gisdataagent_redis-data"
    if contaminated:
        redis_labels["com.docker.compose.project.config_files"] = str(
            REPO_ROOT / "docker-compose.gemma4-demo.yml"
        )
        redis_network = "gisdataagent_gemma4-demo-net"
        redis_volume = "gisdataagent_gemma4_demo_redis"

    internal_facts = {
        "schema": "gis-data-agent.internal-runtime-facts.v1",
        "profile_id": "unit-compose-dev",
        "migration": {
            "status": "in_sync",
            "catalog_count": len(migrations),
            "applied_count": len(migrations),
            "catalog_fingerprint": migration_hash,
            "database_fingerprint": migration_hash,
        },
        "released_standard": {
            "doc_code": "STANDARD",
            "version_label": "v1",
            "status": "released",
            "element_count": 1,
            "elements_sha256": "b" * 64,
        },
        "dependencies": {"redis": {"status": "ok", "version": "7.0"}},
        "route_paths": ["/api/tiles/{layer_id}/{z:int}/{x:int}/{y:int}.pbf"],
    }

    def command_runner(command, _cwd) -> CommandResult:
        if command[-3:] == ["config", "--format", "json"]:
            return CommandResult(0, json.dumps(compose_model))
        if command[-4:] == ["ps", "--all", "--format", "json"]:
            rows = [
                {"Service": "app", "ID": "app-id", "State": "running", "ExitCode": 0},
                {
                    "Service": "redis",
                    "ID": "redis-id",
                    "State": "running",
                    "ExitCode": 0,
                    "Health": "healthy",
                },
            ]
            return CommandResult(0, "\n".join(json.dumps(row) for row in rows))
        if command[:2] == ["docker", "inspect"]:
            container_id = command[-1]
            labels = correct_labels if container_id == "app-id" else redis_labels
            network = "gisdataagent_agent-net" if container_id == "app-id" else redis_network
            mounts = [] if container_id == "app-id" else [{
                "Type": "volume",
                "Name": redis_volume,
                "Destination": "/data",
                "Source": "/var/lib/docker/volumes/private/_data",
            }]
            return CommandResult(0, json.dumps([{
                "Config": {"Labels": labels, "Env": ["PASSWORD=must-not-leak"]},
                "NetworkSettings": {"Networks": {network: {}}},
                "Mounts": mounts,
            }]))
        if command[:2] == ["docker", "exec"]:
            return CommandResult(0, json.dumps(internal_facts))
        raise AssertionError(f"unexpected command shape: {command[0:2]}")

    verifier = DeploymentProfileVerifier(
        profile=profile,
        profile_path=PROFILE_DIR / "main-compose-dev.json",
        repo_root=REPO_ROOT,
        command_runner=command_runner,
        http_getter=lambda _url: HttpResult(401, "application/json", b'{"error":"Unauthorized"}'),
    )
    report = verifier.verify()

    assert report.technical_pass is not contaminated
    assert report.profile_contamination is contaminated
    assert report.capability_status["redis"] == (
        "runtime_failed" if contaminated else "runtime"
    )
    assert report.capability_status["gda_mvt"] == "runtime"
    assert report.promotion_ready is False
    rendered = json.dumps(report.to_dict(), sort_keys=True)
    assert "must-not-leak" not in rendered
    assert "/var/lib/docker" not in rendered
    assert str(REPO_ROOT) not in rendered


def test_static_verification_can_never_authorize_promotion() -> None:
    migrations = discover_migrations()
    compose_model = {
        "name": "static-profile",
        "networks": {"agent-net": {"name": "static-profile_agent-net"}},
        "services": {"app": {"networks": {"agent-net": None}}},
    }
    profile = DeploymentProfile.model_validate({
        "schema": "gis-data-agent.deployment-profile.v1",
        "profile_id": "static-profile",
        "environment": "dev",
        "deployment_type": "compose",
        "llm_mode": "disabled",
        "base_url": "http://127.0.0.1:8000",
        "compose": {
            "project_name": "static-profile",
            "files": ["docker-compose.yml"],
            "network": "agent-net",
            "baseline_probe_service": "app",
            "config_sha256": canonical_compose_fingerprint(compose_model, REPO_ROOT),
            "services": [{
                "name": "app",
                "source_file": "docker-compose.yml",
                "runtime": "required",
            }],
            "volumes": [],
        },
        "migrations": {
            "count": len(migrations),
            "fingerprint": catalog_fingerprint(migrations),
        },
        "released_standard": {
            "doc_code": "STANDARD",
            "version_label": "v1",
            "element_count": 1,
            "elements_sha256": "b" * 64,
        },
        "capabilities": [],
        "http_probes": [],
        "governance": {
            "platform_owner": "data-platform",
            "status": "verified",
            "promotion_blockers": [],
        },
    })

    def command_runner(command, _cwd) -> CommandResult:
        assert command[-3:] == ["config", "--format", "json"]
        return CommandResult(0, json.dumps(compose_model))

    report = DeploymentProfileVerifier(
        profile=profile,
        profile_path=PROFILE_DIR / "main-compose-dev.json",
        repo_root=REPO_ROOT,
        command_runner=command_runner,
    ).verify(include_runtime=False)

    assert report.technical_pass is True
    assert report.promotion_ready is False
    assert report.promotion_blockers == ("runtime_verification",)


def test_capability_status_requires_all_runtime_contract_checks() -> None:
    profile = load_deployment_profile(PROFILE_DIR / "main-compose-dev.json")
    verifier = DeploymentProfileVerifier(
        profile=profile,
        profile_path=PROFILE_DIR / "main-compose-dev.json",
        repo_root=REPO_ROOT,
    )
    output: dict[str, str] = {}

    def check(check_id: str, passed: bool) -> VerificationCheck:
        return VerificationCheck(
            check_id=check_id,
            status="pass" if passed else "fail",
            expected=None,
            actual=None,
        )

    verifier._derive_capability_status(
        checks=[
            check("runtime.http.liveness", True),
            check("runtime.http_content_type.liveness", False),
            check("runtime.http_json_status.liveness", True),
            check("compose.service.redis", True),
            check("runtime.service.redis", True),
            check("runtime.health.redis", True),
            check("runtime.source_file.redis", True),
            check("runtime.network.redis", False),
            check("runtime.volume.redis.data", True),
            check("runtime.internal.redis.status", True),
        ],
        runtime_services={"redis": {}},
        include_runtime=True,
        output=output,
    )

    assert output["liveness"] == "runtime_failed"
    assert output["redis"] == "runtime_failed"
