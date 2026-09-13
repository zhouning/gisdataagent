# TWM Future Latent State v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade TWM `future_latent_state` from an area-total compatibility alias into a trainable multi-dimensional hierarchical future-state latent head.

**Architecture:** Add deterministic latent target extraction and decoding helpers in `neural_dynamics.py`, then make MLP, hierarchical graph, and spatiotemporal transformer candidates predict a latent vector plus the existing scalar heads. Update service evaluation so total-area-only matches no longer hide land-space-type or delta errors.

**Tech Stack:** Python 3, pytest, PyTorch when available, existing TWM service/tests under `data_agent/territory_world_model` and `data_agent/test_territory_world_model.py`.

---

## File Structure

- Modify: `data_agent/territory_world_model/neural_dynamics.py`
  - Add latent v2 dimension extraction, vectorization, decoding, and compatibility indicator helpers.
  - Update MLP, hierarchical graph, and transformer candidate output widths and prediction assembly.
- Modify: `data_agent/territory_world_model/service.py`
  - Add latent transition component metrics.
  - Aggregate v2 component metrics in dynamics evaluation.
  - Update claim text that still calls `future_latent_state` a compatibility alias.
- Modify: `data_agent/test_territory_world_model.py`
  - Add decoder/contract tests.
  - Add neural backend contract test.
  - Add evaluation regression test for same total area but wrong land-type allocation.
- Optionally modify: `docs/twm-current-handoff.md`
  - Only if implementation changes claim wording enough that the handoff would otherwise contradict code.

---

### Task 1: Add Failing Latent v2 Decoder Contract Tests

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Test: `data_agent/test_territory_world_model.py`

- [ ] **Step 1: Write the failing decoder and prediction contract test**

Append near the existing `test_neural_dynamics_prediction_exposes_area_indicator_contract` test:

```python
def test_latent_v2_decoder_outputs_multi_dimensional_state_contract():
    from data_agent.territory_world_model.neural_dynamics import (
        _decode_latent_vector,
        _prediction_from_outputs,
    )

    dimensions = [
        "observed_next.total_area_m2",
        "observed_next.total_feature_count",
        "observed_next.land_space_types.agricultural_space.area_m2",
        "observed_next.land_space_types.agricultural_space.feature_count",
        "observed_next.land_space_types.agricultural_space.area_delta_m2",
        "observed_next.land_space_types.ecological_space.area_m2",
        "observed_next.land_space_types.ecological_space.feature_count",
        "observed_next.land_space_types.ecological_space.area_delta_m2",
        "delta.total_area_delta_m2",
        "delta.total_abs_area_delta_m2",
        "delta.by_land_type.agricultural_space.area_delta_m2",
        "delta.by_land_type.ecological_space.area_delta_m2",
    ]
    values = [1000.0, 10.0, 580.0, 6.0, -20.0, 420.0, 4.0, 20.0, 0.0, 40.0, -20.0, 20.0]

    latent = _decode_latent_vector(dimensions, values, source="unit_test_candidate")

    assert latent["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert latent["latent_head_scope"] == "multi_dimensional_hierarchical_state"
    assert latent["representation_boundary"] == "multi_dimensional_hierarchical_state_latent_not_full_geometry"
    assert latent["latent_vector"]["observed_next.total_area_m2"] == 1000.0
    assert latent["decoded_state"]["total_area_m2"] == 1000.0
    assert latent["decoded_state"]["total_feature_count"] == 10
    assert latent["decoded_state"]["land_space_types"]["agricultural_space"]["area_m2"] == 580.0
    assert latent["decoded_state"]["land_space_types"]["agricultural_space"]["feature_count"] == 6
    assert latent["decoded_state"]["land_space_types"]["agricultural_space"]["area_delta_m2"] == -20.0
    assert latent["transition_delta"]["total_abs_area_delta_m2"] == 40.0
    assert latent["transition_delta"]["by_land_type"]["ecological_space"]["area_delta_m2"] == 20.0

    prediction = _prediction_from_outputs(
        example={"id": "contract-example", "action": {"action_type": "protect", "target_role": "parcel"}},
        latent_dimensions=dimensions,
        latent_values=values,
        constraint_probability=0.24,
        utility_delta=0.31,
        confidence=0.72,
        calibrated_utility=0.28,
        action_allowed_probability=0.82,
        source="unit_test_candidate",
    )

    assert prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert prediction["future_latent_state"]["decoded_state"]["total_area_m2"] == 1000.0
    assert prediction["future_area_and_key_indicators"]["projected"]["total_area_m2"] == 1000.0
    assert prediction["future_latent_state"]["representation_boundary"] != "compatibility_alias_for_future_area_and_key_indicators"
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_latent_v2_decoder_outputs_multi_dimensional_state_contract -q
```

Expected: FAIL with `ImportError` for `_decode_latent_vector` or `TypeError` because `_prediction_from_outputs` does not accept `latent_dimensions` / `latent_values`.

- [ ] **Step 3: Commit the failing test**

```bash
git add data_agent/test_territory_world_model.py
git commit -m "test(twm): specify future latent state v2 contract"
```

---

### Task 2: Implement Latent v2 Extraction and Decoder Helpers

**Files:**
- Modify: `data_agent/territory_world_model/neural_dynamics.py`
- Test: `data_agent/test_territory_world_model.py`

- [ ] **Step 1: Add helper functions in `neural_dynamics.py`**

Place these helpers near `_target_row()` and `_prediction_from_outputs()`:

```python
LATENT_STATE_V2_SCHEMA = "territory_world_model.predicted_latent_state.v2"
LATENT_STATE_V2_BOUNDARY = "multi_dimensional_hierarchical_state_latent_not_full_geometry"


def _latent_dimension_names(examples: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for example in examples:
        targets = dict(example.get("targets") or {})
        latent = dict(targets.get("future_latent_state") or {})
        _collect_latent_dimensions("observed_next", dict(latent.get("observed_next") or latent.get("projected") or {}), names)
        _collect_latent_dimensions("delta", dict(latent.get("delta") or {}), names)
    ordered = sorted(names)
    return ordered or ["observed_next.total_area_m2"]


def _collect_latent_dimensions(prefix: str, payload: dict[str, Any], names: set[str]) -> None:
    for key in ("total_area_m2", "total_feature_count", "total_area_delta_m2", "total_abs_area_delta_m2", "change_intensity"):
        if key in payload:
            names.add(f"{prefix}.{key}")
    for land_type, metrics in sorted(dict(payload.get("land_space_types") or {}).items(), key=lambda item: str(item[0])):
        safe_type = _safe_feature_key(str(land_type))
        metric_payload = dict(metrics or {})
        for metric in ("area_m2", "feature_count", "area_delta_m2"):
            if metric in metric_payload:
                names.add(f"{prefix}.land_space_types.{safe_type}.{metric}")
    for land_type, metrics in sorted(dict(payload.get("by_land_type") or {}).items(), key=lambda item: str(item[0])):
        safe_type = _safe_feature_key(str(land_type))
        metric_payload = dict(metrics or {})
        for metric in ("area_m2", "feature_count", "area_delta_m2"):
            if metric in metric_payload:
                names.add(f"{prefix}.by_land_type.{safe_type}.{metric}")


def _latent_target_vector(targets: dict[str, Any], dimensions: list[str]) -> list[float]:
    latent = dict(targets.get("future_latent_state") or {})
    source = {
        "observed_next": dict(latent.get("observed_next") or latent.get("projected") or {}),
        "delta": dict(latent.get("delta") or {}),
    }
    flat: dict[str, float] = {}
    _flatten_latent_payload("observed_next", source["observed_next"], flat)
    _flatten_latent_payload("delta", source["delta"], flat)
    return [float(flat.get(name, 0.0)) for name in dimensions]


def _flatten_latent_payload(prefix: str, payload: dict[str, Any], out: dict[str, float]) -> None:
    for key in ("total_area_m2", "total_feature_count", "total_area_delta_m2", "total_abs_area_delta_m2", "change_intensity"):
        value = safe_float(payload.get(key), None)
        if value is not None:
            out[f"{prefix}.{key}"] = float(value)
    for land_type, metrics in sorted(dict(payload.get("land_space_types") or {}).items(), key=lambda item: str(item[0])):
        safe_type = _safe_feature_key(str(land_type))
        metric_payload = dict(metrics or {})
        for metric in ("area_m2", "feature_count", "area_delta_m2"):
            value = safe_float(metric_payload.get(metric), None)
            if value is not None:
                out[f"{prefix}.land_space_types.{safe_type}.{metric}"] = float(value)
    for land_type, metrics in sorted(dict(payload.get("by_land_type") or {}).items(), key=lambda item: str(item[0])):
        safe_type = _safe_feature_key(str(land_type))
        metric_payload = dict(metrics or {})
        for metric in ("area_m2", "feature_count", "area_delta_m2"):
            value = safe_float(metric_payload.get(metric), None)
            if value is not None:
                out[f"{prefix}.by_land_type.{safe_type}.{metric}"] = float(value)


def _decode_latent_vector(dimension_names: list[str], values: list[float], *, source: str) -> dict[str, Any]:
    vector = {name: round(float(values[idx]), 6) for idx, name in enumerate(dimension_names)}
    decoded_state: dict[str, Any] = {"land_space_types": {}}
    transition_delta: dict[str, Any] = {"by_land_type": {}}
    for name, value in vector.items():
        parts = name.split(".")
        if name == "observed_next.total_area_m2":
            decoded_state["total_area_m2"] = round(max(0.0, value), 6)
        elif name == "observed_next.total_feature_count":
            decoded_state["total_feature_count"] = int(round(max(0.0, value)))
        elif len(parts) == 4 and parts[:2] == ["observed_next", "land_space_types"]:
            land_type = parts[2]
            metric = parts[3]
            target = decoded_state.setdefault("land_space_types", {}).setdefault(land_type, {})
            target[metric] = int(round(max(0.0, value))) if metric == "feature_count" else round(max(0.0, value), 6) if metric == "area_m2" else round(value, 6)
        elif name == "delta.total_area_delta_m2":
            transition_delta["total_area_delta_m2"] = round(value, 6)
        elif name == "delta.total_abs_area_delta_m2":
            transition_delta["total_abs_area_delta_m2"] = round(max(0.0, value), 6)
        elif name == "delta.change_intensity":
            transition_delta["change_intensity"] = round(_clamp01(value), 6)
        elif len(parts) == 4 and parts[:2] == ["delta", "by_land_type"]:
            land_type = parts[2]
            metric = parts[3]
            target = transition_delta.setdefault("by_land_type", {}).setdefault(land_type, {})
            target[metric] = round(value, 6)
    if "total_area_m2" not in decoded_state:
        decoded_state["total_area_m2"] = round(sum(float((item or {}).get("area_m2") or 0.0) for item in decoded_state["land_space_types"].values()), 6)
    if "total_feature_count" not in decoded_state:
        decoded_state["total_feature_count"] = int(sum(int((item or {}).get("feature_count") or 0) for item in decoded_state["land_space_types"].values()))
    return {
        "schema": LATENT_STATE_V2_SCHEMA,
        "latent_head_scope": "multi_dimensional_hierarchical_state",
        "representation_boundary": LATENT_STATE_V2_BOUNDARY,
        "dimensions": list(dimension_names),
        "latent_vector": vector,
        "decoded_state": decoded_state,
        "transition_delta": transition_delta,
        "source": source,
    }
```

- [ ] **Step 2: Update `_prediction_from_outputs()` signature and body**

Change the function signature to accept latent v2 values while preserving old callers:

```python
def _prediction_from_outputs(
    *,
    example: dict[str, Any],
    constraint_probability: float,
    utility_delta: float,
    confidence: float,
    calibrated_utility: float,
    action_allowed_probability: float,
    source: str,
    latent_dimensions: list[str] | None = None,
    latent_values: list[float] | None = None,
    area_total: float | None = None,
) -> dict[str, Any]:
```

At the top of the function, build the latent:

```python
    action = dict(example.get("action") or {})
    if latent_dimensions and latent_values is not None:
        latent = _decode_latent_vector(latent_dimensions, list(latent_values), source=source)
    else:
        fallback_area = round(max(0.0, float(area_total or 0.0)), 6)
        latent = _decode_latent_vector(["observed_next.total_area_m2"], [fallback_area], source=source)
    decoded = dict(latent.get("decoded_state") or {})
    total_area = float(safe_float(decoded.get("total_area_m2"), 0.0) or 0.0)
```

Replace the existing `latent_observed` / `indicators` block with:

```python
    indicators = {
        "schema": "territory_world_model.future_area_and_key_indicators.v1",
        "representation_boundary": "derived_from_multi_dimensional_hierarchical_state_latent",
        "action": action,
        "observed_next": {
            "total_area_m2": round(total_area, 6),
            "total_feature_count": int(decoded.get("total_feature_count") or 0),
            "land_space_types": dict(decoded.get("land_space_types") or {}),
        },
        "projected": {
            "total_area_m2": round(total_area, 6),
            "projected_risk_pressure": round(_clamp01(constraint_probability), 6),
            "projected_utility_delta": round(float(utility_delta), 6),
            "calibrated_utility_delta": round(float(calibrated_utility), 6),
            "action_allowed_probability": round(_clamp01(action_allowed_probability), 6),
            "confidence": round(_clamp01(confidence), 6),
        },
        "dimensions": list(latent.get("dimensions") or []),
        "source": source,
    }
```

Return `future_latent_state: latent` instead of the old v1 compatibility alias.

- [ ] **Step 3: Run the decoder contract test**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_latent_v2_decoder_outputs_multi_dimensional_state_contract -q
```

Expected: PASS.

- [ ] **Step 4: Run the existing old contract test**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_neural_dynamics_prediction_exposes_area_indicator_contract -q
```

Expected: FAIL if it still asserts `compatibility_alias_for_future_area_and_key_indicators`.

- [ ] **Step 5: Update the old contract test to v2 wording**

Change the final assertions in `test_neural_dynamics_prediction_exposes_area_indicator_contract` to:

```python
    assert prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert prediction["future_latent_state"]["decoded_state"]["total_area_m2"] == 1234.5
    assert prediction["future_latent_state"]["representation_boundary"] == "multi_dimensional_hierarchical_state_latent_not_full_geometry"
    assert indicators["representation_boundary"] == "derived_from_multi_dimensional_hierarchical_state_latent"
```

- [ ] **Step 6: Run both contract tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py::test_latent_v2_decoder_outputs_multi_dimensional_state_contract \
  data_agent/test_territory_world_model.py::test_neural_dynamics_prediction_exposes_area_indicator_contract -q
```

Expected: `2 passed`.

- [ ] **Step 7: Commit**

```bash
git add data_agent/territory_world_model/neural_dynamics.py data_agent/test_territory_world_model.py
git commit -m "feat(twm): add future latent state v2 decoder"
```

---

### Task 3: Train the MLP Backend Against Latent v2 Vectors

**Files:**
- Modify: `data_agent/test_territory_world_model.py`
- Modify: `data_agent/territory_world_model/neural_dynamics.py`
- Test: `data_agent/test_territory_world_model.py`

- [ ] **Step 1: Add the failing MLP contract test**

Append near existing neural dynamics training tests:

```python
def test_neural_multi_head_dynamics_trains_future_latent_state_v2_head():
    from data_agent.territory_world_model.neural_dynamics import train_neural_multi_head_dynamics

    svc = _build_service()
    project, state = _build_project_and_state(svc)
    dataset = svc.build_dynamics_training_dataset(state["state_version"]["id"], {"scenario": "latent_v2_contract"})
    observed = _observed_dynamics_dataset(dataset, count=6)
    for idx, example in enumerate(observed["examples"]):
        example["targets"]["future_latent_state"] = {
            "observed_next": {
                "total_area_m2": 1000.0,
                "total_feature_count": 10,
                "land_space_types": {
                    "agricultural_space": {"area_m2": 600.0 - idx * 3.0, "feature_count": 6, "area_delta_m2": -idx * 3.0},
                    "ecological_space": {"area_m2": 400.0 + idx * 3.0, "feature_count": 4, "area_delta_m2": idx * 3.0},
                },
            },
            "delta": {
                "total_area_delta_m2": 0.0,
                "total_abs_area_delta_m2": idx * 6.0,
                "by_land_type": {
                    "agricultural_space": {"area_delta_m2": -idx * 3.0},
                    "ecological_space": {"area_delta_m2": idx * 3.0},
                },
            },
        }

    report = train_neural_multi_head_dynamics(
        observed,
        {"trainer_type": "torch_multi_head_mlp", "is_scaffold_baseline": False},
        {"objective_contract": {"multi_head_required": ["future_latent_state"]}, "loss_components": {}},
        {"epochs": 2, "hidden_dim": 8, "seed": 7},
    )

    assert report["diagnostics"]["status"] == "pass"
    heads = report["learned_parameters"]["architecture"]["heads"]
    assert "future_latent_state.latent_vector" in heads
    assert "future_latent_state.decoded_state" in heads
    assert "future_latent_state.transition_delta" in heads
    assert "future_latent_state.area_total" not in heads
    assert report["learned_parameters"]["latent_contract"]["dimension_count"] >= 8
    first_prediction = next(iter(report["predictions"].values()))
    assert first_prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert first_prediction["future_latent_state"]["decoded_state"]["land_space_types"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_neural_multi_head_dynamics_trains_future_latent_state_v2_head -q
```

Expected: FAIL because the architecture still lists `future_latent_state.area_total` and learned parameters have no `latent_contract`.

- [ ] **Step 3: Update MLP output width and loss**

In `train_neural_multi_head_dynamics()`:

1. After `target_rows = [_target_row(item) for item in usable]`, add:

```python
    latent_dimensions = _latent_dimension_names(usable)
    latent_width = max(1, len(latent_dimensions))
```

2. Replace `y_area` with:

```python
    y_latent_values = [_latent_target_vector(dict(item.get("targets") or {}), latent_dimensions) for item in train_examples]
    y_latent_stats = _normalization_stats(y_latent_values)
    y_latent = torch.tensor(_normalize_matrix(y_latent_values, y_latent_stats), dtype=torch.float32)
```

3. Change model creation:

```python
    model = _MultiHeadDynamicsMLP(
        input_dim=len(feature_names),
        hidden_dim=cfg["hidden_dim"],
        dropout=cfg["dropout"],
        output_dim=latent_width + 5,
        nn=nn,
    )
```

4. In the training loop, replace scalar area slices:

```python
        latent_pred = out[:, :latent_width]
        constraint_logit = out[:, latent_width:latent_width + 1]
        utility_pred = out[:, latent_width + 1:latent_width + 2]
        confidence_logit = out[:, latent_width + 2:latent_width + 3]
        calibration_pred = out[:, latent_width + 3:latent_width + 4]
        allowed_logit = out[:, latent_width + 4:latent_width + 5]
        constraint_prob = torch.sigmoid(constraint_logit)
        loss = (
            mse(latent_pred, y_latent)
            + bce(constraint_logit, y_constraint)
            + cfg["constraint_risk_calibration_weight"] * mse(constraint_prob, y_constraint)
            + 1.2 * mse(utility_pred, y_utility)
            + 0.7 * bce(confidence_logit, y_confidence)
            + 0.8 * mse(calibration_pred, y_calibration)
            + 0.6 * bce(allowed_logit, y_allowed)
            + cfg["ranking_weight"] * _pairwise_ranking_loss(utility_pred.squeeze(1), y_ranking, torch)
        )
```

5. In prediction assembly, denormalize the latent vector:

```python
        latent_values = _denormalize_vector(row[:latent_width], y_latent_stats)
        constraint = _sigmoid(row[latent_width])
        utility = _denormalize_value(row[latent_width + 1], y_stats["utility_delta"])
        confidence = _sigmoid(row[latent_width + 2])
        calibration = _denormalize_value(row[latent_width + 3], y_stats["calibrated_utility_delta"])
        allowed_probability = _sigmoid(row[latent_width + 4])
```

6. Call `_prediction_from_outputs()` with:

```python
            latent_dimensions=latent_dimensions,
            latent_values=latent_values,
```

- [ ] **Step 4: Update `_MultiHeadDynamicsMLP`**

Change the constructor to:

```python
class _MultiHeadDynamicsMLP:
    def __new__(cls, *, input_dim: int, hidden_dim: int, dropout: float, output_dim: int, nn: Any):
        return nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, output_dim),
        )
```

Add helper:

```python
def _denormalize_vector(values: list[float], stats: dict[str, list[float]]) -> list[float]:
    means = list(stats.get("mean") or [])
    stds = list(stats.get("std") or [])
    return [
        round(float(value) * (float(stds[idx]) or 1.0) + float(means[idx]), 6)
        for idx, value in enumerate(values)
    ]
```

- [ ] **Step 5: Update MLP learned parameter contract**

In `learned_parameters["architecture"]["heads"]`, replace the old area entries with:

```python
            "heads": [
                "future_latent_state.latent_vector",
                "future_latent_state.decoded_state",
                "future_latent_state.transition_delta",
                "constraint_violation_probability",
                "planning_utility_delta",
                "uncertainty.confidence",
                "calibration.calibrated_utility_delta",
                "action_mask.allowed",
            ],
```

Add:

```python
        "latent_contract": {
            "schema": "territory_world_model.future_latent_state_v2_contract.v1",
            "dimension_count": len(latent_dimensions),
            "dimensions": list(latent_dimensions),
            "target_normalization": y_latent_stats,
            "representation_boundary": LATENT_STATE_V2_BOUNDARY,
        },
```

- [ ] **Step 6: Run the MLP contract test**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_neural_multi_head_dynamics_trains_future_latent_state_v2_head -q
```

Expected: PASS.

- [ ] **Step 7: Run nearby neural tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "neural_dynamics or latent_v2" -q
```

Expected: PASS for selected tests.

- [ ] **Step 8: Commit**

```bash
git add data_agent/territory_world_model/neural_dynamics.py data_agent/test_territory_world_model.py
git commit -m "feat(twm): train mlp future latent state v2 head"
```

---

### Task 4: Update Graph and Transformer Backends to Emit Latent v2

**Files:**
- Modify: `data_agent/territory_world_model/neural_dynamics.py`
- Modify: `data_agent/test_territory_world_model.py`

- [ ] **Step 1: Add a failing backend family coverage assertion**

Extend existing graph/transformer tests, or add this test if no focused test exists:

```python
def test_trainable_graph_and_transformer_backends_report_latent_v2_heads():
    svc = _build_service()
    project, state = _build_project_and_state(svc)
    dataset = svc.build_dynamics_training_dataset(state["state_version"]["id"], {"scenario": "latent_v2_backend_contract"})
    observed = _observed_dynamics_dataset(dataset, count=6)

    graph_report = svc.train_dynamics_candidate(state["state_version"]["id"], {
        "backend_type": "torch_hierarchical_graph",
        "dataset": observed,
        "epochs": 2,
        "hidden_dim": 8,
        "seed": 11,
    })
    transformer_report = svc.train_dynamics_candidate(state["state_version"]["id"], {
        "backend_type": "torch_spatiotemporal_transformer",
        "dataset": observed,
        "epochs": 2,
        "hidden_dim": 8,
        "seed": 13,
    })

    for report in (graph_report, transformer_report):
        if report["status"] == "blocked" and "torch_unavailable" in json.dumps(report):
            continue
        heads = report["learned_parameters"]["architecture"]["heads"]
        assert "future_latent_state.latent_vector" in heads
        assert "future_latent_state.area_total" not in heads
        first_prediction = next(iter(report["predictions"].values()))
        assert first_prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_trainable_graph_and_transformer_backends_report_latent_v2_heads -q
```

Expected: FAIL because graph and transformer modules still output six scalar values with area at index 0.

- [ ] **Step 3: Update graph backend output width and slices**

In `train_hierarchical_graph_dynamics()`:

- Compute `latent_dimensions` and `latent_width` from `usable`.
- Build `y_latent` with `_latent_target_vector()`.
- Pass `output_dim=latent_width + 5` to `_HierarchicalGraphDynamicsModel`.
- Slice output using the same scalar-start pattern from Task 3.
- Build predictions with `latent_dimensions` and denormalized latent values.
- Add the same `latent_contract` block in `learned_parameters`.
- Replace architecture head strings with v2 head strings.

Update `_HierarchicalGraphDynamicsModel.__new__()` signature to accept `output_dim: int` and change the final layer:

```python
nn.Linear(hidden_dim, output_dim)
```

- [ ] **Step 4: Update transformer backend output width and residual head indices**

In `train_spatiotemporal_transformer_dynamics()`:

- Compute `latent_dimensions` and `latent_width`.
- Build `y_latent`.
- Pass `output_dim=latent_width + 5` and `scalar_start=latent_width` to `_SpatiotemporalTransformerDynamicsModel`.
- Slice scalar heads as:
  - constraint: `scalar_start`
  - utility: `scalar_start + 1`
  - confidence: `scalar_start + 2`
  - calibration: `scalar_start + 3`
  - allowed: `scalar_start + 4`

Update `_SpatiotemporalTransformerDynamicsModel.__new__()` signature:

```python
        output_dim: int,
        scalar_start: int,
```

Change:

```python
self.head = nn.Linear(hidden_dim, output_dim)
```

Update residual concatenation logic:

```python
out = torch.cat([
    out[:, :scalar_start],
    out[:, scalar_start:scalar_start + 1] + risk_residual,
    out[:, scalar_start + 1:],
], dim=1)
```

For direct risk replacement:

```python
out = torch.cat([
    out[:, :scalar_start],
    risk_logit,
    out[:, scalar_start + 1:],
], dim=1)
```

For feasibility residual:

```python
allowed_index = scalar_start + 4
out = torch.cat([
    out[:, :allowed_index],
    out[:, allowed_index:allowed_index + 1] + feasibility_residual,
    out[:, allowed_index + 1:],
], dim=1)
```

- [ ] **Step 5: Run backend coverage test**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_trainable_graph_and_transformer_backends_report_latent_v2_heads -q
```

Expected: PASS, or SKIP-like pass branch if torch is unavailable and reports are blocked with `torch_unavailable`.

- [ ] **Step 6: Run trainable dynamics focused tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "train_dynamics_candidate or transformer or hierarchical_graph or latent_v2" -q
```

Expected: PASS for selected tests.

- [ ] **Step 7: Commit**

```bash
git add data_agent/territory_world_model/neural_dynamics.py data_agent/test_territory_world_model.py
git commit -m "feat(twm): emit latent v2 from trainable dynamics backends"
```

---

### Task 5: Upgrade Dynamics Evaluation to Score Latent Components

**Files:**
- Modify: `data_agent/territory_world_model/service.py`
- Modify: `data_agent/test_territory_world_model.py`

- [ ] **Step 1: Add failing evaluation regression test**

Add this test near dynamics evaluation tests:

```python
def test_latent_transition_error_detects_land_type_mismatch_when_total_area_matches():
    svc = _build_service()
    target = {
        "observed_next": {
            "total_area_m2": 1000.0,
            "total_feature_count": 10,
            "land_space_types": {
                "agricultural_space": {"area_m2": 600.0, "feature_count": 6, "area_delta_m2": -50.0},
                "ecological_space": {"area_m2": 400.0, "feature_count": 4, "area_delta_m2": 50.0},
            },
        },
        "delta": {
            "total_area_delta_m2": 0.0,
            "total_abs_area_delta_m2": 100.0,
        },
    }
    predicted = {
        "decoded_state": {
            "total_area_m2": 1000.0,
            "total_feature_count": 10,
            "land_space_types": {
                "agricultural_space": {"area_m2": 400.0, "feature_count": 4, "area_delta_m2": 50.0},
                "ecological_space": {"area_m2": 600.0, "feature_count": 6, "area_delta_m2": -50.0},
            },
        },
        "transition_delta": {
            "total_area_delta_m2": 0.0,
            "total_abs_area_delta_m2": 100.0,
        },
        "latent_vector": {
            "observed_next.land_space_types.agricultural_space.area_m2": 400.0,
            "observed_next.land_space_types.ecological_space.area_m2": 600.0,
        },
    }

    components = svc._latent_transition_error_components(predicted=predicted, target=target)

    assert components["total_area_error"] == 0.0
    assert components["land_type_area_mae"] > 0.0
    assert components["aggregate_error"] > 0.0
    assert svc._latent_transition_error(predicted=predicted, target=target) == components["aggregate_error"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_latent_transition_error_detects_land_type_mismatch_when_total_area_matches -q
```

Expected: FAIL because `_latent_transition_error_components` does not exist and `_latent_transition_error` short-circuits on total-area equality.

- [ ] **Step 3: Implement `_latent_transition_error_components()`**

Add this method before `_latent_transition_error()` in `service.py`:

```python
    def _latent_transition_error_components(self, *, predicted: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
        observed = dict(target.get("observed_next") or target.get("projected") or target.get("decoded_state") or {})
        pred = dict(predicted.get("decoded_state") or predicted.get("observed_next") or predicted.get("projected") or predicted)
        observed_delta = dict(target.get("delta") or {})
        pred_delta = dict(predicted.get("transition_delta") or predicted.get("delta") or {})
        components: dict[str, Any] = {}

        observed_area = safe_float(observed.get("total_area_m2"), None)
        pred_area = safe_float(pred.get("total_area_m2"), None)
        if observed_area is not None and pred_area is not None:
            components["total_area_error"] = round(abs(float(pred_area) - float(observed_area)) / max(abs(float(observed_area)), 1.0), 6)

        observed_types = dict(observed.get("land_space_types") or {})
        pred_types = dict(pred.get("land_space_types") or {})
        area_errors = []
        count_errors = []
        delta_errors = []
        for key in sorted(set(observed_types) | set(pred_types)):
            target_payload = dict(observed_types.get(key) or {})
            pred_payload = dict(pred_types.get(key) or {})
            target_area = float(safe_float(target_payload.get("area_m2"), 0.0) or 0.0)
            pred_area_value = float(safe_float(pred_payload.get("area_m2"), 0.0) or 0.0)
            area_errors.append(abs(pred_area_value - target_area) / max(abs(target_area), 1.0))
            target_count = float(safe_float(target_payload.get("feature_count"), 0.0) or 0.0)
            pred_count = float(safe_float(pred_payload.get("feature_count"), 0.0) or 0.0)
            count_errors.append(abs(pred_count - target_count) / max(abs(target_count), 1.0))
            target_delta = float(safe_float(target_payload.get("area_delta_m2"), 0.0) or 0.0)
            pred_delta_value = float(safe_float(pred_payload.get("area_delta_m2"), 0.0) or 0.0)
            delta_errors.append(abs(pred_delta_value - target_delta) / max(abs(target_delta), 1.0))
        if area_errors:
            components["land_type_area_mae"] = self._mean(area_errors)
        if count_errors:
            components["land_type_feature_count_mae"] = self._mean(count_errors)
        if delta_errors:
            components["land_type_delta_mae"] = self._mean(delta_errors)

        delta_component_errors = []
        for key in ("total_area_delta_m2", "total_abs_area_delta_m2", "change_intensity"):
            target_value = safe_float(observed_delta.get(key), None)
            pred_value = safe_float(pred_delta.get(key), None)
            if target_value is not None and pred_value is not None:
                delta_component_errors.append(abs(float(pred_value) - float(target_value)) / max(abs(float(target_value)), 1.0))
        if delta_component_errors:
            components["delta_mae"] = self._mean(delta_component_errors)

        observed_vector = dict(target.get("latent_vector") or {})
        pred_vector = dict(predicted.get("latent_vector") or {})
        if observed_vector and pred_vector:
            vector_errors = []
            for key in sorted(set(observed_vector) | set(pred_vector)):
                target_value = float(safe_float(observed_vector.get(key), 0.0) or 0.0)
                pred_value = float(safe_float(pred_vector.get(key), 0.0) or 0.0)
                vector_errors.append(abs(pred_value - target_value) / max(abs(target_value), 1.0))
            components["latent_vector_mae"] = self._mean(vector_errors)

        numeric = [float(value) for key, value in components.items() if key.endswith("_error") or key.endswith("_mae")]
        components["aggregate_error"] = self._mean(numeric) if numeric else None
        return components
```

- [ ] **Step 4: Update `_latent_transition_error()`**

Replace the method body with:

```python
    def _latent_transition_error(self, *, predicted: dict[str, Any], target: dict[str, Any]) -> float | None:
        components = self._latent_transition_error_components(predicted=predicted, target=target)
        aggregate = components.get("aggregate_error")
        return float(aggregate) if aggregate is not None else None
```

- [ ] **Step 5: Aggregate component metrics in `_dynamics_evaluation_metrics()`**

Inside `_dynamics_evaluation_metrics()`, add before the loop:

```python
        transition_component_rows: list[dict[str, Any]] = []
```

Inside the loop, after `transition_error`:

```python
            transition_components = self._latent_transition_error_components(
                predicted=dict(prediction.get("future_latent_state") or {}),
                target=dict(targets.get("future_latent_state") or {}),
            )
            if transition_components.get("aggregate_error") is not None:
                transition_component_rows.append(transition_components)
```

Before `head_metrics`, add:

```python
        transition_component_metrics = {}
        for key in sorted({key for row in transition_component_rows for key in row if key != "aggregate_error"}):
            values = [float(row[key]) for row in transition_component_rows if row.get(key) is not None]
            transition_component_metrics[key] = self._mean(values)
```

Change future latent head metrics to:

```python
            "future_latent_state": {
                "count": len(transition_errors),
                "mean_error": metrics["mean_transition_error"],
                "components": transition_component_metrics,
            },
```

- [ ] **Step 6: Run the evaluation regression test**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py::test_latent_transition_error_detects_land_type_mismatch_when_total_area_matches -q
```

Expected: PASS.

- [ ] **Step 7: Run dynamics evaluation focused tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "dynamics_evaluation or latent_transition or future_latent_state" -q
```

Expected: PASS for selected tests. If old tests assert exact `mean_transition_error` from total-area-only behavior, update their expected value only after confirming the new component metrics explain the change.

- [ ] **Step 8: Commit**

```bash
git add data_agent/territory_world_model/service.py data_agent/test_territory_world_model.py
git commit -m "feat(twm): evaluate latent v2 component errors"
```

---

### Task 6: Update Claim Text, Focused Verification, and Final Commit

**Files:**
- Modify: `data_agent/territory_world_model/service.py`
- Modify: `data_agent/test_territory_world_model.py`
- Optional modify: `docs/twm-current-handoff.md`

- [ ] **Step 1: Update service claim text**

Replace text that says `future_latent_state remains a compatibility field` or
`compatibility future_latent_state` with wording like:

```python
"claim": "TWM forecasts a multi-dimensional hierarchical future-state latent, constraint-risk, planning utility, uncertainty and action-mask feasibility conditional on review/protect/convert/restore actions; the latent is decoded into state summaries and does not generate full parcel geometry.",
```

In profile / documentation payloads, use:

```python
"future-state latent decoded into area, feature-count, land-space-type and transition-delta summaries"
```

- [ ] **Step 2: Update tests that assert old boundary wording**

Search:

```bash
rg -n "compatibility alias|future_latent_state.area_total|compact area/key|future latent state" data_agent/test_territory_world_model.py data_agent/territory_world_model docs/twm-current-handoff.md
```

For tests that intentionally verify claim boundaries, replace assertions with:

```python
assert "multi-dimensional hierarchical future-state latent" in dynamics_claim
assert "full parcel geometry" in json.dumps(boundary_payload)
```

Keep any assertion that prevents overclaiming full geometry.

- [ ] **Step 3: Run latent-focused tests**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_territory_world_model.py -k "latent or neural_dynamics or train_dynamics_candidate" -q
```

Expected: PASS.

- [ ] **Step 4: Run TWM focused tests that do not require external services**

Run:

```bash
/Users/zhouning/gisdataagent/.venv/bin/python -m pytest \
  data_agent/test_territory_world_model.py \
  data_agent/test_twm_state_input.py \
  data_agent/test_twm_data_foundation_validation.py \
  data_agent/test_twm_deployment_punch_list.py -q
```

Expected: PASS. If runtime is long, record exact failing or slow tests and run the narrow impacted subset again after fixes.

- [ ] **Step 5: Inspect changed files**

Run:

```bash
git diff --stat
git diff --check
```

Expected: only intended files changed; `git diff --check` has no output.

- [ ] **Step 6: Commit final claim/test adjustments**

```bash
git add data_agent/territory_world_model/service.py data_agent/test_territory_world_model.py docs/twm-current-handoff.md
git commit -m "docs(twm): align latent v2 claim boundary"
```

If `docs/twm-current-handoff.md` was not changed, use:

```bash
git add data_agent/territory_world_model/service.py data_agent/test_territory_world_model.py
git commit -m "docs(twm): align latent v2 claim boundary"
```

- [ ] **Step 7: Final verification summary**

Record:

```text
Implemented future_latent_state v2:
- latent vector target extraction and decoder
- MLP, graph, and transformer latent vector heads
- component-level latent evaluation metrics
- claim boundary updated to multi-dimensional latent, not full geometry

Verification:
- <paste exact pytest commands and pass counts>
- git diff --check passed
```

Do not claim production readiness or full geometry generation.

---

## Plan Self-Review

Spec coverage:

- Latent v2 schema: Task 1 and Task 2.
- Target extraction: Task 2.
- Neural head contract for MLP, graph, transformer: Task 3 and Task 4.
- Decoder: Task 2.
- Evaluation components: Task 5.
- Claim boundary: Task 6.
- TDD: every task starts with a failing test or a verification step before implementation.

Type consistency:

- The plan consistently uses `_latent_dimension_names`, `_latent_target_vector`,
  `_decode_latent_vector`, `_denormalize_vector`, and
  `_latent_transition_error_components`.
- `future_latent_state` v2 consistently uses `latent_vector`, `decoded_state`,
  `transition_delta`, `dimensions`, `latent_head_scope`, and
  `representation_boundary`.

Scope:

- This plan intentionally does not address vector tiles, big-data scale, or full
  geometry generation. Those are separate roadmap increments after latent v2 is
  real.
