# Response to Reviewers — NL2Semantic2SQL v4

**Baseline eval SHA-256:** `f07b4047fbf95e360b9bfeabddc980d246436988b733e5ec57e83a0de7762d07`
(file: `data_agent/nl2sql_eval_results/cq_2026-05-06_133518/full_results.json`, pre-v4 snapshot used for regression comparison)

**Manuscript:** *Semantic Grounding and Safe Execution for PostGIS Natural-Language-to-SQL*

This document responds to (i) two external reviews received on v3 (2026-05-07) and (ii) the carry-over theoretical-formalisation request from the v2 peer-review report §3.A (2026-05-06). We have made substantive changes to the manuscript — including a formal metadata-graph definition, an agent-loop-native ablation, an EXPLAIN-based OOM pre-check, and a human-reviewed cross-lingual set — rather than only rhetorical adjustments. Page and line numbers refer to `01_manuscript_v4.tex` / `01_manuscript_v4.pdf`.

> **Note**: this file is a placeholder prepared at Task 0 of the v4 plan. The point-by-point response is written at Task 17, after all code and eval changes land. The v3 content below is retained verbatim for reference until Task 17 replaces it.

---

## (v3 content follows, retained as reference pending Task 17 rewrite)

# Response to Reviewers — NL2Semantic2SQL v3

**Manuscript:** *NL2Semantic2SQL: Semantic Grounding and Safe Execution for PostGIS-based NL2GeoSQL, with a Cross-Domain Stress Test on Warehouse Queries*

This document responds to the two external review reports received on the previous version. We have made substantive changes to the manuscript rather than only rhetorical adjustments. Page and line numbers refer to `01_manuscript_v3.tex` / `01_manuscript_v3.pdf`.

---

## A. Summary of what has changed in v3

- **Title and scope**: the paper is now *primarily* about PostGIS-based NL2GeoSQL. The phrase "cross-domain framework" is replaced with "semantic grounding and safe execution for PostGIS-based NL2GeoSQL, with a cross-domain stress test on warehouse queries". The contribution list is explicitly three contributions on the GIScience side, with BIRD downgraded to a stress test. *(manuscript title line; abstract; §1 Contributions.)*
- **Ablation**: Table 6 is now labelled and framed as a *single-pass diagnostic*. The manuscript explicitly states, in bold, that it is **not** used to attribute the agent-loop 0.682 Spatial EX to components. The only conclusion we draw from it is the domain-scoping finding (warehouse rules do not help GIS). *(§4.6, renamed "Single-pass component diagnostic".)*
- **Robustness**: the 40-question Robustness table now reports **two orthogonal metrics**, *safe-refusal rate* and *bounded-answer compliance*, for every category. We no longer report a single "success rate". The OOM Prevention category is explained as a trade-off between the two. *(§4.2, Table 3.)*
- **BIRD**: Table 5 now includes 95 % Wilson confidence intervals for EX and a Newcombe-style CI for the paired-proportion difference. The 108-question design-set $p=0.0213$ is described as a *development-set tuning effect* and the 150-question held-out set is explicitly the primary BIRD significance test. *(§4.3, Table 5; Table 7 McNemar summary now carries a Role column marking Primary / Development / Exploratory.)*
- **Cross-lingual**: the LLM-translated probe is now caveated in the abstract and methodology as exploratory, with translation-artefact risks acknowledged up front rather than only in Limitations. *(abstract; §4.9.)*
- **Related Work** is rewritten so that IJGIS-published NL-to-spatial-database work (GeoCogent, GeoAgent, Monkuu, GeoSQL-Eval) and the IEEE TKDE NALSpatial paper are foregrounded as the directly related prior art; Spider/BIRD/DIN-SQL are framed as non-spatial backdrop. GIScience foundations (Goodchild; Egenhofer & Franzosa; Clementini et al.) are explicitly cited. *(§2, rewritten.)*
- **Worked example**: a new subsection §3.8 walks a single Chongqing benchmark question through every stage (NL → intent → schema/SRID → injected PostGIS rules → initial SQL → execution error → self-corrected SQL → gold), so that the grounding behaviour is concretely auditable. *(§3.8, Fig. 2.)*
- **References**: all previously identified metadata issues are corrected; five GIScience / NL-to-spatial-DB references are added; `et al.` is expanded to full author lists per Taylor & Francis style; URL access dates are updated; one ISO standard status note is added. *(Bibliography, now 22 entries.)*
- **Anonymisation**: author name, affiliation, and email are removed; commit hashes previously visible in the Reproducibility section are removed; the reviewer-accessible repository link is provided through the editorial system.
- **Language polish**: "honestly", "camera-ready", "available on request", and process-language like "previous version" / "Phase A" have been removed. The KNN operator is written as a single `\texttt{<->}`. The abstract is compressed from ~290 words to 252.

---

## B. Response to Review #1 ("Strict re-review", overall: Major Revision)

### 1. IJGIS适配性仍需加强 — *Done.*

The title, abstract, Introduction, and Conclusion have been rewritten to make the primary contribution PostGIS/NL2GeoSQL. BIRD is now explicitly a cross-domain *stress test*. The abstract's first substantive sentence is now about PostGIS operators, SRIDs, geography casts, KNN, and safe refusal — i.e. GIScience computations, not a generic text-to-SQL pitch.

### 2. "Full pipeline"定义不统一 — *Done by option 2 (diagnostic re-framing).*

We take the reviewer's option (2): the single-pass ablation is moved into a section explicitly labelled *"Single-pass component diagnostic"* with a bold caveat that it is **not used to attribute** the agent-loop 0.682. The only claim we draw from it is the domain-scoping finding (warehouse rules do not help GIS). An agent-loop-native ablation is listed in Limitations and Future Work as the correct way to do component attribution on the primary result.

### 3. BIRD设计集/held-out处理进一步降调 — *Done.*

- Abstract no longer places BIRD design-set significance on equal footing with GIS; the sentence pattern is now "improves the design set by +0.093 ($p=0.0213$) but only +0.033 on the independent held-out set ($p=0.3833$), evidence that warehouse-side gains are sample-dependent".
- Table 5 now describes $p=0.0213$ as a *design-set (tuning) effect*, with the held-out row marked as the primary BIRD test in Table 7.
- 95 % Wilson CIs added for Baseline and Full EX on both sets; a paired-proportion CI (Newcombe-style Wald) is added for $\Delta$: $[-0.03, 0.09]$ on held-out, $[0.02, 0.16]$ on design.
- Multiple-comparison disclosure: Table 7 (paired-McNemar summary) now carries a Role column marking each test as **Primary** (GIS Spatial, BIRD held-out, Full-vs-DIN on GIS Spatial), **Development** (BIRD round-1 subset, BIRD design), or **Exploratory** (Robustness 15-question pilot, Full-vs-DIN on Robustness pilot).

### 4. GIS Robustness 40 题不能与 15 题 pilot 显著性混用 — *Done.*

- Abstract explicitly states "we do not have paired baseline/DIN-SQL runs on the 40-question expansion".
- Table 3 now splits every OOM Prevention cell into *safe-refusal rate* and *bounded-answer compliance*. Safe-refusal is 8/8 on OOM (the pipeline refuses or emits a bounded answer — it never streams a million rows), while bounded-answer compliance is 1/8. For the other five categories the two metrics coincide and are both 1.000.
- The OOM gap is no longer "reported as safer behaviour vs. benchmark criterion" in conflicting sentences; the text now names the two metrics explicitly and explains why we prefer bounded-answer behaviour operationally.

### 5. GIS benchmark 构建的 LLM 辅助偏差 — *Partially addressed.*

The benchmark construction paragraph in §4.1 already names the two residual risks: (a) model-assisted drafting may bias surface phrasing, and (b) the PostGIS operator distribution reflects Chongqing workloads. In v3 we retain and keep this disclosure. What we have **not** added in v3 is a full table of expert count, qualifications, two-person review, and per-PostGIS-operator category distribution — this is primarily because an anonymised version of that disclosure requires care to avoid identifying the authors. We will add this table to the non-anonymised version and have included a placeholder in the companion repository.

### 6. 方法描述仍偏概念化 — *Done.*

§3.8 is a new worked-example subsection (Figure 2) that shows:
- the Chinese question (transliterated to avoid CJK dependencies in the LaTeX template);
- the intent-classifier output (`spatial_measurement`, `metric=length`, `unit=km`, `language=zh`);
- the matched table, geometry column, and SRID;
- the injected PostGIS rules (`::geography` metric rule, unit-conversion rule) and one spatial-measurement few-shot example;
- the initial SQL $s^{(0)}$ (missing `::geography`);
- the execution-time feedback and the corrected SQL $s^{(1)}$;
- the gold SQL and the EX-match outcome.

The paragraph after Fig. 2 summarises the three implementation artefacts (semantic-layer YAML, intent rule set, postprocessor) and commits them to the anonymised companion repository so that the grounding behaviour is concretely reproducible.

### 7. DIN-SQL 和 baseline 公平性 — *Partially addressed.*

We state explicitly in §4.5 that DIN-SQL was re-implemented for PostgreSQL/PostGIS and evaluated on the same 85-question Spatial and 15-question Robustness pilot splits under the same execution harness. The reviewer-requested "schema-only + same self-correction" intermediate baseline is a fair and useful addition and is listed in Limitations (item 8) and Future Work; it requires an additional 85-question paired run against Gemini~2.5~Flash and we were not able to complete it within the revision window.

### 8. Cross-lingual 只能作为探索性实验 — *Done.*

- The abstract now says "because translations are model-produced, this probe is reported as exploratory, not as a generalisation claim".
- §3.9 / §4.9 both explicitly caveat translation artefacts rather than only in Limitations.
- The contribution list no longer mentions cross-lingual generalisation; it is mentioned only as one exploratory probe.
- The 0.820 Chinese GIS number and the 0.682 English GIS Spatial number are now explicitly described as *not directly comparable* because the question sets are different.

### 9. 文本与 LaTeX 细节 — *Done.*

- Abstract is 252 words (v2 was 290).
- "honestly", "camera-ready", "available on request" removed; the Reproducibility section now says "a reviewer-accessible link is provided through the editorial system for double-anonymised review".
- The garbled-byte `鈥?` found on line 404 of v2 is no longer present in v3 (no non-ASCII bytes outside comments; a full scan is included in the revision notes).
- KNN operator is now a single `\texttt{<->}` throughout; the split `\texttt{<-}\texttt{>}` is gone.
- Reproducibility explicitly states "for double-anonymised review".

---

## C. Response to Review #1 — reference-accuracy section

All references flagged as wrong have been corrected, and the 5 suggested additions have been added and used in the text.

| Old v2 entry | v3 action |
|---|---|
| `geocogent` (wrong authors/title/year) | Replaced with `houcoding2025`: Hou, Jiao, Liang, Shen, Zhao, Wu (2025), *IJGIS* 40(4):1073–1106, DOI `10.1080/13658816.2025.2549460`. Description in §2 corrected to "LLM-based agent for geospatial code generation". |
| `geoagent` (wrong authors/year) | Replaced with `lin2026geoagent`: Lin, Xu, Wu, Mao, Wang, Feng, Huang, Du (2026), *IJGIS*, DOI `10.1080/13658816.2026.2624784`. Description changed to "hierarchical LLM-based multi-agent architecture for autonomous spatial analysis". |
| `hou2025geosql` (key/year) | Renamed `hou2026geosql`; full author list Hou, Jiao, Liu, Xie, Chen, Wu, Guan, Wu (2026); *Expert Systems with Applications* vol. 320, article 132122, DOI `10.1016/j.eswa.2026.132122`. Year references throughout the text updated. |
| `ogcsfs` ISO note | Now written as "corresponding to the now-withdrawn ISO 19125-2:2004 edition". |
| `ogcgeosparql` version choice | Entry now states "we cite 1.0 because our topological predicates are normatively defined there; a GeoSPARQL 1.1 revision (OGC 22-047r1) also exists". |
| `postgis` fixed version | Entry pinned to *PostGIS 3.5 Manual* with explicit list of the primitives we rely on (`geometry/geography`, `::geography`, `ST_DWithin`, `ST_Transform`, `<->`). |
| `metricflow` "formalized" | Changed to *operationalised*; the bibitem adds a note clarifying "tool that operationalises semantic-layer modelling, not a formal specification". |
| `chen2024beaver` "near-zero accuracy" | That phrasing is removed from §2; BEAVER is now mentioned only as a benchmark list item. Bibitem adds "(revised 2025)". |
| New: `goodchild1992gis` | Goodchild, M.F. (1992) *IJGIS* 6(1):31–45. Cited in §1 to anchor the GIScience framing. |
| New: `egenhofer1991topological` | Egenhofer & Franzosa (1991) *IJGIS* 5(2):161–174. Cited in §2 as the 4-/9-intersection foundation. |
| New: `clementini1993small` | Clementini, Di Felice, van Oosterom (1993) *SSD'93* LNCS 692. Cited in §2 alongside Egenhofer for end-user topological relations. |
| New: `yu2025monkuu` | Yu et al. (2025) *IJGIS*, DOI `10.1080/13658816.2025.2533322`. Cited in §2 as directly related IJGIS-published NL-to-spatial-DB work. |
| New: `liu2025nalspatial` | Liu et al. (2025) *IEEE TKDE* 37(4):2056–2070. Cited in §2 as the most recent natural-language-interface-for-spatial-database system. |

`et al.` in the reference list has been replaced with full author names for all entries per Taylor & Francis style. URL access dates are now 7 May 2026.

---

## D. Response to Review #2 (overall: Minor to Major Revision)

Reviewer #2 flagged three major methodological items and several reference-formatting items. Several overlap with Review #1 and are handled in the same changes.

### 2.1 Ablation configuration mismatch — *Done.*

See B.2 above. Table 6 is explicitly a single-pass diagnostic and is not used to decompose the agent-loop 0.682 EX. The correct path (agent-loop-native ablation) is named in Limitations and Future Work.

### 2.2 Cross-lingual circularity (LLM translating for an LLM) — *Done.*

See B.8 above. The probe is explicitly exploratory in the abstract and the methodology, not only in Limitations. Human-verified cross-lingual data is called out as required for a generalisation claim.

### 2.3 OOM Prevention — *Reframed with explicit trade-off; engineering fix deferred with an explicit path.*

We have not reshipped the implementation within the revision window, but v3 gives the reviewer the three things asked for:

1. a clear **framing of the trade-off** between *safe refusal* and *bounded answer* (new two-column Table 3);
2. a concrete **engineering path** to bounded-answer compliance: a row-count pre-check using `EXPLAIN` estimates from the database catalogue, forcing the generator to include `LIMIT` when the estimated row count exceeds a configurable threshold (Discussion §5.1 and Future Work);
3. a statement in Limitations that we do **not** claim the 7 refusals as a positive safety result — bounded answers are the preferred behaviour on this category, and the 1/8 number reflects an engineering gap.

### 3. Minor points

- **Chongqing benchmark generalisability** (reviewer comment on Chinese administrative boundaries and POI taxonomies): acknowledged in the Benchmark construction paragraph and expanded in Limitations item (1). The manuscript now names "non-Chinese place names" explicitly as an unevaluated transfer direction.
- **Token cost vs. latency**: Table 4 caption and the Token-cost paragraph explicitly note that $13.6\times$ and $7.9\times$ token ratios translate into correspondingly higher end-to-end latency; a separate seconds-per-query column is not added in v3 because our timing data was collected under mixed queueing conditions (Gemini 429 retries) and we judge the token ratio a cleaner headline number.
- **MetricFlow context**: a one-sentence definition is now inline in §3.4, and the bibitem for MetricFlow explicitly says it "operationalises semantic-layer modelling in analytical SQL pipelines".

### 4. Reference-formatting

- `et al.` expanded to full author lists throughout (B above).
- GeoSQL-Eval year/DOI corrected (B above).
- GeoCogent and GeoAgent metadata corrected (B above).
- URL access dates updated to 7 May 2026.

---

## E. Items deferred to future work, with reasoning

We list every reviewer request that is *not* fully implemented in v3, with our reasoning:

| Request | Status in v3 | Why deferred |
|---|---|---|
| Agent-loop-native 6-way ablation | Listed as Future Work and Limitations item (4) | Requires re-running the agent-loop pipeline with six rule-disabled configurations on the full 125 questions, an estimated ~750 LLM calls with Gemini 429 risk. We considered it too invasive for the revision window; the single-pass diagnostic in v3 is framed conservatively enough that the absence of the agent-loop ablation is now a stated limitation rather than a hidden assumption. |
| 40-question Robustness paired baseline + DIN-SQL | Listed as Future Work | ~80 additional LLM calls per configuration; we decided the v3 two-metric reporting (safe-refusal vs. bounded-answer) is a truer description of current behaviour than extrapolating the 15-question pilot significance. |
| "Schema-only + same self-correction" intermediate baseline (Review #1 item 7) | Listed as Limitations item (8) and Future Work | ~85 additional LLM calls; same reasoning. |
| `EXPLAIN`-based OOM pre-check implemented and re-run | Described as the targeted next-step fix in the Discussion and Future Work; bounded-answer number 1/8 is reported as-is | We prefer to report the current behaviour accurately rather than ship a last-minute code path and re-run. |
| BIRD mini\_dev full re-evaluation | Listed as Future Work | The 150-question held-out set is already the independent test; a full mini\_dev run is strictly more of the same sampling and we judge the held-out result sufficient to make the calibrated claim we now make. |
| Human-verified cross-lingual gold | Listed as Future Work | Requires bilingual annotator pairing; not feasible within revision window. |
| Benchmark expert-panel disclosure table | Will add in the non-anonymised version | Identifying information; held back for double-anonymised review. |

We believe these deferrals are individually defensible and are listed as such in the paper, rather than silently omitted.

---

## F. What we would ask for in the next review round

Given the amount of structural change in v3, we would particularly welcome feedback on:

1. Whether the new framing (PostGIS-primary, BIRD-as-stress-test) reads convincingly to an IJGIS reviewer.
2. Whether the two-metric Robustness table and the accompanying trade-off discussion adequately replace the old single-success-rate reporting.
3. Whether the held-out BIRD CI and the Role column in the paired-McNemar table address the multiple-comparison concern.
4. Whether the worked example (Fig. 2) is sufficient to make the grounding behaviour concretely auditable, or whether we should expand it into a dedicated reproducibility appendix.

We thank both reviewers for the time and care they invested. The v3 manuscript is a substantially stronger paper because of their comments.
