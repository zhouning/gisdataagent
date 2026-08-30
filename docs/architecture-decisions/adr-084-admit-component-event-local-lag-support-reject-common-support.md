# ADR-084: Admit Component-Event Local Lag Support, Reject Common Support

## Status

Accepted.

## Context

Stage 41 froze four source-only total-discharge events before target values.
Stage 42 then froze and, after explicit approval, executed eight bounded USGS
requests: one Stonewall downstream outcome and one Smith Fork observed graph
state for each event. The event selector and empirical lag-support operator
were hash-frozen before these target values existed.

The Kernel must decide whether the new values support event-local empirical
relations, a cross-event common lag, component-specific contrast, or stronger
causal and physical claims. Missing Smith Fork samples and source quality
metadata must remain explicit.

## Options considered

### Option 1: Admit one common lag from the best-lag majority

Two events select 5h and two select 6h. A majority or tie-breaking rule was not
frozen and would discard the set-valued acceptance criterion.

### Option 2: Broaden the per-event tolerance after seeing outcomes

Retuning the `r >= 0.8`, `0.02` best-loss, 60-pair, or interior-best-lag rules
would violate the Stage 42 blind protocol.

### Option 3: Admit event-local sets and require their exact intersection for
common support

This applies the frozen operator unchanged and separates evidence that holds
within each event from evidence that generalizes across all four events.

## Decision

Adopt Option 3.

Reconstruct 72 hourly source totals from the exact synchronized sum of the
four component-discharge streams. Aggregate each downstream target from two
real half-hour samples per open-closed hour, preserve missing hours without
filling, and evaluate all frozen lags from 0 through 12 hours.

Admit the four event-local support sets:

```text
2025 high increase  {5}
2023 high decrease  {5}
2021 low increase   {6, 7}
2021 low decrease   {6}
```

All four responses pass the frozen detectability gate. Reject common empirical
support because the intersection of the four admitted sets is empty.

Preserve Smith Fork as an observed graph state at COMID `18421273`. Preserve
its incomplete support in three events without interpolation. Preserve USGS
approval and qualifier fields as source metadata without assigning scientific
approval semantics.

All selected changes remain Turbine-only. Do not infer non-Turbine component
contrast. Do not promote an empirical relation to causal response, physical
travel time, hydraulic edge time, tributary-mouth flux, or a runtime operator.

## Consequences

### Positive

- Four outcome-blind source events now have reproducible event-local empirical
  relation support.
- The absence of common support is represented directly rather than hidden by
  a best-lag summary.
- Target and graph-state gaps remain auditable.
- The evidence remains isolated from causal, physical, and runtime contracts.

### Negative

- No single lag can be used across all four component-total events.
- Turbine-only events cannot test component contrast.
- The evidence cannot calibrate a deterministic runtime delay.

## Evidence

All eight Stage 42 requests succeeded on the first attempt and persisted
`1,112,317` bytes. The four best lags are `5, 5, 6, 6h`, with Pearson
correlations `0.8217600767931865`, `0.8790617592474798`,
`0.9244168189654225`, and `0.919474372916006`.

The Stage 43 ledger SHA-256 is
`91c85ba78d1f4bd8e500b800b3496f395b378244549c7e0b1a68fa107e85e94a`.
All 10 focused tests and all 43 gates pass with status
`stage43_component_event_local_lag_support_admitted_common_support_rejected`.
The gate report SHA-256 is
`c18c11f2d637e272304b1b60a9ab39e8e135a27cc6fb4e89a86a531a4471c46c`.

## Related decisions

- ADR-073 admits event-local empirical support and requires intersection for
  common support.
- ADR-082 freezes the source-only component-total events and rejects component
  contrast.
- ADR-083 freezes the component-event target protocol before acquisition.
