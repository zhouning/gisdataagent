# Paper58 and GeoSOS-FLUS Full Runtime Design

## Goal

Build a real World Model v1.1 runtime workflow in GIS Data Agent, so the tab can run Paper58 and GeoSOS-FLUS end to end, evaluate the outputs, and load the generated results onto the map.

The current World Model v1.1 tab is still primarily a visualization surface for precomputed Paper58 benchmark artifacts. The new workflow must let an operator start a fresh run from a same-grid sample, track execution, inspect metrics, and view Paper58 and GeoSOS outputs as map layers.

## Current Context

GIS Data Agent already has a World Model v1.1 page and backend routes for Paper58 benchmark visualization. Those routes read local Paper58 benchmark output directories and build map layers from existing arrays and GeoTIFFs.

The local Paper58 repository is:

`/Users/zhouning/paper58-geofm-world-model-rl`

The local GeoSOS-FLUS source and console implementation is:

`/Users/zhouning/FLUS_console_crossplatform`

The runnable GeoSOS-FLUS console is:

`/Users/zhouning/FLUS_console_crossplatform/build/flus_console`

GeoSOS-FLUS is the confirmed comparison model for this workflow. Product text, API fields, manifests, tests, and implementation should use the GeoSOS-FLUS name consistently.

## Non-Goals

- Do not treat precomputed benchmark visualization as a full runtime run.
- Do not call long-running model scripts directly from the frontend request path.
- Do not introduce a separate GeoSOS comparison model.
- Do not claim that Paper58 is a general production replacement for all TWM generation routes.
- Do not require online AlphaEarth or external cloud access for the first runnable version.
- Do not hide failed, missing, or unconfigured engines behind successful-looking UI states.

## Recommended Approach

Use a staged runtime framework:

1. **Stage 1: sample-level full rerun**
   - Select an existing Paper58 same-grid sample.
   - Validate input rasters, classes, grid shape, CRS, and transform metadata.
   - Run Paper58 through a local adapter using the available Paper58 scripts and cached benchmark inputs.
   - Run GeoSOS-FLUS through the local console adapter.
   - Compute shared metrics.
   - Export generated map layers.
   - Display run status, logs, metrics, and map actions in the World Model v1.1 tab.

2. **Stage 2: custom-region runs**
   - Add upload or registered-dataset inputs for start-year LULC, target-year LULC, drivers, constraints, demand, and optional masks.
   - Reuse the same case validation, model adapters, metrics, and map export pipeline.

The first implementation should deliver Stage 1 completely. That gives the user an actual runnable Paper58 versus GeoSOS-FLUS effect inside GIS Data Agent before broadening the input contract.

## Backend Architecture

Create a focused runtime package:

`data_agent/paper58_runtime/models.py`

- Defines run request, run status, case summary, engine status, metric summary, layer summary, and manifest dataclasses.
- Uses plain serializable structures compatible with the existing FastAPI-style JSON routes.

`data_agent/paper58_runtime/case_loader.py`

- Discovers Paper58 same-grid samples from the local Paper58 benchmark input and output directories.
- Reads sample identifiers, area names, year range, raster dimensions, class mapping, CRS, bounds, and available methods.
- Rejects samples with missing rasters, mismatched grid dimensions, unknown class mappings, or missing georeferencing metadata.

`data_agent/paper58_runtime/paper58_adapter.py`

- Wraps the Paper58 local repository.
- Resolves the scripts and artifact directories needed for a same-grid run.
- Produces a Paper58 prediction raster, metrics-ready arrays, logs, and an adapter manifest.
- Records the Paper58 repository path, script path, input sample, method name, random seed, and output hashes.

`data_agent/paper58_runtime/flus_adapter.py`

- Defines a GeoSOS-FLUS adapter interface with `probe()`, `prepare_case()`, `run()`, `collect_outputs()`, and `build_manifest()`.
- Implements `GeoSOSFLUSAdapter` against `/Users/zhouning/FLUS_console_crossplatform/build/flus_console`.
- Records the GeoSOS-FLUS source path, console path, case directory, command, return code, stdout, stderr, and output hashes.

`data_agent/paper58_runtime/metrics.py`

- Computes shared metrics for Paper58 and GeoSOS outputs:
  - overall accuracy
  - change precision
  - change recall
  - change F1
  - figure of merit
  - transition accuracy
  - demand residual by class
  - runtime seconds

`data_agent/paper58_runtime/map_export.py`

- Converts generated rasters into compact map layers using the source raster transform and CRS.
- Produces layers for:
  - start-year land use
  - observed target-year land use
  - Paper58 predicted target-year land use
  - GeoSOS-FLUS predicted target-year land use
  - Paper58 error map
  - GeoSOS-FLUS error map
  - Paper58 versus GeoSOS-FLUS disagreement map
- Ensures exported layer bounds stay on the source study area and do not drift into the ocean because of pixel-space coordinates.

`data_agent/paper58_runtime/runner.py`

- Orchestrates the run stages in a background-safe service function.
- Creates one output directory per run.
- Writes stage status transitions, logs, manifests, metrics, and layer metadata.
- Supports polling from the frontend.

## Storage Layout

Runtime outputs should be written under:

`outputs/world_model_v11_runs/{run_id}/`

Each run directory contains:

- `run_manifest.json`
- `status.json`
- `metrics.json`
- `case/`
- `paper58/`
- `geosos_flus/`
- `layers/`
- `logs/`

The manifest records:

- run id
- created timestamp
- selected case
- engine configuration
- input file paths and hashes
- model method names
- executable or script paths
- stdout and stderr file paths
- output artifact paths
- map layer ids
- metric summary
- warnings and errors

## API Design

Add runtime routes alongside the existing visualization routes:

`GET /api/twm/world-model-v11/runtime/cases`

- Returns available same-grid samples and engine availability.
- Includes separate statuses for `paper58` and `geosos_flus`.

`POST /api/twm/world-model-v11/runtime/runs`

- Starts a run for one case.
- Accepts Paper58 method, GeoSOS-FLUS run options, seed, and run mode.
- Returns `run_id`, initial status, and polling URL.
- Rejects requests when Paper58 or GeoSOS-FLUS prerequisites are unavailable.

`GET /api/twm/world-model-v11/runtime/runs/{run_id}`

- Returns stage status, logs summary, metrics, warnings, errors, and available map layers.

`POST /api/twm/world-model-v11/runtime/runs/{run_id}/map`

- Queues generated layers into the existing map update mechanism.
- Refuses to map a failed or incomplete run unless the requested layers exist.

## Frontend UX

Revise the World Model v1.1 tab into two clear modes:

1. **结果查看**
   - Keeps the current benchmark visualization workflow.
   - Shows existing Paper58 versus GeoSOS-FLUS benchmark results.
   - Clearly labels these as historical or precomputed benchmark outputs.

2. **全流程运行**
   - Lets the user select a sample area.
   - Lets the user choose Paper58 method and GeoSOS-FLUS run options.
   - Shows `GeoSOS-FLUS 可运行` when the local console probe succeeds.
   - Starts a run and polls stage status.
   - Shows a compact timeline:
     - 输入检查
     - Paper58 运行
     - GeoSOS-FLUS 运行
     - 指标计算
     - 图层生成
     - 可视化发布
   - Shows a metrics table comparing Paper58 and GeoSOS.
   - Provides one map action after layers are generated.

All visible text in the tab should be Chinese. Font size, spacing, cards, table density, and action placement should be consistent with the rest of GIS Data Agent. English identifiers can remain in technical details, logs, and file names.

## Error Handling

- Missing Paper58 repository: return `paper58 unavailable` with the missing path.
- Missing FLUS console binary: return `geosos_flus unavailable` with the expected path.
- Raster shape mismatch: fail during input validation before any model starts.
- Missing CRS or transform: fail map export and keep the run artifacts available for inspection.
- Model execution failure: store stdout, stderr, return code, stage name, and command.
- Partial outputs: show the completed stages and disable unavailable map layers.

## Testing Plan

Backend unit tests:

- Case discovery returns same-grid samples with area, years, shape, CRS, and bounds.
- Case validation rejects mismatched rasters and missing georeferencing.
- Paper58 adapter builds a manifest and output paths from a fixture run.
- GeoSOS-FLUS adapter probes the local console path and supports a fake executable in tests.
- Metrics compute accuracy, change F1, figure of merit, transition accuracy, and demand residual on small arrays.
- Map export uses raster georeferencing and never emits pixel-space ocean-shifted bounds.
- Runtime routes start, poll, and map a completed fixture run.

Frontend and contract tests:

- The World Model v1.1 tab exposes `结果查看` and `全流程运行`.
- The full-run form shows Paper58 and GeoSOS-FLUS availability separately.
- The UI shows stage status and metrics after a completed fixture run.
- The map button appears only after generated layers are available.

End-to-end smoke test:

- Start GIS Data Agent locally.
- Open `世界模型v1.1`.
- Switch to `全流程运行`.
- Select a small same-grid sample.
- Run Paper58 and GeoSOS-FLUS.
- Wait for completion.
- Load generated layers into the map.
- Verify the layer list, timeline behavior, and map bounds.

## Acceptance Criteria

- A user can start a new Paper58 and GeoSOS-FLUS run from the World Model v1.1 tab.
- The run creates a durable output directory with manifest, logs, metrics, and layers.
- The UI clearly distinguishes precomputed benchmark viewing from newly executed runtime runs.
- GeoSOS-FLUS is called through the local `/Users/zhouning/FLUS_console_crossplatform` implementation.
- Failed stages surface actionable error messages and preserve logs.
- Generated map layers use source georeferencing and stay over the study area.
- Automated tests cover backend services, route contracts, frontend contract behavior, and one local e2e smoke path.

## Implementation Boundary

The first implementation should focus on same-grid Paper58 samples and local GeoSOS-FLUS execution. It should not add custom raster upload, online AlphaEarth retrieval, or any additional GeoSOS engine abstraction. Those are separate follow-up increments after the core runtime contract is stable.
