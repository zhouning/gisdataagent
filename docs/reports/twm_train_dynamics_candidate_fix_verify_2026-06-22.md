# TWM train-dynamics-candidate fix verification

- Generated at: `2026-06-22T07:27:12Z`
- Base URL: `http://localhost:8000`
- Auth: `POST /login` as `admin`, cookie received: `True`
- Requests: `10`, OK: `10`, Failed: `0`
- Mock used: `False`
- Smoke test used: `False`

## Results

### bishan_demo

- Project ID: `d1eb03bf-a55e-4f49-b7ed-bff14178a431`
- State ID: `c1580a0d-21b0-4a91-8a69-b9bb9cca7968`
- Build: `{"state_version": {"id": "c1580a0d-21b0-4a91-8a69-b9bb9cca7968", "object_count": 5745, "relation_count": 10349, "build_status": "ready"}}`
- Train: `{"schema": "territory_world_model.train_dynamics_report.v1", "status": "blocked", "project_id": "d1eb03bf-a55e-4f49-b7ed-bff14178a431", "state_version_id": "c1580a0d-21b0-4a91-8a69-b9bb9cca7968", "evidence_gate": {"status": "blocked", "missing": ["readiness_pass", "backend_report", "non_scaffold_trainer"], "claim_scope": "trainer_blocked"}, "recommendations": ["improve observed temporal and usable examples before training a dynamics candidate", "ensure trained predictions pass dynamics_backend_report before forecast consumption", "replace scaffold trainer with a real neural/statistical optimizer before claiming trainable TWM dynamics"]}`

### bishan_multi_admin

- Project ID: `0b71f56b-2dcb-49ac-afdb-2d4195bdd9e7`
- State ID: `f10d9012-f979-475d-976b-908236f84372`
- Build: `{"state_version": {"id": "f10d9012-f979-475d-976b-908236f84372", "object_count": 22531, "relation_count": 43329, "build_status": "ready"}}`
- Train: `{"schema": "territory_world_model.train_dynamics_report.v1", "status": "blocked", "project_id": "0b71f56b-2dcb-49ac-afdb-2d4195bdd9e7", "state_version_id": "f10d9012-f979-475d-976b-908236f84372", "evidence_gate": {"status": "blocked", "missing": ["readiness_pass", "backend_report", "non_scaffold_trainer"], "claim_scope": "trainer_blocked"}, "recommendations": ["improve observed temporal and usable examples before training a dynamics candidate", "ensure trained predictions pass dynamics_backend_report before forecast consumption", "replace scaffold trainer with a real neural/statistical optimizer before claiming trainable TWM dynamics"]}`

### one_map_village

- Project ID: `b14e07dd-3654-492b-b741-0bd9998a2cc7`
- State ID: `9b008b36-14df-444c-9ef2-500e27583493`
- Build: `{"state_version": {"id": "9b008b36-14df-444c-9ef2-500e27583493", "object_count": 5494, "relation_count": 2632, "build_status": "ready"}}`
- Train: `{"schema": "territory_world_model.train_dynamics_report.v1", "status": "blocked", "project_id": "b14e07dd-3654-492b-b741-0bd9998a2cc7", "state_version_id": "9b008b36-14df-444c-9ef2-500e27583493", "evidence_gate": {"status": "blocked", "missing": ["readiness_pass", "backend_report", "non_scaffold_trainer"], "claim_scope": "trainer_blocked"}, "recommendations": ["improve observed temporal and usable examples before training a dynamics candidate", "ensure trained predictions pass dynamics_backend_report before forecast consumption", "replace scaffold trainer with a real neural/statistical optimizer before claiming trainable TWM dynamics"]}`

## Failures

- None

## Records

| Name | Status | OK | ms | Summary |
| --- | --- | --- | --- | --- |
| `auth.login_admin_password` | `200` | `True` | `141.1` | `{}` |
| `bishan_demo.create_project` | `200` | `True` | `4.0` | `{"status": "draft"}` |
| `bishan_demo.build_state` | `200` | `True` | `16301.0` | `{"state_version": {"id": "c1580a0d-21b0-4a91-8a69-b9bb9cca7968", "object_count": 5745, "relation_count": 10349, "build_status": "ready"}}` |
| `bishan_demo.train_dynamics_candidate` | `200` | `True` | `5633.5` | `{"schema": "territory_world_model.train_dynamics_report.v1", "status": "blocked", "project_id": "d1eb03bf-a55e-4f49-b7ed-bff14178a431", "state_version_id": "c1580a0d-21b0-4a91-8a69-b9bb9cca7968", "evidence_gate": {"status": "blocked", "missing": ["readiness...` |
| `bishan_multi_admin.create_project` | `200` | `True` | `3.2` | `{"status": "draft"}` |
| `bishan_multi_admin.build_state` | `200` | `True` | `84164.7` | `{"state_version": {"id": "f10d9012-f979-475d-976b-908236f84372", "object_count": 22531, "relation_count": 43329, "build_status": "ready"}}` |
| `bishan_multi_admin.train_dynamics_candidate` | `200` | `True` | `19201.8` | `{"schema": "territory_world_model.train_dynamics_report.v1", "status": "blocked", "project_id": "0b71f56b-2dcb-49ac-afdb-2d4195bdd9e7", "state_version_id": "f10d9012-f979-475d-976b-908236f84372", "evidence_gate": {"status": "blocked", "missing": ["readiness...` |
| `one_map_village.create_project` | `200` | `True` | `5.7` | `{"status": "draft"}` |
| `one_map_village.build_state` | `200` | `True` | `8686.9` | `{"state_version": {"id": "9b008b36-14df-444c-9ef2-500e27583493", "object_count": 5494, "relation_count": 2632, "build_status": "ready"}}` |
| `one_map_village.train_dynamics_candidate` | `200` | `True` | `3714.0` | `{"schema": "territory_world_model.train_dynamics_report.v1", "status": "blocked", "project_id": "b14e07dd-3654-492b-b741-0bd9998a2cc7", "state_version_id": "9b008b36-14df-444c-9ef2-500e27583493", "evidence_gate": {"status": "blocked", "missing": ["readiness...` |
