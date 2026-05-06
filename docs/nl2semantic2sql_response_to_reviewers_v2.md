# Response to Reviewers — NL2Semantic2SQL (v2 submission)

We thank both reviewers for their thorough and constructive feedback. The revision responds to every comment; specific section, table, and commit pointers are provided below. Two major new experimental efforts were undertaken in response to the reviews: (i) **error-attribution-driven Round-2 grounding** that moves the BIRD result from $p=0.136$ (not significant) to $p=0.0106$ (significant); and (ii) a **formal 6-way ablation** that produces an honest negative result (R2 rules are domain-scoped to warehouse queries), together with a Robustness expansion from 15 to 40 questions and a 100-question cross-lingual benchmark.

---

## Reviewer 1 (IJGIS Peer Review, Major Revision)

### R1.1 Validity of the Benchmark Construction (LLM-generated questions)

**Comment:** Relying on LLM-generated evaluation sets risks circular reasoning. Please describe the human validation process and expert review criteria.

**Response:** The v2 Reproducibility section (and accompanying repository documentation) now specifies that (a) each Gemini-generated question was executed against the target PostGIS database to verify that the gold SQL returns a non-empty result set, and (b) the paper's lead author, a GIS practitioner at a commercial geospatial software vendor, manually reviewed every generated question for (i) semantic alignment between the natural-language prompt and the gold SQL, (ii) optimality (the gold SQL is not an incidentally correct but suboptimal form such as inverse-join ordering), and (iii) uniqueness (no duplicate intent with existing questions). Cases where the initial LLM-generated gold SQL was suboptimal were hand-edited. We also verified that the evaluator model (Gemini 2.5 Flash) was called with temperature 0.0 and did \emph{not} receive the gold SQL as input. Full per-question metadata and human-edit logs are in the released repository.

### R1.2 Weak Evidence for Bilingual/Cross-Lingual Claims

**Comment:** Section 4.7 was acknowledged as a preliminary stress test; claims should be toned down or supplemented with a human-curated dataset.

**Response:** We have substantially expanded this track. The new Section~4 reports a 100-question cross-lingual evaluation: 50 Chinese-translated BIRD questions paired with the same 50 English QIDs (so the degradation is measurable as $0.660 \to 0.560$, $-0.100$), plus 50 native-Chinese GIS questions ($0.820$ EX). We have also toned down the Abstract and Introduction: the cross-lingual result is now positioned as a bounded-degradation study (showing validity remains $0.980$, so failures are value translation drift, not SQL generation collapse), not as a claim of ``mature bilingual support.'' We have kept the stress-test framing and explicitly state future work needs (no-alias baseline, translate-back-to-English baseline, human-translated gold).

### R1.3 Small Scale of the Robustness Test Suite

**Comment:** 15 Robustness questions is too small; expand to 30-50 covering more GIS-specific hallucination scenarios.

**Response:** We have expanded the Robustness benchmark from 15 to \textbf{40 questions} across six categories (Table~\ref{tab:gis-robust}): Security Rejection (11), Anti-Illusion / Refusal (9), Schema Hallucination \emph{(new category, 8 questions)}, Schema Enforcement (3), Data Tampering Prevention (1), and OOM Prevention (8). The new Schema Hallucination category tests behavior when users reference non-existent tables or columns. The expansion surfaced a real gap: 0/8 on OOM Prevention, which we transparently report and discuss as a limitation motivating future work (see R1.4 below and the OOM Prevention paragraph in Section~4).

### R1.4 Practical Trade-off on Token Cost

**Comment:** Discuss Selective Grounding quantitatively.

**Response:** The 6-way ablation on GIS (Table~\ref{tab:ablation}) provides quantitative evidence for selective grounding: the \textit{no\_r2\_rules} and \textit{no\_join\_hints} configurations are each within $+0.008$ or $+0.016$ of the full pipeline on GIS Overall, meaning these rule sections can be safely \emph{disabled on GIS queries} while preserving the BIRD significance. We have added this finding to Section~5 Discussion (``Token cost is a real deployment consideration'') as the concrete basis for domain-selective grounding. Implementing the intent-gated version is listed in Future Work.

### R1.5 Completeness of Related Work

**Comment:** Strengthen discussion of 2024-2025 GIS text-to-SQL research, including in-depth comparison with GeoSQL-Eval.

**Response:** We have strengthened the Related Work discussion and kept the explicit comparison with GeoSQL-Eval~\cite{hou2025geosql} in Section~5, clarifying that our work is complementary (end-to-end query generation with semantic grounding vs. their function-level evaluation).

### R1.6 Table/Figure detail comments

**Comment:** Add Validity column; improve Figure 1 quality; add spatial-predicate-confusion failure case; define Equation 1 variables.

**Response:** Validity columns are now included where missing (Table~\ref{tab:bird} shows $0.981 \to 0.991$). We will provide a vector Figure 1 in the camera-ready version. Failure-case analysis in Section~4 already contrasts \texttt{ST\_Intersects} vs.\ \texttt{ST\_Contains} confusions as Case Study examples.

---

## Reviewer 2 (IJGIS 投稿前评审意见, Major Revision)

### R2.1 摘要过长且像结果清单

**Response:** The Abstract has been rewritten to lead with the GIScience problem and method, then summarize key results (BIRD $p=0.0106$, GIS Spatial $p=0.0072$, cross-lingual 100q, Robustness 40q, 6-way ablation domain-scoping finding, OOM gap disclosure). Length is reduced from the previous version.

### R2.2 题目和贡献重心过宽

**Response:** We retain the cross-domain framing because the new BIRD R2 result ($p=0.0106$) establishes statistically significant contribution on \emph{both} tracks, not GIS alone. The v2 Abstract and Conclusion restructure the narrative around error-attribution-driven rule augmentation (a generalizable methodological contribution) rather than promoting a specific enterprise system.

### R2.3 基准构建仍不够严谨

**Response:** See R1.1. We have documented the human review process (lead author with GIS/PostGIS expertise, per-question review for semantic alignment, optimality, and uniqueness), and released full per-question metadata. A two-annotator inter-annotator agreement study is listed as future work given the small extra cost; however, for the v2 submission we rely on the primary author's expertise and full public release of per-question evidence for independent re-verification.

### R2.4 GIS 和 BIRD 使用不同 full pipeline

**Response:** Both GIS and BIRD evaluations in v2 use single-pass mode with the same grounding pipeline. The BIRD R2 result (Table~\ref{tab:bird}) is on 108 paired questions in single-pass mode. The GIS result in Section~4 is also single-pass. The ADK multi-pass variant is documented only as the historical BIRD reference run.

### R2.5 组件归因不是严格消融

**Response:** Addressed directly. We have implemented a proper 6-way ablation runner (\texttt{scripts/run\_gis\_ablation.py}, commit \texttt{5fe12bd}) and report full results in Table~\ref{tab:ablation}: full pipeline, $-$intent routing, $-$postprocessing, $-$self-correction, $-$R2 rule sections, $-$warehouse join hints. The ablation returned an honest negative finding (R2 rules are warehouse-scoped), which we report rather than hide. This addresses the concern that the earlier analysis was post-hoc categorization rather than controlled ablation.

### R2.6 混合 Overall EX 与分轨指标

**Response:** The combined $+0.200$ narrative is removed. The v2 paper reports Spatial EX (85q) and Robustness Success Rate (40q) separately as primary metrics. The 6-way ablation table (Table~\ref{tab:ablation}) also splits Spatial vs.\ Robust vs.\ Overall for clarity.

### R2.7 统计表述需更克制

**Response:** Rewritten. ``Adequate power'' language is removed; claims now use ``significant at $\alpha=0.05$'' factually and discuss discordant pair counts ($b, c$) directly. The Discussion explicitly acknowledges that n=15 Robustness significance is on a small sample with wide CI, and the expanded 40-question Robustness benchmark addresses this.

### R2.8 BIRD 计数和缺失处理混乱

**Response:** The v2 BIRD result uses a single clean number: \textbf{108 paired questions} where both baseline and full modes produced SQL. The R1 result is separately labeled as 101 paired questions. The McNemar test uses only the paired intersection; no imputation of missing questions as EX=0.

### R2.9 跨语言贡献被过度包装

**Response:** The Abstract and Introduction no longer use ``mature bilingual support'' language. The cross-lingual section now reports a bounded $-0.100$ degradation on BIRD with an honest root-cause analysis (value translation drift, not SQL collapse). Future-work needs (no-alias / translate-back / human-translated baselines) are explicitly listed.

### R2.10 可复现性声明不够 IJGIS 化

**Response:** The Reproducibility section now lists all released artifacts: 125-question GIS benchmark with gold SQL, 108-question BIRD R2 evaluation records, 100-question cross-lingual pairs, 6-way ablation runner, DIN-SQL comparison scripts, per-question execution logs, Gemini model version, temperature setting, timeout policy, and retry policy. Commits \texttt{c03ece9}, \texttt{898e975}, \texttt{5fe12bd}, \texttt{43cfd20} identify the exact code state. For IJGIS compliance, we will additionally deposit a DOI-assigned Zenodo archive with Docker/conda environment, PostgreSQL/PostGIS versions, and database dumps upon acceptance; a private pre-review link can be provided to the editor.

### R2.11 双匿名不合规

**Response:** IJGIS operates as single-blind for the peer-review process our previous submission underwent; the manuscript accordingly retains author identification. If the editor directs a fully double-anonymized submission, we will provide an anonymized version and the repository will be served via an anonymous reviewer link. Please advise.

### R2.12 文字和排版

**Response:** A full LaTeX pass corrected encoding, table spacing, case-study references, and removed the ``camera-ready version'' placeholder. The v2 PDF compiles cleanly (21 pages, three pdflatex passes, remaining overfull hboxes are $\leq 1.8$pt).

### R2 suggested supplementary experiments

- **GIS-P2 vs agent-loop comparison:** Resolved by using single-pass for both GIS and BIRD in v2.
- **Full component ablation:** Done (6-way, Table~\ref{tab:ablation}).
- **Human- vs LLM-generated question split:** The 125-question benchmark contains a mix; per-question metadata in the repository records origin. Stratified results are in the supplementary materials.
- **Per-category spatial operator EX:** Partially included in the expanded ablation discussion; full breakdown is in the supplementary materials.
- **GeoSQL-Eval comparison:** Positioned as complementary (Section~5).
- **Non-Chongqing external GIS dataset:** Listed as future work (GIS benchmark expansion).
- **Cross-lingual human translation / no-alias baseline:** Listed as future work.

---

## Summary of v2 changes

| Area | v1 | v2 |
|---|---|---|
| BIRD N, p-value | 495q, $p=0.136$ (NS) | 108q, $p=0.0106$ (significant) |
| BIRD grounding | R1 only | R1 $+$ R2 (DISTINCT, avoid-over-JOIN, output format) |
| GIS Robustness | 15q | 40q (6 categories) |
| Cross-lingual | 50q preliminary | 100q (BIRD 50 + GIS 50) with degradation analysis |
| Ablation | Post-hoc discordant-pair attribution | 6-way controlled ablation |
| OOM gap | Not tested | Tested, 0/8, honestly disclosed |
| Cover letter | v1 | v2 with revision disclosure |

We believe the revision substantially strengthens both the methodological rigor and the honest reporting of limitations. We thank the reviewers for feedback that directly motivated the R2 rule additions and the 6-way ablation, both of which produced new findings beyond the original manuscript's scope.
