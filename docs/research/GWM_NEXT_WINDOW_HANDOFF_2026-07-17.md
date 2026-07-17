# GWM / Geospatial Kernel 新窗口交接

日期：**2026年7月17日，星期五**

分支：`feat/v12-extensible-platform`

## 1. 新窗口首先读取

按顺序读取：

1. `docs/research/GWM_RESEARCH_PRINCIPLES.md`
2. `docs/research/DAM_GK_RESEARCH_SPEC.md`
3. `docs/research/DAM_GK_TWM_STAGE_REVIEW_2026-07-17.md`
4. `docs/research/GWM_NEXT_WINDOW_HANDOFF_2026-07-17.md`

必须继续遵守：选择难而正确的方向；不把普通GNN、GIS缓冲或距离衰减包装成Geospatial Kernel；不把观测预测写成政策因果；不删除失败实验；不以测试通过替代科学验证。

## 2. 当前阶段定位

当前阶段可以冻结为：

`DAM-GK Observed Dynamics Baseline v1 — 2026-07-17`

它不是通用GWM完成版，也不是政策行动世界模型。它是一个具备真实多步状态写回、动态关系门控、软拓扑重算、多尺度图、未知地域验证和严格消融的观测状态动力学研究基线。

## 3. 当前主要代码

核心目录：

`data_agent/uwm/dam_geospatial_kernel/`

重点文件：

- `contracts.py`：张量契约、可变状态、教师强制和类别守恒转移模式；
- `model.py`：动态关系门控、时滞传播、软拓扑重算、递归状态写回；
- `twm_adapter.py`：真实Dynamic World年度转移和多关系、多尺度图；
- `twm_sequence_adapter.py`：2017—2023一致节点序列和严格过去时历史空间上下文；
- `twm_transition_head.py`：变化风险、条件目标类别、写回状态语义拆分；
- `twm_sequence_benchmark.py`：多步训练、地域留出、阈值选择、强基线和指标；
- `twm_benchmark.py`：单步真实数据基准；
- `controlled_benchmark.py`：受控机制恢复基准；
- `negative_controls.py`：地理负对照。

主测试：

`data_agent/test_uwm_dam_geospatial_kernel.py`

当前结果：`25 passed`。

## 4. 当前真实数据

目录：

`data/twm_public_landcover/gee_dynamic_world/`

20个地区，每个地区包含：

- 2017—2023年度Dynamic World土地覆盖，100米，9类；
- SRTM高程，100米；
- SRTM坡度，100米；
- VIIRS夜间灯光均值，100米。

当前节点状态为12维：9维土地类别状态和3维物理背景。

逐步上下文为10维：坐标、尺度、年份和6类严格过去时历史状态。6类历史状态是上一年变化、累计变化率、邻域近期变化率、邻域类别熵、邻域建成类占比和同类邻域占比。

当前正式矩阵采用采样步长24，即采样节点约每2.4千米一个。不要把它描述为全部100米像元训练。

## 5. 最新正确的概率语义

必须区分：

\[
q_t=P(change)
\]

\[
P(D_t\mid change)
\]

\[
P(S_{t+1})=(1-q_t)P(S_t)+q_tP(D_t\mid change)
\]

- `q_t`回答是否变化；
- `P(D_t | change)`回答真实变化后变成什么；
- `P(S_{t+1})`才是写回下一步的世界状态。

不要再用持久性混合后的未来状态冒充条件目标类别。最新代码已经修复这一问题，并新增真实变化单元上的`changed_destination_accuracy`和`changed_destination_macro_f1`。

## 6. 最新正式实验

实验协议：20地区，5折，种子31/47/73，共15次；每次12地区训练、4地区验证阈值、4个完全未见地区测试；80 epochs；训练目标2018—2020，测试目标2021—2023。

带严格过去时历史上下文：

`data/benchmarks/dam_gk_2026-07-17/twm_recursive_region_cv_5fold_3seed_conditional_destination_v5/summary.json`

无历史上下文配对消融：

`data/benchmarks/dam_gk_2026-07-17/twm_recursive_region_cv_5fold_3seed_conditional_destination_no_temporal_v5_ablation/summary.json`

这些结果位于被`.gitignore`忽略的`data/`目录，本机仍保留，但不会提交GitHub。

最新主结果：

- 递归变化F1均值0.391999，冻结状态0.384848，独立单步链0.352822；
- 递归变化F1在7/15次超过冻结状态，在9/15次超过单步链；
- 递归整体类别Macro-F1均值0.467355，冻结状态逐运行10/15次更低，但持久性仍为0.604943；
- 真实变化单元条件目标Macro-F1：递归0.196076、冻结0.188698、单步链0.151818；
- 条件目标Macro-F1中递归9/15次超过冻结，11/15次超过单步链；
- 历史上下文相对无历史版本，在递归变化F1上15/15次更好，平均提升0.234137；
- 历史上下文在整体类别Macro-F1上12/15次更好，平均提升0.161007；
- 历史上下文没有改善条件目标类别：只有9/15次更好，平均降低0.013832。

## 7. 当前科学结论

可以支持：

1. 严格过去时、具有局部空间结构的地理历史，稳定改善未来变化风险识别；
2. Kernel已真实执行多步写回、关系重算和拓扑重算；
3. 递归模型在真实变化单元的目标类别上平均优于独立单步链，但绝对性能仍低；
4. 地理历史主要回答“哪里会变化”，不能回答“为什么变成某一类”。

不能支持：

1. 高标准Geospatial Kernel已经全面完成；
2. 递归写回普遍优于冻结状态；
3. 已可靠预测未来土地类别；
4. 已学习政策因果效应；
5. 通用GWM或完整UWM已经实现；
6. 多阶段规划价值已经通过真实行动数据验证。

H3继续阻塞，H6继续阻塞。

## 8. 下一窗口最关键任务：数据基础升级

新skills如果可以帮助搜索、下载、整理或接入数据，应优先用于以下工作，而不是继续在当前20地区数据上调参。

### 第一优先级：逐年度外生驱动

- 年度VIIRS夜间灯光；
- 年度人口或人口栅格；
- 年度建成区、不透水面和建设强度；
- 历史道路网络或年度道路变化；
- 年度POI与公共服务设施；
- 年度企业、产业和就业活动。

### 第二优先级：带时空位置的真实事件

- 新建道路；
- 建设项目开工与竣工；
- 土地出让；
- 用地性质调整；
- 规划许可；
- 城市更新；
- 灾害和重大工程。

事件至少需要位置、时间、类别、强度、作用范围、事件前状态和事件后连续状态。

### 第三优先级：行动—结果或准实验数据

用于验证行动条件Kernel、反事实世界和Planner价值。必须区分观测行动、合成回放和规则模拟，不得把后两者冒充真实政策干预。

## 9. 新数据接入的验收门槛

新数据进入模型前必须完成：

1. 来源、许可和版本记录；
2. 时间戳语义说明；
3. 空间坐标系和分辨率对齐；
4. NoData、缺失和异常值检查；
5. 未来标签泄漏检查；
6. 训练、验证和测试地域隔离；
7. 数据覆盖率与有效样本量报告；
8. 原始数据与派生特征分离；
9. 对每类数据声明能支持和不能支持的科学主张。

## 10. 推荐的新窗口启动提示

可以直接在新窗口输入：

> 今天是2026年7月17日，星期五。请先阅读`docs/research/GWM_RESEARCH_PRINCIPLES.md`、`docs/research/DAM_GK_RESEARCH_SPEC.md`、`docs/research/DAM_GK_TWM_STAGE_REVIEW_2026-07-17.md`和`docs/research/GWM_NEXT_WINDOW_HANDOFF_2026-07-17.md`。继续Geospatial Kernel和GWM论文工作。首先使用新的skills评估并获取下一阶段所需的年度时变外生驱动和真实时空事件数据；不要继续在当前20地区数据上盲目调参；所有数据必须经过来源、时间、空间、泄漏和主张边界审查。

## 11. 常用验证命令

```bash
.venv/bin/pytest -q data_agent/test_uwm_dam_geospatial_kernel.py
.venv/bin/python -m py_compile data_agent/uwm/dam_geospatial_kernel/*.py
```

正式矩阵脚本：

```bash
.venv/bin/python scripts/run_dam_gk_twm_recursive_region_matrix.py \
  --sample-stride 24 \
  --epochs 80 \
  --seeds 31 47 73 \
  --output-dir data/benchmarks/dam_gk_2026-07-17/<new_experiment_name>
```

不要无理由重复运行已有完整矩阵。只有新增数据、明确算法假设或严格消融时才启动新的15次实验。
