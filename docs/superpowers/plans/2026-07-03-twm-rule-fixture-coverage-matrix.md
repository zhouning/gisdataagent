# TWM Rule Fixture Coverage Matrix Plan

1. Add RED tests in `data_agent/test_territory_world_model.py` for the service, route and tool.
2. Add `TerritoryWorldModelService.rule_fixture_coverage_matrix_report()` using existing CSV/JSON fixture files.
3. Add `GET /api/twm/rule-fixture-coverage-matrix`.
4. Add `twm_rule_fixture_coverage_matrix()` to the ADK toolset and register it.
5. Run focused TWM tests and compile checks.

