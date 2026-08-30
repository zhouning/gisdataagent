# ADR-082: Admit Source-Only Total-Discharge Events and Reject Component Contrast

## Status

Accepted.

## Context

Stage 40 admitted complete synchronized hourly value support for Center Hill
Orifice, Sluice, Spillway, and Turbine Flow over 2021-2025. It deliberately did
not sum those values or select events because the total derivation, exclusions,
excitation gate, ranking, target functional, and claim boundary were not yet
frozen.

Stage 41 must determine whether those already acquired public values support a
new outcome-blind event experiment. It must not use known downstream outcomes
to choose events, reinterpret source quality codes, or turn interval-average
component values into commands or actions.

## Evidence boundary

The four components are exact-hour joined and summed in `cms`. Missing, null,
negative, or mismatched duplicate values fail closed. The derived total is used
only inside the selector; the complete total series is not persisted.

The source gate reuses the frozen Stage 31 73-hour excitation-identifiability
operator without threshold changes. A candidate requires an absolute one-hour
step of at least `50m3/s`, a 73-hour range of at least `100m3/s`, at least three
hours of excursion support, at least three normalized step-hours, at least
`30m3/s` standard deviation, maximum absolute lag autocorrelation no greater
than `0.97`, and lag-design condition number no greater than `50`.

Fifteen prior outcome markers, four Stage 36 target-exposed markers, and the
2024-05-15 through 2024-05-18 outcome window are excluded. Each interval is
expanded by 30 days, and the complete 73-hour candidate window must not
overlap it. The selected events preserve high/low antecedent flow and
increase/decrease direction strata and remain at least 180 days apart.

## Options considered

### Option 1: Keep Stage 40's total and event rejection indefinitely

This would preserve the strict boundary but ignore complete synchronized source
support and a reusable excitation gate.

### Option 2: Treat each component as an independently identifiable control

The unchanged gate finds 0 Orifice, 0 Sluice, 0 Spillway, and 2,542 Turbine
candidates. This evidence cannot support four-component contrast or separate
component-response claims.

### Option 3: Select total-discharge events and disclose component support

The total selector finds 2,547 eligible candidates across all four frozen
strata. It selects four independent events, but all four one-hour steps are
Turbine-only. This supports total-discharge excitation events while preserving
the negative component-diversity result.

### Option 4: Acquire new downstream values immediately

The source event manifest and target functional must be content-addressed and
reviewable before any new outcome request. Stage 41 has no network authority.

## Decision

Adopt Option 3.

Admit the exact synchronized total derivation for source-only selection and the
four frozen total-discharge excitation events. Reject non-Turbine component
contrast. Preserve quality codes without approval semantics. Freeze the
empirical lag-support set target functional for a possible later experiment,
but require fresh approval before any downstream or tributary request.

Do not admit a gate command, human action, causal intervention, observed
downstream response, physical response time, or runtime operator.

## Consequences

### Positive

- The next outcome experiment has four content-addressed, outcome-blind source
  events spanning high/low flow and increase/decrease directions.
- All known target exposures are conservatively excluded at the full-window
  level.
- The source derivation, ranking, target functional, and claim boundary are
  reproducible from the 20 Stage 40 artifacts.
- The component-diversity failure is measurable rather than implicit.

### Negative

- The selected design cannot estimate separate Orifice, Sluice, Spillway, and
  Turbine effects.
- One selected window includes two uninterpreted Turbine quality codes.
- No downstream response has been observed for the new events.
- The hourly end label still does not identify an actuation instant.

## Evidence

The protocol, candidate ledger, and event-selection manifest SHA-256 values are
respectively:

```text
e5da6a7c3a8b9dba355f41e92114cf3ae8bd726c2c6026fdb1d8fd4b5ed88f33
625b1bee79ccf1eb83059a906250497c3460eb247cdfe06d6b3fb3ef8bcab60f
3ffecd85ce74147eb11e1ccc084b4ac5b2774bae81511a416c54735b156d7e6a
```

The public evidence ledger SHA-256 is
`6c859b4cc52455beea308e2418832c9ce71a679f9ca882d3bcea9facbaf7a1d3`.
All 21 focused tests and all 37 gates pass with status
`stage41_complete_source_only_total_discharge_events_admitted`. The gate report
SHA-256 is
`46d92725139c4d9a93fadad708aea6ba9e4edcce93187cf2bcff945c1cbfe340`.

## Related decisions

- ADR-072 admits release excitation support but not universal exact lag.
- ADR-073 admits event-local lag support and rejects unsupported common support.
- ADR-081 admits synchronized component value support without event promotion.
