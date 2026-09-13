# Generated Idea

**Method**: DIRECT
**Topic**: Action transfer in urban world models under real policy regime shifts
**Web Search**: Yes - OpenAlex metadata and the existing UWM novelty corpus were consulted
**Generated**: 2026-07-24T00:00:00+09:00

## Title

Do Urban World Models Transfer Across Policy Actions? A Four-Event Stress Test of New York Mobility Forecasting

## Abstract

Urban spatiotemporal models are usually validated by random or temporal holdouts within stable operating regimes. A model described as an urban world model, however, should respond correctly to an unseen action rather than merely extrapolate historical inertia. We construct a multi-action benchmark from four official New York City taxi fare interventions in 2015, 2019, 2022 and 2025, monthly TLC trip records aggregated to 263 taxi zones, official action rules and spatial exposure, and action-specific pre-period mobility graphs. Each intervention contributes 52 pre-action weeks and a sealed 12-week forecast horizon. A leave-one-action-out protocol compares an action-conditioned geospatial residual model with historical and spatial autoregressive baselines, a matched no-action model, and seven corruptions of action timing, components and spatial scope. Under the frozen weeks 1/2/4/8/12 metric, the action model improves two interventions but worsens two, produces mean skill of -2.52% against the historical baseline, and passes none of eight preregistered transfer gates; a four-week-delayed action control scores best overall. The candidate loses to both autoregressive baselines in six of seven fixed sensitivity specifications, but beats both when all 12 horizons are equally weighted, making horizon weighting a material boundary rather than a supplemental footnote. Calibrated predictive intervals cannot be recovered without leakage because V5 did not retain residual-level cross-fitted training-action predictions; paired score-difference bootstrap uncertainty remains available. The contribution is therefore not a successful policy-effect predictor, but a reproducible, metric-transparent stress test showing that large zone-week panels do not substitute for independent intervention support and that action semantics require direct negative-control evaluation. The study makes no causal claim about taxi fares or congestion pricing.

## Falsifiable Hypotheses

- H1: Correct action conditioning improves the equal-event held-out error over the frozen historical AR baseline.
- H2: Correct action conditioning improves at least three of four unseen actions without severe fold-level degradation.
- H3: Correct action timing, components and spatial scope outperform every frozen semantic corruption.
- H4: Any action-model advantage persists across targets and forecast horizons rather than arising from one event or endpoint.
- H5: Runtime replay reproduces all committed predictions without pre-commitment target access.

H1-H4 are rejected by the frozen V5 result; H5 is supported. These outcomes are the intended falsification evidence, not failed implementation artifacts.

## Novelty Boundary

Traffic forecasting, graph forecasting, continual adaptation, public-event mobility prediction and policy-impact studies are established areas. Event Traffic Forecasting, LLM-MPE, SeMob and FUSE-Traffic already condition mobility forecasts on public-event or textual semantics. The candidate contribution is narrower: policy-action-level leave-one-out evaluation of an urban action-conditioned model, coupled to frozen corruptions of action date, components, identity, exposure and spatial scope, strong inertia baselines, prediction commitment and failure publication. Novelty does not come from adding a graph network, an event/policy indicator, semantic text or the term "urban world model." The focused audit is recorded in `docs/research/UWM_NYC_ACTION_TRANSFER_NOVELTY_AUDIT.md`.

## References Consulted

- Barbosa, H. et al. (2018). Human mobility: Models and applications. *Physics Reports*. https://doi.org/10.1016/j.physrep.2018.01.001
- Chen, X. et al. (2021). TrafficStream: A Streaming Traffic Flow Forecasting Framework Based on Graph Neural Networks and Continual Learning. *IJCAI*. https://doi.org/10.24963/ijcai.2021/498
- Lu, Y. (2021). Learning to Transfer for Traffic Forecasting via Multi-task Learning. arXiv:2111.15542.
- Zhang, Q. et al. (2023). When Spatio-Temporal Meet Wavelets: Disentangled Traffic Forecasting via Efficient Spectral Graph Attention Networks. *ICDE*. https://doi.org/10.1109/ICDE55515.2023.00046
- Han, X. et al. (2024). Event Traffic Forecasting with Sparse Multimodal Data. *ACM Multimedia*. https://doi.org/10.1145/3664647.3680706
- Zhao, Z. et al. (2024). Exploring large language models for human mobility prediction under public events. *Computers, Environment and Urban Systems*. https://doi.org/10.1016/j.compenvurbsys.2024.102153
- Chen, R. et al. (2025). SeMob: Semantic Synthesis for Dynamic Urban Mobility Prediction. *EMNLP*. https://doi.org/10.18653/v1/2025.emnlp-main.775
- Richens, J. and Everitt, T. (2024). Robust agents learn causal world models. arXiv:2402.10877.
- NYC Taxi and Limousine Commission. Trip Record Data and adopted fare rules.
- New York State Department of Taxation and Finance and Metropolitan Transportation Authority. Official surcharge and Congestion Relief Zone materials.
