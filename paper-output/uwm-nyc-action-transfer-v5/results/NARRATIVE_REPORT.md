# Narrative Report: NYC Multi-Action Transfer Stress Test

Experiment status: `COMPLETE_WITH_MANDATORY_CAUTIONS`

Plan: `plan-output/uwm-nyc-action-transfer-v5/PAPER_PLAN.md`

Novelty decision: `PASS_WITH_NARROWED_CONTRIBUTION`

## Evidence Summary

The frozen V5 benchmark is complete and reproducible, but the evaluated
action-conditioned DAM-GK configuration does not show stable transfer across
the four admitted NYC yellow-taxi fare actions. Under the preregistered
weeks 1/2/4/8/12 metric, its error is 0.368389, compared with 0.362616 for
History AR and 0.361416 for Spatial AR. It improves two actions, degrades two,
has mean fold skill of -2.52%, and passes 0/8 frozen transfer gates.

This result is not uniformly negative across horizon weighting. The candidate
loses to both autoregressive baselines in six of seven fixed sensitivity
specifications, but beats both when all 12 horizons are equally weighted.
That reversal must appear in the main paper.

Score-difference bootstrap uncertainty is available from 20,000 paired draws.
Calibrated predictive intervals are not available: V5 retained scalar inner-
fold validation metrics, but not residual-level cross-fitted training-action
predictions. Three held-out seed predictions measure ensemble spread and must
not be presented as calibrated uncertainty.

## S1: Reproducible And Leakage-Resistant Model Boundary

Statement: The benchmark is reproducible and leakage-resistant at the declared
model boundary.

Support status: `supported`

Key results:

- All 15 paper-level integrity checks pass.
- Predictions were committed before evaluator access.
- All required predictions replay without target access.
- The evaluator, protocol, runtime, submission contracts and scored prediction
  hashes match their commitments.
- All 11 required submissions and all eight frozen gates were evaluated, and
  the failure status was published rather than suppressed.

Evidence: `benchmark_integrity.csv`, `evidence_inventory.csv`,
`frozen_evidence_summary.json`; Figure 1 for the four-action design.

Interpretation: The reported negative result is a completed benchmark outcome,
not an interrupted training run or a missing-output failure.

Boundary: The benchmark is model-held-out, not analyst-blind. Analysts had seen
parts of the 2015 and 2025 outcome history. The integrity evidence does not
establish causal identification or future-event validity.

## S2: No Stable Cross-Action Advantage

Statement: The evaluated action-conditioned configuration lacks stable
cross-action advantage over strong historical dynamics.

Support status: `supported`

Key results:

- Correct-action error: 0.368389.
- History AR error: 0.362616; candidate-minus-history: +0.005773.
- Spatial AR error: 0.361416; candidate-minus-spatial: +0.006973.
- Mean event skill versus History AR: -2.52%.
- Improved actions: 2/4; frozen transfer gates passed: 0/8.
- The candidate loses to both AR baselines in 6/7 fixed sensitivity
  specifications.
- When all 12 horizons are equally weighted, the candidate scores 0.379255,
  versus 0.383750 for History AR and 0.383072 for Spatial AR, reversing both
  pairwise rankings.

Evidence: `primary_scores.csv`, `fold_skill.csv`, `gate_summary.csv`,
`metric_sensitivity_contrasts.csv`, `metric_sensitivity_summary.json`;
Figures 2, 3a and 5; Tables 1, 2 and 4.

Interpretation: The preregistered primary result and most fixed alternatives do
not support a reliable action-conditioned gain. The all-12-horizon reversal
also shows that uniform inferiority is not supported. The defensible statement
is unstable, horizon-weighting-sensitive transfer.

Boundary: This is not evidence that every UWM architecture fails. It evaluates
one frozen configuration on four known NYC yellow-taxi actions. It is not a
future, cross-city or operational forecast claim.

## S3: Correct Action Semantics Are Not Reliably Preferred

Statement: The evaluated model does not reliably identify correct action
timing, components and spatial scope.

Support status: `supported`

Key results:

- Four of seven corrupted actions have lower overall error than the correct
  action: date +4 weeks, action deleted, exposure shuffled and components
  permuted.
- The best submission is the date +4 weeks control at 0.358918.
- Correct action minus date +4 weeks error is +0.009471, with paired bootstrap
  interval [0.005853, 0.013101].
- No correct-versus-control comparison is won in all four event folds; fold-win
  counts range from one to three.
- The correct action does beat date -4 weeks, cross-event action swap and wrong
  spatial scope overall, so the model is not completely insensitive to every
  action corruption.

Evidence: `action_controls.csv`, `primary_scores.csv`; Figure 4; Table 3.

Interpretation: Correct action semantics are not consistently selected over
plausible corruptions. The winning +4-week control indicates that nominal
timing was not robustly identified.

Boundary: The +4-week result is not proof that the real policy took effect four
weeks late. It may reflect adaptation, concurrent shocks, model misspecification
or a control that approximates an omitted lag.

## S4: Failure Is Structured By Event, Target And Horizon

Statement: Transfer behavior is heterogeneous rather than a uniform model
collapse.

Support status: `supported`

Key results:

- Event skills versus History AR are -15.35% (2015), -13.91% (2019), +10.78%
  (2022) and +8.39% (2025).
- All four targets worsen in 2015 and 2019 and improve in 2022 and 2025.
- Aggregated across events, pickup count improves marginally
  (candidate-minus-history -0.000118), while dropoff count (+0.008047), CBD
  inflow (+0.008032) and CBD outflow (+0.007130) worsen.
- On preregistered horizons, weeks 1 and 2 worsen, while weeks 4, 8 and 12
  improve. Non-reported intermediate weeks drive the all-12-horizon reversal.

Evidence: `fold_skill.csv`, `error_decomposition.csv`, `horizon_profile.csv`;
Figures 3 and 5.

Interpretation: The average result combines large early-event losses with
later-event gains and strong horizon dependence. Reporting only the aggregate
would conceal the scientific pattern.

Boundary: Cross-year differences, concurrent shocks and changing taxi demand
can explain part of this heterogeneity. These descriptive contrasts do not
identify policy effects.

## S5: Effective Intervention Support Is Four Actions

Statement: Zone-week row count cannot be interpreted as independent
intervention support.

Support status: `partially_supported`

Key results:

- Independent action events: 4.
- Training actions per fold: 3.
- Zones per event: 263; weeks per event: 64.
- Rows per event: 16,832; total zone-week rows: 67,328.
- Each fold therefore has 50,496 training rows but only three training actions.

Evidence: `support_units.csv`; Figure 1.

Interpretation: The experimental hierarchy makes the action event, not the
zone-week row, the transfer unit. Large row counts improve within-event error
measurement but do not create additional independently varied policies.

Boundary: The benchmark records the hierarchy and reports every event, but four
events are too few to estimate a population distribution of urban actions.
This supports a pseudoreplication caution, not a theorem that node-level
exposure contains no useful variation.

## Novelty Boundary

The focused audit admits only a narrow contribution. Continual traffic
forecasting, cross-city transfer, public-event mobility prediction and semantic
text fusion are established. SeMob, Event Traffic Forecasting, LLM-MPE and
FUSE-Traffic are direct event-aware precedents.

Within the covered sources, no screened work combined documented policy-action
leave-one-out folds, prediction commitment/replay, strong historical baselines
and frozen corruptions of action date, components, identity, exposure and
spatial scope. This scoped distinction may be stated; an absolute first claim
may not.

Evidence: `docs/research/UWM_NYC_ACTION_TRANSFER_NOVELTY_AUDIT.md` and
`docs/research/UWM_NYC_ACTION_TRANSFER_QUERY_LEDGER_2026-07-24.json`.

## Writer Contract

The manuscript must:

- describe the result as a four-action, retrospective, model-held-out stress
  test of one frozen configuration;
- keep Figure 5 in the main paper and report the all-12-horizon reversal;
- distinguish paired score uncertainty from unavailable predictive intervals;
- state that semantic event-aware forecasting is prior art;
- use the action event, not 67,328 zone-week rows, as intervention support;
- avoid causal policy effects, future-event validity, cross-city validity,
  operational validity and universal UWM/GWM conclusions.

