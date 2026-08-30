# ADR-038: Reject state variation and advective velocity as phase remedies

- Status: Accepted
- Date: 2026-07-28
- Scope: Geospatial Kernel transport-closure development after ADR-037

## Context

ADR-037 attributed the failed predictive phase gate to a propagation closure
that is too slow on the outcome-visible development window. Its initial-state
Manning `dQ/dA` path times were 15.56 hours at Center Hill and 2.64 hours at
J. Percy Priest, while the diagnostic prediction corrections were -10 hours
and -2 hours. Before changing the operator equation, two narrower hypotheses
had to be tested without using observation outcomes:

1. whether the initial hydraulic state was unrepresentative and a
   state-dependent Manning calculation could contain much faster path times;
2. whether public NWM velocity supported a faster propagation scale than the
   RouteLink Manning closure.

A typed public path-response diagnostic now traces the exact directed
action-to-outlet path and computes per-reach Manning area, `dQ/dA` celerity,
and travel time. It explicitly reports a zero-flow path as nonpropagating
rather than emitting infinity or NaN. It remains a diagnostic and does not
admit its travel-time prior as a flood-wave lag.

The public acquisition used NWM retrospective streamflow and velocity for all
672 hourly states from 2022-03-31T01:00:00Z through
2022-04-28T01:00:00Z. Four deduplicated Zarr chunks were acquired through the
public NOAA NWM retrospective store. The already verified local time chunk was
reused. No action, gauge-observation, or saved prediction values were read by
the acquisition or envelope calculation.

NWM streamflow is a modeled state that may contain nudging, not ground truth.
NWM velocity is an advective-velocity proxy, not flood-wave celerity. These
semantic limits are represented in the report and constrain the claims below.

## Evidence

| Public state diagnostic, q05/q50/q95 | Center Hill | J. Percy Priest |
| --- | ---: | ---: |
| Manning wave path time | 15.58/16.14/16.80 h | 2.44/2.63/2.84 h |
| NWM velocity advective path time | 20.49/21.50/22.40 h | 3.21/3.42/3.91 h |
| Manning celerity / NWM velocity | 1.270/1.315/1.505 | 1.230/1.329/1.579 |
| Manning area / NWM `Q/velocity` area proxy | 1.000/1.029/1.122 | 0.999/1.030/1.173 |

All 672 states in both systems produced finite positive path responses. There
were no streamflow or velocity fill values, no nonpropagating path hours, and
no invalid advective path hours.

The Center Hill Manning q05-to-q95 path-time range is only 1.22 hours, and its
fastest q05 response remains approximately 15.58 hours. It therefore does not
approach the approximately 6-hour action-to-observation phase or explain the
approximately 10-hour prediction correction. The J. Percy Priest range is
only 0.40 hours, and its fastest q05 response remains approximately 2.44
hours; it likewise does not explain the approximately 2-hour prediction
correction.

The NWM advective path times are longer, not shorter, than the Manning wave
times. Substituting NWM velocity for `dQ/dA` would therefore move both systems
away from the required phase direction. This comparison does not test a
diffusive-wave or local-inertial celerity, because advective velocity and
flood-wave signal speed are different physical quantities.

The full-window Manning-to-NWM area ratios remain close to one and strengthen
the narrower ADR-037 result: gross initial `Q -> A` scaling is not supported
as the primary defect. NWM area is still only a modeled proxy and cannot
validate the cross-section closure.

## Decision

Reject the hypothesis that ordinary state variation within the present
Manning closure can explain the phase failure. Do not promote a dynamic
Manning path time from this window into a predictive correction.

Reject NWM advective velocity as a substitute flood-wave celerity. Retain it
only as an independently sourced scale diagnostic with its semantic type
preserved.

Do not fit a celerity multiplier from the ratio to the observed phase. The
outcomes were visible before this diagnostic was defined, and neither system
provides independent physical evidence for such a multiplier.

Retain the finite-volume conservation core, complete tributary DAG, typed path
support, and mass ledger. The next transport work is:

1. audit the boundary and gauge spatial measures against the RouteLink path,
   including effective partial-reach lengths;
2. define analytic response-family gates that distinguish kinematic,
   diffusive-wave, and local-inertial behavior before viewing a new holdout;
3. implement the smallest conservative candidate whose additional term has a
   physical state and an independently checkable limiting case;
4. freeze public multi-system evaluation only after the operator family and
   missing/negative observation rules are fixed.

## Artifacts

- Celerity-envelope plan SHA256:
  `c7a6aa31771f3af709b6916553b32104ebb1b3d3a8ce8e56e13ce0035dadb7fe`
- Celerity-envelope report SHA256:
  `f2511dc889110089e30b41389d43ad3fd199e88862a48f511a4663f4f90a2afe`
- Center Hill path-response CSV SHA256:
  `40aecf9d1a93a348bcd6821e238ae6cb615e26da174c00ab9a8fb4564fdcd3c1`
- J. Percy Priest path-response CSV SHA256:
  `0512f0bdb0c6e6738a9c59c8847e0437e471a5b06d551480d37234eead6e699a`

## Claim boundary

- `public_data_without_user_supplied_data=true`
- `outcome_values_used_by_envelope=false`
- `state_variation_primary_phase_remedy=false`
- `nwm_velocity_is_flood_wave_celerity=false`
- `nwm_advective_velocity_substitution_supported=false`
- `initial_area_scaling_primary_failure=false`
- `celerity_multiplier_admitted=false`
- `operator_form_admitted=false`
- `geospatial_kernel_validated=false`
