# TWM 公开多时期土地利用基准

更新日期：2026-06-22

## 1. 当前结论

本轮新增的是 TWM 的公开数据基准入口：它面向 GLC_FCS30D、Dynamic World、MODIS 等本地导出的多时期土地覆盖栅格栈，也可以用现有 DongGuan 80m 样例作为真实数据适配验证。

关键边界：`forecast_demand` 是正式预测设定；`oracle_demand` 使用目标年类别总量，只能作为上限诊断，不能作为真实预测结果。

## 2. 数据画像

- source type: `manifest`
- region count: `20`
- rolling case count: `100`

## 3. 渲染器输出

![Maps](assets/twm_public_landcover_benchmark_maps.png)

![Metrics](assets/twm_public_landcover_benchmark_metrics.png)

## 4. 汇总指标

| candidate | cases | mean OA | mean Kappa | mean change FoM | mean change F1 | mean macro F1 | target demand abs err | oracle demand abs err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| twm_ablation_no_demand_projection | 100 | 0.684568 | 0.418705 | 0.145773 | 0.249480 | 0.276936 | 938088 | 979126 |
| twm_independent_transition_oracle_demand | 100 | 0.920055 | 0.815725 | 0.129043 | 0.217537 | 0.535597 | 0 | 0 |
| twm_ablation_no_drivers_forecast_demand | 100 | 0.908293 | 0.789627 | 0.072575 | 0.133096 | 0.488534 | 0 | 325410 |
| twm_ablation_no_transition_prior_forecast_demand | 100 | 0.908287 | 0.789498 | 0.072329 | 0.132645 | 0.488046 | 0 | 325410 |
| twm_independent_transition_forecast_demand | 100 | 0.908289 | 0.789502 | 0.072289 | 0.132572 | 0.488305 | 0 | 325410 |
| twm_cross_region_smoothed_transition_forecast_demand | 100 | 0.908285 | 0.789484 | 0.072275 | 0.132543 | 0.488515 | 0 | 325410 |
| twm_calibrated_hierarchical_transition_forecast_demand | 100 | 0.908280 | 0.789488 | 0.072235 | 0.132471 | 0.487631 | 0 | 325410 |
| twm_hierarchical_transition_forecast_demand | 100 | 0.908282 | 0.789498 | 0.072135 | 0.132292 | 0.487298 | 0 | 325410 |
| twm_ablation_no_neighborhood_forecast_demand | 100 | 0.905953 | 0.784610 | 0.058692 | 0.108670 | 0.481672 | 0 | 325410 |
| markov_transition_projection | 100 | 0.903706 | 0.780626 | 0.045569 | 0.085295 | 0.478585 | 0 | 325410 |
| persistence | 100 | 0.925218 | 0.827574 | 0.000000 | 0.000000 | 0.554431 | 189862 | 198886 |

## 5. 组件贡献诊断

下表为正式 `forecast_demand` 设定下，full TWM 相对各对照项的聚合差值。正值表示 full TWM 更好；`no_demand_projection` 只用于诊断，不能作为合法预测候选。

| component | comparison | Δ full-comparison change FoM | Δ OA | Δ change F1 | Δ target demand error |
|---|---|---:|---:|---:|---:|
| transition_surface_vs_markov | markov_transition_projection | 0.026720 | 0.004583 | 0.047277 | 0 |
| hierarchical_pooling_candidate | twm_hierarchical_transition_forecast_demand | 0.000154 | 0.000007 | 0.000280 | 0 |
| calibrated_hierarchical_pooling_candidate | twm_calibrated_hierarchical_transition_forecast_demand | 0.000054 | 0.000009 | 0.000101 | 0 |
| cross_region_transition_smoothing_candidate | twm_cross_region_smoothed_transition_forecast_demand | 0.000014 | 0.000004 | 0.000029 | 0 |
| external_drivers | twm_ablation_no_drivers_forecast_demand | -0.000286 | -0.000004 | -0.000524 | 0 |
| neighborhood_context | twm_ablation_no_neighborhood_forecast_demand | 0.013597 | 0.002336 | 0.023902 | 0 |
| transition_prior | twm_ablation_no_transition_prior_forecast_demand | -0.000040 | 0.000002 | -0.000073 | 0 |
| demand_projection_constraint | twm_ablation_no_demand_projection | -0.073484 | 0.223721 | -0.116908 | -938088 |

## 6. 训练诊断

| candidate | cases | pass | review | fitted source classes | pooled fallback | hard fallback | local/pooled rate | mean pooled weight | cross-region support | cross-region smoothed | mean smooth weight | solvers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| twm_independent_transition_forecast_demand | 100 | 1 | 99 | 591 | 0 | 309 | 0.656667 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | lbfgs:590, newton-cg:1 |
| twm_hierarchical_transition_forecast_demand | 100 | 1 | 99 | 591 | 309 | 0 | 1.000000 | 1.000000 | 0.000000 | 0.000000 | 0.000000 | lbfgs:590, newton-cg:1 |
| twm_calibrated_hierarchical_transition_forecast_demand | 100 | 1 | 99 | 591 | 309 | 0 | 1.000000 | 0.307500 | 0.000000 | 0.000000 | 0.000000 | lbfgs:590, newton-cg:1 |
| twm_cross_region_smoothed_transition_forecast_demand | 100 | 100 | 0 | 0 | 0 | 0 | 0.000000 | 0.000000 | 1.000000 | 0.593333 | 0.105999 | n/a |
| twm_ablation_no_drivers_forecast_demand | 100 | 1 | 99 | 591 | 0 | 309 | 0.656667 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | lbfgs:591 |
| twm_ablation_no_neighborhood_forecast_demand | 100 | 1 | 99 | 591 | 0 | 309 | 0.656667 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | lbfgs:591 |
| twm_ablation_no_transition_prior_forecast_demand | 100 | 1 | 99 | 591 | 0 | 309 | 0.656667 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | lbfgs:590, newton-cg:1 |
| twm_ablation_no_demand_projection | 100 | 1 | 99 | 591 | 0 | 309 | 0.656667 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | lbfgs:590, newton-cg:1 |
| twm_independent_transition_oracle_demand | 100 | 1 | 99 | 591 | 0 | 309 | 0.656667 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | lbfgs:590, newton-cg:1 |

## 7. 单案例指标

### 上海市_浦东新区_祝桥镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4888`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.823057 | 0.776133 | 0.000000 | 0.000000 | 0.628628 | 0 |
| markov_transition_projection | forecast_demand | 0.800989 | 0.748576 | 0.036728 | 0.070854 | 0.588489 | 1077 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.812122 | 0.762641 | 0.063932 | 0.120180 | 0.600926 | 1077 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.812122 | 0.762641 | 0.063932 | 0.120180 | 0.600926 | 1077 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.812122 | 0.762641 | 0.063932 | 0.120180 | 0.600926 | 1077 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.812207 | 0.762748 | 0.064240 | 0.120725 | 0.601182 | 1077 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.812207 | 0.762748 | 0.064086 | 0.120452 | 0.602906 | 1077 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.810031 | 0.759999 | 0.061163 | 0.115275 | 0.599933 | 1077 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.812207 | 0.762748 | 0.064240 | 0.120725 | 0.601182 | 1077 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.547075 | 0.443987 | 0.259223 | 0.411719 | 0.370480 | 17084 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.827861 | 0.782569 | 0.200896 | 0.334577 | 0.613577 | 2316 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000154 | 0.000085 | 0.000272 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.002769 | -0.002091 | -0.004905 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000308 | 0.000085 | 0.000545 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.195291 | -0.265047 | 0.291539 | 8594 | 16007 |

### 上海市_浦东新区_祝桥镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `6990`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.855270 | 0.817800 | 0.000000 | 0.000000 | 0.731194 | 0 |
| markov_transition_projection | forecast_demand | 0.807431 | 0.758466 | 0.065710 | 0.123317 | 0.598876 | 2306 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.825064 | 0.780582 | 0.120362 | 0.214863 | 0.614818 | 2306 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.825064 | 0.780582 | 0.120362 | 0.214863 | 0.614818 | 2306 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.825064 | 0.780582 | 0.120362 | 0.214863 | 0.614818 | 2306 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.825064 | 0.780582 | 0.120362 | 0.214863 | 0.614818 | 2306 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.824470 | 0.779838 | 0.118001 | 0.211093 | 0.613350 | 2306 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.825374 | 0.780972 | 0.121885 | 0.217286 | 0.612262 | 2306 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.825064 | 0.780582 | 0.120362 | 0.214863 | 0.614818 | 2306 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.554422 | 0.453208 | 0.213607 | 0.352020 | 0.458342 | 16462 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.844956 | 0.805155 | 0.111130 | 0.200031 | 0.709405 | 1367 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002361 | -0.000594 | -0.003770 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.001523 | 0.000310 | 0.002423 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.093245 | -0.270642 | 0.137157 | 7548 | 14156 |

### 上海市_浦东新区_祝桥镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4598`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.810116 | 0.762291 | 0.000000 | 0.000000 | 0.659053 | 0 |
| markov_transition_projection | forecast_demand | 0.785617 | 0.731668 | 0.056296 | 0.106591 | 0.610031 | 1367 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.799943 | 0.749599 | 0.091216 | 0.167182 | 0.626308 | 1367 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.799943 | 0.749599 | 0.091216 | 0.167182 | 0.626308 | 1367 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.799943 | 0.749599 | 0.091216 | 0.167182 | 0.626308 | 1367 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.799943 | 0.749599 | 0.091216 | 0.167182 | 0.626308 | 1367 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.798870 | 0.748255 | 0.086670 | 0.159515 | 0.625548 | 1367 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.795338 | 0.743834 | 0.090480 | 0.165945 | 0.618118 | 1367 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.799943 | 0.749599 | 0.091216 | 0.167182 | 0.626308 | 1367 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.593275 | 0.499689 | 0.288609 | 0.447938 | 0.436753 | 15350 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.805821 | 0.756570 | 0.168420 | 0.288286 | 0.635984 | 2278 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.004546 | -0.001073 | -0.007667 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.000736 | -0.004605 | -0.001237 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.197393 | -0.206668 | 0.280756 | 4856 | 13983 |

### 上海市_浦东新区_祝桥镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `9158`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.827550 | 0.784034 | 0.000000 | 0.000000 | 0.710250 | 0 |
| markov_transition_projection | forecast_demand | 0.770500 | 0.713571 | 0.025450 | 0.049636 | 0.594845 | 2278 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.779401 | 0.724679 | 0.048674 | 0.092829 | 0.602844 | 2278 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.779344 | 0.724609 | 0.048542 | 0.092590 | 0.602811 | 2278 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.779344 | 0.724609 | 0.048542 | 0.092590 | 0.602811 | 2278 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.779401 | 0.724679 | 0.048674 | 0.092829 | 0.602844 | 2278 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.779514 | 0.724820 | 0.048411 | 0.092352 | 0.602859 | 2278 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.775784 | 0.720165 | 0.040084 | 0.077079 | 0.591983 | 2278 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.779401 | 0.724679 | 0.048674 | 0.092829 | 0.602844 | 2278 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.551031 | 0.450670 | 0.245565 | 0.394302 | 0.388197 | 16433 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.812659 | 0.764305 | 0.197837 | 0.330324 | 0.675447 | 2537 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000263 | 0.000113 | -0.000477 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.008590 | -0.003617 | -0.015750 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.196891 | -0.228370 | 0.301473 | 7352 | 14155 |

### 上海市_浦东新区_祝桥镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_ablation_no_transition_prior_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `7418`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.820345 | 0.772707 | 0.000000 | 0.000000 | 0.688474 | 0 |
| markov_transition_projection | forecast_demand | 0.777423 | 0.717977 | 0.091133 | 0.167043 | 0.565662 | 2502 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.784939 | 0.727500 | 0.105289 | 0.190519 | 0.575787 | 2502 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.784939 | 0.727500 | 0.105289 | 0.190519 | 0.575787 | 2502 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.784939 | 0.727500 | 0.105289 | 0.190519 | 0.575787 | 2502 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.784939 | 0.727500 | 0.105289 | 0.190519 | 0.575787 | 2502 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.785052 | 0.727644 | 0.105841 | 0.191422 | 0.576134 | 2502 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.785194 | 0.727823 | 0.104600 | 0.189391 | 0.563424 | 2502 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.785391 | 0.728073 | 0.106394 | 0.192325 | 0.576054 | 2502 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.534925 | 0.429087 | 0.263905 | 0.417603 | 0.367680 | 17411 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.817547 | 0.767248 | 0.120181 | 0.214574 | 0.681173 | 1574 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000552 | 0.000113 | 0.000903 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.000689 | 0.000255 | -0.001128 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.001105 | 0.000452 | 0.001806 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.158616 | -0.250014 | 0.227084 | 9038 | 14909 |

### 东莞市_东莞市_虎门镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1606`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.946767 | 0.915517 | 0.000000 | 0.000000 | 0.568394 | 0 |
| markov_transition_projection | forecast_demand | 0.930735 | 0.889315 | 0.030864 | 0.059880 | 0.488727 | 394 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.932751 | 0.892536 | 0.045929 | 0.087824 | 0.490799 | 394 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.932799 | 0.892613 | 0.045929 | 0.087824 | 0.490810 | 394 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.932799 | 0.892613 | 0.045929 | 0.087824 | 0.490810 | 394 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.932799 | 0.892613 | 0.045929 | 0.087824 | 0.490810 | 394 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.932463 | 0.892076 | 0.043026 | 0.082502 | 0.489354 | 394 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.932031 | 0.891386 | 0.040859 | 0.078510 | 0.487867 | 394 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.932751 | 0.892536 | 0.045929 | 0.087824 | 0.490799 | 394 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.662795 | 0.508378 | 0.116214 | 0.208228 | 0.267203 | 7228 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.939519 | 0.904214 | 0.151537 | 0.263191 | 0.566431 | 464 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002903 | -0.000288 | -0.005322 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.005070 | -0.000720 | -0.009314 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.070285 | -0.269956 | 0.120404 | 6432 | 6834 |

### 东莞市_东莞市_虎门镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1482`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.959007 | 0.934961 | 0.000000 | 0.000000 | 0.633380 | 0 |
| markov_transition_projection | forecast_demand | 0.939903 | 0.904927 | 0.042130 | 0.080854 | 0.488580 | 457 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.942687 | 0.909331 | 0.062399 | 0.117468 | 0.493357 | 457 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.942687 | 0.909331 | 0.062399 | 0.117468 | 0.493357 | 457 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.942687 | 0.909331 | 0.062399 | 0.117468 | 0.493357 | 457 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.942351 | 0.908800 | 0.058966 | 0.111365 | 0.491109 | 457 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.942639 | 0.909255 | 0.062399 | 0.117468 | 0.491420 | 457 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.941679 | 0.907736 | 0.056406 | 0.106789 | 0.493510 | 457 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.942687 | 0.909331 | 0.062399 | 0.117468 | 0.493357 | 457 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.699467 | 0.558054 | 0.109758 | 0.197805 | 0.280976 | 6527 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.950271 | 0.920936 | 0.062384 | 0.117441 | 0.595570 | 287 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | -0.000048 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.005993 | -0.001008 | -0.010679 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.047359 | -0.243220 | 0.080337 | 5364 | 6070 |

### 东莞市_东莞市_虎门镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `798`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.963327 | 0.941829 | 0.000000 | 0.000000 | 0.625113 | 0 |
| markov_transition_projection | forecast_demand | 0.950799 | 0.921805 | 0.019399 | 0.038059 | 0.576680 | 287 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.954735 | 0.928060 | 0.064843 | 0.121789 | 0.564238 | 287 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.954735 | 0.928060 | 0.064843 | 0.121789 | 0.564238 | 287 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.954735 | 0.928060 | 0.064843 | 0.121789 | 0.564238 | 287 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.954783 | 0.928137 | 0.065923 | 0.123692 | 0.566031 | 287 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.954351 | 0.927450 | 0.061616 | 0.116080 | 0.562307 | 287 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.951663 | 0.923178 | 0.031403 | 0.060894 | 0.560301 | 287 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.954735 | 0.928060 | 0.064843 | 0.121789 | 0.564238 | 287 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.731148 | 0.596435 | 0.101969 | 0.185066 | 0.313659 | 5785 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.958719 | 0.934663 | 0.035108 | 0.067834 | 0.614952 | 150 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.003227 | -0.000384 | -0.005709 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.033440 | -0.003072 | -0.060895 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.037126 | -0.223587 | 0.063277 | 3496 | 5498 |

### 东莞市_东莞市_虎门镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `578`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.949215 | 0.919697 | 0.000000 | 0.000000 | 0.548529 | 0 |
| markov_transition_projection | forecast_demand | 0.942783 | 0.909721 | 0.008347 | 0.016556 | 0.531353 | 150 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.944415 | 0.912296 | 0.024597 | 0.048013 | 0.519879 | 150 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.944415 | 0.912296 | 0.024597 | 0.048013 | 0.519879 | 150 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.944415 | 0.912296 | 0.024597 | 0.048013 | 0.519879 | 150 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.944415 | 0.912296 | 0.024597 | 0.048013 | 0.519879 | 150 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.944655 | 0.912675 | 0.027211 | 0.052980 | 0.520233 | 150 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.943071 | 0.910176 | 0.012573 | 0.024834 | 0.531475 | 150 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.944415 | 0.912296 | 0.024597 | 0.048013 | 0.519879 | 150 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.724188 | 0.591388 | 0.119141 | 0.212914 | 0.297533 | 5818 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.942783 | 0.909595 | 0.039571 | 0.076130 | 0.525194 | 203 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.002614 | 0.000240 | 0.004967 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.012024 | -0.001344 | -0.023179 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.094544 | -0.220227 | 0.164901 | 4060 | 5668 |

### 东莞市_东莞市_虎门镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `616`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.956175 | 0.930878 | 0.000000 | 0.000000 | 0.618015 | 0 |
| markov_transition_projection | forecast_demand | 0.947439 | 0.917156 | 0.017320 | 0.034050 | 0.579706 | 203 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.951087 | 0.922906 | 0.064885 | 0.121864 | 0.596329 | 203 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.951087 | 0.922906 | 0.064885 | 0.121864 | 0.596329 | 203 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.951087 | 0.922906 | 0.064885 | 0.121864 | 0.596329 | 203 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.951039 | 0.922830 | 0.062857 | 0.118280 | 0.595710 | 203 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.950751 | 0.922376 | 0.059829 | 0.112903 | 0.592435 | 203 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.949023 | 0.919653 | 0.040075 | 0.077061 | 0.589802 | 203 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.951087 | 0.922906 | 0.064885 | 0.121864 | 0.596329 | 203 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.687659 | 0.535882 | 0.106498 | 0.192495 | 0.281513 | 6682 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.948735 | 0.919263 | 0.054250 | 0.102916 | 0.609333 | 253 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.005056 | -0.000336 | -0.008961 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.024810 | -0.002064 | -0.044803 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.041613 | -0.263428 | 0.070631 | 3922 | 6479 |

### 佛山市_高明区_杨和镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1294`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.924022 | 0.822708 | 0.000000 | 0.000000 | 0.499207 | 0 |
| markov_transition_projection | forecast_demand | 0.903628 | 0.781822 | 0.010534 | 0.020849 | 0.480246 | 596 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.910971 | 0.798447 | 0.055403 | 0.104989 | 0.484670 | 596 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.910971 | 0.798447 | 0.055403 | 0.104989 | 0.484670 | 596 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.910971 | 0.798447 | 0.055403 | 0.104989 | 0.484670 | 596 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.910971 | 0.798447 | 0.055403 | 0.104989 | 0.484670 | 596 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.910644 | 0.797706 | 0.053747 | 0.102010 | 0.486240 | 596 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.906536 | 0.788406 | 0.030303 | 0.058824 | 0.478851 | 596 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.910971 | 0.798447 | 0.055403 | 0.104989 | 0.484670 | 596 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.622001 | 0.343704 | 0.137580 | 0.241882 | 0.247660 | 10536 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.919769 | 0.813659 | 0.045941 | 0.087846 | 0.487195 | 255 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001656 | -0.000327 | -0.002979 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.025100 | -0.004435 | -0.046165 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.082177 | -0.288970 | 0.136893 | 10830 | 9940 |

### 佛山市_高明区_杨和镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1150`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.939436 | 0.857614 | 0.000000 | 0.000000 | 0.558707 | 0 |
| markov_transition_projection | forecast_demand | 0.933038 | 0.843326 | 0.038940 | 0.074961 | 0.530110 | 255 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.934274 | 0.846218 | 0.045158 | 0.086413 | 0.530448 | 255 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.934274 | 0.846218 | 0.045158 | 0.086413 | 0.530448 | 255 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.934274 | 0.846218 | 0.045158 | 0.086413 | 0.530448 | 255 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.934237 | 0.846133 | 0.044589 | 0.085372 | 0.530277 | 255 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.934746 | 0.847324 | 0.050301 | 0.095783 | 0.533051 | 255 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.934019 | 0.845623 | 0.050301 | 0.095783 | 0.531800 | 255 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.934274 | 0.846218 | 0.045158 | 0.086413 | 0.530448 | 255 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.652174 | 0.359023 | 0.134771 | 0.237530 | 0.228330 | 9962 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.938054 | 0.852514 | 0.139227 | 0.244423 | 0.556555 | 396 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.005143 | 0.000472 | 0.009370 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.005143 | -0.000255 | 0.009370 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.089613 | -0.282100 | 0.151117 | 8852 | 9707 |

### 佛山市_高明区_杨和镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `608`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.946197 | 0.871773 | 0.000000 | 0.000000 | 0.585129 | 0 |
| markov_transition_projection | forecast_demand | 0.940163 | 0.855554 | 0.092075 | 0.168623 | 0.446376 | 394 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.941799 | 0.859503 | 0.105605 | 0.191035 | 0.453662 | 394 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.941799 | 0.859503 | 0.105605 | 0.191035 | 0.453662 | 394 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.941799 | 0.859503 | 0.105605 | 0.191035 | 0.453662 | 394 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.941762 | 0.859415 | 0.105605 | 0.191035 | 0.453634 | 394 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.941544 | 0.858888 | 0.104953 | 0.189968 | 0.455734 | 394 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.939945 | 0.855027 | 0.091439 | 0.167556 | 0.448583 | 394 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.941762 | 0.859415 | 0.105605 | 0.191035 | 0.453634 | 394 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.697470 | 0.406971 | 0.134103 | 0.236491 | 0.275759 | 8643 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.942998 | 0.863998 | 0.034418 | 0.066546 | 0.561896 | 173 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000652 | -0.000255 | -0.001067 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.014166 | -0.001854 | -0.023479 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | -0.000037 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.028498 | -0.244329 | 0.045456 | 8388 | 8249 |

### 佛山市_高明区_杨和镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `866`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.943326 | 0.866087 | 0.000000 | 0.000000 | 0.573902 | 0 |
| markov_transition_projection | forecast_demand | 0.938418 | 0.854342 | 0.014646 | 0.028868 | 0.540111 | 173 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.938636 | 0.854858 | 0.018824 | 0.036952 | 0.544235 | 173 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.938527 | 0.854600 | 0.017626 | 0.034642 | 0.537496 | 173 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.938600 | 0.854772 | 0.018824 | 0.036952 | 0.544230 | 173 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.938636 | 0.854858 | 0.018824 | 0.036952 | 0.544235 | 173 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.938600 | 0.854772 | 0.018824 | 0.036952 | 0.544206 | 173 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.938018 | 0.853396 | 0.012865 | 0.025404 | 0.529805 | 173 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.938600 | 0.854772 | 0.018225 | 0.035797 | 0.540868 | 173 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.690817 | 0.408866 | 0.135709 | 0.238985 | 0.255041 | 8768 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.938854 | 0.856879 | 0.076251 | 0.141698 | 0.558689 | 290 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | -0.000036 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.005959 | -0.000618 | -0.011548 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000599 | -0.000036 | -0.001155 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.116885 | -0.247819 | 0.202033 | 7882 | 8595 |

### 佛山市_高明区_杨和镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1048`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.941399 | 0.861734 | 0.000000 | 0.000000 | 0.548434 | 0 |
| markov_transition_projection | forecast_demand | 0.934128 | 0.846061 | 0.045055 | 0.086225 | 0.503260 | 290 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.934674 | 0.847335 | 0.049090 | 0.093586 | 0.510083 | 290 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.934674 | 0.847335 | 0.049090 | 0.093586 | 0.510083 | 290 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.934674 | 0.847335 | 0.049090 | 0.093586 | 0.510083 | 290 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.934710 | 0.847420 | 0.049669 | 0.094637 | 0.511861 | 290 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.934637 | 0.847250 | 0.049669 | 0.094637 | 0.508988 | 290 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.934674 | 0.847335 | 0.050248 | 0.095689 | 0.509081 | 290 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.934674 | 0.847335 | 0.049090 | 0.093586 | 0.510083 | 290 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.611386 | 0.336187 | 0.105370 | 0.190651 | 0.248638 | 10924 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.938563 | 0.853847 | 0.068376 | 0.128000 | 0.528438 | 263 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000579 | -0.000037 | 0.001051 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.001158 | 0.000000 | 0.002103 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.056280 | -0.323288 | 0.097065 | 11932 | 10634 |

### 北京市_密云县_石城镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `10202`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.899394 | 0.715070 | 0.000000 | 0.000000 | 0.549702 | 0 |
| markov_transition_projection | forecast_demand | 0.874647 | 0.663344 | 0.003312 | 0.006602 | 0.494763 | 1158 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.876179 | 0.667458 | 0.009825 | 0.019458 | 0.502061 | 1158 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.876179 | 0.667458 | 0.009825 | 0.019458 | 0.502061 | 1158 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.876179 | 0.667458 | 0.009825 | 0.019458 | 0.502061 | 1158 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.876157 | 0.667399 | 0.009647 | 0.019110 | 0.500878 | 1158 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.875916 | 0.666753 | 0.008763 | 0.017373 | 0.499928 | 1158 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.874538 | 0.663051 | 0.002962 | 0.005907 | 0.496025 | 1158 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.876179 | 0.667458 | 0.009825 | 0.019458 | 0.502061 | 1158 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.679080 | 0.346384 | 0.172121 | 0.293692 | 0.293747 | 15171 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.929655 | 0.754343 | 0.481392 | 0.649919 | 0.535076 | 4000 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001062 | -0.000263 | -0.002085 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.006863 | -0.001641 | -0.013551 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.162296 | -0.197099 | 0.274234 | 13506 | 14013 |

### 北京市_密云县_石城镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `19668`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.834869 | 0.593722 | 0.000000 | 0.000000 | 0.545493 | 0 |
| markov_transition_projection | forecast_demand | 0.777017 | 0.407461 | 0.010949 | 0.021661 | 0.450474 | 2794 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.778242 | 0.410717 | 0.014719 | 0.029011 | 0.452962 | 2794 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.778242 | 0.410717 | 0.014719 | 0.029011 | 0.452962 | 2794 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.778242 | 0.410717 | 0.014719 | 0.029011 | 0.452962 | 2794 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.778242 | 0.410717 | 0.014719 | 0.029011 | 0.452962 | 2794 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.778220 | 0.410658 | 0.014619 | 0.028817 | 0.450576 | 2794 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.777433 | 0.408565 | 0.012632 | 0.024949 | 0.449460 | 2794 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.778242 | 0.410717 | 0.014719 | 0.029011 | 0.452962 | 2794 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.705380 | 0.359132 | 0.136364 | 0.240000 | 0.304495 | 8928 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.751329 | 0.486617 | 0.146648 | 0.255785 | 0.522753 | 7059 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000100 | -0.000022 | -0.000194 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.002087 | -0.000809 | -0.004062 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.121645 | -0.072862 | 0.210989 | 13634 | 6134 |

### 北京市_密云县_石城镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `14840`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.885587 | 0.769136 | 0.000000 | 0.000000 | 0.583440 | 0 |
| markov_transition_projection | forecast_demand | 0.752336 | 0.567492 | 0.057207 | 0.108223 | 0.478754 | 7042 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.768352 | 0.595462 | 0.089206 | 0.163801 | 0.488748 | 7042 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.768374 | 0.595500 | 0.089303 | 0.163964 | 0.488752 | 7042 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.768352 | 0.595462 | 0.089206 | 0.163801 | 0.488748 | 7042 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.768352 | 0.595462 | 0.089206 | 0.163801 | 0.488748 | 7042 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.766295 | 0.591870 | 0.082672 | 0.152718 | 0.486398 | 7042 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.757149 | 0.575898 | 0.070861 | 0.132345 | 0.484461 | 7042 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.768352 | 0.595462 | 0.089206 | 0.163801 | 0.488748 | 7042 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.521126 | 0.304695 | 0.153095 | 0.265538 | 0.288061 | 21946 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.873816 | 0.749970 | 0.129404 | 0.229155 | 0.552252 | 1823 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.006534 | -0.002057 | -0.011083 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.018345 | -0.011203 | -0.031456 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.063889 | -0.247226 | 0.101737 | 18608 | 14904 |

### 北京市_密云县_石城镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `15490`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.837844 | 0.624156 | 0.000000 | 0.000000 | 0.501074 | 0 |
| markov_transition_projection | forecast_demand | 0.809312 | 0.571148 | 0.056141 | 0.106314 | 0.424259 | 1807 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.811238 | 0.575479 | 0.058567 | 0.110653 | 0.433217 | 1807 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.811194 | 0.575380 | 0.058324 | 0.110219 | 0.422615 | 1807 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.811194 | 0.575380 | 0.058324 | 0.110219 | 0.422615 | 1807 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.811238 | 0.575479 | 0.058567 | 0.110653 | 0.432352 | 1807 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.810713 | 0.574298 | 0.056504 | 0.106965 | 0.435652 | 1807 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.810691 | 0.574248 | 0.060759 | 0.114558 | 0.408440 | 1807 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.811238 | 0.575479 | 0.058567 | 0.110653 | 0.433217 | 1807 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.585826 | 0.273872 | 0.199102 | 0.332085 | 0.245112 | 19016 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.885478 | 0.648714 | 0.470631 | 0.640040 | 0.479924 | 6635 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002063 | -0.000525 | -0.003688 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.002192 | -0.000547 | 0.003905 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.140535 | -0.225412 | 0.221432 | 15046 | 17209 |

### 北京市_密云县_石城镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `18052`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.903245 | 0.745248 | 0.000000 | 0.000000 | 0.572325 | 0 |
| markov_transition_projection | forecast_demand | 0.797738 | 0.331668 | 0.055336 | 0.104869 | 0.356170 | 5724 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.799422 | 0.337235 | 0.060299 | 0.113739 | 0.358004 | 5724 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.799422 | 0.337235 | 0.060299 | 0.113739 | 0.358004 | 5724 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.799422 | 0.337235 | 0.060299 | 0.113739 | 0.358004 | 5724 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.799422 | 0.337235 | 0.060299 | 0.113739 | 0.358004 | 5724 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.799422 | 0.337235 | 0.060299 | 0.113739 | 0.358004 | 5724 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.798328 | 0.333621 | 0.056985 | 0.107826 | 0.356786 | 5724 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.799422 | 0.337235 | 0.060299 | 0.113739 | 0.358004 | 5724 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.766974 | 0.440959 | 0.149046 | 0.259425 | 0.335253 | 9185 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.866683 | 0.686101 | 0.134582 | 0.237236 | 0.543955 | 3334 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.003314 | -0.001094 | -0.005913 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.088747 | -0.032448 | 0.145686 | 16132 | 3461 |

### 南京市_六合区_马鞍街道_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4620`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.903703 | 0.846368 | 0.000000 | 0.000000 | 0.563134 | 0 |
| markov_transition_projection | forecast_demand | 0.865258 | 0.776913 | 0.079032 | 0.146486 | 0.478727 | 1989 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.876828 | 0.796070 | 0.124244 | 0.221027 | 0.495966 | 1989 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.876828 | 0.796070 | 0.124244 | 0.221027 | 0.495966 | 1989 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.876828 | 0.796070 | 0.124244 | 0.221027 | 0.495966 | 1989 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.876970 | 0.796304 | 0.124713 | 0.221769 | 0.496023 | 1989 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.878356 | 0.798599 | 0.129661 | 0.229557 | 0.493100 | 1989 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.871368 | 0.787030 | 0.102412 | 0.185796 | 0.493937 | 1989 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.876828 | 0.796070 | 0.124244 | 0.221027 | 0.495966 | 1989 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.579309 | 0.378848 | 0.152011 | 0.263905 | 0.297161 | 15618 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.896150 | 0.834148 | 0.088574 | 0.162735 | 0.573509 | 750 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.005417 | 0.001528 | 0.008530 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.021832 | -0.005460 | -0.035231 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.027767 | -0.297519 | 0.042878 | 10954 | 13629 |

### 南京市_六合区_马鞍街道_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `5072`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.878724 | 0.814910 | 0.000000 | 0.000000 | 0.547362 | 0 |
| markov_transition_projection | forecast_demand | 0.860647 | 0.787195 | 0.012548 | 0.024785 | 0.508086 | 716 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.866984 | 0.796872 | 0.036247 | 0.069958 | 0.516984 | 716 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.866927 | 0.796785 | 0.036032 | 0.069558 | 0.516960 | 716 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.866927 | 0.796785 | 0.036032 | 0.069558 | 0.516960 | 716 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.866927 | 0.796785 | 0.036032 | 0.069558 | 0.515972 | 716 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.866361 | 0.795921 | 0.034105 | 0.065960 | 0.517709 | 716 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.863815 | 0.792033 | 0.024156 | 0.047172 | 0.510129 | 716 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.866984 | 0.796872 | 0.036247 | 0.069958 | 0.516984 | 716 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.561034 | 0.378040 | 0.186771 | 0.314755 | 0.279412 | 16364 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.866446 | 0.802697 | 0.228207 | 0.371610 | 0.545721 | 2645 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002142 | -0.000623 | -0.003998 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.012091 | -0.003169 | -0.022786 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.150524 | -0.305950 | 0.244797 | 8688 | 15648 |

### 南京市_六合区_马鞍街道_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `7534`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.899573 | 0.849884 | 0.000000 | 0.000000 | 0.603064 | 0 |
| markov_transition_projection | forecast_demand | 0.831707 | 0.757683 | 0.032855 | 0.063620 | 0.509815 | 2643 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.844211 | 0.775687 | 0.073496 | 0.136929 | 0.523662 | 2643 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.844154 | 0.775606 | 0.073310 | 0.136606 | 0.523639 | 2643 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.844154 | 0.775606 | 0.073310 | 0.136606 | 0.523639 | 2643 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.844097 | 0.775524 | 0.073310 | 0.136606 | 0.522700 | 2643 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.845116 | 0.776991 | 0.076669 | 0.142419 | 0.523615 | 2643 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.835894 | 0.763712 | 0.047353 | 0.090425 | 0.512396 | 2643 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.844126 | 0.775565 | 0.073310 | 0.136606 | 0.523170 | 2643 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.522844 | 0.339551 | 0.161351 | 0.277868 | 0.253770 | 17899 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.897819 | 0.844795 | 0.195053 | 0.326434 | 0.592121 | 1523 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.003173 | 0.000905 | 0.005490 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.026143 | -0.008317 | -0.046504 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000186 | -0.000085 | -0.000323 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.087855 | -0.321367 | 0.140939 | 8242 | 15256 |

### 南京市_六合区_马鞍街道_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1548`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.910464 | 0.861660 | 0.000000 | 0.000000 | 0.630595 | 0 |
| markov_transition_projection | forecast_demand | 0.880393 | 0.811615 | 0.065727 | 0.123346 | 0.594539 | 1521 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.900931 | 0.843963 | 0.159901 | 0.275715 | 0.615307 | 1521 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.900931 | 0.843963 | 0.159901 | 0.275715 | 0.615307 | 1521 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.900931 | 0.843963 | 0.159901 | 0.275715 | 0.615307 | 1521 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.900874 | 0.843874 | 0.159614 | 0.275288 | 0.615276 | 1521 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.899403 | 0.841557 | 0.151069 | 0.262484 | 0.610851 | 1521 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.893802 | 0.832735 | 0.129157 | 0.228767 | 0.606724 | 1521 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.900931 | 0.843963 | 0.159901 | 0.275715 | 0.615307 | 1521 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.579139 | 0.390615 | 0.151137 | 0.262588 | 0.298535 | 15861 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.908201 | 0.855393 | 0.142394 | 0.249290 | 0.638244 | 1063 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.008832 | -0.001528 | -0.013231 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.030744 | -0.007129 | -0.046948 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.008764 | -0.321792 | -0.013127 | 7996 | 14340 |

### 南京市_六合区_马鞍街道_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1442`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.919206 | 0.871651 | 0.000000 | 0.000000 | 0.618357 | 0 |
| markov_transition_projection | forecast_demand | 0.898611 | 0.835682 | 0.051920 | 0.098715 | 0.529850 | 1034 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.908937 | 0.852417 | 0.107946 | 0.194859 | 0.547605 | 1034 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.908937 | 0.852417 | 0.107946 | 0.194859 | 0.547605 | 1034 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.908937 | 0.852417 | 0.107946 | 0.194859 | 0.547605 | 1034 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.908965 | 0.852463 | 0.107631 | 0.194344 | 0.546745 | 1034 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.909106 | 0.852692 | 0.107631 | 0.194344 | 0.548678 | 1034 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.904523 | 0.845264 | 0.085379 | 0.157326 | 0.547981 | 1034 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.908937 | 0.852417 | 0.107946 | 0.194859 | 0.547605 | 1034 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.588814 | 0.389380 | 0.138274 | 0.242954 | 0.292233 | 15452 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.913095 | 0.860714 | 0.050439 | 0.096033 | 0.593432 | 497 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000315 | 0.000169 | -0.000515 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.022567 | -0.004414 | -0.037533 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.030328 | -0.320123 | 0.048095 | 8582 | 14418 |

### 厦门市_同安区_莲花镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `462`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.965016 | 0.857778 | 0.000000 | 0.000000 | 0.510995 | 0 |
| markov_transition_projection | forecast_demand | 0.960249 | 0.837807 | 0.053846 | 0.102190 | 0.478275 | 186 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.961364 | 0.842356 | 0.065112 | 0.122263 | 0.474603 | 186 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.961595 | 0.843297 | 0.069268 | 0.129562 | 0.481871 | 186 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.961595 | 0.843297 | 0.069268 | 0.129562 | 0.481871 | 186 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.961133 | 0.841415 | 0.062016 | 0.116788 | 0.463354 | 186 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.961210 | 0.841729 | 0.060987 | 0.114964 | 0.470413 | 186 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.959903 | 0.836395 | 0.042816 | 0.082117 | 0.477778 | 186 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.961249 | 0.841885 | 0.064078 | 0.120438 | 0.471065 | 186 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.714478 | 0.318233 | 0.093308 | 0.170689 | 0.218751 | 7585 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.964709 | 0.855109 | 0.073996 | 0.137795 | 0.484618 | 106 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.004125 | -0.000154 | -0.007299 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.022296 | -0.001461 | -0.040146 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.001034 | -0.000115 | -0.001825 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.028196 | -0.246886 | 0.048426 | 10650 | 7399 |

### 厦门市_同安区_莲花镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `282`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.970975 | 0.880188 | 0.000000 | 0.000000 | 0.583972 | 0 |
| markov_transition_projection | forecast_demand | 0.969283 | 0.871933 | 0.055147 | 0.104530 | 0.483518 | 106 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.969822 | 0.874177 | 0.059041 | 0.111498 | 0.482373 | 106 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.969937 | 0.874657 | 0.062963 | 0.118467 | 0.479136 | 106 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.969745 | 0.873856 | 0.061652 | 0.116144 | 0.475092 | 106 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.969783 | 0.874016 | 0.059041 | 0.111498 | 0.482368 | 106 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.969860 | 0.874337 | 0.061652 | 0.116144 | 0.483035 | 106 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.969514 | 0.872894 | 0.057740 | 0.109175 | 0.468918 | 106 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.969860 | 0.874337 | 0.059041 | 0.111498 | 0.482378 | 106 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.708365 | 0.319026 | 0.072769 | 0.135665 | 0.229171 | 7707 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.969629 | 0.873945 | 0.045963 | 0.087886 | 0.546747 | 87 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.002611 | 0.000038 | 0.004646 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.001301 | -0.000308 | -0.002323 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000038 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.013728 | -0.261457 | 0.024167 | 11450 | 7601 |

### 厦门市_同安区_莲花镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `224`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.973128 | 0.887407 | 0.000000 | 0.000000 | 0.670059 | 0 |
| markov_transition_projection | forecast_demand | 0.970706 | 0.876766 | 0.014398 | 0.028387 | 0.555638 | 76 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.971398 | 0.879677 | 0.026490 | 0.051613 | 0.561316 | 76 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.971398 | 0.879677 | 0.025132 | 0.049032 | 0.559937 | 76 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.971436 | 0.879838 | 0.025132 | 0.049032 | 0.560856 | 76 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.971475 | 0.880000 | 0.027851 | 0.054194 | 0.561791 | 76 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.971321 | 0.879353 | 0.023778 | 0.046452 | 0.560318 | 76 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.970821 | 0.877251 | 0.017060 | 0.033548 | 0.558032 | 76 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.971398 | 0.879677 | 0.026490 | 0.051613 | 0.561316 | 76 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.810126 | 0.428981 | 0.110104 | 0.198367 | 0.255752 | 5179 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.973128 | 0.886325 | 0.063187 | 0.118863 | 0.658808 | 75 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002712 | -0.000077 | -0.005161 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.009430 | -0.000577 | -0.018065 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.083614 | -0.161272 | 0.146754 | 6034 | 5103 |

### 厦门市_同安区_莲花镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `174`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.974473 | 0.891395 | 0.000000 | 0.000000 | 0.589745 | 0 |
| markov_transition_projection | forecast_demand | 0.973205 | 0.884882 | 0.037921 | 0.073072 | 0.518365 | 75 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.974012 | 0.888350 | 0.054208 | 0.102842 | 0.564104 | 75 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.973858 | 0.887690 | 0.054208 | 0.102842 | 0.564013 | 75 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.973858 | 0.887690 | 0.054208 | 0.102842 | 0.564013 | 75 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.973897 | 0.887855 | 0.051209 | 0.097429 | 0.562987 | 75 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.973858 | 0.887690 | 0.051209 | 0.097429 | 0.562900 | 75 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.973474 | 0.886038 | 0.042313 | 0.081191 | 0.517449 | 75 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.974012 | 0.888350 | 0.054208 | 0.102842 | 0.564104 | 75 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.805167 | 0.425429 | 0.099516 | 0.181018 | 0.270782 | 5247 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.973358 | 0.885990 | 0.071429 | 0.133333 | 0.586405 | 101 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002999 | -0.000154 | -0.005413 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.011895 | -0.000538 | -0.021651 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.045308 | -0.168845 | 0.078176 | 6464 | 5172 |

### 厦门市_同安区_莲花镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `320`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.973012 | 0.884421 | 0.000000 | 0.000000 | 0.553175 | 0 |
| markov_transition_projection | forecast_demand | 0.970437 | 0.872646 | 0.025543 | 0.049813 | 0.527557 | 101 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.970245 | 0.871818 | 0.028169 | 0.054795 | 0.525893 | 101 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.970245 | 0.871818 | 0.028169 | 0.054795 | 0.525893 | 101 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.970245 | 0.871818 | 0.028169 | 0.054795 | 0.525893 | 101 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.970283 | 0.871984 | 0.029487 | 0.057285 | 0.526424 | 101 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.970283 | 0.871984 | 0.029487 | 0.057285 | 0.526913 | 101 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.970514 | 0.872978 | 0.038810 | 0.074720 | 0.531714 | 101 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.970283 | 0.871984 | 0.029487 | 0.057285 | 0.526424 | 101 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.811433 | 0.437333 | 0.101115 | 0.183659 | 0.258823 | 5026 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.971667 | 0.878556 | 0.088391 | 0.162424 | 0.555805 | 123 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.001318 | 0.000038 | 0.002490 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.010641 | 0.000269 | 0.019925 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.001318 | 0.000038 | 0.002490 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.072946 | -0.158812 | 0.128864 | 6306 | 4925 |

### 合肥市_巢湖市_散兵镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1616`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.955784 | 0.932038 | 0.000000 | 0.000000 | 0.625018 | 0 |
| markov_transition_projection | forecast_demand | 0.937351 | 0.904324 | 0.048204 | 0.091975 | 0.518570 | 738 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.942370 | 0.911989 | 0.100744 | 0.183048 | 0.526566 | 738 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.942370 | 0.911989 | 0.100744 | 0.183048 | 0.526566 | 738 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.942370 | 0.911989 | 0.100744 | 0.183048 | 0.526566 | 738 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.942370 | 0.911989 | 0.101291 | 0.183950 | 0.526536 | 738 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.942071 | 0.911533 | 0.098564 | 0.179441 | 0.537961 | 738 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.939561 | 0.907701 | 0.074092 | 0.137962 | 0.520523 | 738 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.942400 | 0.912035 | 0.101291 | 0.183950 | 0.526573 | 738 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.807660 | 0.706483 | 0.153097 | 0.265541 | 0.399112 | 6692 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.950556 | 0.924002 | 0.068525 | 0.128261 | 0.603335 | 360 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002180 | -0.000299 | -0.003607 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.026652 | -0.002809 | -0.045086 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000547 | 0.000030 | 0.000902 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.052353 | -0.134710 | 0.082493 | 4400 | 5954 |

### 合肥市_巢湖市_散兵镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1942`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.952976 | 0.927234 | 0.000000 | 0.000000 | 0.573594 | 0 |
| markov_transition_projection | forecast_demand | 0.942967 | 0.911767 | 0.012036 | 0.023785 | 0.550081 | 360 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.944999 | 0.914910 | 0.032568 | 0.063082 | 0.553065 | 360 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.944999 | 0.914910 | 0.032568 | 0.063082 | 0.553065 | 360 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.944999 | 0.914910 | 0.032568 | 0.063082 | 0.553065 | 360 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.944999 | 0.914910 | 0.032568 | 0.063082 | 0.553065 | 360 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.944760 | 0.914540 | 0.029271 | 0.056877 | 0.552470 | 360 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.944401 | 0.913985 | 0.026539 | 0.051706 | 0.552496 | 360 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.944999 | 0.914910 | 0.032568 | 0.063082 | 0.553065 | 360 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.777575 | 0.665609 | 0.149693 | 0.260406 | 0.349364 | 7796 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.948614 | 0.919890 | 0.184878 | 0.312063 | 0.544412 | 714 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.003297 | -0.000239 | -0.006205 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.006029 | -0.000598 | -0.011376 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.117125 | -0.167424 | 0.197324 | 5426 | 7436 |

### 合肥市_巢湖市_散兵镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1568`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.953245 | 0.927391 | 0.000000 | 0.000000 | 0.614120 | 0 |
| markov_transition_projection | forecast_demand | 0.938098 | 0.903143 | 0.063462 | 0.119351 | 0.502470 | 714 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.946074 | 0.915624 | 0.151010 | 0.262396 | 0.525022 | 714 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.946134 | 0.915718 | 0.151592 | 0.263273 | 0.525070 | 714 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.946134 | 0.915718 | 0.151592 | 0.263273 | 0.525070 | 714 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.946254 | 0.915905 | 0.152757 | 0.265029 | 0.525172 | 714 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.945656 | 0.914970 | 0.142929 | 0.250110 | 0.522740 | 714 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.944670 | 0.913427 | 0.144076 | 0.251865 | 0.519630 | 714 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.946104 | 0.915671 | 0.151592 | 0.263273 | 0.525063 | 714 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.781638 | 0.671791 | 0.146640 | 0.255773 | 0.365566 | 7529 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.944610 | 0.914294 | 0.056872 | 0.107623 | 0.577444 | 442 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.008081 | -0.000418 | -0.012286 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.006934 | -0.001404 | -0.010531 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000582 | 0.000030 | 0.000877 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.004370 | -0.164436 | -0.006623 | 6522 | 6815 |

### 合肥市_巢湖市_散兵镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1856`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.946254 | 0.917170 | 0.000000 | 0.000000 | 0.582938 | 0 |
| markov_transition_projection | forecast_demand | 0.933825 | 0.898403 | 0.010825 | 0.021419 | 0.539566 | 442 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.936693 | 0.902806 | 0.041841 | 0.080321 | 0.544552 | 442 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.936693 | 0.902806 | 0.041841 | 0.080321 | 0.544552 | 442 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.936693 | 0.902806 | 0.041841 | 0.080321 | 0.544552 | 442 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.936693 | 0.902806 | 0.041841 | 0.080321 | 0.544552 | 442 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.936634 | 0.902714 | 0.041357 | 0.079429 | 0.545008 | 442 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.934692 | 0.899733 | 0.022821 | 0.044623 | 0.540968 | 442 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.936693 | 0.902806 | 0.041841 | 0.080321 | 0.544552 | 442 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.762159 | 0.651456 | 0.154886 | 0.268227 | 0.357928 | 8200 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.942788 | 0.912125 | 0.216833 | 0.356389 | 0.580940 | 760 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000484 | -0.000059 | -0.000892 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.019020 | -0.002001 | -0.035698 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.113045 | -0.174534 | 0.187906 | 6742 | 7758 |

### 合肥市_巢湖市_散兵镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_calibrated_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1972`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.944909 | 0.915622 | 0.000000 | 0.000000 | 0.590168 | 0 |
| markov_transition_projection | forecast_demand | 0.928478 | 0.890969 | 0.058559 | 0.110638 | 0.462628 | 741 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.932750 | 0.897482 | 0.086591 | 0.159381 | 0.471488 | 741 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.932750 | 0.897482 | 0.086591 | 0.159381 | 0.471488 | 741 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.932780 | 0.897527 | 0.087048 | 0.160155 | 0.483184 | 741 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.932810 | 0.897573 | 0.087048 | 0.160155 | 0.483214 | 741 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.932302 | 0.896798 | 0.084312 | 0.155513 | 0.474196 | 741 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.929882 | 0.893109 | 0.069065 | 0.129207 | 0.476350 | 741 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.932780 | 0.897527 | 0.086591 | 0.159381 | 0.471526 | 741 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.824420 | 0.735756 | 0.178829 | 0.303401 | 0.422024 | 6007 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.935767 | 0.901859 | 0.103214 | 0.187115 | 0.564656 | 593 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002279 | -0.000448 | -0.003868 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.017526 | -0.002868 | -0.030174 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000030 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.092238 | -0.108330 | 0.144020 | 2438 | 5266 |

### 天津市_滨海新区_临港工业区_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `markov_transition_projection`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `6010`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.877164 | 0.796679 | 0.000000 | 0.000000 | 0.643723 | 0 |
| markov_transition_projection | forecast_demand | 0.839801 | 0.728956 | 0.073130 | 0.136293 | 0.538930 | 1731 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.842150 | 0.732929 | 0.062146 | 0.117019 | 0.564146 | 1731 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.842150 | 0.732929 | 0.062146 | 0.117019 | 0.564146 | 1731 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.842150 | 0.732929 | 0.062146 | 0.117019 | 0.564146 | 1731 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.842150 | 0.732929 | 0.062146 | 0.117019 | 0.565387 | 1731 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.843384 | 0.735018 | 0.068002 | 0.127345 | 0.565745 | 1731 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.836760 | 0.723811 | 0.047404 | 0.090518 | 0.551556 | 1731 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.842089 | 0.732828 | 0.061952 | 0.116675 | 0.562531 | 1731 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.695710 | 0.503186 | 0.210351 | 0.347586 | 0.368770 | 10069 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.856932 | 0.769265 | 0.103583 | 0.187721 | 0.634802 | 1588 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.005856 | 0.001234 | 0.010326 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.014742 | -0.005390 | -0.026501 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000194 | -0.000061 | -0.000344 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.148205 | -0.146440 | 0.230567 | 3632 | 8338 |

### 天津市_滨海新区_临港工业区_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `5778`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.886949 | 0.816917 | 0.000000 | 0.000000 | 0.628219 | 0 |
| markov_transition_projection | forecast_demand | 0.842059 | 0.751226 | 0.015008 | 0.029571 | 0.556443 | 1588 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.853952 | 0.769957 | 0.060119 | 0.113419 | 0.571158 | 1588 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.853952 | 0.769957 | 0.060119 | 0.113419 | 0.571158 | 1588 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.853952 | 0.769957 | 0.060119 | 0.113419 | 0.571158 | 1588 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.853952 | 0.769957 | 0.060119 | 0.113419 | 0.571158 | 1588 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.853500 | 0.769246 | 0.059068 | 0.111548 | 0.569244 | 1588 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.843625 | 0.753692 | 0.019462 | 0.038181 | 0.566412 | 1588 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.853952 | 0.769957 | 0.060119 | 0.113419 | 0.571158 | 1588 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.712419 | 0.554875 | 0.233503 | 0.378602 | 0.425703 | 10022 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.885413 | 0.813088 | 0.168511 | 0.288420 | 0.597738 | 1314 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001051 | -0.000452 | -0.001871 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.040657 | -0.010327 | -0.075238 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.173384 | -0.141533 | 0.265183 | 3988 | 8434 |

### 天津市_滨海新区_临港工业区_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `2958`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.887250 | 0.816889 | 0.000000 | 0.000000 | 0.599605 | 0 |
| markov_transition_projection | forecast_demand | 0.863736 | 0.776993 | 0.081462 | 0.150652 | 0.537212 | 1313 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.877254 | 0.799117 | 0.136885 | 0.240807 | 0.555721 | 1313 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.877254 | 0.799117 | 0.136885 | 0.240807 | 0.555721 | 1313 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.877254 | 0.799117 | 0.136885 | 0.240807 | 0.555721 | 1313 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.877375 | 0.799314 | 0.137652 | 0.241993 | 0.555828 | 1313 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.876351 | 0.797639 | 0.131291 | 0.232108 | 0.553048 | 1313 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.866897 | 0.782167 | 0.102681 | 0.186240 | 0.541013 | 1313 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.877314 | 0.799215 | 0.137396 | 0.241597 | 0.555371 | 1313 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.654102 | 0.479646 | 0.193461 | 0.324202 | 0.348069 | 11696 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.877796 | 0.802325 | 0.056632 | 0.107193 | 0.569479 | 565 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.005594 | -0.000903 | -0.008699 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.034204 | -0.010357 | -0.054567 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000511 | 0.000060 | 0.000790 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.056576 | -0.223152 | 0.083395 | 8148 | 10383 |

### 天津市_滨海新区_临港工业区_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_transition_prior_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `3624`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.871684 | 0.792039 | 0.000000 | 0.000000 | 0.606158 | 0 |
| markov_transition_projection | forecast_demand | 0.857655 | 0.770219 | 0.019861 | 0.038948 | 0.561630 | 565 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.862020 | 0.777266 | 0.044127 | 0.084525 | 0.590730 | 565 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.861990 | 0.777217 | 0.043901 | 0.084110 | 0.590705 | 565 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.861990 | 0.777217 | 0.043901 | 0.084110 | 0.590705 | 565 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.862020 | 0.777266 | 0.044127 | 0.084525 | 0.590730 | 565 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.861719 | 0.776780 | 0.042774 | 0.082039 | 0.590121 | 565 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.860274 | 0.774447 | 0.038735 | 0.074580 | 0.567627 | 565 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.862050 | 0.777314 | 0.044353 | 0.084939 | 0.590754 | 565 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.588800 | 0.411232 | 0.211558 | 0.349233 | 0.327341 | 14459 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.872949 | 0.792942 | 0.214493 | 0.353223 | 0.615598 | 1587 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001353 | -0.000301 | -0.002486 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.005392 | -0.001746 | -0.009945 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000226 | 0.000030 | 0.000414 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.167431 | -0.273220 | 0.264708 | 12270 | 13894 |

### 天津市_滨海新区_临港工业区_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4348`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.871745 | 0.792045 | 0.000000 | 0.000000 | 0.646195 | 0 |
| markov_transition_projection | forecast_demand | 0.844919 | 0.747009 | 0.111808 | 0.201129 | 0.540910 | 1587 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.851483 | 0.757716 | 0.129200 | 0.228835 | 0.557912 | 1587 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.851453 | 0.757667 | 0.128982 | 0.228493 | 0.553377 | 1587 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.851453 | 0.757667 | 0.128982 | 0.228493 | 0.553377 | 1587 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.851483 | 0.757716 | 0.129200 | 0.228835 | 0.557912 | 1587 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.851603 | 0.757913 | 0.128111 | 0.227125 | 0.557574 | 1587 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.846154 | 0.749023 | 0.113502 | 0.203865 | 0.533616 | 1587 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.851392 | 0.757569 | 0.128547 | 0.227809 | 0.553192 | 1587 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.707572 | 0.547867 | 0.250977 | 0.401250 | 0.374950 | 9821 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.867048 | 0.785108 | 0.142417 | 0.249326 | 0.635719 | 1307 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001089 | 0.000120 | -0.001710 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.015698 | -0.005329 | -0.024970 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000653 | -0.000091 | -0.001026 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.121777 | -0.143911 | 0.172415 | 4756 | 8234 |

### 宁波市_余姚市_小曹娥镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `5954`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.842282 | 0.732989 | 0.000000 | 0.000000 | 0.449292 | 0 |
| markov_transition_projection | forecast_demand | 0.795650 | 0.666084 | 0.046101 | 0.088140 | 0.389283 | 1824 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.802517 | 0.677305 | 0.067066 | 0.125702 | 0.395867 | 1824 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.802549 | 0.677357 | 0.067235 | 0.125998 | 0.395874 | 1824 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.802549 | 0.677357 | 0.067235 | 0.125998 | 0.395874 | 1824 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.802549 | 0.677357 | 0.067066 | 0.125702 | 0.395900 | 1824 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.804305 | 0.680228 | 0.073504 | 0.136942 | 0.398047 | 1824 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.799451 | 0.672295 | 0.063709 | 0.119787 | 0.391769 | 1824 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.802549 | 0.677357 | 0.067066 | 0.125702 | 0.395900 | 1824 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.688173 | 0.521927 | 0.309179 | 0.472325 | 0.340295 | 9624 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.848254 | 0.735814 | 0.220080 | 0.360763 | 0.426239 | 1454 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.006438 | 0.001788 | 0.011240 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.003357 | -0.003066 | -0.005915 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000032 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.242113 | -0.114344 | 0.346623 | 5904 | 7800 |

### 宁波市_余姚市_小曹娥镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `3052`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.891437 | 0.812254 | 0.000000 | 0.000000 | 0.496482 | 0 |
| markov_transition_projection | forecast_demand | 0.886582 | 0.799780 | 0.186378 | 0.314197 | 0.438458 | 1095 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.887668 | 0.801697 | 0.182943 | 0.309301 | 0.438055 | 1095 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.887668 | 0.801697 | 0.182943 | 0.309301 | 0.438055 | 1095 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.887668 | 0.801697 | 0.182943 | 0.309301 | 0.438055 | 1095 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.887604 | 0.801585 | 0.182632 | 0.308856 | 0.437716 | 1095 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.887924 | 0.802148 | 0.182943 | 0.309301 | 0.436942 | 1095 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.887860 | 0.802036 | 0.188889 | 0.317757 | 0.445723 | 1095 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.887732 | 0.801810 | 0.182943 | 0.309301 | 0.438102 | 1095 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.706410 | 0.527117 | 0.260768 | 0.413665 | 0.311611 | 9539 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.881248 | 0.795428 | 0.161982 | 0.278803 | 0.488288 | 1314 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | 0.000256 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.005946 | 0.000192 | 0.008456 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000064 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.077825 | -0.181258 | 0.104364 | 7690 | 8444 |

### 宁波市_余姚市_小曹娥镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `3692`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.877256 | 0.794944 | 0.000000 | 0.000000 | 0.462982 | 0 |
| markov_transition_projection | forecast_demand | 0.853876 | 0.756920 | 0.096224 | 0.175555 | 0.404438 | 1295 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.863011 | 0.772115 | 0.131967 | 0.233165 | 0.416267 | 1295 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.863011 | 0.772115 | 0.131967 | 0.233165 | 0.416267 | 1295 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.863011 | 0.772115 | 0.131967 | 0.233165 | 0.416267 | 1295 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.863011 | 0.772115 | 0.131967 | 0.233165 | 0.416267 | 1295 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.862659 | 0.771531 | 0.132466 | 0.233943 | 0.418515 | 1295 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.860200 | 0.767440 | 0.130224 | 0.230440 | 0.418929 | 1295 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.862915 | 0.771956 | 0.131967 | 0.233165 | 0.416260 | 1295 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.739532 | 0.582130 | 0.278429 | 0.435580 | 0.342611 | 7714 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.856463 | 0.766655 | 0.115335 | 0.206817 | 0.463373 | 1379 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000499 | -0.000352 | 0.000778 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.001743 | -0.002811 | -0.002725 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | -0.000096 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.146462 | -0.123479 | 0.202415 | 5190 | 6419 |

### 宁波市_余姚市_小曹娥镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `2892`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.888115 | 0.820866 | 0.000000 | 0.000000 | 0.590976 | 0 |
| markov_transition_projection | forecast_demand | 0.853780 | 0.771710 | 0.056710 | 0.107333 | 0.516201 | 1379 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.868249 | 0.794300 | 0.137465 | 0.241704 | 0.530626 | 1379 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.868153 | 0.794150 | 0.136671 | 0.240475 | 0.530582 | 1379 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.868153 | 0.794150 | 0.136671 | 0.240475 | 0.530582 | 1379 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.868249 | 0.794300 | 0.137465 | 0.241704 | 0.530626 | 1379 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.871890 | 0.799984 | 0.149517 | 0.260139 | 0.539724 | 1379 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.864703 | 0.788764 | 0.112580 | 0.202376 | 0.527150 | 1379 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.868025 | 0.793951 | 0.136935 | 0.240885 | 0.530180 | 1379 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.678814 | 0.520088 | 0.257370 | 0.409379 | 0.348604 | 10870 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.883037 | 0.815220 | 0.153459 | 0.266085 | 0.584760 | 1082 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.012052 | 0.003641 | 0.018435 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.024885 | -0.003546 | -0.039328 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000530 | -0.000224 | -0.000819 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.119905 | -0.189435 | 0.167675 | 5354 | 9491 |

### 宁波市_余姚市_小曹娥镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1720`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.910952 | 0.860201 | 0.000000 | 0.000000 | 0.616622 | 0 |
| markov_transition_projection | forecast_demand | 0.884602 | 0.821090 | 0.063479 | 0.119380 | 0.547989 | 1082 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.901753 | 0.847681 | 0.165312 | 0.283721 | 0.596388 | 1082 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.901753 | 0.847681 | 0.165312 | 0.283721 | 0.596388 | 1082 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.901753 | 0.847681 | 0.165312 | 0.283721 | 0.596388 | 1082 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.901753 | 0.847681 | 0.165312 | 0.283721 | 0.596414 | 1082 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.901338 | 0.847038 | 0.161813 | 0.278553 | 0.597915 | 1082 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.896132 | 0.838966 | 0.132572 | 0.234109 | 0.581310 | 1082 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.901753 | 0.847681 | 0.165312 | 0.283721 | 0.596388 | 1082 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.720751 | 0.581957 | 0.235522 | 0.381252 | 0.400196 | 9309 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.904724 | 0.851289 | 0.074790 | 0.139172 | 0.605577 | 546 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.003499 | -0.000415 | -0.005168 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.032740 | -0.005621 | -0.049612 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.070210 | -0.181002 | 0.097531 | 3878 | 8227 |

### 广州市_增城区_正果镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `444`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.971461 | 0.872659 | 0.000000 | 0.000000 | 0.531858 | 0 |
| markov_transition_projection | forecast_demand | 0.969936 | 0.864359 | 0.046512 | 0.088889 | 0.508645 | 122 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.970490 | 0.866862 | 0.065389 | 0.122751 | 0.517688 | 122 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.970490 | 0.866862 | 0.066591 | 0.124868 | 0.515496 | 122 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.970490 | 0.866862 | 0.066591 | 0.124868 | 0.515496 | 122 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.970352 | 0.866236 | 0.066591 | 0.124868 | 0.517813 | 122 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.970872 | 0.868583 | 0.073864 | 0.137566 | 0.523140 | 122 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.970144 | 0.865298 | 0.060606 | 0.114286 | 0.513698 | 122 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.970490 | 0.866862 | 0.067797 | 0.126984 | 0.520026 | 122 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.658263 | 0.216592 | 0.062469 | 0.117593 | 0.209171 | 10045 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.968340 | 0.854317 | 0.093973 | 0.171802 | 0.501316 | 248 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.008475 | 0.000382 | 0.014815 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.004783 | -0.000346 | -0.008465 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.002408 | 0.000000 | 0.004233 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.002920 | -0.312227 | -0.005158 | 14270 | 9923 |

### 广州市_增城区_正果镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `916`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.972883 | 0.878499 | 0.000000 | 0.000000 | 0.556895 | 0 |
| markov_transition_projection | forecast_demand | 0.965948 | 0.842778 | 0.029087 | 0.056530 | 0.497440 | 244 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.967439 | 0.849662 | 0.052308 | 0.099415 | 0.497173 | 244 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.967439 | 0.849662 | 0.052308 | 0.099415 | 0.497173 | 244 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.967439 | 0.849662 | 0.052308 | 0.099415 | 0.497173 | 244 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.967439 | 0.849662 | 0.052308 | 0.099415 | 0.497173 | 244 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.967335 | 0.849182 | 0.053388 | 0.101365 | 0.497298 | 244 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.966849 | 0.846941 | 0.045872 | 0.087719 | 0.496333 | 244 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.967439 | 0.849662 | 0.052308 | 0.099415 | 0.497173 | 244 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.557875 | 0.157640 | 0.047768 | 0.091181 | 0.218008 | 12949 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.966156 | 0.852175 | 0.050246 | 0.095685 | 0.541490 | 284 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.001080 | -0.000104 | 0.001950 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.006436 | -0.000590 | -0.011696 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.004540 | -0.409564 | -0.008234 | 20636 | 12705 |

### 广州市_增城区_正果镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `234`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.973022 | 0.885476 | 0.000000 | 0.000000 | 0.626465 | 0 |
| markov_transition_projection | forecast_demand | 0.963902 | 0.850364 | 0.016268 | 0.032015 | 0.580873 | 284 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.967196 | 0.864020 | 0.063063 | 0.118644 | 0.587863 | 284 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.967196 | 0.864020 | 0.063063 | 0.118644 | 0.587863 | 284 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.967196 | 0.864020 | 0.063063 | 0.118644 | 0.587863 | 284 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.967127 | 0.863732 | 0.062000 | 0.116761 | 0.587679 | 284 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.967023 | 0.863301 | 0.058824 | 0.111111 | 0.587610 | 284 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.963867 | 0.850221 | 0.014327 | 0.028249 | 0.582238 | 284 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.967127 | 0.863732 | 0.062000 | 0.116761 | 0.587679 | 284 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.687184 | 0.242029 | 0.067863 | 0.127101 | 0.208683 | 9277 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.967508 | 0.865785 | 0.076845 | 0.142723 | 0.583834 | 287 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.004239 | -0.000173 | -0.007533 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.048736 | -0.003329 | -0.090395 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.001063 | -0.000069 | -0.001883 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.004800 | -0.280012 | 0.008457 | 11664 | 8993 |

### 广州市_增城区_正果镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `684`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.968410 | 0.870401 | 0.000000 | 0.000000 | 0.501799 | 0 |
| markov_transition_projection | forecast_demand | 0.959463 | 0.838023 | 0.023932 | 0.046745 | 0.464664 | 287 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.961787 | 0.847306 | 0.058304 | 0.110184 | 0.472931 | 287 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.961752 | 0.847168 | 0.057370 | 0.108514 | 0.469663 | 287 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.961752 | 0.847168 | 0.057370 | 0.108514 | 0.469663 | 287 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.961891 | 0.847722 | 0.060177 | 0.113523 | 0.473002 | 287 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.961856 | 0.847583 | 0.060177 | 0.113523 | 0.473049 | 287 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.960781 | 0.843288 | 0.045375 | 0.086811 | 0.465342 | 287 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.961787 | 0.847306 | 0.058304 | 0.110184 | 0.472931 | 287 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.650288 | 0.243450 | 0.069970 | 0.130788 | 0.220130 | 10405 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.966121 | 0.861930 | 0.108293 | 0.195423 | 0.485527 | 225 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.001873 | 0.000069 | 0.003339 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.012929 | -0.001006 | -0.023373 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.011666 | -0.311499 | 0.020604 | 14408 | 10118 |

### 广州市_增城区_正果镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `696`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.973403 | 0.889748 | 0.000000 | 0.000000 | 0.677181 | 0 |
| markov_transition_projection | forecast_demand | 0.967543 | 0.866598 | 0.052072 | 0.098990 | 0.412759 | 223 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.968965 | 0.872442 | 0.076087 | 0.141414 | 0.429486 | 223 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.968895 | 0.872157 | 0.073753 | 0.137374 | 0.422318 | 223 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.968930 | 0.872299 | 0.074919 | 0.139394 | 0.425902 | 223 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.968965 | 0.872442 | 0.076087 | 0.141414 | 0.429486 | 223 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.968826 | 0.871872 | 0.074919 | 0.139394 | 0.429301 | 223 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.967855 | 0.867881 | 0.057692 | 0.109091 | 0.420418 | 223 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.968965 | 0.872442 | 0.076087 | 0.141414 | 0.429486 | 223 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.552327 | 0.170913 | 0.043167 | 0.082761 | 0.207682 | 13056 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.969936 | 0.873174 | 0.066445 | 0.124611 | 0.670096 | 196 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001168 | -0.000139 | -0.002020 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.018395 | -0.001110 | -0.032323 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.032920 | -0.416638 | -0.058653 | 19932 | 12833 |

### 成都市_桂阳县_舂陵江镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1720`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.899816 | 0.793896 | 0.000000 | 0.000000 | 0.593121 | 0 |
| markov_transition_projection | forecast_demand | 0.883083 | 0.755370 | 0.075370 | 0.140176 | 0.546751 | 940 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.890745 | 0.771401 | 0.113492 | 0.203849 | 0.572641 | 940 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.890745 | 0.771401 | 0.112903 | 0.202899 | 0.572601 | 940 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.890745 | 0.771401 | 0.112903 | 0.202899 | 0.572601 | 940 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.890683 | 0.771273 | 0.113492 | 0.203849 | 0.572597 | 940 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.890867 | 0.771658 | 0.112315 | 0.201948 | 0.570295 | 940 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.886853 | 0.763258 | 0.096665 | 0.176289 | 0.534636 | 940 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.890745 | 0.771401 | 0.112903 | 0.202899 | 0.572636 | 940 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.594729 | 0.306325 | 0.179966 | 0.305036 | 0.246336 | 14047 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.891695 | 0.780684 | 0.064173 | 0.120606 | 0.590550 | 628 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001177 | 0.000122 | -0.001901 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.016827 | -0.003892 | -0.027560 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000589 | 0.000000 | -0.000950 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.066474 | -0.296016 | 0.101187 | 10914 | 13107 |

### 成都市_桂阳县_舂陵江镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4426`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.896690 | 0.787132 | 0.000000 | 0.000000 | 0.580298 | 0 |
| markov_transition_projection | forecast_demand | 0.881091 | 0.759261 | 0.024334 | 0.047512 | 0.530468 | 628 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.882715 | 0.762550 | 0.037085 | 0.071518 | 0.540964 | 628 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.882715 | 0.762550 | 0.037085 | 0.071518 | 0.540964 | 628 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.882715 | 0.762550 | 0.037085 | 0.071518 | 0.540964 | 628 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.882715 | 0.762550 | 0.037085 | 0.071518 | 0.540964 | 628 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.882930 | 0.762984 | 0.037354 | 0.072018 | 0.541257 | 628 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.880785 | 0.758641 | 0.026174 | 0.051013 | 0.533930 | 628 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.882685 | 0.762488 | 0.037354 | 0.072018 | 0.540884 | 628 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.624548 | 0.344146 | 0.181998 | 0.307949 | 0.257716 | 12794 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.898039 | 0.784812 | 0.247420 | 0.396691 | 0.561130 | 1585 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000269 | 0.000215 | 0.000500 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.010911 | -0.001930 | -0.020505 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000269 | -0.000030 | 0.000500 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.144913 | -0.258167 | 0.236431 | 7896 | 12166 |

### 成都市_桂阳县_舂陵江镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `5920`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.898253 | 0.786576 | 0.000000 | 0.000000 | 0.574250 | 0 |
| markov_transition_projection | forecast_demand | 0.864848 | 0.711105 | 0.081588 | 0.150866 | 0.490231 | 1585 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.866932 | 0.715560 | 0.082304 | 0.152090 | 0.491834 | 1585 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.866932 | 0.715560 | 0.082304 | 0.152090 | 0.491834 | 1585 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.866932 | 0.715560 | 0.082304 | 0.152090 | 0.491834 | 1585 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.866932 | 0.715560 | 0.082304 | 0.152090 | 0.491834 | 1585 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.866503 | 0.714643 | 0.083738 | 0.154536 | 0.492749 | 1585 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.865829 | 0.713201 | 0.081349 | 0.150459 | 0.490544 | 1585 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.866932 | 0.715560 | 0.082304 | 0.152090 | 0.491834 | 1585 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.519430 | 0.250145 | 0.146714 | 0.255885 | 0.235434 | 15923 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.888753 | 0.766834 | 0.172448 | 0.294168 | 0.566270 | 1378 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.001434 | -0.000429 | 0.002446 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.000955 | -0.001103 | -0.001631 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.064410 | -0.347502 | 0.103795 | 18180 | 14338 |

### 成都市_桂阳县_舂陵江镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `5600`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.890438 | 0.782139 | 0.000000 | 0.000000 | 0.566068 | 0 |
| markov_transition_projection | forecast_demand | 0.855624 | 0.714063 | 0.036192 | 0.069857 | 0.512668 | 1378 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.860558 | 0.723835 | 0.055627 | 0.105391 | 0.530229 | 1378 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.860650 | 0.724017 | 0.055852 | 0.105794 | 0.533614 | 1378 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.860650 | 0.724017 | 0.055852 | 0.105794 | 0.533614 | 1378 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.860619 | 0.723956 | 0.055852 | 0.105794 | 0.530300 | 1378 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.860190 | 0.723106 | 0.052710 | 0.100141 | 0.521628 | 1378 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.857217 | 0.717219 | 0.045598 | 0.087220 | 0.511583 | 1378 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.860374 | 0.723470 | 0.055402 | 0.104987 | 0.524353 | 1378 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.587557 | 0.330823 | 0.192163 | 0.322377 | 0.260691 | 14193 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.871315 | 0.754894 | 0.115933 | 0.207777 | 0.555634 | 1517 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002917 | -0.000368 | -0.005250 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.010029 | -0.003341 | -0.018171 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000225 | -0.000184 | -0.000404 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.136536 | -0.273001 | 0.216986 | 11802 | 12815 |

### 成都市_桂阳县_舂陵江镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4934`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.884156 | 0.772101 | 0.000000 | 0.000000 | 0.547185 | 0 |
| markov_transition_projection | forecast_demand | 0.842384 | 0.704370 | 0.021272 | 0.041659 | 0.498093 | 1501 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.848943 | 0.716672 | 0.043057 | 0.082560 | 0.517966 | 1501 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.848820 | 0.716442 | 0.042440 | 0.081424 | 0.505286 | 1501 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.848851 | 0.716499 | 0.042440 | 0.081424 | 0.505388 | 1501 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.848943 | 0.716672 | 0.043057 | 0.082560 | 0.517966 | 1501 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.848177 | 0.715235 | 0.040181 | 0.077258 | 0.517805 | 1501 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.845572 | 0.710349 | 0.033868 | 0.065518 | 0.499124 | 1501 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.848943 | 0.716672 | 0.043057 | 0.082560 | 0.517966 | 1501 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.595280 | 0.334402 | 0.181905 | 0.307817 | 0.238521 | 13490 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.876402 | 0.747936 | 0.108631 | 0.195973 | 0.545373 | 1037 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002876 | -0.000766 | -0.005302 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.009189 | -0.003371 | -0.017042 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.138848 | -0.253663 | 0.225257 | 7562 | 11989 |

### 杭州市_淳安县_界首乡_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `758`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.981105 | 0.963774 | 0.000000 | 0.000000 | 0.488520 | 0 |
| markov_transition_projection | forecast_demand | 0.978941 | 0.959531 | 0.040595 | 0.078023 | 0.429848 | 114 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.979259 | 0.960141 | 0.046259 | 0.088427 | 0.432062 | 114 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.979259 | 0.960141 | 0.043419 | 0.083225 | 0.431054 | 114 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.979259 | 0.960141 | 0.046259 | 0.088427 | 0.432062 | 114 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.979287 | 0.960197 | 0.046259 | 0.088427 | 0.432067 | 114 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.979172 | 0.959975 | 0.044837 | 0.085826 | 0.431539 | 114 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.979172 | 0.959975 | 0.044837 | 0.085826 | 0.431038 | 114 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.979259 | 0.960141 | 0.046259 | 0.088427 | 0.432062 | 114 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.821636 | 0.676489 | 0.081739 | 0.151125 | 0.341776 | 6412 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.977470 | 0.956822 | 0.120141 | 0.214511 | 0.444024 | 296 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001422 | -0.000087 | -0.002601 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.001422 | -0.000087 | -0.002601 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.035480 | -0.157623 | 0.062698 | 4186 | 6298 |

### 杭州市_淳安县_界首乡_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `736`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.979778 | 0.961371 | 0.000000 | 0.000000 | 0.472037 | 0 |
| markov_transition_projection | forecast_demand | 0.972191 | 0.946900 | 0.031024 | 0.060181 | 0.413896 | 296 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.973576 | 0.949544 | 0.053911 | 0.102307 | 0.422705 | 296 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.973576 | 0.949544 | 0.052798 | 0.100301 | 0.422826 | 296 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.973576 | 0.949544 | 0.052798 | 0.100301 | 0.422826 | 296 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.973576 | 0.949544 | 0.052798 | 0.100301 | 0.422826 | 296 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.973547 | 0.949489 | 0.053911 | 0.102307 | 0.422160 | 296 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.973229 | 0.948883 | 0.047269 | 0.090271 | 0.419951 | 296 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.973576 | 0.949544 | 0.053911 | 0.102307 | 0.422705 | 296 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.798875 | 0.646652 | 0.073164 | 0.136352 | 0.274835 | 7161 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.977614 | 0.957375 | 0.051508 | 0.097969 | 0.452819 | 136 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | -0.000029 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.006642 | -0.000347 | -0.012036 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.019253 | -0.174701 | 0.034045 | 6752 | 6865 |

### 杭州市_淳安县_界首乡_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `340`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.979172 | 0.960424 | 0.000000 | 0.000000 | 0.466293 | 0 |
| markov_transition_projection | forecast_demand | 0.975393 | 0.953394 | 0.004684 | 0.009324 | 0.449132 | 136 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.976778 | 0.956017 | 0.040000 | 0.076923 | 0.454917 | 136 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.976778 | 0.956017 | 0.040000 | 0.076923 | 0.454917 | 136 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.976778 | 0.956017 | 0.040000 | 0.076923 | 0.454917 | 136 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.976807 | 0.956071 | 0.041262 | 0.079254 | 0.455246 | 136 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.976835 | 0.956126 | 0.042527 | 0.081585 | 0.456339 | 136 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.975739 | 0.954050 | 0.014184 | 0.027972 | 0.449534 | 136 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.976778 | 0.956017 | 0.040000 | 0.076923 | 0.454917 | 136 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.774268 | 0.607452 | 0.063457 | 0.119341 | 0.275088 | 7959 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.976691 | 0.955801 | 0.016089 | 0.031669 | 0.455623 | 99 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.002527 | 0.000057 | 0.004662 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.025816 | -0.001039 | -0.048951 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.023457 | -0.202510 | 0.042418 | 6190 | 7823 |

### 杭州市_淳安县_界首乡_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `648`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.966133 | 0.936247 | 0.000000 | 0.000000 | 0.494032 | 0 |
| markov_transition_projection | forecast_demand | 0.963364 | 0.931174 | 0.002362 | 0.004713 | 0.474889 | 99 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.963623 | 0.931662 | 0.007120 | 0.014140 | 0.474648 | 99 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.963566 | 0.931554 | 0.006324 | 0.012569 | 0.474407 | 99 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.963566 | 0.931554 | 0.006324 | 0.012569 | 0.474407 | 99 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.963652 | 0.931716 | 0.007918 | 0.015711 | 0.475188 | 99 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.963681 | 0.931771 | 0.007120 | 0.014140 | 0.475192 | 99 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.963883 | 0.932150 | 0.015152 | 0.029851 | 0.474490 | 99 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.963623 | 0.931662 | 0.007120 | 0.014140 | 0.474648 | 99 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.718996 | 0.535020 | 0.093409 | 0.170858 | 0.270340 | 10239 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.961142 | 0.927366 | 0.056859 | 0.107599 | 0.460426 | 313 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000000 | 0.000058 | 0.000000 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.008032 | 0.000260 | 0.015711 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.086289 | -0.244627 | 0.156718 | 9748 | 10140 |

### 杭州市_淳安县_界首乡_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1096`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.966450 | 0.937002 | 0.000000 | 0.000000 | 0.507201 | 0 |
| markov_transition_projection | forecast_demand | 0.957594 | 0.920956 | 0.001360 | 0.002716 | 0.459528 | 310 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.959498 | 0.924504 | 0.025766 | 0.050238 | 0.463897 | 310 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.959498 | 0.924504 | 0.025766 | 0.050238 | 0.463897 | 310 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.959498 | 0.924504 | 0.025766 | 0.050238 | 0.463897 | 310 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.959498 | 0.924504 | 0.025766 | 0.050238 | 0.463897 | 310 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.959469 | 0.924451 | 0.025052 | 0.048880 | 0.463665 | 310 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.958344 | 0.922354 | 0.013067 | 0.025798 | 0.459699 | 310 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.959498 | 0.924504 | 0.025766 | 0.050238 | 0.463897 | 310 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.781018 | 0.617031 | 0.108682 | 0.196057 | 0.267730 | 7967 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.963046 | 0.930285 | 0.074157 | 0.138075 | 0.445093 | 271 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000714 | -0.000029 | -0.001358 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.012699 | -0.001154 | -0.024440 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.082916 | -0.178480 | 0.145819 | 4902 | 7657 |

### 武汉市_江夏区_江夏区经济开发区梁子湖风景区办事_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1658`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.925276 | 0.789616 | 0.000000 | 0.000000 | 0.530188 | 0 |
| markov_transition_projection | forecast_demand | 0.889005 | 0.705221 | 0.058981 | 0.111392 | 0.417824 | 1517 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.906112 | 0.750653 | 0.165536 | 0.284051 | 0.447237 | 1517 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.906112 | 0.750653 | 0.165536 | 0.284051 | 0.447237 | 1517 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.906112 | 0.750653 | 0.165536 | 0.284051 | 0.447237 | 1517 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.906081 | 0.750571 | 0.165192 | 0.283544 | 0.447232 | 1517 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.905713 | 0.749592 | 0.164848 | 0.283038 | 0.445829 | 1517 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.895424 | 0.722268 | 0.108928 | 0.196456 | 0.427885 | 1517 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.906050 | 0.750490 | 0.165192 | 0.283544 | 0.447100 | 1517 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.774109 | 0.473727 | 0.229534 | 0.373368 | 0.290676 | 7675 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.910688 | 0.765955 | 0.156991 | 0.271378 | 0.510044 | 1274 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000688 | -0.000399 | -0.001013 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.056608 | -0.010688 | -0.087595 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000344 | -0.000062 | -0.000507 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.063998 | -0.132003 | 0.089317 | 7026 | 6158 |

### 武汉市_江夏区_江夏区经济开发区梁子湖风景区办事_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `7072`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.904883 | 0.712078 | 0.000000 | 0.000000 | 0.427569 | 0 |
| markov_transition_projection | forecast_demand | 0.867260 | 0.631721 | 0.009935 | 0.019675 | 0.379232 | 1274 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.868428 | 0.634959 | 0.018406 | 0.036147 | 0.380187 | 1274 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.868428 | 0.634959 | 0.018406 | 0.036147 | 0.380187 | 1274 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.868428 | 0.634959 | 0.018406 | 0.036147 | 0.380187 | 1274 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.868366 | 0.634788 | 0.018406 | 0.036147 | 0.379867 | 1274 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.868182 | 0.634277 | 0.017221 | 0.033860 | 0.379670 | 1274 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.868305 | 0.634618 | 0.019356 | 0.037978 | 0.379215 | 1274 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.868397 | 0.634873 | 0.018406 | 0.036147 | 0.380027 | 1274 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.740786 | 0.379655 | 0.230869 | 0.375132 | 0.235294 | 8307 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.953808 | 0.830378 | 0.621221 | 0.766362 | 0.389079 | 2266 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001185 | -0.000246 | -0.002287 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.000950 | -0.000123 | 0.001831 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | -0.000031 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.212463 | -0.127642 | 0.338985 | 5682 | 7033 |

### 武汉市_江夏区_江夏区经济开发区梁子湖风景区办事_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1910`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.970577 | 0.894607 | 0.000000 | 0.000000 | 0.561500 | 0 |
| markov_transition_projection | forecast_demand | 0.955713 | 0.832004 | 0.100136 | 0.182043 | 0.373693 | 657 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.956419 | 0.834683 | 0.108442 | 0.195666 | 0.378342 | 657 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.956419 | 0.834683 | 0.108442 | 0.195666 | 0.378342 | 657 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.956419 | 0.834683 | 0.108442 | 0.195666 | 0.378342 | 657 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.956419 | 0.834683 | 0.108442 | 0.195666 | 0.378342 | 657 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.955958 | 0.832936 | 0.101637 | 0.184520 | 0.377415 | 657 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.956357 | 0.834450 | 0.103896 | 0.188235 | 0.375944 | 657 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.956419 | 0.834683 | 0.108442 | 0.195666 | 0.378342 | 657 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.893612 | 0.630574 | 0.142742 | 0.249824 | 0.248362 | 3293 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.963821 | 0.873460 | 0.063018 | 0.118565 | 0.536395 | 324 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.006805 | -0.000461 | -0.011146 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.004546 | -0.000062 | -0.007431 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.034300 | -0.062807 | 0.054158 | 2766 | 2636 |

### 武汉市_江夏区_江夏区经济开发区梁子湖风景区办事_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `708`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.954300 | 0.845358 | 0.000000 | 0.000000 | 0.466713 | 0 |
| markov_transition_projection | forecast_demand | 0.945025 | 0.818065 | 0.010597 | 0.020971 | 0.430864 | 324 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.948434 | 0.829347 | 0.051044 | 0.097130 | 0.442179 | 324 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.948434 | 0.829347 | 0.051044 | 0.097130 | 0.442179 | 324 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.948434 | 0.829347 | 0.051044 | 0.097130 | 0.442179 | 324 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.948464 | 0.829449 | 0.051654 | 0.098234 | 0.443471 | 324 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.948280 | 0.828839 | 0.052265 | 0.099338 | 0.442417 | 324 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.947328 | 0.825688 | 0.042578 | 0.081678 | 0.435417 | 324 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.948434 | 0.829347 | 0.051044 | 0.097130 | 0.442179 | 324 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.824693 | 0.511480 | 0.188127 | 0.316678 | 0.269478 | 5857 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.943735 | 0.815498 | 0.047670 | 0.091002 | 0.437564 | 468 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.001221 | -0.000154 | 0.002208 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.008466 | -0.001106 | -0.015452 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.137083 | -0.123741 | 0.219548 | 6276 | 5533 |

### 武汉市_江夏区_江夏区经济开发区梁子湖风景区办事_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1480`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.954699 | 0.848411 | 0.000000 | 0.000000 | 0.477507 | 0 |
| markov_transition_projection | forecast_demand | 0.940756 | 0.807871 | 0.006736 | 0.013381 | 0.439132 | 468 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.943151 | 0.815639 | 0.034611 | 0.066907 | 0.446468 | 468 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.943151 | 0.815639 | 0.034611 | 0.066907 | 0.446468 | 468 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.943151 | 0.815639 | 0.034611 | 0.066907 | 0.446468 | 468 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.943151 | 0.815639 | 0.034611 | 0.066907 | 0.446468 | 468 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.942660 | 0.814046 | 0.031316 | 0.060731 | 0.444335 | 468 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.942537 | 0.813647 | 0.031316 | 0.060731 | 0.442623 | 468 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.943151 | 0.815639 | 0.034611 | 0.066907 | 0.446468 | 468 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.792660 | 0.445984 | 0.160791 | 0.277037 | 0.244231 | 6921 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.953194 | 0.840018 | 0.176364 | 0.299845 | 0.494984 | 466 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.003295 | -0.000491 | -0.006176 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.003295 | -0.000614 | -0.006176 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.126180 | -0.150491 | 0.210130 | 7260 | 6453 |

### 深圳市_龙岗区_南澳街道_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `360`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.988741 | 0.977829 | 0.000000 | 0.000000 | 0.582020 | 0 |
| markov_transition_projection | forecast_demand | 0.985517 | 0.971571 | 0.027304 | 0.053156 | 0.481847 | 74 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.985814 | 0.972155 | 0.041522 | 0.079734 | 0.479110 | 74 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.985765 | 0.972058 | 0.037931 | 0.073090 | 0.462016 | 74 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.985814 | 0.972155 | 0.041522 | 0.079734 | 0.479110 | 74 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.985864 | 0.972252 | 0.041522 | 0.079734 | 0.490154 | 74 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.985765 | 0.972058 | 0.037931 | 0.073090 | 0.479100 | 74 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.985517 | 0.971571 | 0.030822 | 0.059801 | 0.478587 | 74 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.985814 | 0.972155 | 0.041522 | 0.079734 | 0.479110 | 74 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.870939 | 0.769237 | 0.064950 | 0.121977 | 0.312965 | 2626 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.987401 | 0.975054 | 0.162069 | 0.278932 | 0.544857 | 110 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.003591 | -0.000049 | -0.006644 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.010700 | -0.000297 | -0.019933 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.023428 | -0.114875 | 0.042243 | 3498 | 2552 |

### 深圳市_龙岗区_南澳街道_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `348`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.990774 | 0.981770 | 0.000000 | 0.000000 | 0.612010 | 0 |
| markov_transition_projection | forecast_demand | 0.985715 | 0.971615 | 0.020690 | 0.040541 | 0.532377 | 110 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.986409 | 0.972995 | 0.053381 | 0.101351 | 0.566196 | 110 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.986509 | 0.973192 | 0.053381 | 0.101351 | 0.567706 | 110 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.986360 | 0.972897 | 0.049645 | 0.094595 | 0.566005 | 110 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.986409 | 0.972995 | 0.053381 | 0.101351 | 0.566196 | 110 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.986608 | 0.973389 | 0.060932 | 0.114865 | 0.568088 | 110 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.985913 | 0.972010 | 0.027778 | 0.054054 | 0.552677 | 110 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.986409 | 0.972995 | 0.053381 | 0.101351 | 0.566196 | 110 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.942116 | 0.886236 | 0.078496 | 0.145565 | 0.337812 | 1133 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.988195 | 0.976720 | 0.057851 | 0.109375 | 0.580256 | 70 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.007551 | 0.000199 | 0.013514 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.025603 | -0.000496 | -0.047297 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.025115 | -0.044293 | 0.044214 | 442 | 1023 |

### 深圳市_龙岗区_南澳街道_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_cross_region_smoothed_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `72`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.989782 | 0.979888 | 0.000000 | 0.000000 | 0.643519 | 0 |
| markov_transition_projection | forecast_demand | 0.986509 | 0.973501 | 0.014706 | 0.028986 | 0.558660 | 70 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.988939 | 0.978275 | 0.112903 | 0.202899 | 0.594519 | 70 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.988840 | 0.978080 | 0.112903 | 0.202899 | 0.591462 | 70 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.988840 | 0.978080 | 0.112903 | 0.202899 | 0.591462 | 70 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.988989 | 0.978372 | 0.117409 | 0.210145 | 0.609334 | 70 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.988641 | 0.977690 | 0.099602 | 0.181159 | 0.591469 | 70 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.986608 | 0.973696 | 0.014706 | 0.028986 | 0.563454 | 70 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.988939 | 0.978275 | 0.112903 | 0.202899 | 0.594519 | 70 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.904469 | 0.820301 | 0.078460 | 0.145504 | 0.323625 | 2007 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.989038 | 0.978463 | 0.114754 | 0.205882 | 0.610613 | 66 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.013301 | -0.000298 | -0.021740 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.098197 | -0.002331 | -0.173913 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.034443 | -0.084470 | -0.057395 | 1726 | 1937 |

### 深圳市_龙岗区_南澳街道_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `74`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.986657 | 0.973816 | 0.000000 | 0.000000 | 0.602235 | 0 |
| markov_transition_projection | forecast_demand | 0.983384 | 0.967450 | 0.000000 | 0.000000 | 0.561258 | 66 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.985517 | 0.971628 | 0.073718 | 0.137313 | 0.573382 | 66 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.985517 | 0.971628 | 0.073718 | 0.137313 | 0.573382 | 66 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.985517 | 0.971628 | 0.073718 | 0.137313 | 0.573382 | 66 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.985517 | 0.971628 | 0.073718 | 0.137313 | 0.573382 | 66 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.986211 | 0.972989 | 0.101974 | 0.185075 | 0.598075 | 66 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.983979 | 0.968616 | 0.021341 | 0.041791 | 0.564269 | 66 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.985517 | 0.971628 | 0.073718 | 0.137313 | 0.573382 | 66 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.854174 | 0.739086 | 0.060359 | 0.113846 | 0.307637 | 2981 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.985765 | 0.972095 | 0.114007 | 0.204678 | 0.581231 | 73 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.028256 | 0.000694 | 0.047762 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.052377 | -0.001538 | -0.095522 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.013359 | -0.131343 | -0.023467 | 3776 | 2915 |

### 深圳市_龙岗区_南澳街道_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `164`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.987352 | 0.975260 | 0.000000 | 0.000000 | 0.692081 | 0 |
| markov_transition_projection | forecast_demand | 0.984078 | 0.968899 | 0.012461 | 0.024615 | 0.596486 | 70 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.985913 | 0.972484 | 0.083333 | 0.153846 | 0.599212 | 70 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.985715 | 0.972096 | 0.076159 | 0.141538 | 0.594081 | 70 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.985864 | 0.972387 | 0.083333 | 0.153846 | 0.594677 | 70 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.985814 | 0.972290 | 0.079734 | 0.147692 | 0.599031 | 70 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.985814 | 0.972290 | 0.079734 | 0.147692 | 0.598476 | 70 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.984326 | 0.969383 | 0.018809 | 0.036923 | 0.591425 | 70 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.985913 | 0.972484 | 0.083333 | 0.153846 | 0.599212 | 70 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.871485 | 0.761944 | 0.071243 | 0.133010 | 0.283078 | 2632 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.984574 | 0.969890 | 0.049844 | 0.094955 | 0.655369 | 82 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.003599 | -0.000099 | -0.006154 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.064524 | -0.001587 | -0.116923 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.012090 | -0.114428 | -0.020836 | 1944 | 2562 |

### 福州市_永泰县_嵩口镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `markov_transition_projection`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1416`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.963191 | 0.751703 | 0.000000 | 0.000000 | 0.498460 | 0 |
| markov_transition_projection | forecast_demand | 0.959801 | 0.714794 | 0.147315 | 0.256799 | 0.435290 | 419 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.958566 | 0.706029 | 0.132521 | 0.234029 | 0.434980 | 419 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.958566 | 0.706029 | 0.132521 | 0.234029 | 0.434980 | 419 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.958566 | 0.706029 | 0.132521 | 0.234029 | 0.434980 | 419 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.958566 | 0.706029 | 0.131711 | 0.232764 | 0.434761 | 419 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.959199 | 0.710524 | 0.138229 | 0.242884 | 0.434431 | 419 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.958281 | 0.704006 | 0.129286 | 0.228969 | 0.430970 | 419 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.958534 | 0.705804 | 0.131711 | 0.232764 | 0.433416 | 419 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.725735 | 0.196272 | 0.097324 | 0.177384 | 0.227836 | 8760 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.957457 | 0.722261 | 0.070656 | 0.131987 | 0.475867 | 323 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.005708 | 0.000633 | 0.008855 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.003235 | -0.000285 | -0.005060 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000810 | -0.000032 | -0.001265 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.035197 | -0.232831 | -0.056645 | 13902 | 8341 |

### 福州市_永泰县_嵩口镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `994`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.962874 | 0.759166 | 0.000000 | 0.000000 | 0.481461 | 0 |
| markov_transition_projection | forecast_demand | 0.954859 | 0.717139 | 0.036806 | 0.070998 | 0.394219 | 321 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.955651 | 0.722101 | 0.043326 | 0.083054 | 0.408589 | 321 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.955651 | 0.722101 | 0.043326 | 0.083054 | 0.408589 | 321 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.955651 | 0.722101 | 0.043326 | 0.083054 | 0.408589 | 321 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.955651 | 0.722101 | 0.043326 | 0.083054 | 0.408589 | 321 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.955968 | 0.724086 | 0.046251 | 0.088413 | 0.409256 | 321 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.955239 | 0.719521 | 0.038248 | 0.073677 | 0.395365 | 321 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.955651 | 0.722101 | 0.043326 | 0.083054 | 0.408589 | 321 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.774550 | 0.240840 | 0.100507 | 0.182656 | 0.226830 | 7073 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.960846 | 0.747498 | 0.113530 | 0.203911 | 0.469612 | 260 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.002925 | 0.000317 | 0.005359 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.005078 | -0.000412 | -0.009377 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.057181 | -0.181101 | 0.099602 | 9600 | 6752 |

### 福州市_永泰县_嵩口镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `990`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.969336 | 0.790351 | 0.000000 | 0.000000 | 0.467281 | 0 |
| markov_transition_projection | forecast_demand | 0.965281 | 0.764138 | 0.114338 | 0.205212 | 0.417351 | 260 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.965218 | 0.763708 | 0.109304 | 0.197068 | 0.421811 | 260 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.965218 | 0.763708 | 0.109304 | 0.197068 | 0.415778 | 260 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.965218 | 0.763708 | 0.109304 | 0.197068 | 0.415778 | 260 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.965218 | 0.763708 | 0.109304 | 0.197068 | 0.420624 | 260 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.965630 | 0.766505 | 0.117379 | 0.210098 | 0.424648 | 260 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.965123 | 0.763062 | 0.111312 | 0.200326 | 0.414788 | 260 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.965281 | 0.764138 | 0.110307 | 0.198697 | 0.422098 | 260 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.640237 | 0.147845 | 0.062930 | 0.118408 | 0.204953 | 11548 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.967752 | 0.765194 | 0.138326 | 0.243034 | 0.440168 | 324 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.008075 | 0.000412 | 0.013030 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.002008 | -0.000095 | 0.003258 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.001003 | 0.000063 | 0.001629 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.046374 | -0.324981 | -0.078660 | 18850 | 11288 |

### 福州市_永泰县_嵩口镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `664`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.976273 | 0.827360 | 0.000000 | 0.000000 | 0.499353 | 0 |
| markov_transition_projection | forecast_demand | 0.970540 | 0.772326 | 0.073045 | 0.136146 | 0.396415 | 294 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.972124 | 0.784567 | 0.102537 | 0.186002 | 0.399155 | 294 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.972187 | 0.785057 | 0.102537 | 0.186002 | 0.399162 | 294 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.972124 | 0.784567 | 0.102537 | 0.186002 | 0.399155 | 294 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.972124 | 0.784567 | 0.102537 | 0.186002 | 0.399155 | 294 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.972092 | 0.784322 | 0.101373 | 0.184084 | 0.398942 | 294 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.971712 | 0.781384 | 0.093291 | 0.170662 | 0.398091 | 294 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.972124 | 0.784567 | 0.102537 | 0.186002 | 0.399155 | 294 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.808604 | 0.259133 | 0.093612 | 0.171198 | 0.230805 | 6202 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.975672 | 0.823097 | 0.069409 | 0.129808 | 0.478323 | 83 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001164 | -0.000032 | -0.001918 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.009246 | -0.000412 | -0.015340 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.008925 | -0.163520 | -0.014804 | 9098 | 5908 |

### 福州市_永泰县_嵩口镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `markov_transition_projection`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `270`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.975735 | 0.823288 | 0.000000 | 0.000000 | 0.646672 | 0 |
| markov_transition_projection | forecast_demand | 0.974341 | 0.813303 | 0.042998 | 0.082450 | 0.552404 | 83 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.974373 | 0.813534 | 0.039168 | 0.075383 | 0.554853 | 83 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.974373 | 0.813534 | 0.039168 | 0.075383 | 0.554853 | 83 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.974373 | 0.813534 | 0.039168 | 0.075383 | 0.554853 | 83 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.974373 | 0.813534 | 0.039168 | 0.075383 | 0.554853 | 83 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.974436 | 0.813995 | 0.040441 | 0.077739 | 0.555168 | 83 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.974278 | 0.812843 | 0.037897 | 0.073027 | 0.555845 | 83 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.974373 | 0.813534 | 0.039168 | 0.075383 | 0.554853 | 83 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.802617 | 0.260263 | 0.087626 | 0.161132 | 0.217730 | 6371 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.973961 | 0.810065 | 0.034648 | 0.066975 | 0.632345 | 100 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.001273 | 0.000063 | 0.002356 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.001271 | -0.000095 | -0.002356 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.048458 | -0.171756 | 0.085749 | 8920 | 6288 |

### 苏州市_吴江区_黎里镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4042`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.920467 | 0.876213 | 0.000000 | 0.000000 | 0.438376 | 0 |
| markov_transition_projection | forecast_demand | 0.885944 | 0.821035 | 0.061014 | 0.115012 | 0.394214 | 1524 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.892095 | 0.830686 | 0.083312 | 0.153811 | 0.412686 | 1524 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.892095 | 0.830686 | 0.083584 | 0.154273 | 0.416695 | 1524 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.891953 | 0.830463 | 0.082771 | 0.152887 | 0.412080 | 1524 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.891982 | 0.830508 | 0.082771 | 0.152887 | 0.407874 | 1524 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.892237 | 0.830908 | 0.083855 | 0.154734 | 0.412948 | 1524 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.889487 | 0.826594 | 0.073909 | 0.137644 | 0.398562 | 1524 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.891982 | 0.830508 | 0.082771 | 0.152887 | 0.407874 | 1524 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.601910 | 0.420073 | 0.150221 | 0.261204 | 0.244511 | 14621 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.911794 | 0.863549 | 0.085838 | 0.158105 | 0.405156 | 698 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000543 | 0.000142 | 0.000923 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.009403 | -0.002608 | -0.016167 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000541 | -0.000113 | -0.000924 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.066909 | -0.290185 | 0.107393 | 9072 | 13097 |

### 苏州市_吴江区_黎里镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1794`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.926136 | 0.886930 | 0.000000 | 0.000000 | 0.633853 | 0 |
| markov_transition_projection | forecast_demand | 0.909867 | 0.862967 | 0.027865 | 0.054219 | 0.530035 | 677 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.913183 | 0.868009 | 0.050896 | 0.096863 | 0.554946 | 677 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.913041 | 0.867793 | 0.049552 | 0.094426 | 0.537835 | 677 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.913098 | 0.867879 | 0.049888 | 0.095035 | 0.542126 | 677 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.913183 | 0.868009 | 0.050896 | 0.096863 | 0.554946 | 677 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.913296 | 0.868181 | 0.054610 | 0.103564 | 0.554921 | 677 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.910972 | 0.864648 | 0.032715 | 0.063357 | 0.538573 | 677 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.913154 | 0.867966 | 0.050896 | 0.096863 | 0.554929 | 677 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.606587 | 0.439586 | 0.134974 | 0.237845 | 0.249347 | 14363 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.911766 | 0.866084 | 0.087422 | 0.160788 | 0.615417 | 1051 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.003714 | 0.000113 | 0.006701 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.018181 | -0.002211 | -0.033506 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | -0.000029 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.084078 | -0.306596 | 0.140982 | 8866 | 13686 |

### 苏州市_吴江区_黎里镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `2382`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.894164 | 0.841587 | 0.000000 | 0.000000 | 0.532225 | 0 |
| markov_transition_projection | forecast_demand | 0.870355 | 0.807275 | 0.028621 | 0.055649 | 0.491165 | 1046 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.879879 | 0.821432 | 0.066964 | 0.125523 | 0.503885 | 1046 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.879879 | 0.821432 | 0.066726 | 0.125105 | 0.501092 | 1046 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.879879 | 0.821432 | 0.066726 | 0.125105 | 0.501092 | 1046 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.879907 | 0.821474 | 0.066964 | 0.125523 | 0.503985 | 1046 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.879765 | 0.821264 | 0.067441 | 0.126360 | 0.503903 | 1046 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.876251 | 0.816039 | 0.052863 | 0.100418 | 0.500451 | 1046 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.879879 | 0.821432 | 0.066964 | 0.125523 | 0.503885 | 1046 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.603753 | 0.440142 | 0.169913 | 0.290471 | 0.258068 | 14464 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.870440 | 0.808013 | 0.090983 | 0.166792 | 0.551246 | 1602 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000477 | -0.000114 | 0.000837 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.014101 | -0.003628 | -0.025105 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.102949 | -0.276126 | 0.164948 | 7454 | 13418 |

### 苏州市_吴江区_黎里镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `2520`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.910915 | 0.867950 | 0.000000 | 0.000000 | 0.520540 | 0 |
| markov_transition_projection | forecast_demand | 0.873388 | 0.813855 | 0.041941 | 0.080506 | 0.396907 | 1602 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.887560 | 0.834690 | 0.103232 | 0.187144 | 0.405883 | 1602 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.887588 | 0.834732 | 0.103745 | 0.187987 | 0.405891 | 1602 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.887503 | 0.834607 | 0.102975 | 0.186723 | 0.405866 | 1602 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.887560 | 0.834690 | 0.103232 | 0.187144 | 0.405883 | 1602 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.884584 | 0.830315 | 0.090554 | 0.166070 | 0.404873 | 1602 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.879368 | 0.822647 | 0.064140 | 0.120548 | 0.399762 | 1602 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.887503 | 0.834607 | 0.102719 | 0.186301 | 0.405635 | 1602 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.555710 | 0.397314 | 0.154198 | 0.267195 | 0.231221 | 16543 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.908676 | 0.864366 | 0.159601 | 0.275269 | 0.475677 | 1042 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.012678 | -0.002976 | -0.021074 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.039092 | -0.008192 | -0.066596 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000513 | -0.000057 | -0.000843 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.050966 | -0.331850 | 0.080051 | 11452 | 14941 |

### 苏州市_吴江区_黎里镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1078`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.926844 | 0.892040 | 0.000000 | 0.000000 | 0.636909 | 0 |
| markov_transition_projection | forecast_demand | 0.906012 | 0.861295 | 0.045815 | 0.087616 | 0.504210 | 980 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.914231 | 0.873425 | 0.091662 | 0.167930 | 0.507835 | 980 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.914231 | 0.873425 | 0.091662 | 0.167930 | 0.507835 | 980 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.914231 | 0.873425 | 0.091662 | 0.167930 | 0.507835 | 980 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.914231 | 0.873425 | 0.091662 | 0.167930 | 0.507835 | 980 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.913948 | 0.873007 | 0.090325 | 0.165684 | 0.507600 | 980 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.911340 | 0.869159 | 0.075181 | 0.139848 | 0.507669 | 980 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.914231 | 0.873425 | 0.091662 | 0.167930 | 0.507835 | 980 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.574162 | 0.404095 | 0.124010 | 0.220656 | 0.250284 | 15719 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.915394 | 0.875795 | 0.064139 | 0.120546 | 0.614853 | 787 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.001337 | -0.000283 | -0.002246 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.016481 | -0.002891 | -0.028082 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.032348 | -0.340069 | 0.052726 | 7668 | 14739 |

### 西安市_周至县_陈河镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `9630`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.875643 | 0.422975 | 0.000000 | 0.000000 | 0.425546 | 0 |
| markov_transition_projection | forecast_demand | 0.845706 | 0.329992 | 0.040820 | 0.078438 | 0.257471 | 1351 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.846735 | 0.334462 | 0.044847 | 0.085844 | 0.258008 | 1351 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.846735 | 0.334462 | 0.044847 | 0.085844 | 0.258008 | 1351 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.846735 | 0.334462 | 0.044847 | 0.085844 | 0.258008 | 1351 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.846735 | 0.334462 | 0.044847 | 0.085844 | 0.258008 | 1351 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.848307 | 0.341286 | 0.055052 | 0.104360 | 0.258284 | 1351 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.846925 | 0.335286 | 0.047241 | 0.090221 | 0.257880 | 1351 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.846735 | 0.334462 | 0.044847 | 0.085844 | 0.258008 | 1351 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.657247 | 0.155225 | 0.199038 | 0.331996 | 0.221642 | 12603 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.912625 | 0.414140 | 0.494731 | 0.661967 | 0.440075 | 3495 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.010205 | 0.001572 | 0.018516 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.002394 | 0.000190 | 0.004377 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.154191 | -0.189488 | 0.246152 | 14416 | 11252 |

### 西安市_周至县_陈河镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `6010`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.902222 | 0.412234 | 0.000000 | 0.000000 | 0.434058 | 0 |
| markov_transition_projection | forecast_demand | 0.886535 | 0.230072 | 0.132995 | 0.234767 | 0.317278 | 1528 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.888350 | 0.242390 | 0.137511 | 0.241775 | 0.327943 | 1528 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.888458 | 0.243125 | 0.137763 | 0.242165 | 0.331784 | 1528 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.888458 | 0.243125 | 0.137763 | 0.242165 | 0.331784 | 1528 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.888350 | 0.242390 | 0.137511 | 0.241775 | 0.327943 | 1528 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.887862 | 0.239081 | 0.134998 | 0.237882 | 0.326140 | 1528 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.886616 | 0.230624 | 0.137008 | 0.240997 | 0.305933 | 1528 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.888404 | 0.242757 | 0.137763 | 0.242165 | 0.331777 | 1528 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.705879 | 0.088548 | 0.165083 | 0.283383 | 0.137285 | 10365 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.891628 | 0.402572 | 0.207493 | 0.343676 | 0.404080 | 1483 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002513 | -0.000488 | -0.003893 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.000503 | -0.001734 | -0.000778 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000252 | 0.000054 | 0.000390 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.027572 | -0.182471 | 0.041608 | 14974 | 8837 |

### 西安市_周至县_陈河镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_hierarchical_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `4068`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.925901 | 0.576586 | 0.000000 | 0.000000 | 0.474588 | 0 |
| markov_transition_projection | forecast_demand | 0.890978 | 0.471966 | 0.015275 | 0.030090 | 0.427935 | 1386 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.894365 | 0.488368 | 0.032056 | 0.062121 | 0.440201 | 1386 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.894446 | 0.488762 | 0.032315 | 0.062606 | 0.440368 | 1386 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.894446 | 0.488762 | 0.032315 | 0.062606 | 0.440368 | 1386 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.894338 | 0.488237 | 0.031798 | 0.061636 | 0.432264 | 1386 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.893796 | 0.485613 | 0.028707 | 0.055812 | 0.436233 | 1386 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.890301 | 0.468685 | 0.014275 | 0.028149 | 0.427750 | 1386 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.894338 | 0.488237 | 0.031798 | 0.061636 | 0.432264 | 1386 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.542698 | 0.082740 | 0.092525 | 0.169378 | 0.137195 | 17185 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.920916 | 0.529576 | 0.122363 | 0.218045 | 0.451789 | 723 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.003349 | -0.000569 | -0.006309 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.017781 | -0.004064 | -0.033972 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000258 | -0.000027 | -0.000485 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.060469 | -0.351667 | 0.107257 | 24510 | 15799 |

### 西安市_周至县_陈河镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `3218`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.925792 | 0.582374 | 0.000000 | 0.000000 | 0.571053 | 0 |
| markov_transition_projection | forecast_demand | 0.914061 | 0.499164 | 0.059798 | 0.112847 | 0.430411 | 717 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.916445 | 0.513059 | 0.066996 | 0.125579 | 0.442870 | 717 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.916527 | 0.513532 | 0.067326 | 0.126157 | 0.435313 | 717 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.916527 | 0.513532 | 0.067326 | 0.126157 | 0.435313 | 717 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.916391 | 0.512743 | 0.066667 | 0.125000 | 0.446776 | 717 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.917719 | 0.520480 | 0.084405 | 0.155671 | 0.449089 | 717 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.917096 | 0.516848 | 0.075965 | 0.141204 | 0.433052 | 717 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.916445 | 0.513059 | 0.066996 | 0.125579 | 0.442870 | 717 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.697291 | 0.155255 | 0.145229 | 0.253624 | 0.204844 | 11818 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.918450 | 0.562524 | 0.159365 | 0.274918 | 0.524338 | 913 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.017409 | 0.001274 | 0.030092 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.008969 | 0.000651 | 0.015625 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.078233 | -0.219154 | 0.128045 | 15992 | 11101 |

### 西安市_周至县_陈河镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1894`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.916283 | 0.609542 | 0.000000 | 0.000000 | 0.518935 | 0 |
| markov_transition_projection | forecast_demand | 0.896613 | 0.534635 | 0.034920 | 0.067483 | 0.403701 | 911 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.902438 | 0.560855 | 0.066080 | 0.123969 | 0.417651 | 911 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.902411 | 0.560733 | 0.065796 | 0.123469 | 0.409992 | 911 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.902411 | 0.560733 | 0.065796 | 0.123469 | 0.409992 | 911 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.902465 | 0.560977 | 0.066080 | 0.123969 | 0.420911 | 911 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.902601 | 0.561586 | 0.066365 | 0.124469 | 0.413254 | 911 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.896695 | 0.535001 | 0.036260 | 0.069983 | 0.406844 | 911 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.902411 | 0.560733 | 0.065796 | 0.123469 | 0.413820 | 911 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.717556 | 0.261316 | 0.121947 | 0.217385 | 0.174456 | 9956 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.898672 | 0.577474 | 0.098623 | 0.179539 | 0.481583 | 1377 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000285 | 0.000163 | 0.000500 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.029820 | -0.005743 | -0.053986 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | -0.000284 | -0.000027 | -0.000500 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.055867 | -0.184882 | 0.093416 | 14782 | 9045 |

### 郑州市_荥阳市_广武镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `7022`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.858659 | 0.773492 | 0.000000 | 0.000000 | 0.426736 | 0 |
| markov_transition_projection | forecast_demand | 0.819503 | 0.702584 | 0.062755 | 0.118099 | 0.362508 | 1375 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.823699 | 0.709499 | 0.072668 | 0.135490 | 0.364822 | 1375 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.823699 | 0.709499 | 0.072668 | 0.135490 | 0.364822 | 1375 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.823699 | 0.709499 | 0.072668 | 0.135490 | 0.364822 | 1375 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.823699 | 0.709499 | 0.072668 | 0.135490 | 0.364822 | 1375 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.823937 | 0.709891 | 0.073134 | 0.136299 | 0.365314 | 1375 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.822314 | 0.707216 | 0.067343 | 0.126188 | 0.362401 | 1375 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.823660 | 0.709434 | 0.072668 | 0.135490 | 0.364773 | 1375 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.512946 | 0.327111 | 0.169469 | 0.289823 | 0.268529 | 12564 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.814039 | 0.712063 | 0.123598 | 0.220004 | 0.388900 | 2139 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000466 | 0.000238 | 0.000809 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.005325 | -0.001385 | -0.009302 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | -0.000039 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.096801 | -0.310753 | 0.154333 | 13614 | 11189 |

### 郑州市_荥阳市_广武镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `7398`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.882611 | 0.811550 | 0.000000 | 0.000000 | 0.502511 | 0 |
| markov_transition_projection | forecast_demand | 0.804022 | 0.698417 | 0.024082 | 0.047031 | 0.429787 | 2138 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.814158 | 0.714014 | 0.055211 | 0.104644 | 0.437574 | 2138 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.814158 | 0.714014 | 0.055211 | 0.104644 | 0.437574 | 2138 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.814158 | 0.714014 | 0.055211 | 0.104644 | 0.437574 | 2138 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.814158 | 0.714014 | 0.055211 | 0.104644 | 0.437574 | 2138 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.815504 | 0.716085 | 0.059153 | 0.111699 | 0.438995 | 2138 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.809882 | 0.707434 | 0.040579 | 0.077993 | 0.436201 | 2138 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.814356 | 0.714318 | 0.056084 | 0.106212 | 0.437719 | 2138 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.571423 | 0.382470 | 0.175613 | 0.298760 | 0.279152 | 11314 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.885185 | 0.806877 | 0.246668 | 0.395724 | 0.470335 | 1619 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.003942 | 0.001346 | 0.007055 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.014632 | -0.004276 | -0.026651 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000873 | 0.000198 | 0.001568 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.120402 | -0.242735 | 0.194116 | 6514 | 9176 |

### 郑州市_荥阳市_广武镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_transition_prior_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `7388`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.832924 | 0.736165 | 0.000000 | 0.000000 | 0.410478 | 0 |
| markov_transition_projection | forecast_demand | 0.784148 | 0.647471 | 0.058599 | 0.110711 | 0.330292 | 1615 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.787632 | 0.653161 | 0.063035 | 0.118595 | 0.328448 | 1615 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.787632 | 0.653161 | 0.063035 | 0.118595 | 0.328448 | 1615 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.787632 | 0.653161 | 0.063035 | 0.118595 | 0.328448 | 1615 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.787632 | 0.653161 | 0.063035 | 0.118595 | 0.328448 | 1615 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.788226 | 0.654131 | 0.062648 | 0.117909 | 0.328492 | 1615 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.784029 | 0.647277 | 0.054772 | 0.103856 | 0.325892 | 1615 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.787552 | 0.653032 | 0.063229 | 0.118937 | 0.328625 | 1615 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.632790 | 0.450051 | 0.229998 | 0.373981 | 0.303620 | 9032 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.815781 | 0.721686 | 0.205910 | 0.341502 | 0.402628 | 2146 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000387 | 0.000594 | -0.000686 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.008263 | -0.003603 | -0.014739 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000194 | -0.000080 | 0.000342 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.166963 | -0.154842 | 0.255386 | 7412 | 7417 |

### 郑州市_荥阳市_广武镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `6178`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.852166 | 0.770442 | 0.000000 | 0.000000 | 0.458709 | 0 |
| markov_transition_projection | forecast_demand | 0.780268 | 0.675234 | 0.044034 | 0.084354 | 0.415112 | 2146 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.791789 | 0.692262 | 0.068120 | 0.127551 | 0.418051 | 2146 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.791789 | 0.692262 | 0.068120 | 0.127551 | 0.418051 | 2146 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.791789 | 0.692262 | 0.068120 | 0.127551 | 0.418051 | 2146 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.791789 | 0.692262 | 0.068120 | 0.127551 | 0.418051 | 2146 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.792976 | 0.694018 | 0.070648 | 0.131973 | 0.417535 | 2146 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.781733 | 0.677399 | 0.044591 | 0.085374 | 0.414927 | 2146 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.791789 | 0.692262 | 0.068120 | 0.127551 | 0.418051 | 2146 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.589635 | 0.408587 | 0.196655 | 0.328674 | 0.274494 | 10432 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.858738 | 0.773571 | 0.182819 | 0.309125 | 0.452560 | 1099 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.002528 | 0.001187 | 0.004422 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.023529 | -0.010056 | -0.042177 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.128535 | -0.202154 | 0.201123 | 5492 | 8286 |

### 郑州市_荥阳市_广武镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `6646`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.812178 | 0.717016 | 0.000000 | 0.000000 | 0.397862 | 0 |
| markov_transition_projection | forecast_demand | 0.789294 | 0.676811 | 0.043357 | 0.083111 | 0.353587 | 887 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.794243 | 0.684401 | 0.051344 | 0.097674 | 0.355574 | 887 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.794243 | 0.684401 | 0.051344 | 0.097674 | 0.355574 | 887 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.794243 | 0.684401 | 0.051344 | 0.097674 | 0.355574 | 887 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.794283 | 0.684462 | 0.051541 | 0.098029 | 0.355653 | 887 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.794402 | 0.684644 | 0.053508 | 0.101581 | 0.358085 | 887 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.793531 | 0.683308 | 0.056275 | 0.106553 | 0.355852 | 887 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.794243 | 0.684401 | 0.051344 | 0.097674 | 0.355574 | 887 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.574511 | 0.394955 | 0.234272 | 0.379611 | 0.279652 | 10951 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.809209 | 0.721867 | 0.253022 | 0.403859 | 0.394042 | 2615 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.002164 | 0.000159 | 0.003907 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.004931 | -0.000712 | 0.008879 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.182928 | -0.219732 | 0.281937 | 6688 | 10064 |

### 重庆市_云阳县_江口镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1422`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.951408 | 0.822859 | 0.000000 | 0.000000 | 0.496739 | 0 |
| markov_transition_projection | forecast_demand | 0.939719 | 0.780737 | 0.121763 | 0.217092 | 0.322523 | 723 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.940471 | 0.783470 | 0.129460 | 0.229243 | 0.321724 | 723 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.940471 | 0.783470 | 0.129460 | 0.229243 | 0.321724 | 723 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.940471 | 0.783470 | 0.129460 | 0.229243 | 0.321724 | 723 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.940471 | 0.783470 | 0.129460 | 0.229243 | 0.321724 | 723 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.940833 | 0.784786 | 0.133089 | 0.234913 | 0.322100 | 723 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.939664 | 0.780534 | 0.122783 | 0.218712 | 0.321260 | 723 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.940471 | 0.783470 | 0.129460 | 0.229243 | 0.321724 | 723 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.696955 | 0.274523 | 0.117833 | 0.210824 | 0.194500 | 11317 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.950100 | 0.815261 | 0.097331 | 0.177396 | 0.474905 | 351 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.003629 | 0.000362 | 0.005670 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.006677 | -0.000807 | -0.010531 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.011627 | -0.243516 | -0.018419 | 12416 | 10594 |

### 重庆市_云阳县_江口镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_neighborhood_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1892`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.943978 | 0.803882 | 0.000000 | 0.000000 | 0.451167 | 0 |
| markov_transition_projection | forecast_demand | 0.939079 | 0.783670 | 0.053970 | 0.102412 | 0.409175 | 350 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.939914 | 0.786635 | 0.059166 | 0.111722 | 0.419528 | 350 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.939914 | 0.786635 | 0.059166 | 0.111722 | 0.419528 | 350 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.939914 | 0.786635 | 0.059166 | 0.111722 | 0.419528 | 350 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.939914 | 0.786635 | 0.059166 | 0.111722 | 0.419528 | 350 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.939970 | 0.786832 | 0.060117 | 0.113415 | 0.418545 | 350 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.939358 | 0.784658 | 0.061069 | 0.115108 | 0.416559 | 350 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.939914 | 0.786635 | 0.059166 | 0.111722 | 0.419528 | 350 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.631276 | 0.230353 | 0.110385 | 0.198824 | 0.192034 | 13629 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.931148 | 0.770998 | 0.086080 | 0.158515 | 0.426580 | 788 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.000951 | 0.000056 | 0.001693 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.001903 | -0.000556 | 0.003386 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.051219 | -0.308638 | 0.087102 | 17628 | 13279 |

### 重庆市_云阳县_江口镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `2486`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.938996 | 0.792217 | 0.000000 | 0.000000 | 0.511410 | 0 |
| markov_transition_projection | forecast_demand | 0.918930 | 0.737763 | 0.019870 | 0.038965 | 0.427211 | 785 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.921964 | 0.747575 | 0.043829 | 0.083977 | 0.431951 | 785 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.921964 | 0.747575 | 0.043829 | 0.083977 | 0.431951 | 785 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.921964 | 0.747575 | 0.043829 | 0.083977 | 0.431951 | 785 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.921936 | 0.747485 | 0.043829 | 0.083977 | 0.431815 | 785 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.922242 | 0.748475 | 0.046397 | 0.088680 | 0.431992 | 785 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.919042 | 0.738123 | 0.021269 | 0.041653 | 0.427176 | 785 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.921936 | 0.747485 | 0.043829 | 0.083977 | 0.431815 | 785 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.703162 | 0.303357 | 0.136513 | 0.240232 | 0.227584 | 10937 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.933652 | 0.768154 | 0.124854 | 0.221992 | 0.475822 | 700 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.002568 | 0.000278 | 0.004703 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.022560 | -0.002922 | -0.042324 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | -0.000028 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.092684 | -0.218802 | 0.156255 | 10286 | 10152 |

### 重庆市_云阳县_江口镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_transition_prior_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `2680`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.929422 | 0.753086 | 0.000000 | 0.000000 | 0.442319 | 0 |
| markov_transition_projection | forecast_demand | 0.915424 | 0.696554 | 0.049287 | 0.093943 | 0.402380 | 700 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.919069 | 0.709635 | 0.079386 | 0.147095 | 0.411943 | 700 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.919069 | 0.709635 | 0.079386 | 0.147095 | 0.411943 | 700 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.919069 | 0.709635 | 0.079386 | 0.147095 | 0.411943 | 700 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.919069 | 0.709635 | 0.079386 | 0.147095 | 0.411943 | 700 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.919042 | 0.709535 | 0.079026 | 0.146477 | 0.411215 | 700 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.917873 | 0.705341 | 0.067634 | 0.126700 | 0.408601 | 700 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.919097 | 0.709735 | 0.079746 | 0.147713 | 0.412087 | 700 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.613242 | 0.219185 | 0.134109 | 0.236501 | 0.179825 | 14428 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.926277 | 0.741364 | 0.170812 | 0.291784 | 0.414429 | 665 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.000360 | -0.000027 | -0.000618 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.011752 | -0.001196 | -0.020395 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000360 | 0.000028 | 0.000618 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.054723 | -0.305827 | 0.089406 | 18990 | 13728 |

### 重庆市_云阳县_江口镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_independent_transition_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1844`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.948403 | 0.814922 | 0.000000 | 0.000000 | 0.515613 | 0 |
| markov_transition_projection | forecast_demand | 0.936269 | 0.774336 | 0.068729 | 0.128617 | 0.399477 | 634 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.938328 | 0.781628 | 0.085989 | 0.158360 | 0.401863 | 634 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.938328 | 0.781628 | 0.085989 | 0.158360 | 0.401863 | 634 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.938328 | 0.781628 | 0.085989 | 0.158360 | 0.401863 | 634 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.938328 | 0.781628 | 0.085989 | 0.158360 | 0.401863 | 634 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.938050 | 0.780643 | 0.083624 | 0.154341 | 0.400699 | 634 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.936102 | 0.773745 | 0.068270 | 0.127814 | 0.398572 | 634 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.938328 | 0.781628 | 0.085989 | 0.158360 | 0.401863 | 634 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.730602 | 0.323496 | 0.137550 | 0.241835 | 0.216933 | 10179 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.946621 | 0.804058 | 0.074840 | 0.139258 | 0.496778 | 329 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002365 | -0.000278 | -0.004019 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.017719 | -0.002226 | -0.030546 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.051561 | -0.207726 | 0.083475 | 10072 | 9545 |

### 长沙市_浏阳市_高坪镇_2017_2018_2019

- train: `2017->2018`
- holdout: `2018->2019`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `872`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.972388 | 0.885605 | 0.000000 | 0.000000 | 0.577052 | 0 |
| markov_transition_projection | forecast_demand | 0.962741 | 0.846389 | 0.079969 | 0.148095 | 0.465729 | 455 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.964570 | 0.853930 | 0.113691 | 0.204170 | 0.486374 | 455 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.964570 | 0.853930 | 0.113691 | 0.204170 | 0.486374 | 455 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.964570 | 0.853930 | 0.113691 | 0.204170 | 0.486374 | 455 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.964570 | 0.853930 | 0.113691 | 0.204170 | 0.486374 | 455 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.964659 | 0.854295 | 0.117269 | 0.209921 | 0.486760 | 455 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.963597 | 0.849916 | 0.097869 | 0.178289 | 0.480874 | 455 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.964570 | 0.853930 | 0.113691 | 0.204170 | 0.486374 | 455 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.697770 | 0.270280 | 0.070568 | 0.131834 | 0.206424 | 10533 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.970883 | 0.878379 | 0.060547 | 0.114180 | 0.562867 | 150 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.003578 | 0.000089 | 0.005751 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.015822 | -0.000973 | -0.025881 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | -0.043123 | -0.266800 | -0.072336 | 13836 | 10078 |

### 长沙市_浏阳市_高坪镇_2018_2019_2020

- train: `2018->2019`
- holdout: `2019->2020`
- best forecast by change FoM: `twm_ablation_no_transition_prior_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `832`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.970441 | 0.877994 | 0.000000 | 0.000000 | 0.547168 | 0 |
| markov_transition_projection | forecast_demand | 0.967196 | 0.863522 | 0.024933 | 0.048653 | 0.512215 | 149 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.967904 | 0.866467 | 0.041629 | 0.079930 | 0.521650 | 149 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.967579 | 0.865117 | 0.040687 | 0.078193 | 0.523171 | 149 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.967550 | 0.864994 | 0.040687 | 0.078193 | 0.520880 | 149 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.967963 | 0.866713 | 0.042572 | 0.081668 | 0.524397 | 149 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.967786 | 0.865976 | 0.038809 | 0.074718 | 0.526580 | 149 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.967461 | 0.864626 | 0.033214 | 0.064292 | 0.517503 | 149 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.968022 | 0.866958 | 0.043518 | 0.083406 | 0.527144 | 149 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.639212 | 0.223981 | 0.064308 | 0.120844 | 0.214863 | 12503 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.965101 | 0.857596 | 0.062806 | 0.118189 | 0.516064 | 301 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | -0.002820 | -0.000118 | -0.005212 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.008415 | -0.000443 | -0.015638 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.001889 | 0.000118 | 0.003476 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.022679 | -0.328692 | 0.040914 | 17878 | 12354 |

### 长沙市_浏阳市_高坪镇_2019_2020_2021

- train: `2019->2020`
- holdout: `2020->2021`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1016`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.976901 | 0.905526 | 0.000000 | 0.000000 | 0.572934 | 0 |
| markov_transition_projection | forecast_demand | 0.968582 | 0.872985 | 0.014032 | 0.027675 | 0.528629 | 301 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.969379 | 0.876205 | 0.031399 | 0.060886 | 0.531530 | 301 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.969379 | 0.876205 | 0.031399 | 0.060886 | 0.528664 | 301 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.969379 | 0.876205 | 0.031399 | 0.060886 | 0.528664 | 301 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.969379 | 0.876205 | 0.031399 | 0.060886 | 0.531530 | 301 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.969556 | 0.876920 | 0.036329 | 0.070111 | 0.531743 | 301 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.969320 | 0.875966 | 0.036329 | 0.070111 | 0.539741 | 301 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.969379 | 0.876205 | 0.031399 | 0.060886 | 0.531530 | 301 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.724940 | 0.318895 | 0.065321 | 0.122631 | 0.243725 | 9508 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.974158 | 0.894032 | 0.090517 | 0.166008 | 0.556903 | 229 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.004930 | 0.000177 | 0.009225 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | 0.004930 | -0.000059 | 0.009225 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.033922 | -0.244439 | 0.061745 | 12508 | 9207 |

### 长沙市_浏阳市_高坪镇_2020_2021_2022

- train: `2020->2021`
- holdout: `2021->2022`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `552`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.966960 | 0.866420 | 0.000000 | 0.000000 | 0.547180 | 0 |
| markov_transition_projection | forecast_demand | 0.963007 | 0.850000 | 0.047360 | 0.090437 | 0.524705 | 229 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.964069 | 0.854306 | 0.063880 | 0.120089 | 0.528706 | 229 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.964069 | 0.854306 | 0.063880 | 0.120089 | 0.528706 | 229 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.964069 | 0.854306 | 0.063880 | 0.120089 | 0.528706 | 229 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.964069 | 0.854306 | 0.063880 | 0.120089 | 0.528706 | 229 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.964305 | 0.855263 | 0.067247 | 0.126019 | 0.528179 | 229 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.963449 | 0.851794 | 0.054730 | 0.103781 | 0.527105 | 229 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.964069 | 0.854306 | 0.063880 | 0.120089 | 0.528706 | 229 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.641395 | 0.247052 | 0.068137 | 0.127581 | 0.251724 | 12393 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.962446 | 0.850156 | 0.117176 | 0.209772 | 0.556876 | 415 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.003367 | 0.000236 | 0.005930 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.009150 | -0.000620 | -0.016308 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.004257 | -0.322674 | 0.007492 | 18390 | 12164 |

### 长沙市_浏阳市_高坪镇_2021_2022_2023

- train: `2021->2022`
- holdout: `2022->2023`
- best forecast by change FoM: `twm_ablation_no_drivers_forecast_demand`
- best oracle by change FoM: `twm_independent_transition_oracle_demand`
- forecast demand abs error against oracle: `1204`

| candidate | demand mode | OA | Kappa | change FoM | change F1 | macro F1 | predicted change |
|---|---|---:|---:|---:|---:|---:|---:|
| persistence | forecast_demand | 0.965986 | 0.865778 | 0.000000 | 0.000000 | 0.502416 | 0 |
| markov_transition_projection | forecast_demand | 0.955986 | 0.828911 | 0.042610 | 0.081737 | 0.468288 | 413 |
| twm_independent_transition_forecast_demand | forecast_demand | 0.958228 | 0.837626 | 0.073338 | 0.136654 | 0.476894 | 413 |
| twm_hierarchical_transition_forecast_demand | forecast_demand | 0.958228 | 0.837626 | 0.073338 | 0.136654 | 0.476894 | 413 |
| twm_calibrated_hierarchical_transition_forecast_demand | forecast_demand | 0.958228 | 0.837626 | 0.073338 | 0.136654 | 0.476894 | 413 |
| twm_cross_region_smoothed_transition_forecast_demand | forecast_demand | 0.958228 | 0.837626 | 0.073338 | 0.136654 | 0.476894 | 413 |
| twm_ablation_no_drivers_forecast_demand | forecast_demand | 0.958611 | 0.839117 | 0.078512 | 0.145594 | 0.477484 | 413 |
| twm_ablation_no_neighborhood_forecast_demand | forecast_demand | 0.956428 | 0.830631 | 0.048895 | 0.093231 | 0.466839 | 413 |
| twm_ablation_no_transition_prior_forecast_demand | forecast_demand | 0.958228 | 0.837626 | 0.073338 | 0.136654 | 0.476894 | 413 |
| twm_ablation_no_demand_projection | no_demand_projection | 0.746386 | 0.337125 | 0.095092 | 0.173669 | 0.237256 | 8843 |
| twm_independent_transition_oracle_demand | oracle_demand | 0.961178 | 0.848423 | 0.065789 | 0.123457 | 0.488275 | 305 |

Ablation deltas against `twm_independent_transition_forecast_demand`:

| ablation | Δ change FoM | Δ OA | Δ change F1 | Δ target demand error | Δ predicted change |
|---|---:|---:|---:|---:|---:|
| twm_ablation_no_drivers_forecast_demand | 0.005174 | 0.000383 | 0.008940 | 0 | 0 |
| twm_ablation_no_neighborhood_forecast_demand | -0.024443 | -0.001800 | -0.043423 | 0 | 0 |
| twm_ablation_no_transition_prior_forecast_demand | 0.000000 | 0.000000 | 0.000000 | 0 | 0 |
| twm_ablation_no_demand_projection | 0.021754 | -0.211842 | 0.037015 | 10194 | 8430 |

## 8. 下一步

- 将当前 leave-region-out 跨区域平滑升级为真正的 region-holdout / temporal-holdout 参数共享实验，并报告分区域显著性。
- 增加 road/accessibility、population、planning-policy、economic activity 等更接近土地变化机制的协变量，重新评估 no-driver ablation。
- 将 demand 从简单历史趋势升级为独立情景需求模型，避免把模拟器能力和需求外推误差混在一起。
- 缓存可复用特征栈和 per-source-class 拟合结果，降低 100-case 真实基准的迭代成本。
