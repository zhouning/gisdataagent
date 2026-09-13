# TWM Future Latent State v2 Design

Date: 2026-06-29
Project: GIS Data Agent / Territory World Model
Status: approved for implementation planning

## Purpose

TWM currently exposes `future_latent_state` as a compatibility field backed by
a compact `total_area_m2` / key-indicator proxy. That is honest, but it leaves a
gap between the world-model claim and the actual trainable head. This increment
turns `future_latent_state` into a real multi-dimensional hierarchical state
head without claiming full parcel geometry generation.

The goal is to make the next-state head:

- action-conditioned
- multi-dimensional
- decodable into readable territorial state summaries
- evaluated by land-space-type and transition-delta errors, not only total area
- still claim-gated and explicit about its boundary

## Non-Goals

- Do not generate full future parcel geometries.
- Do not claim production accuracy.
- Do not replace the existing evidence, readiness, causal, GeoFM, planner, or
  human-review gates.
- Do not start the large-data / vector-tile roadmap in this increment.
- Do not refactor all of `TerritoryWorldModelService`; only touch service
  helpers directly needed for latent v2 metrics and contracts.

## Current Boundary

Relevant current implementation:

- `data_agent/territory_world_model/neural_dynamics.py`
  - `_target_row()` extracts only `area_total` from `targets.future_latent_state`.
  - `_prediction_from_outputs()` emits `future_latent_state` as a compatibility
    alias for `future_area_and_key_indicators`.
  - trainable MLP, graph, and transformer candidates all preserve the same
    area-centric latent output.
- `data_agent/territory_world_model/service.py`
  - `_latent_from_snapshot_rows()` already builds richer observed targets:
    `total_area_m2`, `total_feature_count`, and
    `land_space_types.{type}.area_m2 / feature_count / area_delta_m2`.
  - `_latent_transition_error()` currently prefers total-area error and only
    falls back to land-type area error when total area is absent.

This means the data contract has richer target information than the neural
training head uses.

## Design

### 1. Latent v2 Schema

Add a v2 prediction shape under `future_latent_state`:

```json
{
  "schema": "territory_world_model.predicted_latent_state.v2",
  "latent_head_scope": "multi_dimensional_hierarchical_state",
  "representation_boundary": "multi_dimensional_hierarchical_state_latent_not_full_geometry",
  "dimensions": ["total_area_m2", "..."],
  "latent_vector": {"total_area_m2": 123.0, "...": 0.42},
  "decoded_state": {
    "total_area_m2": 123.0,
    "total_feature_count": 10,
    "land_space_types": {
      "farmland": {
        "area_m2": 80.0,
        "feature_count": 7,
        "area_delta_m2": -5.0
      }
    }
  },
  "transition_delta": {
    "total_area_delta_m2": 3.0,
    "total_abs_area_delta_m2": 8.0,
    "change_intensity": 0.064
  },
  "source": "torch_hierarchical_graph"
}
```

Keep `future_area_and_key_indicators` for compatibility, but derive it from the
decoded latent state rather than treating it as the source of truth.

### 2. Target Extraction

Replace the scalar-only target path with a reusable latent-vector extractor in
`neural_dynamics.py`.

The extractor should build a stable, sorted vector from:

- `observed_next.total_area_m2`
- `observed_next.total_feature_count`
- `observed_next.land_space_types.<type>.area_m2`
- `observed_next.land_space_types.<type>.feature_count`
- `observed_next.land_space_types.<type>.area_delta_m2`
- `delta.total_area_delta_m2`
- `delta.total_abs_area_delta_m2`
- `delta.by_land_type.<type>.area_delta_m2` when present

Dimension names must be deterministic across training and prediction. Missing
dimensions decode as `0.0`.

### 3. Neural Head Contract

MLP, hierarchical graph, and spatiotemporal transformer candidate backends should
output:

- a latent vector with width equal to the training target dimensions
- the existing scalar heads:
  - `constraint_violation_probability`
  - `planning_utility_delta`
  - `uncertainty.confidence`
  - `calibration.calibrated_utility_delta`
  - `action_mask.allowed`

The old area scalar head should be removed as the definition of
`future_latent_state`. If an area value is still needed by compatibility
consumers, it must come from `decoded_state.total_area_m2`.

The architecture report should list:

- `future_latent_state.latent_vector`
- `future_latent_state.decoded_state`
- `future_latent_state.transition_delta`

It must not describe `future_latent_state.area_total` as the latent head.

### 4. Decoder

Add a deterministic decoder:

- Input: `dimension_names` and predicted normalized/denormalized latent values.
- Output: `decoded_state`, `transition_delta`, and compatibility indicators.
- Clamp counts and areas to non-negative values where the semantic quantity
  cannot be negative.
- Preserve signed delta dimensions.

The decoder is deliberately simple. The innovation in this increment is the
state-head contract and evaluation, not a black-box geometry generator.

### 5. Evaluation

Update `_latent_transition_error()` to evaluate v2 latents by multiple metrics:

- `total_area_error`
- `land_type_area_mae`
- `land_type_feature_count_mae`
- `delta_mae`
- `latent_vector_mae`

The function may keep a scalar return for existing gates, but the evaluation
report must expose the component metrics under
`target_head_metrics.future_latent_state.components`.

The scalar `mean_transition_error` should aggregate the component errors instead
of short-circuiting on total area.

### 6. Claim Boundary

After implementation, allowed wording is:

> TWM predicts an action-conditioned multi-dimensional hierarchical future-state
> latent, decoded into area, feature-count, land-space-type and transition-delta
> summaries.

Disallowed wording remains:

- full future parcel geometry generation
- production-ready territorial simulator
- ungated causal planning model
- national-scale readiness

## Testing Plan

Follow TDD.

1. Add a unit test for `_prediction_from_outputs()` or the new decoder:
   - input includes multiple land-space-type dimensions
   - output schema is `territory_world_model.predicted_latent_state.v2`
   - output has `latent_vector`, `decoded_state`, and `transition_delta`
   - compatibility indicators are derived from decoded state

2. Add a neural training contract test:
   - train on a small fixture with two land-space types
   - learned architecture heads include v2 latent vector/decoded state
   - learned architecture heads do not include `future_latent_state.area_total`
   - prediction includes v2 latent output

3. Add an evaluation test:
   - construct a prediction where total area matches but land-type allocation is
     wrong
   - `_latent_transition_error()` / dynamics evaluation must report non-zero
     land-type or latent-vector error
   - this prevents the previous false pass caused by total-area-only scoring

4. Run focused tests:
   - `python -m pytest data_agent/test_territory_world_model.py -k "latent or neural_dynamics" -q`
   - expand to affected TWM tests if focused tests pass.

## Migration / Compatibility

- No database migration is required.
- Existing v1 predictions remain readable.
- Forecast consumers should prefer v2 `decoded_state` when available and fall
  back to v1 `projected` / `observed_next` only for old reports.
- Reports should retain `future_area_and_key_indicators` for UI compatibility.

## Implementation Order

1. Add failing tests for decoder/prediction contract.
2. Implement latent vector target extraction and decoder.
3. Update MLP output width and prediction builder.
4. Update graph and transformer candidate output width.
5. Add failing evaluation test for total-area false pass.
6. Update service evaluation metrics.
7. Update claim text and architecture limitations where they currently call
   `future_latent_state` a compatibility alias.
8. Run focused tests and update documentation if output field names changed.

## Risks

- Small fixtures can overfit. Tests should assert contract and metric behavior,
  not production-quality accuracy.
- Dimension explosion is possible if arbitrary land-space labels are used.
  Restrict dimensions to deterministic observed labels in the training dataset.
- Existing UI payload rendering may assume v1 fields. Preserve compatibility
  fields until the UI is explicitly upgraded.

## Implementation Decision

Use the existing observed land-space labels from the training dataset as the
dimension vocabulary for the first implementation. Do not introduce a global
land-class registry in this increment.
