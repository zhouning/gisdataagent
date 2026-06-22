# TWM dynamics_backend_report cache verification

- Generated at: `2026-06-22T08:04:45Z`
- Auth: `POST /login` as `admin`, cookie received: `True`
- Requests: `6`, OK: `6`, Failed: `0`
- Mock used: `False`
- Smoke test used: `False`
- Data source: `data_agent/test_data/twm_bishan_multi_admin_eval`
- Project ID: `6b18dd88-de28-46f0-a876-b8c2e339a7c2`
- State ID: `faa0571b-adcb-484a-8041-e99d19d4a3b9`
- Performance: `{"first_ms": 61326.1, "second_ms": 2.4, "speedup_ratio": 25552.542, "first_under_previous_timeout_45s": false, "second_under_10s": true}`

## Failures

- None

## Records

| Name | Status | OK | ms | Summary |
| --- | --- | --- | --- | --- |
| `auth.login_admin_password` | `200` | `True` | `128.2` | `{}` |
| `multi_admin.create_project` | `200` | `True` | `3.6` | `{"status": "draft"}` |
| `multi_admin.build_state` | `200` | `True` | `80936.8` | `{"state_version": {"id": "faa0571b-adcb-484a-8041-e99d19d4a3b9", "object_count": 22531, "relation_count": 43329, "build_status": "ready"}}` |
| `multi_admin.evaluate_rules` | `200` | `True` | `107851.1` | `{"summary": {"state_version_id": "faa0571b-adcb-484a-8041-e99d19d4a3b9", "rule_count": 7, "hit_count": 140, "review_task_count": 139, "data_quality_hit_count": 1, "approval_consistency_hit_count": 56, "evidence_item_count": 556}, "state_version_id": "faa057...` |
| `multi_admin.dynamics_backend_report.first` | `200` | `True` | `61326.1` | `{"schema": "territory_world_model.dynamics_backend_report.v1", "status": "blocked", "project_id": "6b18dd88-de28-46f0-a876-b8c2e339a7c2", "state_version_id": "faa0571b-adcb-484a-8041-e99d19d4a3b9", "evidence_gate": {"status": "blocked", "missing": ["readine...` |
| `multi_admin.dynamics_backend_report.second` | `200` | `True` | `2.4` | `{"schema": "territory_world_model.dynamics_backend_report.v1", "status": "blocked", "project_id": "6b18dd88-de28-46f0-a876-b8c2e339a7c2", "state_version_id": "faa0571b-adcb-484a-8041-e99d19d4a3b9", "evidence_gate": {"status": "blocked", "missing": ["readine...` |
