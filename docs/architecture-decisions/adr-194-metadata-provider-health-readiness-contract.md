# ADR-194: Metadata Provider Health and Readiness Contract

**Status:** Accepted (bounded runtime slice)

## Context

The Metadata Fabric bridge now supports credential-safe provider read/search and
low-cardinality operation metrics. That does not tell the application whether a
configured OpenMetadata or Gravitino endpoint is reachable, authorized, or still
speaks the expected health protocol. Treating every configured URL as healthy
would let traffic reach an instance that cannot satisfy the platform's metadata
control-plane dependency.

## Decision

Add a read-only provider probe with schema `gda.metadata_provider_health.v1`.

- Gravitino is probed at the fixed `/health` endpoint and must return a bounded
  JSON object whose `status` is `up`, `ok`, or `healthy`.
- OpenMetadata is probed at the fixed `/api/v1/system/version` endpoint (the
  configured server-root URL is normalized to that API root) with the same
  bearer-token source contract as the read/search bridge.
- The probe sends no catalog query and never returns provider response content.
  Its output is limited to provider, fixed endpoint, HTTP status, latency,
  retryability, and a stable failure class.
- Failure classes are `configuration_error`, `unauthorized`, `unavailable`,
  and `protocol_error`. HTTP 5xx and transport/timeouts are retryable; 401/403
  are authorization failures; malformed or oversized health responses are
  protocol failures.
- `/ready` remains ready when a provider is absent (local-only mode), but fails
  closed when a configured provider is unhealthy. `/api/admin/system-info`
  exposes the same bounded provider summaries for operators.

This is an application dependency probe, not a production OpenMetadata or
Gravitino SLO, HA, backup, identity, or provider-wide conformance claim.

## Consequences

The platform can distinguish configuration and provider incidents before routing
metadata-dependent traffic, while preserving the existing authority boundary.
Probe traffic is bounded and must use a short timeout; operators should not use
this endpoint as a replacement for provider-native metrics or alerting.

The fixed OpenMetadata `1.13.1` acceptance observed `/system/version` with HTTP
`200`, alongside source-only credential resolution, bounded search, UUID
read-after-search, and bridge metrics. The report is stored with mode `0600` at
`.tmp/metadata-fabric/openmetadata-provider-search-acceptance-report.json` and
has SHA-256
`af678ea2f2c832057a8fb18908edf76875a7b5425119e3dbb35e26eb7787f759`.

The fixed Gravitino `1.3.0-local-arm64` seed/restart/recover acceptance also
observed `/health` with HTTP `200` after restart, and passed provider read/search
and tombstone projection. Its report `report_sha256` is
`ff81a05ad9a93b35d187135b3a59791e8efa35e429744b986ef3bca2418cd6d3`.
