# TWM Optimization Dataset

This directory is an engineering fixture for TWM dynamic projection and
multi-objective scenario comparison.

It is not a production decision output. It organizes the existing test package
into objective definitions, candidate actions, scenario bundles, metrics,
constraint violations, and a Pareto-style summary so the TWM optimization layer
can be developed against a stable contract.

Key files:

- `objective_catalog.csv`
- `action_space.geojson`
- `constraint_masks.geojson`
- `scenario_candidates.csv`
- `scenario_feasibility.csv`
- `scenario_project_membership.csv`
- `scenario_metrics.csv`
- `scenario_constraint_violations.csv`
- `pareto_summary.json`
