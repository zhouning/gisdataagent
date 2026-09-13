# Claim-Result Map

Status: `READY_FOR_WRITER_ADMISSION_REVIEW`

## Admitted Quantitative Claims

| Claim | Required wording | Source |
| --- | --- | --- |
| Primary score | Under the frozen weeks 1/2/4/8/12 metric, correct action scores 0.368389 versus 0.362616 for History AR and 0.361416 for Spatial AR | `results/primary_scores.csv` |
| Event transfer | Mean fold skill is -2.52%; two of four actions improve | `results/fold_skill.csv`, `results/frozen_evidence_summary.json` |
| Frozen decision | None of eight preregistered transfer gates passes | `results/gate_summary.csv` |
| Best control | The +4-week action-date corruption ranks first at 0.358918 | `results/primary_scores.csv`, `results/action_controls.csv` |
| Semantic comparison | Four of seven corruptions beat correct action overall; no comparison is won in all four folds | `results/action_controls.csv` |
| Heterogeneity | 2015/2019 degrade and 2022/2025 improve relative to History AR | `results/fold_skill.csv`, `results/error_decomposition.csv` |
| Sensitivity | Candidate loses both AR baselines in 6/7 fixed specifications but beats both when all 12 horizons are equally weighted | `results/metric_sensitivity_contrasts.csv`, `results/metric_sensitivity_summary.json` |
| Support hierarchy | Four actions generate 67,328 zone-week rows; each fold trains on three actions and 50,496 rows | `results/support_units.csv` |
| Integrity | All 15 paper-level integrity checks pass and all evidence inventory hashes match | `results/benchmark_integrity.csv`, `results/frozen_evidence_summary.json` |

## Admitted Interpretive Claims

| Claim ID | Admitted interpretation | Mandatory boundary |
| --- | --- | --- |
| S1 | The benchmark outcome is reproducible at the declared model boundary | Retrospective model-held-out, not analyst-blind |
| S2 | This configuration lacks stable cross-action advantage | Horizon weighting changes the ranking; do not claim uniform inferiority |
| S3 | Correct action semantics are not reliably preferred | The +4-week winner does not identify a true implementation lag |
| S4 | Failure is structured by event, target and horizon | No causal interpretation of cross-year contrasts |
| S5 | Zone-week rows are not independent policy actions | This is a support-unit caution, not proof that spatial exposure is useless |

## Uncertainty Language

Allowed:

- "paired taxi-zone bootstrap interval for a score difference"
- "20,000-draw frozen score bootstrap"
- "calibrated predictive intervals are unavailable in V5"
- "three-seed ensemble spread"

Prohibited:

- "95% predictive interval" unless a future artifact supplies leakage-free calibration
- "seed-based confidence interval"
- "four actions provide population-level intervention inference"
- "67,328 independent intervention observations"

Source: `results/uncertainty_readiness.json`.

## Novelty Language

Allowed:

> Within the covered sources, we found no equivalent benchmark combining
> documented policy-action leave-one-out folds, prediction commitment/replay,
> strong historical baselines and frozen semantic action corruptions.

Prohibited:

- first event-aware or semantic mobility forecasting model
- first traffic forecasting under distribution shift
- first action-conditioned urban model
- first NYC taxi event or policy forecasting study
- proof of a causal or universal urban world model

Source: `docs/research/UWM_NYC_ACTION_TRANSFER_NOVELTY_AUDIT.md`.

## Scope Phrases

Use consistently:

- "evaluated action-conditioned configuration"
- "four-action retrospective stress test"
- "NYC yellow-taxi mobility"
- "model-held-out"
- "under the frozen weeks 1/2/4/8/12 metric"
- "horizon-weighting sensitive"

Do not use:

- "UWM cannot work"
- "urban mobility as a whole"
- "caused by the fare action"
- "future unseen policy" or "analyst-blind"
- "cross-city generalization"
- "operational forecasting validity"

## Figure And Table Contract

| Artifact | Required message |
| --- | --- |
| Figure 1 | Four action environments are the transfer support; row count is not action count |
| Figure 2 | Correct action loses the preregistered tournament and passes 0/8 gates |
| Figure 3 | The mean combines two harmful and two helpful event transfers |
| Figure 4 | Correct semantics do not dominate the frozen corruptions |
| Figure 5 | The primary failure coexists with an all-12-horizon ranking reversal |
| Table 1 | Exact score ranking of all 11 submissions |
| Table 2 | All four event results |
| Table 3 | All seven semantic controls and paired score intervals |
| Table 4 | All seven fixed metric/horizon/zone specifications |

## Writer Admission Preconditions

- Narrative Markdown and JSON exist and agree on S1-S5 status.
- All five figures exist in PDF, SVG and PNG with source CSVs.
- All four LaTeX tables exist.
- Novelty audit and exact query ledger exist.
- Figure 5 and calibrated-interval limitation are admitted to the main text.
- Global `data/DATA_SEEKER_REPORT.md` is a separate Chongqing route and must not
  supply methods or data claims to this NYC paper; use the frozen V5 evidence
  inventory and canonical plan instead.
