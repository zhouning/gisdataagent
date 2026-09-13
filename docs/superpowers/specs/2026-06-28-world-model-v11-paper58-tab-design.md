# World Model v1.1 Paper58 Benchmark Tab Design

## Status

Approved design. Implementation plan not yet written.

## Background

GIS Data Agent already has DataPanel-based world model tabs, including `WorldModelV2Tab`, `WorldModelV21Tab`, and `TerritoryWorldModelTab`. The TWM validation bundle now exposes a report-only Paper58 evidence object under `paper58_external_benchmark`.

Paper58 shows external benchmark value against GeoSOS-FLUS, but its technical architecture depends on AlphaEarth/GeoFM. That dependency is not suitable as a natural-resources intranet runtime backend. The World Model v1.1 tab must therefore surface Paper58 as benchmark evidence only, while keeping TWM-native generation and planning as the runtime route.

## Product Goal

Add an independent DataPanel tab named `世界模型 v1.1` that presents Paper58 benchmark evidence against GeoSOS-FLUS from a server-configured sanitized artifact directory.

The tab helps users answer:

- Is Paper58 benchmark evidence available?
- Which Paper58 method and GeoSOS-FLUS baseline were compared?
- What are the metric deltas?
- Does this evidence affect runtime generation, production readiness, or claim ladder status?

## Non-Goals

- Do not make Paper58 a production runtime generator.
- Do not call AlphaEarth, GeoFM, or external network services.
- Do not trigger Paper58 training or full model reproduction from the first version of the tab.
- Do not promote TWM claim ladder, production readiness, SCCA, or selected-plan evidence from Paper58 results.
- Do not allow arbitrary frontend-provided filesystem paths.

## User Experience

The `世界模型 v1.1` tab is a quiet operational evidence dashboard, not a marketing page.

The first version contains:

1. Header/status strip
   - Evidence status: `missing`, `supporting_evidence`, `review`, or `blocked`
   - Runtime boundary badges:
     - `external_benchmark_support_only`
     - `runtime_dependency=none`
     - `geofm_runtime_allowed=false`
     - `not_a_runtime_generator`

2. Evidence source panel
   - Server-configured benchmark directory status
   - Source file availability:
     - `metric_summary_by_method.csv`
     - `metrics_by_method.csv`
     - `manifest.json`
   - Missing/read error diagnostics

3. Paper58 vs GeoSOS-FLUS metric table
   - Best Paper58 method
   - Baseline method
   - Area count
   - Paper58 wins vs baseline
   - Deltas for:
     - `mean_change_f1`
     - `mean_fom`
     - `mean_transition_accuracy`
     - `mean_allocation_disagreement`

4. Boundary explanation panel
   - Paper58 is external benchmark support only.
   - It does not make AlphaEarth/GeoFM a TWM runtime dependency.
   - It does not replace TWM-native generation and planning.
   - It does not prove TWM production accuracy.

5. `刷新证据` action
   - Re-reads the configured sanitized artifacts.
   - Does not start training.
   - Does not call external services.
   - Does not rewrite production validation bundles unless a later version explicitly adds that capability.

## Backend Design

Add a small API surface that wraps the existing Paper58 evidence builder.

Candidate endpoints:

- `GET /api/twm/paper58-benchmark`
- `POST /api/twm/paper58-benchmark/refresh`

Both endpoints read the benchmark directory from server configuration, for example:

- `TWM_PAPER58_BENCHMARK_DIR`

The implementation should reuse:

- `build_paper58_external_benchmark(...)` from `scripts/run_twm_validation_bundle.py`, or a shared module extracted from it if direct script import becomes awkward.

The response schema should preserve the existing evidence object:

- `schema`
- `status`
- `provided`
- `missing`
- `read_errors`
- `source_files`
- `metric_summary`
- `manifest_summary`
- `claim_scope`
- `runtime_dependency`
- `geofm_runtime_allowed`
- `twm_generator_role`
- `primary_twm_route`
- `blocks_validation`
- `can_promote_claim_ladder`
- `claim_boundary`

## Frontend Design

Add:

- `frontend/src/components/datapanel/WorldModelV11Tab.tsx`

Register it in:

- `frontend/src/components/DataPanel.tsx`

The tab should follow existing DataPanel conventions and avoid adding a new design system. It should use compact panels/tables consistent with the operational style of existing world model tabs.

Frontend states:

- Loading: initial request in progress
- Missing: configured directory absent or not configured, with non-blocking boundary
- Supporting evidence: metrics and deltas visible
- Review: malformed optional files or incomplete evidence
- Blocked: configured path not found or unreadable
- Error: API failure, shown as a retryable UI error

## Data Flow

1. User opens `世界模型 v1.1`.
2. Frontend calls `GET /api/twm/paper58-benchmark`.
3. Backend reads `TWM_PAPER58_BENCHMARK_DIR`.
4. Backend calls Paper58 evidence builder.
5. Frontend renders status, metrics, source files, diagnostics, and boundary.
6. User clicks `刷新证据`.
7. Frontend calls `POST /api/twm/paper58-benchmark/refresh`.
8. Backend re-reads local sanitized artifacts and returns the same schema.

## Security And Deployment Constraints

- The frontend must not submit arbitrary filesystem paths.
- Backend path resolution must use only the configured directory.
- The API must not read raw geometries, row-level attributes, or unrestricted local files.
- No AlphaEarth/GeoFM network or runtime dependency is introduced.
- Missing Paper58 evidence remains non-blocking.
- Supporting Paper58 evidence cannot promote production readiness or claim ladder status.

## Error Handling

- Unset `TWM_PAPER58_BENCHMARK_DIR`: return `status=missing`.
- Path not found: return `status=blocked`, `blocks_validation=false`.
- Malformed `metric_summary_by_method.csv`: return `status=review`.
- Malformed optional `metrics_by_method.csv`: return `status=review`.
- Missing optional `manifest.json`: allow `supporting_evidence` if sanitized summary is otherwise valid.
- Malformed present `manifest.json`: return `status=review`.

## Testing Plan

Backend tests:

- Missing configuration returns non-blocking missing evidence.
- Valid sanitized fixture returns supporting evidence.
- Bad configured path returns blocked but non-blocking evidence.
- Malformed summary CSV returns review.
- Malformed optional per-region CSV returns review.
- Missing optional manifest still permits supporting evidence.
- API does not accept a frontend-supplied path.

Frontend tests:

- DataPanel registers `worldmodel_v11`.
- Tab renders status badges and claim boundary.
- Tab renders metric table for supporting evidence.
- Missing/review/blocked states render diagnostics.
- Refresh button re-fetches evidence and does not trigger training or full bundle regeneration.

Integration smoke:

- Set `TWM_PAPER58_BENCHMARK_DIR` to a sanitized fixture.
- Start frontend/backend.
- Open `世界模型 v1.1`.
- Confirm Paper58 status is `supporting_evidence`.
- Confirm boundary text says external benchmark only and GeoFM runtime is not allowed.

## Acceptance Criteria

- A new independent `世界模型 v1.1` tab appears in DataPanel.
- The tab reads only server-configured sanitized Paper58 artifacts.
- Valid artifacts show Paper58 vs GeoSOS-FLUS metrics.
- Missing or malformed artifacts show conservative diagnostics.
- The UI visibly states that Paper58 is not a TWM runtime generator.
- No production readiness, claim ladder, SCCA, selected-plan, or generation backend behavior changes.
- Tests cover backend API, frontend rendering, refresh behavior, and boundary text.
