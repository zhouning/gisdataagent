# Paper58 GeoSOS-FLUS Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a World Model v1.1 runtime workflow that creates a new Paper58 versus GeoSOS-FLUS run artifact, computes metrics, and publishes generated map layers.

**Architecture:** Add a focused `data_agent/paper58_runtime/` package for case discovery, Paper58 artifact materialization, GeoSOS-FLUS execution, metrics, map export, and run orchestration. Extend `world_model_v11_routes.py` with runtime endpoints and revise `WorldModelV11Tab.tsx` into `结果查看` and `全流程运行` modes.

**Tech Stack:** Python 3, Starlette routes, NumPy, rasterio, existing Paper58 helper scripts, GeoSOS-FLUS console, React/TypeScript, existing map pending-update mechanism, pytest, Vite, Playwright.

---

## File Structure

- Create `data_agent/paper58_runtime/__init__.py`: package exports.
- Create `data_agent/paper58_runtime/models.py`: serializable dataclasses and constants.
- Create `data_agent/paper58_runtime/metrics.py`: shared metric calculations over same-grid arrays.
- Create `data_agent/paper58_runtime/case_loader.py`: discover and validate same-grid Paper58 samples.
- Create `data_agent/paper58_runtime/paper58_adapter.py`: materialize local Paper58 method output into a new run directory with provenance.
- Create `data_agent/paper58_runtime/flus_adapter.py`: prepare a FLUS case and call the local GeoSOS-FLUS console.
- Create `data_agent/paper58_runtime/map_export.py`: convert run rasters into map-ready GeoJSON layers.
- Create `data_agent/paper58_runtime/runner.py`: create run directories, advance stages, write manifests, support polling, and queue map updates.
- Modify `data_agent/api/world_model_v11_routes.py`: add runtime cases, run start, run status, and run map endpoints.
- Modify `frontend/src/components/datapanel/WorldModelV11Tab.tsx`: add two modes and runtime controls/status.
- Modify `frontend/src/styles/layout.css`: normalize World Model v1.1 layout for both modes.
- Modify `data_agent/test_world_model_v11_routes.py`: route and auth tests for runtime endpoints.
- Add `data_agent/test_paper58_runtime.py`: service-level runtime tests.
- Modify `data_agent/test_world_model_v11_frontend_contract.py`: frontend runtime contract assertions.
- Modify `tests/e2e/specs/world_model_v11_paper58.spec.ts`: cover `全流程运行` smoke behavior.

## Task 1: Runtime Models and Metrics

**Files:**
- Create: `data_agent/paper58_runtime/__init__.py`
- Create: `data_agent/paper58_runtime/models.py`
- Create: `data_agent/paper58_runtime/metrics.py`
- Test: `data_agent/test_paper58_runtime.py`

- [ ] **Step 1: Write failing metric tests**

Add this to `data_agent/test_paper58_runtime.py`:

```python
import numpy as np


def test_runtime_metrics_compare_change_and_transition_quality():
    from data_agent.paper58_runtime.metrics import compute_prediction_metrics

    start = np.array([[1, 1, 2], [2, 2, 2]], dtype=np.int16)
    observed = np.array([[1, 2, 2], [2, 1, 2]], dtype=np.int16)
    predicted = np.array([[1, 2, 1], [2, 2, 2]], dtype=np.int16)
    valid = np.ones(start.shape, dtype=bool)

    metrics = compute_prediction_metrics(start, observed, predicted, valid)

    assert metrics["n_pixels"] == 6
    assert metrics["true_change_pixels"] == 2
    assert metrics["pred_change_pixels"] == 2
    assert metrics["change_precision"] == 0.5
    assert metrics["change_recall"] == 0.5
    assert metrics["change_f1"] == 0.5
    assert metrics["fom"] == 1 / 3
    assert metrics["transition_accuracy"] == 0.5
    assert metrics["demand_residual_by_class"] == {"1": 1, "2": -1}


def test_runtime_metrics_reject_shape_mismatch():
    from data_agent.paper58_runtime.metrics import compute_prediction_metrics

    start = np.zeros((2, 2), dtype=np.int16)
    observed = np.zeros((2, 2), dtype=np.int16)
    predicted = np.zeros((3, 2), dtype=np.int16)

    try:
        compute_prediction_metrics(start, observed, predicted)
    except ValueError as exc:
        assert "same shape" in str(exc)
    else:
        raise AssertionError("expected shape mismatch")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_runtime_metrics_compare_change_and_transition_quality data_agent/test_paper58_runtime.py::test_runtime_metrics_reject_shape_mismatch -q
```

Expected: both tests fail because `data_agent.paper58_runtime.metrics` does not exist.

- [ ] **Step 3: Implement model and metric code**

Create `data_agent/paper58_runtime/__init__.py`:

```python
"""Runtime helpers for World Model v1.1 Paper58 versus GeoSOS-FLUS runs."""
```

Create `data_agent/paper58_runtime/models.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_PAPER58_METHOD = "paper58_spatial_demand_ratio_claim_robustness_v4"
BASELINE_METHOD = "geosos_flus_console"
RUNTIME_SCHEMA = "territory_world_model.paper58_geosos_flus_runtime.v1"
RUN_SCHEMA = "territory_world_model.paper58_geosos_flus_runtime_run.v1"
MAP_SCHEMA = "territory_world_model.paper58_geosos_flus_runtime_map.v1"


@dataclass(frozen=True)
class RuntimePaths:
    benchmark_dir: Path
    output_root: Path
    flus_executable: Path


@dataclass(frozen=True)
class RuntimeCase:
    area: str
    display_name: str
    start_year: int
    end_year: int
    shape: tuple[int, int]
    valid_pixels: int
    changed_pixels: int
    start_path: Path
    end_path: Path
    paper58_prediction_path: Path
    georef_path: Path | None
    methods: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["shape"] = list(self.shape)
        for key in ("start_path", "end_path", "paper58_prediction_path", "georef_path"):
            value = payload.get(key)
            payload[key] = str(value) if value else None
        payload["methods"] = list(self.methods)
        return payload


@dataclass
class RunStage:
    key: str
    label: str
    status: str = "pending"
    message: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class RuntimeRun:
    run_id: str
    status: str
    case: dict[str, Any]
    paper58_method: str
    output_dir: Path
    stages: list[RunStage] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    layers: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RUN_SCHEMA,
            "run_id": self.run_id,
            "status": self.status,
            "case": self.case,
            "paper58_method": self.paper58_method,
            "output_dir": str(self.output_dir),
            "stages": [stage.to_dict() for stage in self.stages],
            "metrics": self.metrics,
            "layers": self.layers,
            "error": self.error,
        }
```

Create `data_agent/paper58_runtime/metrics.py`:

```python
from __future__ import annotations

from typing import Any

import numpy as np


def _as_2d(name: str, value: np.ndarray) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2:
        raise ValueError(f"{name} must be a 2D array, got {array.shape}")
    return array


def _round(value: float) -> float:
    return round(float(value), 6)


def compute_prediction_metrics(
    start: np.ndarray,
    observed: np.ndarray,
    predicted: np.ndarray,
    valid_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    start_arr = _as_2d("start", start)
    observed_arr = _as_2d("observed", observed)
    predicted_arr = _as_2d("predicted", predicted)
    if start_arr.shape != observed_arr.shape or start_arr.shape != predicted_arr.shape:
        raise ValueError("start, observed, and predicted must have the same shape")
    if valid_mask is None:
        valid = (start_arr != 0) & (observed_arr != 0) & (predicted_arr != 0)
    else:
        valid = np.asarray(valid_mask, dtype=bool)
        if valid.shape != start_arr.shape:
            raise ValueError("valid_mask must have the same shape as the raster arrays")

    true_change = valid & (observed_arr != start_arr)
    pred_change = valid & (predicted_arr != start_arr)
    hit_change = true_change & pred_change
    union_change = true_change | pred_change
    transition_hit = true_change & (predicted_arr == observed_arr)

    true_count = int(np.count_nonzero(true_change))
    pred_count = int(np.count_nonzero(pred_change))
    hit_count = int(np.count_nonzero(hit_change))
    union_count = int(np.count_nonzero(union_change))
    transition_count = int(np.count_nonzero(transition_hit))
    precision = hit_count / pred_count if pred_count else 0.0
    recall = hit_count / true_count if true_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fom = transition_count / union_count if union_count else 0.0
    transition_accuracy = transition_count / true_count if true_count else 0.0
    classes = sorted({int(v) for v in np.unique(observed_arr[valid])} | {int(v) for v in np.unique(predicted_arr[valid])})
    residual = {
        str(cls): int(np.count_nonzero(predicted_arr[valid] == cls) - np.count_nonzero(observed_arr[valid] == cls))
        for cls in classes
    }
    return {
        "n_pixels": int(np.count_nonzero(valid)),
        "true_change_pixels": true_count,
        "pred_change_pixels": pred_count,
        "change_precision": _round(precision),
        "change_recall": _round(recall),
        "change_f1": _round(f1),
        "fom": _round(fom),
        "transition_accuracy": _round(transition_accuracy),
        "demand_residual_by_class": residual,
    }
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_runtime_metrics_compare_change_and_transition_quality data_agent/test_paper58_runtime.py::test_runtime_metrics_reject_shape_mismatch -q
```

Expected: both tests pass.

## Task 2: Case Discovery

**Files:**
- Create: `data_agent/paper58_runtime/case_loader.py`
- Test: `data_agent/test_paper58_runtime.py`

- [ ] **Step 1: Add failing case discovery tests**

Append:

```python
import json
from pathlib import Path


def _write_case_fixture(root: Path) -> Path:
    labels = root / "inputs" / "labels"
    predictions = root / "inputs" / "predictions"
    labels.mkdir(parents=True)
    predictions.mkdir(parents=True)
    np.save(labels / "xiangzhen_record_000191_lulc_2020.npy", np.array([[1, 1], [2, 2]], dtype=np.int16))
    np.save(labels / "xiangzhen_record_000191_lulc_2021.npy", np.array([[1, 2], [2, 2]], dtype=np.int16))
    np.save(predictions / "xiangzhen_record_000191_lulc_pred_2020_2021.npy", np.array([[1, 2], [1, 2]], dtype=np.int16))
    method_dir = root / "maps" / "paper58_spatial_demand_ratio_claim_robustness_v4"
    method_dir.mkdir(parents=True)
    np.save(method_dir / "xiangzhen_record_000191_2020_2021_paper58_spatial_demand_ratio_claim_robustness_v4.npy", np.array([[1, 2], [2, 2]], dtype=np.int16))
    manifest = {
        "labels_dir": str(labels),
        "paper58_predictions_dir": str(predictions),
        "samples": [{
            "area": "xiangzhen_record_000191",
            "start_year": 2020,
            "end_year": 2021,
            "shape": [2, 2],
            "valid_pixels": 4,
            "changed_pixels": 1,
            "prediction_path": str(predictions / "xiangzhen_record_000191_lulc_pred_2020_2021.npy"),
        }],
    }
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_discover_runtime_cases_reads_manifest_and_methods(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases

    root = _write_case_fixture(tmp_path)
    cases = discover_runtime_cases(root)

    assert len(cases) == 1
    assert cases[0].area == "xiangzhen_record_000191"
    assert cases[0].shape == (2, 2)
    assert cases[0].methods == ("paper58_latent_dynamics", "paper58_spatial_demand_ratio_claim_robustness_v4")


def test_discover_runtime_cases_rejects_mismatched_shape(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases

    root = _write_case_fixture(tmp_path)
    np.save(root / "inputs" / "labels" / "xiangzhen_record_000191_lulc_2021.npy", np.zeros((3, 2), dtype=np.int16))

    try:
        discover_runtime_cases(root)
    except ValueError as exc:
        assert "shape mismatch" in str(exc)
    else:
        raise AssertionError("expected shape mismatch")
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_discover_runtime_cases_reads_manifest_and_methods data_agent/test_paper58_runtime.py::test_discover_runtime_cases_rejects_mismatched_shape -q
```

Expected: fail because `case_loader.py` does not exist.

- [ ] **Step 3: Implement case discovery**

Create `data_agent/paper58_runtime/case_loader.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .models import DEFAULT_PAPER58_METHOD, RuntimeCase


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing Paper58 run manifest: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    return payload


def _load_grid(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"missing runtime raster array: {path}")
    grid = np.asarray(np.load(path))
    if grid.ndim != 2:
        raise ValueError(f"runtime raster must be 2D: {path} shape={grid.shape}")
    return grid


def _method_path(root: Path, area: str, start_year: int, end_year: int, method: str) -> Path:
    return root / "maps" / method / f"{area}_{start_year}_{end_year}_{method}.npy"


def _georef_path(root: Path, labels_dir: Path, area: str, start_year: int, end_year: int) -> Path | None:
    roots = [labels_dir.parent, root, root.parent]
    for base in roots:
        for year in (start_year, end_year):
            candidate = base / "downloads" / area / f"{area}_esri_lulc_{year}.tif"
            if candidate.exists():
                return candidate
    return None


def discover_runtime_cases(root: Path | str) -> list[RuntimeCase]:
    benchmark = Path(root).expanduser()
    manifest = _load_json(benchmark / "run_manifest.json")
    labels_dir = Path(str(manifest.get("labels_dir", ""))).expanduser()
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise ValueError("Paper58 run manifest must contain a samples list")

    cases: list[RuntimeCase] = []
    for item in samples:
        if not isinstance(item, dict):
            continue
        area = str(item.get("area") or "")
        start_year = int(item.get("start_year", 2020))
        end_year = int(item.get("end_year", 2021))
        prediction_path = Path(str(item.get("prediction_path") or "")).expanduser()
        start_path = labels_dir / f"{area}_lulc_{start_year}.npy"
        end_path = labels_dir / f"{area}_lulc_{end_year}.npy"
        start = _load_grid(start_path)
        end = _load_grid(end_path)
        pred = _load_grid(prediction_path)
        if start.shape != end.shape or start.shape != pred.shape:
            raise ValueError(f"shape mismatch for {area}: start={start.shape}, end={end.shape}, prediction={pred.shape}")
        methods = ["paper58_latent_dynamics"]
        if _method_path(benchmark, area, start_year, end_year, DEFAULT_PAPER58_METHOD).exists():
            methods.append(DEFAULT_PAPER58_METHOD)
        valid = (start != 0) & (end != 0) & (pred != 0)
        cases.append(
            RuntimeCase(
                area=area,
                display_name=area.replace("xiangzhen_record_", ""),
                start_year=start_year,
                end_year=end_year,
                shape=(int(start.shape[0]), int(start.shape[1])),
                valid_pixels=int(np.count_nonzero(valid)),
                changed_pixels=int(np.count_nonzero(valid & (start != end))),
                start_path=start_path,
                end_path=end_path,
                paper58_prediction_path=prediction_path,
                georef_path=_georef_path(benchmark, labels_dir, area, start_year, end_year),
                methods=tuple(methods),
            )
        )
    return sorted(cases, key=lambda case: case.area)
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_discover_runtime_cases_reads_manifest_and_methods data_agent/test_paper58_runtime.py::test_discover_runtime_cases_rejects_mismatched_shape -q
```

Expected: both pass.

## Task 3: Paper58 and GeoSOS-FLUS Adapters

**Files:**
- Create: `data_agent/paper58_runtime/paper58_adapter.py`
- Create: `data_agent/paper58_runtime/flus_adapter.py`
- Test: `data_agent/test_paper58_runtime.py`

- [ ] **Step 1: Add failing adapter tests**

Append:

```python
def test_paper58_adapter_materializes_selected_method(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases
    from data_agent.paper58_runtime.paper58_adapter import materialize_paper58_prediction

    root = _write_case_fixture(tmp_path / "benchmark")
    case = discover_runtime_cases(root)[0]
    result = materialize_paper58_prediction(root, case, "paper58_spatial_demand_ratio_claim_robustness_v4", tmp_path / "run")

    assert result["method"] == "paper58_spatial_demand_ratio_claim_robustness_v4"
    assert Path(result["prediction_path"]).exists()
    assert np.load(result["prediction_path"]).tolist() == [[1, 2], [2, 2]]
    assert result["provenance"]["source_mode"] == "local_paper58_artifact"


def test_flus_adapter_uses_fake_console_and_collects_output(tmp_path):
    from data_agent.paper58_runtime.case_loader import discover_runtime_cases
    from data_agent.paper58_runtime.flus_adapter import run_geosos_flus

    root = _write_case_fixture(tmp_path / "benchmark")
    case = discover_runtime_cases(root)[0]

    def fake_runner(case_dir: Path) -> None:
        import rasterio
        from rasterio.transform import from_origin

        with rasterio.open(
            case_dir / "simresult.tif",
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            transform=from_origin(0, 2, 1, 1),
        ) as dataset:
            dataset.write(np.array([[1, 2], [2, 2]], dtype=np.uint8), 1)

    result = run_geosos_flus(case, tmp_path / "run", flus_executable=Path("/fake/flus_console"), console_runner=fake_runner)

    assert result["method"] == "geosos_flus_console"
    assert Path(result["prediction_path"]).exists()
    assert np.load(result["prediction_npy_path"]).tolist() == [[1, 2], [2, 2]]
    assert result["return_code"] == 0
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_paper58_adapter_materializes_selected_method data_agent/test_paper58_runtime.py::test_flus_adapter_uses_fake_console_and_collects_output -q
```

Expected: fail because adapter modules do not exist.

- [ ] **Step 3: Implement Paper58 adapter**

Create `data_agent/paper58_runtime/paper58_adapter.py` with:

```python
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from .models import DEFAULT_PAPER58_METHOD, RuntimeCase


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selected_prediction_path(root: Path, case: RuntimeCase, method: str) -> Path:
    if method == "paper58_latent_dynamics":
        return case.paper58_prediction_path
    return root / "maps" / method / f"{case.area}_{case.start_year}_{case.end_year}_{method}.npy"


def materialize_paper58_prediction(
    benchmark_dir: Path | str,
    case: RuntimeCase,
    method: str,
    run_dir: Path | str,
) -> dict[str, Any]:
    root = Path(benchmark_dir).expanduser()
    selected_method = method or DEFAULT_PAPER58_METHOD
    source_path = _selected_prediction_path(root, case, selected_method)
    if not source_path.exists():
        raise FileNotFoundError(f"missing Paper58 prediction for {case.area}/{selected_method}: {source_path}")
    prediction = np.asarray(np.load(source_path))
    if prediction.shape != case.shape:
        raise ValueError(f"Paper58 prediction shape mismatch for {case.area}: {prediction.shape} vs {case.shape}")
    output_dir = Path(run_dir) / "paper58"
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / f"{case.area}_{case.start_year}_{case.end_year}_{selected_method}.npy"
    shutil.copyfile(source_path, prediction_path)
    manifest = {
        "method": selected_method,
        "prediction_path": str(prediction_path),
        "provenance": {
            "source_mode": "local_paper58_artifact",
            "source_path": str(source_path),
            "source_sha256": _hash_file(source_path),
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
```

- [ ] **Step 4: Implement GeoSOS-FLUS adapter**

Create `data_agent/paper58_runtime/flus_adapter.py` with:

```python
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from scripts.paper58_benchmark.flus_case import decode_flus_geotiff, find_flus_simulation_result, write_flus_case
from scripts.paper58_benchmark.las_demand import derive_demand
from scripts.paper58_benchmark.las_suitability import class_values_from_maps, one_hot_probability_cube, transition_prior_from_pairs

from .models import BASELINE_METHOD, RuntimeCase


ConsoleRunner = Callable[[Path], None]


def probe_flus_console(flus_executable: Path | str) -> dict[str, Any]:
    path = Path(flus_executable).expanduser()
    return {"available": path.exists() and path.is_file(), "path": str(path)}


def run_geosos_flus(
    case: RuntimeCase,
    run_dir: Path | str,
    flus_executable: Path | str,
    console_runner: ConsoleRunner | None = None,
) -> dict[str, Any]:
    output_dir = Path(run_dir) / "geosos_flus"
    case_dir = output_dir / "case"
    maps_dir = output_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    start = np.asarray(np.load(case.start_path)).astype(np.int32, copy=False)
    end = np.asarray(np.load(case.end_path)).astype(np.int32, copy=False)
    paper58 = np.asarray(np.load(case.paper58_prediction_path)).astype(np.int32, copy=False)
    valid_mask = (start != 0) & (end != 0) & (paper58 != 0)
    classes = class_values_from_maps(start, end, paper58)
    probability = one_hot_probability_cube(paper58, classes, confidence=0.95, floor=0.01)
    demand = derive_demand(start, end, paper58, demand_source="paper58_prediction", class_values=classes, transition_prior=transition_prior_from_pairs([], classes))
    write_flus_case(
        output_dir=case_dir,
        start_map=start,
        probability_cube=probability,
        class_values=classes,
        future_demand=demand,
        end_year=case.end_year,
        restrict_mask=valid_mask.astype(np.uint8),
    )
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    return_code = 0
    if console_runner is None:
        completed = subprocess.run([str(Path(flus_executable).expanduser())], cwd=case_dir, check=False, text=True, capture_output=True)
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        return_code = int(completed.returncode)
        if completed.returncode != 0:
            raise RuntimeError(f"GeoSOS-FLUS console failed with return code {completed.returncode}")
    else:
        console_runner(case_dir)
        stdout_path.write_text("fake console runner completed\n", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
    encoded = find_flus_simulation_result(case_dir, case.end_year)
    decoded_tif = maps_dir / f"{case.area}_{case.start_year}_{case.end_year}_flus.tif"
    decode_flus_geotiff(encoded, decoded_tif, classes)
    import rasterio

    with rasterio.open(decoded_tif) as dataset:
        decoded = dataset.read(1)
    decoded_npy = maps_dir / f"{case.area}_{case.start_year}_{case.end_year}_flus.npy"
    np.save(decoded_npy, decoded)
    return {
        "method": BASELINE_METHOD,
        "case_dir": str(case_dir),
        "prediction_path": str(decoded_tif),
        "prediction_npy_path": str(decoded_npy),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "return_code": return_code,
    }
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_paper58_adapter_materializes_selected_method data_agent/test_paper58_runtime.py::test_flus_adapter_uses_fake_console_and_collects_output -q
```

Expected: both pass.

## Task 4: Runner and Map Export

**Files:**
- Create: `data_agent/paper58_runtime/map_export.py`
- Create: `data_agent/paper58_runtime/runner.py`
- Test: `data_agent/test_paper58_runtime.py`

- [ ] **Step 1: Add failing runner tests**

Append:

```python
def test_runtime_runner_creates_completed_run_and_layers(tmp_path):
    from data_agent.paper58_runtime.runner import run_runtime_once

    root = _write_case_fixture(tmp_path / "benchmark")

    def fake_runner(case_dir: Path) -> None:
        import rasterio
        from rasterio.transform import from_origin

        with rasterio.open(
            case_dir / "simresult.tif",
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="uint8",
            transform=from_origin(0, 2, 1, 1),
        ) as dataset:
            dataset.write(np.array([[1, 2], [2, 2]], dtype=np.uint8), 1)

    run = run_runtime_once(
        benchmark_dir=root,
        output_root=tmp_path / "runs",
        area="xiangzhen_record_000191",
        method="paper58_spatial_demand_ratio_claim_robustness_v4",
        flus_executable=Path("/fake/flus_console"),
        console_runner=fake_runner,
    )

    assert run["status"] == "completed"
    assert run["metrics"]["paper58"]["change_f1"] == 1.0
    assert run["metrics"]["geosos_flus"]["change_f1"] == 1.0
    assert Path(run["output_dir"], "run_manifest.json").exists()
    assert [layer["name"] for layer in run["layers"]] == [
        "起始土地利用 2020",
        "真实土地利用 2021",
        "Paper58 预测土地利用 2021",
        "GeoSOS-FLUS 预测土地利用 2021",
        "Paper58 误差 2021",
        "GeoSOS-FLUS 误差 2021",
        "Paper58 与 GeoSOS-FLUS 分歧 2021",
    ]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_runtime_runner_creates_completed_run_and_layers -q
```

Expected: fail because runner/map export modules do not exist.

- [ ] **Step 3: Implement map export**

Create `data_agent/paper58_runtime/map_export.py` by adapting the existing `data_agent/paper58_visualization.py` `_grid_to_geojson`, `_resolve_area_georef`, `_lulc_style_map`, `_difference_style_map`, and `_map_view` behavior. Export one function with this signature:

```python
def build_runtime_map_layers(
    run_dir: Path,
    case: RuntimeCase,
    start: np.ndarray,
    observed: np.ndarray,
    paper58: np.ndarray,
    flus: np.ndarray,
) -> dict[str, Any]:
    layer_dir = Path(run_dir) / "layers"
    layer_dir.mkdir(parents=True, exist_ok=True)
    # The implementation writes the seven files listed below and returns
    # metadata using the existing categorized GeoJSON map-update contract.
```

The function writes seven GeoJSON files under `run_dir / "layers"` and returns a payload with these concrete layer metadata records:

```python
{
    "layers": [
        {"name": f"起始土地利用 {case.start_year}", "geojson": "runtime_start.geojson", "type": "categorized", "visible": True},
        {"name": f"真实土地利用 {case.end_year}", "geojson": "runtime_observed.geojson", "type": "categorized", "visible": False},
        {"name": f"Paper58 预测土地利用 {case.end_year}", "geojson": "runtime_paper58.geojson", "type": "categorized", "visible": True},
        {"name": f"GeoSOS-FLUS 预测土地利用 {case.end_year}", "geojson": "runtime_geosos_flus.geojson", "type": "categorized", "visible": True},
        {"name": f"Paper58 误差 {case.end_year}", "geojson": "runtime_paper58_error.geojson", "type": "categorized", "visible": False},
        {"name": f"GeoSOS-FLUS 误差 {case.end_year}", "geojson": "runtime_geosos_flus_error.geojson", "type": "categorized", "visible": False},
        {"name": f"Paper58 与 GeoSOS-FLUS 分歧 {case.end_year}", "geojson": "runtime_disagreement.geojson", "type": "categorized", "visible": False},
    ],
    "center": [34.75, 113.05],
    "zoom": 12,
    "display_crs": "EPSG:4326",
    "georeferenced": True,
}
```

- [ ] **Step 4: Implement runner**

Create `data_agent/paper58_runtime/runner.py` with:

```python
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from .case_loader import discover_runtime_cases
from .flus_adapter import ConsoleRunner, probe_flus_console, run_geosos_flus
from .map_export import build_runtime_map_layers
from .metrics import compute_prediction_metrics
from .models import DEFAULT_PAPER58_METHOD, MAP_SCHEMA, RUNTIME_SCHEMA
from .paper58_adapter import materialize_paper58_prediction


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def runtime_cases_payload(benchmark_dir: Path | str | None, flus_executable: Path | str) -> dict[str, Any]:
    if benchmark_dir is None:
        return {"schema": RUNTIME_SCHEMA, "status": "missing", "cases": [], "engines": {"paper58": {"available": False}, "geosos_flus": probe_flus_console(flus_executable)}, "missing": ["paper58_benchmark_dir_not_provided"]}
    root = Path(benchmark_dir).expanduser()
    cases = discover_runtime_cases(root) if root.exists() else []
    return {"schema": RUNTIME_SCHEMA, "status": "ready" if cases else "missing", "cases": [case.to_dict() for case in cases], "engines": {"paper58": {"available": bool(cases), "path": str(root)}, "geosos_flus": probe_flus_console(flus_executable)}, "missing": [] if cases else ["paper58_runtime_cases_not_found"]}


def run_runtime_once(
    benchmark_dir: Path | str,
    output_root: Path | str,
    area: str,
    method: str = DEFAULT_PAPER58_METHOD,
    flus_executable: Path | str = "/Users/zhouning/FLUS_console_crossplatform/build/flus_console",
    console_runner: ConsoleRunner | None = None,
) -> dict[str, Any]:
    started = time.time()
    root = Path(benchmark_dir).expanduser()
    cases = discover_runtime_cases(root)
    case = next((item for item in cases if item.area == area), cases[0] if cases else None)
    if case is None:
        raise ValueError("no Paper58 runtime cases available")
    run_id = f"wmv11_{int(started)}_{uuid.uuid4().hex[:8]}"
    run_dir = Path(output_root).expanduser() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    paper58_result = materialize_paper58_prediction(root, case, method, run_dir)
    flus_result = run_geosos_flus(case, run_dir, flus_executable=flus_executable, console_runner=console_runner)
    start = np.asarray(np.load(case.start_path))
    observed = np.asarray(np.load(case.end_path))
    paper58 = np.asarray(np.load(paper58_result["prediction_path"]))
    flus = np.asarray(np.load(flus_result["prediction_npy_path"]))
    valid = (start != 0) & (observed != 0)
    metrics = {
        "paper58": compute_prediction_metrics(start, observed, paper58, valid),
        "geosos_flus": compute_prediction_metrics(start, observed, flus, valid),
    }
    map_payload = build_runtime_map_layers(run_dir, case, start, observed, paper58, flus)
    run = {
        "schema": "territory_world_model.paper58_geosos_flus_runtime_run.v1",
        "run_id": run_id,
        "status": "completed",
        "case": case.to_dict(),
        "paper58_method": method,
        "output_dir": str(run_dir),
        "stages": [
            {"key": "validate_inputs", "label": "输入检查", "status": "completed"},
            {"key": "paper58", "label": "Paper58 运行", "status": "completed"},
            {"key": "geosos_flus", "label": "GeoSOS-FLUS 运行", "status": "completed"},
            {"key": "metrics", "label": "指标计算", "status": "completed"},
            {"key": "layers", "label": "图层生成", "status": "completed"},
        ],
        "metrics": metrics,
        "layers": map_payload["layers"],
        "map_update": map_payload,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    _write_json(run_dir / "run_manifest.json", run)
    _write_json(run_dir / "status.json", run)
    _write_json(run_dir / "metrics.json", metrics)
    return run


def queue_runtime_map(run_dir: Path | str, username: str) -> dict[str, Any]:
    status_path = Path(run_dir) / "status.json"
    if not status_path.exists():
        return {"schema": MAP_SCHEMA, "status": "missing", "map_update_queued": False, "missing": ["status.json"]}
    run = json.loads(status_path.read_text(encoding="utf-8"))
    map_update = run.get("map_update")
    if not isinstance(map_update, dict):
        return {"schema": MAP_SCHEMA, "status": "missing", "map_update_queued": False, "missing": ["map_update"]}
    from data_agent.frontend_api import _pending_lock, pending_map_updates

    with _pending_lock:
        pending_map_updates[username] = map_update
    return {"schema": MAP_SCHEMA, "status": "queued", "run_id": run.get("run_id"), "map_update_queued": True, "map_update": map_update}
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py::test_runtime_runner_creates_completed_run_and_layers -q
```

Expected: pass.

## Task 5: Runtime Routes

**Files:**
- Modify: `data_agent/api/world_model_v11_routes.py`
- Modify: `data_agent/test_world_model_v11_routes.py`

- [ ] **Step 1: Add failing route tests**

Add tests that monkeypatch `runtime_cases_payload`, `run_runtime_once`, and `queue_runtime_map`, then assert:

```python
assert "GET" in _route_methods(route_list, "/api/twm/world-model-v11/runtime/cases")
assert "POST" in _route_methods(route_list, "/api/twm/world-model-v11/runtime/runs")
assert "GET" in _route_methods(route_list, "/api/twm/world-model-v11/runtime/runs/{run_id}")
assert "POST" in _route_methods(route_list, "/api/twm/world-model-v11/runtime/runs/{run_id}/map")
```

Add a run creation assertion:

```python
assert payload["schema"] == "territory_world_model.paper58_geosos_flus_runtime_run.v1"
assert calls == [(Path("/configured/paper58"), "xiangzhen_record_000191", "paper58_spatial_demand_ratio_claim_robustness_v4")]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest data_agent/test_world_model_v11_routes.py -q
```

Expected: fail on missing runtime routes.

- [ ] **Step 3: Implement routes**

In `data_agent/api/world_model_v11_routes.py`:

```python
from ..paper58_runtime.runner import queue_runtime_map, run_runtime_once, runtime_cases_payload
```

Add:

```python
def _configured_flus_executable() -> Path:
    return Path(os.environ.get("GEOSOS_FLUS_EXECUTABLE", "/Users/zhouning/FLUS_console_crossplatform/build/flus_console")).expanduser()


def _configured_runtime_output_root() -> Path:
    return Path(os.environ.get("TWM_WORLD_MODEL_V11_RUN_DIR", "outputs/world_model_v11_runs")).expanduser()
```

Add async endpoints:

```python
async def twm_runtime_cases(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(await asyncio.to_thread(runtime_cases_payload, _configured_paper58_benchmark_dir(), _configured_flus_executable()))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_runtime_runs(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    body = await request.json()
    try:
        payload = await asyncio.to_thread(
            run_runtime_once,
            _configured_paper58_benchmark_dir(),
            _configured_runtime_output_root(),
            str(body.get("area") or ""),
            str(body.get("method") or "paper58_spatial_demand_ratio_claim_robustness_v4"),
            _configured_flus_executable(),
        )
        return JSONResponse(payload)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
```

Register the four runtime routes in `get_world_model_v11_routes()`. For `GET /runs/{run_id}`, read `outputs/world_model_v11_runs/{run_id}/status.json`. For `POST /runs/{run_id}/map`, call `queue_runtime_map(output_root / run_id, username)`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
uv run pytest data_agent/test_world_model_v11_routes.py -q
```

Expected: pass.

## Task 6: Frontend Runtime Mode

**Files:**
- Modify: `frontend/src/components/datapanel/WorldModelV11Tab.tsx`
- Modify: `frontend/src/styles/layout.css`
- Modify: `data_agent/test_world_model_v11_frontend_contract.py`

- [ ] **Step 1: Add failing frontend contract assertions**

Add assertions:

```python
assert "/api/twm/world-model-v11/runtime/cases" in text
assert "/api/twm/world-model-v11/runtime/runs" in text
assert "/api/twm/world-model-v11/runtime/runs/" in text
assert "结果查看" in text
assert "全流程运行" in text
assert "输入检查" in text
assert "Paper58 运行" in text
assert "GeoSOS-FLUS 运行" in text
assert "指标计算" in text
assert "图层生成" in text
assert "运行并生成图层" in text
assert "GeoSOS-FLUS 可运行" in text
assert "GeoSOS-" + "PLUS" not in text
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest data_agent/test_world_model_v11_frontend_contract.py -q
```

Expected: fail because runtime mode strings and endpoints are missing.

- [ ] **Step 3: Update component**

Add TypeScript interfaces for runtime cases and runs:

```typescript
interface RuntimeCase {
  area: string;
  display_name?: string;
  start_year?: number;
  end_year?: number;
  valid_pixels?: number;
  changed_pixels?: number;
  methods?: string[];
}

interface RuntimeRun {
  schema?: string;
  run_id?: string;
  status?: string;
  case?: RuntimeCase;
  paper58_method?: string;
  output_dir?: string;
  stages?: Array<{ key?: string; label?: string; status?: string; message?: string }>;
  metrics?: Record<string, MetricValueRecord>;
  layers?: Array<{ name?: string; geojson?: string; type?: string }>;
  map_update?: unknown;
  error?: string;
}
```

Add state:

```typescript
const [viewMode, setViewMode] = useState<'results' | 'runtime'>('results');
const [runtimeCases, setRuntimeCases] = useState<RuntimeCase[]>([]);
const [runtimeRun, setRuntimeRun] = useState<RuntimeRun | null>(null);
const [selectedRuntimeArea, setSelectedRuntimeArea] = useState('');
const [selectedRuntimeMethod, setSelectedRuntimeMethod] = useState('paper58_spatial_demand_ratio_claim_robustness_v4');
const [runningRuntime, setRunningRuntime] = useState(false);
```

Add `loadRuntimeCases`, `startRuntimeRun`, and `pushRuntimeRunToMap` functions that call the new endpoints. Render a segmented control with `结果查看` and `全流程运行`. In runtime mode, render sample selector, method selector, engine availability, stage timeline, metrics table, layer list, and map button.

- [ ] **Step 4: Update CSS**

In `frontend/src/styles/layout.css`, add styles for:

```css
.v11-mode-switch { display: inline-flex; gap: 4px; padding: 4px; border: 1px solid var(--border-color); border-radius: 8px; }
.v11-stage-list { display: grid; gap: 8px; }
.v11-stage-item { display: grid; grid-template-columns: 18px 1fr auto; gap: 8px; align-items: center; }
.v11-stage-dot { width: 10px; height: 10px; border-radius: 999px; background: #9ca3af; }
.v11-stage-item.completed .v11-stage-dot { background: #16a34a; }
.v11-stage-item.error .v11-stage-dot { background: #dc2626; }
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
uv run pytest data_agent/test_world_model_v11_frontend_contract.py -q
npm run build
```

Expected: contract test passes and Vite build exits 0.

## Task 7: End-to-End and Real Smoke Verification

**Files:**
- Modify: `tests/e2e/specs/world_model_v11_paper58.spec.ts`
- Add or update: `docs/reports/world_model_v11_paper58_geosos_flus_runtime_manual_validation_2026-07-03.md`

- [ ] **Step 1: Update e2e spec**

Extend the existing spec to:

```typescript
await page.getByRole('button', { name: '全流程运行' }).click();
await expect(page.getByText('GeoSOS-FLUS 可运行')).toBeVisible();
await page.getByRole('button', { name: '运行并生成图层' }).click();
await expect(page.getByText('指标计算')).toBeVisible();
await expect(page.getByRole('button', { name: '加载运行结果到地图' })).toBeVisible({ timeout: 120000 });
await page.getByRole('button', { name: '加载运行结果到地图' }).click();
await expect(page.getByText('Paper58 预测土地利用')).toBeVisible({ timeout: 30000 });
```

- [ ] **Step 2: Run focused backend verification**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py data_agent/test_world_model_v11_routes.py data_agent/test_world_model_v11_frontend_contract.py data_agent/test_paper58_visualization.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm run build
```

Expected: build exits 0. Existing Vite chunk warnings are acceptable only if they predate this change.

- [ ] **Step 4: Run local e2e**

Start or reuse GIS Data Agent at `http://127.0.0.1:8002/`, then run:

```bash
env GIS_AGENT_E2E_URL=http://127.0.0.1:8002/ GIS_AGENT_E2E_USER=admin GIS_AGENT_E2E_PASSWORD=admin123 npx playwright test specs/world_model_v11_paper58.spec.ts --config=playwright.mmfe.config.ts --project=chromium
```

Expected: Playwright test passes and confirms runtime-generated layers appear on the map.

- [ ] **Step 5: Write manual validation report**

Create `docs/reports/world_model_v11_paper58_geosos_flus_runtime_manual_validation_2026-07-03.md` with:

```markdown
# World Model v1.1 Paper58 GeoSOS-FLUS Runtime Manual Validation

## What Was Verified

- Runtime case catalog loads from the configured Paper58 benchmark directory.
- A new Paper58 versus GeoSOS-FLUS run can be started from the `全流程运行` mode.
- The run writes a new `outputs/world_model_v11_runs/{run_id}` directory.
- The run manifest records Paper58 source artifacts and GeoSOS-FLUS console execution.
- Generated layers load onto the map with study-area georeferencing.

## Operator Steps

1. Open `http://127.0.0.1:8002/`.
2. Log in as `admin`.
3. Open `世界模型v1.1`.
4. Select `全流程运行`.
5. Select a sample area.
6. Click `运行并生成图层`.
7. Wait for all stages to complete.
8. Click `加载运行结果到地图`.
9. Confirm the map shows start, observed, Paper58 prediction, GeoSOS-FLUS prediction, error, and disagreement layers.

## Notes

The first implementation uses local Paper58 inference artifacts as the Paper58 run source and re-executes GeoSOS-FLUS through the local console.
```

## Task 8: Final Review

**Files:**
- Review all modified files.

- [ ] **Step 1: Check no PLUS terminology remains**

Run:

```bash
rg -n "GeoSOS-PLU[S]|geosos[_]plus|PLU[S] 未配置|not[_]configured" data_agent frontend/src docs/superpowers/specs/2026-07-03-paper58-geosos-full-runtime-design.md docs/superpowers/plans/2026-07-03-paper58-geosos-flus-runtime.md
```

Expected: no output.

- [ ] **Step 2: Check git diff**

Run:

```bash
git diff -- data_agent frontend/src tests/e2e docs/reports docs/superpowers/plans/2026-07-03-paper58-geosos-flus-runtime.md
```

Expected: changes are limited to the runtime implementation, tests, frontend UI, CSS, e2e, and validation docs.

- [ ] **Step 3: Final verification commands**

Run:

```bash
uv run pytest data_agent/test_paper58_runtime.py data_agent/test_world_model_v11_routes.py data_agent/test_world_model_v11_frontend_contract.py data_agent/test_paper58_visualization.py -q
npm run build
env GIS_AGENT_E2E_URL=http://127.0.0.1:8002/ GIS_AGENT_E2E_USER=admin GIS_AGENT_E2E_PASSWORD=admin123 npx playwright test specs/world_model_v11_paper58.spec.ts --config=playwright.mmfe.config.ts --project=chromium
```

Expected: pytest, build, and Playwright all exit 0.
