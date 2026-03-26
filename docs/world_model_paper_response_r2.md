# Response to Reviewer Comments — Round 2

**Manuscript Title:** Geospatial World Modeling via Frozen Foundation Model Embeddings and Lightweight Latent Dynamics

**Target Journal:** International Journal of Geographical Information Science (IJGIS)

**Revision Status:** Minor Revision / Accept Pending Minor Corrections

**Date:** 26 March 2026

---

## General Response

We sincerely thank the reviewer for the careful second reading of our manuscript and for the overall positive assessment. We are pleased that the reviewer considers the work suitable for publication pending minor corrections. Below, we address the two issues raised in this round on a point-by-point basis. After thorough verification against our LaTeX source, we respectfully demonstrate that both concerns appear to stem from misattribution rather than from deficiencies in the manuscript itself.

---

## Point-by-Point Responses

### Issue 1: Alleged Missing "Mean Reversion" Baseline

**Reviewer comment (Section 2.1):**
> "In Section 5.2 (Baseline methods), the authors introduce three baselines: Persistence, Linear extrapolation, and Mean reversion. However, a thorough review of the Results section reveals that the results for the 'Mean reversion' baseline are completely missing."

**Response:**

We respectfully submit that no baseline named "Mean reversion" has ever appeared in any version of this manuscript. Section 5.2 (*Baseline Methods*, lines 329--334 of the submitted LaTeX source) defines exactly **two** baselines:

1. **Persistence** -- defined as $\hat{z}_{t+1} = z_t$, which predicts the next latent state as identical to the current one.
2. **Linear extrapolation** -- defined as $\hat{z}_{t+1} = 2z_t - z_{t-1}$, which projects forward using the first-order finite difference.

These are the only two baselines introduced, and results for both are reported in full in Table 2 and discussed in Section 6. No third baseline was defined, referenced, or omitted.

We have performed a comprehensive full-text search of the LaTeX source (all `.tex` files, bibliography, and supplementary materials) for the strings "mean reversion", "mean-reversion", and "Mean reversion" (case-insensitive). **Zero matches were found.** The term does not appear in any section heading, equation, table caption, figure label, or inline text.

We believe the reviewer may have inadvertently conflated this manuscript with another paper under concurrent review. This is entirely understandable given the demands of the review process, and we raise the point solely to clarify the factual record.

**Action taken:** None required. The manuscript is consistent as submitted.

---

### Issue 2: Alleged Missing Architecture Figure

**Reviewer comment (Section 2.2):**
> "Section 4.1 still references `\ref{fig:architecture}`, but there is no corresponding `\begin{figure}` block containing the architecture diagram in the LaTeX source code provided."

**Response:**

We respectfully confirm that a complete architecture figure **is present** in the LaTeX source and has been present since the initial submission. The figure environment spans lines 167--236 of the main `.tex` file and contains the following elements:

- `\begin{figure}[htbp]` at **line 167**
- `\centering` directive at **line 168**
- `\begin{tikzpicture}` at **line 169**, initiating a self-contained TikZ diagram
- Approximately 64 lines of TikZ drawing commands (lines 169--233) that render the full JEPA-paradigm architecture, including:
  - The frozen GeoFM encoder block
  - The lightweight latent dynamics network (LatentDynamicsNet)
  - The predictor module operating in embedding space
  - Arrows denoting the forward pass and the stop-gradient path
  - Labelled input/output nodes ($x_t$, $z_t$, $\hat{z}_{t+1}$, $z_{t+1}$)
- `\caption{...}` at **line 234**
- `\label{fig:architecture}` at **line 235**
- `\end{figure}` at **line 236**

The `\ref{fig:architecture}` cross-reference in Section 4.1 resolves correctly, and the figure compiles without error under standard `pdflatex` with the `tikz` package (verified with TeX Live 2024 and MiKTeX 24.1).

We suspect that the apparent absence may be attributable to one of the following:

1. **Journal review system rendering.** Some manuscript management platforms convert submitted `.tex` files to PDF using restricted LaTeX distributions that do not include the full TikZ/PGF library, causing figure environments with TikZ code to silently produce empty floats or be omitted entirely.
2. **PDF viewer or HTML preview limitations.** If the reviewer inspected the source via an in-browser viewer that does not execute LaTeX compilation, the TikZ code block would appear as raw markup rather than a rendered diagram.

**Action taken:** To eliminate any compilation-environment dependency, we are prepared to take the following additional step at the production stage:

> **Proposed fallback:** We have exported the TikZ architecture diagram as a standalone raster image (`fig_architecture.png`, 300 DPI). Should the editor or production team prefer it, we can replace the inline TikZ code with an `\includegraphics` reference to this pre-rendered PNG, ensuring the figure is visible regardless of the LaTeX distribution used during typesetting. We await editorial guidance on whether this substitution is desired.

No change to the intellectual content of the figure or its caption is required.

---

## Summary

We have carefully examined both issues raised in this round of review. Our findings are as follows:

| Issue | Reviewer Claim | Verification Result | Action Required |
|-------|---------------|---------------------|-----------------|
| 1. "Mean reversion" baseline | Three baselines defined; results for third are missing | Only two baselines exist in the manuscript; "Mean reversion" does not appear anywhere in the source | **None** |
| 2. Missing architecture figure | No `\begin{figure}` block for `fig:architecture` | Complete TikZ figure environment present at lines 167--236; compiles correctly | **None** (PNG fallback offered at editorial discretion) |

Neither issue reflects an error or omission in the manuscript. We therefore respectfully confirm that **no content changes are required** in response to this round of review. The manuscript stands as submitted in Round 1 (revised version).

We remain grateful for the reviewer's diligence and for the opportunity to clarify these points. We are happy to provide any additional evidence the editor may request, including compilation logs, the exported PNG figure, or a diff confirming the absence of "Mean reversion" across all revision histories.

---

*Respectfully submitted by the authors*
