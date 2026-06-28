# World Model v1.1 Paper58 Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent `世界模型 v1.1` DataPanel tab that displays server-configured Paper58 external benchmark evidence against GeoSOS-FLUS without making Paper58, AlphaEarth, or GeoFM a TWM runtime dependency.

**Architecture:** Add a small authenticated backend API that reads `TWM_PAPER58_BENCHMARK_DIR` and returns the existing `paper58_external_benchmark` evidence schema. Add a compact React DataPanel tab that calls that API, renders status/metrics/boundary diagnostics, and exposes a refresh button that only re-reads local sanitized artifacts.

**Tech Stack:** Python standard library, Starlette routes, existing TWM validation-bundle Paper58 helper, pytest, React 18, TypeScript, existing DataPanel CSS conventions, lucide-react icons.

---

## File Map

- Create `data_agent/api/world_model_v11_routes.py`
  - Authenticated `GET /api/twm/paper58-benchmark`
  - Authenticated `POST /api/twm/paper58-benchmark/refresh`
  - Reads only `TWM_PAPER58_BENCHMARK_DIR`
  - Reuses `build_paper58_external_benchmark(...)`
- Modify `data_agent/frontend_api.py`
  - Mounts `get_world_model_v11_routes()`
- Create `data_agent/test_world_model_v11_routes.py`
  - Backend route tests for auth, configured path, missing config, refresh, and no frontend path body
- Create `data_agent/test_world_model_v11_frontend_contract.py`
  - Static frontend contract tests because this project has no frontend test runner
- Create `frontend/src/components/datapanel/WorldModelV11Tab.tsx`
  - Evidence dashboard UI and refresh action
- Modify `frontend/src/components/DataPanel.tsx`
  - Registers `worldmodel_v11` tab and renders `WorldModelV11Tab`

No core TWM model, planner, state builder, SCCA, production-readiness, or runtime generator modules should be edited.

---

### Task 1: Backend Paper58 Evidence API

**Files:**
- Create: `data_agent/test_world_model_v11_routes.py`
- Create: `data_agent/api/world_model_v11_routes.py`
- Modify: `data_agent/frontend_api.py`

- [ ] **Step 1: Write failing backend route tests**

Create `data_agent/test_world_model_v11_routes.py`:

```python
import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from data_agent.api import world_model_v11_routes as routes


def fake_request(method="GET", body=b"{}"):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": method, "path": "/", "headers": []},
        receive,
    )


def fake_summary(path):
    return {
        "schema": "territory_world_model.paper58_external_benchmark.v1",
        "status": "supporting_evidence" if path else "missing",
        "provided": bool(path),
        "claim_scope": "external_benchmark_support_only",
        "runtime_dependency": "none",
        "geofm_runtime_allowed": False,
        "twm_generator_role": "not_a_runtime_generator",
        "primary_twm_route": "twm_native_generation_and_planning",
        "blocks_validation": False,
        "can_promote_claim_ladder": False,
        "metric_summary": {
            "best_paper58_method": "paper58_semantic_keep_loo_selector",
            "baseline_method": "geosos_flus_console",
            "paper58_vs_baseline_wins": 4,
            "area_count": 43,
        },
        "source_files": {"paper58_benchmark_dir": str(path)} if path else {},
        "missing": [] if path else ["paper58_benchmark_dir_not_provided"],
        "claim_boundary": "Paper58 is external benchmark support only.",
    }


def test_world_model_v11_status_requires_auth(monkeypatch):
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)

    resp = asyncio.run(routes.paper58_benchmark_status(fake_request()))

    assert resp.status_code == 401


def test_world_model_v11_status_uses_server_configured_dir(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    calls = []
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setenv("TWM_PAPER58_BENCHMARK_DIR", "/safe/paper58")
    monkeypatch.setattr(
        routes,
        "build_paper58_external_benchmark",
        lambda path: calls.append(str(path)) or fake_summary(path),
    )

    resp = asyncio.run(routes.paper58_benchmark_status(fake_request()))
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert calls == ["/safe/paper58"]
    assert payload["status"] == "supporting_evidence"
    assert payload["claim_scope"] == "external_benchmark_support_only"
    assert payload["runtime_dependency"] == "none"
    assert payload["geofm_runtime_allowed"] is False
    assert payload["can_promote_claim_ladder"] is False


def test_world_model_v11_missing_config_is_non_blocking(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.delenv("TWM_PAPER58_BENCHMARK_DIR", raising=False)
    monkeypatch.setattr(routes, "build_paper58_external_benchmark", fake_summary)

    resp = asyncio.run(routes.paper58_benchmark_status(fake_request()))
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert payload["status"] == "missing"
    assert payload["blocks_validation"] is False
    assert payload["can_promote_claim_ladder"] is False


def test_world_model_v11_refresh_does_not_accept_frontend_path(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    calls = []
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setenv("TWM_PAPER58_BENCHMARK_DIR", "/configured/paper58")
    monkeypatch.setattr(
        routes,
        "build_paper58_external_benchmark",
        lambda path: calls.append(str(path)) or fake_summary(path),
    )

    resp = asyncio.run(
        routes.paper58_benchmark_refresh(
            fake_request("POST", b'{"paper58_benchmark_dir":"/unsafe/user/path"}')
        )
    )
    payload = json.loads(resp.body)

    assert resp.status_code == 200
    assert calls == ["/configured/paper58"]
    assert payload["source_files"]["paper58_benchmark_dir"] == "/configured/paper58"


def test_world_model_v11_routes_are_registered():
    route_paths = {route.path for route in routes.get_world_model_v11_routes()}

    assert "/api/twm/paper58-benchmark" in route_paths
    assert "/api/twm/paper58-benchmark/refresh" in route_paths
```

- [ ] **Step 2: Run backend tests and verify they fail**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_world_model_v11_routes.py
```

Expected: FAIL because `data_agent.api.world_model_v11_routes` does not exist.

- [ ] **Step 3: Add the backend routes**

Create `data_agent/api/world_model_v11_routes.py`:

```python
"""World Model v1.1 Paper58 benchmark evidence routes."""

import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from scripts.run_twm_validation_bundle import build_paper58_external_benchmark


def _configured_paper58_benchmark_dir() -> Path | None:
    configured = os.environ.get("TWM_PAPER58_BENCHMARK_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


async def _paper58_benchmark_response(request: Request) -> JSONResponse:
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        summary = build_paper58_external_benchmark(_configured_paper58_benchmark_dir())
        return JSONResponse(summary)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def paper58_benchmark_status(request: Request) -> JSONResponse:
    """GET /api/twm/paper58-benchmark"""
    return await _paper58_benchmark_response(request)


async def paper58_benchmark_refresh(request: Request) -> JSONResponse:
    """POST /api/twm/paper58-benchmark/refresh"""
    return await _paper58_benchmark_response(request)


def get_world_model_v11_routes() -> list[Route]:
    """Return Route objects for World Model v1.1 Paper58 benchmark evidence."""
    return [
        Route("/api/twm/paper58-benchmark", paper58_benchmark_status, methods=["GET"]),
        Route("/api/twm/paper58-benchmark/refresh", paper58_benchmark_refresh, methods=["POST"]),
    ]
```

- [ ] **Step 4: Mount the backend routes**

In `data_agent/frontend_api.py`, add this import inside `get_frontend_api_routes()` near the other world-model route imports:

```python
    from .api.world_model_v11_routes import get_world_model_v11_routes
```

Add this route spread before the World Model v2 routes:

```python
        # World Model v1.1 (Paper58 external benchmark evidence)
        *get_world_model_v11_routes(),
```

- [ ] **Step 5: Run backend tests and verify they pass**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_world_model_v11_routes.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add data_agent/test_world_model_v11_routes.py data_agent/api/world_model_v11_routes.py data_agent/frontend_api.py
git commit -m "feat: add World Model v1.1 Paper58 evidence API"
```

---

### Task 2: DataPanel Tab Registration Contract

**Files:**
- Create: `data_agent/test_world_model_v11_frontend_contract.py`
- Modify: `frontend/src/components/DataPanel.tsx`
- Create: `frontend/src/components/datapanel/WorldModelV11Tab.tsx`

- [ ] **Step 1: Write failing frontend registration contract test**

Create `data_agent/test_world_model_v11_frontend_contract.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PANEL = ROOT / "frontend" / "src" / "components" / "DataPanel.tsx"
WORLD_MODEL_V11_TAB = ROOT / "frontend" / "src" / "components" / "datapanel" / "WorldModelV11Tab.tsx"


def test_world_model_v11_tab_is_registered_in_datapanel():
    text = DATA_PANEL.read_text(encoding="utf-8")

    assert "WorldModelV11Tab" in text
    assert "worldmodel_v11" in text
    assert "世界模型v1.1" in text
    assert "{activeTab === 'worldmodel_v11' && <WorldModelV11Tab />}" in text


def test_world_model_v11_tab_file_contains_boundary_contract():
    text = WORLD_MODEL_V11_TAB.read_text(encoding="utf-8")

    assert "/api/twm/paper58-benchmark" in text
    assert "/api/twm/paper58-benchmark/refresh" in text
    assert "Paper58 is external benchmark support only" in text
    assert "runtime_dependency=none" in text
    assert "geofm_runtime_allowed=false" in text
    assert "not_a_runtime_generator" in text
    assert "刷新证据" in text
```

- [ ] **Step 2: Run the frontend contract test and verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_world_model_v11_frontend_contract.py
```

Expected: FAIL because `WorldModelV11Tab.tsx` and the DataPanel registration do not exist.

- [ ] **Step 3: Add a minimal WorldModelV11Tab stub**

Create `frontend/src/components/datapanel/WorldModelV11Tab.tsx`:

```tsx
import { RefreshCw } from 'lucide-react';

export default function WorldModelV11Tab() {
  return (
    <div className="datapanel-section">
      <div className="datapanel-section-header">
        <div>
          <h3>世界模型 v1.1</h3>
          <p>Paper58 is external benchmark support only.</p>
        </div>
        <button className="secondary-button" type="button">
          <RefreshCw size={14} />
          刷新证据
        </button>
      </div>
      <div className="datapanel-card">
        <p>runtime_dependency=none</p>
        <p>geofm_runtime_allowed=false</p>
        <p>not_a_runtime_generator</p>
        <p>/api/twm/paper58-benchmark</p>
        <p>/api/twm/paper58-benchmark/refresh</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Register the tab in DataPanel**

In `frontend/src/components/DataPanel.tsx`:

Add import:

```tsx
import WorldModelV11Tab from './datapanel/WorldModelV11Tab';
```

Add `worldmodel_v11` to `TabKey`:

```tsx
| 'worldmodel_v11'
```

Add the tab next to the existing world model tabs:

```tsx
{ key: 'worldmodel_v11', label: '世界模型v1.1', icon: <Globe size={ICON_SIZE} /> },
```

Add render block next to `worldmodel_v21`:

```tsx
{activeTab === 'worldmodel_v11' && <WorldModelV11Tab />}
```

- [ ] **Step 5: Run frontend contract test and verify it passes**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_world_model_v11_frontend_contract.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add data_agent/test_world_model_v11_frontend_contract.py frontend/src/components/DataPanel.tsx frontend/src/components/datapanel/WorldModelV11Tab.tsx
git commit -m "feat: register World Model v1.1 tab"
```

---

### Task 3: WorldModelV11Tab Evidence Dashboard

**Files:**
- Modify: `data_agent/test_world_model_v11_frontend_contract.py`
- Modify: `frontend/src/components/datapanel/WorldModelV11Tab.tsx`

- [ ] **Step 1: Extend the frontend contract test for dashboard behavior**

Append to `test_world_model_v11_tab_file_contains_boundary_contract()`:

```python
    assert "statusBadgeClass" in text
    assert "loadEvidence" in text
    assert "refreshEvidence" in text
    assert "metric_summary" in text
    assert "mean_change_f1" in text
    assert "mean_fom" in text
    assert "mean_transition_accuracy" in text
    assert "mean_allocation_disagreement" in text
    assert "source_files" in text
    assert "read_errors" in text
```

- [ ] **Step 2: Run the frontend contract test and verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_world_model_v11_frontend_contract.py::test_world_model_v11_tab_file_contains_boundary_contract
```

Expected: FAIL because the tab is still a static stub.

- [ ] **Step 3: Replace the stub with the evidence dashboard**

Replace `frontend/src/components/datapanel/WorldModelV11Tab.tsx` with:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, RefreshCw, ShieldCheck } from 'lucide-react';

interface Paper58Evidence {
  schema?: string;
  status?: 'missing' | 'supporting_evidence' | 'review' | 'blocked' | string;
  provided?: boolean;
  missing?: string[];
  read_errors?: Array<{ path?: string; error?: string }>;
  source_files?: Record<string, string | null | undefined>;
  metric_summary?: {
    best_paper58_method?: string | null;
    baseline_method?: string | null;
    area_count?: number | null;
    paper58_vs_baseline_wins?: number | null;
    deltas?: Record<string, number | null | undefined>;
  };
  manifest_summary?: Record<string, unknown>;
  claim_scope?: string;
  runtime_dependency?: string;
  geofm_runtime_allowed?: boolean;
  twm_generator_role?: string;
  primary_twm_route?: string;
  blocks_validation?: boolean;
  can_promote_claim_ladder?: boolean;
  claim_boundary?: string;
  error?: string;
}

const metricLabels: Record<string, string> = {
  mean_change_f1: 'Change F1',
  mean_fom: 'FoM',
  mean_transition_accuracy: 'Transition accuracy',
  mean_allocation_disagreement: 'Allocation disagreement',
};

function formatValue(value: unknown) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '-';
    return value.toFixed(4);
  }
  if (typeof value === 'boolean') return String(value);
  if (value === null || typeof value === 'undefined' || value === '') return '-';
  return String(value);
}

function statusBadgeClass(status?: string) {
  if (status === 'supporting_evidence') return 'status-badge success';
  if (status === 'review') return 'status-badge warning';
  if (status === 'blocked') return 'status-badge danger';
  return 'status-badge muted';
}

export default function WorldModelV11Tab() {
  const [evidence, setEvidence] = useState<Paper58Evidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const metricRows = useMemo(() => {
    const deltas = evidence?.metric_summary?.deltas || {};
    return Object.keys(metricLabels).map(key => ({
      key,
      label: metricLabels[key],
      delta: deltas[key],
    }));
  }, [evidence]);

  const loadEvidence = async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch('/api/twm/paper58-benchmark', { credentials: 'include' });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || 'Paper58 evidence load failed');
        return;
      }
      setEvidence(data);
    } catch (err: any) {
      setError(err.message || 'Paper58 evidence load failed');
    } finally {
      setLoading(false);
    }
  };

  const refreshEvidence = async () => {
    setRefreshing(true);
    setError('');
    try {
      const resp = await fetch('/api/twm/paper58-benchmark/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await resp.json();
      if (!resp.ok || data.error) {
        setError(data.error || 'Paper58 evidence refresh failed');
        return;
      }
      setEvidence(data);
    } catch (err: any) {
      setError(err.message || 'Paper58 evidence refresh failed');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadEvidence();
  }, []);

  const status = evidence?.status || 'missing';
  const sourceFiles = evidence?.source_files || {};
  const missing = evidence?.missing || [];
  const readErrors = evidence?.read_errors || [];

  return (
    <div className="datapanel-section world-model-v11-tab">
      <div className="datapanel-section-header">
        <div>
          <h3>世界模型 v1.1</h3>
          <p>Paper58 is external benchmark support only. TWM-native generation and planning remain the runtime route.</p>
        </div>
        <button className="secondary-button" type="button" onClick={refreshEvidence} disabled={refreshing || loading}>
          <RefreshCw size={14} />
          {refreshing ? '刷新中' : '刷新证据'}
        </button>
      </div>

      {error && (
        <div className="datapanel-card danger">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="datapanel-card">
        <div className="datapanel-card-header">
          <ShieldCheck size={16} />
          <strong>Paper58 boundary</strong>
          <span className={statusBadgeClass(status)}>{status}</span>
        </div>
        <div className="metric-grid compact">
          <div><span>Claim scope</span><strong>{formatValue(evidence?.claim_scope)}</strong></div>
          <div><span>runtime_dependency=none</span><strong>{formatValue(evidence?.runtime_dependency)}</strong></div>
          <div><span>geofm_runtime_allowed=false</span><strong>{formatValue(evidence?.geofm_runtime_allowed)}</strong></div>
          <div><span>Generator role</span><strong>{formatValue(evidence?.twm_generator_role || 'not_a_runtime_generator')}</strong></div>
          <div><span>Primary route</span><strong>{formatValue(evidence?.primary_twm_route)}</strong></div>
          <div><span>Can promote claim ladder</span><strong>{formatValue(evidence?.can_promote_claim_ladder)}</strong></div>
        </div>
        <p className="muted-text">{evidence?.claim_boundary || 'Paper58 is external benchmark support only.'}</p>
      </div>

      <div className="datapanel-card">
        <div className="datapanel-card-header">
          <CheckCircle2 size={16} />
          <strong>Paper58 vs GeoSOS-FLUS</strong>
        </div>
        <div className="metric-grid compact">
          <div><span>Paper58 method</span><strong>{formatValue(evidence?.metric_summary?.best_paper58_method)}</strong></div>
          <div><span>Baseline</span><strong>{formatValue(evidence?.metric_summary?.baseline_method)}</strong></div>
          <div><span>Area count</span><strong>{formatValue(evidence?.metric_summary?.area_count)}</strong></div>
          <div><span>Wins</span><strong>{formatValue(evidence?.metric_summary?.paper58_vs_baseline_wins)}</strong></div>
        </div>
        <table className="data-table compact-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Delta</th>
            </tr>
          </thead>
          <tbody>
            {metricRows.map(row => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{formatValue(row.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="datapanel-card">
        <div className="datapanel-card-header">
          <strong>Evidence source</strong>
        </div>
        <div className="metric-grid compact">
          <div><span>metric_summary_by_method.csv</span><strong>{formatValue(sourceFiles.metric_summary_by_method)}</strong></div>
          <div><span>metrics_by_method.csv</span><strong>{formatValue(sourceFiles.metrics_by_method)}</strong></div>
          <div><span>manifest.json</span><strong>{formatValue(sourceFiles.manifest)}</strong></div>
        </div>
        {missing.length > 0 && <p className="muted-text">Missing: {missing.join(', ')}</p>}
        {readErrors.length > 0 && <p className="muted-text">Read errors: {readErrors.map(item => item.error || item.path).join('; ')}</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run frontend contract test and verify it passes**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q data_agent/test_world_model_v11_frontend_contract.py
```

Expected: PASS.

- [ ] **Step 5: Run TypeScript build**

Run:

```bash
npm run build
```

from `frontend/`.

Expected: TypeScript and Vite build pass. If pre-existing frontend build issues appear outside these files, report them before broad fixes.

- [ ] **Step 6: Commit Task 3**

```bash
git add data_agent/test_world_model_v11_frontend_contract.py frontend/src/components/datapanel/WorldModelV11Tab.tsx
git commit -m "feat: render World Model v1.1 Paper58 evidence dashboard"
```

---

### Task 4: End-to-End Verification

**Files:**
- Verify: `data_agent/test_world_model_v11_routes.py`
- Verify: `data_agent/test_world_model_v11_frontend_contract.py`
- Verify: `frontend/src/components/DataPanel.tsx`
- Verify: `frontend/src/components/datapanel/WorldModelV11Tab.tsx`
- Verify: `data_agent/api/world_model_v11_routes.py`
- Verify: `data_agent/frontend_api.py`

- [ ] **Step 1: Run backend and frontend contract tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_world_model_v11_routes.py \
  data_agent/test_world_model_v11_frontend_contract.py
```

Expected: PASS.

- [ ] **Step 2: Run Paper58 validation helper regression tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest -q \
  data_agent/test_twm_validation_bundle_smoke_script.py -k paper58
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm run build
```

from `frontend/`.

Expected: PASS.

- [ ] **Step 4: Run source diff check**

Run:

```bash
git diff --check -- \
  data_agent/api/world_model_v11_routes.py \
  data_agent/frontend_api.py \
  data_agent/test_world_model_v11_routes.py \
  data_agent/test_world_model_v11_frontend_contract.py \
  frontend/src/components/DataPanel.tsx \
  frontend/src/components/datapanel/WorldModelV11Tab.tsx
```

Expected: no output and exit code 0.

- [ ] **Step 5: Confirm no runtime-boundary violation**

Run:

```bash
rg -n "AlphaEarth|GeoFM|runtime_dependency|can_promote_claim_ladder|selected_plan|production_readiness|claim_ladder" \
  data_agent/api/world_model_v11_routes.py \
  frontend/src/components/datapanel/WorldModelV11Tab.tsx
```

Expected:

- AlphaEarth/GeoFM only appear in boundary text if present.
- UI/API preserve `runtime_dependency=none`, `geofm_runtime_allowed=false`, and `can_promote_claim_ladder`.
- No route code calls production readiness, selected-plan, claim ladder promotion, SCCA, or generation backend modules.

- [ ] **Step 6: Commit only if verification changed tracked files**

Run:

```bash
git status --short -- \
  data_agent/api/world_model_v11_routes.py \
  data_agent/frontend_api.py \
  data_agent/test_world_model_v11_routes.py \
  data_agent/test_world_model_v11_frontend_contract.py \
  frontend/src/components/DataPanel.tsx \
  frontend/src/components/datapanel/WorldModelV11Tab.tsx
```

Expected: no output. If any intended verification-only formatting change appears, commit it with:

```bash
git add data_agent/api/world_model_v11_routes.py data_agent/frontend_api.py data_agent/test_world_model_v11_routes.py data_agent/test_world_model_v11_frontend_contract.py frontend/src/components/DataPanel.tsx frontend/src/components/datapanel/WorldModelV11Tab.tsx
git commit -m "test: verify World Model v1.1 Paper58 tab"
```
