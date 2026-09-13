# DAM-GK Research Specification

## Objective

`DAM-GK` denotes the **Dynamic Action-conditioned Multi-scale Geospatial Kernel** used by the Geospatial World Model research track.

It is not a renamed adjacency matrix, distance-decay rule, generic graph attention layer, or GIS buffer operation. Its research objective is to learn an action-conditioned spatial dynamics operator:

\[
\mathcal{K}_{\theta}(\mathcal{G}_t,S_t,A_t,C_t)
\rightarrow
(\Phi_{t:t+H},\Delta \mathcal{G}_{t:t+H},U_{t:t+H})
\]

where the operator jointly estimates effective relations, delayed propagation, soft topology rewrite and uncertainty.

## Falsifiable hypotheses

### H1 — Action-conditioned relation discovery

For the same world state and candidate graph, changing the action type, target or intensity must change effective edge gates and future-state predictions. A model whose gates remain unchanged fails H1.

### H2 — Multi-relational necessity

A kernel using boundary, network, similarity and hierarchy relations must outperform or produce better calibrated uncertainty than a single-relation graph on at least one held-out real-data task. Otherwise the additional relation system is not justified.

Controlled mechanism recovery alone is insufficient to pass H2. The multi-relational state-prediction claim remains blocked until a real-data holdout shows predictive or calibration advantage.

Status on 2026-07-17: a five-fold, three-seed region holdout shows that the physical-consistency main model beats its single-relation ablation in 5/15 runs. A relation-channel residual raises this to 11/15 but lowers mean absolute F1 relative to the main model. General unseen-region H2 remains blocked.

### H3 — Dynamic topology necessity

After state write-back, effective edge weights must be recomputed. Freezing the initial graph must reduce multi-step predictive or planning performance on tasks where connectivity or functional dependence changes.

Status on 2026-07-17: a real 2017-2023 recursive benchmark now performs state write-back, stepwise context updates and topology recomputation under five-fold, three-seed unseen-region evaluation. Early unconstrained and state-aligned operators were rejected. A probability-conserving categorical model with strictly past-only temporal geographic context initially produced 14/15 write-back wins when destination prediction was read from the persistence-mixed future state. That metric was later judged semantically confounded. After separating change risk, conditional destination and written-back state, recursive write-back beats frozen-state change F1 in 7/15 runs and class Macro-F1 in 10/15 runs. Temporal history still beats its paired no-history model on change F1 in 15/15 runs, with mean 0.391999 versus 0.157863, but conditional destination Macro-F1 does not improve on average. H3 remains blocked: dynamic history is strongly necessary for change-risk prediction, while recursive write-back and destination dynamics are not yet uniformly necessary.

### H4 — Multi-scale consistency

Fine-scale predictions aggregated through real containment relations should agree with independently predicted coarse-scale states within a declared tolerance. A model that improves fine-scale accuracy by violating coarse-scale consistency fails H4.

Status on 2026-07-17: an independent coarse-state head plus fine-to-coarse consistency loss reduces held-out consistency MAE in 13/15 region-fold/seed runs. The effect on fine-scale change F1 is neutral on average. H4 has encouraging evidence but remains blocked under the all-run stability criterion.

### H5 — Geographic negative controls

Time shuffling, action shuffling, relation-type shuffling, spatial rewiring and coordinate/projection controls must degrade the appropriate metrics. Failure to degrade indicates that the model may not be using the claimed geographic mechanism.

### H6 — Future-state planning value

A planner consuming DAM-GK state write-back must outperform static ranking, one-step planning, no-write-back planning and fixed-topology planning in controlled environments and at least one bounded real-data replay task.

Status on 2026-07-17: on unseen-region multi-year land-state prediction, recursive write-back beats the independent one-step chain on final-horizon change F1 in 5/15 runs and persistence on final-horizon class Macro-F1 in 0/15 runs. This is a state-prediction precursor rather than a planning experiment, but it rejects the current transition operator as a sufficient basis for H6. H6 remains blocked.

A subsequent probability-conserving categorical transition operator was tested on the first formal region fold. It lost to frozen state, an independently chained one-step model and persistence on the final horizon. The full matrix was intentionally not launched because the predeclared continuation criterion was not met. Additional time-varying explanatory state is required before further H6 testing.

## Core model components

1. **Multi-relational candidate graph** — preserves typed boundary, distance, network, similarity and hierarchy edges.
2. **Action-conditioned relation gate** — estimates the current effective strength of every candidate edge.
3. **Lag-aware propagation operator** — distributes each message across multiple future lags rather than performing one undifferentiated message-passing step.
4. **Soft topology rewrite** — recomputes edge-retention and effective-relation probabilities after state changes.
5. **Probabilistic state transition** — predicts mean state deltas and heteroscedastic uncertainty.
6. **Cross-scale consistency objective** — constrains fine and coarse predictions through an explicit aggregation matrix.

## Initial data bindings

### TWM real cross-region temporal data

- 20 regions.
- Annual Dynamic World state from 2017–2023.
- 100 m cells.
- Elevation, slope and night-light drivers.
- Primary use: temporal holdout, leave-region-out evaluation and multi-scale consistency.

### UWM Chongqing graph data

- 1,017 administrative nodes.
- Boundary, mobility-context and geographic-configuration relations.
- Environmental, service, road and livability proxy states.
- Primary use: multi-relational discovery, graph rewiring diagnostics and planning integration.

### External observed environmental holdouts

- OpenAQ station temporal observations.
- TAP gridded PM2.5 temporal holdout.
- Primary use: observed-state dynamics and uncertainty evaluation, not policy-effect validation.

### Prepared action-conditioned replay

- 6,817 replay transitions.
- Three current UWM action families.
- Primary use: architecture development and ablation only.
- It must never be described as 6,817 observed policy interventions.

## Mandatory baselines

1. Static persistence and historical mean.
2. Target-only dynamics.
3. Fixed distance decay.
4. Fixed boundary adjacency.
5. Static graph neural network.
6. Action-conditioned model without graph structure.
7. DAM-GK without topology rewrite.
8. DAM-GK without lag structure.
9. DAM-GK without multi-scale consistency.
10. DAM-GK without state write-back.

## Claim boundary

The first implementation may support claims about algorithmic mechanism recovery, observed-state prediction, geographic negative controls and bounded future-state planning. It cannot support identified policy-causal effects, universal geographic laws or a general-purpose foundation GWM without additional data and validation.
