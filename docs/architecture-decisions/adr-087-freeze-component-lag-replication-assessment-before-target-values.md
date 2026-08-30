# ADR-087: Freeze Component-Lag Replication Assessment Before Target Values

## Status

Accepted.

## Context

Stage 44 selected four source-only events after closing the known Stonewall
target-exposure inventory. Stage 45 then froze the minimum four-request target
plan and a fail-closed executor, but execution remains unauthorized and no new
target value exists.

The replication decision still needs an executable cohort operator. Freezing
only prose would leave room to change support membership, event aggregation,
or partial-pass behavior after seeing the target values.

## Options considered

### Option 1: Acquire and assess immediately

This would require separate authorization for the four external USGS requests
and would combine data acquisition with a not-yet-frozen assessment step.

### Option 2: Freeze the assessment after acquisition

This would allow target observations to influence implementation details and
would weaken the prospective replication claim.

### Option 3: Freeze the operator and full assessment protocol now

This preserves the Stage 44 hypothesis, binds all upstream evidence and future
manifest requirements, and can be completed entirely offline.

## Decision

Adopt Option 3.

Freeze a Kernel operator that requires four unique events in the exact order
`high_increase`, `high_decrease`, `low_increase`, `low_decrease`. Each event
must pass the unchanged empirical detectability gate and its support set must
contain the flow-class lag: `5h` for both high-flow directions and `6h` for
both low-flow directions. This is support membership, not exact best-lag
equality. Partial direction or flow-class success is forbidden.

Freeze source reconstruction to 72 exact-hour sums of Orifice, Sluice,
Spillway, and Turbine Flow. Freeze target compilation to the four Stage 45
Stonewall windows, 84 elapsed hours each, with open-closed hourly means from
observed half-hour samples. Source gaps fail and target gaps remain unfilled.

Require a future acquisition checkpoint that binds the exact Stage 45 plan,
four source IDs, four output names, four manifest artifacts, and every raw
hash. Until that checkpoint exists, assessment execution remains false.

## Consequences

### Positive

- Target observations cannot alter cohort membership, lag requirements,
  thresholds, aggregation, or all-four pass logic.
- The scientific decision is implemented as a testable Kernel object with
  explicit per-event rejection reasons.
- Protocol compilation remains offline and independently reproducible.

### Negative

- One missing or failed event rejects the entire cohort.
- Target gaps cannot be repaired by filling, widening a window, or replacing
  an event.
- The real replication result remains unavailable until the separately
  authorized Stage 45 plan is executed.

## Claim boundary

The assessment operator and protocol are frozen, but no target value has been
acquired and the real replication test has not run. A future pass can admit
only Center Hill component-total flow-class cohort replication. Universal lag,
Stage 30 override, non-Turbine component contrast, causal or physical
interpretation, and runtime promotion remain rejected.

## Evidence

The assessment operator, protocol, and gate report SHA-256 values are
respectively:

```text
8370ad5889ec0e39aff8a13492d63fcf50709a1d89a74d18c7674bc38f4104c3
a5c976927bde7084047e29f6b20ac75806ca41457562f91f2c049bdeca793803
d4297f065b1b15136db4befe65300fc3705ee292e7d4a964b53d45a83a43de22
```

All 46 gates pass with status
`stage46_component_lag_replication_assessment_protocol_frozen_targets_pending`.

## Related decisions

- ADR-085 freezes the complete target-exposure boundary and replication
  cohort.
- ADR-086 freezes the exact four-request Stage 45 target plan.
