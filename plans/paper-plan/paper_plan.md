# Do Urban World Models Transfer Across Policy Actions?

Status: `COMPLETE_NEGATIVE_RESULT_ARCHIVED`

Plan date: 2026-07-24

## Source And Scope

- Source type: completed benchmark result, frozen protocol, committed predictions and research idea.
- Domain: urban mobility forecasting and urban world-model evaluation.
- Study design family: retrospective leave-one-action-out predictive benchmark with semantic negative controls.
- Unit of observation: taxi-zone by event-relative week; the independent transfer unit is the policy action event, not the zone-week row.
- Main contribution type: predictive and measurement/benchmark.
- Pipeline branch: Mixed, combining Predictive and Descriptive/Measurement. The weaker descriptive/predictive ceiling governs.
- Study population: NYC yellow-taxi mobility around four official fare actions in 2015, 2019, 2022 and 2025.
- Known unknowns: exhaustive coverage beyond the focused novelty audit, calibrated predictive intervals unavailable from retained V5 artifacts, and generalization to a genuinely future action.
- Explicit exclusion: no causal policy-effect, welfare, congestion-reduction, operational deployment or cross-city claim.

Runtime-R4 is treated as the bounded execution contract for this urban
benchmark, not as proof of a universal GWM or Geospatial Kernel.

## Central Claim

- Claim: Under a frozen leave-one-action-out protocol across four NYC taxi fare interventions, the evaluated action-conditioned geospatial model did not transfer reliably beyond strong historical forecasting and did not consistently prefer the correct action semantics over corrupted actions.
- Claim strength: predictive/descriptive.
- Inferential target: transportability of one frozen action-conditioned model configuration across the four admitted NYC yellow-taxi actions.
- Falsification condition: the claim would be undermined if an integrity-preserving recomputation showed that the committed correct-action model beat the history and fixed-spatial baselines, improved at least three of four events without severe degradation, and beat every frozen semantic corruption under the preregistered metric and uncertainty procedure.

The claim is deliberately about the evaluated configuration and protocol. It is
not the universal statement that urban world models cannot work.

The preregistered weeks 1/2/4/8/12 conclusion is horizon-weighting sensitive.
The candidate loses to History AR and Spatial AR in six of seven fixed
alternative specifications, but slightly beats both when all 12 horizons are
equally weighted. The admitted claim is therefore lack of stable transfer, not
uniform inferiority under every reasonable metric.

## Research Questions

1. Can four documented urban fare actions be organized into a leakage-resistant leave-one-action-out forecasting benchmark?
2. Does the correct-action model add predictive value beyond historical inertia, fixed spatial smoothing and a matched no-action architecture?
3. Does the model prefer the correct action date, components and spatial scope over semantically incorrect controls?
4. How does transfer performance vary by event, mobility target and 1-12 week horizon?
5. What does the effective event sample size imply for claims based on large zone-week panels?

## Subclaims

| ID | Subclaim | Observable implication | Minimum evidence | Primary analysis | Main alternative explanation | Weakening pattern |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | The benchmark is reproducible and leakage-resistant at the model boundary. | Four complete folds, committed predictions before target access and zero-difference replay. | Protocol, data verification, firewall, commitment and replay receipts. | M1 integrity audit. | Hidden leakage through preprocessing, graph construction or model selection. | Any pre-commitment target read, hash mismatch or incomplete key set. |
| S2 | The evaluated action-conditioned model lacks stable cross-action advantage over strong historical dynamics. | Mean skill is non-positive or unstable, with fewer than three improved events and confidence intervals crossing no improvement. | Equal-event metric, event-level skills and paired uncertainty. | M2 primary comparison and M3 fold heterogeneity. | Metric choice masks meaningful operational gains. | Consistent gains under preregistered and scale-appropriate alternatives. |
| S3 | Correct action semantics are not reliably identified. | At least one corrupted action equals or beats the correct action overall or across multiple folds. | All seven frozen controls scored on identical keys and budgets. | M4 semantic-control tournament. | A control accidentally approximates an unmodeled implementation lag. | Correct action wins every control robustly after declared, non-retuned timing diagnostics. |
| S4 | Transfer failure is event- and horizon-dependent rather than uniform model collapse. | Positive skills for some events/horizons and negative skills for others. | Event, target and horizon decompositions. | M3 and M5 failure anatomy. | Differences are solely caused by count scale or sparse zones. | Heterogeneity disappears under pre-action normalization and robust zone restrictions. |
| S5 | Zone-week sample size cannot be interpreted as independent intervention support. | Training has 50,496 rows per fold but only three training actions. | Explicit hierarchy and event-level resampling/sensitivity. | M6 support-unit analysis. | Zone-level exposure supplies sufficient independent action variation. | Stable correct-action transfer under event and exposure-support diagnostics. |

## Data And Measurement Plan

| Dataset | Role | Unit | Coverage | Key variables | Linkage | Preprocessing | Limitations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NYC TLC Yellow Taxi trip records | Mobility state and observed forecast targets | trip, then taxi-zone week | 52 pre-action and 12 post-action weeks for each event | pickup, dropoff, origin, destination, timestamps | Taxi Zone IDs and event-relative week | clean IDs/times, aggregate counts, complete zone-week grid | Yellow taxis are not total NYC mobility; reporting and fleet composition change over years. |
| TLC Taxi Zone polygons and lookup | Stable spatial units and adjacency | 263 polygons | fixed benchmark geography | zone ID, borough, geometry | LocationID | geometry validation and adjacency construction | Zone system is administrative/operational, not behaviorally homogeneous. |
| Official 2015 action evidence | Action identity and timing | event | effective 2015-01-01 | USD 0.30 improvement surcharge, citywide exposure | event ID | map to canonical numeric action | Uniform exposure makes exposure-shuffle control degenerate for this event. |
| Official 2019 action evidence | Action identity and timing | event/zone | effective 2019-02-02 | USD 2.50 applicable Manhattan surcharge | event and exposure zone | encode components, date and exposure | Bundled contemporaneous changes are not causally separated. |
| Official 2022 adopted fare rule | Action identity and timing | event | effective 2022-12-19 | taximeter and surcharge components | event ID | encode ten fee components and summary fields | Large multi-component bundle differs from spatial surcharges. |
| Official 2025 CRZ evidence | Action identity and timing | event/zone | effective 2025-01-05 | USD 0.75 per-trip charge and CBD scope | event and CBD Taxi Zones | spatial exposure overlay and canonical action | Early implementation period may contain adaptation and concurrent shocks. |
| Pre-action OD panels | Mobility relation graph | directed zone pair | event-specific 52 pre-action weeks | trip flow | origin/destination zone IDs | remove self/invalid/nonpositive flow; retain top 8 destinations per origin | Frozen graph cannot represent post-action network rewiring. |
| V5 committed predictions and targets | Primary evaluation evidence | fold-zone-horizon-target | four outer folds, 12 horizons | predictions for 11 submissions and 4 targets | fold, zone, horizon | hash verification and exact key join | Analysts had previously seen parts of 2015/2025 outcomes; this is model-held-out, not analyst-blind. |

### Variable Construction

| Variable | Construct | Source fields | Transformation | Unit/scale | Missingness handling | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| `pickup_count` | origin activity state | pickup timestamp and zone | weekly count | trips/week/zone | complete grid with declared zeros only after source checks | totals against source event panel |
| `dropoff_count` | destination activity state | dropoff timestamp and zone | weekly count | trips/week/zone | same as pickup | totals against source event panel |
| `cbd_inflow` | flows entering CBD | origin/destination and CBD membership | weekly qualifying count | trips/week/zone | invalid ODs excluded | direction and membership tests |
| `cbd_outflow` | flows leaving CBD | origin/destination and CBD membership | weekly qualifying count | trips/week/zone | invalid ODs excluded | direction and membership tests |
| `canonical_action` | action magnitude and semantics | ten fee components, total/relative change, spatial/time/implementation shares | 15 numeric dimensions in V5 | mixed USD and shares | no imputation after protocol freeze | zero-action anchor and source-document crosswalk |
| `primary_error` | equal-event predictive error | prediction, target, pre-action target mean | zone-target absolute error normalized by pre-action mean; equal average over zones, targets, horizons and events | unitless | protocol-defined low-denominator handling only | frozen evaluator conformance tests |
| `event_skill` | gain over history AR | candidate and AR event errors | `1 - candidate/history` | proportion | none | exact reproduction from result JSON |
| `semantic_control_delta` | preference for correct action | correct and corrupted action errors | correct minus control error | unitless; lower is better | none | identical prediction keys and seed contract |

## Method-Library Calibration

- Category files read: `human_mobility.md` and `ml_prediction.md`.
- Matched entries: vector-based pedestrian navigation for cross-context validation; COVID mobility manifold work for temporal/geographic structure; XGBoost prediction pattern for explicit model comparison and held-out validation.
- Adapted method patterns: cross-context tests, strong baseline comparison, error decomposition, held-out validation and clearly separated descriptive versus predictive claims.
- Adapted validation patterns: cross-event evaluation, negative controls, model comparison, sensitivity, leakage audit and explicit uncertainty.
- External nearby methods screened: TrafficStream continual traffic forecasting, traffic domain generalization and cross-city transfer, Event Traffic Forecasting, LLM-MPE, SeMob, FUSE-Traffic, spectral graph traffic forecasting, human mobility models and causal-world-model robustness work.
- No-match note: event-aware and semantic-text mobility prediction are prior art. The focused audit found no equivalent benchmark combining leave-one-institutional-action-out mobility forecasting, prediction commitment and corruptions of action timing, components, identity, exposure and spatial scope. This is a scoped search result, not a global first claim. The paper must not borrow causal language from policy-impact designs.

## Identification Or Modeling Strategy

Primary strategy: frozen predictive benchmark audit. Do not tune or replace the
V5 model after seeing the four-fold results.

Primary procedure:

```text
for each held-out action e:
    fit/select on the other three actions only
    frozen_history = AR(pre_action_state_e)
    action_delta = DAM_GK(state_e, pre_action_graph_e, canonical_action_e)
    forecast_e = frozen_history + action_delta
    roll open-loop for 12 weeks without observed state write-back

primary score = equal mean over events, zones, four targets and weeks 1/2/4/8/12
```

Required comparisons are history AR, fixed-adjacency spatial AR, a matched
no-action residual architecture and seven action corruptions. Primary
score-difference uncertainty is paired by taxi zone within each event and
reported with the frozen 20,000-draw bootstrap. Because there are only four
events, event-level results must always be shown; zone bootstrap intervals must
not be presented as evidence of a large intervention sample. V5 did not retain
residual-level cross-fitted training-action predictions, so calibrated
predictive intervals cannot be constructed without leakage. Three-seed spread
is ensemble variation and must not be labeled a calibrated interval.

Assumptions:

- event action documents identify dates, components and exposure accurately;
- pre-action state and graph construction do not read post-action targets;
- the equal-event metric reflects the scientific question better than pooled trip error;
- each held-out event is a meaningful transportability environment, despite cross-year differences;
- descriptive uncertainty does not identify a causal action effect.

Why this matches the claim: the claim concerns predictive transfer and semantic
action use, so a held-out-action forecast and action-corruption tournament test
the claim directly without requiring causal identification.

Unsuitable conditions or failure triggers: target leakage, action-document
errors, non-reproducible committed predictions, an evaluator mismatch, or a
paper narrative that generalizes from one failed configuration to all UWM.

## Evidence Chain

| Evidence | Supports | Type | Data/variables | Analysis | Decision rule | Threat | Placement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | S1 | table/diagnostic | protocol, bundle and hashes | M1 | all integrity checks pass | hidden preprocessing leakage | Table 1 and Methods |
| E2 | S1 | workflow | four event folds and Runtime-R4 | M1 | complete fold isolation and replay | architecture diagram mistaken for validity | Figure 1 |
| E3 | S2 | prediction/contrast | primary scores | M2 | correct action versus AR and spatial AR | weak baseline or pooled metric | Figure 2, Table 2 |
| E4 | S2, S4 | heterogeneity | event skills and bootstrap interval | M3 | show all four events and uncertainty | one event dominates interpretation | Figure 3 |
| E5 | S3 | negative-control contrast | seven corruptions | M4 | correct action must beat every control | control inadvertently plausible | Figure 4 |
| E6 | S4 | heterogeneity | event-target-horizon errors | M5 | report sign and magnitude across all cells | selective panel reporting | Figure 5, supplement |
| E7 | S5 | measurement/support | event and zone-week hierarchy | M6 | inference distinguishes four events from 67,328 rows | pseudoreplication | Figure 1 and Discussion |
| E8 | S2-S4 | robustness/readiness | frozen predictions, targets and retained artifact audit | M7-M8 | score bootstrap is valid; calibrated intervals are unavailable; all fixed sensitivities are reported without retuning | post hoc uncertainty or metric selection | Figure 5 and Limitations |

## Main Analyses

| Analysis | Purpose | Model/procedure | Inputs | Outputs | Acceptance criteria | Failure action |
| --- | --- | --- | --- | --- | --- | --- |
| M1 Integrity audit | Establish benchmark validity | verify 147 data checks, firewall, hashes, commitment chronology and replay | frozen V5 receipts | `tables/benchmark_integrity.csv` | all declared checks reproduce | stop manuscript and repair provenance only; do not rescore |
| M2 Primary model tournament | Test cross-action advantage | equal-event normalized MAE ranking | formal result JSON | `tables/primary_scores.csv` | exact match to frozen evaluator | treat any mismatch as invalid until resolved |
| M3 Event transfer heterogeneity | Prevent aggregate masking | fold skills and paired zone bootstrap | result JSON/predictions | `tables/fold_skill.csv` | all four folds and intervals shown | narrow claim to descriptive case comparison |
| M4 Semantic action tournament | Test action identity, timing and scope | correct action versus seven frozen corruptions | committed predictions | `tables/action_controls.csv` | identical keys, metric and seed contract | remove action-semantics interpretation if controls are incomparable |
| M5 Target/horizon anatomy | Locate failure structure | event-target and horizon decompositions | result JSON | `tables/error_decomposition.csv` | complete 4 x 4 and five-horizon coverage | label any reduced panel exploratory |
| M6 Effective-support analysis | Expose pseudoreplication risk | hierarchical sample accounting and event leave-one-out sensitivity | fold metadata | `tables/support_units.csv` | event counts displayed beside row counts | remove any language implying tens of thousands of interventions |
| M7 Predictive interval readiness | Determine whether leakage-free calibration is possible | audit retained inner-fold and seed artifacts before interval construction | fold artifacts and development metrics | `results/uncertainty_readiness.json` | construct intervals only if residual-level cross-fitted training-action predictions exist | current result: unavailable; keep a point-forecast paper and state the limitation |
| M8 Metric and zone sensitivity | Address normalization and horizon-weighting concerns | fixed alternatives computed from committed predictions only | committed predictions/targets | `results/metric_sensitivity_scores.csv` and `results/metric_sensitivity_contrasts.csv` | no ranking-driven metric selection; report every fixed specification | current result: candidate loses both baselines in 6/7 specifications but wins both with all 12 horizons |

## Analysis Execution DAG

Dependency summary:

```text
T0 artifact freeze --> T2 primary tables --> T3 controls/decomposition --> T5 figures
                 \--> T4 calibration/sensitivity --------------------/
T1 literature audit -----------------------------------------------> T6 evidence map
T5 figures --------------------------------------------------------> T6 evidence map
T6 evidence map ---------------------------------------------------> T7 writer gate
```

### T0: Freeze Paper Evidence Inventory

- Depends on: none.
- Purpose: bind every planned statement to the completed V5 artifact set.
- Inputs: protocol, verification, commitment, replay and formal result files.
- Method/model: hash and schema audit; no model execution.
- Implementation notes: preserve the V5 result even if later diagnostics are unfavorable.
- Outputs: proposed `paper-output/uwm_nyc_action_transfer/evidence_inventory.csv`.
- Validation/diagnostics: SHA-256 match to completion verification and clean path resolution.
- Acceptance criteria: every primary number has one authoritative source path and field.
- Failure action: stop downstream paper work and resolve artifact identity.
- Downstream consumers: T2-T7.

### T1: Complete Focused Novelty Audit

- Depends on: none.
- Purpose: distinguish the contribution from standard traffic forecasting, continual adaptation, causal policy evaluation and generic world-model benchmarks.
- Inputs: DIRECT idea references, OpenAlex results and venue-index searches.
- Method/model: exact-query screening plus backward/forward citation review.
- Implementation notes: novelty object is the multi-action transfer protocol and semantic action controls, not the graph architecture.
- Outputs: `docs/research/UWM_NYC_ACTION_TRANSFER_NOVELTY_AUDIT.md` and its exact query ledger.
- Validation/diagnostics: exact query/date/source ledger and DOI deduplication.
- Acceptance criteria: at least the closest traffic-transfer and intervention-conditioned forecasting papers are screened at abstract/method level.
- Failure action: narrow title and contribution if an equivalent benchmark exists.
- Downstream consumers: T6 and T7.

Completed result: `PASS_WITH_NARROWED_CONTRIBUTION`. Event-semantic mobility
forecasting is prior art; the admitted novelty object is the policy-action
transfer and semantic-corruption evaluation protocol.

### T2: Materialize Primary Paper Tables

- Depends on: T0.
- Purpose: create compact, reviewable tables from the frozen formal result.
- Inputs: action transfer results and completion verification.
- Method/model: deterministic extraction only.
- Implementation notes: no recomputation that changes the frozen evaluator.
- Outputs: proposed `tables/primary_scores.csv`, `tables/fold_skill.csv`, `tables/gate_summary.csv`.
- Validation/diagnostics: exact agreement with report values and row-count checks.
- Acceptance criteria: score precision and labels match authoritative JSON.
- Failure action: fix extraction, never edit source results.
- Downstream consumers: T3, T5 and T6.

### T3: Materialize Semantic-Control And Failure Anatomy Tables

- Depends on: T0 and T2.
- Purpose: show why the model fails the world-model action test.
- Inputs: all 11 committed submissions and result decompositions.
- Method/model: correct-versus-control differences by event, target and horizon.
- Implementation notes: show controls that beat the candidate, not only favorable controls.
- Outputs: proposed `tables/action_controls.csv` and `tables/error_decomposition.csv`.
- Validation/diagnostics: complete control/fold matrix and sign convention tests.
- Acceptance criteria: seven controls, four folds, four targets and five report horizons are accounted for.
- Failure action: withhold the affected mechanism interpretation.
- Downstream consumers: T5 and T6.

### T4: Add Non-Retuned Calibration And Metric Sensitivity

- Depends on: T0.
- Purpose: audit uncertainty readiness and verify that the negative conclusion is not a single metric artifact.
- Inputs: committed predictions, targets and retained training-event artifacts.
- Method/model: residual-artifact readiness audit, MAE/WAPE/log/count-scale sensitivity, all-12-horizon sensitivity and robust zone restrictions.
- Implementation notes: supplemental analysis cannot change V5 gate status or tune the model.
- Outputs: `results/uncertainty_readiness.json`, `results/metric_sensitivity_scores.csv`, `results/metric_sensitivity_contrasts.csv` and `results/horizon_profile.csv`.
- Validation/diagnostics: held-out target denylist during calibration; fixed metric list before computation.
- Acceptance criteria: every fixed specification is reported and interval readiness is decided without held-out-label leakage.
- Failure action: applied. Retain the V5 point result, state that calibrated predictive intervals are unavailable, and lead with the all-12-horizon reversal in Figure 5.
- Downstream consumers: T5 and T6.

### T5: Render Main Figures

- Depends on: T2-T4.
- Purpose: turn the evidence chain into five compact arguments.
- Inputs: validated paper tables and event metadata.
- Method/model: deterministic plotting with source data exported beside each figure.
- Implementation notes: failure and uncertainty must be visually primary.
- Outputs: proposed `figures/F1` through `figures/F5` plus source CSV files.
- Validation/diagnostics: label clipping, grayscale legibility, color-vision simulation and number spot checks.
- Acceptance criteria: every panel resolves to a table and evidence ID.
- Failure action: redesign the panel; do not use decorative architecture figures.
- Downstream consumers: T6 and T7.

### T6: Build Claim-Result And Narrative Evidence Map

- Depends on: T1, T3-T5.
- Purpose: prevent the paper from implying policy causality or universal UWM failure.
- Inputs: claims S1-S5, all final tables/figures and novelty audit.
- Method/model: sentence-level claim to artifact mapping and prohibited-phrase audit.
- Implementation notes: distinguish model failure, benchmark completion and future V6 validation.
- Outputs: proposed `paper-output/uwm_nyc_action_transfer/claim_result_map.md`.
- Validation/diagnostics: every quantitative statement has a source; all scope terms are explicit.
- Acceptance criteria: no unresolved claim without primary evidence and one robustness path.
- Failure action: narrow or delete the unsupported statement.
- Downstream consumers: T7.

### T7: Paper-Writer Admission Gate

- Depends on: T6.
- Purpose: decide whether the AI Urban Scientist paper-writer may draft the manuscript.
- Inputs: paper plan, novelty audit, evidence inventory, tables, figures and claim-result map.
- Method/model: re-run all paper-planner quality gates and paper-writer prerequisites.
- Implementation notes: venue and real author metadata must be supplied before submission formatting.
- Outputs: writer admission record or typed return to T1/T4/T6.
- Validation/diagnostics: no-invention, citation coverage and artifact traceability checks.
- Acceptance criteria: no failed gate; cautions are visible in title, abstract and limitations.
- Failure action: return to the owning task, not to model retuning.
- Downstream consumers: manuscript drafting.

## Figures And Tables

| Item | Role | Linked evidence | Panels/columns | Type | Key comparison | Takeaway | Placement rationale |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Figure 1 | Define the scientific test and effective sample hierarchy | E1, E2, E7 | A four-action timeline; B action versus zone-week support counts | timeline + log horizontal bars | four action environments versus 67,328 rows | The benchmark tests transfer across four actions, not 67,328 independent interventions | Main context figure |
| Figure 2 | Show the primary tournament | E3 | A all-model ranking; B eight frozen gate outcomes | dot plot + gate matrix | correct action versus strong baselines, matched no-action and controls | Correct action loses the preregistered tournament and passes 0/8 gates | Main primary result |
| Figure 3 | Expose event and target heterogeneity | E4, E6 | A four fold skills; B event-target error contrast matrix | bars + zero-centered heatmap | 2015/2019 versus 2022/2025 across four targets | Aggregate failure combines two helpful and two harmful transfers | Main scientific finding |
| Figure 4 | Test semantic action use | E5 | A correct-versus-control score differences and bootstrap intervals; B fold wins | interval plot + horizontal bars | correct date/components/scope versus seven corruptions | Correct semantics are not reliably preferred | Main mechanism/falsification figure |
| Figure 5 | Expose horizon and metric sensitivity | E6, E8 | A week 1-12 candidate-minus-baseline profiles; B seven fixed sensitivity specifications | horizon lines + paired dot plot | preregistered weeks versus all 12 horizons and alternative metrics/zones | The frozen failure is real under the primary metric but horizon-weighting sensitive | Main robustness figure |
| Table 1 | Primary score ranking | E3 | rank, model, model type, primary error | table | all 11 submissions | Exact preregistered numerical anchor | Main |
| Table 2 | Event-level transfer | E4 | fold, history error, candidate error, delta, skill, improvement | table | all four actions | Prevents aggregate masking | Main |
| Table 3 | Semantic controls | E5 | control, score delta, bootstrap interval, fold wins | table | correct versus seven corruptions | Prevents favorable-only reporting | Main/supplement |
| Table 4 | Metric and horizon sensitivity | E8 | specification, metric, candidate and baseline scores, contrasts | table | seven fixed specifications | Makes the all-12-horizon reversal explicit | Main/supplement |

### Figure Design Spec

Set-wide style: white background; Arial or Source Sans 3; 8 pt labels, 9 pt
axes and 10 pt panel titles at final width; letter spacing 0; no 3-D effects or
heavy frames; direct labels where feasible. Export PDF/SVG line art and 600 dpi
raster maps. All source data accompany figures.

| Figure | Palette type | Named palette + hex/version | Colorblind-safe? | Redundant encoding | Uncertainty shown | Format/dpi/width |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | categorical | Okabe-Ito: `#0072B2,#E69F00,#009E73,#D55E00,#CC79A7,#000000,#7A7A7A` | yes; test deuteranopia/protanopia | shape, numbering and line style | action-window bands | SVG/PDF, 183 mm |
| F2 | categorical | candidate `#0072B2`, baselines `#7A7A7A,#000000`, controls `#D55E00` | yes | point shape and pass/fail symbols | bootstrap gate outcome | PDF, 183 mm |
| F3 | diverging | BrBG `#8C510A,#D8B365,#F5F5F5,#5AB4AC,#01665E`, zero-centered | yes | sign, bar direction and numeric cell labels | all four event effects shown | PDF, 183 mm |
| F4 | categorical + diverging | Okabe-Ito controls; BrBG for signed deltas | yes | control glyph and line pattern | bootstrap intervals where valid | PDF, 183 mm |
| F5 | categorical + signed | History AR `#000000`, Spatial AR `#E69F00`, pass/fail row shading | yes | marker shape, sign and direct annotations | complete fixed sensitivity set | PDF, 183 mm |

## Robustness Matrix

| Check | Threat addressed | Implementation | Expected output | Claim affected | Required/optional |
| --- | --- | --- | --- | --- | --- |
| Exact replay and hash audit | irreproducible result | verify commitment and zero-difference replay | integrity table | S1 | required |
| Leave-one-action-out firewall | outcome leakage | inspect read routes, nested selection and graph dates | fold audit | S1-S3 | required |
| History AR and spatial AR | weak baseline | same target keys and horizon metric | primary ranking | S2 | required |
| Matched no-action architecture | architecture-capacity confounding | remove action signal only | matched contrast | S2-S3 | required |
| Seven semantic corruptions | shortcut action use | date, component, scope, event and exposure controls | control tournament | S3 | required |
| Event-level reporting | pooled-row pseudoreplication | show every fold and mean of event scores | fold table | S2, S4, S5 | required |
| Target/horizon decomposition | aggregate masking | complete event-target and horizon panels | decomposition matrix | S4 | required |
| Alternative metrics and horizon weighting | normalization dependence | seven fixed specifications, including all 12 horizons | sensitivity table and Figure 5 | S2-S4 | completed; 6/7 losses and one reversal must be in main text |
| Zone restrictions | sparse denominator effects | declared minimum pre-action activity thresholds of 10 and 100 | sensitivity table | S2-S4 | completed |
| Predictive interval readiness | overconfident point forecasts | audit residual-level cross-fitted training-action predictions before calibration | readiness JSON | S2, S4 | completed as unavailable; explicit point-forecast limitation required |
| Analyst-blind future event | retrospective overfitting | V6 prospective protocol | future external result | generalization | optional for V5 paper; required for future-event claim |
| Cross-city transfer | NYC specificity | same action ontology in new city | transfer matrix | generalization | optional; not part of current claim |

## Risk Register

| Risk | Likelihood | Impact | Affected claim | Mitigation | If unresolved |
| --- | --- | --- | --- | --- | --- |
| Only four independent action events | certain | high | S2-S5 | equal-event design, full fold display and bounded claim | state that the study is a four-event stress test, not population-level law |
| Cross-year concurrent shocks | high | high | S2-S4 | no causal claim; calendar/history baseline; event heterogeneity | interpret as predictive transportability only |
| Model failure may look like an implementation failure | medium | high | contribution | emphasize 15/15 completion, replay and matched controls | publish benchmark and falsification separately from model success |
| Reviewers may reject a negative result | medium-high | high | publication value | center the benchmark, semantic controls and effective support insight | target benchmark/methodology venue and avoid a method-superiority pitch |
| Novelty may overlap OOD or continual traffic forecasting | medium | high | title/contribution | focused T1 audit | narrow to action-event holdout and semantic action evaluation |
| Taxi data are not total mobility | certain | medium | scope | bind title and conclusions to NYC yellow taxis | remove citywide transport claims |
| Bootstrap may overstate intervention certainty | high | high | S2 | label zone-paired interval correctly and show four event results | avoid inferential population language |
| Horizon weighting changes ranking | certain | high | S2-S4 | show preregistered and all-12-horizon results together in Figure 5 | call the result horizon-weighting sensitive; do not claim uniform inferiority |
| No calibrated predictive intervals | certain | medium | predictive completeness | retain valid score-difference bootstrap and readiness audit | state point-forecast-only limitation; never call seed spread calibrated uncertainty |
| Universal GWM language returns | medium | high | all | claim-result map and prohibited phrase audit | block paper-writer admission |

## Reviewer Defense

| Reviewer concern | Response in analysis | Response in writing |
| --- | --- | --- |
| This is just another traffic forecasting model. | The primary object is an event-held-out action transfer benchmark with semantic corruptions, not a new neural architecture. | Lead with the scientific test and failure result; put model details after the benchmark. |
| Four events are too few. | Agree; use events as the transfer unit and make sparse action support a central limitation. | Never present 67,328 rows as intervention sample size; position V6 as future validation. |
| The study does not identify policy effects. | No causal estimator or policy-effect claim is used. | State predictive transportability in title, abstract, methods and discussion. |
| Negative results may reflect a bad model. | The conclusion is configuration-bounded; matched no-action and semantic controls locate the failure. | Say "the evaluated configuration," never "UWM cannot work." |
| The delayed-action control winning could reflect real implementation lag. | Report it as an alternative explanation and inspect declared timing without retuning. | Treat the control as evidence that nominal action timing was not robustly identified, not proof of a four-week true lag. |
| The benchmark was not analyst-blind. | Prediction/target access was model-firewalled, but analysts had seen parts of prior outcomes. | Use "model-held-out retrospective benchmark" and reserve "future" for V6. |
| Graph complexity is unnecessary. | Fixed spatial AR is an explicit strong baseline and currently performs best among formal models. | Present this as a result, not hide it. |

## Interpretation Framework

| Result pattern | Interpretation | Claim/title change | Figure/discussion change |
| --- | --- | --- | --- |
| Primary | Current result: correct action loses to strong AR baselines, improves 2/4 events and loses semantic-control tests. | Keep question title and bounded failure claim. | Lead with F2-F4; discuss event support and evaluation discipline. |
| Null | Correct action and matched no-action are indistinguishable. | Reframe to "Action Inputs Do Not Add Transferable Signal..." | Center matched architecture contrast; reduce component-level discussion. |
| Heterogeneous | Current result: 2022/2025 improve while 2015/2019 degrade. | Use "Unstable Transfer" in subtitle/abstract. | Make F3 central and reject aggregate superiority language. |
| Mechanism | Correct action improves but corrupted timing/components/scope also improve. | Remove semantic action-learning claim; call it nonspecific adaptation. | Center F4 and alternative implementation-lag explanations. |
| Fragile | Current result: the candidate loses both baselines in 6/7 fixed specifications but wins when all 12 horizons are equally weighted. | Keep the question title and describe "horizon-weighting-sensitive failure under the preregistered metric." | Keep F5 in the main paper and state that uniform inferiority is not supported. |

## Quality Gates

| Gate | Status | Notes |
| --- | --- | --- |
| Claim-design fit | pass | Predictive/descriptive claim matches leave-one-action-out evaluation; causal language is excluded. |
| Data sufficiency | pass | Four complete event bundles, targets, strong baselines, controls and receipts support the bounded four-event claim. No cross-city or causal subclaim is included. |
| Execution readiness | pass | Primary V5 evidence, focused novelty audit, metric sensitivity, uncertainty-readiness audit and final figures are complete. |
| Evidence coverage | pass | Every subclaim has primary evidence and at least one integrity, negative-control or sensitivity path. |
| Mechanism discipline | pass | The paper tests whether semantic action inputs matter; it does not call predictive differences causal mechanisms. |
| Robustness adequacy | caution | Baselines, matched ablation, semantic controls, event decomposition, replay and metric sensitivity are complete; calibrated predictive intervals are unavailable and must remain a visible limitation. |
| Figure economy | pass | Five figures carry benchmark, primary, heterogeneity, semantic-control and robustness evidence. |
| Visual design | pass | All figures specify palette, redundant encoding, uncertainty, typography and print format. |
| No invention | pass | Existing values come from the frozen V5 result; future T1/T4 outputs are explicitly proposed. |

## Handoff Decision

T0-T7 are complete, and the paper artifacts are archived as a bounded negative
result. The V5 model must not be retrained or tuned in response to the observed
failures.
