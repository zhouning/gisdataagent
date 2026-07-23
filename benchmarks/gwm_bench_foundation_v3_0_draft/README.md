# GWM-Bench Foundation V3.0

## 当前状态

`V3_ALL_TRACKS_COMPLETED_VERIFIED`

V3已经完成五组预测、确定性或种子完整重放、预测承诺、承诺后目标注册和唯一一次正式评分。
协议要求的 `CONTROLLED-C2` 也已经完成512个更大不规则图、10个正式训练种子和7类对照，
其中8/10个种子达到冻结稳定门。
冻结的 `suite_protocol.json` 与 `runtime_r2_evaluator_seal.json` 仍保留预测前状态，不能为了显示
最终状态而修改；城市评分的封存状态以 `final_results/final_results.json` 为准，V3全轨道状态以
`final_results/v3_completion_manifest.json` 和 `final_results/v3_completion_verification.json` 为准。

最终主指标为：固定邻接空间 `0.2138`、TWM/DAM-GK `0.2029`、GeoSOS FLUS `0.1099`、
非空间历史 `0.0694`、状态不变 `0.0500`。TWM减FLUS的地区配对bootstrap差为 `0.0930`，
95%区间 `[0.0208, 0.1645]`；TWM明显优于FLUS，但没有超过固定邻接空间基线。

## V3只新增一个主要问题

V2检查原有20地区上的未来时间泛化。V3检查模型到完全没有参与训练、调参和阈值选择的
20个新城市后，三步土地状态递推是否仍然有效。

V3采用已经存在的2023-2025历史标签，但执行顺序严格隔离：

1. 固定协议、地区、输入年份、模型和评分器；
2. 只获取新城市2017-2022输入；
3. 封存TWM、FLUS和三个内部基线的预测哈希；
4. 预测全部封存后，才允许获取2023-2025测试标签；
5. 使用冻结评分器运行一次并发布全部结果。

因此V3是流程封存的地域锁箱，不是像V2那样真正的未来盲测。

## 固定数据范围

| 项目 | Draft1定义 |
| --- | --- |
| 开发地区 | 原20地区 |
| 地域锁箱 | 20个新城市，5个地理分层，每层4个 |
| 数据源 | `GOOGLE/DYNAMICWORLD/V1`、SRTM、VIIRS |
| 空间分辨率 | 100米 |
| 输入年份 | 2017-2022 |
| 预测年份 | 2023-2025 |
| 预测方式 | 从2022开始三步开环递推，不写回真实状态 |
| 主指标 | 20地区乘3年份变化F1的非加权平均 |

地区及边界在 `lockbox_regions.json`。机器可读总规则在 `suite_protocol.json`。

## 三条轨道

| 轨道 | 作用 | 当前状态 |
| --- | --- | --- |
| `RUNTIME-R2` | 统一准备、预测、写回、审计、哈希和标签防火墙 | 五模型与所有随机种子重放通过 |
| `CONTROLLED-C2` | DAM-GK在新图规模、关系组合、时滞和拓扑上的机制迁移 | 512样本、10种子、7类对照完成，8/10稳定门通过 |
| `OBSERVED-O3` | 20个新城市上的TWM、FLUS和三个基线对比 | 已完成并发布全部结果 |

水库、真实干预因果效应和跨TWM/UWM迁移均为非阻塞扩展，不属于V3核心完成条件。

## 预测前无标签预检（历史命令）

```bash
.venv/bin/python benchmarks/gwm_bench_foundation_v3_0_draft/preflight_v3_draft.py
```

该命令只适用于Phase C目标尚未取得时。V3 final后目标目录已经按协议存在，不应把预测前预检
重新解释为最终状态检查。预测前留存结果为：

```text
GWM-Bench Foundation V3.0-draft1: PASS_RUNTIME_R2_EVALUATOR_SEALED_LABEL_FIREWALL_INTACT
```

预检只读取协议、地区边界、已有开发数据清单和文件系统状态，不打开任何测试标签像素。

## Phase A获取命令

Phase A已经完成。以下命令用于断点重放或重新验证2017-2022输入，不会获取目标年份：

```bash
.venv/bin/python scripts/download_twm_gee_dynamic_world_benchmark.py \
  --project ee-zn19860115 \
  --regions-json benchmarks/gwm_bench_foundation_v3_0_draft/lockbox_regions.json \
  --years 2017,2018,2019,2020,2021,2022 \
  --driver-years 2017,2018,2019,2020,2021,2022 \
  --include-drivers \
  --output-dir data/twm_public_landcover/gee_dynamic_world_v3_input_2017_2022 \
  --manifest-output data/twm_public_landcover/gee_dynamic_world_v3_input_2017_2022/manifest.json \
  --status-output data/twm_public_landcover/gee_dynamic_world_v3_input_2017_2022/download_status.json
```

Phase A独立验收结果为：

| 项目 | 数量 |
| --- | ---: |
| 地区 | 20 |
| 年度土地状态栅格 | 120 |
| 驱动栅格 | 60 |
| 固定采样节点 | 1,227 |
| 状态历史行 | 7,362 |
| 有向四邻接边 | 4,278 |
| 2023-2025提交键 | 3,681 |
| 目标文件 | 0 |

节点和空间图已经通过20,859次逐值复算，评分器通过16项构造答案测试。预测承诺和Runtime-R2
回放完成前禁止创建或填充：

```text
data/twm_public_landcover/gee_dynamic_world_v3_lockbox_targets_2023_2025
```

本次执行先完成承诺与验证，承诺指纹为
`fcce6679f251b85d350f7ac41cab68164be383e6bbc5685df91542cbeb1b93c1`，随后才取得目标；
目标数据指纹为 `182333a179764d111750fe2430fb6a8ab7c163ce2ba2b43ce6553978bd7e7c71`。

## CONTROLLED-C2结果

受控轨道只使用确定性合成机制，不需要下载新数据。模型在128个规则 `4 x 4` 图上拟合，随后在
512个更大不规则图上测试；测试图有18,291个节点和137,012条边，包含训练样本中未共同出现的
三关系组合、1至5步时滞、软拓扑概率以及单行动源和双行动源变化。

| 项目 | 正式结果 |
| --- | ---: |
| 稳定门通过 | 8 / 10种子 |
| 受影响节点状态MAE均值 | 0.004540 |
| 行动门MAE均值 | 0.011814 |
| 软拓扑MAE均值 | 0.083318 |
| 时滞分布MAE均值 | 0.083803 |

无行动、固定拓扑、无时滞、行动打乱、关系打乱和空间重连均为10/10按预期退化；单关系消融为
8/10按预期退化。种子47和211没有通过，原因都是软拓扑概率误差超过冻结上限；没有删除失败、
替换种子或事后修改门槛。C2结果指纹为
`6cd522355ba50ef00c83e329fd6124c9d34abb5e115b12e3f6351bdcf4b04f14`。

## 最终结果与边界

五个模型已经全部报告。真实逐步变化共231个，20个地区均至少发生一次变化，满足预设充分性门。
TWM优于FLUS，但固定邻接空间的变化F1略高于TWM；同时固定邻接的类别Macro-F1和Brier更差，
因此不能用单一指标把它解释成全面更优。V3不使用主观综合分，也不证明真实政策因果、运营预测、
跨领域迁移或一般GWM有效性。

城市评分见 `final_results/FINAL_REPORT_ZH.md`；三轨合并结论见
`final_results/V3_COMPLETION_REPORT_ZH.md`。V3全轨道完成指纹为
`b41834410944115e6a987818bb1ecc5b38db1812582a8dda5b8f2a1fd5cae38e`。
