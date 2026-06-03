# World Model v2.1 Paper9 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new World Model v2.1 tab in GIS Data Agent that runs the latest Paper9 `arcgis-farmland-mpc` Tool 4 MPC planner through a thin backend adapter and verifies it with real Paper9 data.

**Architecture:** Keep the existing World Model and World Model v2 code paths unchanged. Add a lazy-loading backend adapter, two REST routes, and a compact DataPanel tab that calls those routes. Paper9 remains the algorithm source of truth through `D:\test\_publish\arcgis-farmland-mpc\farmland_mpc`.

**Tech Stack:** Python 3.14, Starlette routes, pytest, React 18, TypeScript, Vite, Paper9 `farmland_mpc` package, ONNX Runtime, GeoPandas/FlatGeobuf for optional map output.

---

## Source And Real-Data Baseline

- Paper9 source repo: `D:\test\_publish\arcgis-farmland-mpc`
- GitHub remote: `https://github.com/zhouning/arcgis-farmland-mpc.git`
- Remote heads checked on 2026-06-03:
  - `main`: `f339e132cd9563d2016fb0e5d4d00cdc85f8b8ba`
  - `feat/product-v1`: `8c3c9af21d31a108060c1dec2a6fe373d54425f4`
  - `feat/v12-extensible-platform`: `9b886b982af179502218ea873399d4d7a70e7ec5`
- Local Paper9 package import probe passed:
  - `farmland_mpc.__version__ == "0.2.1"`
  - `onnxruntime.__version__ == "1.25.1"`
- `uv` is not installed in this environment, so verification commands use `python -m ...`.

Real-data verification input:

```text
prepared_dir:
D:\test\_publish\arcgis-farmland-mpc\runs\restoration\buchanan_va\prepared_watershed

ensemble_dir:
D:\test\_publish\arcgis-farmland-mpc\paper\checkpoints\restoration\profiles\buchanan_va\watershed\ensemble_seed0
```

This is a public real-data Paper9 track: Buchanan VA abandoned-mine restoration planning units from OSMRE e-AMLIS, USGS NHD flowlines, USGS 3DEP slope, and Census TIGER boundary. It is not synthetic. The direct Paper9 probe already completed a full 50-step episode with `horizon=2`, `top_k=5`, `continuation=greedy`, `env_kind=restoration`, producing `D:\tmp\wm_v21_paper9_probe\mpc_summary.json`.

Spec adjustment based on the real-data check: add `env_kind` to the v2.1 request, defaulting to `county`, with `restoration` supported. Without this, the repository's public real-data track cannot run through Tool 4.

## File Structure

- Create `data_agent/world_model_v21.py`
  - Lazy Paper9 import, repo status, ONNX discovery, request validation, Tool 4 execution, summary normalization, optional map conversion.
- Create `data_agent/api/world_model_v21_routes.py`
  - `GET /api/world-model-v21/status`
  - `POST /api/world-model-v21/plan`
- Modify `data_agent/frontend_api.py`
  - Import and mount v2.1 routes next to existing v2 routes.
- Create `data_agent/test_world_model_v21.py`
  - Unit tests for status, validation, ONNX discovery, normalization, and map-warning behavior.
- Create `data_agent/test_world_model_v21_routes.py`
  - Route tests with mocked auth and mocked service.
- Create `data_agent/test_world_model_v21_realdata_smoke.py`
  - Real-data service test using Buchanan VA `prepared_watershed` and matching shipped ONNX ensemble.
- Create `frontend/src/components/datapanel/WorldModelV21Tab.tsx`
  - Operational tab with source status, planning inputs, hard constraints, results, and map update status.
- Modify `frontend/src/components/DataPanel.tsx`
  - Add `worldmodel_v21` tab key, import, tab label, and render branch.
- Modify `frontend/src/styles/layout.css`
  - Add compact `worldmodel-v21-*` layout rules for path wrapping, grid inputs, and result metrics.

## Task 1: Backend Status And Validation

**Files:**
- Create: `data_agent/world_model_v21.py`
- Test: `data_agent/test_world_model_v21.py`

- [ ] **Step 1: Write failing tests for repo status and validation**

Add these tests to `data_agent/test_world_model_v21.py`:

```python
from pathlib import Path

import pytest

from data_agent.world_model_v21 import (
    WorldModelV21Service,
    WorldModelV21ValidationError,
)


def test_status_missing_repo(tmp_path):
    svc = WorldModelV21Service(repo_path=tmp_path / "missing")
    status = svc.status()
    assert status["status"] == "unavailable"
    assert status["paper9"]["repo_exists"] is False
    assert status["paper9"]["importable"] is False


def test_onnx_discovery_accepts_standard_and_shipped_names(tmp_path):
    (tmp_path / "ensemble_member0.onnx").write_bytes(b"onnx")
    (tmp_path / "ensemble_lam5.0_member1.onnx").write_bytes(b"onnx")
    svc = WorldModelV21Service(repo_path=tmp_path)
    members = svc.find_onnx_members(tmp_path)
    assert [p.name for p in members] == [
        "ensemble_lam5.0_member1.onnx",
        "ensemble_member0.onnx",
    ]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("horizon", 0, "horizon must be between 1 and 20"),
        ("top_k", 0, "top_k must be between 1 and 500"),
        ("n_episodes", 0, "n_episodes must be between 1 and 20"),
        ("continuation", "beam", "continuation must be 'random' or 'greedy'"),
        ("scoring", "score", "scoring must be 'reward' or 'slope'"),
        ("env_kind", "other", "env_kind must be 'county' or 'restoration'"),
    ],
)
def test_validation_rejects_bad_ranges(tmp_path, field, value, message):
    prepared = tmp_path / "prepared"
    ensemble = tmp_path / "ensemble"
    prepared.mkdir()
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")
    payload = {
        "prepared_dir": str(prepared),
        "ensemble_dir": str(ensemble),
        "horizon": 5,
        "top_k": 50,
        "n_episodes": 1,
        "continuation": "random",
        "scoring": "reward",
        "env_kind": "county",
    }
    payload[field] = value

    svc = WorldModelV21Service(repo_path=tmp_path)
    with pytest.raises(WorldModelV21ValidationError, match=message):
        svc.validate_plan_request(payload)
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21.py -q
```

Expected: FAIL because `data_agent.world_model_v21` does not exist yet.

- [ ] **Step 3: Implement the service skeleton, status, ONNX discovery, and validation**

Create `data_agent/world_model_v21.py` with these public interfaces:

```python
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

VERSION = "2.1.0"
DEFAULT_REPO = Path(r"D:\test\_publish\arcgis-farmland-mpc")


class WorldModelV21Error(Exception):
    status_code = 500


class WorldModelV21ValidationError(WorldModelV21Error):
    status_code = 400


class WorldModelV21UnavailableError(WorldModelV21Error):
    status_code = 503


_instance_lock = threading.Lock()
_instance = None


def get_world_model_v21_service():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = WorldModelV21Service()
    return _instance


class WorldModelV21Service:
    def __init__(self, repo_path: str | Path | None = None):
        raw = repo_path or os.environ.get("PAPER9_FARMLAND_MPC_REPO") or DEFAULT_REPO
        self.repo_path = Path(raw)

    def status(self) -> dict[str, Any]:
        repo_exists = self.repo_path.is_dir()
        import_info = self._import_paper9() if repo_exists else {
            "importable": False,
            "package_version": None,
            "error": "Paper9 repository not found",
        }
        defaults = {
            "prepared_dir": os.environ.get("PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR", ""),
            "ensemble_dir": os.environ.get("PAPER9_FARMLAND_MPC_DEFAULT_ENSEMBLE_DIR", ""),
            "out_dir_policy": "per-user timestamped uploads directory",
        }
        onnx_count = 0
        if defaults["ensemble_dir"]:
            onnx_count = len(self.find_onnx_members(defaults["ensemble_dir"]))
        ready = repo_exists and import_info["importable"]
        return {
            "status": "ready" if ready else "unavailable",
            "version": VERSION,
            "paper9": {
                "repo_path": str(self.repo_path),
                "repo_exists": repo_exists,
                "remote": self._git(["config", "--get", "remote.origin.url"]),
                "commit": self._git(["rev-parse", "HEAD"]),
                "commit_date": self._git(["show", "-s", "--format=%ci", "HEAD"]),
                **import_info,
            },
            "defaults": defaults,
            "capabilities": {
                "tool4_plan": ready,
                "prepare_sample_train": False,
                "onnx_inference": ready,
                "county_env": True,
                "restoration_env": True,
                "cultivated_area_floor": True,
                "baimu_area_floor": True,
            },
            "onnx_member_count": onnx_count,
        }

    def find_onnx_members(self, ensemble_dir: str | Path) -> list[Path]:
        root = Path(ensemble_dir)
        if not root.is_dir():
            return []
        members = sorted(root.glob("*.onnx"), key=lambda p: p.name)
        return [p for p in members if "member" in p.stem]

    def validate_plan_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        prepared_dir = Path(str(payload.get("prepared_dir", "")).strip())
        ensemble_dir = Path(str(payload.get("ensemble_dir", "")).strip())
        if not prepared_dir.is_dir():
            raise WorldModelV21ValidationError(f"prepared_dir not found: {prepared_dir}")
        if not ensemble_dir.is_dir():
            raise WorldModelV21ValidationError(f"ensemble_dir not found: {ensemble_dir}")
        members = self.find_onnx_members(ensemble_dir)
        if not members:
            raise WorldModelV21ValidationError(f"No ONNX ensemble members found under {ensemble_dir}")

        horizon = self._int_range(payload, "horizon", 5, 1, 20)
        top_k = self._int_range(payload, "top_k", 50, 1, 500)
        n_episodes = self._int_range(payload, "n_episodes", 1, 1, 20)
        continuation = str(payload.get("continuation", "random")).strip().lower()
        if continuation not in {"random", "greedy"}:
            raise WorldModelV21ValidationError("continuation must be 'random' or 'greedy'")
        scoring = str(payload.get("scoring", "reward")).strip().lower()
        if scoring == "slope_only":
            scoring = "slope"
        if scoring not in {"reward", "slope"}:
            raise WorldModelV21ValidationError("scoring must be 'reward' or 'slope'")
        env_kind = str(payload.get("env_kind", "county")).strip().lower()
        if env_kind not in {"county", "restoration"}:
            raise WorldModelV21ValidationError("env_kind must be 'county' or 'restoration'")

        return {
            "prepared_dir": prepared_dir,
            "ensemble_dir": ensemble_dir,
            "onnx_members": members,
            "horizon": horizon,
            "top_k": top_k,
            "n_episodes": n_episodes,
            "continuation": continuation,
            "scoring": scoring,
            "env_kind": env_kind,
            "threads": self._int_range(payload, "threads", 0, 0, 64),
            "proj_crs": payload.get("proj_crs") or None,
            "seed_offset": self._int_range(payload, "seed_offset", 0, 0, 1000000),
            "cultivated_area_floor_delta_ha": self._optional_float(payload, "cultivated_area_floor_delta_ha"),
            "baimu_area_floor_delta_ha": self._optional_float(payload, "baimu_area_floor_delta_ha"),
            "gamma_conn": self._optional_float(payload, "gamma_conn"),
            "delta_conn": self._optional_float(payload, "delta_conn"),
        }
```

Include private helpers `_import_paper9`, `_git`, `_int_range`, and `_optional_float` in the same file. `_import_paper9` must insert `self.repo_path` into `sys.path` only if absent, import `farmland_mpc`, and return `{"importable": True, "package_version": farmland_mpc.__version__, "error": None}`.

- [ ] **Step 4: Run backend validation tests**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21.py -q
```

Expected: PASS for the status, discovery, and validation tests.

- [ ] **Step 5: Commit Task 1**

```powershell
git add data_agent/world_model_v21.py data_agent/test_world_model_v21.py
git commit -m "feat: add world model v2.1 service status"
```

## Task 2: Tool 4 Plan Execution And Summary Normalization

**Files:**
- Modify: `data_agent/world_model_v21.py`
- Modify: `data_agent/test_world_model_v21.py`

- [ ] **Step 1: Write failing tests for mocked planning and summary normalization**

Append these tests:

```python
def test_run_plan_calls_paper9_with_expected_args(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared"
    ensemble = tmp_path / "ensemble"
    prepared.mkdir()
    ensemble.mkdir()
    (ensemble / "ensemble_member0.onnx").write_bytes(b"onnx")
    calls = {}

    def fake_run(**kwargs):
        calls.update(kwargs)
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "config": {"n_blocks": 562, "n_parcels": 562, "max_steps": 50},
            "ensemble": {"n_members": 1, "paths": ["ensemble_member0.onnx"]},
            "results": [{"episode": 0, "total_reward": 12.5, "steps_run": 50}],
            "aggregate": {"slope_pct_mean": 0.0, "cont_mean": 0.0, "baimu_ha_mean": 0.0},
        }
        (out_dir / "mpc_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return summary

    svc = WorldModelV21Service(repo_path=tmp_path)
    monkeypatch.setattr(svc, "_load_paper9_plan_run", lambda: fake_run)
    result = svc.run_plan(
        {
            "prepared_dir": str(prepared),
            "ensemble_dir": str(ensemble),
            "horizon": 2,
            "top_k": 5,
            "n_episodes": 1,
            "continuation": "greedy",
            "scoring": "reward",
            "env_kind": "restoration",
        },
        user_id="pytest",
    )

    assert calls["prepared_dir"] == str(prepared)
    assert calls["ensemble_dir"] == str(ensemble)
    assert calls["env_kind"] == "restoration"
    assert calls["horizon"] == 2
    assert calls["top_k"] == 5
    assert result["status"] == "ok"
    assert result["summary"]["total_reward"] == 12.5
    assert result["summary"]["steps_run"] == 50


def test_map_conversion_failure_is_warning(tmp_path, monkeypatch):
    svc = WorldModelV21Service(repo_path=tmp_path)
    bad_shp = tmp_path / "missing.shp"
    warnings = []
    assert svc._convert_optimized_shp_to_fgb(bad_shp, tmp_path, warnings) is None
    assert warnings and "optimized shapefile not found" in warnings[0]
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21.py -q
```

Expected: FAIL because `run_plan`, `_load_paper9_plan_run`, and `_convert_optimized_shp_to_fgb` are not implemented.

- [ ] **Step 3: Implement planning, output directory creation, normalization, and optional map conversion**

Add these service methods:

```python
    def run_plan(self, payload: dict[str, Any], user_id: str) -> dict[str, Any]:
        cfg = self.validate_plan_request(payload)
        plan_run = self._load_paper9_plan_run()
        out_dir = self._new_output_dir(user_id)
        output_fc = out_dir / "optimized_dltb.shp"
        input_dltb_fc = cfg["prepared_dir"] / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"
        output_fc_arg = str(output_fc) if cfg["env_kind"] == "county" and input_dltb_fc.exists() else None

        try:
            summary = plan_run(
                ensemble_dir=str(cfg["ensemble_dir"]),
                out_dir=str(out_dir),
                horizon=cfg["horizon"],
                top_k=cfg["top_k"],
                n_episodes=cfg["n_episodes"],
                continuation=cfg["continuation"],
                scoring=cfg["scoring"],
                threads=cfg["threads"],
                seed_offset=cfg["seed_offset"],
                prepared_dir=str(cfg["prepared_dir"]),
                proj_crs=cfg["proj_crs"],
                env_kind=cfg["env_kind"],
                output_fc=output_fc_arg,
                input_dltb_fc=str(input_dltb_fc) if output_fc_arg else None,
                cultivated_area_floor_delta_ha=cfg["cultivated_area_floor_delta_ha"],
                baimu_area_floor_delta_ha=cfg["baimu_area_floor_delta_ha"],
                gamma_conn=cfg["gamma_conn"],
                delta_conn=cfg["delta_conn"],
            )
        except WorldModelV21Error:
            raise
        except Exception as exc:
            raise WorldModelV21UnavailableError(str(exc)) from exc

        warnings: list[str] = []
        map_layer = None
        if output_fc_arg:
            map_layer = self._convert_optimized_shp_to_fgb(output_fc, out_dir, warnings)

        normalized = self._normalize_summary(summary)
        artifacts = {
            "summary_json": "mpc_summary.json" if (out_dir / "mpc_summary.json").exists() else None,
            "land_use_npy": "mpc_land_use.npy" if (out_dir / "mpc_land_use.npy").exists() else None,
            "optimized_shp": output_fc.name if output_fc.exists() else None,
            "map_layer": map_layer.name if map_layer else None,
        }
        return {
            "status": "ok",
            "version": VERSION,
            "source": "arcgis-farmland-mpc",
            "mode": "tool4_mpc",
            "env_kind": cfg["env_kind"],
            "prepared_dir": str(cfg["prepared_dir"]),
            "ensemble_dir": str(cfg["ensemble_dir"]),
            "out_dir": str(out_dir),
            "summary": normalized,
            "artifacts": artifacts,
            "map_config": self._build_map_config(map_layer) if map_layer else None,
            "map_update_queued": False,
            "warnings": warnings,
        }

    def _load_paper9_plan_run(self):
        info = self._import_paper9()
        if not info["importable"]:
            raise WorldModelV21UnavailableError(info["error"] or "Paper9 import failed")
        from farmland_mpc.mpc_plan import run
        return run

    def _normalize_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        results = summary.get("results") or []
        first = results[0] if results else {}
        aggregate = summary.get("aggregate") or {}
        config = summary.get("config") or {}
        return {
            "total_reward": first.get("total_reward"),
            "steps_run": first.get("steps_run"),
            "swaps_completed": first.get("swaps_completed"),
            "n_selected": first.get("n_selected"),
            "budget_used": first.get("budget_used"),
            "budget_fraction_used": first.get("budget_fraction_used"),
            "slope_change_pct": first.get("slope_change_pct", aggregate.get("slope_pct_mean")),
            "cont_change": first.get("cont_change", aggregate.get("cont_mean")),
            "baimu_area_change_ha": first.get("baimu_area_change_ha", aggregate.get("baimu_ha_mean")),
            "n_episodes": config.get("n_episodes"),
            "n_blocks": config.get("n_blocks"),
            "n_parcels": config.get("n_parcels"),
            "max_steps": config.get("max_steps"),
            "ensemble_members": (summary.get("ensemble") or {}).get("n_members"),
        }
```

Implement `_new_output_dir`, `_convert_optimized_shp_to_fgb`, and `_build_map_config` in the same file. `_new_output_dir` must create `data_agent/uploads/<user_id>/world_model_v21/<YYYYmmdd_HHMMSS_microseconds>`. `_convert_optimized_shp_to_fgb` must append a warning and return `None` when the shapefile is absent or GeoPandas raises.

- [ ] **Step 4: Run service tests**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add data_agent/world_model_v21.py data_agent/test_world_model_v21.py
git commit -m "feat: run paper9 world model v2.1 planning"
```

## Task 3: REST Routes And Frontend API Mounting

**Files:**
- Create: `data_agent/api/world_model_v21_routes.py`
- Modify: `data_agent/frontend_api.py`
- Test: `data_agent/test_world_model_v21_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `data_agent/test_world_model_v21_routes.py`:

```python
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from data_agent.api import world_model_v21_routes as routes


class FakeService:
    def status(self):
        return {"status": "ready", "version": "2.1.0"}

    def run_plan(self, body, user_id):
        return {
            "status": "ok",
            "version": "2.1.0",
            "summary": {"total_reward": 1.0},
            "map_config": {"layers": []},
        }


def fake_request(method="GET", body=b"{}"):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": method, "path": "/", "headers": []}, receive)


@pytest.mark.asyncio
async def test_status_requires_auth(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    resp = await routes.wm_v21_status(fake_request())
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_status_returns_service_payload(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "get_world_model_v21_service", lambda: FakeService())
    resp = await routes.wm_v21_status(fake_request())
    assert resp.status_code == 200
    assert b'"ready"' in resp.body


@pytest.mark.asyncio
async def test_plan_queues_map_update(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "get_world_model_v21_service", lambda: FakeService())
    pending = {}
    monkeypatch.setattr(routes, "_queue_map_update", lambda uid, cfg: pending.setdefault(uid, cfg))
    resp = await routes.wm_v21_plan(fake_request("POST", b'{"prepared_dir":"x","ensemble_dir":"y"}'))
    assert resp.status_code == 200
    assert pending["alice"] == {"layers": []}
```

- [ ] **Step 2: Run route tests and confirm failure**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21_routes.py -q
```

Expected: FAIL because route module does not exist.

- [ ] **Step 3: Implement route module**

Create `data_agent/api/world_model_v21_routes.py`:

```python
import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..world_model_v21 import (
    WorldModelV21Error,
    WorldModelV21UnavailableError,
    get_world_model_v21_service,
)


async def wm_v21_status(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(get_world_model_v21_service().status())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def wm_v21_plan(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        svc = get_world_model_v21_service()
        result = await asyncio.to_thread(svc.run_plan, body, username)
        map_config = result.pop("map_config", None)
        if map_config:
            _queue_map_update(username, map_config)
            result["map_update_queued"] = True
        return JSONResponse(result)
    except WorldModelV21UnavailableError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except WorldModelV21Error as exc:
        return JSONResponse({"error": str(exc)}, status_code=getattr(exc, "status_code", 400))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def _queue_map_update(user_id: str, map_config: dict):
    from ..frontend_api import pending_map_updates, _pending_lock
    with _pending_lock:
        pending_map_updates[user_id] = map_config


def get_world_model_v21_routes() -> list:
    return [
        Route("/api/world-model-v21/status", wm_v21_status, methods=["GET"]),
        Route("/api/world-model-v21/plan", wm_v21_plan, methods=["POST"]),
    ]
```

- [ ] **Step 4: Mount v2.1 routes**

Modify `data_agent/frontend_api.py`:

```python
from .api.world_model_v21_routes import get_world_model_v21_routes
```

Add the spread immediately after `*get_world_model_v2_routes(),`:

```python
        # World Model v2.1 (Paper9 arcgis-farmland-mpc Tool 4)
        *get_world_model_v21_routes(),
```

- [ ] **Step 5: Run route tests**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21_routes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add data_agent/api/world_model_v21_routes.py data_agent/frontend_api.py data_agent/test_world_model_v21_routes.py
git commit -m "feat: expose world model v2.1 API routes"
```

## Task 4: Frontend Tab And DataPanel Wiring

**Files:**
- Create: `frontend/src/components/datapanel/WorldModelV21Tab.tsx`
- Modify: `frontend/src/components/DataPanel.tsx`
- Modify: `frontend/src/styles/layout.css`

- [ ] **Step 1: Create the v2.1 tab component**

Create `WorldModelV21Tab.tsx` with these key types and defaults:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { Play, RefreshCw } from 'lucide-react';

type EnvKind = 'county' | 'restoration';
type Continuation = 'random' | 'greedy';
type Scoring = 'reward' | 'slope';

interface V21Status {
  status: 'ready' | 'unavailable';
  version: string;
  paper9: {
    repo_path: string;
    repo_exists: boolean;
    remote?: string | null;
    commit?: string | null;
    commit_date?: string | null;
    package_version?: string | null;
    importable: boolean;
    error?: string | null;
  };
  defaults: {
    prepared_dir: string;
    ensemble_dir: string;
  };
  capabilities: Record<string, boolean>;
  onnx_member_count?: number;
}

interface V21Result {
  status: string;
  version: string;
  source: string;
  mode: string;
  env_kind: EnvKind;
  prepared_dir: string;
  ensemble_dir: string;
  out_dir: string;
  summary: Record<string, number | string | null | undefined>;
  artifacts: Record<string, string | null>;
  map_update_queued: boolean;
  warnings?: string[];
}

const DEFAULT_FORM = {
  prepared_dir: '',
  ensemble_dir: '',
  env_kind: 'county' as EnvKind,
  horizon: 5,
  top_k: 50,
  n_episodes: 1,
  continuation: 'random' as Continuation,
  scoring: 'reward' as Scoring,
  threads: 0,
  seed_offset: 0,
  proj_crs: '',
  cultivated_area_floor_delta_ha: '',
  baimu_area_floor_delta_ha: '',
  gamma_conn: '',
  delta_conn: '',
};
```

The component must:

- fetch `/api/world-model-v21/status` on mount;
- prefill `prepared_dir` and `ensemble_dir` from status defaults when provided;
- expose `env_kind` so real-data `restoration` runs are possible;
- serialize blank optional numeric fields as `null`;
- call `/api/world-model-v21/plan`;
- after a successful run, fetch `/api/map/pending` and call `window.__handleMapUpdate` when present;
- render warnings without blocking successful results.

- [ ] **Step 2: Add DataPanel wiring**

Modify imports:

```tsx
import WorldModelV21Tab from './datapanel/WorldModelV21Tab';
```

Add `worldmodel_v21` to `TabKey`:

```tsx
| 'worldmodel_v21'
```

Add tab after `worldmodel_v2`:

```tsx
{ key: 'worldmodel_v21', label: '世界模型v2.1', icon: <Globe size={ICON_SIZE} /> },
```

Add render branch after v2:

```tsx
{activeTab === 'worldmodel_v21' && <WorldModelV21Tab />}
```

- [ ] **Step 3: Add compact styles**

Append these rules to `frontend/src/styles/layout.css`:

```css
.worldmodel-v21-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.worldmodel-v21-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.worldmodel-v21-path {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-secondary);
  word-break: break-all;
  line-height: 1.45;
}

.worldmodel-v21-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.worldmodel-v21-grid .config-row {
  min-width: 0;
}

.worldmodel-v21-grid input,
.worldmodel-v21-grid select {
  width: 100%;
}

.worldmodel-v21-results-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  font-size: 12px;
}

.worldmodel-v21-metric {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 6px 8px;
  min-width: 0;
}

.worldmodel-v21-metric span {
  display: block;
  color: var(--text-secondary);
  font-size: 10.5px;
  margin-bottom: 2px;
}

.worldmodel-v21-metric strong {
  display: block;
  color: var(--text);
  overflow-wrap: anywhere;
}
```

- [ ] **Step 4: Build frontend**

Run:

```powershell
cd frontend
npm run build
```

Expected: PASS; TypeScript and Vite build complete without errors.

- [ ] **Step 5: Commit Task 4**

```powershell
git add frontend/src/components/datapanel/WorldModelV21Tab.tsx frontend/src/components/DataPanel.tsx frontend/src/styles/layout.css
git commit -m "feat: add world model v2.1 tab"
```

## Task 5: Real-Data Service Smoke Test

**Files:**
- Create: `data_agent/test_world_model_v21_realdata_smoke.py`

- [ ] **Step 1: Write the real-data smoke test**

Create `data_agent/test_world_model_v21_realdata_smoke.py`:

```python
from pathlib import Path

import pytest

from data_agent.world_model_v21 import WorldModelV21Service


REPO = Path(r"D:\test\_publish\arcgis-farmland-mpc")
PREPARED = REPO / "runs" / "restoration" / "buchanan_va" / "prepared_watershed"
ENSEMBLE = (
    REPO
    / "paper"
    / "checkpoints"
    / "restoration"
    / "profiles"
    / "buchanan_va"
    / "watershed"
    / "ensemble_seed0"
)


def test_world_model_v21_runs_real_buchanan_va_data_end_to_end():
    if not PREPARED.is_dir() or not ENSEMBLE.is_dir():
        pytest.skip("Paper9 Buchanan VA real-data fixture is not present on this machine")

    svc = WorldModelV21Service(repo_path=REPO)
    result = svc.run_plan(
        {
            "prepared_dir": str(PREPARED),
            "ensemble_dir": str(ENSEMBLE),
            "env_kind": "restoration",
            "horizon": 2,
            "top_k": 5,
            "n_episodes": 1,
            "continuation": "greedy",
            "scoring": "reward",
            "threads": 0,
        },
        user_id="pytest_realdata",
    )

    assert result["status"] == "ok"
    assert result["env_kind"] == "restoration"
    assert result["summary"]["n_blocks"] == 562
    assert result["summary"]["max_steps"] == 50
    assert result["summary"]["steps_run"] == 50
    assert result["summary"]["n_selected"] == 50
    assert result["summary"]["total_reward"] > 0
    assert (Path(result["out_dir"]) / "mpc_summary.json").exists()
    assert (Path(result["out_dir"]) / "mpc_land_use.npy").exists()
```

- [ ] **Step 2: Run the real-data smoke test**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21_realdata_smoke.py -q -s
```

Expected: PASS locally. The run should take about 40-60 seconds on this machine and complete all 50 restoration-planning steps.

- [ ] **Step 3: Commit Task 5**

```powershell
git add data_agent/test_world_model_v21_realdata_smoke.py
git commit -m "test: add world model v2.1 real data smoke"
```

## Task 6: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run scoped backend tests**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21.py data_agent/test_world_model_v21_routes.py -q
```

Expected: PASS.

- [ ] **Step 2: Run real-data end-to-end test**

Run:

```powershell
python -m pytest data_agent/test_world_model_v21_realdata_smoke.py -q -s
```

Expected: PASS; output includes Paper9 MPC log lines, `n_blocks=562`, `steps_run=50`, and positive `total_reward`.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 4: Check git diff scope**

Run:

```powershell
git status --short
git diff -- data_agent/world_model_v21.py data_agent/api/world_model_v21_routes.py data_agent/frontend_api.py data_agent/test_world_model_v21.py data_agent/test_world_model_v21_routes.py data_agent/test_world_model_v21_realdata_smoke.py frontend/src/components/datapanel/WorldModelV21Tab.tsx frontend/src/components/DataPanel.tsx frontend/src/styles/layout.css
```

Expected: only World Model v2.1 files and intended wiring changed.

- [ ] **Step 5: Final commit**

```powershell
git add data_agent/world_model_v21.py data_agent/api/world_model_v21_routes.py data_agent/frontend_api.py data_agent/test_world_model_v21.py data_agent/test_world_model_v21_routes.py data_agent/test_world_model_v21_realdata_smoke.py frontend/src/components/datapanel/WorldModelV21Tab.tsx frontend/src/components/DataPanel.tsx frontend/src/styles/layout.css
git commit -m "feat: integrate paper9 world model v2.1"
```

## Self-Review

- Spec coverage: The plan implements a new v2.1 tab, keeps v2 untouched, adds status and plan routes, lazily imports Paper9, runs Tool 4, normalizes summaries, queues map updates when spatial output exists, and verifies against real Paper9 data.
- Real-data coverage: The plan uses Buchanan VA `prepared_watershed` and matching shipped ONNX ensemble. This is the public real-data track in the Paper9 repository. Bishan raw cadastral prepared data is not present in this checkout, and the service still supports county-mode Bishan runs when a matching private `prepared_dir` is supplied.
- Placeholder scan: No task uses open-ended placeholders; every command and expected result is concrete.
- Type consistency: Request fields are `prepared_dir`, `ensemble_dir`, `env_kind`, `horizon`, `top_k`, `n_episodes`, `continuation`, `scoring`, `threads`, `seed_offset`, `proj_crs`, `cultivated_area_floor_delta_ha`, `baimu_area_floor_delta_ha`, `gamma_conn`, and `delta_conn` across service, API, frontend, and tests.
