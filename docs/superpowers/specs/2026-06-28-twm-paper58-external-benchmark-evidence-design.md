# TWM Paper58 External Benchmark Evidence Design

- **Date**: 2026-06-28
- **Scope**: Narrow validation-bundle evidence slice for Territory World Model
- **Status**: Approved by user after confirming Paper58 must not become the TWM generation runtime

## Goal

Add a conservative Paper58 evidence intake path to the TWM validation bundle.

Paper58 provides useful local evidence against matched FLUS and GeoSOS-FLUS-style baselines, but its technical architecture depends on AlphaEarth/GeoFM. The natural-resource intranet environment cannot and should not rely on AlphaEarth access. Therefore Paper58 must be treated as external benchmark support only, not as a TWM generation backend, not as a production dependency, and not as evidence that TWM can use an AlphaEarth-based runtime in deployment.

The useful outcome is a repeatable report section that lets TWM say:

- TWM-native generation and planning remain the main route.
- Paper58 benchmark results are supporting external evidence.
- Paper58 does not upgrade TWM production accuracy, deployability, or runtime claim levels.
- Any Paper58-inspired ideas must be reimplemented with TWM-native and intranet-available inputs before they affect TWM runtime behavior.

## Non-Goals

- No Paper58 generator integration into TWM runtime.
- No AlphaEarth, online GeoFM, or external cloud dependency in the TWM validation runner.
- No promotion of Paper58 metrics into TWM production-readiness gates.
- No claim that TWM inherits Paper58's GeoSOS-FLUS surpass result.
- No change to TWM dynamics, planner ranking, state builder, SCCA handling, or production observed-history gates.
- No modification of existing untracked report artifacts.

## Current Context

The current TWM validation bundle already includes:

- state build, rule evaluation, audit report, selected-plan evaluation, validation ladder, and claim ladder;
- optional SCCA causal evidence intake;
- production observed-history preflight;
- production scale readiness;
- deployment punch-list output.

The gap is a safe place to record external benchmark evidence from Paper58 without confusing it with TWM runtime evidence.

Paper58's latest local outputs add strong external benchmark information, including leave-one-area-out and same-grid FLUS comparisons. That information helps position TWM research evidence, but it is not a valid TWM intranet runtime dependency because Paper58 relies on AlphaEarth/GeoFM-derived representations.

TWM already has its own TWM-native partial surpass evidence against GeoSOS-FLUS-style baselines. That evidence should remain the primary basis for TWM's own model and planner claims.

## Approach

Add a small, additive Paper58 external benchmark evidence surface to `scripts/run_twm_validation_bundle.py`.

1. **Input contract**
   - Accept an optional Paper58 benchmark artifact directory or manifest path.
   - Read sanitized benchmark summaries only, such as metric summary CSVs, per-region metric CSVs, and manifest JSON.
   - Do not read raw rasters, AlphaEarth embeddings, or Paper58 generated prediction arrays.

2. **Evidence summary**
   - Produce a `paper58_external_benchmark` report object with:
     - `schema`: `territory_world_model.paper58_external_benchmark.v1`
     - `status`: `supporting_evidence`, `review`, `missing`, or `blocked`
     - `claim_scope`: `external_benchmark_support_only`
     - `runtime_dependency`: `none`
     - `geofm_runtime_allowed`: `false`
     - `twm_generator_role`: `not_a_runtime_generator`
     - `primary_twm_route`: `twm_native_generation_and_planning`
     - sanitized metric highlights and boundaries.

3. **Claim boundary**
   - Keep Paper58 outside production readiness.
   - Keep Paper58 outside claim-ladder promotion.
   - Add explicit wording that Paper58 does not prove TWM production accuracy and does not authorize AlphaEarth-dependent runtime deployment.

4. **Markdown output**
   - Add an `External Benchmark Evidence` section to the validation-bundle Markdown.
   - Show the Paper58 summary, dependency boundary, and recommended next actions.
   - Make the boundary visible even when no Paper58 artifact is supplied, so the report does not imply missing Paper58 blocks TWM.

5. **Recommendations**
   - If Paper58 evidence is provided, recommend using it for research positioning and benchmark comparison only.
   - If AlphaEarth/GeoFM dependency is detected or declared, recommend keeping it outside TWM runtime and reimplementing any useful gate idea with intranet-available TWM-native inputs.

## Expected Outputs

The implementation should update or add tests around:

- `data_agent/test_twm_validation_bundle_smoke_script.py`

The implementation may update:

- `scripts/run_twm_validation_bundle.py`
- `scripts/smoke_twm_validation_bundle.sh`
- `docs/reports/twm_validation_bundle.json`
- `docs/reports/twm_validation_bundle.md`

No core TWM model file should be edited for this slice.

## Acceptance Criteria

- A missing Paper58 artifact does not block validation-bundle execution.
- A supplied Paper58 summary appears under `paper58_external_benchmark`.
- The summary always marks Paper58 as external supporting evidence only.
- The summary always records `runtime_dependency: none` and `geofm_runtime_allowed: false` for TWM.
- Paper58 evidence does not change `claim_ladder.current_level`.
- Paper58 evidence does not change production observed-history or production readiness statuses.
- Markdown output includes a clear dependency boundary and does not describe Paper58 as a TWM generator.
- Tests cover both missing and supplied Paper58 benchmark evidence.

## Testing Plan

Run focused tests:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py
```

Run the validation bundle once with a sanitized local Paper58 fixture:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python scripts/run_twm_validation_bundle.py \
  --paper58-benchmark-dir /private/tmp/twm_paper58_benchmark_fixture \
  --output /private/tmp/twm_validation_bundle_paper58.json \
  --markdown-output /private/tmp/twm_validation_bundle_paper58.md
```

The fixture must be derived from metric summaries only. It must not contain raw AlphaEarth embeddings, raw rasters, or Paper58 prediction arrays.

## Risk Controls

- Keep the feature additive and report-only.
- Prefer sanitized CSV/JSON summaries over raw geospatial artifacts.
- Make the AlphaEarth/GeoFM deployment boundary explicit in both JSON and Markdown.
- Do not connect Paper58 evidence to production readiness or claim-ladder promotion.
- Preserve TWM-native generation and planning as the primary route.
- Add negative tests proving Paper58 evidence cannot upgrade TWM claims.

## Deferred Work

- Reimplement selected Paper58-inspired gate ideas with TWM-native and intranet-available features.
- Compare TWM-native and Paper58 evidence in a separate research positioning report.
- Add a broader external-benchmark registry for Paper6, Paper7, Paper10, Paper11, Paper12, and Paper13.
- Use real authoritative observed history to advance TWM production claims.
