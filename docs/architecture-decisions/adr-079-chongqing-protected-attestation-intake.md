# ADR-079: Chongqing protected admission attestation intake

**Status**: Accepted

**Date**: 2026-08-17

**Decision owners**: Platform Architecture, Data Platform, Data Governance, Security

## Context

M3-31 provides one immutable, metadata-only readiness record for the first
Chongqing land-parcel candidate. It intentionally leaves six derivation inputs,
eight governance decisions and one fresh protected attestation unresolved. The
next workflow needs a deterministic intake boundary so that external evidence
can be checked without copying source payloads or allowing the evaluator to
become an ingestion authority.

## Decision

Adopt `data_agent.chongqing_protected_admission` as the M3-32 read-only intake
and evaluation contract. An external attestation bundle must:

1. bind to the exact M3-31 logical evidence fingerprint and file SHA-256;
2. repeat the source identity binding without source records, geometry or local
   paths;
3. provide all fifteen requirement records as independently attested
   `verified` entries with SHA-256 fingerprints;
4. pass the fixed archive, extraction, governance, binding, privacy and
   no-mutation check inventory;
5. identify the protected verifier and a non-local HTTPS evidence URI; and
6. be observed within 24 hours, unexpired, and valid for no more than seven
   days.

The evaluator produces a fingerprinted report. A complete external bundle may
set `admission_eligible=true` in that report, meaning the evidence is ready for
the separate admission decision boundary. It never sets content admission,
Landing, ResourceVersion, PlatformRun, scheduler submission, provider mutation,
or production readiness authority to true.

## Authority boundary

`validate` checks the checked-in M3-31 baseline and succeeds while the baseline
is valid but blocked. `evaluate` requires an external attestation file and
fails closed on any drift, missing requirement, stale timestamp, path/payload
marker, or failed check. `verify` rejects report tampering and any authority or
production overclaim. No command reads or copies the Chongqing source payload.

Synthetic complete attestation fixtures in unit tests exercise the evaluator
only; they are not production evidence and are not checked in as an admission
decision.

## Consequences

**Positive**: the next protected workflow has a stable, testable input schema
and can report exactly which of the fifteen external requirements remain
blocked.

**Positive**: complete evidence cannot be confused with write authority; the
report retains an explicit no-mutation and no-production boundary.

**Negative**: AR-2 remains `in_progress` until real external attestations are
provided and reviewed by the protected verifier. The checked baseline remains
`admission_eligible=false` because no attestation is present.

## Verification

```bash
./scripts/chongqing-protected-admission.sh validate
python -m pytest data_agent/test_chongqing_protected_admission.py -q
```
