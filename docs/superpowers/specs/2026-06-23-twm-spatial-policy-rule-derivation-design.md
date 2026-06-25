# TWM Spatial Policy Rule Derivation Design

- **Date**: 2026-06-23
- **Scope**: Phase 6 narrow slice for the Territorial World Model roadmap
- **Strategy**: `to_spatial_policy_rule`
- **Status**: Approved for implementation by the user's "continue TWM development" request

## Goal

Add a conservative standards-platform derivation strategy that turns spatial-policy-like `std_data_element` rows into disabled, review-required `twm_policy_rule` candidates.

This closes the current gap between standard contracts and TWM policy-rule authoring without changing TWM rule execution behavior.

## Non-Goals

- No automatic approval or enabling of generated rules.
- No UI for reviewing generated rules.
- No change to `RuleEvaluator` semantics.
- No attempt to infer legal conclusions from ordinary data-quality fields.

## Inputs

The strategy reads one `std_document_version`, its parent `std_document`, and bound `std_data_element` rows.

Only elements with both `bound_table` and `bound_column` are considered. A row is a spatial-policy candidate only when it is explicitly spatial or carries a known TWM policy role signal, such as permanent basic farmland, ecological redline, urban boundary, planning zone, boundary, or geometry.

Normal fields such as `dlbm` must not create policy rules.

## Outputs

For each candidate element, the strategy creates:

1. One `twm_rule_set` for the source standard version if it does not already exist.
2. One new `twm_policy_rule` row with `enabled=false`, `review_policy='review_required'`, and category `standard_derived_spatial_policy`.
3. One `std_derived_link` row with `target_kind='spatial_policy_rule'`, `target_table='twm_policy_rule'`, and strategy `to_spatial_policy_rule`.

Generated rules are audit candidates. They are intentionally disabled until a reviewer approves and enables them.

## Rule Body Contract

Generated `rule_body` must pass the current TWM DSL validator:

```json
{
  "version": "1.0",
  "subject": {"object_type": "project"},
  "constraint": {
    "target_role": "pbf",
    "spatial_predicate": "intersects",
    "min_overlap_area_m2": 1
  },
  "hit_when": {
    "overlap_area_m2": {"gt": 1}
  },
  "evidence": {
    "required": ["source_feature", "rule_clause", "spatial_calc"]
  },
  "review": {"policy": "review_required"},
  "metadata": {
    "derived_from": "std_data_element"
  }
}
```

The target role is selected by a small deterministic heuristic. PBF and redline-like targets get `severity='high'`; less direct geometry or boundary candidates get `severity='medium'`.

## Stale Semantics

The strategy preserves history. A re-derive creates new `twm_policy_rule` rows, marks prior active `std_derived_link` rows for the same document and strategy stale, and updates old rule metadata with `derived_status='stale'`.

This matches TWM's audit requirement and avoids deleting earlier generated interpretations.

## Schema Change

The existing `std_derived_link.target_kind` CHECK constraint must admit `spatial_policy_rule`. This is a strict superset migration and does not alter existing link rows.

## Tests

The implementation is accepted when targeted tests verify:

- the derivation runner lists `to_spatial_policy_rule` as active;
- a spatial candidate produces one draft rule set, one disabled policy rule, and one active derived link;
- a non-spatial bound field produces no rule;
- a re-run stales the previous active link while preserving historical `twm_policy_rule` rows.
