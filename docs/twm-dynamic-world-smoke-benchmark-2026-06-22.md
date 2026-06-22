# TWM 公开多时期土地利用基准

更新日期：2026-06-22

## 1. 当前结论

本轮新增的是 TWM 的公开数据基准入口：它面向 GLC_FCS30D、Dynamic World、MODIS 等本地导出的多时期土地覆盖栅格栈，也可以用现有 DongGuan 80m 样例作为真实数据适配验证。

关键边界：`forecast_demand` 是正式预测设定；`oracle_demand` 使用目标年类别总量，只能作为上限诊断，不能作为真实预测结果。

## 2. 数据画像

- source type: `manifest`
- region count: `2`
- rolling case count: `2`

## 3. 渲染器输出

![Maps](docs/assets/twm_public_landcover_benchmark_maps.png)

![Metrics](docs/assets/twm_public_landcover_benchmark_metrics.png)

## 4. 汇总指标

| candidate | cases | mean OA | mean Kappa | mean change FoM | mean change F1 | mean macro F1 | target demand abs err | oracle demand abs err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| twm_independent_transition_oracle_demand | 2 | 0.980139 | 0.811097 | 0.190388 | 0.304997 | 0.457793 | 0 | 0 |
| twm_independent_transition_forecast_demand | 2 | 0.975037 | 0.759633 | 0.108270 | 0.186402 | 0.394798 | 0 | 2310 |
| twm_ablation_no_drivers_forecast_demand | 2 | 0.975037 | 0.759633 | 0.108270 | 0.186402 | 0.394798 | 0 | 2310 |
| twm_ablation_no_transition_prior_forecast_demand | 2 | 0.975037 | 0.759633 | 0.108270 | 0.186402 | 0.394798 | 0 | 2310 |
| twm_ablation_no_neighborhood_forecast_demand | 2 | 0.974446 | 0.753481 | 0.095031 | 0.161714 | 0.392992 | 0 | 2310 |
| markov_transition_projection | 2 | 0.974519 | 0.753908 | 0.091934 | 0.157576 | 0.391899 | 0 | 2310 |
| twm_ablation_no_demand_projection | 2 | 0.814272 | 0.226415 | 0.065233 | 0.121339 | 0.203863 | 23700 | 23852 |
| persistence | 2 | 0.980187 | 0.818802 | 0.000000 | 0.000000 | 0.493844 | 1814 | 926 |

## 5. 单案例指标

### beijing_core_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1268`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.987628 | 0.815042 | 0.000000 | 0.000000 | 0.500859 | 0 |
| markov_transition_projection | forecast_demand | 0.979764 | 0.721600 | 0.008294 | 0.016451 | 0.437569 | 335 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.980387 | 0.730177 | 0.030266 | 0.058754 | 0.442887 | 335 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.980387 | 0.730177 | 0.030266 | 0.058754 | 0.442887 | 335 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.979788 | 0.721930 | 0.007101 | 0.014101 | 0.438404 | 335 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.980387 | 0.730177 | 0.030266 | 0.058754 | 0.442887 | 335 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.822764 | 0.183201 | 0.039019 | 0.075108 | 0.198596 | 7366 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.987748 | 0.804125 | 0.301917 | 0.463804 | 0.477643 | 299 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.023165 | -0.000599 | -0.044653 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.008753 | -0.157623 | 0.016354 | 12614 | 7031 |

### tianjin_core_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1042`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.972747 | 0.822562 | 0.000000 | 0.000000 | 0.486829 | 0 |
| markov_transition_projection | forecast_demand | 0.969274 | 0.786216 | 0.175573 | 0.298701 | 0.346229 | 572 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.969687 | 0.789089 | 0.186275 | 0.314050 | 0.346708 | 572 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.969687 | 0.789089 | 0.186275 | 0.314050 | 0.346708 | 572 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.969104 | 0.785033 | 0.182961 | 0.309327 | 0.347581 | 572 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.969687 | 0.789089 | 0.186275 | 0.314050 | 0.346708 | 572 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.805781 | 0.269630 | 0.091447 | 0.167570 | 0.209130 | 8104 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.972529 | 0.818069 | 0.078859 | 0.146190 | 0.437943 | 164 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.003314 | -0.000583 | -0.004723 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.094828 | -0.163906 | -0.146480 | 11086 | 7532 |

## 6. 下一步

- 建立 GLC_FCS30D 或 Dynamic World 的多区域 manifest。
- 增加 region-holdout，并将 ablation 从单区域扩展到多区域显著性统计。
- 将 demand 从简单历史趋势升级为独立情景需求模型。
