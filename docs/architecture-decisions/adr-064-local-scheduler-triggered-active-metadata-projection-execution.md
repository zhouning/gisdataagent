# ADR-064: Local scheduler-triggered Active Metadata projection execution

**Status**: Accepted

**Date**: 2026-07-30

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-048](adr-048-local-authorized-metadata-fabric-ingestion-replay.md) · [ADR-062](adr-062-atomic-active-metadata-authorization-and-dispatch.md) · [ADR-063](adr-063-local-authorized-active-metadata-scheduler-delivery.md)

## Context

M3-17 proved that an exact Active Metadata authorization can become a real DolphinScheduler `3.4.2` workflow instance and provider `SUCCESS`, but the workflow deliberately had no side effect. M3-2 separately proved authorized OpenMetadata/Gravitino projection and zero-mutation replay, but the provider clients were invoked directly by the rehearsal. The missing boundary was a scheduler task that actually triggers the authorized provider projection while preserving distinct dispatch, provider-apply and platform-success authorities.

The retained real input is the Chongqing central cultural-district Shapefile bundle registered in M3-16. Its path-free inventory contains 20 `PolygonZ` features, 33 fields, EPSG:4490 and content SHA-256 `fd474fd65c8e4a71da241eb3fd07748ca3b972fbd2d3c32833376dbe71104007`. M3-18 does not reopen or commit the source path because no new source-data claim is required.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Treat M3-17 scheduler `SUCCESS` as provider execution | No new runtime | Confuses control-plane delivery with business mutation | Rejected |
| Copy provider mutation logic into the DolphinScheduler image | Self-contained task | Creates a second mutation engine and embeds provider credentials in the scheduler runtime | Rejected |
| Submit two independent workflow instances for create and replay | Strong scheduler-level replay signal | The second dispatch would require its own durable authorization and complicate this boundary | Rejected |
| Let one authorized task call an ephemeral executor that reuses M3-2 clients for apply and exact replay | Proves scheduler-to-provider execution without duplicating adapters | Local callback and bootstrap provider security are not production-grade | Adopted |

## Decision

### 1. Dispatch and provider apply remain independently authorized

The existing M3-16/M3-17 chain authorizes `dolphinscheduler.dispatch` for the provider-native workflow binding. A second execution-plan Artifact, PolicyDecision and Approval authorize `metadata_fabric.apply` for the exact tenant, Run, DefinitionVersion, source ResourceVersion, content hash, natural provider targets and apply-plan fingerprint.

The source dataset is itself the projected ResourceVersion; M3-18 does not fabricate a target ResourceVersion merely to satisfy authorization cardinality. The provider-apply decision therefore canonicalizes the exact unique ResourceVersion scope before M3-2 validation.

### 2. DolphinScheduler triggers exactly one bounded callback

The official standalone image runs one Shell task whose immutable body contains the projection request fingerprint and calls a short-lived HTTP executor through Docker Desktop's host gateway. The executor accepts exactly one request, rejects body or fingerprint drift, holds provider credentials and authorization only in memory, and returns success only after both provider phases pass.

The callback is plaintext local HTTP and is not a protected workload identity, authenticated service endpoint, production network path or durable controller. Its URL and credentials are excluded from evidence, and the server is stopped after the rehearsal.

### 3. Existing provider clients own mutation and read-back

The executor reuses `OpenMetadataApplyClient`, `GravitinoApplyClient` and `apply_once` from ADR-048. The first apply must create provider state and read back the exact GDA ResourceURN, ResourceVersion, content hash, governance refs and technical revision. The immediate second apply must be `no_op` with zero mutations and the same OpenMetadata observation, Gravitino observation and binding-candidate fingerprint.

Partial inventory, state drift, inactive authorization or provider failure remains fail closed under the M3-2 behavior. M3-18 does not add another provider mutation implementation.

### 4. Scheduler and provider success are still not platform success

DolphinScheduler `SUCCESS` produces the existing `submitted/success` FrameworkAttemptObservations and one external correlation. Provider apply/read-back forms additional local evidence, but the PlatformRun remains `reconciling`; only the existing platform success evidence gate may produce `succeeded`.

### 5. Provider objects are retained, ephemeral control resources are removed

The OpenMetadata and Gravitino projection objects remain available for read-back. The callback server, both Kubernetes port-forwards, DolphinScheduler container and temporary GDA Control PostgreSQL database must all be removed. No legacy authority, source data, production deployment or persistent GDA binding is written.

## Verification

The local rehearsal recorded:

- one authorized DolphinScheduler instance with six exact GDA correlation variables and terminal `SUCCESS`;
- one callback request matching request SHA-256 `462d738064fb2352acee3b72b1b966bc5ce4f524904bc991b87c8c56d1f2f8ae`;
- first apply `created` with 10 mutations across OpenMetadata and Gravitino;
- replay `no_op` with zero mutations;
- OpenMetadata table UUID `9d043410-02b5-487d-bb70-da5f3969a978`;
- shared binding-candidate SHA-256 `7de24cee9dd50dfeefcc886cf43024f4d92b7650767d71d064fdce19ffccb16b`;
- PlatformRun `reconciling`, never `succeeded`;
- callback, two port-forwards, standalone container and temporary database cleanup;
- contract SHA-256 `a6632ae0edd4d4f3389129a8c07411a8d101ae56fbfc26b03fb0aff6928bb7bd`;
- evidence SHA-256 `397c0f1a29f53935c5508155470c4972cfc50260f0d0686fb48cb3f75519b17b`.

## Claim Boundary

Allowed now:

- local scheduler-triggered provider projection execution is verified for the recorded Docker Desktop identities;
- the exact Chongqing ResourceVersion content hash reached both provider projections;
- independent local dispatch and provider-apply authorizations were validated;
- first apply, provider read-back and zero-mutation replay are correlated to one scheduler Run.

Fixed false now:

- protected workload identity, OIDC, TLS and provider-wide minimum privilege;
- Gravitino authentication and production durable catalog behavior;
- production scheduler submission, HA, backup and deployed controller;
- binding persistence, production OpenLineage delivery and production ingestion;
- platform Run success and `production_ready`.

## Consequences

**Positive**: M3-18 closes the local scheduler-to-provider execution gap without creating a second provider adapter or weakening platform success authority.

**Negative**: the executor is an ephemeral host process, OpenMetadata uses bootstrap admin, Gravitino is unauthenticated and uses its local memory catalog, and the retained provider objects make this exact `created` rehearsal intentionally non-repeatable without a new target or explicit cleanup.

**Revisit trigger**: replace this boundary only when a deployed executor with protected workload identity, minimum-privilege dual-provider credentials, authenticated durable Gravitino catalog, production scheduler metadata/HA, persistent binding and platform terminal evidence is available.
