# ADR-035: Preserve approved negative discharge in the v2 score

- Status: Accepted
- Date: 2026-07-28
- Scope: v2 scoring only

## Context

The v2 outcome recovery retained the original USGS `00060` values and performed
no imputation. J. Percy Priest station `03430200` has 637 complete hourly target
values in the candidate window. Of these, 83 approved values are negative, from
`-5.450992969` to `-0.02145001129` m3/s. The maximum observed hourly value is
`156.0966168` m3/s.

The frozen USGS parser accepted these finite approved observations and wrote
them unchanged. The frozen scorer then stopped before writing a score because
its CSV reader imposed an additional nonnegative-observation condition.

The frozen protocol did not predeclare clipping negative observations to zero,
omitting them, replacing them, or applying a rating correction. Any such action
after outcome access would change the evaluation mask or target values.

## Decision

Preserve every finite approved negative discharge exactly as published and use
it directly in the predeclared RMSE, MAE, bias, and NSE calculations. Do not
clip, omit, transform, or impute it.

Use a recovery scorer that changes only the scorer's input-domain assertion
from "finite and nonnegative" to "finite". It must retain the sealed prediction
hashes, common complete-case mask, persistence baseline, minimum 600-hour gate,
metrics, and noncompensatory two-system gate.

## Claim effect

The numeric predictive comparison remains interpretable because neither
predictions nor observed values are altered. The process is nevertheless not a
strict frozen-code confirmatory run: both outcome acquisition and scoring
required post-outcome recovery code. The final score must set strict protocol
conformance and the prospective holdout gate to false regardless of the raw
predictive gate.

The result cannot automatically admit the operator form or validate the full
Geospatial Kernel.
