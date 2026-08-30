# ADR-050: Bind junction geometry to evidence-gated loss semantics

- Status: Accepted geometry compiler; public loss coefficient not admitted
- Date: 2026-07-28
- Scope: Stage 9 geographic binding after ADR-049

## Context

ADR-049 implemented a subcritical junction closure with explicit branch loss
coefficients. Its manufactured diagnostics prove that the numerical system can
enforce branch total-head loss, outgoing characteristics, and node mass
balance. They do not establish where a real coefficient comes from.

The repository already contains a public USGS NLDI/NHDPlus FeatureCollection
and a compiled NWM v3 Center Hill subnetwork. The outlet junction has the
public topology `18421705 + 18421707 -> 18421703`. These centerlines can support
auditable endpoint, direction, and angle calculations. Their attributes contain
only `nhdplus_comid`; they do not classify a culvert, gate, weir, bridge, or
uncontrolled natural confluence and do not contain cross sections or a local
loss assessment.

A branch angle is therefore an input to some hydraulic formulations, not by
itself an energy-loss law. Treating `K=f(angle)` as a universal relation would
turn a geographic measurement into an unsupported hydraulic parameter.

## Authoritative semantic check

The HEC-RAS Hydraulic Reference Manual's official *Modeling Stream Junctions*
page states that its default energy method performs standard-step calculations
and does not account for tributary-flow angle. Its energy-method child page
evaluates friction from reach length and average friction slope and also
evaluates contraction or expansion losses.

The angle-aware alternative is HEC-RAS's one-dimensional momentum method. It
uses cross-section specific force and supplied reach angles together with
friction, water-weight, and flow-weighted area terms. NHDPlus centerlines do not
supply those control-volume inputs either.

Retrieved official source records:

- junction page: `https://www.hec.usace.army.mil/confluence/rasdocs/ras1dtechref/latest/overview-of-optional-capabilities/modeling-stream-junctions`,
  snapshot SHA-256
  `3858127f64666d61d438c5660ac9d910b17abe6477f2479c334f03a3aa8c03a0`;
- energy and momentum child pages, page IDs `43816554` and `43816560`,
  retrieved through the official Confluence API, response SHA-256
  `59bdf525ebc59d2cd34e4523e255bebae41d08af2f3435237844e33b32790563`.

These definitions do not provide an exact mapping from the available public
centerline fields to ADR-049's branch-local dimensionless velocity-head
multiplier.

## Decision

Introduce a geographic junction compiler with four distinct contracts:

1. `GeographicJunctionBranchSource` retains branch role, source feature ID,
   full source URI, source SHA-256, CRS, and LineString coordinates.
2. `GeographicJunctionGeometry` resolves the endpoint nearest the declared
   node, samples a fixed local path window, computes WGS84 ellipsoidal flow
   azimuths, and reports upstream pair angles and upstream-to-downstream
   deflections.
3. `JunctionStructureEvidence` may classify a natural confluence, culvert,
   gate, weir, or bridge only when a separate hashed source record supports the
   classification. Missing evidence is represented as `unknown`.
4. `JunctionEnergyLossCoefficientEvidence` must name the exact branches, use
   ADR-049's `dimensionless_velocity_head_multiplier` semantics, cite a hashed
   source record, and confirm site-specific applicability. Only a site-specific
   engineering assessment or documented structure loss model can produce a
   `DynamicWaveJunctionEnergyLoss`.

An absent or incompatible coefficient record returns a typed `not_admitted`
result with reason codes. It does not silently create `K=0`. The DAG binding
function requires an admitted record for every junction and verifies exact
incoming-branch order before producing the Stage 8 loss map. Trying to bind a
non-admitted public case raises
`geographic_junction_energy_loss_dag_binding_not_admitted`. Omitting the map
from the DAG remains the explicit ADR-048 common-stage choice.

## Public compilation

The Center Hill public source is the USGS NLDI upstream-tributary request for
USGS `03424860`, frozen at SHA-256
`1f8bc9bdb6fae8e4a6e40c34531ae0a002dbaddde0fd475b53e956630a0b262c`.
The D5 topology source is frozen at SHA-256
`9ae3611462c731ef1508dd091f499425b8befe338fa85e6649df696ee7a1b951`.

Using a 30 m terminal window and 0.25 m endpoint tolerance:

| Quantity | Result |
|---|---:|
| Maximum endpoint snap distance | 0.000 m |
| `18421705` flow azimuth | 43.548 deg |
| `18421707` flow azimuth | 320.566 deg |
| `18421703` downstream flow azimuth | 354.674 deg |
| Upstream pair angle | 82.982 deg |
| `18421705` downstream deflection | 48.874 deg |
| `18421707` downstream deflection | 34.108 deg |

All three branches support the full 30 m window. Reversing every input
coordinate sequence leaves all compiled azimuths unchanged. A junction shifted
outside the snap tolerance fails closed.

The geometry is admitted as a geographic fact. The structure classification
is `unknown`, the loss admission is `not_admitted`, no implicit zero loss is
inserted, and the public case is not bound to the loss-aware DAG.

## GIS operator boundary

The geometric primitives deliberately overlap with traditional GIS software,
but their product semantics differ:

| Concern | Traditional GIS operator | Geospatial Kernel operator |
|---|---|---|
| Endpoint snap | Returns adjusted or matched geometry | Verifies a hydraulic node precondition and fails if tolerance is exceeded |
| Bearing/angle | Returns a geometric measurement | Preserves flow role, local window, CRS method, source identity, and hydraulic applicability limits |
| Attribute join | Copies structure or coefficient fields | Requires typed evidence, exact branch attachment, units/semantics, and applicability before model binding |
| Missing coefficient | Often remains null or is filled by workflow convention | Produces an explicit non-admission; never invents an angle formula or implicit zero |
| Output | New feature/field/table | Auditable input or refusal for a conservative hydraulic closure |

The Kernel does not replace GEOS, PROJ, or desktop GIS implementations of basic
geometry. It composes those mature primitives with physical state, direction,
provenance, admissibility, and conservation contracts.

## Evidence

All 15 Stage 9 gates pass. Ten focused tests cover manufactured angle recovery,
coordinate-order invariance, ellipsoidal sampling distance, CRS and snap
negative controls, centerline-only non-admission, unsupported angle-derived
coefficients, exact evidence binding, non-admitted DAG rejection, evidence
misattachment, and the public Center Hill compilation.

The public artifact is
`data/geotransport_v0_1/center_hill_v2_d5_full_subnetwork/junction_geometry_18421703.json`.
The gate report is
`benchmarks/geotransport_v0_1/dynamic_wave_junction_geometry_gates.json`.

## Consequences

Stage 9 makes branch geometry operational inside the world-model framework:
the AI can reason over an explicitly directed, measured, source-bound junction
and can know why that geometry is or is not sufficient for a hydraulic law.
This is stronger than a GIS angle field and intentionally weaker than claiming
a calibrated confluence-loss model.

The next admissible positive-loss public case requires proactively acquired
site-specific structure/section records or a documented loss model whose
required variables can all be compiled from public sources. Natural confluence
momentum closure additionally requires cross-section pressure/specific-force
support and is a separate operator, not an angle-derived patch to ADR-049.

## Claim boundary

- `public_geographic_junction_geometry_compiled=true`
- `ellipsoidal_branch_azimuths_and_angles_compiled=true`
- `geometry_provenance_preserved=true`
- `evidence_gated_stage8_dag_binding_implemented=true`
- `structure_type_verified=false`
- `centerline_angle_loss_formula_implemented=false`
- `public_loss_coefficient_admitted=false`
- `public_case_bound_to_loss_aware_dag=false`
- `junction_vector_momentum_closure_implemented=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
