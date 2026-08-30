# ADR-088: Freeze Fail-Closed Component-Lag Replication Executor

## Status

Accepted.

## Context

Stage 46 froze the strict four-event cohort operator before target acquisition.
The remaining implementation risk was the real-data path connecting the future
Stage 45 raw payloads to that operator. Manifest interpretation, source-hour
reconstruction, target aggregation, missing-hour behavior, and lag pairing all
could change the result if left unspecified until after values were visible.

## Options considered

### Option 1: Implement the evidence compiler after acquisition

This would allow observed gaps and values to influence alignment and validation
decisions, weakening the prospective assessment.

### Option 2: Reuse Stage 43 compilation without modification

Stage 43 had complete Stonewall hourly coverage and its helper assumed every
target hour existed. It did not implement the Stage 46 contract in which gaps
remain unfilled and pair count may fall below 72.

### Option 3: Freeze a gap-aware fail-closed compiler before acquisition

This can bind the future manifest and raw artifacts exactly while giving
missing observations explicit absolute-time semantics.

## Decision

Adopt Option 3.

Freeze an evidence compiler that accepts only the fixed Stage 45 directory. It
must verify the protocol, plan, state, manifest, request order, attempts, byte
totals, raw paths, hashes, sizes, provenance, TLS flag, and payload fields
before opening the assessment path.

Reconstruct 72 source values from exact-hour sums of Orifice, Sluice, Spillway,
and Turbine Flow. Reject missing, null, non-finite, or negative components.
Compile target hours only when both open-closed half-hour positions exist.

Pair each source value to the target whose UTC support end equals the source
support end plus the candidate lag. A missing target hour removes only that
pair; it never shifts subsequent hours. Apply the frozen minimum pair count of
60 and all other empirical support thresholds before passing results to the
unchanged Stage 46 all-four cohort operator.

Freeze an offline runner requiring `--execute-frozen-assessment` and the exact
Stage 47 output location. The runner has no network request capability. The
Stage 45 acquirer module is imported only for its already-frozen raw payload
validator.

## Consequences

### Positive

- Data validation and time alignment cannot change after target observation.
- Missing hours cannot silently create lag shifts through sequence compaction.
- Every future result will bind its acquisition state, manifest, raw hashes,
  upstream checkpoints, and output provenance.

### Negative

- A missing raw file or metadata mismatch rejects the whole execution.
- Sparse but otherwise plausible data may fail the 60-pair threshold.
- The real cohort result remains unavailable until Stage 45 acquisition is
  separately authorized and completed.

## Claim boundary

The evidence compiler, offline runner, and execution protocol are frozen, but
target acquisition and assessment execution remain false. A future pass can
admit only Center Hill component-total flow-class cohort replication. Universal
lag, Stage 30 override, non-Turbine component contrast, causal or physical
interpretation, and runtime promotion remain rejected.

## Evidence

The evidence compiler, execution protocol, and gate report SHA-256 values are
respectively:

```text
63ca89193e5159827ddf2e7be9774ed31f683ead4c98236ebc44938a964b57c9
8c0bc867315b43a6439ea616914bcde768d5134355f69853979aa1fdd0d61a9f
713ff753d04add9c236e18f2ef98459d543a4822d0d74b6e60d6e561b515997f
```

All 47 gates pass with status
`stage47_component_lag_replication_executor_frozen_targets_pending`.

## Related decisions

- ADR-086 freezes the exact four-request Stage 45 target plan.
- ADR-087 freezes the Stage 46 cohort assessment before target values.
