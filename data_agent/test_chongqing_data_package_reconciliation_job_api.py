from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import (
    CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_CANCEL,
    CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_GET,
    CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_SUBMIT,
)
from data_agent.chongqing_data_package_reconciliation_job import (
    ChongqingDataPackageReconciliationJob,
)
from data_agent.chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
)
from data_agent.chongqing_entity_link_baseline import (
    build_chongqing_entity_link_baseline,
)

TENANT = "chongqing-customer"
ACTOR = "human:operator-1"
BASELINE = build_chongqing_entity_link_baseline(tenant_id=TENANT)
EFFECTIVE_AT = BASELINE.link_assertion_drafts[0].valid_from + timedelta(days=1)


def _request(*, body: dict, path_params: dict | None = None, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {}
    request.path_params = path_params or {}
    request.query_params = {}
    return request


def _user():
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": "platform_operator", "tenant_id": TENANT},
    )


def _submission() -> ChongqingDataPackageReconciliationRequest:
    return ChongqingDataPackageReconciliationRequest(
        tenant_id=TENANT,
        previous_baseline=BASELINE,
        desired_baseline=BASELINE,
        effective_at=EFFECTIVE_AT,
        evaluated_at=EFFECTIVE_AT + timedelta(hours=1),
        idempotency_key="cq.async.api.job-001",
        recorded_by=ACTOR,
    )


def _job(request: ChongqingDataPackageReconciliationRequest):
    now = datetime.now(UTC)
    return ChongqingDataPackageReconciliationJob(
        tenant_id=TENANT,
        job_id=uuid4(),
        idempotency_key=request.idempotency_key,
        request_sha256=request.request_sha256,
        status="queued",
        phase="queued",
        phase_detail="queued",
        phase_completed=0,
        phase_total=1,
        progress_percent=0,
        attempt_count=0,
        max_attempts=5,
        submitted_by=ACTOR,
        submitted_at=now,
        updated_at=now,
    )


def test_async_job_routes_share_capability_guards_and_status_contract():
    submission = _submission()
    job = _job(submission)
    headers = {
        "X-GDA-Capability-Fingerprint": CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_SUBMIT.fingerprint,
        "idempotency-key": submission.idempotency_key,
    }
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "submit_chongqing_data_package_reconciliation_job", return_value=job),
    ):
        response = asyncio.run(
            routes.submit_entity_data_package_reconciliation_job(
                _request(body=submission.model_dump(mode="json"), headers=headers)
            )
        )
    assert response.status_code == 202
    assert json.loads(response.body)["data"]["status"] == "queued"

    get_headers = {
        "X-GDA-Capability-Fingerprint": CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_GET.fingerprint,
    }
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "get_chongqing_data_package_reconciliation_job", return_value=job),
    ):
        response = asyncio.run(
            routes.get_entity_data_package_reconciliation_job(
                _request(path_params={"job_id": str(job.job_id)}, headers=get_headers, body={})
            )
        )
    assert response.status_code == 200
    assert json.loads(response.body)["data"]["job_id"] == str(job.job_id)

    cancel_headers = {
        "X-GDA-Capability-Fingerprint": CHONGQING_DATA_PACKAGE_RECONCILIATION_JOB_CANCEL.fingerprint,
    }
    cancel_job = job.model_copy(
        update={
            "status": "cancelled",
            "phase": "cancelled",
            "phase_detail": "cancelled_before_start",
            "completed_at": datetime.now(UTC),
            "cancel_requested_by": ACTOR,
            "cancel_reason": "operator requested stop",
            "cancel_requested_at": datetime.now(UTC),
        }
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "cancel_chongqing_data_package_reconciliation_job", return_value=cancel_job),
    ):
        response = asyncio.run(
            routes.cancel_entity_data_package_reconciliation_job(
                _request(
                    body={"reason": "operator requested stop"},
                    path_params={"job_id": str(job.job_id)},
                    headers=cancel_headers,
                )
            )
        )
    assert response.status_code == 200
    assert json.loads(response.body)["data"]["status"] == "cancelled"


def test_async_submit_rejects_capability_drift_before_parsing():
    response = asyncio.run(
        routes.submit_entity_data_package_reconciliation_job(
            _request(
                body={},
                headers={"X-GDA-Capability-Fingerprint": "0" * 64},
            )
        )
    )
    assert response.status_code == 401

