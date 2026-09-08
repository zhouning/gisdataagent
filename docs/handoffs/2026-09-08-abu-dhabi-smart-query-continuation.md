# Abu Dhabi Smart Query Continuation Handoff

**Recorded:** 2026-09-08

**Scope:** Continue productizing governed NL2Semantic2SQL for the Makani and
Liveability virtual sources. The immediate next activity is to evaluate a
local LLM without weakening the semantic, execution, or benchmark controls.

## Start Here

- Repository: `/Users/zhouning/gisdataagent`
- Working branch: `feat/abu-dhabi-nl2semantic2sql-productization`
- Remote: `origin/feat/abu-dhabi-nl2semantic2sql-productization`
- Last pushed commit: `d7e1c5c6 fix(nl2sql): deliver governed liveability map results`
- Do **not** reset, clean, stash, or bulk-commit the worktree. It contains a
  large number of modified and untracked files belonging to other work.
- The only commit made in this window contains the reviewed Liveability
  NL2Semantic2SQL/map delivery changes. It is synchronized with `origin`.

## Product Goal and Non-Negotiable Boundaries

The target is a productized, governed ability to answer arbitrary supported
questions over both business databases, with unified metadata, a shared Abu
Dhabi DMT ontology plus source overlays, reviewed semantic configuration,
safe read-only execution, evidence, and flexible tabular/chart/map results.

It is not acceptable to obtain a score by adding question IDs, benchmark Gold
SQL, expected result rows, or prompt fragments that target particular
benchmark questions to the runtime path. A reviewed metric contract is allowed
only when it is a reusable semantic asset with a business definition,
scope/row-policy, bindings, fingerprint checks, and ordinary runtime routing.
Such deterministic contract hits must be reported separately from model-route
accuracy.

Do not claim all-database arbitrary-question coverage or 100% end-to-end
accuracy until a frozen, independently reproducible benchmark proves the
relevant layer: asset selection, SQL/IR validity, execution, result
equivalence, and presentation/map correctness.

The product flow and current governance position are recorded in
`docs/nl2semantic2sql_product_workflow.md`. Read it before changing query
logic, semantics, ontology, benchmark, or UI navigation.

## Current Runtime State

At handoff time both services are running locally:

- Backend/Chainlit: `http://127.0.0.1:8000` (PID 90104)
- Frontend: `http://127.0.0.1:5173` (PID 48257)

The frontend was pre-existing. Do not kill either process merely to restart a
test. If a restart is necessary, use the project launcher:

```bash
cd /Users/zhouning/gisdataagent
scripts/run_abu_dhabi_liveability_demo.sh --port 8000
```

The launcher loads local operator/source secret files itself. Never copy API
keys, database credentials, or source DSNs into source-controlled documents,
scripts, benchmark artifacts, or commits.

## Latest Delivered End-to-End Capability

The following prompt was verified in the real browser against the registered,
read-only Liveability source:

```text
@Liveability 在地图上按行政区展示宜居设施数量，并按数量分级设色
```

Observed outcome:

1. Routing resolves the reviewed reusable metric contract
   `LIVEABILITY_FACILITY_COUNT_BY_DISTRICT_V5`.
2. The governed source query returns 99 district metric rows.
3. The presentation layer obtains bounded, server-side district geometries,
   verifies the metric-result fingerprint, and publishes 99 GeoJSON polygons
   as a `choropleth` map layer.
4. The chat message is updated in place with the final answer. It does not
   remain stuck on the intermediate `正在规划` state.
5. The map title is semantic/localized:
   `按宜居行政区分级设色的宜居设施数量`; it is not a raw contract identifier.

This is a reviewed semantic-contract path (`llm_invoked=false`), deliberately
separate from free-form local-model evaluation. It proves source execution and
map delivery, not general LLM accuracy.

Implementation files in `d7e1c5c6`:

- `data_agent/abu_dhabi_nl2sql_map_presentation.py`: governed result-to-map
  handoff, semantic labels, fingerprint check, and bounded geometry retrieval.
- `data_agent/governed_virtual_nl2sql.py`: applies reviewed row scopes to
  canonical/direct metric SQL and classifies registered-source outages.
- `data_agent/liveability_nl2sql.py`: distinguishes source unavailability
  from semantic/execution rejection.
- `data_agent/app.py`: separates map payload delivery from Chainlit message
  metadata and updates progress in place.
- `frontend/src/components/MapPanel.tsx`: preserves localized business labels
  in non-English UI.

## Validation Evidence

Completed for the pushed commit:

- Targeted backend regression suite: `327 passed`.
- `frontend`: `npm run build` passed.
- TCP connectivity to the real business source `10.255.254.109:5444` passed.
- Browser E2E passed: final response and `99 行` visible, map legend visible,
  99 Leaflet SVG polygon paths present, and no lingering planning message.

Useful follow-up checks:

```bash
cd /Users/zhouning/gisdataagent
.venv/bin/python -m pytest \
  data_agent/test_abu_dhabi_nl2sql_map_presentation.py \
  data_agent/test_governed_virtual_nl2sql.py \
  data_agent/test_liveability_nl2sql.py
cd frontend && npm run build
node tests/e2e/abu_dhabi_liveability_choropleth_real_e2e.js
```

The successful final browser screenshot is
`/tmp/liveability_map_e2e_final_20260908.png` while the current machine
session remains available.

## Current Semantic and Benchmark Assets

The runtime uses the current artifacts resolved through the artifact registry;
do not replace them by manually copying an older JSON file into the live path.

- Liveability current semantic artifact version observed in real execution:
  `abu-dhabi-liveability_data_20260730-v37-park-answerability-match-20260905`.
- Liveability benchmark and historical evaluation artifacts:
  `docs/customer/abu_dhabi_liveability_site_validation/`.
- Makani current v8 semantic/table-card artifacts and benchmarks:
  `docs/customer/abu_dhabi_liveability_site_validation/`.
- Canonical Makani manual test workbook:
  `docs/customer/abu_dhabi_liveability_site_validation/makani_sync_full_free_form_benchmark_simple_manual_test_v2.xlsx`.
- Product and governance documentation:
  `docs/nl2semantic2sql_architecture.md`,
  `docs/nl2semantic2sql_implementation_guide.md`, and
  `docs/nl2semantic2sql_product_workflow.md`.

When running a benchmark, persist the exact semantic artifact version,
metadata/discovery fingerprint, model/provider configuration, run timestamp,
case population, and failure classes. Historical Gemini reports are valuable
evidence, but they must not be overwritten or treated as evidence for a
different model/provider.

## Local LLM Evaluation Procedure

The architecture supports provider-specific transports; changing model family
does not justify changing the governed semantic/execution pipeline. For a
local OpenAI-compatible server such as Ollama or LM Studio, set its environment
through the operator environment file or the product model configuration, then
restart only the backend process that must inherit the settings.

Example local Ollama profile (use the exact installed model tag; do not commit
this as a secret file):

```dotenv
GDA_LLM_PROVIDER=ollama
GDA_LLM_BASE_URL=http://127.0.0.1:11434/v1
GDA_LLM_MODEL=<installed-model-tag>
GDA_LLM_API_KEY=ollama
GDA_LLM_TIMEOUT_SECONDS=180

# Keep embedding configuration explicit. Re-embedding is required before a
# changed embedding model becomes authoritative for semantic retrieval.
GDA_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
GDA_EMBEDDING_MODEL=<installed-embedding-model-tag>
GDA_EMBEDDING_API_KEY=ollama
GDA_EMBEDDING_DIMENSION=<actual-vector-dimension>
```

LM Studio uses the same contract with provider `lm_studio` and its server URL
(commonly `http://127.0.0.1:1234/v1`). The generic transport implementation is
`data_agent/openai_compatible_llm.py`; it normalizes API bases and supports
`ollama`, `lm_studio`, and `openai_compatible` providers. Provider-specific
prompt packages live under `data_agent/prompts_nl2sql/`.

Before a live benchmark, first prove both chat and embedding endpoints:

```bash
cd /Users/zhouning/gisdataagent
.venv/bin/python scripts/verify_openai_compatible_models.py
```

This checks `/v1/models`, one deterministic chat completion, one embedding
call, and the configured embedding vector dimension. A failed model probe is
infrastructure failure, not an NL2SQL correctness failure.

For local-model evaluation, retain both two routes and report them separately:

1. `baseline_sql`: production default, model proposes SQL within retrieved,
   governed semantic scope and SQL/semantic/row-policy gates validate it.
2. `semantic_ir_experimental`: model produces `AdHocSemanticQueryIR`; the
   deterministic compiler produces SQL only from approved logical bindings.
3. Reviewed direct metric contracts: no LLM invocation; report separately.

For each model run, start with a small, balanced smoke cohort from both
sources, including simple lookup/aggregation, multilingual phrasing,
multi-table relation, spatial presentation, ambiguity/refusal, and data-quality
limitations. Only after failure classification should the full frozen cohort be
run. Improvements must generalize through semantic metadata, ontology mapping,
retrieval, compiler/validator behavior, or display contracts; never through
question-specific runtime branches.

## Outstanding Work, Ordered by Product Risk

1. Establish reproducible, model-specific benchmark runs for the current
   Makani and Liveability artifacts, measuring selection, execution, result
   equivalence, and presentation rather than a single aggregate score.
2. Expand supported free-form coverage from reviewed contracts through
   reusable semantic assets: table/field roles, aliases, granularities,
   approved joins, metrics, value domains, spatial semantics, and data-quality
   annotations.
3. Improve the unified UI path so metadata -> ontology overlay -> semantic
   configuration -> left-chat response remains discoverable for any future
   source, without two-source hardcoding.
4. Complete semantic/ontology interoperability governance before representing
   import/export as fully production-grade. The audit found these concrete
   gaps: strict OSSIE import does not detect modified projections; ordinary
   Turtle/JSON-LD import discards fields/relationships/metrics; JSON/YAML
   imports must forcibly down-rank execution fields; imports need full
   review/validation/publish lifecycle; source discovery and UI source choices
   must be dynamic; and permissions, tenancy, audit retention and lifecycle
   controls require completion.
5. Record unresolved source-data quality/semantic ambiguities as governed
   remediation items for a future physical-lake, data-governance stage rather
   than fabricating a runtime interpretation.

## New-Window Prompt

Use this concise prompt in the new window:

```text
Read docs/handoffs/2026-09-08-abu-dhabi-smart-query-continuation.md first.
Continue Abu Dhabi governed Smart Query on branch
feat/abu-dhabi-nl2semantic2sql-productization. I am switching to a local LLM
for a reproducible two-route benchmark. Preserve all unrelated dirty files,
do not use benchmark-specific runtime rules, verify the local chat+embedding
endpoints, then run a balanced Makani/Liveability smoke cohort and report
selection, execution, result-equivalence, presentation, and infrastructure
failures separately.
```
