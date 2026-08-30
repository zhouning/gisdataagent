# ADR-148: Approval-Gated Reference Master Golden Record Authority

**Status**: Accepted

**Date**: 2026-08-04

**Related**: ADR-103, ADR-121, ADR-143, ADR-146, ADR-147

## Context

Natural-resource GIS needs stable administrative-unit and land-use-code identities across
source systems, versions, spatial products and agent workflows. Source revisions can be replayed,
AI/entity-matching output can be useful evidence, and a steward must be able to correct a golden
record without losing the previous version. None of those facts authorizes a model or source system
to rewrite the active record directly.

The result must remain maintainable from EA-oriented logical/physical model work while being
consumable by the GIS Data Agent's standard, model, metadata, lineage and approval functions. The
control plane therefore needs a tenant-scoped identity and version authority with a database-enforced
approval boundary, rather than a second ungoverned catalog.

## Options Considered

| Option | Pros | Cons | Complexity | When Valid |
|---|---|---|---|---|
| Immediately replace the platform with a standalone enterprise MDM product | Mature survivorship, stewardship UI and broad entity-resolution features | New identity, approval, metadata and GIS integration boundary; migration and operating cost are high before the first domain is proven | High | Multiple domains, large-scale merge/split and multi-channel distribution are already funded requirements |
| Put master data into the generic standard/data-product platform without a dedicated authority slice | Fewer modules and a short initial path | Golden identity, source evidence and approval semantics become implicit in product tables or pipelines; AI can accidentally become a writer | Medium initially, high later | Only for non-authoritative dimensions where no cross-system identity is required |
| Keep stable identity/version/approval in the GDA Control Ledger; keep entity content in governed PostGIS/Iceberg products and project metadata to OpenMetadata/Gravitino | One approval and audit authority, rebuildable GIS projections, EA-compatible model artifacts, incremental adoption | Requires explicit evidence contracts and a later projection/distribution layer; not a full MDM suite | Medium | Chosen for the first administrative-unit and land-use-code vertical slice |

## Decision

Choose the hybrid authority in Option 3.

- Migration 124 owns immutable `master_source_record`, `master_match_candidate`,
  `master_entity_version`, `master_entity_activation` and append-only `master_data_event` tables.
- Source identity is derived from tenant, source system, source record ID and source revision. Exact
  replays return the original fingerprint; changed evidence conflicts instead of overwriting it.
- `master-match-v1` emits immutable candidates only. Business-key, normalized-name and active-parent
  evidence are explained with a 6500/2500/1000 score; scores below 5500 are discarded and a
  recommendation requires at least 8500 with a 500-point lead. A human approval is still required
  for activation.
- A version is active only through an unexpired, approved `ApprovalCase` with action
  `master_data.entity.activate` and exact target ResourceURN/fingerprint. Activation uses an
  activation-version CAS, enforces active business-key uniqueness and rejects hierarchy cycles.
- Database triggers, forced tenant RLS and a least-privilege gateway role make source, version,
  candidate and event rows immutable. The gateway receives SELECT and controlled function execution,
  never direct master INSERT/UPDATE/DELETE privileges.
- The API derives tenant, actor, timestamps, ResourceURNs and fingerprints at the server boundary.
  It exposes source observation, machine matching, version staging/listing, approval creation,
  activation, active lookup and event history. EA remains a model-maintenance/projection client; it
  does not become a second runtime authority.

## Verification

- Contract/API tests cover frozen tenant-bound models, sorted evidence, dual time semantics, score
  explanations, machine-only matching, exact approval binding, admin-only activation and OpenAPI
  identity injection.
- `uv run pytest -q data_agent/test_master_data_authority.py data_agent/test_master_data_api.py
  data_agent/test_platform_gateway.py` passes the current focused contract suite.
- `scripts/certify_master_data_lifecycle.py` applies migrations through 124 to disposable PostgreSQL
  16.14 and verifies 18 lifecycle, idempotency, CAS, unique-key, immutability, RLS and privilege
  checks; it also verifies that the one-time container is removed. The report is written to
  `/tmp/gda-master-data-lifecycle.json` when requested.

## Trade-offs

- This is an authority slice, not a complete enterprise MDM product. Merge/split survivorship,
  bulk hierarchy changes, golden-record distribution and large-scale probabilistic entity resolution
  are intentionally deferred.
- Content remains in governed GIS/data-product storage, so a projection and reconciliation contract
  is required before external consumers can treat a master entity as a serving dataset.
- The first algorithm is deliberately conservative and deterministic. It may send ambiguous or
  multilingual matches to review rather than maximizing automation.
- EA and metadata systems may show model/projection state, but approval and active pointers remain in
  the GDA Control Ledger to avoid dual-write authority.

## Consequences

- Positive: source evidence, candidate reasoning, version history, approval and active state are
  replayable and tenant-isolated; GIS agents can consume typed contracts instead of scraping EA or
  source tables.
- Negative: stewards must approve activations, and every content update creates a new immutable version.
  The first release supports only two reference domains.
- Mitigation: expose bounded API operations, deterministic match explanations and rebuildable metadata/
  PostGIS/Iceberg projections; add new domains only with their code/value and lifecycle contracts.

## Revisit Trigger

Revisit this decision when at least one of the following is approved and measured: merge/split and
survivorship across multiple authoritative systems; bulk hierarchy or effective-dated change volume
that exceeds the ledger path; a requirement to distribute golden records transactionally to many
operational systems; probabilistic matching at a scale the deterministic matcher cannot handle; or
EA/OpenMetadata/Gravitino interoperability requires a different canonical identity protocol.

