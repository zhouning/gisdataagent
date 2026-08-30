# ADR-214: GIS Service Endpoint Readiness Binding

## Context

An `EndpointRevision` is immutable and may be recorded only from a ready
`ServiceDeploymentRevision`. Before this decision, the recorder verified
service ownership, readiness time, protocol compatibility, and MVT serving
projection binding, but it did not verify that the registered endpoint URI was
the URI contained in the ready deployment's terminal v2 provider observation.

That allowed one successful health receipt for one provider address to support a
different address in the endpoint registry. The active pointer could therefore
refer to an endpoint without its own release-bound readiness evidence.

## Decision

Migration 208 replaces the existing `record_endpoint_revision` function without
changing its public signature or adding a table. For every new endpoint revision
it joins the ready deployment to its terminal `FrameworkAttemptObservation` and
requires:

```text
endpoint_revision.endpoint_uri
  == deployment.terminal_observation.evidence.endpoint_uri
```

The existing checks remain in force: tenant RLS, ready state, non-retroactive
creation time, service/protocol compatibility, immutable content identity, and
the release-bound MVT serving projection contract. Exact recorder replay remains
valid for already registered immutable endpoint revisions.

| Option | Result |
|---|---|
| Let endpoint registration choose any HTTPS URI after deployment readiness | Rejected: the ready health receipt no longer proves the active address. |
| Add endpoint-specific health records and a new checker worker | Rejected: duplicates the existing terminal provider evidence ledger. |
| Bind the endpoint recorder to the deployment's existing terminal observation | Chosen: keeps one evidence source and enforces the relation in PostgreSQL. |

## Consequences

Each newly registered endpoint now has a direct evidence chain:

```text
DataProductVersion -> ReleaseBinding -> DeploymentRevision
-> terminal v2 provider observation (verified endpoint URI)
-> EndpointRevision -> active CAS pointer
```

Different endpoints require their own ready deployment revision and terminal
evidence. This is intentional: a canary URI cannot be promoted on the strength
of a health check against another URI.

This does not probe the provider, build an endpoint, warm cache, orchestrate
canary traffic, verify every network zone, or complete rollback and ServiceSLO
operations.

## Verification

Disposable PostgreSQL 16 certification attempts to register a different URI
after a ready settlement and verifies rejection. It then registers two immutable
endpoint revisions, each with its own ready deployment and exact ready-observed
URI, exercises active-pointer CAS and rollback, and verifies RLS/immutability
controls.

```bash
uv run python scripts/certify_gis_service_control_plane.py
```
