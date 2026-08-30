# ADR-030: t-route Execution Semantics and Fixed-Kernel Initialization

**Date**: 2026-07-27  
**Status**: Execution-layer semantics admitted; fixed-commit kernel initialization gate failed

## Context

ADR-029 rejected promotion of the current fixed-commit t-route Muskingum-Cunge (MC) integration after an outcome-free
state, pulse-amplitude, and timestep matrix. That decision deliberately did not attribute the failure to the MC method or
the full t-route application. An unresolved possibility was that the local serial-chain adapter had omitted or reversed a
critical part of the official Python/Cython network driver.

The project receives no user-supplied data. This audit therefore uses fixed public source from `NOAA-OWP/t-route` commit
`12a8eae0cdfed437143c590659fa7077605a5e70`, the verified public RouteLink fixture, and synthetic boundary pulses. It loads
no observed discharge, action, forcing, or outcome values.

## Decision

Admit the following execution-semantic findings for an open-loop serial chain without reservoirs or data assimilation:

1. The official driver separately aggregates previous-step and current-step upstream discharge.
2. The official default is `assume_short_ts=False`. Under that default the next segment receives the upstream segment's
   previous discharge as `qup` and newly computed discharge as `quc`.
3. `assume_short_ts=True` replaces `quc` with `qup`, including at an external reach boundary.
4. `qts_subdivisions` only selects a held lateral-flow time column. It is not spatial reach subdivision or an internal
   solver substep.
5. The Python driver writes one global `dt` to the parameter table and casts inputs to float32. Lateral `ql` is a flow rate;
   the Fortran kernel forms `C4=(ql*dt)/D`.
6. The local adapter now exposes `assume_short_timestep: bool = False`, and its call traces match both official recursion
   modes for the scoped serial-chain case.

This closes the hypothesis that omitted default upstream recursion in the full Python driver explains the ADR-029 matrix
failure. It does not claim equivalence to branching scheduling, reservoir routing, data assimilation, parallel subnetworks,
or the full t-route application.

## Initialization Finding

The fixed Fortran source is not numerically well-defined under its declared variable contracts:

- `qdc` is declared `intent(out)` and read in the wet/dry guard before assignment (lines 20 and 73-74);
- `secant2_h` declares `Qj`, `C1`, `C2`, `C3`, and `C4` as `intent(out)`, then computes `X` from `Qj` or `C1..C4` at
  lines 281/285/291/295 before assigning the coefficients at lines 309-312 and `Qj` at lines 327-331;
- `velp` is passed through the ABI but the compiler confirms it is unused, so zeroing velocity in the full driver cannot
  explain the response difference.

The apparent intent is to reuse secant values across calls or iterations, but `intent(out)` makes those dummy arguments
undefined on subroutine entry and the caller does not initialize the first values. This is a fixed-source implementation
defect, not a property of Muskingum-Cunge mathematics.

Two isolated cold-process traces were run at `dt=300s`, background `2m3/s`, and pulses `0.1/1/10m3/s`. Both finished the
240-hour warmup at exactly `1.9999922513961792m3/s`. One trace executed only MC calls; the other advanced an independent
conservative Manning operator after the same MC calls. The operators share no state. For the `10m3/s` pulse, MC net outlet
volume differed by `454.331m3`; negative outlet volume differed by `2.880m3`. Required call-order invariance therefore
failed. The static undefined-read finding and the dynamic cold-process sensitivity reinforce each other. They do not prove
that every negative lobe is caused by this defect.

## Reach and Mode Evidence

The 54-case reach diagnostic repeats all 27 registered state-amplitude-timestep cases under both recursion modes.

Under the official default, 24 of 27 cases have an above-tolerance negative lobe at the outlet and at some internal reach.
The first affected feature is `1622797` in 21 cases, `1622687` in one, and `1623573` in two; the three `100m3/s`, `3600s`
cases have none. Across 211 above-tolerance reach responses, the minimum negative excursion is 240 float32 ULPs, the median
is approximately 80,654 ULPs, and the maximum is over 7.7 million ULPs. The default failure is therefore not merely
sub-ULP differencing noise. Only 26 of 54 registered timestep comparisons pass.

With `assume_short_ts=True`, no outlet case has a negative lobe. Six cases have internal accumulated negative volume, but
each minimum excursion is only 0.5 ULP and none reaches the outlet. This mode passes only 9 of 54 timestep comparisons,
worse than the official default. It was not pre-registered for promotion and is retained only as a diagnostic switch.

## Consequences

Keep the unmodified fixed-commit runtime as reproducibility evidence only. It cannot be a professional Geospatial Kernel
operator because it fails initialization, call-order invariance, negative-response, and timestep-stability gates.

The next MC experiment must use an explicitly derived diagnostic source in which carry variables have declared, initialized
state. It must never be labeled official or silently substituted for the fixed source. Run the same outcome-free matrix on
that derived runtime to determine which failures remain after initialization is defined. In parallel, continue with an
independently implemented conservative kinematic-wave comparator; do not make promotion depend on repairing one external
baseline.

This decision rejects one fixed source implementation and its current adapter/runtime combination. It does not reject the
MC method, t-route as a whole, the Geospatial Kernel mission, or the proposition that geographic laws belong inside GWM.

## Artifact Identity

- execution-semantics report: `d5858ca8e0ce1eafee04dc009f24f43003b584ab069b8a822f0dfd70efcc151d`;
- default/short-ts reach-response report: `394e6a0cbf2f0fcde2148841322d0a67f6cc67f7e2fd4d8bf7af505b7a0b3481`;
- isolated call-order-sensitivity report: `7092f7b648809b7819ce0665dcac71a2b79a8191768ac0156c970f483e520ca1`.

## Claim Boundary

- `adapter_default_chain_semantics_match=true`
- `full_t_route_application_equivalence_claimed=false`
- `fixed_commit_kernel_initialization_gate_passed=false`
- `call_order_invariance_passed=false`
- `default_outlet_negative_lobe_cases=24/27`
- `short_timestep_mode_promoted=false`
- `all_negative_lobes_explained_by_initialization_defect=false`
- `generic_muskingum_cunge_method_rejected=false`
- `professional_transfer_operator_certified=false`
- `geospatial_kernel_validated=false`
