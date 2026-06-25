# TWM Dynamic World FLUS Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable adapter that packages Dynamic World admin20 rolling cases as FLUS-console inputs and can evaluate FLUS outputs with the existing TWM benchmark metrics.

**Architecture:** Keep the work isolated in one script under `scripts/` plus one focused test module under `data_agent/`. The script reuses the existing public land-cover benchmark loader and metric functions, writes FLUS-compatible rasters/config files, and optionally evaluates a FLUS output raster when present.

**Tech Stack:** Python, NumPy, rasterio, pytest, existing `scripts/build_twm_public_landcover_benchmark.py` helpers, local FLUS console executable.

---

### Task 1: Adapter Behavior Tests

**Files:**
- Create: `data_agent/test_twm_dynamic_world_flus_comparison.py`

- [ ] **Step 1: Write failing tests**

```python
def test_dynamic_world_to_flus_class_mapping_round_trips_nodata():
    module = _load_module()
    arr = np.array([[0, 1, 8], [-32768, 4, 99]], dtype=np.int16)
    valid = np.isin(arr, np.arange(9))
    encoded = module.dynamic_world_to_flus_classes(arr, classes=list(range(9)), valid=valid)
    decoded = module.flus_to_dynamic_world_classes(encoded, classes=list(range(9)), valid=valid)
    assert encoded.tolist() == [[1, 2, 9], [0, 5, 0]]
    assert decoded.tolist() == [[0, 1, 8], [0, 4, 0]]
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run: `pytest data_agent/test_twm_dynamic_world_flus_comparison.py -q`

Expected: FAIL with missing module or missing functions.

### Task 2: Minimal Adapter Script

**Files:**
- Create: `scripts/run_twm_dynamic_world_flus_comparison.py`

- [ ] **Step 1: Implement class mapping helpers**

```python
def dynamic_world_to_flus_classes(arr, *, classes, valid):
    out = np.zeros(arr.shape, dtype=np.uint8)
    for idx, cls in enumerate(classes, start=1):
        out[valid & (arr == cls)] = idx
    return out
```

- [ ] **Step 2: Implement FLUS config, demand CSV, and raster packaging**

The run directory must contain `landuse.tif`, `probability.tif`, `restrict.tif`, `CCregionsimlog.txt`, `CCregionMakovChain.csv`, and `metadata.json`.

- [ ] **Step 3: Implement output evaluation**

Read a FLUS Byte output, map `1..n` back to Dynamic World classes, call `pixel_metrics`, and return a `flus_console_direct` metric payload.

### Task 3: Verification

**Files:**
- Test: `data_agent/test_twm_dynamic_world_flus_comparison.py`
- Script: `scripts/run_twm_dynamic_world_flus_comparison.py`

- [ ] **Step 1: Run unit tests**

Run: `pytest data_agent/test_twm_dynamic_world_flus_comparison.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run package-only smoke on one real admin20 case**

Run: `python scripts/run_twm_dynamic_world_flus_comparison.py --manifest data/twm_public_landcover/gee_dynamic_world/twm_dynamic_world_manifest.json --region-limit 1 --case-limit 1 --output docs/reports/twm_dynamic_world_admin20_flus_smoke_2026-06-23.json --run-root /private/tmp/twm_flus_admin20_smoke --no-run-flus`

Expected: report status `pass`, one packaged case, and all expected FLUS input files exist.
