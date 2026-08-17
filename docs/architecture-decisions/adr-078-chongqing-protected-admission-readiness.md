# ADR-078: Chongqing protected admission readiness

**Status**: Accepted

**Date**: 2026-08-17

**Decision owners**: Platform Architecture, Data Platform, Data Governance, Security

## Context

M3-28 records the Chongqing source as a metadata-only physical baseline. M3-29
records the archive-to-working-set comparison without proving derivation. M3-30
selects the first land-parcel candidate and freezes eight governance decision
slots, all still pending. These records are individually verifiable, but they
do not yet provide one admission gate that can be consumed by a future protected
ingestion workflow.

Without a unified gate, an ingestion implementation could accidentally treat a
complete-looking checklist as authority while omitting one derivation input,
one governance decision, or the protected environment attestation.

## Decision

Adopt M3-31 as an immutable, metadata-only admission readiness contract for
`source://chongqing-planning-institute-sample/assets/bishan_land_use_dltb_local`.
It binds the M3-28 admission evidence, M3-29 provenance evidence and M3-30
governance evidence by both logical and file fingerprints.

The contract fixes fifteen required inputs in three authority classes:

- six derivation inputs: operator identity, tool version, command/workflow
  digest, modified-entry manifest, additional-entry manifest, and
  archive-to-working-set attestation;
- eight governance decisions: owner, license, retention, access,
  privacy/sensitivity, standard version, DataSLO, and golden result;
- one fresh protected admission attestation.

The checked profile records all fifteen as `missing`, derives
`admission_eligible=false`, and is validated in CI. A future protected workflow
may consume this contract only after it supplies independently attested values
for every requirement and re-evaluates the complete bundle.

## Authority boundary

M3-31 is a readiness record, not an admission decision. It creates no Landing
object, ResourceVersion, PlatformRun, scheduler submission, provider mutation,
lakehouse table, serving projection, or production ingestion authority. It does
not copy source payloads and contains no absolute source path, record value, or
geometry.

Rehashing the JSON cannot promote any claim. `admission_eligible`,
`source_content_admitted`, and `production_ready` remain false until a separate
protected verifier accepts fresh external attestations.

## Consequences

**Positive**: the next admission workflow has one explicit, fingerprint-bound
contract and a complete blocker inventory instead of loosely coupled notes.

**Positive**: CI can reject requirement drift, path/payload leakage and any
attempt to convert a pending readiness profile into write authority.

**Negative**: AR-2 remains `in_progress`; all fifteen external requirements
remain unresolved and no content may enter Landing.

## Verification

```bash
./scripts/chongqing-admission-readiness.sh
python -m pytest data_agent/test_chongqing_admission_readiness.py -q
```

The checked evidence fingerprint is
`2f5ae24ab904af0eed18ee7c517ab5c4638cbdf0923c9345b0041af185d25591`; its
file SHA-256 is
`c595065e152988529ff12e2301d59caebb31d2889658a676c9d1f8239e6f8372`.
