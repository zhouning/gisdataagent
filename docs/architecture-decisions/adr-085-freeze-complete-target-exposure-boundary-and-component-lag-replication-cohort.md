# ADR-085: Freeze Complete Target Exposure Boundary and Replication Cohort

## Status

Accepted.

## Context

Stage 43 found an exploratory flow-class pattern in four outcome-blind source
events: both high-flow events supported `5h`, while both low-flow events
supported `6h` or a set containing `6h`. The four-way support intersection was
empty, so no common lag was admitted.

A confirmatory cohort must be selected without reusing target-exposed periods.
The Stage 41 exclusion inventory contained 15 event markers, four Stage 36
markers, and one Stage 28 outcome window. It did not include earlier broad
Center Hill development and holdout outcome windows. A provisional Stage 44
high-increase candidate at `2021-12-30T15:00:00Z` lies inside the already
inspected development window and therefore cannot be called blind.

## Options considered

### Option 1: Keep the Stage 41 exclusion inventory

This would preserve more candidates but falsely classify target-exposed source
periods as blind.

### Option 2: Exclude only the newly discovered development window

This fixes the observed collision but leaves the protocol vulnerable to other
known acquisition windows scattered across earlier experiments.

### Option 3: Compile a hash-bound inventory of all known target exposures

This makes the exclusion boundary independently reproducible, retains actual
request boundaries, and permits source selection only after the inventory is
complete.

## Decision

Adopt Option 3.

Hash-bind 15 authoritative acquisition manifests, outcome reports, and sealed
protocols. Extract all known `USGS-03424860 / 00060` value request boundaries,
retain acquisition buffers, and merge 34 records into 27 unique intervals.
Expand every interval by 30 days before evaluating a complete 73-hour source
event window.

Apply the unchanged component-total source selector and 180-day inter-event
separation. Freeze four Turbine-only events:

```text
high increase  2023-01-29T01:00:00Z
high decrease  2025-01-22T20:00:00Z
low increase   2021-04-28T17:00:00Z
low decrease   2023-07-29T04:00:00Z
```

Freeze the confirmatory hypothesis before any new target plan or value: both
high-flow directions must support `5h`, both low-flow directions must support
`6h`, and all four event-local responses must pass the unchanged Stage 43
operator. Reject partial direction or flow-class success. Forbid event
reselection and target-operator retuning after values.

Stage 44 does not create a target request plan. A later stage must freeze a
bounded plan and obtain fresh user approval before any request.

## Consequences

### Positive

- The confirmatory cohort has a reproducible known-exposure boundary.
- Broad development and holdout windows can no longer silently leak into blind
  event selection.
- The exploratory `5h/6h` pattern now has a strict prospective failure rule.

### Negative

- Eligible candidates fall from 2,547 under Stage 41 to 1,343 under the
  complete inventory.
- Only 3 high-increase and 11 high-decrease candidates remain.
- All selected events remain Turbine-only, so component contrast is unavailable.

## Claim boundary

The source cohort and hypothesis are frozen, but the replication test has not
run. A future pass can admit only Center Hill component-total flow-class cohort
replication. It cannot establish a universal lag, overturn the Stage 30
historical falsification, or admit a causal response, physical travel time,
hydraulic edge time, non-Turbine component contrast, or runtime operator.

## Evidence

The target exposure inventory, replication protocol, candidate ledger, event
manifest, and gate report SHA-256 values are respectively:

```text
ccb102452ec522c8303d52d71fc01969504f668e5c17f17011eac3041517aa9d
ee84167cf3b58b6ce1721795286f6539448f9fec5d781cd2212abfc67e47006d
8ee23589977a0bf0520da90a4fb062b72f7448ba05fca4cda2ad84da2564f12b
b98851b30c5c3556eb52daff493546d7832e072beee256d9a6dd82e5c99abe9f
1481f7426bd0102a2f1661a6de9c903c99d20ef1607d122989ec2f76f7107a49
```

All 44 gates pass with status
`stage44_component_lag_replication_cohort_frozen_source_only`.

## Related decisions

- ADR-073 requires exact support-set intersection for common empirical support.
- ADR-082 freezes the original source-only component-total events.
- ADR-084 admits Stage 43 event-local support and rejects common support.
