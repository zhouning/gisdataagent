# ADR-077: Chongqing source governance gate

**Status**: Accepted

**Date**: 2026-08-17

**Decision owners**: Data Platform, Data Governance, Security, Data Product

## Context

M3-28 binds the full Chongqing source corpus through metadata-only physical and
logical fingerprints. M3-29 makes the unresolved archive-to-working-set
derivation explicit. Neither record identifies which asset should enter the
first land-parcel vertical slice or provides owner, license, retention, access,
privacy/sensitivity, standard-version, DataSLO, or golden-result decisions.

Selecting a candidate is not equivalent to approving its content. Leaving the
required governance fields only in roadmap prose would allow later ingestion
code to omit a decision or treat an informal note as authority.

## Decision

Adopt M3-30 as a separate, immutable and metadata-only governance baseline for
`source://chongqing-planning-institute-sample/assets/bishan_land_use_dltb_local`.
The evidence binds the M3-28 admission fingerprints, the M3-29 provenance
fingerprints, the source group, asset ID, archive fingerprint, and extracted
working-set fingerprint.

The gate enumerates eight independently required decisions:

- owner;
- license;
- retention;
- access;
- privacy and sensitivity;
- standard version;
- DataSLO;
- golden result.

Each decision is represented by a status, a decision reference, and an
attestation fingerprint. In the checked baseline all eight statuses are
`pending`, all references and attestations are absent, and the exact blocker
inventory is CI validated. A fresh protected attestation is required even after
all decision records exist.

## Authority boundary

M3-30 selects the first candidate scope only. It does not approve source
governance, complete derivation provenance, admit content, create an immutable
Landing object, ResourceVersion, PlatformRun, scheduler command, provider
mutation, lakehouse table, serving projection, or production ingestion.

The evidence contains no source payload, absolute path, record value, or
geometry. It cannot be edited or rehashed into an approval. Later admission
must consume separate signed decision attestations and complete M3-29
derivation evidence, then run through a protected fail-closed admission path.

## Consequences

**Positive**: the first AR-2 land-parcel candidate and every governance input
required for admission are now machine-checkable platform facts.

**Positive**: CI rejects missing fields, fingerprint drift, path/payload
markers, and any attempt to turn pending decisions into admission authority.

**Negative**: AR-2 remains `in_progress`. Eight governance decisions, six
derivation inputs, and a fresh protected attestation are still external
blockers.

## Verification

```bash
./scripts/chongqing-source-governance.sh
python -m pytest data_agent/test_chongqing_source_governance.py -q
```

The checked evidence fingerprint is
`97cf11ab8938c048dce9db903d1a4f30758f208dec6dad1a08b740a4a8fe7b6f`; its
file SHA-256 is
`25bc5e2dfc5528f5556e7174f8c99fed7abaf30b9312528f5164c16bdf7cca9a`.
