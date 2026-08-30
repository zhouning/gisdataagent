# ADR-054: Native conservative vector junction with explicit reaction

- Status: implemented as a native candidate; public validation pending
- Date: 2026-07-28
- Depends on: ADR-047, ADR-050, ADR-051, ADR-052, and ADR-053

## Context

ADR-053 refused to select a HEC-RAS projected-momentum variant because seven
predeclared force interpretations could not reproduce Example 10 within the
published stage tolerance and no independent discriminator was available. That
refusal is a limit on an opaque compatibility path, not a withdrawal of the
Geospatial Kernel mission.

A geographic junction law must preserve at least four facts that are absent
from a conventional scalar graph node:

1. branches have flow-oriented directions in a geographic reference frame;
2. section shape determines the hydrostatic pressure integral;
3. water mass cannot disappear in a zero-storage node; and
4. directional momentum that does not pass into the outgoing branch must be
   carried by a wall, bed, structure, or multidimensional junction state.

A general multi-in/one-out junction cannot conserve two independent horizontal
momentum components using only one-dimensional branch states while also
assuming zero junction reaction. At a turning or asymmetric confluence, the
missing transverse component is physical load transfer, not numerical noise.

## Decision

Implement a native, fully specified candidate in
`conservative_vector_junction.py`. Do not modify the frozen HEC-RAS diagnostic
path or select any Stage 12 force variant.

The hydraulic coupling remains the existing subcritical network Riemann
contract:

```text
one common free-surface elevation
sum(Q_upstream) = Q_downstream
one outgoing characteristic invariant retained per branch
zero junction storage
```

For branch flow azimuth `alpha`, measured clockwise from true north, the local
east/north unit tangent is:

```text
t(alpha) = [sin(alpha), cos(alpha)]
```

Each trapezoidal terminal section contributes the conservative Saint-Venant
generalized momentum flux per unit density:

```text
F = Q^2 / A + g I1
```

where `I1` is the exact section hydrostatic pressure integral. The first term
is exposed as convective flux and the second as hydrostatic flux. The initial
candidate uses the depth-averaged Saint-Venant momentum coefficient `beta=1`;
no empirical coefficient is fitted.

Upstream terminal control-volume normals point opposite their flow tangents,
while the downstream normal points with its tangent. The net outward vector
flux is therefore:

```text
B = F_down t_down - sum(F_up,i t_up,i)
```

The reaction exerted by the unresolved junction walls and bed on the water is
retained explicitly:

```text
R_junction_on_fluid = B
momentum ledger residual = B - R_junction_on_fluid = [0, 0]
```

This is a conservative balance with an external reaction. It is not a claim
that branch momentum alone is homogeneous or that a two-dimensional junction
cell has been solved. The equal reaction is a resolved load required by the
specified one-dimensional coupling, not an observed force.

The network wrapper advances the existing synchronous finite-volume reaches
and returns this reaction as node-level spatial state. It does not inject the
two-dimensional reaction into an arbitrary branch as a one-dimensional scalar
source.

## Geographic binding

`ConservativeVectorJunctionContract.from_geographic_geometry` binds admitted
WGS84 centerline directions from the Stage 8 geographic geometry compiler.
Branch roles and identifiers must match exactly. Non-admitted geometry,
noncanonical azimuths, reversed combining flow, branch reordering without a
matching contract, and unsupported hydraulic roots fail with typed errors.

This is where the implementation differs from a traditional GIS operator.
A GIS buffer, overlay, or network trace transforms or queries geographic data
and normally ends after producing geometry or attributes. This kernel operator
uses geographic direction as part of a time-varying physical state contract;
combines it with cross-section shape, discharge, pressure, graph role, and
conservation; emits a dimensional residual and reaction ledger; and refuses
unsupported states. It can use GIS-derived centerlines, but its result is a
physical state transition and audit record rather than a geometry product.

## Manufactured controls

The Stage 13 compiler evaluates 14 gates:

- predecessor Stage 10-12 hashes remain frozen;
- zero-storage mass closes within `2e-12 m3/s`;
- east and north momentum ledgers close within `2e-12 m4/s2`;
- convective and hydrostatic terms reconstruct the total flux;
- a rigid 73-degree rotation rotates the reaction covariantly and preserves
  its magnitude and the scalar hydraulic solution;
- consistent upstream permutation leaves the vector sum unchanged;
- a symmetric lake at rest retains its water surface and zero discharges;
- symmetric transverse hydrostatic reactions cancel;
- the synchronous finite-volume network step closes its volume, node mass,
  and vector momentum ledgers; and
- the bounded public-evidence refusal assessment passes.

All 14 gates pass. Passing these gates establishes internal law consistency,
not empirical accuracy or operator admission.

## Public evidence audit

The user supplied no private data. Four public JSON objects were acquired
through the approved local proxy from Crossref, OpenAlex, Zenodo, and GitHub.
The acquisition totaled `16708` bytes and sent no workspace data.

The bounded search identified the relevant experimental lineage, including
Shumate's *Experimental Description of Flow at an Open-Channel Junction* and
the Weber-Shumate-Mawer 90-degree junction paper. The OpenAlex snapshot marks
the thesis as closed, with no full text or PDF URL. The open Zenodo record is a
CC-BY article with one PDF and no machine-readable numeric attachment. The
exact GitHub repository query returned zero results.

The evidence status is:

```text
no_independent_open_machine_readable_confluence_validation_dataset_
identified_in_bounded_search
```

This is not a global absence claim. A literature record is not a hydraulic
observation, an article PDF is not automatically a raw dataset, and a zero-hit
catalog query is not proof that no dataset exists.

## Consequences

The Geospatial Kernel now has a native directional junction core whose law is
inspectable and whose unresolved physics is explicit. DAM-GK's original
mission therefore remains intact: geographic structure constrains inference
inside the model rather than serving only as preprocessing.

The current candidate remains diagnostic-only and not admitted because the
junction reaction and predicted terminal states have not passed an independent
public laboratory or field validation. HEC-RAS Example 10 remains a separate
compatibility diagnostic and does not define this law.

The next scientific increment should add one of the following without fitting
against the validation target:

1. an open laboratory case with machine-readable terminal geometry, branch
   flow, and water-surface observations;
2. an independently measured wall or structural load for direct reaction
   validation; or
3. an explicit two-dimensional shallow-water junction control cell whose
   internal storage and momentum state replace the inferred reaction.

## Artifacts

- Native implementation:
  `data_agent/uwm/geospatial_kernel_v2/conservative_vector_junction.py`
- Offline and network tests:
  `data_agent/test_geospatial_kernel_conservative_vector_junction.py`
- Evidence acquisition:
  `scripts/acquire_geotransport_stage13_confluence_evidence.py`
- Evidence assessment:
  `scripts/assess_geotransport_stage13_confluence_evidence.py`
- Gate compiler:
  `scripts/compile_geotransport_stage13_vector_junction_gates.py`
- Native gate report:
  `benchmarks/geotransport_v0_1/stage13_conservative_vector_junction_gates.json`
- Evidence assessment report:
  `benchmarks/geotransport_v0_1/stage13_confluence_evidence_assessment.json`
