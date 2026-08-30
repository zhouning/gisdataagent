# ADR-040: Fix analytic response gates before implementing the next equation

- Status: Accepted
- Date: 2026-07-28
- Scope: Geospatial Kernel transport-family selection after ADR-039

## Context

ADR-037 through ADR-039 eliminated timestamp support, tributary topology,
ordinary hydraulic-state variation, NWM advective velocity, and endpoint
measure error as primary explanations for the failed kinematic-wave phase
gate. The next step changes the transport equation. Because the development
outcomes are already visible, equation selection cannot be justified by
trying several implementations against those outcomes.

An outcome-independent analytic protocol now fixes the limiting behavior that
candidate solvers must reproduce. It operates on an incremental
cross-section-area pulse whose spatial integral is incremental water volume.
The three linearized reference families are:

| Family | Reference equation | Distinguishing moment behavior |
| --- | --- | --- |
| Kinematic | `da/dt + c_k da/dx = 0` | centroid translates; variance is unchanged |
| Diffusive | `da/dt + c_k da/dx = D d2a/dx2` | centroid translates; variance grows by `2Dt` |
| Local inertial | `d2a/dt2 = c_g^2 d2a/dx2` | zero-tendency pulse splits; variance grows by `(c_g t)^2` |

The local-inertial case is the undamped interior gravity-wave limit with zero
initial time tendency. Its two counterpropagating components test the
second-order momentum memory of the equation. It is not the transfer function
of a one-way dam boundary.

## Evidence

Three Gaussian-pulse cases were sampled on a fixed 1 m axis from -6 km to
+6 km. All cases passed predeclared finite, nonnegative, integrated-volume,
centroid, and variance gates. Relative volume and variance tolerances are
`1e-10`; the absolute centroid tolerance is `1e-8 m`.

The limiting gates also passed:

1. all three families reduce to the same initial pulse at zero elapsed time;
2. the diffusive family at `D=0` is exactly the kinematic reference;
3. the selected cases have strictly distinct variance growth;
4. the local-inertial reference contains the expected two gravity-wave
   components.

The zero-time identity uses a declared `1e-15 m2` absolute area tolerance.
This accommodates a `5e-324` floating-point subnormal difference in the far
Gaussian tail; it is not a physical fit or a solver tolerance.

No public data, user data, action values, observations, or saved predictions
are read by this protocol. The analytic references themselves are not
candidate river operators.

## Decision

Require every next transport candidate to expose incremental area and volume
semantics and to pass the matching analytic family gates before any public
development comparison. Conservation, finite/nonnegative state, explicit
boundary flux, and the existing mass ledger remain common gates rather than
family-specific options.

Do not select diffusive or local-inertial dynamics from the visible outcome
curves. The next outcome-free diagnostic will derive state-dependent gravity
wave celerity `sqrt(gA/T)` and hydraulic-diffusion scales from the already
acquired public state and RouteLink geometry. That evidence will determine
which additional term has the correct physical scale and direction for a
first conservative candidate.

Do not interpret the analytic local-inertial upstream component as upstream
river routing or backwater admission. Boundary characteristics, friction,
network junctions, and damping remain to be specified and tested.

## Artifact

- Analytic response-family gate report SHA256:
  `415f9807e2f2cd8f10180025c66e07b98045c6497f2c8df25cf957a6d76836be`

## Claim boundary

- `outcome_values_used=false`
- `analytic_reference_families_available=true`
- `candidate_operator_implemented=false`
- `candidate_operator_admitted=false`
- `physical_parameter_values_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
