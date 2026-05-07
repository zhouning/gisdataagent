# NL2Semantic2SQL — IJGIS Submission Package (v3)

**Manuscript title:** *NL2Semantic2SQL: Semantic Grounding and Safe Execution for PostGIS-based NL2GeoSQL, with a Cross-Domain Stress Test on Warehouse Queries*

**Submission status:** Double-anonymised for IJGIS peer review. Author identity and affiliation are provided only through the editorial submission system, not in any of the files below.

## Files in this package

| File | What it is |
|---|---|
| `01_manuscript_v3.tex` | Final LaTeX source, 21 pages, 7,981 words total (incl. references). |
| `01_manuscript_v3.pdf` | Compiled manuscript PDF. |
| `02_cover_letter_v3.tex` | Cover letter to the Editor-in-Chief, anonymised. |
| `02_cover_letter_v3.pdf` | Compiled cover letter PDF. |
| `03_response_to_reviewers_v3.md` | Item-by-item response to the two external reviews on the previous version. |
| `03_response_to_reviewers_v3.pdf` | Compiled response PDF. |
| `README.md` | This file. |

## How v3 differs from v2

v2 was a "cross-domain text-to-SQL" paper with GIS and BIRD both treated as primary domains; v3 positions **PostGIS-based NL2GeoSQL** as the primary GIScience contribution, with BIRD reported on a second evaluation track that measures the warehouse path of the same bilingual framework. The structural changes:

- **Title and contributions**: narrowed to PostGIS-side. BIRD is a second evaluation track of the same bilingual framework, reported as a current-state snapshot that scopes the next warehouse-side engineering round.
- **Ablation**: the single-pass ablation is now labelled and framed as a *diagnostic*, explicitly **not** used to attribute the agent-loop 0.682 Spatial EX. An agent-loop-native ablation is listed as future work.
- **Robustness**: the 40-question table now reports two orthogonal metrics — *safe-refusal rate* and *bounded-answer compliance* — instead of a single success rate. The OOM Prevention category (bounded-answer 1/8) is explained as an engineering gap with a targeted `EXPLAIN`-based mitigation path.
- **BIRD**: 95% Wilson CIs on EX and a Newcombe-style CI on the paired-proportion difference added to Table 5. The 108-question design set is described as a *development-set tuning effect* and the 150-question held-out set is the primary BIRD significance test. The McNemar-summary table gains a Role column marking Primary / Development / Exploratory.
- **Cross-lingual**: LLM-translated Chinese BIRD probe is caveated as *exploratory* in the abstract and methodology, not only in Limitations.
- **Related Work**: rewritten to foreground IJGIS-published NL-to-spatial-database work (GeoCogent, GeoAgent, Monkuu, GeoSQL-Eval) and the IEEE TKDE NALSpatial paper as the directly related prior art, with Spider/BIRD/DIN-SQL as non-spatial backdrop. GIScience foundations (Goodchild; Egenhofer & Franzosa; Clementini et al.) are cited.
- **Worked example** added (§3.8, Figure 2): traces a single Chongqing benchmark question through every stage — NL → intent → SRID/geometry → injected PostGIS rules → initial SQL → execution error → self-corrected SQL → gold — so that the grounding behaviour is concretely auditable.
- **References**: 22 entries (up from 19 in v2). GeoCogent / GeoAgent / GeoSQL-Eval metadata corrected. Goodchild 1992, Egenhofer & Franzosa 1991, Clementini et al. 1993, Monkuu 2025, NALSpatial 2025 added. `et al.` expanded to full author lists per Taylor & Francis style. URL access dates updated to 7 May 2026. ISO 19125-2:2004 noted as withdrawn; PostGIS pinned to 3.5; MetricFlow re-described as "operationalising" rather than "formalizing" the semantic layer.
- **Anonymisation**: author name, affiliation, and email removed; commit hashes previously visible in the Reproducibility section removed; reviewer-accessible repository link is provided through the editorial system only.
- **Language polish**: "honestly", "camera-ready", "available on request", and process-language ("previous version", "Phase A", "v1/v2") removed. KNN operator is written as a single `\texttt{<->}`. Abstract compressed from ~290 words to 252.

## Key numbers at a glance

| Metric | Result |
|---|---|
| Total word count (incl. references) | 7,981 (within IJGIS ~8,000 limit) |
| Abstract word count | 252 |
| Page count | 21 |
| Primary GIS Spatial EX (85q) | 0.682 vs. baseline 0.529; paired McNemar two-sided exact *p* = 0.0072; +0.153 |
| GIS Spatial vs. DIN-SQL | +0.118; *p* = 0.0213 |
| Robustness 40q safe-refusal | 40/40 = 1.000 |
| Robustness 40q bounded-answer | 33/40 = 0.825 (OOM category bounded-answer 1/8) |
| BIRD 108q design set | 0.593 vs. 0.500; *p* = 0.0213 (development-set tuning) |
| BIRD 150q held-out (primary) | 0.507 vs. 0.473; *p* = 0.3833, **not significant**; 95% CI on Δ: [−0.03, 0.09] |

## Compiling the LaTeX sources

```bash
# Manuscript (pdflatex, 2 passes)
pdflatex 01_manuscript_v3.tex
pdflatex 01_manuscript_v3.tex

# Cover letter
pdflatex 02_cover_letter_v3.tex

# Response to reviewers (needs XeLaTeX for CJK in a few reviewer quotes)
pandoc 03_response_to_reviewers_v3.md \
  -o 03_response_to_reviewers_v3.pdf \
  --pdf-engine=xelatex \
  -V geometry:margin=1in -V fontsize=11pt \
  -V CJKmainfont="Microsoft YaHei" -V mainfont="Times New Roman"
```

## Pre-submission checklist

- [x] Word count within the 8,000-word IJGIS limit (7,981).
- [x] Abstract within 250 ± a few words (252).
- [x] Double-anonymised: no author name, affiliation, email, or commit hash in any PDF.
- [x] All reference metadata externally verified (GeoCogent, GeoAgent, GeoSQL-Eval, Monkuu, NALSpatial, Egenhofer, Clementini, Goodchild).
- [x] `et al.` expanded to full author lists throughout the bibliography.
- [x] Single primary LLM (Gemini 2.5 Flash) disclosed as a limitation.
- [x] Two-metric Robustness reporting (no conflation of safe-refusal with bounded-answer).
- [x] BIRD held-out is the primary warehouse test; design-set significance is framed as tuning effect.
- [x] Worked example (Figure 2) present.
- [x] Anonymised reviewer link to be provided through the editorial submission form.
- [ ] Submit via Taylor & Francis IJGIS portal.
- [ ] Paste cover-letter body into the portal's cover-letter field; upload the PDF version as a supplementary file.
- [ ] Upload response-to-reviewers PDF as a supplementary file.
