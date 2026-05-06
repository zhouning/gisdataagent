# NL2Semantic2SQL v2 Submission Bundle

**Target journal:** International Journal of Geographical Information Science (IJGIS)
**Author:** Zhou Ning, Beijing SuperMap Software Co., Ltd. (zhouning1@supermap.com)
**Submission type:** Regular research article — revised submission responding to previous review

## Bundle contents

| # | File | Description |
|---|---|---|
| 01 | `01_manuscript_v2.{pdf,tex}` | Main manuscript, 21 pages, 236 KB PDF |
| 02 | `02_cover_letter_v2.{pdf,tex}` | Cover letter with v2 change summary |
| 03 | `03_response_to_reviewers_v2.{pdf,md}` | Point-by-point response to previous reviewers |
| 04 | `04_v2_change_summary.md` | Internal change tracking / data consolidation |

## Quick data summary (v2 vs v1)

| Track | v1 result | v2 result |
|---|---|---|
| BIRD warehouse | 495q, EX $+0.027$, $p=0.136$ (NS) | 108q, EX $+0.093$, $p=0.0106$ (**significant**) |
| GIS Spatial | 85q, EX $0.682$, $p=0.0072$ | unchanged |
| GIS Robustness | 15q, $0.800$ | 40q, $32/40=0.800$; 5/6 categories = 1.000; OOM 0/8 (honest disclosure) |
| Cross-lingual | 50q preliminary stress test | 100q (BIRD 50 zh + GIS 50 zh), bounded degradation analysis |
| Ablation | Post-hoc discordant-pair attribution | 6-way controlled ablation with R2 domain-scoping finding |

## Key v2 contributions

1. **Error-attribution-driven Round-2 grounding** — identified 3 recurring BIRD failure patterns (DISTINCT, over-JOIN, output format), added 3 targeted rule sections, and achieved BIRD significance $p=0.0106$ with sample size \emph{comparable} to R1 ($101 \to 108$ questions).
2. **6-way ablation with honest negative result** — R2 rules do not aid GIS spatial queries (delta within $\pm 0.016$), establishing that rule effectiveness is domain-scoped and motivating future work on intent-gated grounding.
3. **100-question cross-lingual benchmark** — first execution-based cross-lingual text-to-SQL study spanning both GIS and warehouse tracks.
4. **Expanded Robustness 40q with OOM gap disclosure** — transparently report 0/8 failure on large-table guard, naming the root cause (intent classification miss) and the mitigation direction (orthogonal large-table guard layer).

## Reproducibility

- Release commits: `c03ece9` (R2 grounding rules), `898e975` (Robustness expansion + cross-lingual benchmark), `5fe12bd` (6-way ablation runner + paper v2 update package), `43cfd20` (v2 manuscript).
- Primary repo: internal GitLab (available on request) + public GitHub mirror (commits above).
- Eval result directories: `data_agent/nl2sql_eval_results/bird_pg_2026-05-05_123808/` (BIRD R2), `bird_pg_chinese_2026-05-05_201113/` (BIRD zh), `cq_2026-05-05_230059/` (GIS 125q), `gis_ablation_2026-05-06_060319/` (6-way).

## Submission metadata

- LLM: Gemini 2.5 Flash, temperature 0.0
- Database: PostgreSQL 16 + PostGIS 3.4
- Framework: Python 3.13, single-pass mode (no ADK agent loop)
- Statistical tool: `scipy.stats.binomtest` for one-sided McNemar exact test

## Submission checklist

- [x] Manuscript PDF compiles cleanly
- [x] Cover letter updated with revision disclosure
- [x] Response to reviewers addresses every comment
- [x] Reproducibility section lists all released artifacts
- [x] Author identification retained (IJGIS single-blind for this revision)
- [ ] Zenodo DOI deposit (planned upon acceptance)
- [ ] Anonymous reviewer link (available if editor requests double-blind)
