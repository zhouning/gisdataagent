# UWM Customer Demand Phase 0 Integration

Date: 2026-07-10

## Source Branches

- Integration branch: `feat/v12-extensible-platform`
- Requirement worktree: `.worktrees/uwm-livability-requirement-split`
- Requirement branch head before integration: `e1ea8c9`
- Mobility-aware UWM head before design commit: `1d5e924`

## Preservation

- Status: `/private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt`
  - SHA-256: `6b12d3a240b1a8b898a33dee4bfd044e79dd01d40602f1b55c6af7f611c6cce7`
- Patch: `/private/tmp/uwm-livability-requirement-split-2026-07-10.patch`
  - SHA-256: `a32454aa569c37aa93316b7cc6e7c5ccece2ee30158936e25c54e8b47f9fe186`
- Source archive: `/private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz`
  - SHA-256: `c38927bbc20c99d2d23c8aacf4328e721f674425db3f044f3024a49f67b917d9`

`/private/tmp` is non-persistent temporary storage. The operating system or a
cleanup process may remove these files without notice. Copy all three
preservation artifacts to durable storage before relying on them for recovery.

## Source Archive Manifest

The source archive contains exactly these eight files:

```text
data_agent/uwm/livability_requirement_registry.py
data_agent/test_uwm_livability_requirement_registry.py
data_agent/test_uwm_ai_demand_readiness_routes.py
data_agent/test_uwm_ai_demand_readiness_frontend_contract.py
frontend/src/components/datapanel/AiDemandReadinessTab.tsx
frontend/src/components/datapanel/LivabilityWorldModelTab.tsx
frontend/src/components/datapanel/TraditionalLivabilityTab.tsx
frontend/src/styles/layout.css
```

The binary-safe patch records all tracked modifications reported by the saved
status, including tracked files not present in the eight-file source archive.
Untracked entries shown in the saved status are not represented by `git diff`
and are not recoverable from the patch. Only the eight files listed above are
recoverable from the source archive.

## Verification Commands

Run these commands before using any preservation artifact:

```bash
printf '%s  %s\n' \
  '6b12d3a240b1a8b898a33dee4bfd044e79dd01d40602f1b55c6af7f611c6cce7' \
  '/private/tmp/uwm-livability-requirement-split-2026-07-10-status.txt' \
  'a32454aa569c37aa93316b7cc6e7c5ccece2ee30158936e25c54e8b47f9fe186' \
  '/private/tmp/uwm-livability-requirement-split-2026-07-10.patch' \
  'c38927bbc20c99d2d23c8aacf4328e721f674425db3f044f3024a49f67b917d9' \
  '/private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz' \
  | shasum -a 256 -c -

tar -tzf /private/tmp/uwm-livability-requirement-split-2026-07-10-files.tar.gz
```

The checksum command must report `OK` for all three artifacts. The archive
listing must match the eight-file manifest exactly.

## Safe Patch Recovery

Do not apply the patch to the integration branch or to the existing dirty
requirement worktree. Recover into a new detached worktree based on the saved
requirement branch head, verify the patch first, and only then apply it:

```bash
recovery_dir=/private/tmp/uwm-livability-requirement-split-recovery

git worktree add --detach "$recovery_dir" e1ea8c9
git -C "$recovery_dir" status --short
git -C "$recovery_dir" apply --check --binary \
  /private/tmp/uwm-livability-requirement-split-2026-07-10.patch
git -C "$recovery_dir" apply --binary \
  /private/tmp/uwm-livability-requirement-split-2026-07-10.patch
git -C "$recovery_dir" status --short
```

The first status command must be empty. Stop without applying if checksum
verification or `git apply --check` fails. These commands are recovery
instructions only; no recovery was performed while preparing this report.

## Integration Rule

The requirement branch is implementation input, not a blind merge. The
canonical registry follows the confirmed one-primary-route design and retains
the mobility-aware UWM exports already present on the integration branch.

## Phase 0 Verification

Verification was run from `/Users/zhouning/gisdataagent` on 2026-07-10 at
integration head `11b550e2ad42bb1bc82b11d68a8e8571f9456411`.

### Backend Regression Set

Command:

```bash
PYTHONPATH=. .venv/bin/pytest \
  data_agent/test_uwm_livability_requirement_registry.py \
  data_agent/test_uwm_ai_demand_readiness_routes.py \
  data_agent/test_uwm_ai_demand_readiness_frontend_contract.py \
  data_agent/test_uwm_traditional_livability_analysis.py \
  data_agent/test_uwm_livability_decision_routes.py \
  data_agent/test_uwm_full_admin_mobility_graph.py \
  data_agent/test_uwm_model_based_rl.py \
  data_agent/test_uwm_core_action_conditioned_dynamics_benchmark.py \
  data_agent/test_uwm_core_world_model_policy_improvement_benchmark.py -q
```

Actual result:

```text
.................................................                        [100%]
49 passed in 55.93s
```

Exit code: `0`.

### Frontend Production Build

Command:

```bash
cd frontend && npm run build
```

Actual result:

```text
> gis-data-agent-frontend@1.0.0 build
> tsc -b && vite build

vite v6.4.1 building for production...
✓ 4104 modules transformed.
dist/index.html                           0.96 kB │ gzip:     0.53 kB
dist/assets/spritesheet-DpIxuf5L.svg      5.55 kB │ gzip:     1.67 kB
dist/assets/index-DWaK5A76.css          263.95 kB │ gzip:    43.10 kB
dist/assets/geojson-DPlpFmCu.js          53.01 kB │ gzip:    14.23 kB
dist/assets/maplibre-gl-BJp5ln2T.js   1,024.80 kB │ gzip:   277.43 kB
dist/assets/index-D7YAZvrR.js         4,192.69 kB │ gzip: 1,247.50 kB
✓ built in 4.89s
```

Exit code: `0`. Vite also emitted two non-blocking warnings: the existing
`@loaders.gl/worker-utils` browser-external `spawn` warning and the existing
post-minification chunk-size warning for chunks larger than 500 kB.

### Runtime Registry Invariants

Command:

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
from collections import Counter
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
    validate_livability_requirement_registry,
)
registry = build_livability_requirement_registry()
rows = registry["livability_scenarios"] + registry["customer_ai_demands"]
print(validate_livability_requirement_registry(registry))
print("row_count", len(rows))
print("route_counts", dict(Counter(row["primary_route"] for row in rows)))
print("production_complete_count", sum(
    row["implementation_level"] == "production_complete" for row in rows
))
PY
```

Actual result:

```text
{'valid': True, 'errors': []}
row_count 30
route_counts {'traditional_livability': 13, 'uwm_livability': 4, 'planning_land': 4, 'infrastructure_assets': 4, 'population_demand': 1, 'economy_investment': 2, 'impact_implementation': 2}
production_complete_count 0
```

Exit code: `0`. The seven route counts sum to `30`; every registered scenario
or demand has one primary route. The zero production-complete count is an
intentional readiness result and prevents the Phase 0 ownership registry and
UI from being represented as completed business capability.

### Repository Checks Before Report Update

Commands:

```bash
git diff --check
git status --short
```

Actual results:

- `git diff --check` produced no output and exited `0`.
- `git status --short` exited `0` and produced 91 entries: 6 tracked modified
  entries and 85 untracked entries already present in the shared integration
  worktree.
- The report itself was clean before this Task 6 update.
- No existing dirty entry, the preserved requirement worktree, or any business
  code was modified by Task 6.

The exact status output captured before this report update is stored at
`/private/tmp/phase0-task6-git-status-before.txt`. This path is temporary and
is recorded only as execution evidence, not as a durable project artifact.

## Remaining Phase 1–4 Work

## Phase 0 Final Review Fix Verification

Final-review fixes were verified on 2026-07-10 after adding fail-closed
canonical validation, per-requirement evidence boundaries, stable public source
document identifiers, explicit product-route availability wording, and route
authentication regression coverage.

Backend command: the same Phase 0 regression set documented above. Actual
result: `53 passed in 54.44s`, exit code `0`.

Frontend command: `cd frontend && npm run build`. Actual result: `4104 modules
transformed`, `built in 4.93s`, exit code `0`. The existing loaders.gl `spawn`
and chunk-size warnings remained non-blocking.

Runtime registry validation returned `{'valid': True, 'errors': []}` for 30
rows. Evidence counts were `contract_only=29` and `unsupported=1`; all 30 rows
remain `not_assessed` for uncertainty until implementation evidence is added.
Maximum claim counts were `requirement_registered=29` and `unsupported=1`.
Public source documents are stable filenames only, while
`source_provenance_server_side=true` keeps machine paths out of the API.
`production_complete_count` remains `0`.

`git diff --check` produced no output and exited `0` before the final commit.

Phase 0 establishes ownership, API exposure, UI visibility and claim
boundaries. It does not mark any requirement as production complete.

### Phase 1: Traditional Livability Completion

- Implement S1, S4, S6 and S7 from curated, traceable data and rules.
- Implement demand 8 network accessibility, demand 12 facility
  inventory/capacity/service gaps and demand 21 public-service coverage.
- Implement the supported observed or proxy portions of demands 9, 10, 13, 14
  and 16.
- Define an explicit demand 15 community-text input contract when source text
  is absent.
- Require actual candidate filtering and network/location-allocation analysis
  for S7; missing LIV standards or customer fields remain blockers.

### Phase 2: UWM Livability Completion

- Implement S2 with canonical parcel/facility actions and counterfactual
  transitions.
- Implement demand 7 forecast, target-state gap and intervention planning.
- Deepen demand 11 environmental hybrid dynamics and implement demand 19
  disturbance, recovery and robust planning.
- Begin shared Geospatial World Model Kernel contracts and UWM adapters.
- Distinguish deterministic, simulated and observed transitions and retain
  static, no-action and action-ablation planner baselines.

### Phase 3: Non-Livability Capabilities

- Implement planning and land demands 1, 2 and 3, followed by population
  demand 6.
- Implement observed-data portions of infrastructure and asset demands 4 and
  5.
- Add readiness and data contracts for demands 17, 18, 20, 22 and 23.
- Add tabs only for coherent reusable workflows; authoritative, proxy and
  missing data must remain explicit.

### Phase 4: Impact and Implementation Orchestration

- Implement demands 24 and 25 after their domain outputs exist.
- Aggregate cross-domain dependencies, costs, benefits, risks and evidence.
- Produce prioritization and roadmaps with human-review gates.
- Reduce result grades when finance, planning or infrastructure evidence is
  missing; derive implementation order from explicit dependencies and
  constraints.
