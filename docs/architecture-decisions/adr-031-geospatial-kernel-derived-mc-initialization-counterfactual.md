# ADR-031: Derived MC Initialization Counterfactual

**Date**: 2026-07-27  
**Status**: Initialization defect isolated; transfer-response failure remains

## Context

ADR-030 found two facts in the fixed t-route MC baseline: the local serial-chain adapter matches the scoped official
execution semantics, and the fixed Fortran kernel reads secant carry variables before they are defined under their declared
`intent(out)` contracts. A cold-process trace test also failed required call-order invariance. That left an important causal
question: are the negative response lobes and timestep instability merely consequences of undefined initialization?

## Decision

Build one explicitly derived diagnostic runtime from fixed commit
`12a8eae0cdfed437143c590659fa7077605a5e70`. Preserve the acquired official source and official shared library byte for
byte. Apply only patch `explicit_secant_carry_initialization_v1`:

1. initialize caller variables `qdc`, `Qj`, `Qj_0`, `C1`, `C2`, `C3`, `C4`, and `X` before the secant loop;
2. declare `Qj` and `C1..C4` as `intent(inout)` in `secant2_h`, matching their apparent carry-state use;
3. retain `X` as `intent(out)` and leave all equations, geometry, coefficients, tolerances, compiler optimization, RouteLink
   parameters, boundary pulses, warmup, and response metrics unchanged.

The derived build is permanently labeled `official_source_unmodified=false`, `derived_diagnostic_only=true`, and
`professional_baseline_eligible=false`. The official loader rejects it; only the dedicated diagnostic loader accepts it.

## Evidence

The derived source and library have identities:

- official core source: `1c0e47b3528c3fdf20c960408e41138921cb903e5035bd19e6c4e68f8f4b46da`;
- derived core source: `90a7fd29088916174ba4198c00a88d171906676562245a6f2e95fb2236606e80`;
- explicit patch: `1b215b9f96f2e95697fab4470ab8ff5a4db6d4ba111bf156fca52a381a2c1061`;
- derived Linux/aarch64 shared library: `42589a475030bada760648385fcf7d2afcb23bef19046756ce9c89c57a516052`.

The isolated cold-process traces now finish with zero difference in net outlet volume, negative outlet volume, minimum
response, `t05`, `t50`, and `t95`. The initialization patch therefore fixes the measured trace-invariance defect.

It does not fix the transfer-response matrix:

- 24 of 27 outlet cases still have above-tolerance negative lobes;
- the same first-negative-reach distribution remains: feature `1622797` in 21 cases, `1622687` in one, `1623573` in two,
  and none in three;
- all 211 above-tolerance reach responses remain at least 240 float32 ULPs from zero;
- only 26 of 54 timestep comparisons pass;
- diagnostic net recovered fraction ranges from approximately `0.7164` to `3.4751`.

The derived runtime exposes no authoritative MC storage, so the recovery range remains a physical-stock diagnostic rather
than a proof of MC mass nonconservation. Negative outlet response and timestep instability are directly observable and do
not depend on the storage proxy.

## Consequences

The undefined initialization path is a real fixed-source defect but is not a sufficient explanation for ADR-029's transfer
failure. Do not spend the next kernel cycle tuning initialization or selecting `assume_short_ts=True`; those paths have now
been falsified as promotion remedies under the registered protocol.

Retain the derived runtime only as a counterfactual artifact. The next comparison must be an independently implemented,
conservative kinematic-wave operator with explicit state, flux, spatial subdivision, and timestep convergence gates. This
provides a geographic transport core whose invariants the project owns, while t-route remains external evidence rather than
a hidden dependency of the Geospatial Kernel mission.

## Artifact Identity

- derived build manifest: `5dc6cba8e1260db25499791e8dc5282f5705c72b0500f3e32aec8ec7c9988c9f`;
- derived 27-case response matrix: `83d5ebeaada13505d1d51902903d8d79203e3f3dc243b366b3563b0930781447`.

## Claim Boundary

- `initialization_defect_removed_for_diagnostic=true`
- `cold_process_trace_invariance=true`
- `derived_outlet_negative_lobe_cases=24/27`
- `derived_timestep_stability_passed=26/54`
- `initialization_defect_sufficient_explanation=false`
- `derived_runtime_is_official=false`
- `professional_baseline_eligible=false`
- `professional_transfer_operator_certified=false`
- `geospatial_kernel_validated=false`
