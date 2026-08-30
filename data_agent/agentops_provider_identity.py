"""Deterministic provider identity helpers shared by AgentOps boundaries."""

from __future__ import annotations

import re

from .agentops_temporal_contracts import TemporalActivityRequest

FLINK_PROVIDER_REF = "provider:flink"
FLINK_ICEBERG_OPERATION = "flink.iceberg.reconciliation.v1"
FLINK_JOB_RECEIPT_PREFIX = "flink://job/"

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def derive_specialist_provider_receipt_ref(request: TemporalActivityRequest) -> str:
    """Return the provider-native receipt reference when its identity is bound.

    Unknown or incomplete provider bindings retain the historical generic receipt
    reference; the provider adapter remains responsible for rejecting an invalid
    binding before making a side effect.
    """

    spec = request.provider_spec
    if spec is not None and (
        spec.provider_ref == FLINK_PROVIDER_REF
        and spec.operation_ref == FLINK_ICEBERG_OPERATION
    ):
        raw_job_id = (spec.parameters or {}).get("job_id")
        job_id = raw_job_id.strip() if isinstance(raw_job_id, str) else ""
        if _JOB_ID_RE.fullmatch(job_id) is not None:
            return f"{FLINK_JOB_RECEIPT_PREFIX}{job_id}"
    return f"provider://specialist/{request.activity_id}/{request.attempt_no}"


__all__ = [
    "FLINK_ICEBERG_OPERATION",
    "FLINK_JOB_RECEIPT_PREFIX",
    "FLINK_PROVIDER_REF",
    "derive_specialist_provider_receipt_ref",
]
