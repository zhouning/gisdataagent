# ADR-076: Chongqing extraction provenance boundary

**Status**: Accepted

**Date**: 2026-08-17

## Context

M3-28 binds the Chongqing archive and extracted working set by fingerprints and
records 526 exact archive matches, 6 modified entries, no missing entries and
52 extracted-only files. That comparison proves neither why the six entries
changed nor how the 52 additional files were produced. Treating the working
set as a byte-exact extraction would create a false source claim.

## Options considered

| Option | Benefit | Cost / risk | Decision |
|---|---|---|---|
| Treat the working set as an exact extraction | Fastest path to ingestion | Converts an unresolved derivation into a false authority claim | Rejected |
| Admit the working set into Landing now | Provides immediate lakehouse input | Bypasses operator, tool, transformation and governance evidence | Rejected |
| Record a metadata-only comparison and explicit provenance gap | Reproducible, path-free and fail-closed | Leaves content and ingestion blocked until external evidence arrives | Chosen |

## Decision

Adopt the M3-29 evidence contract as a separate, immutable provenance-gap
record. It reuses the checked M3-28 archive/extracted fingerprints and
comparison counts, identifies the comparison algorithm and scope, and records
six missing derivation inputs:

- operator identity;
- extraction tool version;
- command or workflow digest;
- modified-entry manifest;
- extracted-only-entry manifest;
- archive-to-working-set attestation.

The evidence is metadata-only. It contains no source payload, absolute path,
record value or geometry. `comparison_observed=true` and
`derivation_provenance_complete=false` are independent claims.

## Authority boundary

M3-29 does not create a Landing object, ResourceVersion, PlatformRun,
PolicyDecision, Approval, scheduler command, provider mutation or production
ingestion authority. It cannot be edited or rehashed into an approval. A fresh
protected admission must consume complete derivation evidence and resolve the
remaining owner, license, retention, access, privacy and sensitivity blockers.

## Consequences

**Positive**: the mismatch is now a first-class, CI-validated platform fact
instead of an informal note in ADR-074.

**Positive**: later operators can attach the missing derivation artifacts to a
stable upstream evidence fingerprint without copying restricted source data.

**Negative**: AR-2 remains `in_progress`; no content is admitted and no
immutable Landing authority exists.

## Verification

```bash
python -m data_agent.chongqing_extraction_provenance
python -m pytest data_agent/test_chongqing_extraction_provenance.py -q
```
