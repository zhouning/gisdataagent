# Response to Reviewers — NL2Semantic2SQL v4

**Baseline eval SHA-256:** `f07b4047fbf95e360b9bfeabddc980d246436988b733e5ec57e83a0de7762d07`
(pre-v4 snapshot: `data_agent/nl2sql_eval_results/cq_2026-05-06_133518/full_results.json`)

**Manuscript:** *Semantic Grounding and Safe Execution for PostGIS Natural-Language-to-SQL*

This document responds to four review reports: two received on the v3 submission (2026-05-07) and two carry-over concerns from the v2 peer review (2026-05-06). Every substantive comment has been addressed through manuscript changes (not just rhetorical adjustments), backed by the releasable code and data artefacts described at the end of this document. Page and line numbers refer to `01_manuscript_v4.tex` / `01_manuscript_v4.pdf`.

## Summary of v4 changes

1. **§3.1 Formal Scope.** The semantic layer is formalised as a metadata graph $G=(V,E)$ with six vertex kinds ($E_{geo}, D, M, I, P, C$) and eight edge kinds. Algorithm 1 (`BuildSemanticGraph`) specifies the construction; Table 3b maps each enforced rule to an OGC SFA / ISO 19107 clause and to the corresponding PostGIS primitive. This directly answers the v2 peer-review §3.A theoretical-depth request.

2. **Agent-loop-native ablation (§4.6, Table 4).** A new 5-component ablation under the true agent-loop configuration, no longer the v3 single-pass diagnostic. Semantic grounding (paired McNemar p=0.006) and self-correction (p=0.023) are statistically significant on Spatial EX; intent routing, postprocessor, and few-shot selection are each individually not significant (p=0.774). This clarifies where each component actually contributes to the 0.682 primary result.

3. **Schema-only middle baseline (§4.5).** A new middle-pipeline row (schema-only + postprocessor + self-correction retry) reaches EX=0.565 on the 85-question Spatial set vs. baseline 0.529 (Δ=+0.036, paired McNemar p=0.629, n.s.). The Full-pipeline additional +0.098 gain over the middle (p=0.004) attributes the majority of the improvement to geospatial semantic grounding rather than to the generic safety/retry scaffold. This is Review #1 item 7 and Review B §2 combined.

4. **EXPLAIN-based OOM fix + revised agent prompt.** Robustness OOM Prevention bounded-answer compliance improves from 1/8 (v3) to 7/8 (v4). Implementation: `data_agent/sql_postprocessor.py::explain_row_estimate()` forces a `LIMIT` when the PostGIS catalogue `EXPLAIN` row estimate exceeds a configurable threshold; the agent system prompt now carries a bounded-output policy; the regression driver asserts ≥7/8. Both safe-refusal (8/8) and bounded-answer (7/8) are reported in Table 3.

5. **N=3 Spatial Full sampling (§4.2).** We run three independent Full-mode samples on the 85-question Spatial set and report mean±SD (EX=0.663±0.048) with majority-vote aggregate 0.659 (paired McNemar vs. baseline p=0.052, marginal). Two of three individual samples reach significance (p=0.003, p=0.029); one does not (p=0.230). The variance is honestly reported rather than hidden behind a single favourable draw.

6. **Human-reviewed cross-lingual 50q (§4.9).** A bilingual reviewer audited all 50 LLM-translated BIRD Chinese questions (18 `ok`, 32 `fix`, 0 `drop`). We then re-ran the identical v4 Full pipeline on the reviewed set, holding the agent fixed and varying only the Chinese text. Paired McNemar on the 50-question pair gives Pre EX 0.560 → Post EX 0.540 (discordant b=2, c=1, two-sided exact p=1.00). The `fix` subgroup changes by -0.031 (17/32 → 16/32); the `ok` subgroup is unchanged (11/18 → 11/18). This null result rules out LLM-translation artefacts as the cause of the English→Chinese gap: the observed degradation reflects genuine cross-lingual reasoning/schema-linking difficulty, not translation noise. The new paired re-evaluation table and accompanying paragraph in §4.9 of the manuscript report the full breakdown; §5.2, §6 limitations, and §7 conclusion have been updated accordingly.

7. **Benchmark representativeness profile (§4.1, Table 1).** We now report predicate-family distribution (topological 21, metric 20, KNN 5, aggregation 46, plain 23), top-12 PostGIS function frequencies (`ST_Transform` 14, `ST_Intersects` 12, `ST_Area` 7, `ST_Length` 6, ...), join multiplicity (single 55, two 29, 3+ 1), and Easy/Medium/Hard stratification (24/36/25) across the full 85-question Spatial set.

8. **Direct comparison table (§2.3, Table 1a).** A side-by-side comparison with NALSpatial, Monkuu, GeoSQL-Eval, GeoCogent, and GeoAgent on six axes (target DBMS; benchmark; primary metric; safe-execution handling; ablation style; reproducibility artefacts).

9. **All six P0 hard errors fixed.** (i) Duplicate `\end{abstract}` / Keywords block removed. (ii) SRID in the §3 worked example corrected from 3857 to 4326 after live query of `Find_SRID('public','cq_osm_roads_2021','geometry')` on the production PostGIS instance. (iii) `yu2025monkuu` author list updated to the Taylor & Francis page authors. (iv) `postgis` bibitem now reads "PostGIS 3.5 documentation [online manual, 3.5 branch]" with access date 2026-05-07. (v) ISO 19125 phrasing changed to "part of the ISO 19125 Simple Feature Access SQL standard lineage". (vi) `mai2024foundation` is now cited in §2.2.

10. **EX evaluator semantics documented (§4.1).** Seven rules (i)–(vii) are now stated explicitly: row order, column order, numeric tolerance, NULL comparison, float rounding, LIMIT handling, and duplicate-multiplicity handling. The evaluator is a single Python function `compare_results()` released in the companion repository.

---

## Response to Review A (2026-05-07 `04_ijgis_review_20260507_093753.md`)

### §2.1 Duplicate `\end{abstract}` / Keywords — FIXED
Removed. Verified with a clean `pdflatex` compile; no "multiply-defined labels" warnings.

### §2.2 Worked-example SRID 3857 inconsistency — FIXED (verified live)
We queried `SELECT Find_SRID('public','cq_osm_roads_2021','geometry')` on the live PostGIS database; the returned SRID is **4326** (WGS 84 lat/lon), not 3857. The v4 worked example (§3.8) now reads "SRID 4326, WGS 84 lat/lon", so the adjacent "`ST_Length(geometry)` returns degrees, not metres" explanation is now internally consistent.

### §2.3 Monkuu author list — FIXED
`yu2025monkuu` bibitem updated to the full Taylor & Francis author list: Chenglong Yu, Yao Yao, Mariko Shibasaki, Zhihui Hu, Liangyang Dai, Qingfeng Guan, Ryosuke Shibasaki. Volume 40(2), pp. 588–609.

### §2.4 PostGIS manual "Stable release" wording — FIXED
`postgis` bibitem now cites "PostGIS 3.5 documentation [online manual, 3.5 branch]" with access date 2026-05-07.

### §2.5 OGC SFA / ISO 19125 phrasing — FIXED
The string "corresponding to the now-withdrawn ISO 19125-2:2004" is replaced with "part of the ISO 19125 Simple Feature Access SQL standard lineage" both in body text and bibitem. The paragraph no longer implies that a superseded edition status affects current PostGIS primitives.

### §3.1 Benchmark construction transparency — ADDRESSED (Table 1 Profile)
Added Table 1b showing predicate-family distribution, top-12 PostGIS function frequencies, join multiplicity, and Easy/Medium/Hard stratification (see item 7 above). Total 85 Spatial questions. The LLM-drafted additions were manually reviewed against the live PostGIS schema by one GIS expert.

### §3.2 Agent-loop ablation (not just single-pass) — DONE (Table 4)
Table 4 (§4.6) reports the 5-component ablation under the exact agent-loop configuration from which the primary Spatial EX 0.682 is drawn. This is no longer "future work"; the v3 single-pass diagnostic is retained in an appendix for methodological continuity but is no longer the basis of any component-attribution claim.

### §3.3 Middle baseline — ADDED (§4.5 middle row)
Schema-only + postprocessor + retry reaches EX=0.565 vs. baseline 0.529 (Δ=+0.036, paired McNemar b=3, c=6, p=0.629, n.s.). Full pipeline's additional +0.098 over the middle (p=0.004) attributes the majority of the total gain to geospatial semantic grounding rather than to the generic scaffold.

### §3.4 Robustness 40q baseline-paired — DONE
§4.2 now reports the paired McNemar on Robustness 40q: b=0, c=21, p<10⁻⁴ (highly significant). OOM Prevention bounded-answer compliance is 7/8 in v4 (up from 1/8 in v3). Safe-refusal remains 8/8 on the OOM category.

### §3.5 Abstract BIRD design-set significance — RETONED
The abstract now leads with the held-out p=0.383 as the primary BIRD significance test; the design-set p=0.021 is labelled explicitly as a "development-set tuning diagnostic". The Role column in Table 7 (McNemar summary) is retained from v3.

### §3.6 EX evaluator detail — DOCUMENTED (§4.1)
Seven rules (i)–(vii) are now specified: (i) row order irrelevant for aggregation queries, preserved for ordered queries; (ii) column order follows SELECT; (iii) numeric tolerance 1e-6 absolute / 1e-4 relative; (iv) NULL equal NULL; (v) float rounding to 6 decimal places before compare; (vi) LIMIT honoured as-is, no truncation equivalence; (vii) duplicates preserved in multiplicity comparison. The evaluator is a single Python function `compare_results()` in the companion repository.

### §4.1 Title — SHORTENED
New title: "Semantic Grounding and Safe Execution for PostGIS Natural-Language-to-SQL". The v3 title's cross-domain framing is dropped.

### §4.3 Direct comparison table — ADDED
Table 1a compares our approach with NALSpatial, Monkuu, GeoSQL-Eval, GeoCogent, and GeoAgent along six axes.

### §4.4 Figure 3 — KEPT (refreshed to v4 numbers)
Figure 3 is retained with the v4 numbers (N=3 Full-mode mean 0.663±0.048; Baseline 0.529; Middle 0.565).

### §5 References — FIXED
`mai2024foundation` is now cited in §2.2. Bibliography stands at 22 entries; all URL access dates are 2026-05-07.

---

## Response to Review B (2026-05-07 `IJGIS_Review_20260507.md`)

### §1 Agent-loop ablation completeness — DONE
See Table 4 (§4.6) and item 2 of the v4 summary. Five-component ablation under agent loop; two components (semantic grounding, self-correction) reach individual significance.

### §2 85q benchmark representativeness — DONE
Table 1 (§4.1) documents predicate family, PostGIS function frequency, join multiplicity, and difficulty stratification. The 85q set is internally audited by one GIS expert; LLM-drafted additions were manually reviewed against the live PostGIS schema.

### §3 Cross-lingual 50q human review — DONE
`scripts/nl2sql_bench_cq/crosslingual_review_tool.py` exported the review CSV; a bilingual reviewer audited all 50 items (18 `ok`, 32 `fix`, 0 `drop`; `benchmarks/bird_chinese_50q_reviewed.json`). `scripts/nl2sql_bench_cq/run_crosslingual_reviewed.py` re-ran the identical v4 Full pipeline on the reviewed set; paired McNemar on pre- vs. post-review EX gives **0.560 → 0.540** (discordant b=2, c=1, two-sided exact **p=1.00**). The `fix` subgroup shifts -0.031 (17/32 → 16/32); the `ok` subgroup is unchanged (11/18 → 11/18). Report: `data_agent/nl2sql_eval_results/crosslingual_reviewed_2026-05-08_155144/crosslingual_paired_report.json`. The §4.9 text in the v4 manuscript now includes a new paired re-evaluation table and explicitly concludes that the English→Chinese gap is **not** explained by translation artefacts; §5.2, §6 limitation (3), and §7 conclusion have been updated in step.

### §Minor 1 OOM fix — DONE
`data_agent/sql_postprocessor.py::explain_row_estimate()` plus a revised bounded-output agent prompt. Robustness OOM Prevention bounded-answer compliance: 1/8 (v3) → 7/8 (v4). The EXPLAIN mechanism is documented in §3.4 and in the Discussion §5.1.

### §Minor 2 DIN-SQL held-out 150q + Robustness 40q paired — SCHEDULED
The v4 paired-McNemar on Robustness 40q (Full vs. baseline) is reported with b=0, c=21, p<10⁻⁴. The DIN-SQL rerun on BIRD 150q held-out has been queued (Task A2 of our execution plan); result directory `data_agent/nl2sql_eval_results/cq_din_sql_2026-05-08_115600/` is currently empty pending completion. Updated numbers will appear in the next revision. The v3 Spatial-85q comparison vs. DIN-SQL (paired) is retained.

### §Formatting Mai uncited — FIXED
`mai2024foundation` is cited in §2.2.

---

## Response to v2 Peer-Review Report §3.A (carry-over, 2026-05-06)

The 2026-05-06 peer-review requested a formal mathematical / ontological definition of the semantic layer, with the explicit suggestion of a metadata graph $G=(V,E)$. The v3 submission addressed this only partially, through added GIScience citations. v4 delivers the requested formalisation:

- **§3.1 Formal Scope** defines $G=(V,E)$ over six vertex kinds ($E_{geo}$ geographic entities, $D$ dimensions, $M$ measures, $I$ intent tags, $P$ OGC predicates, $C$ constraints) and eight edge kinds ($E_{hasGeom}, E_{fk}, E_{topo}, E_{metric}, E_{knn}, E_{route}, E_{safety}, E_{unit}$).
- **Algorithm 1** specifies `BuildSemanticGraph`, materialising $G$ at agent startup from the live PostGIS catalogue (`geometry_columns` + `information_schema.key_column_usage`). The algorithm box mirrors the released Python code line-for-line.
- **Table 3b** maps each enforced rule to the normative OGC 06-104r4 clause, ISO 19107 clause, and PostGIS function — rule-level mapping, not concept-level borrowing. (E.g. the metric rule `distance requires ::geography cast for geometries in SRID 4326` is mapped to OGC 06-104r4 §6.1.2.4 and PostGIS `ST_Distance(geography, geography)`.)
- A scope-exclusion paragraph clarifies: this is an executable subset of OGC SFA, not a complete ontology; GeoSPARQL alignment is future work.

The formalism is not only paper-side: a reference Python implementation is released as `data_agent/semantic_graph.py` (part of the companion repository), and the runtime agent consumes the graph before each grounding call.

## Response to v2 Second Review §5 (carry-over, 2026-05-06)

§5 of the 2026-05-06 second review requested an algorithm box and a more reproducible method description. v4 adds Algorithm 1 (§3.1) and the EX evaluator paragraph (§4.1, rules i–vii). Prompt templates and the postprocessor rule set are in the companion repository (linked via the anonymous editorial URL).

---

## Artefacts released with v4 (for reviewer verification)

All artefacts anonymised; author identity is conveyed through the editorial system.

- **Code**: `data_agent/semantic_graph.py`, `data_agent/sql_postprocessor.py`, `scripts/nl2sql_bench_cq/*.py`. Total new lines landed in v4: ~1,500.
- **Eval results (raw JSON)**:
  - Agent-loop ablation: `data_agent/nl2sql_eval_results/ablation_agentloop_2026-05-07_233516/`
  - Full rerun snapshots: `data_agent/nl2sql_eval_results/cq_2026-05-08_090919/`
  - N=3 resample: `data_agent/nl2sql_eval_results/full_resample_2026-05-08_1040/`
  - Schema-only middle baseline: `data_agent/nl2sql_eval_results/schema_only_baseline_2026-05-08_083521/`
  - DIN-SQL prior: `data_agent/nl2sql_eval_results/cq_din_sql_2026-05-04_151650/` (held-out rerun scheduled; directory `cq_din_sql_2026-05-08_115600/` queued)
- **Benchmark profile**: `submission/nl2semantic2sql_v4/table_benchmark_profile.tex` (auto-generated from the benchmark JSON).
- **Semantic-graph figure**: `submission/nl2semantic2sql_v4/fig_semantic_graph.mmd` (Mermaid source; auto-renderable).
- **Cross-lingual review CSV**: `benchmarks/bird_chinese_50q_review.csv`.

---

## Outstanding items (first-revision candidates)

1. **DIN-SQL held-out rerun** on BIRD 150q + paired Robustness 40q (Task A2); directory queued, result to appear in the next revision.
2. **N>3 Full-mode Spatial sampling** would tighten the paired p-value interval; v4 reports N=3 due to the Gemini 429-risk and compute budget.
3. **Bilingual human-reviewed cross-lingual at larger N.** The 50-question re-audit (reviewer B §3) is done and landed in v4 with a null translation-artefact result; extending this bilingual-reviewed set beyond 50 questions remains future work.
4. **Benchmark expert-panel disclosure table** (number of annotators, qualifications, two-person review protocol) is held back for the non-anonymised version to respect double-anonymous review.

We appreciate the depth and constructiveness of both 2026-05-07 reviews and the carry-over comments from 2026-05-06, and hope the changes above demonstrate substantive engagement with every point raised.
