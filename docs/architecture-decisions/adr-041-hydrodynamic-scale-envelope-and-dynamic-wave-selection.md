# ADR-041: Select a dynamic-wave core from public hydraulic scales

- Status: Accepted
- Date: 2026-07-28
- Scope: First post-kinematic transport candidate after ADR-040

## Context

ADR-040 fixed outcome-independent analytic gates for kinematic, diffusive, and
local-inertial response families. The next decision is which physical term to
implement first. It must be based on public base-state and geometry scales,
not on fitting the already visible downstream observations.

A typed path diagnostic now derives, for every reach and all 672 public hourly
states:

- trapezoidal depth and top width from the Manning `Q -> A` base state;
- mean velocity `u=Q/A`;
- linear gravity-wave celerity `c_g=sqrt(gA/T)`;
- Froude number `Fr=u/c_g`;
- linearized diffusive-wave coefficient `D=Q/(2S0T)`;
- reach Péclet number `Pe=c_k L/D`;
- diffusive first-passage variance contribution `2DL/c_k^3`.

These are scale diagnostics. Gravity-wave time and diffusive spread are not
admitted as observed flood-wave lag.

## Evidence

| q05/q50/q95 public-state envelope | Center Hill | J. Percy Priest |
| --- | ---: | ---: |
| Manning centroid path time | 15.58/16.14/16.80 h | 2.44/2.63/2.84 h |
| Gravity-wave path time | 1.16/1.20/1.24 h | 0.28/0.30/0.32 h |
| Gravity/Manning time ratio | 0.074/0.074/0.075 | 0.112/0.113/0.114 |
| Diffusive first-passage standard deviation | 72.12/72.62/73.17 h | 24.98/25.34/25.68 h |
| Supercritical effective-length fraction | 0.0449/0.0449/0.0449 | 0.0230/0.0230/0.0230 |
| Supercritical Manning-time fraction | 0.00395/0.00397/0.00405 | 0.00135/0.00139/0.00142 |

All 672 states in both systems are finite and propagating. Gravity-wave time
is shorter than Manning time in every state. This independently supports the
direction of the phase attribution: pressure/inertial characteristics provide
a materially faster physical scale than the current kinematic closure.

Pure diffusive-wave routing is not a suitable first candidate. At Center Hill,
several low-slope reaches have median `D` near `5.6e4 m2/s` and `Pe` below
`0.01`; the resulting spread exceeds the already slow Manning time by a factor
near 4.5. At J. Percy Priest, feature 18401509 contributes approximately 98%
of the diffusive first-passage variance. An operator dominated by this scale
would primarily broaden and attenuate a response that is already too delayed
and attenuated.

A gravity-only local-inertial equation is also insufficient as the full-path
operator. Center Hill features 18421763 and 18421761 are supercritical in all
672 states; J. Percy Priest feature 18401881 is likewise supercritical. These
segments occupy only 4.49% and 2.30% of effective path length, but demonstrate
that convective momentum cannot be deleted as a universal equation term.

The high-Froude reaches contribute only 0.40% and 0.14% of Manning path time.
They therefore do not erase the gravity-wave scale finding, but they determine
the minimum equation family needed to represent all path regimes without an
ad hoc reach switch.

## Decision

Select a conservative two-state dynamic-wave finite-volume core as the first
post-kinematic candidate. Its state is wetted area `A` and discharge `Q`; its
homogeneous momentum flux retains both convective momentum and hydrostatic
pressure. Manning friction, bed slope, lateral flow, geometry transitions,
and network junctions remain explicit source or coupling terms.

Require the candidate to recover:

1. the kinematic limit under equilibrium friction;
2. the local-inertial gravity-wave limit when convective momentum is removed;
3. the ADR-040 mass, centroid, variance, and initial-identity gates;
4. finite, nonnegative area and explicit mass conservation;
5. subcritical and supercritical Riemann cases without equation switching.

Implement in stages: first a prismatic single-reach homogeneous flux and
Riemann/CFL gates, then well-balanced bed/friction sources, then directed
network junction coupling. No development observations are used until these
analytic gates pass.

Do not admit the dynamic-wave family, gravity-wave time, diffusive scale, or
any parameter correction at this decision point.

## Artifacts

- Hydrodynamic-scale report SHA256:
  `65faa0ace3d6895aca38f93ab847a3c16a6205f057d200e2f9b9521e84285919`
- Center Hill path-scale CSV SHA256:
  `1f01b40d0baba98d1912f123bea6ef81ed47958d88b2e4e4a25760cd3c77789f`
- J. Percy Priest path-scale CSV SHA256:
  `2c5296b688ad589239913e9866cc179062eeb19ec39b12ac1ce57d37ea3afb9f`

## Claim boundary

- `public_data_without_user_supplied_data=true`
- `outcome_values_used=false`
- `gravity_wave_scale_direction_supported=true`
- `pure_diffusive_first_candidate_supported=false`
- `full_path_local_inertial_simplification_supported=false`
- `dynamic_wave_first_candidate_selected=true`
- `candidate_operator_implemented=false`
- `candidate_operator_admitted=false`
- `geospatial_kernel_validated=false`
