# Abu Dhabi Intelligent Query Product Evidence

This report records the current product boundary after the 2026-08-20
Liveability, Makani, and federated runs. It distinguishes technical catalog
coverage from reviewed business semantics and does not claim that every table
has a complete business ontology.

## Verified benchmark result

| Track | Runtime route | Cases | Verified result |
|---|---|---:|---:|
| Liveability single source | selective direct metric contracts + governed free-form NL2Semantic2SQL + shadow IR | 15 | 15/15 |
| Makani single source | selective direct metric contracts + governed free-form NL2Semantic2SQL + shadow IR | 15 | 15/15 |
| Liveability + Makani federation | reviewed metric contracts + typed federated IR | 9 | 9/9 |

The single-source tracks each passed 12/12 answerable Gold-equivalence cases
and 3/3 refusals. Their repeated selective-direct stability runs passed 75/75
per source. The
federated track passed 6/6 two-source Gold-equivalence cases and 3/3 row-level
cross-source refusal cases. All 12 executed federated source subplans produced
validated semantic plans; Chinese, English, and Arabic each passed 3/3.

Federated runtime semantics contain neither benchmark questions nor Gold
references. Positive cases are business-language questions without physical
table names, schemas, SQL, or GIS function names. Gold is loaded only by the
benchmark runner. The final federated run invoked no LLM because each admitted
subplan compiled a reviewed metric contract deterministically.

## Semantic configuration

| Source | Catalog resources | Active table-local bindings | Reviewed business assets | Reviewed relations | Metric contracts |
|---|---:|---:|---:|---:|---:|
| `liveability_data_20260730/public` | 159 | 138 | 8 | 5 | 146 |
| `makani_sync_full/public` | 772 | 764 | 7 | 4 | 770 |

The high metric-contract totals include one governed table-local inventory
contract for each admitted table. Those contracts provide broad read-only
query admission, but are not equivalent to customer-certified business
meaning. The reviewed 8/7 asset subsets carry multilingual labels, aliases,
grain, field roles, spatial roles, and business capabilities.

The federated v4 layer contains two reviewed cross-source contracts. Each
subplan stores only `source + metric_contract_id`; it stores no child question,
physical table name, or Gold path. Both databases execute independently and
the application returns two sections. Cross-database SQL and cross-source
joins are disabled.

The single-source selective-direct reports show deterministic canonical metric
serving on 6/12 Liveability and 4/12 Makani answerable cases. Those routes
had zero LLM calls and direct Gold equivalence of 6/6 and 4/4 respectively.
The remaining answerable cases, all safety refusals, and any query containing
an unbound filter, comparison, or time modifier use the governed free-form
route. Across five runs, route behavior was 100% consistent; typed IR
validation was 12/12 on every run.

## Ontology status

The ontology is **not complete as a business ontology**.

Technical coverage is complete for the discovered snapshots: 159 resources /
2,839 fields for Liveability and 772 resources / 24,589 fields for Makani.
The ontology overlays expose 138 and 764 governed table-local concepts. The
reviewed semantic subsets are now mirrored into those overlays, including 8/7
business assets and 5/4 relations, so the ontology is no longer only a table
catalog. The activation gates remain deliberately set to
`business_semantic_coverage_complete=false` and
`business_semantic_coverage_scope=reviewed_asset_subset`.

Completeness still requires steward-approved meaning for the remaining high
value tables: entity identity, grain, measures and additivity, value domains,
time semantics, units, null/orphan policy, spatial role and CRS, and join
cardinality. A data dictionary is enough to propose these assets, but not to
certify them automatically.

## Runtime role of the ontology

The hot path consumes the ontology's reviewed projection in the semantic
layer; it does not query the ontology JSON as a separate database on every
request.

1. Multilingual labels and aliases resolve business assets from the question.
2. Grain, field roles, and capabilities constrain dimensions and measures.
3. Only reviewed equality or spatial relations can admit a join.
4. A reviewed metric chooses a canonical contract where available.
5. SQL admission checks tables, fields, geometry usage, relations, source,
   schema, read-only policy, and row budget.
6. Typed TaskFrame, SemanticQueryIR, ValidationReport, LogicalPlan, and
   PhysicalPlan evidence records what was understood and compiled without
   exposing the question or Gold answer inside the plan.

For the current single-source path, high-confidence reviewed metric contracts
are now a deterministic serving route; the free-form path's typed IR remains
observational shadow evidence. In the federated path, metric contracts authorize each source query;
the federated typed plan proves the two independent subplans and application
merge but is still marked non-authoritative evidence.

## Claim boundary

The current evidence supports strong governed single-source analytics and two
reviewed forms of two-source independent aggregation. It does not support an
accuracy claim for arbitrary cross-source joins, row-level entity matching,
cross-source spatial linkage, or arbitrary cross-database SQL.

## Next release work

1. Build a customer-held-out set of at least 30 unseen business questions,
   separated from semantic authoring and Gold, with asset-resolution and IR
   correctness scored independently.
2. Promote ontology coverage in steward-reviewed domain batches, starting
   with the tables that appear in customer questions; do not treat all 902
   admitted table-local concepts as semantically complete.
3. Move supported aggregate/filter/join capabilities from shadow observation
   to selective typed-IR serving, with explicit capability-gap fallback.
4. Add mixed spatial + governed-metric questions and parameterized compilers,
   then measure result equivalence against the existing governed route.
5. Expose product trace fields for resolved asset, metric contract, validation,
   plan fingerprints, source snapshot, fallback reason, and claim boundary.
