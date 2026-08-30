# ADR-052: HEC-RAS irregular-section junction reference

- Status: accepted as a partial-conformance diagnostic; junction operator not admitted
- Date: 2026-07-28
- Depends on: ADR-047 through ADR-051

## Context

ADR-051 implemented a direction-aware projected-momentum candidate, but its
public Center Hill case had parameterized trapezoids, no supported momentum
coefficient, a nonconservative initial state, and no momentum root. Those data
were insufficient to distinguish an operator error from an input-support
failure.

Stage 11 therefore uses public HEC-RAS Example 10, a subcritical combining
junction with surveyed station/elevation sections, spatially varying Manning
roughness, documented flows, reach lengths, and angles. No user-provided data
is required. Acquisition is bounded to three hash-locked public objects under
the ignored `.tmp/` directory:

1. the USACE Example 10 ZIP, SHA-256
   `c17a7e0e48c9578ce04caa9ffbdb798b979f4f7beb1be027f543b8e45f7f98c2`;
2. the USACE momentum Standard Table 2 image, SHA-256
   `e38d571214ec7c6ba842d90d5ec7368694faead75ff61e17bf61aced48d99624`;
3. a fixed-commit HydroClaude HEC-RAS 6.6 result HDF, SHA-256
   `762b14a079570c2dabd2e4ffdef29bfde561a13cd0fcd09b15353f6de3efa4b6`.

The first two objects are official USACE input and publication evidence. The
third is a public third-party recomputation. It supplies additional numeric
precision for diagnosis, but it is not a USACE original result, an observation,
or independent field truth.

The official ZIP contains 19 cross sections and the expected junction:

```text
Spring Creek / Upper Reach  -- 3000 cfs -- 80 ft --  0 deg --+
                                                               +--> 4100 cfs
Spruce Creek / Spruce Creek -- 1100 cfs -- 70 ft -- 45 deg --+
```

The official page is USACE Applications Guide page ID `80528340`. The
documented projected-momentum equation is on Hydraulic Reference Manual page
ID `43816560`; cross-section subdivision, flow distribution, and average
conveyance friction are on page IDs `43815904`, `43816570`, and `43815934`.

## Decision

Introduce two independent Stage 11 reference modules without changing the
frozen Geospatial Kernel package entry point:

- `irregular_section.py` implements piecewise-linear open-section hydraulics;
- `hec_ras_reference.py` strictly parses `G02`, `F01`, and `P02` and evaluates
  the documented combining-flow momentum equation.

The Stage 10 entry files remain byte-identical:

```text
__init__.py
  7db7e6459143d2a54e742a732fcd3f85c422a9775559296dc39a985ab632315d
dynamic_wave_junction_momentum.py
  64cd7ae682784a2d9fc4be48bf6a3a7fc2eb074d5e31bca97fdc5bd6f298a873
```

### Irregular-section operator

For each surveyed linear segment, the implementation integrates wet area,
top width, wetted perimeter, and hydrostatic pressure exactly. The pressure
term is

```text
I1 = integral_A h dA = integral_x h(x)^2 / 2 dx.
```

Manning zones divide the horizontal section into subsections. Surveyed bed and
bank lengths contribute to wetted perimeter; artificial vertical walls at
subsection boundaries do not. In SI units,

```text
K_i = A_i R_i^(2/3) / n_i
Q_i = Q K_i / sum(K_i)
beta = A/Q^2 sum(Q_i^2/A_i).
```

This makes `beta` a state-dependent consequence of geometry, roughness, stage,
and discharge partition rather than a fitted constant.

### Reference junction equation

Specific force is

```text
SF = beta Q^2/(g A) + I1.
```

For each upstream branch `i`, average-conveyance friction is

```text
Sf_bar_i = ((Q_i + Q_down)/(K_i + K_down))^2.
```

The downstream area is flow-weighted to avoid double counting:

```text
Aproj_i = A_i cos(theta_i) + A_down Q_i/Q_down.
```

Using the documented half-length control volume,

```text
Ffriction_i = Sf_bar_i (L_i/2) Aproj_i
Wbed_i      = S0_i     (L_i/2) Aproj_i
R = SF_down - sum[SF_i cos(theta_i) - Ffriction_i + Wbed_i].
```

The scalar solver finds a common upstream stage, rejects dry and supercritical
states, and requires fixed-flow mass conservation. It scans the entire closed
section domain before bisection, so a low supercritical root cannot be selected
for this subcritical plan.

## Conformance result

At the exact stages stored by the secondary HEC-RAS 6.6 HDF, the kernel
reproduces all three terminal sections within float32-aware tolerances:

| Terminal section | Stage (ft) | Area (ft2) | Conveyance (cfs) | beta |
|---|---:|---:|---:|---:|
| Spring Creek / Upper Reach 10.106 | 75.5037918 | 388.60428 | 85515.51 | 1.0000000 |
| Spruce Creek / Spruce Creek 0.013 | 75.5037918 | 192.00957 | 34594.45 | 1.0023891 |
| Spring Creek / Lower Reach 10.091 | 75.0377579 | 557.90460 | 127947.62 | 1.0000000 |

Area, top width, wetted perimeter, conveyance, `beta`, and subsection flow
partition all conform. In particular, the Spruce Creek left/channel/right
flows are reproduced as approximately `0.17439 / 1099.72282 / 0.10279 cfs`.
The exact secondary stages also round to the official published `75.50 ft`
common upstream stage and `75.04 ft` downstream stage.

The documented projected-momentum closure does not reproduce that common
upstream stage. At the exact secondary reference stage its residual is
`5.46559 m3`. The admissible subcritical root is:

```text
implemented root       = 75.93724 ft
secondary HEC-RAS root = 75.50379 ft
stage error            =  0.43345 ft (0.13211 m)
```

The implemented root has branch Froude numbers about `0.436`, `0.355`, and
`0.450`, and satisfies the implemented equation to numerical tolerance. The
discrepancy is therefore not explained by section area, wetted geometry,
Manning conveyance, discharge partition, `beta`, mass balance, or accidental
selection of a supercritical root. The remaining hypothesis is an undocumented
or differently interpreted HEC internal pressure, friction, or weight-force
treatment. Stage 11 does not introduce an inferred coefficient to erase the
difference.

The accepted result is deliberately split:

- irregular-section geometry: conformed;
- conveyance and subsection flow distribution: conformed;
- momentum coefficient `beta`: conformed;
- documented projected-momentum stage: not conformed;
- public junction operator: not admitted.

## Relationship to traditional GIS operators

The numerical primitives are not intended to replace mature GIS software.
Coordinate transformation, topology construction, line direction, distance,
section extraction, raster sampling, and table joins should continue to use
PROJ, GEOS, GDAL, QGIS, ArcGIS, or equivalent tested implementations.

The difference is the contract around those primitives:

| Concern | Traditional GIS implementation | Geospatial Kernel implementation |
|---|---|---|
| Cross-section clipping | Produces geometry or attributes | Produces a wet hydraulic state with exact area, pressure, and perimeter semantics |
| Roughness overlay | Spatial join or zonal attribution | Partitions conveyance and derives state-dependent discharge and `beta` |
| Bearing and angle | Measures orientation | Projects a declared flow-role-specific force onto the downstream axis |
| Reach distance | Reports length | Becomes a force-integration control-volume length |
| Flow table join | Attaches numeric fields | Requires mass conservation and flow-weighted downstream area allocation |
| Missing or invalid state | Often returns null or partial output | Rejects unsupported, dry, reverse, supercritical, or nonconservative closure |
| Output meaning | Feature, raster, or table | Auditable physical state, residual, provenance, admissibility, or typed refusal |

The low-level geometry and numerical formulas may be identical to professional
GIS or hydraulic software. The Geospatial Kernel contribution is their typed
composition with dynamics, conservation laws, direction, uncertainty,
provenance, scientific gates, and explicit refusal boundaries. Reimplementing
a buffer or overlay is not itself a world-model kernel; making spatial state
participate in falsifiable physical closure is.

## Consequences

Stage 11 demonstrates that the Geospatial Kernel mission remains valid even
when a candidate closure fails. The kernel now understands an irregular
cross-section as more than geometry and can carry it through state-dependent
hydraulic invariants. It also refuses to label partial conformance as a valid
junction law.

The next investigation should isolate HEC's remaining force treatment using
additional official examples or a transparent open hydraulic implementation.
Candidate terms must be tested one at a time against multiple cases. No term
may be inferred from the Example 10 stage and then reported as validation on
the same case. A Stage 12 operator remains blocked until the junction-stage
discrepancy is explained or an independently specified alternative closure is
validated.

## Evidence

The acquisition script is
`scripts/acquire_geotransport_hec_ras_example10.py`. It enforces HTTPS host
allowlists, exact size and hash checks, required ZIP member hashes, the local
7897 proxy default, and ignored `.tmp/` output.

The compiler is
`scripts/compile_geotransport_hec_ras_example10_gates.py`. Its report is
`benchmarks/geotransport_v0_1/hec_ras_example10_momentum_gates.json`.
All expected-behavior gates pass while `documented_projected_momentum_stage_`
`conformed=false` and `operator_admitted=false` remain explicit scientific
outcomes.

Focused tests use manufactured geometry and text fixtures only; they do not
depend on network access or downloaded `.tmp` evidence.
