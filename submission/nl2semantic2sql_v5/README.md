# NL2Semantic2SQL — Submission Bundle (IJGIS)

This directory holds the IJGIS submission artefacts for the double-anonymised review.

## Files

- `01_manuscript_v5.tex` / `01_manuscript_v5.pdf` — main manuscript (23 pages).
- `02_cover_letter_v5.tex` / `02_cover_letter_v5.pdf` — cover letter (2 pages).
- `03_response_to_reviewers_v5.md` / `03_response_to_reviewers_v5.pdf` — point-by-point response to the two 2026-05-08 review reports (5 pages).
- `supplementary_v5.tex` / `supplementary_v5.pdf` — supplementary material (6 pages).
- `references.bib` — BibTeX source, 24 entries, rendered via natbib + abbrvnat (Harvard author-date).
- `table_benchmark_profile.tex` / `fig_semantic_graph.mmd` — auxiliary inputs included from the manuscript.

## Word count

- Main text: 6988 words
- References (rendered): 570 words
- Total: 7558 words (target ≤7800 per IJGIS)
- Abstract: 181 words (target ≤220 per IJGIS)

## Headline results

**Robustness 40q (primary claim, paired).** Full 39/40 = 0.975 vs baseline 18/40 = 0.450; paired McNemar b=0, c=21, p<10^-4.

**Spatial 85q (secondary, marginal).** Three-run majority-vote EX = 0.659 (primary Spatial headline, paired McNemar p=0.052, marginal). Pooled mean ± SD 0.663 ± 0.048 across three independent Full-mode runs vs baseline 0.529.

**BIRD 150q held-out (secondary, directional only).** +0.033 EX improvement, p=0.3833, n.s., 95% CI [-0.03, 0.09].

**Cross-lingual 50q (null translation artefact).** Bilingual human re-audit of all 50 LLM-translated BIRD Chinese questions yields paired McNemar p=1.00, ruling out translation artefacts.

**Cross-family ablation (baseline-only).** On a 30q Spatial subset, Gemini-2.5-Flash baseline→full gain p=0.0312; DeepSeek-V4-Flash baseline matches Gemini-2.5-Flash baseline at EX 0.600.

**External baseline (DIN-SQL paired).** BIRD 150q held-out: Full 0.507 vs DIN-SQL 0.440 (p=0.076, marginal). Robustness 40q: Full 0.975 vs DIN-SQL 0.275 (p=7.45e-9, highly significant).

## Reproducibility

All runs use Gemini 2.5 Flash at temperature 0.0. Per-question timeout 60 s. Paired McNemar tests are two-sided exact binomial on discordant pairs. Detailed per-track configurations are in Supplement S5.

## Compile

```bash
pdflatex 01_manuscript_v5.tex
bibtex 01_manuscript_v5
pdflatex 01_manuscript_v5.tex
pdflatex 01_manuscript_v5.tex
pdflatex 02_cover_letter_v5.tex
pdflatex supplementary_v5.tex
pdflatex supplementary_v5.tex
pandoc 03_response_to_reviewers_v5.md -o 03_response_to_reviewers_v5.pdf --pdf-engine=xelatex
```
