# World Model v2.1 Paper9 Integration Design

- **Status**: Concept approved; pending written-spec review
- **Date**: 2026-06-03
- **Scope**: New GIS Data Agent DataPanel tab and backend adapter for Paper9 `arcgis-farmland-mpc` latest results
- **Source repository**: `D:\test\_publish\arcgis-farmland-mpc` / `https://github.com/zhouning/arcgis-farmland-mpc`
- **First slice**: Paper9 Tool 4 MPC Planning only

## Goal

Add a new "世界模型 v2.1" tab to GIS Data Agent that integrates the latest Paper9 `arcgis-farmland-mpc` production/reproducibility repository through a thin backend adapter. The first release runs Paper9 Tool 4 MPC Planning against an existing `prepared_dir` and `tool3/*.onnx` ensemble, then reports planning metrics and pushes the optimized layout to the map when a spatial output is available.

## Non-goals

- Do not replace or remove the existing "世界模型v2" tab.
- Do not copy Paper9 algorithm modules into `data_agent/`.
- Do not integrate Tool 1 prepare, Tool 2 sample, or Tool 3 train in the first slice.
- Do not train new ensembles from the GIS Data Agent UI in this slice.
- Do not depend on the old `D:\test\paper9_contrastive` `.pt` and `.zip` research weights.
- Do not introduce deployment of Paper9 services or containers.

## Rationale

The current GIS Data Agent World Model v2 integration is a fixed Bishan demonstration wrapper around older local research paths:

- `D:\test\county_env.py`
- `D:\test\mpc_planner.py`
- `D:\test\parcel_scoring_policy.py`
- `D:\test\paper9_contrastive\multi_seed`

The latest Paper9 repository has moved to a deployable workflow:

- `farmland_mpc` Python package and `farmland-mpc` CLI
- `prepared_dir`-based region abstraction
- ONNX ensemble inference via `ensemble_member*.onnx`
- ArcGIS Pro, QGIS, Docker, benchmark, verification, and paper artifacts
- new cultivated-area and baimu-fang constraint options

World Model v2.1 should therefore be a new integration surface backed by the Paper9 package, while v2 remains available as a legacy fixed-demo entry.

## Recommended Architecture

Use a thin adapter layer inside GIS Data Agent:

```text
DataPanel / WorldModelV21Tab
        |
        v
/api/world-model-v21/status
/api/world-model-v21/plan
        |
        v
data_agent.world_model_v21.WorldModelV21Service
        |
        v
D:\test\_publish\arcgis-farmland-mpc\farmland_mpc
        |
        v
farmland_mpc.mpc_plan.run
```

The adapter is responsible for path validation, import setup, request validation, summary normalization, and map-output handoff. Paper9 remains the source of truth for algorithm behavior.

## Backend Components

### `data_agent/world_model_v21.py`

Create `WorldModelV21Service` with these responsibilities:

- Resolve the Paper9 repository path from `PAPER9_FARMLAND_MPC_REPO`; default to `D:\test\_publish\arcgis-farmland-mpc`.
- Add the repo root to `sys.path` only inside the service import path, so `farmland_mpc` can be imported without installing the package globally.
- Report repository status:
  - repo path exists
  - `farmland_mpc` import succeeds
  - package version, if available
  - Git commit hash and commit date, if available
  - default `prepared_dir` and `ensemble_dir`, if configured
  - ONNX member count
- Validate planning input:
  - `prepared_dir` exists
  - `ensemble_dir` exists
  - `ensemble_dir` contains at least one `ensemble_member*.onnx`
  - `horizon` is 1-20
  - `top_k` is 1-500
  - `n_episodes` is 1-20
  - `continuation` is `random` or `greedy`
  - `scoring` is `reward` or `slope`
  - optional hard constraints are numeric when supplied
- Run Paper9 Tool 4 by calling `farmland_mpc.mpc_plan.run`.
- Create a per-user output directory under the current GIS Data Agent upload area:
  - `data_agent/uploads/<user>/world_model_v21/<timestamp>/`
- Normalize the returned summary into a stable JSON response.
- If an optimized shapefile is generated, convert it to a map-friendly layer format and queue it through `pending_map_updates`.

The service should not import `farmland_mpc` at module import time. Imports happen lazily inside methods so the app can start even when the Paper9 repo is absent.

### `data_agent/api/world_model_v21_routes.py`

Create routes:

- `GET /api/world-model-v21/status`
- `POST /api/world-model-v21/plan`

`status` response shape:

```json
{
  "status": "ready",
  "version": "2.1.0",
  "paper9": {
    "repo_path": "D:\\test\\_publish\\arcgis-farmland-mpc",
    "remote": "https://github.com/zhouning/arcgis-farmland-mpc.git",
    "commit": "6c00b9b",
    "commit_date": "2026-06-02 12:37:18 +0800",
    "package_version": "0.2.1",
    "importable": true
  },
  "defaults": {
    "prepared_dir": "",
    "ensemble_dir": "",
    "out_dir_policy": "per-user timestamped uploads directory"
  },
  "capabilities": {
    "tool4_plan": true,
    "prepare_sample_train": false,
    "onnx_inference": true,
    "cultivated_area_floor": true,
    "baimu_area_floor": true
  }
}
```

`plan` request shape:

```json
{
  "prepared_dir": "D:\\path\\to\\prepared",
  "ensemble_dir": "D:\\path\\to\\prepared\\tool3",
  "horizon": 5,
  "top_k": 50,
  "n_episodes": 1,
  "continuation": "random",
  "scoring": "reward",
  "threads": 0,
  "proj_crs": "EPSG:32648",
  "cultivated_area_floor_delta_ha": null,
  "baimu_area_floor_delta_ha": null,
  "gamma_conn": null,
  "delta_conn": null
}
```

`plan` response shape:

```json
{
  "status": "ok",
  "version": "2.1.0",
  "source": "arcgis-farmland-mpc",
  "mode": "tool4_mpc",
  "prepared_dir": "D:\\path\\to\\prepared",
  "ensemble_dir": "D:\\path\\to\\prepared\\tool3",
  "out_dir": "D:\\adk\\data_agent\\uploads\\admin\\world_model_v21\\20260603_120000",
  "summary": {
    "total_reward": 123.45,
    "initial_slope": 0.0,
    "final_slope": 0.0,
    "slope_change_pct": -1.289,
    "n_episodes": 1,
    "best_episode": 1
  },
  "artifacts": {
    "summary_json": "mpc_summary.json",
    "optimized_shp": "optimized_dltb.shp",
    "map_layer": "optimized_dltb.fgb"
  },
  "map_update_queued": true
}
```

The route should return:

- `401` when the user is not authenticated.
- `400` for invalid JSON or invalid parameter ranges.
- `503` when the Paper9 repo/package/ensemble is unavailable.
- `500` only for unexpected internal errors.

### Route Mounting

Modify `data_agent/frontend_api.py` to import and mount `get_world_model_v21_routes()` near the existing World Model v2 routes.

## Frontend Components

### `frontend/src/components/datapanel/WorldModelV21Tab.tsx`

Create a new tab component. The UI should be dense and operational, matching the existing DataPanel style rather than a landing page.

The tab has four areas:

1. **Source Status**
   - Paper9 repo path
   - Git commit
   - package version
   - ONNX/model availability
   - a clear ready/warning/error badge

2. **Planning Inputs**
   - `prepared_dir`
   - `ensemble_dir`
   - optional `proj_crs`
   - `horizon`
   - `top_k`
   - `n_episodes`
   - `continuation`
   - `scoring`
   - `threads`

3. **Hard Constraints**
   - cultivated-area floor delta in hectares
   - baimu-fang area floor delta in hectares
   - `gamma_conn`
   - `delta_conn`

4. **Results**
   - run status
   - total reward
   - slope change
   - contiguity / baimu metrics when present in summary
   - output directory
   - artifact names
   - map push status

The component should fetch `/api/world-model-v21/status` on mount. The Plan button is disabled unless status is ready and the two required paths are non-empty.

### `frontend/src/components/DataPanel.tsx`

Add the new tab without removing existing tabs:

- import `WorldModelV21Tab`
- add `worldmodel_v21` to `TabKey`
- add an intelligence-group tab labeled `世界模型v2.1`
- render `<WorldModelV21Tab />` when active

## UX Rules

- Keep the view compact and scan-friendly.
- Use visible labels for all inputs.
- Show loading state on the run button.
- Do not rely on color alone; error/warning text must include plain language.
- Keep numeric inputs bounded in the UI to match backend validation.
- Do not display long paths in narrow controls without wrapping or horizontal overflow protection.
- Avoid nested cards. Use one main configuration panel and one results panel.

## Data Flow

1. User opens DataPanel `世界模型v2.1`.
2. Frontend calls `GET /api/world-model-v21/status`.
3. Backend validates Paper9 repo/import availability and returns status.
4. User enters `prepared_dir` and `ensemble_dir`, adjusts MPC parameters.
5. Frontend calls `POST /api/world-model-v21/plan`.
6. Backend validates inputs and calls `farmland_mpc.mpc_plan.run`.
7. Backend reads `mpc_summary.json` and normalizes metrics.
8. Backend queues a map update if spatial output conversion succeeds.
9. Frontend renders summary and fetches `/api/map/pending` to update the map.

## Map Output Handling

Paper9 Tool 4 can write an optimized shapefile. GIS Data Agent should not assume GeoJSON output from Paper9. The adapter should:

- request an `optimized_dltb.shp` output path in the per-user run directory;
- if the shapefile exists, read it with `geopandas`;
- convert it to WGS84;
- simplify only if needed for payload size;
- write a map-friendly artifact under the same run directory;
- queue a `pending_map_updates` payload compatible with existing map handling.

If map conversion fails, the plan response still succeeds with `map_update_queued: false` and includes the conversion error in a non-fatal `warnings` array.

## Configuration

Environment variables:

- `PAPER9_FARMLAND_MPC_REPO`
  - default: `D:\test\_publish\arcgis-farmland-mpc`
- `PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR`
  - default: empty string
- `PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR`
  - default: empty string

The UI should prefill default paths returned by the status endpoint, but users can override them per run.

## Error Handling

- Missing Paper9 repo: show "Paper9 repository not found" and the resolved path.
- `farmland_mpc` import failure: show import error and suggest verifying the repo path or installing dependencies.
- Missing `prepared_dir`: reject before running.
- Missing ONNX members: reject before running.
- ONNX/env block mismatch: surface the Paper9 error text; this is expected when using an ensemble trained for a different region.
- Long-running run failure: return the Paper9 exception text and keep any partial artifact path in the response if available.
- Map conversion failure: treat as warning, not a failed planning run.

## Testing

### Backend Unit Tests

Add tests for:

- status when repo path is missing
- status when repo path exists but package import fails
- status when repo path exists and `farmland_mpc.__version__` is available
- validation rejects invalid `horizon`, `top_k`, `n_episodes`, `continuation`, and `scoring`
- validation rejects missing `prepared_dir`
- validation rejects missing ONNX members
- `run_plan` calls `farmland_mpc.mpc_plan.run` with the expected parameters when mocked
- summary normalization handles a minimal `mpc_summary.json`
- map conversion failure is reported as a warning rather than fatal

### API Tests

Add tests for:

- unauthenticated status and plan return `401`
- invalid JSON returns `400`
- unavailable service returns `503`
- mocked successful planning returns normalized JSON

### Frontend Tests

Add focused tests for:

- initial status loading
- ready status renders repo commit and package version
- Plan button disabled until required paths exist
- request body serializes numeric and nullable constraint fields correctly
- result panel renders output directory and slope metrics
- error state does not overflow the tab container

## Acceptance Criteria

- A new `世界模型v2.1` tab appears under the intelligent-analysis group.
- Existing `世界模型` and `世界模型v2` tabs still work unchanged.
- `GET /api/world-model-v21/status` reports Paper9 source status without requiring a run.
- `POST /api/world-model-v21/plan` can call a mocked `farmland_mpc.mpc_plan.run` in tests and returns normalized output.
- The backend does not import `farmland_mpc` at application startup.
- The implementation does not copy Paper9 algorithm code into GIS Data Agent.
- Missing repo, missing dependency, missing prepared data, and missing ONNX ensemble all produce explicit user-facing errors.
- A successful plan run can queue a map update when spatial output conversion succeeds.

## Future Extensions

After Tool 4 planning is stable, add separate slices for:

- Tool 1 prepare from DLTB + DEM
- Tool 2 transition/pairwise sampling
- Tool 3 contrastive ONNX ensemble training
- async task progress streaming for long-running prepare/train/plan workflows
- benchmark and verification reports from the Paper9 repository
- direct comparison panel between World Model v2 legacy output and v2.1 Paper9 ONNX output
