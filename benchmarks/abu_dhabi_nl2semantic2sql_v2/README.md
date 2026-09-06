# Abu Dhabi NL2Semantic2SQL Benchmark v2

This is the main semantic-selection and governance benchmark for the two real
PostgreSQL sources:

- `liveability_data_20260730.public`
- `makani_sync_full.public`

The public dataset contains business-language questions and semantic intent
contracts. It does not contain SQL, result rows, physical table names in the
questions, or runtime semantic-layer prompts. Private SQL/result contracts are
loaded only by the independent evaluator after a reviewed semantic asset has
been selected.

The 36 cases cover:

- single-asset Top-1 selection and multi-asset reviewed-set coverage;
- semantic field, metric operation, unit and grain selection;
- reviewed relationship and spatial predicate admission;
- multi-measure and multi-asset queries;
- multilingual questions;
- ambiguity clarification and unpublished-candidate blocking;
- unsupported prediction and sensitive-data refusal;
- federated separate aggregation versus forbidden cross-source joins.

`selection_report.json` is only the deterministic first-stage result. It is not
an end-to-end NL2Semantic2SQL accuracy claim. Single-asset cases are scored by
Top-1; composite cases are scored by coverage of the complete reviewed asset
set. The report exposes both metrics separately, plus reviewed admission and
overall selection pass rate:

- evaluated cases: 30 single-source cases;
- single-asset Top-1 accuracy: reported as `execute_single_asset_top1_accuracy`;
- multi-asset reviewed-set coverage: reported as `execute_multi_asset_reviewed_set_coverage_accuracy`;
- SQL correctness, result correctness, and runtime LLM quality: not evaluated
  by this report.

Run the public artifact and first-stage report with:

```bash
uv run --no-sync python scripts/build_abu_dhabi_benchmark_v2.py
uv run --no-sync python scripts/evaluate_abu_dhabi_benchmark_v2_selection.py
```

The product console exposes this benchmark separately from the older v1
15-case stability control group.

## Left-chat manual validation

The manual NL2Semantic2SQL execution entry is the GIS Data Agent left natural-
language chat. The right-side workbench is for inspecting registered sources,
ontology, semantic configuration, and evaluation evidence; it is not the
manual question entry.

- `abu_dhabi_nl2semantic2sql_left_chat_manual_v1.json` contains all 36 public
  questions with a session-independent chat input, expected outcome, and
  per-case manual checks.
- `LEFT_CHAT_MANUAL_VALIDATION.md` is the human-readable checklist.
- The published checklist uses an explicit business-source prefix:
  `@Liveability`, `@Makani`, or `@AbuDhabi`. The question text itself contains
  no physical table name. In the product UI, an unprefixed question is also
  resolved against the current published semantic artifacts when it has a
  unique source match; if multiple registered sources match, the UI asks the
  user to select a source instead of guessing.
- The left chat applies the same semantic candidate and execution-admission
  boundary as the evaluator before any SQL runtime is invoked.
- `reports/left_chat_real_ui_smoke_20260821.json` records a real browser smoke
  run through the left chat against the two registered PostgreSQL sources.
- `tests/e2e/abu_dhabi_left_chat_plain_question_real_e2e.js` covers the
  unprefixed left-chat path, including new-session initialization, source
  resolution, governed execution, and rendered evidence.

Regenerate the manual artifact from the public Benchmark v2 file with:

```bash
uv run --no-sync python scripts/build_abu_dhabi_left_chat_manual_benchmark.py
```

## Published end-to-end evidence

`published_report_manifest.json` is the product-facing publication pointer for
the current controlled real-source run. It binds the baseline SQL report, the
SemanticQueryIR candidate report, and their pairwise comparison by SHA-256.
The evidence API verifies those checksums on every read and publishes only
aggregate outcome, route, latency, token, failure-class, and semantic-layer
binding fields. Private Gold identifiers, checksums, SQL, result contracts,
questions loaded by the evaluator, and source rows are not included in the
product response.

The current report contains 36 objective, reference-checked cases. Thirty are
shared policy, reviewed-contract, or federated controls; only six exercise a
different model planning route. Both routes pass all six. This single paired
run therefore supports a current-run tie, not promotion of the experimental
route. Repeated stability evidence is required before a production route
decision.

`reports/stability_summary_3run_20260821.json` aggregates three controlled
pairwise runs. Each input report is bound by SHA-256, and all runs use the same
public benchmark, private Gold checksum, and semantic configuration. Across 18
route-changing observations, both routes pass 17. The baseline and candidate
each have one unique result-equivalence failure. The candidate is faster in
one run and slower in two, with 9,238 additional input tokens and 2,272
additional output tokens in total. The repeated evidence therefore does not
support candidate promotion.
