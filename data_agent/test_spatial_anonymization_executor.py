from uuid import UUID

from starlette.testclient import TestClient

from data_agent.spatial_anonymization_executor import (
    SpatialAnonymizationExecutor,
    SpatialAnonymizationExecutorConfig,
    create_app,
)
from data_agent.spatial_anonymization_worker import SpatialAnonymizationWorkerResult

RUN_ID = UUID("71000000-0000-4000-8000-000000000001")
ATTEMPT_ID = UUID("71000000-0000-4000-8000-000000000002")
REQUEST_VERSION_ID = UUID("71000000-0000-4000-8000-000000000003")
OUTCOME_ID = UUID("71000000-0000-4000-8000-000000000004")


class FakeWorker:
    def __init__(self):
        self.calls = []

    def execute(self, tenant_id, run_id):
        self.calls.append((tenant_id, run_id))
        return SpatialAnonymizationWorkerResult(
            tenant_id=tenant_id,
            run_id=run_id,
            attempt_id=ATTEMPT_ID,
            request_version_id=REQUEST_VERSION_ID,
            status="completed",
            output_table="public.restricted_parcels_l3",
            output_row_count=4,
            receipt_sha256="a" * 64,
            outcome_event_id=OUTCOME_ID,
            recovered_from_receipt=False,
        )


def _client(tmp_path):
    token = tmp_path / "executor-token"
    token.write_text("certification-token", encoding="utf-8")
    token.chmod(0o600)
    worker = FakeWorker()
    service = SpatialAnonymizationExecutor(
        SpatialAnonymizationExecutorConfig(token_file=token.resolve()),
        worker=worker,
    )
    return TestClient(create_app(service)), worker


def test_executor_requires_token_and_accepts_only_run_reference(tmp_path):
    client, worker = _client(tmp_path)
    payload = {"tenant_id": "tenant-a", "run_id": str(RUN_ID)}

    assert client.post(
        "/v1/execute/spatial-anonymization-run", json=payload
    ).status_code == 401
    response = client.post(
        "/v1/execute/spatial-anonymization-run",
        json=payload,
        headers={"Authorization": "Bearer certification-token"},
    )

    assert response.status_code == 200
    assert response.json()["schema"] == "gda.spatial_anonymization_executor.v1"
    assert response.json()["output_table"] == "public.restricted_parcels_l3"
    assert worker.calls == [("tenant-a", RUN_ID)]


def test_executor_rejects_provider_supplied_business_parameters(tmp_path):
    client, worker = _client(tmp_path)

    response = client.post(
        "/v1/execute/spatial-anonymization-run",
        json={
            "tenant_id": "tenant-a",
            "run_id": str(RUN_ID),
            "source_table": "attacker_selected_table",
        },
        headers={"Authorization": "Bearer certification-token"},
    )

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_execution_request"}
    assert worker.calls == []
