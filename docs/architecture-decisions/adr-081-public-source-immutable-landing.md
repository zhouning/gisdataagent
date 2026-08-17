# ADR-081: Public/Open Source Immutable Landing

**Status**: Accepted

**Date**: 2026-08-17

**Decision owners**: Platform Architecture, Data Platform, Data Governance

## Context

AR-2 needs a working source-to-platform entry point while the Chongqing
protected source remains blocked on external governance attestations. The
existing control ledger already owns `Resource`, `ResourceVersion` and
`Artifact`; creating another Landing registry would repeat the authority split
that AR-0 is intended to remove.

The first executable slice must copy actual bytes, prove their checksum, make
replay idempotent, and leave an auditable binding without reading protected
source payloads or granting scheduler/provider mutation authority.

## Options considered

| Option | Benefit | Limitation | Decision |
|---|---|---|---|
| Add a dedicated Landing database/table | Explicit schema | Creates a second version and artifact authority | Rejected |
| Register a path and trust later ingestion | Small implementation | Does not prove bytes or protect against replacement | Rejected |
| Content-addressed local Landing plus atomic existing-ledger registration | Real byte-level behavior, deterministic replay, no new authority | Local profile is not object-store or production evidence | Adopted |

## Decision

Adopt `data_agent.public_source_landing` for the public/open profile:

1. Require an HTTPS source URI without credentials, query, or fragment, an
   explicit license identifier, an expected SHA-256, owner, media type, and
   controlled actor.
2. Copy a regular non-symlink source file into a content-addressed path under
   `<tenant>/<dataset>/sha256/<content_sha256>/payload.<suffix>` using atomic
   no-overwrite installation. The manifest is installed alongside the payload
   with restrictive permissions and the same no-overwrite rule.
3. Represent the Landing authority using the existing `gda_control.resource`,
   `resource_version` and `artifact` rows. The gateway registers all three in
   one transaction through `register_landing`; a conflict rolls back the
   complete registration.
4. Expose `/api/platform/v1/landings` for an authenticated same-tenant actor
   to register an already staged object. The CLI performs the local byte copy
   and can invoke the same gateway transaction.
5. Keep `admission_class=public_open`, `content_admission_authorized=true` and
   `production_ready=false` explicit in the manifest. This path is not allowed
   to reinterpret M3-31/M3-32/M3-33 Chongqing evidence or bypass the protected
   workflow.

## Consequences

**Positive**: the platform now has a real immutable byte Landing and ledger
identity with deterministic replay and conflict rollback, without another
registry or queue.

**Negative**: the current implementation is a local filesystem profile. It
does not prove object-store locking, cloud identity, DataOps scheduling,
Bronze/Silver/Gold transformation, or production readiness.

**Next**: bind this public Landing ResourceVersion to a minimal DataOps
definition and PlatformRun, then materialize a small GeoJSON/ZIP slice to the
lightweight serving profile. Separately provision the protected Chongqing
environment and real attestations.

## Verification

- `data_agent/test_public_source_landing.py`
- `data_agent/test_public_source_landing_postgres.py`
- Natural Earth 110m public-domain ZIP smoke: content SHA-256
  `0f243aeac8ac6cf26f0417285b0bd33ac47f1b5bdb719fd3e0df37d03ea37110`,
  214,976 bytes, replay and verify passed.
