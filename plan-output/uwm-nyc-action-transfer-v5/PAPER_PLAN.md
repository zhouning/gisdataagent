# Paper Experimenter Plan Adapter

Canonical plan: `plans/paper-plan/paper_plan.md`

Canonical plan SHA-256:
`acd6ff8d9b8e8fccff7d3562f410b332334eb5e507427d189e8312cce1a7e742`

This adapter resolves the upstream AI Urban Scientist path mismatch:
`paper-planner` writes `plans/paper-plan/paper_plan.md`, while
`paper-experimenter` requires `plan-output/<name>/PAPER_PLAN.md`.

Read and execute the canonical plan. Stop if its current SHA-256 differs from
the value above. This plan consumes only the already admitted V5 NYC benchmark.
