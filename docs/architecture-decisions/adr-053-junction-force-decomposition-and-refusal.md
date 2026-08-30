# ADR-053: Junction force decomposition and evidence-bounded refusal

- Status: accepted as a diagnostic refusal; no junction variant admitted
- Date: 2026-07-28
- Depends on: ADR-051 and ADR-052

## Context

ADR-052 reproduced the terminal-section geometry, conveyance, subsection flow
partition, and momentum coefficient of public USACE HEC-RAS Example 10. The
documented projected-momentum equation nevertheless produced a common upstream
stage of `75.93724 ft`, while the secondary HEC-RAS 6.6 recomputation produced
`75.50379 ft`. The `0.43345 ft` difference could not be attributed to geometry,
mass balance, Manning conveyance, beta, or selection of a supercritical root.

Stage 12 must isolate the remaining force terms without fitting a coefficient
or choosing an alternative equation merely because it approaches the same
Example 10 result. The user supplied no private data. All additional evidence
was acquired from bounded public USACE and fixed-commit GitHub sources through
the approved local proxy, with no workspace data sent externally.

## Evidence boundary

The Stage 12 acquisition contains four ignored `.tmp` artifacts totaling
`280125` bytes:

1. USACE `Momentum Based Junction Method`, page ID `43816560`, version 4;
2. USACE `Mixed Flow Regime Calculations`, page ID `43816541`, version 8;
3. a 62-result USACE junction catalog search snapshot;
4. `babakpst/RiverNetwork` `solve_network_mod.f90` at commit
   `f0f5f07ceecd416cf6a1fbe629d3e1050d6d2a74`.

The two USACE pages are authoritative documentation. The catalog response is a
discovery snapshot, not proof of global absence. The public Fortran source is a
transparent candidate audit, not reference truth. The Stage 11 HEC-RAS HDF
remains a secondary recomputation rather than an official observation or an
independent validation target.

Stage 10 and Stage 11 implementation and evidence files are hash-frozen by the
Stage 12 compiler. No Stage 10 or Stage 11 file was changed.

## Documented semantics audit

USACE equation 4-3 defines natural-channel specific force as:

```text
SF = beta Q^2/(g A_m) + A_t Ybar
```

`A_m` is moving flow area, while `A_t` includes ineffective flow area. The
secondary HDF exposes both quantities. At all three Example 10 terminal
sections they are identical:

| Section | `A_m` (ft2) | `A_t` (ft2) | Difference (ft2) |
|---|---:|---:|---:|
| Spring Creek / Upper Reach 10.106 | 388.60428 | 388.60428 | 0 |
| Spruce Creek / Spruce Creek 0.013 | 192.00957 | 192.00957 | 0 |
| Spring Creek / Lower Reach 10.091 | 557.90460 | 557.90460 | 0 |

Therefore, ineffective-area semantics cannot explain the Example 10 stage
discrepancy.

The junction page contains two internally inconsistent displayed equations:

- equation 4-7 reuses `theta_1` for the second upstream reach, although the
  prose requires a reach-specific angle and equation 4-5 uses `theta_2`;
- equation 4-9 repeats the first branch label and uses friction slope in a
  water-weight equation, contradicting the bed-slope definition in equation
  4-8 and the surrounding prose.

These are recorded as documentation ambiguities. The documented baseline
continues to follow the coherent prose: branch-specific angle and invert bed
slope.

## Force decomposition

`hec_ras_force_diagnostic.py` decomposes hydrostatic pressure, convective
momentum, direction projection, half-length control-volume area, average-
conveyance friction, bed weight, and branch residual. It is not exported from
the package entry point and every result is marked diagnostic-only and not
admitted.

At the exact secondary HEC-RAS terminal stages, the documented equation yields:

| Term (m3) | Upper main stem | 45-degree tributary | Downstream |
|---|---:|---:|---:|
| Hydrostatic pressure | 55.42622 | 26.48802 | 77.15350 |
| Convective momentum | 20.38328 | 5.55953 | 26.51838 |
| Projected hydrostatic pressure | 55.42622 | 18.72986 | n/a |
| Projected convective momentum | 20.38328 | 3.93118 | n/a |
| Friction force | 0.99848 | 0.28955 | n/a |
| Bed-weight force | 0.90255 | 0.12125 | n/a |
| Net branch contribution | 75.71356 | 22.49274 | n/a |
| Specific force | 75.80949 | 32.04755 | 103.67189 |

The upstream contribution sum is `98.20629 m3`; downstream specific force is
`103.67189 m3`; the exposed residual is `5.46559 m3`. The decomposition exactly
recovers the Stage 11 residual and root.

## Predeclared variants

Seven equations were declared before evaluation. Each non-baseline variant
changes exactly one force semantic:

| Variant | Reference residual (m3) | Root (ft) | Stage error (ft) |
|---|---:|---:|---:|
| Documented full specific-force projection | 5.46559 | 75.93724 | +0.43345 |
| Hydrostatic pressure unprojected | -2.29257 | 75.33354 | -0.17025 |
| Upstream control-volume area unprojected | 5.49875 | 75.93974 | +0.43595 |
| Exact bed-angle sine | 5.46559 | 75.93724 | +0.43345 |
| Flow-weighted downstream friction share | 5.47835 | 75.93628 | +0.43248 |
| Friction slope used as water-weight slope | 5.20135 | 75.92151 | +0.41772 |
| Rectangular half-depth pressure approximation | 5.16356 | 75.81911 | +0.31532 |

None is within the official table's `0.005 ft` rounding interval. More
importantly, even an exact same-case match would not establish validity because
Example 10 would then be both hypothesis generator and validation target.

No fitted coefficient, residual correction, or post-hoc combination of these
variants was evaluated.

## Independent evidence search

The current USACE catalog search finds two presentations of Example 10 and two
presentations of Example 15. The duplicate IDs are current/versioned pages for
the same models. Example 15 is a lateral-weir split-flow problem and does not
provide a second ordinary combining-junction momentum case.

The fixed-commit `RiverNetwork` source declares a momentum-junction option, but
both its upstream and downstream branches explicitly state that only the
energy-based option is implemented. It therefore cannot discriminate among
the Stage 12 momentum variants.

The evidence search is bounded rather than exhaustive. Its valid conclusion is
that no independent discriminator was found in the searched sources, not that
none exists anywhere.

## Decision

Do not select a force variant and do not admit the HEC-RAS-style projected-
momentum junction operator. Preserve the accepted components separately:

- exact irregular-section wet geometry and hydrostatic integral;
- Manning conveyance and state-dependent flow partition;
- momentum coefficient beta;
- mass, direction, control-volume, and residual contracts;
- typed rejection of unsupported closure.

The result status is `diagnostic_refusal_no_independent_discriminator`. Passing
the 14 Stage 12 gates means that evidence identity, decomposition, ambiguity
reporting, variant isolation, and refusal behavior are correct. It does not
mean that the junction law conforms.

## Consequences and next work

The HEC-RAS reproduction path has reached an evidence limit, not a reason to
abandon the Geospatial Kernel. A kernel is valuable precisely because it keeps
validated primitives while refusing an unresolved composition instead of
hiding its residual.

The next implementation stage should separate two goals:

1. Keep the HEC-RAS adapter as a diagnostic compatibility target and resume it
   only when a second official case, an exposed HEC force trace, or an actually
   implemented transparent reference becomes available.
2. Advance the native Geospatial Kernel with a conservative finite-volume
   network-junction closure whose law is fully specified, has manufactured
   mass/momentum and rotation invariants, and can be tested against public
   laboratory or field confluence observations. Agreement with HEC-RAS may be
   measured, but it must not define the native law.

This preserves the geographic kernel mission: spatial orientation, section
shape, graph role, scale, and conservation remain first-class model state,
rather than GIS preprocessing followed by an opaque fitted correction.

## Evidence

- Acquisition:
  `scripts/acquire_geotransport_hec_ras_stage12_evidence.py`
- Diagnostic implementation:
  `data_agent/uwm/geospatial_kernel_v2/hec_ras_force_diagnostic.py`
- Compiler:
  `scripts/compile_geotransport_hec_ras_stage12_force_diagnostic.py`
- Benchmark:
  `benchmarks/geotransport_v0_1/hec_ras_example10_force_decomposition_diagnostic.json`
- Offline tests:
  `data_agent/test_geospatial_kernel_hec_ras_force_diagnostic.py`
