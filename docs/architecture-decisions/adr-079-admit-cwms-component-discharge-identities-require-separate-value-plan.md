# ADR-079: Admit CWMS component-discharge identities, require separate value plan

## Status

Accepted

## Context

ADR-078 preserved the negative Stage 36 hydraulic-boundary result and concluded
that another blind experiment must first identify a directionally meaningful
action or discharge-flux source independently of the downstream outcome. The
public Center Hill tailwater-elevation marker cannot supply that semantic role:
it is a local hydraulic state that may include backwater.

A user-approved, metadata-only USACE CWMS request screened the LRN TIMESERIES
catalog for Center Hill. The exact request was limited to one logical request,
three attempts, and one megabyte. It sent no workspace data and requested no
time-series values. The first attempt returned 62,337 bytes and 37 catalog
entries with no pagination token.

The catalog contains four hourly, manual-revision discharge series with
component-specific names and explicit aliases. This resolves source identity,
but catalog names and extents alone do not establish value continuity, command
semantics, human decisions, causal intervention, or runtime admissibility.

## Decision drivers

- Preserve the exact approved request boundary and raw response hash.
- Reproduce and bind the Stage 37 negative-result ledger and gates.
- Select only exact `1Hour.1Hour.man-rev` component discharge identities.
- Exclude similarly named daily forecast series.
- Retain native `cms`, LRN office, interval, time-zone, alias, and extent
  metadata.
- Treat extents as catalog assertions, not verified complete coverage.
- Admit no values without a separate bounded plan and fresh approval.
- Reject gate-command, human-action, causal-intervention, and runtime
  promotion through typed refusal controls.

## Catalog result

The checkpoint admits these four source identities:

| Component | Explicit alias | Catalog earliest time | Catalog latest time |
|---|---|---|---|
| Orifice | `Orifice Flow` | `2008-08-04T06:00:00Z` | `2026-07-28T05:00:00Z` |
| Sluice | `Sluice Gate Flow` | `2004-09-30T19:00:00Z` | `2026-07-28T05:00:00Z` |
| Spillway | `Spillway Flow` | `1987-05-20T05:00:00Z` | `2026-07-28T05:00:00Z` |
| Turbine | `Turbine Flow` | `1987-05-20T05:00:00Z` | `2026-07-28T05:00:00Z` |

All four use office `LRN`, units `cms`, interval `1Hour`, zero interval
offset, and catalog time zone `US/Central`. Their identifiers are:

- `CETT1-CENTER_HILL.Flow-Orifice.Ave.1Hour.1Hour.man-rev`;
- `CETT1-CENTER_HILL.Flow-Sluice.Ave.1Hour.1Hour.man-rev`;
- `CETT1-CENTER_HILL.Flow-Spillway.Ave.1Hour.1Hour.man-rev`; and
- `CETT1-CENTER_HILL.Flow-Turbine.Ave.1Hour.1Hour.man-rev`.

The catalog repeats identical extent records for the sluice and spillway
series. Stage 38 records both raw and unique extent counts rather than treating
duplicate catalog metadata as additional temporal support.

## Considered options

### Option 1: Treat the four series as observed gate commands

Component discharge is a physical flux measurement or estimate. It does not
identify a command, its issue time, the operator, or the decision process.

### Option 2: Infer continuous historical availability from catalog extents

An earliest and latest timestamp does not establish completeness, sampling
regularity, revision history, quality codes, or event-window support.

### Option 3: Fetch all four value histories immediately

This would exceed the approved metadata-only research boundary and would leave
time windows, page sizes, byte limits, missing-value policy, and blinding
semantics unspecified.

### Option 4: Admit catalog identities and freeze a later value plan

This narrows the next experiment to directionally meaningful flux sources
while keeping value acquisition and scientific promotion independently gated.

## Decision

Adopt Option 4.

Admit Stage 38 only as a public component-discharge source-identity checkpoint.
Preserve the Stage 37 negative result. Do not admit historical values,
continuous coverage, gate commands, human actions, causal interventions, or
runtime operators. Require a separate bounded value-acquisition plan and fresh
user approval before contacting a CWMS value endpoint.

## Kernel versus traditional GIS implementation

A conventional catalog script can filter names and display aliases. The
Geospatial Kernel responsibility is the executable claim boundary: exact
content-addressed evidence, exclusion of near-name forecast series, preservation
of the prior negative result, and typed refusal of unsupported operational or
causal promotion.

## Consequences

### Positive

- Four directionally meaningful component-discharge source identities are now
  available for planning a later blind experiment.
- The approved one-request boundary and raw response are reproducible.
- Similar daily forecasts cannot silently enter the admitted source set.
- Catalog metadata cannot be consumed as commands or runtime actions.

### Negative

- Stage 38 adds no discharge values and no positive hydraulic response result.
- Missingness, quality, latency, revisions, and event-window coverage remain
  unknown.
- Component flux still does not reveal gate commands or human decisions.
- A new protocol and explicit approval are required before value acquisition.

## Evidence

The raw catalog response SHA-256 is
`845f357258d6c2729363df7eb0ba85735a35dbdfc82e8e455d34a1f1c66a2312`.
The acquisition manifest SHA-256 is
`2c908e632c9f389730f7c5184ed719bdc87bf49f5058ee29832ef19c8d3601ac`.
The Stage 38 ledger SHA-256 is
`1cbd80d6ffde6c142dbf2f364475c6b94713b93d8f6de348d8bfecb40e4af7b4`.

All 18 focused tests and all 34 gates pass with status
`stage38_cwms_component_discharge_catalog_checkpoint_admitted`. The gate report
SHA-256 is
`0eeab2e425200a0698041acdb64ae91bc4233c6c657b55817fc7b303862ea021`.

## Related decisions

- ADR-077 freezes observed hydraulic-boundary events and rejects action
  semantics.
- ADR-078 attributes the negative boundary result and rejects posthoc rescue.
