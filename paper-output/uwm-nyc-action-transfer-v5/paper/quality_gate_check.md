# Paper Quality Gate

- [x] Each subclaim has at least one supporting result artifact.
- [x] All five planned figures exist in PDF, SVG and PNG with source CSVs.
- [x] All four planned LaTeX tables exist.
- [x] Every citation key in `main.tex` has an entry in `references.bib`.
- [x] Claim language matches S1-S4 `supported` and S5 `partially_supported` status.
- [x] Every numerical result traces to `results/` CSV or JSON files.
- [x] The primary weeks 1/2/4/8/12 result and all-12-horizon reversal both appear in the abstract, Results and Discussion.
- [x] Paired score uncertainty is distinguished from unavailable calibrated predictive intervals.
- [x] Four actions, not 67,328 rows, are described as intervention support.
- [x] No causal effect, analyst-blind, future-event, cross-city, operational or universal UWM/GWM claim is made.
- [x] Event-aware semantic forecasting prior art is cited; no absolute first claim is made.
- [x] Methods cite actual retained NYC panel and benchmark paths.
- [x] The unrelated Chongqing `data/DATA_SEEKER_REPORT.md` is explicitly excluded from NYC Methods claims.
- [x] No synthetic mobility data or fabricated public code URL is asserted.

## Post-compilation verification

- [x] `latexmk` completed successfully and produced a nonempty 22-page PDF.
- [x] The final `main.log` has zero undefined citations, undefined references, overfull boxes or fatal errors.
- [x] All five figures and four tables render in source order; no table appears after Discussion or the bibliography.
- [x] All PDF fonts are embedded.
- [x] Visual inspection found no clipping, overlap, missing graphic, orphaned heading or unresolved marker.
- [x] Both focused UWM paper tests pass.
- [x] V5 completion passes 15/15 checks; repeated validation leaves its report hash unchanged.
- [x] V6 definition passes 41/41 checks; repeated validation leaves its report hash unchanged and still reports `Activation ready: False`.

Final gate status: `PASSED_WITH_DECLARED_LIMITATIONS`
