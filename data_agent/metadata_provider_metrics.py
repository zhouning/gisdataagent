"""Low-cardinality Prometheus metrics for Metadata Fabric provider bridges."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

_PROVIDERS = frozenset({"openmetadata", "gravitino"})
_OPERATIONS = frozenset({"read", "search"})
_OUTCOMES = frozenset({"present", "not_found", "success", "error"})

metadata_provider_operations = Counter(
    "gda_metadata_provider_operations_total",
    "Metadata provider bridge operations by provider, operation and bounded outcome",
    ["provider", "operation", "outcome"],
)
metadata_provider_operation_duration = Histogram(
    "gda_metadata_provider_operation_duration_seconds",
    "Metadata provider bridge operation latency",
    ["provider", "operation"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)


def record_metadata_provider_operation(
    provider: str,
    operation: str,
    outcome: str,
    duration_s: float = 0,
) -> None:
    """Record provider, operation and bounded outcome without catalog labels."""
    provider_label = provider if provider in _PROVIDERS else "unknown"
    operation_label = operation if operation in _OPERATIONS else "unknown"
    outcome_label = outcome if outcome in _OUTCOMES else "error"
    try:
        metadata_provider_operations.labels(
            provider=provider_label,
            operation=operation_label,
            outcome=outcome_label,
        ).inc()
        if duration_s > 0:
            metadata_provider_operation_duration.labels(
                provider=provider_label,
                operation=operation_label,
            ).observe(duration_s)
    except Exception:
        pass
