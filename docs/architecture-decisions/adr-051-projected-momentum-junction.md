# ADR-051: Direction-aware projected-momentum junction closure

- Status: accepted as a diagnostic candidate; public operator not admitted
- Date: 2026-07-28
- Depends on: ADR-047 through ADR-050

## Context

ADR-050 compiled WGS84 branch directions for the public Center Hill
confluence `18421705 + 18421707 -> 18421703`. It deliberately refused to turn
centerline angle into an empirical energy-loss coefficient. The next Kernel
step therefore needs a physical closure in which direction is an actual term,
not a proxy for an undocumented `K=f(angle)` rule.

HEC-RAS's official Momentum Based Junction Method provides the relevant
one-dimensional reference. It balances momentum only along the downstream
reach's X axis. Its specific force includes convective and hydrostatic terms,
and the control-volume equation also retains reach angle, friction, water
weight, section spacing, momentum correction coefficients, and flow-weighted
downstream area. It is not a two-dimensional vector momentum balance.

The official source page is
`https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/latest/overview-of-optional-capabilities/modeling-stream-junctions/momentum-based-junction-method`,
page ID `43816560`. The frozen official child-page API response has SHA-256
`59bdf525ebc59d2cd34e4523e255bebae41d08af2f3435237844e33b32790563`.
The mixed-flow source is official page ID `43816541`, snapshot SHA-256
`adfd85e41624ee7fc7e3fbba528656c6bcf4e4e1445d552cfbb1b395ed5cc49b`.

## Decision

Introduce `ProjectedMomentumJunctionContract` and
`solve_subcritical_projected_momentum_junction` as an independent Stage 10
candidate. Do not change the frozen package entry point or the Stage 7/8 DAG
defaults.

For branch `i`, define specific force in cubic metres as

```text
M_i = beta_i Q_i^2 / (g A_i) + I1_i
I1_i = integral of depth below the free surface over dA
```

For the existing trapezoidal section, `I1` is exactly
`section.hydrostatic_pressure_integral_m3(A)`. Manning friction slope is

```text
Sf = n^2 (Q/A)^2 / R^(4/3)
```

The downstream section share assigned to branch `i` is

```text
r_i = Q_i / Q_down
```

and the projected control-volume area term is

```text
Aproj_i = A_i cos(theta_i) + r_i A_down
```

Using arithmetic endpoint slope averages and section-to-section spacing `L_i`,

```text
Ffriction_i = ((Sf_i + Sf_down) / 2) (L_i / 2) Aproj_i
Wbed_i      = ((S0_i + S0_down) / 2) (L_i / 2) Aproj_i
```

The implemented residual is

```text
R = M_down
    - sum_i [M_i cos(theta_i) - Ffriction_i + Wbed_i]
```

The solver uses one common upstream free-surface elevation as its scalar
unknown. Each upstream terminal preserves its outgoing characteristic using a
right boundary with prescribed stage. The downstream discharge is set to the
sum of the resulting upstream discharges, and a left characteristic boundary
resolves its area. The root satisfies `R=0`; mass conservation is imposed by
construction rather than checked only after the fact.

The contract requires exact branch order, section spacing, Manning `n`, bed
slope, deflection angle, upstream and downstream `beta`, and a provenance ID.
It supports only wet, downstream-oriented, subcritical combining flow and
angles from 0 through 90 degrees. Reverse flow, supercritical states, mass-
inconsistent direct evaluations, missing/nonpositive `beta`, and larger angles
fail closed.

## Manufactured positive control

A three-branch rectangular manufactured state uses upstream angles of 20 and
35 degrees, 60 m section spacing, unequal roughness, unequal bed slopes, and
non-unit upstream momentum coefficients. Its downstream `beta` is constructed
from the full equation, not fitted to public outcomes. The solver recovers the
declared upstream elevation of 3.0 m with zero mass, momentum, and outgoing-
characteristic residuals. Both branch friction and water-weight forces are
strictly nonzero.

This proves internal equation and solver consistency. It is not predictive
validation.

## Public Center Hill compilation

The public case combines three independently frozen inputs:

- NWM v3 RouteLink parameters, SHA-256
  `764dccdf71c4761cf82792f5661fd5f66d61987bd52398fe0b93a24c2f7207be`;
- ADR-050 junction geometry, SHA-256
  `ba12696fe8045941c31bd4fc804b702cf3cc20b180e7bd83a1a502c2d4fefd6b`;
- public NWM model initial-state arrays, with their individual hashes retained
  in the gate report.

`BtmWdth` is the trapezoid bottom width and the existing NWM/t-route convention
`horizontal_per_vertical = 1 / ChSlp` is preserved. The upstream control
section bed is reconstructed as `alt - So*Length`; the downstream control
section uses its start-node `alt`. The two upstream endpoint elevations close
to the downstream node within 0.01 m. ADR-050 supplies deflections of 48.874
and 34.108 degrees. Each branch's 30 m geographic window combines with the
30 m downstream window to form a 60 m section spacing.

All three public initial states are wet, downstream-oriented, and subcritical.
They are model initialization values, not observations or conservation truth.
Their raw node residual is

```text
Q_18421705 + Q_18421707 - Q_18421703 = 4.1199999 m3/s
```

so the raw tuple is rejected by the direct momentum evaluator before momentum
is considered.

RouteLink contains no momentum correction coefficient. The diagnostic
contract therefore records `beta=1` as an explicit, uncalibrated assumption.
A 4,803-candidate characteristic scan finds 23 admissible common-stage states
from 144.5903 to 145.0742 m. Their projected-momentum residual is always
positive, ranging from 3,667.49 to 3,908.82 m3, so no root bracket exists. The
solver returns `projected_momentum_junction_no_momentum_root`; it does not emit
a synthetic state.

The public operator is not admitted for five independent reasons:

1. structure classification remains unknown;
2. public `beta` evidence is absent;
3. RouteLink sections are model parameters, not site-surveyed sections;
4. the public initialization is not mass conservative at this node;
5. the characteristic public case has no projected-momentum root.

No loss coefficient is inferred, no implicit `K=0` is inserted, and no public
outcome is used for calibration.

## Relationship to traditional GIS operators

Traditional GIS and the Geospatial Kernel share geometric and data-access
primitives, but their operator products are different.

| Concern | Traditional GIS operator | Stage 10 Geospatial Kernel operator |
|---|---|---|
| Bearing and angle | Measures line orientation | Attaches flow role and projects branch specific force onto the declared downstream axis |
| Cross-section attributes | Joins or interpolates fields | Constructs a typed wet-section pressure and hydraulic-radius state with explicit NWM semantics |
| Distance | Measures between sections | Becomes the control-volume length used by friction and water-weight force terms |
| Flow join | Adds discharge attributes | Enforces `sum(Q_up)=Q_down` and uses the fractions to partition downstream area without double counting |
| Missing `beta` | Leaves null or applies a workflow default | Allows only an explicit diagnostic assumption and blocks scientific admission |
| Invalid state | Usually still returns geometry/table output | Refuses reverse, dry, supercritical, unsupported-angle, nonconservative, or rootless hydraulic closure |
| Output | Feature, raster, or table | Auditable physical state plus conservation residuals, or a typed refusal |

GEOS, PROJ, NetCDF readers, and desktop GIS remain appropriate implementations
of basic geometry and data transformation. The Kernel contribution is the
composition of those primitives with direction, dynamics, conservation,
provenance, admissibility, and explicit claim limits.

## Consequences

Stage 10 gives the Geospatial Kernel a direction-aware physical junction
operator rather than an angle-derived correction. It also demonstrates why
"data can be found publicly" and "the public data is sufficient to admit a
law" are different statements: public geometry, topology, roughness, slope,
and model sections were acquired, but `beta`, surveyed sections, and a
conservative supported state were not.

The next step should not tune `beta` until this one public initialization
closes. It should acquire a public site with surveyed junction sections and
documented hydraulic coefficients, or build a multi-site diagnostic corpus in
which missing variables and solver outcomes are reported without substitution.
Two-dimensional vector junction physics, separating flow, supercritical/mixed
regimes, storage, and structure-specific laws remain separate future
operators.

## Evidence and claim boundary

The report
`benchmarks/geotransport_v0_1/dynamic_wave_momentum_junction_gates.json`
passes all 19 gates. Focused tests cover aligned and angled manufactured roots,
full friction/weight arithmetic, required `beta`, unsupported angles, reverse
and supercritical flow, no-root behavior, serialization limits, and the frozen
public compilation.

- `direction_aware_projected_momentum_operator_implemented=true`
- `cross_section_specific_force_implemented=true`
- `friction_and_water_weight_forces_implemented=true`
- `characteristic_mass_momentum_solver_implemented=true`
- `two_dimensional_vector_momentum_implemented=false`
- `public_beta_evidence_available=false`
- `public_site_surveyed_cross_sections_available=false`
- `public_projected_momentum_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
