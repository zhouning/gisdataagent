from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_container_dependencies_ship_temporal_sdk() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "temporalio==1.32.0" in requirements


def test_container_copies_agentops_migrations_and_worker() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY data_agent/ /app/data_agent/" in dockerfile
    migrations = (
        "240_agentops_temporal_checkpoint_authority.sql",
        "241_agentops_temporal_reconciler_fencing.sql",
        "242_agentops_temporal_start_target_authority.sql",
        "246_agentops_specialist_operation_receipt_authority.sql",
        "247_agentops_specialist_operation_uncertainty.sql",
        "248_agentops_specialist_retry_budget_authority.sql",
    )
    for migration in migrations:
        assert (ROOT / "data_agent" / "migrations" / migration).exists()


def test_discovery_deployment_runs_image_contract_before_polling() -> None:
    manifest = (
        ROOT / "k8s" / "optional" / "temporal-agentops-sandbox" / "discovery-worker.yaml"
    ).read_text(encoding="utf-8")
    guard = "python -m data_agent.agentops_temporal_reconciler_worker image-contract;"
    worker = "exec python -m data_agent.agentops_temporal_reconciler_worker --discover"
    assert guard in manifest
    assert manifest.index(guard) < manifest.index(worker)
