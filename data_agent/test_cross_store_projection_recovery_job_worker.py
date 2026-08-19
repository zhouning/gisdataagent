from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from data_agent import cross_store_projection_recovery_job_worker as worker_module


def test_worker_cli_wires_runtime_and_heartbeat(monkeypatch):
    calls = []
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    class Repository:
        def get_engine(self):
            return engine

    class Resolver:
        @classmethod
        def from_environment(cls, supplied_engine, *, rows_resolver=None):
            assert supplied_engine is engine
            assert rows_resolver is None
            return "provider-resolver"

    class CompensationResolver:
        @classmethod
        def from_environment(cls, *, authority):
            assert isinstance(authority, Repository)
            return "compensation-resolver"

    class Worker:
        def __init__(
            self,
            *,
            repository,
            provider_resolver,
            compensation_resolver,
        ):
            assert isinstance(repository, Repository)
            assert provider_resolver == "provider-resolver"
            assert compensation_resolver == "compensation-resolver"

        def run_once(self, tenant_id, worker_id, **kwargs):
            calls.append((tenant_id, worker_id, kwargs))
            return ()

    monkeypatch.setattr(worker_module, "PostgresProjectionRecoveryJobRepository", Repository)
    monkeypatch.setattr(worker_module, "ProjectionRecoveryProviderResolver", Resolver)
    monkeypatch.setattr(
        worker_module,
        "ProjectionRecoveryCompensationResolver",
        CompensationResolver,
    )
    monkeypatch.setattr(worker_module, "ProjectionRecoveryJobWorker", Worker)

    result = worker_module.main(
        [
            "--tenant-id",
            "chongqing-customer",
            "--worker-id",
            "worker:projection-recovery:test",
            "--limit",
            "2",
            "--lease-seconds",
            "90",
            "--heartbeat-seconds",
            "30",
            "--retry-delay-seconds",
            "12",
            "--poll-seconds",
            "1",
            "--once",
        ]
    )

    assert result == 0
    assert calls == [
        (
            "chongqing-customer",
            "worker:projection-recovery:test",
            {
                "limit": 2,
                "lease_seconds": 90,
                "retry_delay_seconds": 12,
                "heartbeat_interval_seconds": 30.0,
            },
        )
    ]


def test_worker_cli_rejects_heartbeat_not_shorter_than_lease():
    with pytest.raises(SystemExit, match="heartbeat-seconds"):
        worker_module.main(
            [
                "--tenant-id",
                "chongqing-customer",
                "--lease-seconds",
                "30",
                "--heartbeat-seconds",
                "30",
                "--once",
            ]
        )


def test_compose_profile_wires_projection_recovery_worker():
    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
    )
    service = compose["services"]["projection-recovery-worker"]

    assert service["profiles"] == ["projection-recovery"]
    assert service["command"] == [
        "python",
        "-m",
        "data_agent.cross_store_projection_recovery_job_worker",
    ]
    assert service["environment"]["POSTGRES_USER"] == "agent_user"
    assert (
        service["environment"]["GDA_PROJECTION_RECOVERY_ROWS_DIRECTORY"]
        == "/app/data_agent/uploads/projection-recovery-rows"
    )
    assert (
        service["environment"]["GDA_PROJECTION_RECOVERY_COMPENSATION_STRATEGY"]
        == "${GDA_PROJECTION_RECOVERY_COMPENSATION_STRATEGY:-disabled}"
    )
    assert "uploads:/app/data_agent/uploads" in service["volumes"]
    assert all("docker.sock" not in volume for volume in service["volumes"])
