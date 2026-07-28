# ADR-047: Deterministic Metadata Fabric Ingestion Projection

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Data Platform, Metadata Platform, Data Governance, Security, Platform Architecture

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-020](adr-020-platform-resource-run-and-evidence-contracts.md) · [ADR-021](adr-021-legacy-crosswalk-and-golden-slice.md) · [ADR-036](adr-036-read-only-metadata-fabric-bridge-contract.md) · [ADR-046](adr-046-production-network-policy-readiness-gate.md)

## Context

M1 established a read-only identity and reconciliation boundary for one immutable land-use `ResourceVersion`. M2 established local foundation, recovery, metrics, NetworkPolicy evidence and production readiness contracts. The next data-platform capability is controlled metadata ingestion and replay, but the local provider foundation is not currently running and no production provider identity, PolicyDecision/Approval or protected environment is available.

Writing directly to OpenMetadata or Gravitino now would conflate three separate questions: whether a published GDA version has sufficient terminal evidence, which facts each provider owns, and whether a runtime identity is authorized to mutate that provider. It would also make an apparently successful HTTP response look like a platform terminal verdict.

M3-1 therefore defines the deterministic projection and replay contract without adding a provider mutation client. This advances the ingestion architecture while keeping live and production claims false.

## Options Considered

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| Write the synthetic fixture directly to local providers | Quickly demonstrates POST/PUT calls | Foundation is absent; no authorization evidence; success would not prove replay or authority boundaries | Rejected |
| Add another scheduler for metadata ingestion | Isolates metadata jobs | Violates the DolphinScheduler scheduling decision and creates another run authority | Rejected |
| Let each provider adapter construct its own payload and idempotency key | Simple adapters | Identity, ownership and replay semantics would diverge between providers | Rejected |
| Build one terminal-evidence-bound projection plan, then add authorized adapters later | Deterministic, reviewable and reusable; no premature runtime mutation | M3-1 cannot prove live provider ingestion | Adopted |

## Decision

### 1. Only a terminally evidenced ResourceVersion can produce a plan

`data_agent.metadata_fabric_ingestion` joins the existing platform and Metadata Fabric golden fixtures. A plan is generated only when all of the following identify the same tenant, run and target version:

- immutable source and target `ResourceVersion`;
- output `Artifact` whose content hash equals the target version;
- passed `QualityResult` from an evaluator independent of the output producer;
- derive `LineageEvent` binding source, target, definition, run and artifact;
- content-bound `RunSuccessEvidence` binding artifact, quality and lineage;
- M1 `MetadataFabricBinding` and verified provider observations.

Missing or changed output hash, quality verdict, evaluator separation, lineage relation, success evidence, tenant, provider ref or binding fails closed before a plan exists.

### 2. Provider ownership is explicit and GDA is not dual-written

The plan contains one OpenMetadata projection and one or more Gravitino projections:

- OpenMetadata owns owner, domain, glossary/classification, quality discovery and generic-lineage projection;
- Gravitino owns metalake, catalog, schema, table and technical-access projection;
- provider desired state contains the GDA ResourceURN/version/content tuple only as a reference projection;
- GDA Control Ledger remains the authority for ResourceVersion, run, policy, approval, artifact, evidence and action outcome.

Projection field inventories are exact, reject secret-bearing keys and have content-derived state fingerprints and idempotency keys. The plan fixes `writes_to_gda_control=false` and `writes_to_legacy=false`; no catalog payload can become a reverse write into either authority.

### 3. Replay is no-op or blocked in M3-1

The plan has one idempotency key derived from binding, terminal evidence, projection keys and OpenLineage event fingerprint. Rebuilding from identical inputs returns the same plan.

`evaluate_replay` compares current provider observations with the plan. Exact state returns `no_op`. Owner/domain/tag, Gravitino revision, GDA identity or target-inventory drift returns `blocked`. M3-1 never turns drift into an automatic mutation and fixes `provider_apply_authorized=false` and `provider_mutations_executed=false`.

### 4. OpenLineage is a candidate contract, not emitted evidence

The same GDA lineage produces a minimal OpenLineage `COMPLETE` RunEvent candidate using the OpenLineage `2-0-2` RunEvent schema URL. It binds the GDA run, DataOps capability and version-qualified input/output datasets. Its canonical fingerprint is part of the ingestion plan.

M3-1 does not send the event to OpenMetadata or any OpenLineage backend. Therefore the report says `openlineage_candidate_contract_verified=true`, while live emission and production ingestion remain false.

## Verification

The checked-in golden contract produces:

- platform fixture fingerprint `9c18a58248c7f34666cc2eb1a959694725dead05fdab7bf855e57ee71b2091b5`;
- Metadata Fabric fixture fingerprint `74ac611b5ccd5c0f63e13931217172e24bdbaea37f3053c7669ca94096c991f8`;
- ingestion plan fingerprint `a5c8ef636c03a38d0c6edaacff7d1edeba9c4b8a7f1491c493e9308257c5a94d`;
- OpenLineage candidate fingerprint `4929e51c4126e09415a9fc1578c9401077c5d7c374294e70deeebd29c8216dd2`;
- no-op replay fingerprint `c33857b2ae75f1106ed7d59e8e53296a3f76f4b90ef386238159b328d47c57ca`.

Twenty focused tests cover the golden report, terminal evidence, evaluator separation, binding identity, provider ownership, secret fields, projection/plan tampering, deterministic replay, OpenLineage time/dataset validity, OpenMetadata owner/domain/tag drift, Gravitino revision/inventory drift, fixture drift and CLI validation.

## Claim Boundary

Allowed now:

- M3-1 deterministic Metadata Fabric ingestion projection contract is established;
- the synthetic terminal evidence and M1 binding deterministically produce two projection intents and one OpenLineage candidate;
- identical provider observations replay as `no_op`; drift fails closed;
- no GDA or legacy dual write exists in this path.

Fixed false now:

- `provider_apply_authorized`;
- `provider_mutations_executed`;
- live OpenMetadata or Gravitino ingestion;
- live OpenLineage emission;
- `live_provider_ingestion_verified`;
- `production_ingestion_verified` and `production_ready`.

## Consequences

**Positive**: provider adapters can consume one stable plan instead of inventing identity, ownership and replay semantics. Terminal evidence and lineage become prerequisites for discoverability projections, and repeated execution has an explicit no-op result.

**Negative**: M3-1 does not create or update provider objects. The OpenLineage object is a checked-in contract candidate, not wire-level delivery evidence.

**Mitigation**: M3-2 must start a bounded local foundation, use workload identity plus exact PolicyDecision/Approval evidence, execute only the plan's provider-owned projections, read them back, prove create/replay idempotency and retain sanitized observations. Provider success remains non-terminal and must never modify GDA truth.

**Revisit trigger**: change the projection schema only when an actual OpenMetadata/Gravitino API contract or OpenLineage compatibility test requires it; do not add fields merely because a provider supports them.
