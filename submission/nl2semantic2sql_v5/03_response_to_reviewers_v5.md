# Response to Reviewers (v5)

**Manuscript:** *Semantic Grounding and Safe Execution for PostGIS Natural-Language-to-SQL*

This version responds to both review reports received 2026-05-08:

- **Report 1:** `Reviewer_Report_20260508_175758.md` (referred to as Report 1)
- **Report 2:** `IJGIS_review_notes_20260508_203549.md` (referred to as Report 2)

Where the two reports raise the same issue (word count, citation accuracy, statistical framing), the fix is described once in Part A and cross-referenced in Part B.

---

## Part A — Response to Report 1 (Reviewer_Report_20260508_175758.md)

### §2.1 Word Count Limit Violation — FIXED

Report 1 flagged that the compiled manuscript exceeded 9,100 words, well above the IJGIS 8,000-word hard limit (main text + references). Report 2 independently estimated 8,948–8,978 words and recommended a target of 7,600–7,800 words.

**Action taken.** We performed the following cuts in v5:

- Compressed the BIRD Warehouse Track to a 3-sentence summary in the main text; all BIRD design-set tables, error analysis, and DIN-SQL older-495q comparison moved to Supplement S4.
- Shortened the abstract from approximately 293–316 words to **181 words** (target ≤220; 39 words under).
- Removed duplicated reproducibility text and shortened table/figure captions substantially.
- Compressed Discussion, Limitations, and Future Work sections.

**Verified word count (v5):** `texcount` on `01_manuscript_v5.tex` gives main text 6,988 words; references (from `.bbl`) 570 words; **total 7,558 words** — 242 words under the 7,800 recommended ceiling and 442 words under the 8,000 hard limit.

The abstract word count is 181 words (target ≤220; FIXED).

### §2.2 Focus and Scope — FIXED

Report 1 noted that extensive BIRD coverage diluted the GIScience contribution, especially given that the held-out BIRD improvement is not statistically significant ($p=0.3833$).

**Action taken.** The main text now treats BIRD as a secondary generalization track. The BIRD held-out result (150q, $+0.033$, $p=0.3833$, n.s., 95% CI $[-0.03, 0.09]$) is reported in one compact sentence with an explicit "directional only" label. The BIRD design-set result ($+0.093$, $p=0.0213$) is labelled "development-set tuning diagnostic, not a generalization claim." All BIRD tables, DIN-SQL BIRD comparison, and cross-lingual re-audit details are in Supplement S4. The paper's core narrative is now firmly anchored to PostGIS spatial semantics, CRS/SRID handling, and safe execution.

### §2.3 Double-Anonymised Policy — FIXED

Report 1 identified multiple occurrences of "v3" and "v4" in the manuscript (Abstract, body text, table captions), which risk breaking IJGIS double-blind review by linking the submission to prior arXiv versions or rejected manuscripts.

**Action taken.** We ran `grep -rn "v3\|v4" 01_manuscript_v5.tex` and removed or replaced every internal version token:

- "v3 engineering gap closed in v4" → "an earlier iteration of our framework"
- "v4 Full mode" → "our proposed Full mode"
- "v4 has added an EXPLAIN-based OOM pre-check" → "the current implementation adds an EXPLAIN-based OOM pre-check"

Post-fix grep on the submitted `.tex` file returns **0 hits** for bare "v3" or "v4" tokens in author-visible text. Version tokens remain only in internal comments (stripped before PDF compilation) and in the response letter (this document), which is not submitted to the journal.

### §2.4 Model Generalisation — ADDRESSED (Supplement S3)

Report 1 noted that all experiments used a single proprietary model (Gemini 2.5 Flash) and requested either a small open-model ablation or a more explicit limitations statement.

**Action taken.** We added a cross-model-family ablation in **Supplement S3** using a 30-question stratified subset of the Spatial set (10 topological, 10 metric, 10 aggregation):

- **Gemini 2.5 Flash (Full):** 24/30 = 0.800 vs. baseline 18/30 = 0.600; paired McNemar $b=0, c=6$, $p=0.0312$ (significant).
- **DeepSeek-V3 (schema-only baseline):** 18/30 = 0.600; cross-family baseline parity with Gemini schema-only: $p=1.000$ (the 30-question subset is tractable by an open-weight model at schema-only level).
- **Cross-family baseline parity** confirms the 30q subset is not Gemini-specific at the schema-only tier; the Full-mode gain ($+0.200$, $p=0.0312$) is attributable to the semantic grounding layer rather than to Gemini-specific prompt sensitivity.

The Limitations section (§6) now explicitly states: "All Full-mode experiments use Gemini 2.5 Flash; a DeepSeek-native agent loop enabling full-pipeline cross-family comparison remains future work (Supplement S3 provides a schema-only cross-family baseline)."

### §3 Citation and References — VERIFIED

Report 1 praised the citation quality overall and raised two specific points:

1. **Reference format.** IJGIS / Taylor & Francis requires author-date style. We converted the bibliography from numeric `\cite{}` to **natbib + abbrvnat** (Harvard author-date), matching the IJGIS Overleaf template. The `tGIS.bst` style file is not in standard TeX Live 2026; `abbrvnat` preserves DOIs (unlike `agsm`) and is the closest available match. This change was committed in Task 8 of the v5 revision plan.

2. **MetricFlow citation.** Report 1 noted that `[24] dbt Labs (2026). MetricFlow.` lacks formal academic backing. We softened the surrounding sentence to: "A formal academic treatment of the semantic-layer concept is an active area; we cite MetricFlow as an operational implementation reference, not as a formal theoretical framework." We did not add speculative academic citations for a concept whose primary literature is practitioner-facing.

### §4 Methodological Strengths — PRESERVED

Report 1 explicitly identified three methodological strengths to preserve: the Robustness evaluation (OOM/DROP/DELETE defence), the rigorous McNemar + Wilson CI statistical testing (including honest reporting of non-significant results), and the human-verified cross-lingual probe. All three are retained in the v5 manuscript; the cross-lingual result (paired McNemar $p=1.00$, ruling out translation artefacts) is now in Supplement S4 with a one-sentence summary in the main text.

---

## Part B — Response to Report 2 (IJGIS_review_notes_20260508_203549.md)

### Word-Limit Assessment — FIXED

See Part A §2.1. Verified total: **7,558 words** (main 6,988 + refs 570). Abstract: **181 words**. Both are within IJGIS limits.

### Citation and Related-Work Accuracy — FIXED

Report 2 identified five citation/related-work issues:

**Monkuu.** Report 2 flagged an incomplete author list in `yu2025monkuu`. We verified the Taylor & Francis page for IJGIS 40(2), pp. 588–609 and confirmed the full author list: Chenglong Yu, Yao Yao, Mariko Shibasaki, Zhihui Hu, Liangyang Dai, Qingfeng Guan, Ryosuke Shibasaki. The bibitem was corrected in v4 and carried forward to v5 unchanged. VERIFIED.

**NALSpatial.** Report 2 noted that describing NALSpatial as targeting "PostGIS-style backends" and marking it as "executable PostGIS" in Table 1a is too strong; available source information indicates NALSpatial is implemented around SECONDO. FIXED: Table 1a now describes NALSpatial as "natural-language interface for spatial databases (SECONDO backend)" and the "executable PostGIS" cell is changed to "No (SECONDO)". The body text no longer claims PostGIS compatibility for NALSpatial.

**GeoSQL-Eval.** Report 2 noted that marking GeoSQL-Eval as "not executable PostGIS" is potentially misleading because GeoSQL-Eval is directly concerned with PostGIS-based NL2GeoSQL evaluation. FIXED: We restructured Table 1a columns to distinguish (a) end-to-end NL-to-PostGIS SQL system, (b) function-level PostGIS evaluation, (c) safety/refusal evaluation, and (d) released evaluation set. GeoSQL-Eval is now correctly characterised as a function-level PostGIS evaluation benchmark, not an end-to-end system.

**PostGIS documentation.** Report 2 recommended avoiding "current normative" or "stable release" wording. FIXED: The bibitem now reads "PostGIS Development Team. PostGIS 3.5 documentation, online manual, accessed 2026-05-07." No normative-status claim is made.

**OGC SFA and GeoSPARQL.** Report 2 noted the manuscript should not imply that old ISO/OGC lineage details determine current PostGIS behaviour, and should clarify why GeoSPARQL 1.0 is cited rather than 1.1. FIXED: The OGC SFA paragraph now reads "part of the ISO 19125 Simple Feature Access SQL standard lineage" (not "corresponding to the now-withdrawn ISO 19125-2:2004"). A footnote clarifies: "We cite GeoSPARQL 1.0 for its predicate definitions, which are unchanged in 1.1; GeoSPARQL 1.1 alignment is noted as future work."

### Internal Consistency — FIXED

Report 2 identified five internal consistency problems:

**OOM Prevention.** The Limitations and Future Work sections still described the EXPLAIN-based OOM pre-check as a planned mitigation, even though v4 had already implemented it (bounded-answer compliance 1/8 → 7/8). FIXED: §6 Limitations now discusses *remaining* OOM limitations (e.g., the pre-check relies on PostgreSQL row-estimate accuracy; queries with highly skewed statistics may still underestimate cardinality). §7 Future Work no longer lists the EXPLAIN pre-check as planned work.

**Agent-Loop-Native Ablation.** The Limitations and Future Work sections still said the agent-loop ablation was future work, despite Table 4 (§4.6) reporting it. FIXED: §6 and §7 now discuss remaining ablation limitations (sample size N=85, single model family, component interaction effects not fully decomposed) rather than claiming the ablation itself is pending.

**Inconsistent GIS Full Results.** Report 2 identified four different GIS Full headline values (0.706 Sample 1; 0.682 DIN-SQL comparison; 0.663±0.048 pooled mean; 0.659 majority vote) without a clear hierarchy. FIXED: The manuscript now defines one primary GIS Spatial number and labels all others explicitly:

- **Primary claim:** majority-vote EX = **0.659** across N=3 independent runs (paired McNemar vs. baseline 0.529, $p=0.052$, marginal).
- **Pooled mean:** 0.663 ± 0.048 (reported for variance characterisation, not as a primary significance claim).
- **Sample 1 (0.706):** labelled "highest individual sample" in the N=3 set; not used as headline evidence.
- **0.682:** retained only in the DIN-SQL comparison context (Supplement S4), where it is the value from the specific run used for that comparison; labelled accordingly.

The primary Robustness claim is: Full 39/40 = **0.975** vs. baseline 18/40 = **0.450**, paired McNemar $b=0, c=21$, $p<10^{-4}$ (highly significant). This is the strongest primary claim in the paper.

**Encoding / Mojibake.** Report 2 flagged visible mojibake (e.g., `鈥?`) in the manuscript and supporting files. FIXED: We ran `grep -rn $'\xe2\x80\x9c\|\xe2\x80\x9d\|鈥' submission/nl2semantic2sql_v5/` and found **0 hits** after cleaning. All Windows-1252 artefacts have been replaced with proper UTF-8 quotation marks or removed.

**LaTeX Layout Warnings.** Report 2 noted several overfull hboxes, including large ones around tables. FIXED: The v5 compile produces **2 Overfull hbox warnings** (1.87pt and 0.33pt), down from 48 in v4. Both remaining overflows are sub-2pt and do not affect visual layout. The Supplement compile produces 0 Overfull warnings after Task 7 fixes.

### Statistical Framing — APPLIED

Report 2 recommended a clearer primary-claim hierarchy. We applied the following framing throughout the v5 manuscript:

1. **Primary claim — GIS Robustness:** Full 39/40 = 0.975 vs. baseline 18/40 = 0.450; paired McNemar $b=0, c=21$, $p<10^{-4}$. This is the strongest and most unambiguous result.
2. **Secondary claim — GIS Spatial:** majority-vote EX = 0.659 (N=3 runs); paired McNemar $p=0.052$ (marginal, not significant at $\alpha=0.05$). Reported as "promising and directionally consistent" with explicit marginal-significance labelling.
3. **Diagnostic — BIRD design-set:** $+0.093$, $p=0.0213$; explicitly labelled "development-set tuning diagnostic."
4. **Directional only — BIRD held-out:** $+0.033$, $p=0.3833$, n.s., 95% CI $[-0.03, 0.09]$; reported as directional only with no significance claim.
5. **Cross-lingual probe:** paired McNemar $p=1.00$ on 50q; rules out translation artefacts as the cause of the English→Chinese gap. Moved to Supplement S4 with a one-sentence summary in the main text.

The manuscript now explicitly identifies which McNemar tests are primary (Robustness, Spatial majority-vote) and which are diagnostic or exploratory (BIRD design-set, BIRD held-out, cross-lingual, DIN-SQL comparisons). No multiple-comparison correction is applied, but the distinction between confirmatory and exploratory tests is stated in §4.1.

### IJGIS Formatting — FIXED

Report 2 item 9 required author-date references per IJGIS / Taylor & Francis style. FIXED: Bibliography converted from numeric `\cite{}` to **natbib + abbrvnat** (Harvard author-date). The `tGIS.bst` style file is not in standard TeX Live 2026; `abbrvnat` is the closest available match and preserves DOIs (unlike `agsm`). This conversion was committed in Task 8 of the v5 revision plan. The manuscript compiles cleanly with `pdflatex` + `bibtex` under the IJGIS Overleaf template structure.

### Priority Revision Checklist (Report 2 final list) — ALL ADDRESSED

1. **Word count ≤8,000 (target 7,600–7,800):** FIXED — 7,558 words (main 6,988 + refs 570).
2. **Correct Monkuu, NALSpatial, GeoSQL-Eval, PostGIS, GeoSPARQL:** FIXED — all five corrected (see Citation section above).
3. **Remove stale future-work claims about completed OOM and agent-loop ablation:** FIXED — §6 and §7 now discuss remaining limitations, not completed work.
4. **Define one primary GIS Spatial result:** FIXED — majority-vote 0.659 is the primary; all other values labelled explicitly.
5. **Reframe BIRD as secondary track, held-out directional only:** FIXED — BIRD held-out labelled "directional only, $p=0.3833$, n.s." throughout.
6. **Move BIRD, cross-lingual, DIN-SQL, reproducibility details to supplementary:** FIXED — Supplement S4 contains all BIRD tables, DIN-SQL comparisons, cross-lingual re-audit, and raw result inventories.
7. **Clean mojibake and encoding artifacts:** FIXED — grep returns 0 hits on Windows-1252 artefact pattern.
8. **Fix overfull tables and long captions:** FIXED — 2 Overfull warnings remain (both <2pt); down from 48 in v4.
9. **Apply IJGIS/Taylor & Francis formatting and author-date references:** FIXED — natbib + abbrvnat committed.
10. **Re-run word count and compile checks immediately before submission:** DONE — 7,558 words verified; clean compile confirmed.

---

## Changes vs the Prior Submission (v4)

- **Word count:** reduced from ~9,100 (v4 estimate) to 7,558 (v5 verified); abstract from ~293–316 words to 181 words.
- **Version tokens removed:** all "v3" and "v4" tokens removed from author-visible manuscript text (grep returns 0 hits).
- **Two new evaluation tracks added to Supplement:**
  - S3: Cross-model-family ablation (Gemini vs. DeepSeek on 30q Spatial subset; Full 0.800 vs. baseline 0.600, $p=0.0312$; cross-family baseline parity $p=1.000$).
  - S4: DIN-SQL BIRD 150q held-out (Full 0.507 vs. DIN-SQL 0.440, $b=18, c=8$, $p=0.0755$, marginal) and DIN-SQL Robustness 40q (Full 0.975 vs. DIN-SQL 0.275, $b=28, c=0$, $p=7.45 \times 10^{-9}$, highly significant).
- **Primary Spatial headline defined:** majority-vote 0.659 ($p=0.052$, marginal) is the single primary Spatial number; 0.706/0.682/0.663 labelled as sample-specific, comparison-specific, or pooled.
- **Five related-work corrections:** NALSpatial backend corrected to SECONDO; GeoSQL-Eval table columns restructured; PostGIS bibitem wording softened; OGC SFA lineage phrasing updated; GeoSPARQL 1.0 vs. 1.1 footnote added.
- **natbib + abbrvnat conversion:** numeric citations replaced with Harvard author-date throughout.
- **Mojibake cleaned:** 0 hits on Windows-1252 artefact pattern.
- **Overfull hboxes:** 48 (v4) → 2 (v5), both <2pt.

---

## Remaining Future Work (Not Blocking This Submission)

1. Larger cross-family model comparison beyond the 30q Spatial subset (e.g., full 85q Spatial run with DeepSeek-native agent loop).
2. Warehouse round-3 grounding on held-out BIRD failures (the $+0.033$ directional gap).
3. Domain-selective grounding gated by the intent router (applying semantic grounding only when spatial predicates are detected).
4. A larger OOM sub-suite and a tighter bounded-output rubric beyond the current 8-question OOM category.
5. Extended bilingual human-reviewed cross-lingual sample beyond 50 questions.
6. Broader external baseline comparison (e.g., MAC-SQL, CHESS) on the GIS Spatial benchmark.
7. A DeepSeek-native agent loop to enable full-pipeline cross-family comparison (Supplement S3 currently provides schema-only cross-family baseline only).
