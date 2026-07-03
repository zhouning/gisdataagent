# TWM Rule Fixture Coverage Matrix Design

## Context

The pilot readiness matrix already shows that policy rules need positive, negative and boundary fixtures before real authoritative data arrives. The next useful slice is an executable diagnostic that inspects existing demo/test data and reports which hard-constraint rule codes have enough regression fixtures.

## Scope

Add a service report, REST endpoint and ADK tool for `territory_world_model.rule_fixture_coverage_matrix.v1`.

The report covers hard spatial policy rules:

- `TWM-FARM-001`
- `TWM-ECO-001`
- `TWM-PLAN-001`
- `TWM-URBAN-001`

Each rule reports three fixture categories:

- `positive_violation`: a fixture where the rule is hit or requires review.
- `negative_pass`: a fixture where the rule passes.
- `boundary_case`: a touching, threshold, near-zero, same-boundary or review-threshold fixture.

## Data Sources

The first version uses existing repository fixtures only:

- `data_agent/test_data/twm_bishan_demo/tables/rule_evaluation.csv`
- `data_agent/test_data/twm_bishan_demo/optimization/scenario_constraint_violations.csv`
- `data_agent/test_data/twm_bishan_demo/standard_rules.lifecycle.json`

Synthetic and demo data can improve regression coverage only. It must not satisfy the production gate or be described as authoritative validation.

## Output Semantics

The report has overall status:

- `pass`: all required rules have all three categories.
- `action_required`: at least one rule misses a required fixture category.
- `blocked`: the rule catalog or source fixture files are unavailable.

Each rule contains evidence counts, missing categories, source file references and `test_data_work` actions. The report also includes a strict policy block stating that synthetic fixtures cannot satisfy production acceptance.

## Testing

Add tests for:

- service report schema, covered hard rules and missing boundary categories;
- route JSON response;
- ADK tool JSON response.

