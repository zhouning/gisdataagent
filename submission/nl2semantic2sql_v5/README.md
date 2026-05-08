# NL2Semantic2SQL v4 submission bundle

**Manuscript**: Semantic Grounding and Safe Execution for PostGIS Natural-Language-to-SQL
**Target venue**: *International Journal of Geographical Information Science* (IJGIS)
**Submission type**: Regular research article, double-anonymised peer review
**Version**: v4 (2026-05-08)

## Files

- `01_manuscript_v4.tex` / `01_manuscript_v4.pdf` — main manuscript (~22 pages incl. bib)
- `02_cover_letter_v4.tex` / `02_cover_letter_v4.pdf` — cover letter (1 page)
- `03_response_to_reviewers_v4.md` / `03_response_to_reviewers_v4.pdf` — point-by-point response to four review reports (5 pages)
- `table_benchmark_profile.tex` — auto-generated 85q benchmark composition table (consumed by §4.1 via `\input{}`)
- `fig_semantic_graph.mmd` — Mermaid source for the G=(V,E) figure (§3.1)

## Primary claims

- **Robustness (strongest)**: 40-question Robustness suite reaches 0.975 vs. baseline 0.450 (paired McNemar p<10^-4). OOM Prevention bounded-answer compliance improves from v3 1/8 to v4 7/8.
- **Spatial (N=3 pooled)**: mean+/-SD 0.663+/-0.048 (range [0.612, 0.706]); majority-vote 0.659, p=0.052 (marginal). Two of three individual samples significant (p=0.003, p=0.029).
- **Ablation**: semantic grounding -0.118 (p=0.006) and self-correction -0.106 (p=0.023) are statistically significant on Spatial EX; intent routing, postprocessor, and few-shot are not (p=0.774 each).
- **Middle baseline**: schema-only + pp + retry reaches 0.565 (+0.036 over baseline, n.s.); Full's additional +0.098 over middle (p=0.004) attributes gain to semantic grounding, not generic scaffold.

## Companion code artifacts (released with v4)

- `data_agent/semantic_graph.py` — metadata graph G=(V,E) reference implementation (Section 3.1 Algorithm 1 mirrors this 1:1)
- `data_agent/sql_postprocessor.py::explain_row_estimate()` — EXPLAIN-based OOM pre-check
- `scripts/nl2sql_bench_cq/run_ablation_agentloop.py` + `run_single_ablation_config.py` — agent-loop-native ablation harness
- `scripts/nl2sql_bench_cq/run_schema_only_baseline.py` — schema-only middle baseline driver
- `scripts/nl2sql_bench_cq/benchmark_profile.py` — auto-generates Table 1b
- `scripts/nl2sql_bench_cq/crosslingual_review_tool.py` — CSV exporter for the bilingual cross-lingual review

## Eval artifacts

All raw JSON records (per-question execution accuracy, prompts, generated SQL, timings) are available in `data_agent/nl2sql_eval_results/`:

- `cq_2026-05-08_090919/` — v4 final 125q both-mode run (baseline + full)
- `ablation_agentloop_2026-05-07_233516/` — 6-config ablation
- `schema_only_baseline_2026-05-08_083521/` — middle baseline
- `full_resample_2026-05-08_1040/` — third Full sample for N=3 pooling
- `cq_2026-05-06_133518/` — pre-v4 baseline snapshot (SHA for integrity verification)

## Reproduction

```bash
# Setup
export PYTHONPATH=D:/adk
source .venv/Scripts/activate
# Main eval (baseline + full)
python scripts/nl2sql_bench_cq/run_cq_eval.py --mode both --benchmark benchmarks/chongqing_geo_nl2sql_100_benchmark.json
# Ablation
bash scripts/nl2sql_bench_cq/run_ablation_orchestrator.sh
# Middle baseline
python scripts/nl2sql_bench_cq/run_schema_only_baseline.py
# Pooling stats
python scripts/nl2sql_bench_cq/pool_full_samples.py
```

Each driver is resume-safe (partial files preserved on SIGTERM/SIGKILL) and respects a per-question `CQ_EVAL_QUESTION_TIMEOUT` env var (default 90s) to bound agent-loop hangs.

## Outstanding (first-revision candidates)

- Cross-lingual 50q rerun after bilingual human review (CSV at `benchmarks/bird_chinese_50q_review.csv`)
- DIN-SQL rerun on BIRD 150q held-out + GIS Robustness 40q paired evaluation
- Additional Full-mode samples beyond N=3 for tighter significance
