# ADR-081: Admit synchronized component-value support, reject operational promotion

## Status

Accepted

## Context

ADR-080 froze 20 exact source-only CWMS requests for the four Center Hill
component-discharge series. After explicit approval, all requests completed on
their first attempt. No tailwater, tributary, or downstream outcome values were
requested.

Stage 40 must determine what the acquired values actually support before an
event selector or derived total is defined. Complete timestamps alone are not
enough: annual boundary duplicates must agree, nulls and negative values must
remain visible, and CWMS quality codes cannot be interpreted as operational
approval without separate semantics.

## Acquisition result

All 20 logical requests succeeded in 20 attempts and persisted `4,225,697`
bytes. This is below the frozen `20MB` successful-response boundary. Every raw
artifact retains its exact URL, retrieval time, TLS verification, SHA-256, and
source terms.

Each component returned five annual payloads with 43,829 raw rows. Four shared
annual boundary rows were byte-semantically identical by timestamp, value, and
quality code. Deduplication therefore leaves exactly 43,825 unique hourly
positions from `2021-01-01T00:00:00Z` through
`2026-01-01T00:00:00Z` for every component.

| Component | Missing | Null | Negative | Zero | Positive |
|---|---:|---:|---:|---:|---:|
| Orifice | 0 | 0 | 0 | 35,361 | 8,464 |
| Sluice | 0 | 0 | 0 | 43,480 | 345 |
| Spillway | 0 | 0 | 0 | 42,941 | 884 |
| Turbine | 0 | 0 | 0 | 22,259 | 21,566 |

The quality-code inventories are:

| Component | `-2147480957` | `-2147478653` | `0` |
|---|---:|---:|---:|
| Orifice | 83 | 1,571 | 42,171 |
| Sluice | 83 | 1,501 | 42,241 |
| Spillway | 78 | 1,535 | 42,212 |
| Turbine | 4 | 1,664 | 42,157 |

These codes are preserved as source metadata. Stage 40 does not claim that any
code means approved, final, command-issued, or operationally available.

## Decision drivers

- Reproduce the exact Stage 39 protocol, plan, state, manifest, and raw hashes.
- Require identical annual boundary duplicates before deduplication.
- Preserve missing, null, negative, zero, positive, and quality-code counts.
- Admit synchronized support only when all four components are real and
  nonnegative at the same hour.
- Do not compute a total-discharge value series during support audit.
- Keep source support separate from event definition and downstream outcomes.
- Reject command, human-action, causal, physical-time, and runtime promotion.

## Considered options

### Option 1: Interpret quality code `0` as operational approval

The acquired API payload provides integer codes but Stage 40 has no frozen
authoritative mapping that would justify operational semantics.

### Option 2: Immediately persist the four-component sum

The support gate is complete, but producing a derived total would create a new
scientific artifact before its lineage, units, timestamp support, quality
combination, and downstream use are frozen.

### Option 3: Select the largest component changes now

Source values may inform a later outcome-blind selector, but selection rules,
exclusions, minimum excitation, event separation, and target functional must be
frozen first.

### Option 4: Admit only complete synchronized source support

This records the strong coverage result without converting it into an action,
event, causal edge, or runtime transition.

## Decision

Adopt Option 4.

Admit complete hourly coverage for all four component series and complete
synchronized four-component structural support for all 43,825 hours. Reject
quality-code approval semantics. Do not compile total-discharge values or select
events. Do not acquire downstream outcomes. Require a separate source-only
event-selection protocol before the next experiment.

## Consequences

### Positive

- Five years of source support are complete with no fill or negative values.
- All annual duplicate boundaries are independently verified.
- Every hour is structurally eligible for a later four-component total.
- Acquisition provenance and raw values are content addressed.

### Negative

- Quality-code operational meaning remains unresolved.
- Most orifice, sluice, and spillway hours are zero, so event identifiability
  still requires an excitation-aware rule.
- No total series, event, downstream response, predictive increment, or runtime
  operator is admitted.

## Evidence

The acquisition-state and manifest SHA-256 values are respectively
`683837d491b41e02103aeca85851eeb07aee27f17f49947b37a49421f24d36cf`
and
`ed77dacf3743713817177ba6fd7e553c71823693d831af5d38523dbb5fb45a0b`.
The Stage 40 support ledger SHA-256 is
`d4d8b1b145ddd9f45e6c5d0905d6d5cabbdf99da0414cacaa43f6c0798d70de1`.

All 28 focused acquisition and support tests and all 38 gates pass with status
`stage40_complete_component_discharge_source_support_admitted`. The gate report
SHA-256 is
`6d9c78138d635467814a372b2faafb9eb534fd6c8cc66ebe4063e933f5a72dec`.

## Related decisions

- ADR-079 admits component-discharge source identities only.
- ADR-080 freezes the bounded source-only value plan.
