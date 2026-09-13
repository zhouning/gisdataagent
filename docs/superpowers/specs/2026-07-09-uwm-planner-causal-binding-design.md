# UWM Planner-Level Causal Binding Design

Date: 2026-07-09

## Objective

Strengthen the UWM livability world-model planner so causal-question contracts are enforced during planner search and replay generation, not only attached to the final decision package. The implementation must keep the current full-admin real-data scope and must not upgrade simulator replay evidence into observed policy-outcome superiority.

The target system remains:

```text
renderer -> Graph-MDP state -> simulator rollout -> planner search -> evidence gate
```

This change adds a claim-safety layer at the planner-report level:

```text
spatial causal question registry -> action candidates -> replay transitions -> best/static sequences -> report gates
```

## Current Context

The current UWM full-admin decision package already aggregates real local full-admin evidence:

- 1017 graph nodes;
- 7932 graph edges;
- 1137 feasible actions;
- 6817 simulator-grounded transitions;
- 5085 geographic-similarity edges;
- full-admin service surface from 1,194,351 local POI points and 50,366 roads.

The final decision package already attaches spatial causal contracts to the final recommended actions. The gap is lower in the stack: `plan_with_model_based_graph_search` currently emits candidate actions, replay transitions, best sequence, and static baseline actions without requiring or summarizing causal-question binding. This means a downstream report can be claim-safe while the planner trace itself is not fully auditable.

## Scope

Implement planner-level causal binding for `data_agent.uwm.model_based_rl.plan_with_model_based_graph_search`.

In scope:

- Accept an optional `spatial_causal_question_registry` argument.
- Bind all Graph-MDP `available_actions` before search.
- Store bound action records in replay transitions.
- Store bound action records in `best_sequence.action_sequence`.
- Store bound action records in `static_single_step_baseline.action_sequence`.
- Add a planner-level `spatial_causal_contract_binding` summary.
- Add hard claim downgrade behavior when registry binding is missing or unsafe.
- Update full-admin planner replay builder to pass the registry artifact.
- Add focused tests for 36-node data-calibrated replay and 1017-node full-admin replay.
- Regenerate affected UWM artifacts after tests pass.

Out of scope:

- No new synthetic data.
- No smoke-only shortcut.
- No observed policy outcome superiority claim.
- No production governance binding unless the five authoritative governance tables are actually present and accepted.
- No frontend drilldown in this implementation slice.
- No new action family or diffusion/action-sequence generator in this slice.

## Data And Claim Constraints

The implementation must preserve these current claim boundaries:

- `observed_policy_outcome_superiority_claim = false`
- `empirical_superiority_claim = false`
- `policy_outcome_claim_allowed = false` for current bound actions
- current maximum system claim remains `bounded_support`

If causal binding is absent or invalid, planner output must still be inspectable but must not support a planner advantage claim. In that case:

- `spatial_causal_contract_binding.binding_ready = false`
- `claim_boundary.max_claim_level = not_for_claim`
- `supported_claim = no_model_based_graph_search_advantage_claim_supported`
- `spatial_causal_question_registry_binding_required` appears in `remaining_gates`

## Architecture

### Shared Binding Helper

Reuse `data_agent.uwm.spatial_causal_action_binding`:

- `causal_contracts_by_action_type`
- `action_with_spatial_causal_contract`
- `spatial_causal_action_binding_summary`

No duplicate causal-binding logic should be added to `model_based_rl.py`.

### Planner Input

Extend `plan_with_model_based_graph_search`:

```python
def plan_with_model_based_graph_search(
    observation: dict[str, Any],
    *,
    action_types: list[str],
    scenario: dict[str, Any],
    ...
    spatial_causal_question_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

The function will build the Graph-MDP state as it does today, then replace `graph_state["available_actions"]` with causally enriched records. The `action_mask_trace` should remain about mask derivation, but the action records used for search and replay must include causal fields.

### Search And Replay

Every action record emitted by the planner must include, when registry binding is ready:

- `causal_question_id`
- `causal_query`
- `primary_outcome`
- `identification_status`
- `allowed_current_query_level`
- `causal_blocked_reason`
- `required_authoritative_tables`
- `policy_outcome_claim_allowed`
- `causal_claim_level`
- `observed_policy_outcome_superiority_claim`
- `empirical_superiority_claim`

Replay transitions must store the enriched action:

```text
trajectory_dataset.transitions[*].action
```

Best and static sequences must also store enriched actions:

```text
best_sequence.action_sequence[*]
static_single_step_baseline.action_sequence[*]
```

### Planner-Level Binding Summary

Add this top-level report section:

```text
spatial_causal_contract_binding
```

It should summarize all candidate actions, not only the selected sequence:

- registry readiness;
- validation errors;
- active action types;
- feasible action count;
- attached action count;
- missing contract action count;
- action type counts;
- underidentified policy-effect action count;
- identified policy-effect action count;
- policy-outcome-claim-allowed action count;
- required authoritative tables.

For the current full-admin artifact, expected values are:

- feasible action count: 1137;
- attached action count: 1137;
- missing contract action count: 0;
- underidentified policy-effect action count: 1137;
- identified policy-effect action count: 0;
- policy-outcome-claim-allowed action count: 0.

### Claim Gate

Planner supported claim should require all existing conditions plus:

```text
spatial_causal_contract_binding.binding_ready == true
```

If advantage is positive but binding is not ready, the report must not emit a planner advantage claim. This is intentional: a planner that cannot trace its causal question boundary should not contribute to UWM final superiority claims.

## Artifact Generation

Update `scripts/build_uwm_full_admin_graph_planner_replay.py` to read:

```text
data/uwm_public_proxy/chongqing_central/spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json
```

Then pass it into `plan_with_model_based_graph_search`.

The regenerated full-admin planner replay must retain:

- 1017 nodes;
- 7932 edges;
- 1137 available actions;
- 6817 transitions;
- positive planner and risk-adjusted advantages;
- false observed policy-outcome and empirical-superiority claims.

## Testing

Use test-first implementation.

Add or update tests to assert:

1. The 36-node data-calibrated planner replay attaches causal fields when given a registry.
2. The full-admin stored planner replay artifact has candidate-level binding summary for all 1137 actions.
3. The first replay transition action has causal fields and `policy_outcome_claim_allowed is False`.
4. Best sequence and static baseline actions have causal fields.
5. Omitting the registry downgrades `supported_claim` to `no_model_based_graph_search_advantage_claim_supported` and adds `spatial_causal_question_registry_binding_required`.
6. Full-admin counts remain real full scope and are not reduced for testing convenience.

Target verification commands:

```bash
uv run pytest data_agent/test_uwm_data_calibrated_planner_replay.py data_agent/test_uwm_full_admin_graph_planner_replay.py
uv run python scripts/build_uwm_full_admin_graph_planner_replay.py
uv run pytest data_agent/test_uwm_full_admin_livability_decision_package.py data_agent/test_uwm_data_foundation_evidence_gate.py
```

If artifact regeneration changes expected numerical results, inspect the diff. Accept only changes explainable by action-record enrichment, not changes to state construction, simulator coefficients, candidate filtering, or reward logic.

## Failure Handling

The planner should fail only on invalid search parameters or no feasible actions, as it does today. Missing causal registry should not crash research replay, but it must make the claim boundary explicit and block planner advantage claims.

Invalid registry should behave the same as missing binding:

- generated report remains inspectable;
- binding summary reports validation errors;
- claim boundary becomes `not_for_claim`;
- remaining gate includes registry binding requirement.

## Acceptance Criteria

This work is complete only when:

- planner search reports are causally auditable at candidate, transition, selected, and static-baseline levels;
- all affected tests pass;
- regenerated full-admin artifacts preserve full-scope data counts;
- final UWM claims remain strictly bounded and do not imply observed policy outcome superiority;
- no smoke-only or reduced-data path is introduced.
