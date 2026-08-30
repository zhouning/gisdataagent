# ADR-086: Freeze Four-Request Component-Lag Replication Target Plan

## Status

Accepted.

## Context

Stage 44 compiled a complete known target-exposure boundary and selected four
source-only component-total events for a prospective replication test. The
strict hypothesis requires `5h` support in both high-flow directions and `6h`
support in both low-flow directions. Target values must not influence the
events, hypothesis, or empirical operator.

The next decision is which new observations are minimally necessary and how
their acquisition can be bounded before any network request.

## Options considered

### Option 1: Repeat the Stage 42 eight-request design

This would acquire Stonewall outcomes and Smith Fork graph states for every
event. Smith Fork was useful contextual state in Stage 43 but is not an input
to the frozen replication decision.

### Option 2: Acquire broad Stonewall periods

Broad windows would simplify later reuse but expand both target exposure and
the opportunity for post-hoc analysis.

### Option 3: Freeze one exact Stonewall request per event

This supplies only the downstream series used by the frozen empirical-lag
operator and minimizes requests, bytes, and new target exposure.

## Decision

Adopt Option 3.

Freeze four `USGS-03424860 / 00060` continuous-discharge requests. Each begins
at the frozen 72-hour source window start and ends 12 hours after its end,
yielding 84 elapsed hours and at most 169 inclusive half-hour positions.

Allow only HTTPS GET to
`api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items`. Bound each
attempt to 2 MB, each request to three attempts, successful persisted content
to 8 MB, and retry worst-case response content to 24 MB. Reject unexpected
pagination, identity, statistic, unit, time-grid, duplicate, non-finite,
redirect, and response-size behavior.

Freeze an executor against the exact plan hash. In addition to external user
approval, require its explicit `--execute-frozen-plan` switch. Stage 45 plan
compilation does not invoke the executor and makes zero network requests.

## Consequences

### Positive

- The confirmatory acquisition is limited to four necessary target series.
- Exact URLs, windows, retry limits, licenses, output names, and validation
  rules are fixed before values.
- Smith Fork and all other unrelated values remain outside the request scope.

### Negative

- The new cohort will not provide independent Smith Fork graph-state context.
- Missing Stonewall support cannot be repaired by widening or replacing an
  event after acquisition.
- Separate explicit approval is required before executing the frozen plan.

## Claim boundary

The target protocol and request plan are frozen, but execution authorization is
false. No target value has been acquired and the replication test has not run.
Stage 43 remains exploratory event-local evidence; Stage 30 falsification,
universal lag, non-Turbine contrast, causal or physical relation, and runtime
operator claims remain unchanged and rejected.

## Evidence

The protocol, request plan, and gate report SHA-256 values are respectively:

```text
6c24d7b507bd4046dcd9e5ff329a090c57ab4e2a760609364f1b5e7a4bca790b
4b100d5bd2286e5df149a5fb2724162fc0eb9d5da8632a1a26e8dc57f89cf08b
6324d80b982f7364f98af972ac451418fb66ec3a82ac2de5a89e9990735ae4a3
```

All 45 gates pass with status
`stage45_component_lag_replication_target_plan_frozen_values_pending_approval`.

## Related decisions

- ADR-084 admits Stage 43 event-local support and rejects common support.
- ADR-085 freezes the complete exposure boundary and source-only replication
  cohort.
