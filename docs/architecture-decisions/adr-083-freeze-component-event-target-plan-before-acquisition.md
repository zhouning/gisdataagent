# ADR-083: Freeze Component-Event Target Plan Before Acquisition

## Status

Accepted.

## Context

Stage 41 admitted four source-only total-discharge excitation events and froze
an empirical lag-support target functional. It acquired no new target values.
All four selected one-hour source changes are Turbine-only, so any target
experiment must preserve the rejection of non-Turbine component contrast.

Before requesting public downstream data, the Kernel needs an exact event,
site, time-window, query, retry, byte, pagination, license, and post-acquisition
assessment boundary. Otherwise target availability could silently change the
event design or the empirical support thresholds.

## Options considered

### Option 1: Reuse prior Stage 32 target files

Those observations belong to different source events. Reusing them would not
test the four Stage 41 event identities.

### Option 2: Request only the downstream Stonewall site

The frozen target functional includes Smith Fork as observed graph state.
Dropping it after event selection would change the experiment.

### Option 3: Request broad annual target series

Annual requests exceed the event-local need, weaken the acquisition boundary,
and increase the opportunity for post-hoc target inspection.

### Option 4: Freeze eight bounded event-local requests

Four events times two frozen sites yields eight exact 84-hour requests. This is
sufficient for the `0..12h` lag search while retaining a small, auditable
download boundary.

## Decision

Adopt Option 4.

Freeze one Stonewall downstream and one Smith Fork graph-state request for each
Stage 41 event. Each request starts 24 hours before the source marker and ends
60 hours after it, covering the 72-hour source window plus a 12-hour target
extension. Request only continuous discharge parameter `00060` from the public
USGS Water Data OGC endpoint.

Allow at most eight logical requests, three attempts per request, `2MB` per
attempt, `16MB` persisted successful responses, and `48MB` total response bytes
in the retry worst case. Do not follow unexpected pagination. The plan itself
contains no network code and is not authorized for execution.

Preserve the frozen event order and empirical target functional. Do not permit
event reselection or threshold retuning after target values. Require fresh user
approval before execution.

## Consequences

### Positive

- Every future response value can be traced to one frozen event, site, and
  request window.
- The source selector and target functional remain outcome-blind.
- Resource use and retry behavior are explicit before acquisition.
- Existing public-domain source and license metadata are retained.

### Negative

- Target gaps may make an event or relation unassessable.
- Eight requests still require a separate acquisition and validation stage.
- Even successful lag support cannot establish component contrast, causality,
  or physical travel time.

## Evidence

The protocol and request-plan SHA-256 values are respectively:

```text
f5de9f9fb7b3f33964f2dd72490291362b5c20e9670fd65b539a36039de32fc1
28519b1c7834527da9b9b8c2bf30e15f15b293e040b264f60cdbf8df88449ef0
```

All 16 focused tests and all 37 plan gates pass with status
`stage42_component_event_target_plan_frozen_values_pending_approval`. The gate
report SHA-256 is
`4c23a499ed26e527808c83b77d863ccce2e8eb70ecca615f044941cf550dce19`.

## Related decisions

- ADR-073 admits event-local empirical lag support but rejects unsupported
  common support.
- ADR-081 admits synchronized component value support.
- ADR-082 admits source-only total-discharge events and rejects component
  contrast.
