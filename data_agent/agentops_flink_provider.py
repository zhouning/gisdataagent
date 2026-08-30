"""Flink REST provider-native cancellation adapter for AgentOps activities.

The adapter only owns the Flink cancellation transport.  Temporal history and the
specialist receipt authority remain separate sources of truth: an HTTP 202 means
that Flink accepted the request, while only a later ``CANCELED`` job state can
confirm provider cancellation.
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager

import httpx

from .agentops_provider_identity import (
    FLINK_ICEBERG_OPERATION,
    FLINK_JOB_RECEIPT_PREFIX,
    FLINK_PROVIDER_REF,
)
from .agentops_specialist_providers import (
    SpecialistProviderCancellationAdapter,
    SpecialistProviderCancellationObservation,
    SpecialistProviderCancellationStatus,
    SpecialistProviderError,
    SpecialistUncertaintyType,
    _provider_cancellation_observation,
)
from .agentops_temporal_contracts import TemporalActivityRequest

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class FlinkProviderCancellationAdapter(
    SpecialistProviderCancellationAdapter, AbstractContextManager
):
    """Call Flink's native REST cancellation endpoint and observe its state.

    A provider execution spec must bind ``provider:flink``,
    ``flink.iceberg.reconciliation.v1`` and a lowercase 32-hex ``job_id`` in
    ``parameters``.  The receipt reference is deliberately required to be
    ``flink://job/<job_id>`` so a cancellation cannot be redirected to another
    Flink job by a stale worker.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise SpecialistProviderError("Flink REST base URL is required")
        try:
            parsed = httpx.URL(base_url.strip())
        except Exception as exc:
            raise SpecialistProviderError("Flink REST base URL is invalid") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.host:
            raise SpecialistProviderError("Flink REST base URL must be absolute HTTP(S)")
        if parsed.username or parsed.password:
            raise SpecialistProviderError("Flink REST credentials cannot be embedded in URL")
        if parsed.query or parsed.fragment:
            raise SpecialistProviderError("Flink REST base URL cannot contain query or fragment")
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise SpecialistProviderError("Flink REST timeout must be between 0 and 120 seconds")
        self.base_url = str(parsed).rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "gis-data-agent-agentops-flink/1",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _identity(
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> tuple[str, str]:
        spec = request.provider_spec
        if spec is None:
            raise SpecialistProviderError("Flink cancellation requires a provider binding")
        if spec.provider_ref != FLINK_PROVIDER_REF:
            raise SpecialistProviderError("Flink cancellation provider binding differs")
        if spec.operation_ref != FLINK_ICEBERG_OPERATION:
            raise SpecialistProviderError("Flink cancellation operation binding differs")
        raw_job_id = (spec.parameters or {}).get("job_id")
        job_id = raw_job_id.strip() if isinstance(raw_job_id, str) else ""
        if _JOB_ID_RE.fullmatch(job_id) is None:
            raise SpecialistProviderError("Flink provider spec requires a lowercase 32-hex job_id")
        expected_receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{job_id}"
        if provider_receipt_ref != expected_receipt_ref:
            raise SpecialistProviderError("Flink provider receipt is bound to a different job")
        if not isinstance(operation_ref, str) or not operation_ref.strip():
            raise SpecialistProviderError("Flink operation reference is required")
        return job_id, expected_receipt_ref

    def _url(self, job_id: str) -> str:
        return f"{self.base_url}/jobs/{job_id}"

    @staticmethod
    def _observation(
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
        status: SpecialistProviderCancellationStatus,
        failure_type: str | None = None,
        uncertainty_type: SpecialistUncertaintyType | None = None,
    ) -> SpecialistProviderCancellationObservation:
        return _provider_cancellation_observation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=provider_receipt_ref,
            status=status,
            failure_type=failure_type,
            uncertainty_type=uncertainty_type,
        )

    def observe_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation:
        job_id, receipt_ref = self._identity(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=provider_receipt_ref,
        )
        try:
            response = self._client.get(self._url(job_id))
        except (httpx.TimeoutException, httpx.TransportError):
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_CANCELLATION_TRANSPORT_UNAVAILABLE,
            )
        if response.status_code == 404:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_JOB_NOT_FOUND,
            )
        if response.status_code in {401, 403}:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_CANCELLATION_PERMISSION_DENIED,
            )
        if not 200 <= response.status_code < 300:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_CANCELLATION_REJECTED,
            )
        try:
            payload = response.json()
        except ValueError:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_RESPONSE_INVALID,
            )
        state = payload.get("state") if isinstance(payload, dict) else None
        normalized_state = state.strip().upper() if isinstance(state, str) else ""
        if normalized_state == "CANCELED":
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.CONFIRMED,
                failure_type="FlinkJobCancelled",
            )
        if normalized_state in {"CANCELING", "CANCELLING"}:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.ACCEPTED,
                uncertainty_type=SpecialistUncertaintyType.PROVIDER_CANCELLATION_ACCEPTED,
            )
        return self._observation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=receipt_ref,
            status=SpecialistProviderCancellationStatus.UNKNOWN,
            uncertainty_type=(
                SpecialistUncertaintyType.FLINK_RESPONSE_INVALID
                if not isinstance(payload, dict) or not normalized_state
                else SpecialistUncertaintyType.FLINK_JOB_NOT_CANCELLED
            ),
        )

    def request_cancellation(
        self,
        request: TemporalActivityRequest,
        *,
        operation_ref: str,
        provider_receipt_ref: str,
    ) -> SpecialistProviderCancellationObservation:
        job_id, receipt_ref = self._identity(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=provider_receipt_ref,
        )
        observed = self.observe_cancellation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=receipt_ref,
        )
        if observed.status is SpecialistProviderCancellationStatus.CONFIRMED:
            return observed
        try:
            response = self._client.patch(self._url(job_id), params={"mode": "cancel"})
        except (httpx.TimeoutException, httpx.TransportError):
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_CANCELLATION_TRANSPORT_UNAVAILABLE,
            )
        if response.status_code in {401, 403}:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_CANCELLATION_PERMISSION_DENIED,
            )
        if response.status_code == 404:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_JOB_NOT_FOUND,
            )
        if response.status_code not in {200, 202, 204}:
            return self._observation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=receipt_ref,
                status=SpecialistProviderCancellationStatus.UNKNOWN,
                uncertainty_type=SpecialistUncertaintyType.FLINK_CANCELLATION_REJECTED,
            )
        # The PATCH acknowledgement is only an accepted request. A follow-up GET
        # can upgrade it to confirmed, but never the other way around.
        observed = self.observe_cancellation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=receipt_ref,
        )
        if observed.status is SpecialistProviderCancellationStatus.CONFIRMED:
            return observed
        if observed.status is SpecialistProviderCancellationStatus.UNKNOWN:
            return observed
        return self._observation(
            request,
            operation_ref=operation_ref,
            provider_receipt_ref=receipt_ref,
            status=SpecialistProviderCancellationStatus.ACCEPTED,
            uncertainty_type=SpecialistUncertaintyType.PROVIDER_CANCELLATION_ACCEPTED,
        )


__all__ = [
    "FLINK_ICEBERG_OPERATION",
    "FLINK_JOB_RECEIPT_PREFIX",
    "FLINK_PROVIDER_REF",
    "FlinkProviderCancellationAdapter",
]
