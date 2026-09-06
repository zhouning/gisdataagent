# Abu Dhabi NL2SQL Product Benchmark v1

This is the product capability benchmark for the two current registered
sources. It is deliberately separate from the older table-inventory
regression sets.

> **Scope notice (2026-08-30)**: v1 is a narrow product-entry smoke/release
> scope (15 cases per source plus the 9-case federated contract set). It is
> not the full-table accuracy claim and must not be combined with the v2/v3
> challenge or selection benchmarks. The current cross-route evidence index is
> [`../abu_dhabi_nl2semantic2sql_v2/published_report_manifest.json`](../abu_dhabi_nl2semantic2sql_v2/published_report_manifest.json);
> the architecture and claim boundaries are in
> [`../../docs/nl2semantic2sql_architecture.md`](../../docs/nl2semantic2sql_architecture.md).

The current anti-hardcoding audit is
[`../../docs/customer/abu_dhabi_liveability_site_validation/abu_dhabi_nl2sql_integrity_audit_20260830.json`](../../docs/customer/abu_dhabi_liveability_site_validation/abu_dhabi_nl2sql_integrity_audit_20260830.json).
It checks the inspected product runtime for benchmark-question/case literals,
concrete source or Gold identifiers, evaluator imports, and Gold leakage into
runtime prompts. It also checks that semantic assets do not embed complete
benchmark instances, that benchmark cases are marked as non-runtime assets,
and that the stable evidence run uses Gemini free-form generation rather than
a deterministic answer route. It records model-route and artifact-isolation
evidence for the latest Gemini runs. A passing audit is evidence about the
inspected revision; it is not a substitute for code review or a claim about
future code.

## Evaluation contract

The `business-language-clean-v1` profile requires that questions contain no
schema names, physical table names, technical field names, SQL keywords, or
SQL function names. Each case is authored from a customer business scenario,
security contract, or customer workflow. The benchmark definition is frozen
before model execution.

Gold SQL and result fingerprints are evaluation-only artifacts. They are not
loaded by the semantic layer, prompt builder, retrieval index, or runtime
query route. Gold contracts store result columns, row counts, and hashes, not
source data rows.

Each source has 15 cases:

- 12 read-only business questions with frozen runtime results;
- 3 safety/source-scope refusal questions;
- Chinese, English, and Arabic coverage;
- warehouse, GIS, mixed spatial-plus-business, and safety tracks;
- 6 holdout cases that are not used to author runtime assets.

The release profile requires five repeated runs. A single run is a baseline,
never a release claim. The stability aggregator reports Wilson 95% intervals,
per-case pass rates, behavior consistency, track breakdowns, and the release
gate.

## Frozen manifests

- `liveability_product_benchmark_v1.json`: source 12,
  `liveability_data_20260730/public`.
- `makani_product_benchmark_v1.json`: source 13,
  `makani_sync_full/public`.
- `gold/<source>/`: evaluation-only SQL and result contracts.
- `../../docs/customer/abu_dhabi_liveability_site_validation/abu_dhabi_federated_free_form_benchmark_v4.json`:
  clean two-source independent-aggregation benchmark.

The manifests are bound to the source discovery/profile fingerprints and the
v4 selective-direct semantic-layer versions. A source or semantic-layer drift invalidates the
benchmark rather than silently reusing old results.

## Current product result

The high scores in this README are contract-bound measurements. They are
possible because reviewed semantic assets and metric contracts reduce the
search space, while SQL/IR validators, source admission, and result contracts
reject unsafe or non-equivalent plans. They must not be interpreted as arbitrary
natural-language accuracy over every table and field.

### Why near 100% is possible under a frozen contract

The runtime does not ask Gemini to search both physical catalogs blindly.
It progressively narrows the task through registered-source fingerprints,
full technical metadata, ontology/dictionary alignment, reviewed semantic
bindings, candidate resolution, and execution eligibility. Gemini proposes
SQL only inside that grounded context; table/column/relationship/spatial,
read-only, budget, and source-admission guards remain deterministic. The
evaluator then reads an isolated Gold result contract and scores result
equivalence rather than SQL text similarity.

The strongest current all-LLM isolation run is the Makani stable recovery
subset:

| Evidence | Result |
|---|---:|
| Total / business-language / technical-control | 180/180; 153/153; 27/27 |
| Languages | zh 55; en 62; ar 63 |
| Gemini invocation | 180/180 `gemini-3.7-flash` |
| Runtime route | 180 `governed_free_form_llm`; 0 direct metric routes |
| Source governance / understanding / asset / result stages | 180/180 each |
| Mean / P95 generation latency | 8385.945 / 21543.852 ms |
| Unique generated SQL fingerprints | 65 |
| Infrastructure failures | 0 |

This recovery report deliberately records
`product_evaluation_run_valid=false`, `product_baseline_claim_valid=false`,
and `benchmark_accuracy_claim=false`: it proves that the selected failures
were repaired under an immutable runtime snapshot, but it is not a release
run or a full-catalog score.

The 2026-08-29 Makani full diagnostic provides broader, but older, evidence:

| Historical full diagnostic | Result |
|---|---:|
| Overall | 2323/2328 (99.7852%) |
| Business language | 1840/1845 (99.7290%) |
| Gold result equivalence | 2320/2325 (99.7849%) |
| Routes | 2305 LLM; 16 reviewed metric; 4 semantic gate; 3 read-only policy |
| Failures | 4 unexpected refusals; 1 Gold result mismatch |
| Mean / P95 generation latency | 9949.508 / 20548.730 ms |

That full diagnostic predates the latest per-case artifact-immutability gate,
so it remains diagnostic evidence and not the current release score. The
ongoing immutable full rerun must finish before any new full accuracy is
published; checkpoint progress is not an accuracy claim. Liveability's
386/387 (99.742%) cohort analysis also did not rerun the model and excluded
105 stale-source Gold cases, so it cannot be combined with either Makani run.

The accuracy mechanism is therefore a governed hybrid, not a hidden answer
lookup: reviewed metrics may use versioned canonical contracts, while ordinary
questions use model generation under the same semantic and execution gates.
The anti-hardcoding audit found zero runtime hits for benchmark questions,
case IDs, concrete Gold identifiers, or canonical Gold SQL, and verified that
Gold SQL/results/source rows do not enter runtime prompts.

The selective-direct baseline was run on 2026-08-20 through the governed
virtual NL2SQL route, with no HTTP/HTTPS proxy and no benchmark-specific
prompt or few-shot injection. High-confidence unparameterized reviewed
metrics use deterministic canonical compilation; questions with unbound
filters, comparisons, time ranges, or no unique reviewed metric fall back to
the governed LLM route. This table is a historical v1 release-scope result;
it is not the current 2026-08-30 two-catalog full-run score.

| Source | Cases | Passed | Business Gold | Safety | Warehouse | GIS | Mixed |
|---|---:|---:|---:|---:|---:|---:|---:|
| Liveability | 15 | 15/15 | 12/12 | 3/3 | 8/8 | 2/2 | 2/2 |
| Makani | 15 | 15/15 | 12/12 | 3/3 | 7/7 | 3/3 | 2/2 |

| Source | Direct metric routes | LLM-invoked cases | Direct-route Gold | Typed IR validation |
|---|---:|---:|---:|---:|
| Liveability | 6/12 (50.0%) | 9/15 | 6/6 | 12/12 |
| Makani | 4/12 (33.3%) | 11/15 | 4/4 | 12/12 |

These are single-run product baselines after the reviewed semantic-contract
and runtime fixes. Both sources had zero infrastructure failures, all 12
answerable cases were result-equivalent to Gold, and all three safety/source
scope cases were correctly rejected. Source rows were not persisted.

The release claim comes from five repeated runs per source, not from one run:

| Source | Runs | Case observations | Passed | Wilson 95% CI | Safety recall | Release gate |
|---|---:|---:|---:|---:|---:|---|
| Liveability | 5 | 75 | 75 | 95.13%–100% | 100% | `release_ready` |
| Makani | 5 | 75 | 75 | 95.13%–100% | 100% | `release_ready` |

Every case met the per-case 0.8 pass-rate threshold and behavior consistency
was 1.0 in both reports. The intervals are still intervals around a finite
sample; they are not a claim of full-database semantic certification.

The runtime prompt is grounded to a small reviewed asset set. For example,
the Makani spatial cases reduce the candidate context from 764 tables to two
business assets before generation. Gold SQL and result contracts remain
evaluation-only and are never put in prompts or retrieval.

## 2026-09-04 Liveability v34 / Semantic IR v36 regression

The latest customer table-card refresh is bound to source 12
(`liveability_data_20260730/public`, `10.255.254.109:5444`) with 165/165 table
cards and 3,479/3,479 fields matched. Runtime semantic assets are:

- `../../docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_semantic_layer_v34_enum_domains_20260904.json`
- `../../docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_ontology_v33_enum_domains_20260904.json`

After two representation-level fixes—scalar/boolean container normalization
for Gemini and observed-source precedence for case-colliding enum values—the
full 76-case Semantic IR candidate regression passed:

| Metric | Result |
|---|---:|
| Overall cases | **76/76 (100%)** |
| Business-language query Gold equivalence | **28/28 (100%)** |
| Query execution | **28/28 (100%)** |
| Refusal precision / recall | **100% / 100%** |
| Infrastructure failures | **0** |
| Mean / P95 generation latency | **6,748 / 13,870 ms** |

Report: `../../docs/customer/abu_dhabi_liveability_site_validation/liveability_v36_gemini37flash_semantic_ir_full76_representation_enumfix_20260904.json`.

The 100% figure is a finite, frozen-benchmark result for the current source
and semantic snapshot. It is not a full-catalog arbitrary-question accuracy
claim, and it does not promote Semantic IR over the default `baseline_sql`
route. Gold SQL/results remain evaluation-only; no case-specific branch or
benchmark leakage was added.

## Full-catalog readiness boundary

The full technical catalogs are audited separately from the product benchmark:
[`abu_dhabi_full_semantic_readiness_report.json`](../../docs/customer/abu_dhabi_liveability_site_validation/abu_dhabi_full_semantic_readiness_report.json).
That report is metadata-only and classifies every table as reviewed executable,
technical metadata only, or excluded. It also separates business-language
cases from technical catalog controls and records reviewed metric and
relationship coverage. It distinguishes `business_reviewed` from
`business_language_unreviewed`, so a natural-language inventory question is
not counted as an approved business query. The global release gate remains
`not_ready` until the business semantics and relationships for the full catalog
are reviewed; the report is not an arbitrary full-database accuracy claim.

Reports:

- `reports/gpt_5_1_liveability_product_v1_selective_direct_run.json`
- `reports/gpt_5_1_makani_product_v1_selective_direct_run.json`
- `reports/gpt_5_1_liveability_product_v1_selective_direct_run1.json` through `run5.json`
- `reports/gpt_5_1_makani_product_v1_selective_direct_run1.json` through `run5.json`
- `reports/gpt_5_1_liveability_product_v1_selective_direct_stability_report.json`
- `reports/gpt_5_1_makani_product_v1_selective_direct_stability_report.json`
- `reports/gpt_5_1_liveability_product_v1_run1.json` through `run5.json`
- `reports/gpt_5_1_makani_product_v1_run1.json` through `run5.json`
- `reports/gpt_5_1_liveability_product_v1_stability_report.json`
- `reports/gpt_5_1_makani_product_v1_stability_report.json`

## Technical catalog candidate coverage

The product now maintains a separate metadata-derived candidate artifact for
the full technical catalog. These candidates are deliberately not Gold cases:
they contain a schema-qualified table/field identity, a bounded operation, and
Chinese/English/Arabic question templates, but no SQL result, source rows, or
runtime semantic authorization. A candidate can be promoted only after the
registered source is executed read-only and a result contract is frozen against
the same source and profile fingerprints.

Generated 2026-08-26:

- `../../docs/customer/abu_dhabi_liveability_site_validation/liveability_technical_nl2sql_benchmark_candidates_20260826.json`:
  138 technical tables, 2,622 non-geometry fields, 6,252 candidates, and
  18,756 language variants.
- `../../docs/customer/abu_dhabi_liveability_site_validation/makani_technical_nl2sql_benchmark_candidates_20260826.json`:
  764 technical tables, 23,767 non-geometry fields, 54,076 candidates, and
  162,228 language variants.

The candidate generator is
`scripts/build_technical_nl2sql_benchmark_candidates.py`. It emits
`pending_gold_freeze` records only. The technical route is limited to row
counts, grouped values, null/non-null profiles, bounded numeric summaries, and
bounded detail rows; it does not imply business units, KPI meaning, joins,
spatial relations, or raw geometry projection.

## Model selection

The Liveability and Makani product entries resolve their model through the
shared gateway. The precedence is source-specific
`GDA_<SOURCE>_NL2SQL_MODEL`, then `GDA_NL2SQL_MODEL`, `GDA_LLM_MODEL`,
`NL2SQL_AGENT_MODEL`, and finally `MODEL_STANDARD`. The current LAN
configuration selects `gemini-3.7-flash`; switching model families therefore
changes only the gateway/prompt adapter selection, not the governance or SQL
execution contract.

Both stability reports are `release_ready` for this frozen 15-case-per-source
product scope. A separate federated v4 benchmark now proves the narrower
two-source capability shown below; the single-source runs alone do not.

## Current Gemini Drift Stability Evidence

For the 2026-08-24 Liveability discovery refresh, the formal Gemini 3.7 Flash
stability scope is frozen separately at
`docs/customer/abu_dhabi_liveability_site_validation/liveability_gemini37flash_product_v3_stability_benchmark.json`.
It contains 36 reviewed cases: 15 validation business cases, 18 holdout
business cases, and 3 holdout safety refusals. Five complete runs were
executed for each route against the same read-only source and semantic layer:

| Route | Observations | Passed | Aggregate status |
|---|---:|---:|---|
| `baseline_sql` | 180 | 180 | `release_ready` for this scope |
| `semantic_ir_experimental` | 180 | 180 | `candidate_stability_ready`; promotion disabled |

The 100% figures are contract pass rates for this frozen 36-case scope. They
are not a full-table or arbitrary-question accuracy claim; the broader 495-case
refresh still has `business_semantic_coverage_complete=false`.

| Federated scope | Cases | Passed | Gold | Refusals | Validated source plans |
|---|---:|---:|---:|---:|---:|
| Two reviewed independent-section contracts | 9 | 9/9 | 6/6 | 3/3 | 12/12 |

The federated runtime layer contains no benchmark questions, child questions,
physical tables, or Gold paths. It resolves a reviewed business contract,
executes `source + metric_contract_id` independently on source 12 and 13, and
merges only the presentation sections. It does not perform or claim arbitrary
cross-database SQL, cross-source joins, row matching, or spatial linkage.

Federated report:

- `reports/federated_product_v4_contract_ir_run.json`

## Reproduce

Freeze Gold contracts against the registered read-only sources:

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  GDA_DISABLE_LLM_PROXY=true \
  uv run --no-sync python scripts/freeze_abu_dhabi_product_benchmark_v1.py
```

Run either product baseline with the corresponding v4 selective-direct semantic layer and
manifest using `data_agent.free_form_nl2sql_benchmark`. Aggregate repeated
reports with `data_agent.product_nl2sql_benchmark`.

### Full-catalog run recovery

Long full-catalog evaluations must use the runner's atomic checkpoint rather
than keeping results only in memory. A checkpoint is bound to the normalized
benchmark hash, semantic-layer hash/version, source discovery/profile
fingerprints, model/reasoning settings, execution route, prompt version, and
selected case IDs. Resuming with any changed input is rejected; provider or
source outage placeholders and failed answer cases are automatically retried;
only validated passes are reused. The prior failed records remain in the
checkpoint until the retry replaces them.

```bash
uv run --no-sync python -m data_agent.free_form_nl2sql_benchmark \
  --benchmark docs/customer/abu_dhabi_liveability_site_validation/makani_sync_full_free_form_benchmark_v3_revised.json \
  --semantic-layer docs/customer/abu_dhabi_liveability_site_validation/makani_sync_full_semantic_layer_v4_full_coverage.json \
  --source-id 13 --owner abu-dhabi-site-operator \
  --model gemini-3.7-flash --execution-profile baseline_sql \
  --checkpoint docs/customer/abu_dhabi_liveability_site_validation/makani_full_gemini.checkpoint.json \
  --output docs/customer/abu_dhabi_liveability_site_validation/makani_full_gemini.report.json \
  --progress-interval-seconds 30
```

If the process is interrupted, rerun the same command with `--resume`. The
checkpoint contains per-case evidence only; source rows and generated SQL are
never persisted there. The final report records the checkpoint path and reuse
count for auditability.

Do not merge these manifests into the old v3 inventory benchmark. The old
417/417 and 2,291/2,295 numbers remain useful as source-admission and
table-local execution regression evidence, but they are not product-language
accuracy claims.

## Product administration surfaces

The product console exposes two operational surfaces in addition to the
read-only evidence inspector:

- **Semantic administration** (`/api/abu-dhabi/nl2semantic2sql/semantic-admin/*`)
  stores asset, field, relationship, and metric-contract edits in
  `agent_semantic_admin_versions` / `agent_semantic_admin_entries`. A change is
  a draft first; a reviewer must validate and publish it. Published registry
  entries are versioned and auditable, while the current runtime remains bound
  to the frozen, reviewed artifact until an explicit runtime promotion is
  performed.
- **Virtual-lake metadata**
  (`/api/abu-dhabi/nl2semantic2sql/virtual-lake-metadata`) reads the existing
  virtual-source discovery/profile snapshots for source 12 and source 13.
  The response contains schemas, tables, fields, geometry types/CRS, PK/FK,
  estimates, discovery/profile fingerprints, and timestamps. The endpoint is
  metadata-only: `source_rows_persisted` is always `false` and credentials are
  never returned. Before a live discovery has run, it labels the frozen
  technical catalog as `artifact_technical_catalog_evidence` rather than
  claiming a successful live snapshot.

### 2026-09-05 matched v37 dual-route run

The latest same-configuration run is bound to the v37 Liveability semantic layer,
source `10.255.254.109:5444` (`source_id=12`), the frozen v14 76-case benchmark, and
Gemini `gemini-3.7-flash`:

| Route | Overall | Query execution | Gold equivalence | Refusal P/R |
|---|---:|---:|---:|---:|
| `baseline_sql` v51 | 75/76 (98.68%) | 28/28 (100%) | 27/28 (96.43%) | 100% / 100% |
| `semantic_ir_experimental` v52 | **76/76 (100%)** | **28/28 (100%)** | **28/28 (100%)** | **100% / 100%** |

Reports:

```text
docs/customer/abu_dhabi_liveability_site_validation/liveability_v51_gemini37flash_baseline_full76_v37_20260905.json
docs/customer/abu_dhabi_liveability_site_validation/liveability_v52_gemini37flash_semantic_ir_full76_v37_20260905.json
docs/customer/abu_dhabi_liveability_site_validation/liveability_v51_v52_dual_route_pairwise_20260905.json
```

F032 is the sole baseline discrepancy: baseline omitted the requested `needed_ap50`
measure in a top-10 projection, while Semantic IR passed the same case. It is not fixed
by adding a case-specific branch. The runtime now retries such proposals through a
generic ranked-measure projection guard. F024 passed under its published equivalent-result
contract. The candidate release gate remains closed until repeated stability and broader
full-catalog coverage are demonstrated. These percentages are frozen-sample evidence,
not an arbitrary-question claim for either database.
