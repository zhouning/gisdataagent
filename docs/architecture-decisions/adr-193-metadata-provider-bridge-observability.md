# ADR-193: Metadata provider bridge observability contract

## Status

Accepted

## Context

The Metadata Fabric read and bounded-search bridges now execute authenticated
provider calls, but their operation outcomes were not visible in the existing
Prometheus registry. Provider URLs, tenant IDs, namespaces, object IDs and
provider error text are high-cardinality or sensitive and must not become
metric labels.

## Decision

1. Register `gda_metadata_provider_operations_total` and
   `gda_metadata_provider_operation_duration_seconds` in a dedicated module so
   the existing application `/metrics` registry exposes them without changing
   the legacy observability module.
2. Record only provider (`openmetadata|gravitino`), operation (`read|search`)
   and bounded outcome (`present|not_found|success|error`). Unknown values are
   collapsed to `unknown`/`error`.
3. Instrument the provider service dispatch boundary, so API routes, direct
   acceptance tools and future workers share the same outcome semantics. Read
   outcomes preserve `present`/`not_found`; search outcomes use `success`.
4. Metrics are telemetry only. They do not change provider authority, retry,
   tenant binding, error classification or readiness verdicts.

## Evidence

- `data_agent/metadata_provider_metrics.py` registers the bounded metrics and
  records no catalog identifiers.
- `MetadataProviderReadService` and `MetadataProviderSearchService` record
  duration and terminal outcome in `finally` blocks, including configuration
  and transport errors.
- `data_agent/test_metadata_provider_observability.py` covers read success,
  read error and search success/error without changing exception contracts.
- The fixed OpenMetadata `1.13.1` acceptance topology exercised source-only
  provider search and UUID read-after-search; the report recorded
  `provider_operation_metrics_observed=true` at
  `.tmp/metadata-fabric/openmetadata-provider-search-acceptance-report.json`
  (`0600`, SHA-256
  `af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`).

## Consequences

Provider bridge latency and bounded outcomes can now be scraped and alerted on
without leaking provider catalog identity or tenant data. The metric contract
is shared by in-process API/acceptance callers and can be reused by worker
processes that expose the same registry.

This decision does not establish OpenMetadata/Gravitino production metrics,
OTel export, dashboards, SLOs, HA, backup/restore or provider-wide isolation.
Those remain AR-1 production-foundation gates.

## Revisit triggers

- A production telemetry backend requires exemplars or trace correlation.
- Provider conformance requires separate retryable/permanent outcome series.
- Worker deployment exposes an independent metrics registry and needs a
  scrape/aggregation contract.
