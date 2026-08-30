# ADR-080: Freeze component-discharge value plan before acquisition

## Status

Accepted

## Context

ADR-079 admitted four public Center Hill CWMS series only as component-discharge
source identities. It did not establish that values are complete, synchronous,
quality-supported, or usable as an aggregate release boundary. It also required
a separate bounded plan and fresh approval before any value request.

Stage 39 defines that plan without accessing a network endpoint. It binds the
Stage 38 catalog checkpoint and the Stage 34 authoritative CWMS time-series
semantics. The latter establishes that an hourly composite is a one-hour window
stored at the end of its period by default.

## Decision drivers

- Preserve the exact four Stage 38 component identities.
- Bind hourly average values to support interval `[-60m, 0m]` at each label.
- Use a source-only period aligned with the prior 2021-2025 Center Hill pool.
- Bound every request, retry, response, and total persisted byte count.
- Split requests annually so one oversized five-year response cannot silently
  expand the boundary or require pagination.
- Preserve explicit nulls and quality codes without interpreting a code as
  operational approval.
- Require all four real component values before a synchronized total is
  eligible.
- Perform only coverage, quality, duplicate-boundary, and synchronized-support
  audits after acquisition.
- Require another protocol before event selection or downstream outcomes.

## Frozen source support

The plan covers `2021-01-01T00:00:00Z` through
`2026-01-01T00:00:00Z`. Each of the orifice, sluice, spillway, and turbine
series is split into five inclusive annual windows, producing 20 exact logical
requests.

The ideal hourly grid has 43,825 unique inclusive positions per component and
175,300 component positions in total. Adjacent annual responses share their
boundary timestamp. Duplicate boundary rows must be identical before one copy
is retained.

The following value semantics are frozen:

- required office `LRN`, unit `cms`, and interval `PT1H`;
- explicit nulls are preserved and never filled;
- quality codes are inventoried without being interpreted as approval;
- timestamps are normalized to UTC;
- out-of-window values are rejected; and
- negative component values are rejected for synchronized-total eligibility.

An hourly total can be considered only when orifice, sluice, spillway, and
turbine are all real at the same timestamp. Partial sums and component
imputation are prohibited. Stage 39 does not compile or admit total values.

## Request boundary

The frozen plan allows only `cwms-data.usace.army.mil` and records:

- 20 logical requests;
- at most three attempts per request and 60 attempts in total;
- at most `1,000,000` response bytes per attempt;
- at most `20,000,000` persisted successful-response bytes;
- at most `60,000,000` response bytes across the retry worst case;
- no pagination following; unexpected pagination fails closed;
- no workspace or private data transmission; and
- no tailwater, tributary, or downstream outcome request.

The planner contains no network execution path and explicitly records that
execution is not authorized until fresh user approval is received.

## Considered options

### Option 1: Request five years in one response per component

Four requests are simpler but can exceed a response bound or require server
pagination. Automatic pagination would make the approved request count and
download ceiling conditional on server state.

### Option 2: Fetch only windows around prior events

Those windows are outcome-exposed and would not establish source availability
for selecting a new blind event pool.

### Option 3: Treat missing components as zero when forming total discharge

A missing measurement is not evidence of zero physical flux. This would create
unobserved source values and could manufacture release transitions.

### Option 4: Freeze annual source-only requests and audit before selection

This gives deterministic limits, retains all missingness, and allows the next
experiment to be designed from source support before any new target outcome is
opened.

## Decision

Adopt Option 4.

Freeze the Stage 39 component-discharge value protocol and its 20-request plan.
Do not execute the requests in this stage. After fresh approval, acquisition
may only produce raw artifacts and a coverage/quality/synchronization audit.
Event selection, target-functional definition, downstream acquisition, model
fitting, and scoring remain prohibited.

## Consequences

### Positive

- The next network boundary is exact and independently reviewable.
- Retry worst-case traffic is explicit rather than implied.
- Hourly label semantics and duplicate annual boundaries are predeclared.
- Missing component values cannot silently become zero discharge.
- Source inspection remains separated from downstream outcome access.

### Negative

- Twenty logical requests are required instead of four broad requests.
- Stage 39 adds no observed values or predictive result.
- Source coverage may still prove inadequate after acquisition.
- A further freeze is required before selecting blind events.

## Evidence

The Stage 39 protocol SHA-256 is
`b065308dd8b5e44aebd08d3da41dc6a0d822cf4aeb5c5ea5e88500ad95aa557b`.
The exact value-acquisition plan SHA-256 is
`0870a5c636d59b8074efaab199b881e4a384b58d19fd7410ca12e00a329e4f26`.

All 19 focused tests and all 34 gates pass with status
`stage39_component_discharge_value_plan_frozen_values_pending_approval`. The
gate report SHA-256 is
`6b205a953f4f69f27322366fdbdf86cb7241e03529d13e4fa61fcdab5a179802`.

## Related decisions

- ADR-075 separates observation labels from physical process time.
- ADR-079 admits component-discharge identities and requires a separate value
  plan.
