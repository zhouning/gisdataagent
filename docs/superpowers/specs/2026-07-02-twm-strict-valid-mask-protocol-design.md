# TWM Strict Valid Mask Protocol Design

Date: 2026-07-02
Scope: Dynamic World / public land-cover TWM vs FLUS benchmark protocol

## Goal

Remove the inherited holdout-availability caveat from TWM/FLUS benchmark
prediction paths by separating prediction-time valid masks from evaluation-time
valid masks.

## Problem

The current benchmark uses one `valid` mask built from train start, train end and
holdout frames. That is acceptable for pixel-metric evaluation, but it lets
holdout availability influence prediction packaging, demand projection and TWM
allocation masks. Even when the current 100-case manifest happens to have no
prediction/evaluation mask difference, the protocol should not depend on that
accident.

## Design

- Treat `case.valid` as the prediction-time mask for backward compatibility.
- Build `case.valid` from train start and train end only.
- Add an evaluation mask accessor that returns a separate holdout-aware mask.
- Use the prediction mask for:
  - FLUS `landuse`, `restrict`, ANN training anchors and probability cubes;
  - TWM `model_inputs["valid"]`;
  - forecast demand and train-derived transition statistics.
- Use the evaluation mask for:
  - FLUS/TWM pixel metrics;
  - report `valid_cell_count`;
  - holdout oracle counts used only for evaluation diagnostics.
- Report both `prediction_valid_cell_count` and `evaluation_valid_cell_count`.

## Claim Boundary

This is protocol hardening, not a new algorithmic scoring claim. It makes later
GeoSOS/FLUS superiority claims cleaner by ensuring prediction-time mechanics do
not inspect holdout label availability.

## Acceptance

- A case with a holdout nodata cell still packages/predicts over train-valid
  cells.
- The same case evaluates metrics only where holdout labels are valid.
- Existing all-valid cases keep the same results.
- Dynamic World / FLUS focused tests pass.
