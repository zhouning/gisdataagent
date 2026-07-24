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

## 12. 2026年7月20日增量状态

本节保留7月17日交接内容不变，只记录后续进展。

### 12.1 完结边界

- `DAM-GK v0.1`已经完结，工程状态为`complete`，研究状态为`complete_negative`；H1-H5均拒绝，H6不属于该版本范围。不得把后续变体结果追溯改写成v0.1成功。
- `DAM-GK Hydro Action Transport v0.2`已经完结，得到有限的变体级支持：2024内部选择和2025冻结复核均在4/4 horizon通过预测、action shuffle、时间移位和机制敏感度门槛。
- 通用、高标准Geospatial Kernel仍未完结。v0.2不是因果模型、前瞻运行验证或公共独立benchmark，且Mendocino为0/4 horizon优于persistence。

机器检查：

```bash
uv run python scripts/check_dam_gk_completion.py --require all
uv run python scripts/check_dam_gk_hydro_action_transport_v0_2.py
```

### 12.2 forcing-aware进展

已物化fail-closed诊断面板：

- `data/gwm_dam_gk_hydro_forcing_diagnostic_v0/diagnostic_context_panel.parquet`；
- 共105,192行；三个系统回顾性上下文覆盖率均超过95%；
- 所有行`training_input_admitted=false`；
- CDEC inflow仅以`leakage_audit_inflow_cfs`保存，没有无条件`inflow_cfs`字段；
- `v0_3_training_panel_ready=false`。

正式残差审计：

- `data/benchmarks/dam_gk_2026-07-20/hydro_action_transport_forcing_residual_audit.json`；
- Mendocino湿时段MAE在4/4 horizon高于干时段；
- 最小湿/干MAE比`26.611130`；
- 近期降雨最大绝对相关系数`0.430887`；
- 只支持把严格过去时降雨纳入下一协议，不支持降雨因果效应，也不允许降雨替代独立不受控流量；
- `v0_3_training_admitted=false`。

### 12.3 AI Urban Scientist skill结论

完整的`AI-Urban-Sci-Skill-v1/skills/urban-data-seeker`现在可以使用：声明的25个来源/平台技能和vendored `open_data_skills`运行库已存在，适合类型路由、来源发现、限量探测和准入前治理。

它没有专门的hydrology source skill。按其type-first规则，NWM任务只能先走Data.gov/CKAN等平台fallback；确定性路由因“NOAA”关键词会选中`noaa-weather`，但该下游技能明确不覆盖水文模型，因此不能把该自动路由当成NWM适配器。

通过`127.0.0.1:7897`对Data.gov GSA v4 API进行的限量元数据检索，只找到旧版USGS NWM selected-gage routed-streamflow产品；这些产品版本/年份不覆盖2022-2025，也没有所需的增量河段`q_lateral`或`qSfcLatRunoff + qBucket`。它们不能作为独立不受控流量输入。

对`q_lateral`和`qSfcLatRunoff qBucket`的精确Data.gov检索均返回零记录。对BigQuery公共表的元数据请求能够到达Google API，但返回HTTP 401 `CREDENTIALS_MISSING`；本机没有GCP query project、ADC或BigQuery client。因此BigQuery仍是低传输量候选路径，不是当前已经可执行的数据源。

因此该skill对本任务的价值是“提高发现和排除候选的效率”，不是“已经补齐训练数据”。现有UWM manifest、license、lineage、时间可用性、空间交叉表、泄漏和claim gates仍必须保留。

### 12.4 当前唯一合理主路径

停止继续调整v0.2动作门控，也不要启动v0.3训练。下一阶段只推进独立不受控流量证据：

1. 如果取得GCP query project和ADC，优先执行冻结的BigQuery列裁剪canary，直接核验公共表schema、`forecast_offset/ensemble`与四个Azure `tm00`样本的一致性，并先做dry-run成本门槛；
2. 当前无GCP凭据时，沿Azure官方mirror分批提取548个冻结COMID的`feature_id/qSfcLatRunoff/qBucket/nudge`，保留400个缺失小时和NWM版本字段；预计最低传输量约61 GB，不能把远程HDF5切片描述为真正列裁剪；
3. 完成全时段fill/null/value coverage审计；
4. 补齐operational no-DA build/config、restart/spin-up、气象和陆面状态依赖，以及所有水库/同化设置的端到端独立性审计；
5. 持续收集严格absent-to-present publication latency证据。冻结门槛为72个合格转换、覆盖30天；当前检查点为2/72和`0.040116/30`天，当前最大发布延迟上界为`0.820278`小时。

Azure值提取canary已经完成：

- 编译器：`scripts/compile_gwm_bench_v0_3_nwm_azure_value_canary.py`；
- 机器清单：`benchmarks/gwm_bench_v0_3_candidate/nwm_azure_value_extraction_canary.json`；
- 12行系统-时点输出：`data/gwm_bench_v0_3_candidate/nwm_azure_value_canary/system_hourly_values.parquet`；
- 四个跨版本对象均通过Azure size/MD5和冻结SHA-256校验；
- 548个COMID均按`feature_id`联接，v2.1/v2.2/v3.0均通过；
- 三个分量均无selected fill/non-finite值，12个派生聚合与冻结审计一致；
- 当前只编译4/34,664个存在对象，`full_period_values_compiled=false`，`training_input_admitted=false`。

可恢复全时段编译器和跨版本受限pilot也已完成：

- 编译器：`scripts/compile_gwm_bench_v0_3_nwm_azure_values.py`；
- `full-file`路径每个对象先校验Azure size/MD5，再按`feature_id`提取，原子写入3行系统Parquet和receipt，通过后删除临时NetCDF；
- 新增`--transport sparse-range --proxy http://127.0.0.1:7897`路径：通过HDF5 HTTP Range只读取必需chunk，以Azure `If-Match` ETag固定对象，按NWM版本的冻结selector读取后再次核对548个`feature_id`；稀疏receipt使用v2，明确不声称全blob SHA-256；
- 支持传输损坏重试、跨进程对象锁、进程唯一临时文件和逐receipt断点续跑；
- 2022-01-01、2023-01-23和2024-01-01各一个完整UTC日，分别覆盖NWM v2.1、v2.2和v3.0；
- 72对象已编译216行，另有稀疏Range断点对象；selected fill为0、训练准入为false；manifest机器列举完整日期和对应版本；
- v2.2和v3.0配对续跑均为`compiled=0`、`skipped_verified=24`、`transferred_bytes=0`，临时源文件0；
- 当前以`latest_manifest.json`和对象receipt为准，编译仍是`partial_value_compilation_not_training_admitted`；不能把后台分片进度写成全时段覆盖、端到端独立性或forcing准入。

NWM publication-latency collector已完成沙箱外直连验证。经过测试的launchd模板已安装到`~/Library/LaunchAgents/`并以600秒间隔加载，且显式清除一个与任务无关的继承凭据。当前实时报告为`22`次poll、`4/72`个合格转换、`0.125625/30`天；安装任务不等于通过门槛，实时计数以`latest_report.json`为准。

只有独立不受控流量、输入时刻可用性和新独立确认集全部通过后，才冻结v0.3协议并训练。达到该点也只意味着HydroControl forcing-aware变体可以接受正式检验，不等于通用Geospatial Kernel完结。

NCEP当前生产配置审计新增进展：

- 官方入口：`https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.0.20/`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/nwm_ncep_operational_config_report.json`；
- 11个小型官方文本资产均保留URL、原始字节、SHA-256和获取时间；
- 当前ECF/job/script/no-DA namelist链已验证，`FORC_TYP=9`且`output_channelBucket_influx=2`；
- 生产脚本明确把正常AnA CHRTOUT作为open-loop channel输入，并允许no-DA restart缺失时回退到正常AnA、generic或cold restart；
- 当前no-DA namelist中的USGS/USACE reservoir persistence和RFC reservoir forecasts均为true，因此产品名不能直接证明所有观测依赖已关闭；
- `run.ver`匹配`v3.0.20`，但`build.ver`自报`v3.0.1`；2022-2025历史对象到具体生产包、restart和spin-up的逐对象谱系仍未验证；
- 该审计缩小了配置未知项，但同时强化了fail-closed边界：端到端独立性、forcing准入和训练准入仍为false。

### 12.5 NOAA LCD小时降水的访问、时延和版本边界

完整的`urban-data-seeker`经`exact_source`路由到`noaa-weather`后，已经完成一轮仅限小样本的官方来源审计：

- 契约：`benchmarks/gwm_bench_v0_3_candidate/noaa_lcd_source_access_and_latency_contract.json`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/noaa_lcd_source_access_and_latency_report.json`；
- 评估器：`scripts/assess_gwm_noaa_lcd_source_access_and_latency.py`；
- 所有官方页面、响应头和小样本原始字节位于被Git忽略的`data/gwm_bench_v0_3_candidate/noaa_lcd_source_access_and_latency/`，并由契约和报告中的SHA-256绑定。

访问结论必须按用途分开解释：NCEI官方产品页提供Bulk Download和引用说明，Data Access GET小样本无需token并返回HTTP 200，因此`internal_research_model_development`范围内的获取和研究使用门通过。当前证据没有给出原始子集或派生子集的明确公开再分发条款，所以两个公开再分发状态仍为`indeterminate`，不得把内部研究访问通过写成发布授权。

历史输入时可用性仍失败。LCD记录只有`DATE`、`REPORT_TYPE`、`SOURCE`等观测字段，没有逐记录`PUBLISHED_AT`、`INGESTED_AT`、`RECEIVED_AT`、版本ID或修订时间；当前HTTP `Date`和下载文件名中的2026获取时间只证明当前可下载，不能证明2022--2025各预测原点已经公开。观测时间也不得替代发布时间。

官方产品生命周期还排除了v1单源全时段方案：原LCD v1基于ISD，只提供到2025-08-29且不再更新，而冻结窗口要求到2026-01-01。对2025-09-01至09-02的v1探针返回空数组。因此不要执行v1-only的2022--2025全量下载；它在开始前已经确定无法通过完整时段门。

LCDv2/GHCNh形成了新的可检验版本桥候选，但不是即插即用替代：

- v1站号为`72590523275`，v2站号变为`USW00023275`；旧站号查询v2返回空体；
- 同名站坐标移动约`0.227846 km`，`SOURCE`代码也从v1的`6/7`变为v2的`343`；
- 2024-02-01至02-03的72条`FM-15`重叠记录时间戳集合完全一致，trace类别零冲突；
- 55个数值对最大差`0.05 mm`，对应v1百分之一英寸换算和v2十分之一毫米精度差异；
- v2新站号在v1停止更新后的2025-09小样本可访问。

这只支持`bounded_version_bridge_candidate=true`。下一条可执行主线是冻结站号/坐标/source-code交叉表，在更长重叠期验证缺失、trace、精度和逐小时一致性，并寻找带逐记录接收或发布时间的业务报文档案。完成这些工作前，`input_time_availability=fail`、`temporal_resolution_and_coverage=fail`、`training_input_admitted=false`、`general_geospatial_kernel_validated=false`保持不变；冻结K0快照不得修改。

更长重叠协议现已在接触新值之前冻结：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/noaa_lcd_v1_v2_stratified_bridge_protocol.json`；
- 可恢复采集器：`scripts/fetch_gwm_noaa_lcd_v1_v2_stratified_bridge.py`；
- 独立评估器：`scripts/assess_gwm_noaa_lcd_v1_v2_stratified_bridge.py`；
- 当前报告：`benchmarks/gwm_bench_v0_3_candidate/noaa_lcd_v1_v2_stratified_bridge_report.json`。

协议预注册70个日历日、1,680个预期常规小时，包含2022--2023冬季跨年、2023夏季干期、2024--2025冬季跨年和2025-08-16至v1最后日期2025-08-29四个窗口；已经使用过的2024-02-01至02-03发现窗口被明确排除。接受规则要求每个窗口的v1/v2时间戳集合完全一致、联合覆盖率至少95%、numeric/trace/missing类别零冲突、数值差不超过0.051 mm、无重复时间戳、站号交叉表正确且坐标偏移不超过0.5 km。即使四个窗口全部通过，也不能替代发布时间、站点到流域空间支撑或训练准入门。

每个响应有2 MB硬上限、总量有16 MB硬上限，预计仅约4.5 MB，不是全量下载。首次八路并发和随后沙箱外低并发均无法连接NCEI已解析节点；可恢复采集器的正式尝试记录为8/8失败、0字节正文，当前状态为`retrieval_incomplete_bridge_not_assessed`。这不是版本桥失败，也不是数据不存在。窗口和阈值不得因本次访问失败而改变。

端点恢复后的原样续跑命令：

```bash
.venv/bin/python scripts/fetch_gwm_noaa_lcd_v1_v2_stratified_bridge.py
.venv/bin/python scripts/assess_gwm_noaa_lcd_v1_v2_stratified_bridge.py
```

采集器会跳过已通过SHA-256复核的成功收据，只重试失败请求；任何不完整清单都禁止进入窗口评估。当前`stratified_v1_v2_bridge_supported=false`仅表示尚未评估，不得写成科学拒绝。

NOAA单站空间角色也已从“未验证”收敛为明确的`nearby_point_cross_check_only`：

- 契约：`benchmarks/gwm_bench_v0_3_candidate/noaa_hourly_precipitation_spatial_role_contract.json`；
- 新证据契约：`benchmarks/gwm_bench_v0_3_candidate/noaa_hourly_precipitation_spatial_role_v2_contract.json`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/noaa_hourly_precipitation_spatial_role_report.json`；
- 评估器：`scripts/assess_gwm_noaa_hourly_precipitation_spatial_role.py`。

站点和controlled-release目标点身份均已由原候选契约与Mendocino线性参考报告交叉验证，点距为`7.813544 km`，在发现阶段15 km上限内。v1审查首先确认“附近”不是空间forcing证据；随后按照“新证据必须新版本”的规则，v2从USGS NLDI取得并哈希绑定`USGS-11462000`上游流域Polygon。该几何有效，面积约`277.565037 km²`；controlled-release目标点与流域相交，但Ukiah机场站不相交，站点距流域边界约`6867.717 m`。这个上游流域也不等于release到Hopland之间的下游增量catchment。

因此当前虽已通过`source_bound_target_support_geometry`子项，`station_inside_or_overlapping_support_geometry`明确失败；完整站网或最近站选择、空间聚合/插值、地形代表性、误差量化和完整有效期仍缺失。`co_located_point_forcing_supported=false`、`basin_or_catchment_forcing_supported=false`、`spatial_role_and_topology=fail_cross_check_only`保持不变。

这项裁决允许把Ukiah观测用于非训练的邻近点交叉检查，但禁止作为Kernel forcing、训练或评估输入。后续若要升级，必须新建协议版本并在读取完整值之前选择落在正确目标支撑域内的完整站网或等价格点产品，冻结聚合或插值规则，并绑定地形支撑、代表性误差和有效期；不能仅通过放宽距离阈值升级。

### 12.6 CDEC Mendocino上游降水站网的预取值空间协议

已沿上述要求创建新的、读取多站历史值之前冻结的空间协议：

- 契约：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_station_network_contract.json`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_station_network_report.json`；
- 评估器：`scripts/assess_gwm_cdec_mendocino_precipitation_station_network.py`；
- 测试：`data_agent/test_assess_gwm_cdec_mendocino_precipitation_station_network.py`。

该协议只读取并哈希校验元数据目录、USGS流域几何和已有派生协议，没有读取新的历史降水值。CDEC静态目录的23个区域站中有15个带精确逗号分隔`sensor 2`；按站点坐标与`USGS-11462000`上游流域Polygon相交、零缓冲、禁止最近站替代的规则，选中`BOY/CDW/COY/DRW/HDH/PTV/PVN/PVP/WDG`九站，排除流域外六站。`NCW`距边界仅`17.463174 m`，仍按冻结规则排除，证明协议没有为扩大站数放宽边界。

空间聚合已经在多站取值前冻结为：将九个站点投影到`EPSG:32610`，生成Voronoi单元并裁剪到上游流域，以裁剪单元面积占比作为固定权重。九个单元各自唯一归属一个站，合计覆盖投影流域`277.343686 km²`，覆盖率和权重和均为1。每个小时必须九站均有按既有因果差分协议得到的合法增量；任何站缺失都不得重归一化其余权重，也不得前后填充、时间插值或引入流域外站。COY虽与controlled-release近邻，但面积权重仅约`0.007234`，因此COY单点不能冒充流域平均forcing。

这一步关闭的是“取值前固定空间选择与聚合规则”，没有关闭forcing准入。当前目录是带`Hide Inactive`过滤的2022静态快照，不能证明当前或历史站网完整；其余八站的当前小时`sensor 2`语义、九站2022--2025联合覆盖、逐预测原点发布时间、地形/雨影代表性、留一站误差和许可/再分发条款都未验证。该Polygon还是release处的上游流域，不是release到Hopland的下游增量catchment。故`basin_forcing_model_input_admitted=false`、`training_or_evaluation_input_admitted=false`、`general_geospatial_kernel_validated=false`、`general_gwm_validated=false`继续保持。

下一步必须先获取九站当前官方元数据并逐站确认`PRECIPITATION, ACCUMULATED`、`RAIN`、`INCHES`、小时频率及有效期；同时寻找能证明当前/历史站网完整性的官方目录。只有这两个元数据门通过后，才按已冻结的九站名单限量获取2022--2025值并审计严格联合覆盖，不能因某站覆盖差而在同一协议版本中删站或改权重。

九站当前元数据审计现已完成，且推翻了“静态目录中的sensor 2都能作为当前小时输入”的隐含假设：

- 受限采集器：`scripts/fetch_gwm_cdec_mendocino_precipitation_station_metadata.py`；
- 证据契约：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_station_metadata_contract.json`；
- 评估器：`scripts/assess_gwm_cdec_mendocino_precipitation_station_metadata.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_station_metadata_report.json`；
- 原始页与清单：`data/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_station_metadata/raw/20260722T103413Z/`。

采集器经本地代理取得9/9个官方页面，共`719943`字节；单页上限500 KB、总量上限5 MB，未请求历史值接口，也未持久化Cookie响应头。首次沙箱内运行的9/9本地`Operation not permitted`、0字节失败清单保留在相邻时间戳目录中，它不是CDEC科学失败；沙箱外原样重跑才形成当前完整证据清单。

当前小时sensor 2元数据只在`BOY/COY/DRW/HDH/PVN/WDG`六站通过。`CDW`当前sensor 2为event；`PTV`小时sensor 2只覆盖到`2009-02-07`，当前sensor 2为event；`PVP`的sensor 2为monthly且只覆盖到1998。PVP另有当前小时sensor 16 `PRECIPITATION, TIPPING BUCKET / RAINTIP`，但它不是既有累计量sensor 2，禁止未经独立语义与派生协议直接替代。

因此v1九站网络的`all_station_hourly_sensor_semantics=fail`，同版本内不得删除三站或重算权重，也不得开始九站历史值下载。下一步应先从当前官方CDEC站点清单重新筛选流域内全部小时累计降水站；若只能得到六站子集，必须新建v2元数据选择契约并在任何新值之前重新冻结Voronoi权重。即使v2元数据门通过，当前/历史站网完整性、2022--2025严格联合覆盖、发布时间、地形代表性和许可仍须独立关闭，训练准入与通用Kernel结论继续为false。

当前CDEC候选发现与v2空间协议现已继续完成：

- 当前目录协议：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_current_precipitation_catalog_protocol.json`；
- 当前目录报告：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_current_precipitation_catalog_report.json`；
- 新站元数据协议：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_new_station_metadata_protocol.json`；
- 新站元数据报告：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_new_station_metadata_report.json`；
- v2站网契约与报告：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_station_network_v2_contract.json`和`cdec_mendocino_precipitation_station_network_v2_report.json`。

当前站点页公布的生产Locator入口返回HTTP 404；正式协议同时绑定了可达的CDEC开发版Locator、基础/定制JavaScript配置及由配置推导出的`getRealTimePrecipitationDataStations`端点。开发版可达不等于生产完整性证明，但它提供了比2022静态导出更新的当前有界候选集。流域外包框返回20个活动`rain`站，Polygon零缓冲筛选保留17站，排除`NCH/NCW/YJR`。17站包含原9站，并新增`ANP/CPI/GPN/MSR/PUR/PVC/PVE/UPO`八站，故2022静态目录的当前候选完整性明确为false。

八个新增站的官方页面全部成功获取，共`589430`字节，仍未读取历史值。`ANP/CPI/GPN/MSR/PUR/PVE/UPO`只有从`2026-01-28`开始的event累计/增量降水；`PVC`有正确的小时sensor 2语义，但从`2023-08-01`才开始。八站全部无法覆盖冻结的2022起点。至此17个当前候选的元数据均已裁决，值盲合格集合稳定为`BOY/COY/DRW/HDH/PVN/WDG`六站。

v2契约按照新证据新版本原则冻结这六站，并在任何六站历史值获取前重算Voronoi权重。六个裁剪单元完整覆盖`277.343686 km²`投影流域，权重和为1；COY权重从v1的`0.007234`变为v2的`0.024234`。这不是调参，而是站集版本变化后的确定性几何结果；后续缺测不得临时重归一化。当前候选发现、17站元数据裁决、六站当前语义和v2空间聚合协议通过，但生产目录完整性仍为`indeterminate`，历史联合覆盖仍未评估，发布时间仍为`fail`。下一步只能按冻结六站名单取2022--2025值并严格审计联合覆盖，不得根据结果删站。

### 12.7 CDEC六站历史值裁决

六站值探针与全时段审计现已完成，且没有修改冻结的v2站集、Voronoi权重或因果差分阈值：

- 三日探针契约：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_values_probe_v2_contract.json`；
- 三日探针报告：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_values_probe_v2_report.json`；
- 全时段协议：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_values_v2_protocol.json`；
- 全时段报告：`benchmarks/gwm_bench_v0_3_candidate/cdec_mendocino_precipitation_values_v2_report.json`；
- 可恢复采集器：`scripts/fetch_gwm_cdec_mendocino_precipitation_values_v2.py`；
- 独立评估器：`scripts/assess_gwm_cdec_mendocino_precipitation_values_v2.py`。

三日探针取得6/6个官方响应，共`73218`字节，字段、站号、sensor 2、小时频率、`RAIN`和`INCHES`身份全部通过。端点访问/结构门因此为`pass`。严格值网格不通过：`BOY/DRW/HDH/PVN/WDG`均在源标签`2024-02-01 08:00`返回`-9999`，只有COY有效；联合覆盖为`71/72 = 0.986111`。前后值相同也没有用于填补，探针的72/72规则没有事后放宽。

正式协议在读取全时段值之前冻结24个年度站点请求、单响应2 MB和总量48 MB上限、逐请求SHA-256收据、固定PST到UTC重建、首个UTC小时所需的前置源标签缓冲、跨分片边界精确重复折叠，以及既有派生契约中的单站和六站联合`>=0.95`门。24/24响应均一次成功，共`24964289`字节；所有正文和收据哈希通过。评估只输出质量统计，没有物化逐时增量、流域值或训练面板。

全时段结果为明确失败：

- `COY`派生覆盖为`0.978696`，单站通过；
- `BOY/DRW/HDH/PVN/WDG`分别为`0.611026/0.600217/0.610740/0.612879/0.604038`，全部失败；
- 后五站的2023分片均只有9行：3月连续7小时、11月1小时和下一年边界；共同长时段停测不是重试可恢复的网络失败；
- 六站联合派生覆盖为`20467/35064 = 0.583704`，远低于`0.95`；
- 缺测权重重归一化、填补和插值次数均为0。

因此`full_2022_2025_six_station_joint_value_coverage=fail`。禁止根据该结果删除五站、只保留COY或重算同版本权重；那会构成值驱动选择。CDEC v2站网主线到此停止，不能进入basin forcing或训练。生产目录完整性和地形/雨影代表性仍为`indeterminate`，输入时可用性、公开再分发、独立不受控流量、训练准入均为`fail`。

下一步不再围绕这六站调协议。若继续降水forcing，应先为具有正确流域面支撑的格点产品建立新的取值前协议，冻结产品版本、空间裁剪/面积聚合、小时语义、2022--2025覆盖、业务发布时间、地形代表性、许可和误差门。Ukiah单站仍只作邻近点交叉检查。独立不受控流量仍由NWM链关闭，降水不得替代该变量。K0保持：工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

### 12.8 格点降水候选的元数据筛选

已在接触任何栅格值之前完成新的候选筛选协议和正式证据快照：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/gridded_precipitation_candidate_screening_protocol.json`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/gridded_precipitation_candidate_screening_report.json`；
- 受限采集器：`scripts/fetch_gwm_gridded_precipitation_candidate_screening.py`；
- 独立评估器：`scripts/assess_gwm_gridded_precipitation_candidate_screening.py`；
- 测试：`data_agent/test_assess_gwm_gridded_precipitation_candidate_screening.py`；
- 原始元数据与清单：`data/gwm_bench_v0_3_candidate/gridded_precipitation_candidate_screening/raw/20260722T130000Z/`。

路由严格记录了完整`urban-data-seeker`的能力边界：其NOAA bundled adapter覆盖站点CDO/LCD，不覆盖MRMS、Stage IV、AORC或NLDAS格点产品，因此先用Data.gov做发现回退，再转向NOAA NODD/AWS和NASA CMR原生元数据。这个路由结果不是模型准入。协议冻结16个元数据请求和`3b5c256c467bdaa41443e82562c32c9a31bab2572414922d9553d89ed99a78a0`自哈希，禁止GRIB/NetCDF资产、Earthdata认证资产、栅格值读取和训练面板物化，并绑定CDEC v2失败报告及目标流域几何。

正式采集取得14/16个响应，共`528740`字节。MRMS和NLDAS原生元数据请求全部成功并通过正文SHA-256复核；两个失败项仅为Data.gov Stage IV/AORC对照，均返回HTTP 429。报告将它们记为`rate_limited_not_assessed`，对应科学字段为`null`，不得把限流误写成“未找到”或“候选失败”。因此整批manifest为`incomplete`，但两个主要候选的元数据筛选完整。

MRMS筛选结果：

- NOAA官方产品身份、运行小时产品表和开放使用/署名文字通过；
- `2022-01-01/2023-01-01/2024-01-01/2025-01-01/2025-12-31`五个代表日均有24/24个小时对象；
- 2023--2025样本对象的`LastModified`约在标称对象时间后`0.257--0.290`小时；
- 2022-01-01的24个对象却统一在`2023-03-13T05:09:02Z`写入，证明存在历史批量补载；
- 因此当前云对象`LastModified`不能在缺少lineage时冒充原始发布时间，五个完整样本日也不能冒充2022--2025全时段覆盖；
- 全时段目录、原始发布时间、Pass1/版本修订语义、目标流域网格支撑和地形/地形雨代表性仍未关闭。

MRMS当前状态是`operational_candidate_publication_and_full_coverage_pending`。它只被选择进入新的元数据修复协议，`eligible_for_value_protocol=false`，尚不允许下载栅格值。

NLDAS筛选结果：

- `NLDAS_FORA0125_H` v2.0身份、小时频率和`0.125°`网格通过，目标流域包框位于集合范围内；
- 四个代表日均返回24/24个小时granule；
- CMR生产时间相对观测小时延迟`78.008889--12543.276389`小时；
- 官方重处理通知和受保护资产/临时凭据链接均存在，本协议没有请求认证资产；
- 这些生产延迟不满足历史预测原点可用性，公开元数据访问也不等于原始或派生值的公开再分发授权。

NLDAS只能作为`retrospective_cross_check_only`，不得作为预测时点forcing或训练输入。Stage IV/AORC则尚未完成对照筛选，不能作正负结论。

本轮没有候选进入value protocol。`historical_input_time_availability=fail`、`independent_uncontrolled_flow=fail`，流域空间聚合、地形代表性、完整许可仍为`indeterminate`；`basin_forcing_model_input_admitted=false`、`training_input_admitted=false`、`general_geospatial_kernel_validated=false`和`general_gwm_validated=false`。降水仍不得替代NWM负责关闭的独立不受控流量。

下一步唯一允许的MRMS动作是先冻结新的元数据修复协议，至少关闭：2022--2025全对象目录与产品版本边界、Pass1支撑区间及输入/修订语义、严格的首次出现发布时间证据或等价官方lineage、网格定义与流域单元交叠，以及地形代表性误差协议。只有这些非补偿门独立通过后，才可另建栅格值协议；不能从本轮五日样本直接跳到下载值、构造forcing或训练。

### 12.9 MRMS 2022--2025全对象目录裁决

已完成上述MRMS元数据修复的第一步，并保持零栅格值访问：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_full_period_catalog_protocol.json`；
- 正式报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_full_period_catalog_report.json`；
- 受限采集器：`scripts/fetch_gwm_mrms_full_period_catalog.py`；
- 独立评估器：`scripts/assess_gwm_mrms_full_period_catalog.py`；
- 测试：`data_agent/test_assess_gwm_mrms_full_period_catalog.py`；
- 正式原始目录：`data/gwm_bench_v0_3_candidate/mrms_full_period_catalog/raw/20260722T132330Z/`。

协议在正式分页前冻结四个年度S3 ListObjectsV2 walk、`2022-01-01T00:00:00Z`至`2026-01-01T00:00:00Z`的`35064`个精确UTC小时、每页1000项、每年最多12页、总计最多48页和32 MB正文上限。只允许公开目录XML；禁止GRIB/NetCDF对象GET、HEAD、Range、栅格值读取和forcing/training panel物化。协议自哈希为`db6551100df8bb6d7600a5bd996efb7f856a8a73637cfda3ac8778714b0b9a90`。本轮使用完整`urban-data-seeker`完成来源路由，但其`noaa-weather`下游工具仍是站点CDO/LCD能力，因此实际采集按顶层fallback规则使用NOAA NODD公开S3原生元数据；skill路由不构成模型准入。

正式采集完成4/4个年度walk、36个连续分页、共`11678439`字节，所有页正文、manifest、自哈希、前缀、KeyCount、严格键顺序、continuation token来源和终止页均通过独立重放。清单中有`35044`个唯一、正大小、符合精确命名规则的对象；没有重复、越界或异常产品键，但比冻结网格少20小时：

- 2022：`8748/8760 = 0.998630`，缺12小时；
- 2023：`8755/8760 = 0.999429`，缺5小时；
- 2024：`8781/8784 = 0.999658`，缺3小时；
- 2025：`8760/8760 = 1.0`，无缺口。

20个缺失小时形成15个连续段，最长为`2022-02-28T13:00:00Z`至`15:00:00Z`三小时。其余两小时段为`2022-04-26T01:00--02:00Z`、`2023-11-09T18:00--19:00Z`和`2024-03-19T18:00--19:00Z`，其余均为孤立小时；完整精确列表保存在报告中。协议已冻结“每个预期UTC小时必须恰有一个对象”，所以`35044/35064 = 0.999430`仍是`full_2022_2025_catalog_coverage=fail`。不得用插值、相邻累计产品、Pass2、站点值或调低门槛填补这20小时。

本轮也关闭了一个重要误区。NOAA当前运行表确实明确给出`MultiSensor_QPE_01H_Pass1`为`60-min`、`mm`、一小时累计和`20-minute latency`，该当前产品语义通过。但全目录的当前S3 `LastModified`相对对象名标称小时显示：

- 2022有`4835`个对象晚于标称小时24小时以上；
- 2023有5个，2024有0个，2025有1个；
- 全时段共`4841`个，最大滞后`29137.67`小时；
- 2022的中位滞后达到`6154.474444`小时，明显存在大批历史补载或重写。

因此`LastModified`只能证明当前云对象最近写入时间，不能单独证明首次公开时间；当前20分钟声明也不能自动外推到每个2022--2025预测原点。`historical_input_time_availability=fail`保持不变。目录产品名跨观察对象稳定，也不能证明MRMS软件/算法版本和Pass1输入/修订语义在完整有效期内稳定。

MRMS现在仍处于`metadata remediation`，没有进入value protocol。下一步只能：对20个缺失小时做不填补的官方目录/运行事件裁决；取得首次发布时间或等价业务lineage；绑定MRMS软件版本与Pass1输入/修订有效期；另行冻结网格定义、流域单元面积聚合和地形代表性误差协议。任一门未关闭时，`basin_forcing_model_input_admitted=false`、`training_input_admitted=false`、`independent_uncontrolled_flow_admitted=false`、通用Kernel/GWM声明为false，K0总体仍为`fail_closed`。

### 12.10 MRMS缺失对象的跨产品归因

已在不读取任何栅格值的前提下，对全目录发现的20个Pass1缺口完成当前目录重查和跨产品上下文分类：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_missing_object_context_protocol.json`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_missing_object_context_report.json`；
- 采集器：`scripts/fetch_gwm_mrms_missing_object_context.py`；
- 评估器：`scripts/assess_gwm_mrms_missing_object_context.py`；
- 测试：`data_agent/test_assess_gwm_mrms_missing_object_context.py`；
- 正式原始目录：`data/gwm_bench_v0_3_candidate/mrms_missing_object_context/raw/20260722T141600Z/`。

协议自哈希为`2b8cb24e5f9ee89f1538ac95e335e3de54e9c29405dee82a6ffcc89577bd9a6d`，在正式请求前冻结14个受影响日期、20个精确UTC小时和三个产品角色：

- `MultiSensor_QPE_01H_Pass1`：唯一主候选，只重查当前对象是否仍缺；
- `MultiSensor_QPE_01H_Pass2`：小时、官方一小时延迟，只作下游多传感器上下文；
- `RadarOnly_QPE_01H`：每2分钟更新的一小时滚动累计，只取对应整点对象作上游雷达上下文。

三个产品语义并不相同，Pass2或RadarOnly即使存在也禁止替代Pass1。协议只允许42个S3 ListObjectsV2日目录请求，禁止GRIB对象GET、HEAD、Range、栅格读取、forcing或训练面板物化。完整`urban-data-seeker`继续负责NOAA来源路由和probe-first边界；站点型`noaa-weather`工具不实现MRMS目录，因此使用NOAA NODD原生公开S3元数据。

正式采集42/42成功，共`3191841`字节、`10381`个目录对象；全部正文、manifest、前缀、KeyCount、非分页终止和对象大小均通过独立SHA-256复核。当前Pass1日目录仍恰好缺冻结的20小时，没有对象后来重新出现。跨产品分类为：

- 8小时：仅Pass1缺失，Pass2和RadarOnly整点对象均存在；
- 1小时：Pass1和Pass2缺失，RadarOnly存在，即`2022-02-28T13:00:00Z`；
- 2小时：Pass1和RadarOnly缺失，Pass2存在，即`2022-04-06T20:00:00Z`和`2022-04-26T01:00:00Z`；
- 9小时：Pass1、Pass2和RadarOnly整点对象全部缺失。

因此缺口不是单一机制：至少同时存在Pass1特有缺口和更广的生产/目录缺口。这个分类可以指导官方询证，但不能构造替代值。NOAA运行表确认Pass1是60分钟、20分钟延迟，Pass2是60分钟、一小时延迟，RadarOnly是2分钟更新的一小时累计；这些语义差异进一步禁止直接替换。

当前仍缺失不能证明对象最初从未在业务系统产生；未来若补回，也只证明当前桶发生晚到修复，不能证明历史预测原点可用。冻结全目录的`full_2022_2025_catalog_coverage=fail`和`historical_input_time_availability=fail`均不变。下一步应准备但不擅自发送NOAA/NCEP官方outage/backfill/首次发布时间/Pass1版本与修订询证包，并独立冻结MRMS网格到流域面积聚合、地形支撑和代表性误差协议。value protocol、forcing、训练、通用Kernel/GWM和K0仍保持关闭。

### 12.11 NOAA/NCEP MRMS官方询证包

已把12.9和12.10剩余的外部证据缺口转化为可人工审阅、但严格未发送的官方询证包：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_official_evidence_request_protocol.json`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_official_evidence_request_report.json`；
- 人工可读正文：`benchmarks/gwm_bench_v0_3_candidate/mrms_official_evidence_request.md`；
- RFC 822草稿：`benchmarks/gwm_bench_v0_3_candidate/mrms_official_evidence_request.eml`；
- 官方页采集器：`scripts/fetch_gwm_mrms_official_evidence_request.py`；
- 询证包生成器：`scripts/build_gwm_mrms_official_evidence_request.py`；
- 测试：`data_agent/test_build_gwm_mrms_official_evidence_request.py`；
- 正式原始页：`data/gwm_bench_v0_3_candidate/mrms_official_evidence_request/raw/20260722T144000Z/`。

协议自哈希为`3c64a06d7a9194de45a83906250a982aeba1c48ad1350cc3a5d53aaef61cf397`，绑定MRMS全时段目录报告、缺口归因协议/报告/manifest以及NOAA产品表、产品页和开放数据注册页。完整`urban-data-seeker`把来源路由到NOAA；由于站点型`noaa-weather`工具不采集MRMS运行支持页面，正式证据使用两个官方NSSL HTML入口，且只允许2个HTML请求、最多1 MB、禁止附件/数据资产和外部发送。

两页正式采集2/2成功，共`2833`字节，正文和manifest哈希均通过。当前官方页面验证：

- NCEP通过HTTP和LDM提供实时运行MRMS产品；
- `idp-support@noaa.gov`是一般MRMS问题路由；
- `sdm@noaa.gov`与`nco.ops@noaa.gov`是outage或operational issue路由。

最后两个地址只被验证为运行问题转介，不被宣称为历史档案责任人；当前负责2022--2025历史记录的正式owner仍未验证。询证包定义六个非补偿合同：

- `MRMS-COV-1`：20个精确对象是未生产、归档遗漏、删除、损坏还是后续补载，以及是否存在规范替代档案；
- `MRMS-PUB-1`：标称对象时间、首次业务/公开可用时间、重新发布和当前S3 `LastModified`的区别及记录；
- `MRMS-SEM-1`：一小时累计区间标签、Pass1输入、Pass1/Pass2差异和修订/替换规则；
- `MRMS-VER-1`：2022--2025软件、算法、产品定义和批量迁移/补载的有效期；
- `MRMS-GRID-1`：CRS、地球模型、维度、原点、轴序、分辨率、cell-center和mask语义；
- `MRMS-USE-1`：原始对象、内部研究、派生流域聚合与模型特征的使用/再分发及署名条款。

邮件草稿只将`idp-support@noaa.gov`放入`To`，没有Cc；两个outage地址作为未收件的转介候选保留。EML带`X-Unsent: 1`，授权收件人数组为空，`dispatch_authorized=false`、`external_message_sent=false`。未得到用户明确发送授权前，不得打开邮件客户端或调用任何发送接口。

六个合同当前全部为`pending_official_response`。普通或未版本化邮件解释只能帮助转介；要通过门，仍需绑定官方publisher、record identifier、version、date和effective scope。询证包本身不是科学证据，不得修改冻结报告、开启value protocol或放行forcing/训练。下一条本地可执行主线是冻结MRMS网格到流域的面积聚合、地形支撑与代表性误差协议；K0继续`fail_closed`。

### 12.12 MRMS流域空间预准入合同

已完成上一节指定的本地可执行主线，并继续保持零MRMS栅格值访问：

- 合同：`benchmarks/gwm_bench_v0_3_candidate/mrms_basin_spatial_prevalue_contract.json`；
- 评估报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_basin_spatial_prevalue_report.json`；
- 独立评估器：`scripts/assess_gwm_mrms_basin_spatial_prevalue.py`；
- 测试：`data_agent/test_assess_gwm_mrms_basin_spatial_prevalue.py`。

合同自哈希为`d8e711fc534907cdd5c8fc35e4c74755eddab3217f5228eeae77af99c769a390`。它不是取值许可，而是在任何MRMS值进入进程前冻结三阶段空间准入方法：A阶段绑定官方网格并生成流域cell crosswalk和面积权重；B阶段绑定版本化DEM、等面积高程分层以及雷达覆盖/质量支撑；C阶段先裁决独立参考元数据，再冻结代表性误差指标和数值门槛。三阶段全部是非补偿门，空间方法通过也不能补偿对象目录或历史发布时间失败。

目标支撑几何已经独立重放通过。USGS`11462000`上游流域为有效Polygon，测地面积`277.565037 km2`，`EPSG:32610`投影面积`277.343686 km2`，相对差`0.000797474`，低于预先冻结的`0.005`上限；controlled-release点位于流域内，Ukiah站位于流域外。该几何仍是控制边界上游汇水区，不是release至Hopland之间的下游增量汇水区，不能混淆两种空间支持语义。

A阶段已冻结但尚未物化的规则包括：

- 只能从有版本和有效期的官方MRMS网格变换及维度构造完整cell polygon；
- 只选择与流域具有严格正面积交叠的cell，边界cell必须裁切到流域；
- 面积和权重在`EPSG:32610`计算，禁止经纬度平方、centroid或bbox捷径；
- 投影流域覆盖率至少`0.999999`，权重和绝对误差不超过`1e-9`，重复交叠面积率不超过`1e-9`；
- 网格版本变化必须生成独立权重集，所有权重必须在读取降水值前冻结；
- 任一交叠cell为missing或no-coverage时，整个流域小时不可用；禁止对剩余权重重归一化，也禁止Pass2、RadarOnly、最近cell、空间填补或时间插值替代。

当前`MRMS-GRID-1`仍为`pending_official_response`，因此精确grid transform、维度和有效期未获正式证据，cell crosswalk和空间权重均未生成。合同只绑定了官方missing code `-1`和no-coverage code `-3`的现有证据；不能从“名义1 km”反推精确网格。

B阶段仍阻塞：尚未绑定权威发布者、不可变版本、水平CRS/分辨率、垂直基准、空洞/水体策略和全流域覆盖均明确的DEM；四个等面积高程分层没有物化；也没有绑定跨2022--2025有效、可映射到Pass1 cell的官方雷达覆盖或质量字段。不得从名义空间分辨率推断地形或波束遮挡代表性。

C阶段也仍阻塞。CDEC六站联合覆盖只有`20467/35064 = 0.583704`，且其是否参与MRMS Pass1输入尚未证明独立，不能作为主参考；Ukiah只保留`nearby_point_cross_check_only`；NLDAS只保留`retrospective_cross_check_only`。尚无满足流域支撑、四个高程层、至少0.95联合覆盖且不属于已知MRMS输入的独立参考元数据。小时bias/MAE/RMSE、湿小时检测、累计相对偏差、高程分层误差和固定seed的24小时block bootstrap指标已列入v2待冻结清单，但数值阈值尚未设定，也严禁根据随后观察到的MRMS误差反推阈值。

评估器状态为`spatial_prevalue_method_frozen_grid_terrain_reference_blocked`。`prevalue_method_contract_complete=true`仅表示方法边界冻结；`full_2022_2025_pass1_object_coverage=fail`和`historical_input_time_availability=fail`不变，`mrms_raster_values_read=false`，流域forcing、训练输入、通用Geospatial Kernel和通用GWM仍全部为false。K0保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

下一步只能按顺序推进：取得`MRMS-GRID-1`版本化官方记录后生成精确cell crosswalk和版本化面积权重；另建元数据优先的DEM及雷达质量证据合同；找到并先裁决流域内独立参考源；最后在读取任何MRMS或参考值前冻结v2代表性误差数值门槛。任何一步都不得绕过全目录覆盖和历史输入时可用性的既有失败。

### 12.13 DEM与雷达质量元数据筛选

已把12.12的B阶段从抽象待办推进为第二份值盲元数据合同，仍未读取DEM、RQI或MRMS Pass1的任何栅格值：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_spatial_support_metadata_screening_protocol.json`；
- 采集器：`scripts/fetch_gwm_mrms_spatial_support_metadata.py`；
- 评估器：`scripts/assess_gwm_mrms_spatial_support_metadata.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_spatial_support_metadata_screening_report.json`；
- 测试：`data_agent/test_assess_gwm_mrms_spatial_support_metadata.py`；
- 原始元数据：`data/gwm_bench_v0_3_candidate/mrms_spatial_support_metadata_screening/raw/20260722T152500Z/`。

协议自哈希为`97019eb75651ae44cf55e71e0fecc961119061f89d6077ca6cb52c908bfce0e6`，绑定12.12空间预准入合同/报告、原MRMS筛选manifest及官方运行产品表。它冻结8个请求、每个最多2 MB、累计最多8 MB：4个NASA CMR集合/粒度JSON以及4个NOAA S3 `ListObjectsV2`目录XML。禁止跟随CMR granule资产链接、下载DEM、对RQI执行GET/HEAD/Range、访问Pass1对象、读取栅格值、物化cell crosswalk/高程层或forcing/training panel。

本轮使用完整的`urban-data-seeker`路由。DEM按数据类型由`nasa-earthdata-cmr`处理，使用`SRTMGL1 v003`作为版本化候选。确定性路由器曾因查询词`resolution`把`legistar-platform`排到前面；这属于词法误命中，已按skill的“数据类型优先”规则明确拒绝。RQI属于bundle没有专用adapter的水文/雷达质量数据；`noaa-weather`只覆盖CDO/LCD站点，不能冒充MRMS适配器，因此采用平台fallback后的NOAA原生运行表和公开S3目录元数据。所有skill输出仅是来源路由，不是科学准入。

正式采集8/8成功，合计`1057307`字节，所有正文和manifest哈希经独立评估器复核。manifest明确记录`cmr_granule_asset_links_followed=false`、`dem_assets_downloaded=false`、`rqi_objects_downloaded=false`、`mrms_pass1_objects_downloaded=false`和`raster_values_read=false`。

DEM候选得到部分、但不足以准入的正证据：NASA CMR识别集合`C2763266360-LPCLOUD`、revision `39`、`SRTMGL1`版本`003`及DOI `10.5067/MEASURES/SRTM/SRTMGL1.003`。集合元数据的水平参考为Geographic Latitude and Longitude，公布分辨率为约`30 m`，组合geodetic string为`WGS84/EGM96`；Version 3摘要还明确说明使用已有地形数据填补早期SRTM空洞。目标流域包围盒命中两个正式粒度：`N39W124.SRTMGL1.hgt`和`N39W123.SRTMGL1.hgt`，其官方矩形footprint并集对USGS完整Polygon覆盖率为`1.0`，不是仅把bbox相交误写成覆盖。

这仍不能放行DEM。冻结元数据没有独立的vertical datum字段，也没有明确高程单位或水体处理策略；两条可下载granule URL均位于`lp-prod-protected`，本轮未跟随，CMR集合的`AccessConstraints: None`也不能自动替代逐资产访问/复用裁决。因此`dem_vertical_datum_units_void_and_water_policy=fail`、未来内部获取和复用边界为`indeterminate`、`dem_metadata_admitted=false`。不得把`WGS84/EGM96`组合字符串或HGT后缀扩展解释成已通过的垂直基准和单位合同。

RQI也得到部分正证据。现有NOAA运行表正式列出`RadarQualityIndex`为`2-min`、`non-dim`、missing=`-1`、no-coverage=`-3`。`2022-01-01`、`2023-01-01`、`2024-01-01`和`2025-12-31`四个目录各有严格`720/720`个唯一、正大小对象，按2分钟从`00:00:00`连续至`23:58:00`，没有分页。这通过的是候选身份、频率、单位、代码和四个代表日目录存在性，不是质量适用性。

官方表未在冻结证据中说明RQI与beam blockage、range degradation或覆盖质量的物理关系；四天目录也不能证明整个`2022--2025`有效期；`MRMS-GRID-1`仍未关闭，因此不能建立RQI到Pass1 cell的兼容性或crosswalk。故`radar_quality_physical_quality_semantics=fail`、`radar_quality_full_period_effective_interval=fail`、`radar_quality_pass1_grid_crosswalk=fail`，`radar_quality_metadata_admitted=false`。

评估状态为`metadata_screen_complete_candidates_partially_supported_not_admitted`。这一步使“DEM身份/水平参考/流域footprint”和“RQI身份/2分钟目录”成为可复核的正证据，但没有改变B阶段总门的`terrain_dem_and_strata=fail`与`radar_coverage_or_quality_support=fail`，更不改变A阶段`MRMS-GRID-1`、全目录覆盖、历史输入时可用性或C阶段独立参考的失败。`spatial_forcing_model_input_admitted=false`、训练、通用Geospatial Kernel、通用GWM和K0的`fail_closed`均保持不变。

下一步的允许范围也更具体：先对官方SRTM v3用户指南或等价版本化DEM记录建立新的元数据合同，专门绑定垂直基准/单位和水体策略；对RQI取得官方物理质量、有效期及与Pass1网格的关系记录；待`MRMS-GRID-1`通过后才可构造版本化cell crosswalk。上述元数据门全部通过前，仍不得请求任何DEM、RQI或Pass1栅格资产，也不得计算高程分层。

### 12.14 SRTM v3版本化文档证据

已完成12.13指定的第一项后续工作，将SRTM DEM的垂直基准、单位、水体和复用边界从推断问题变成版本化官方文档证据：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/srtm_v3_document_evidence_protocol.json`；
- 采集器：`scripts/fetch_gwm_srtm_v3_document_evidence.py`；
- 评估器：`scripts/assess_gwm_srtm_v3_document_evidence.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/srtm_v3_document_evidence_report.json`；
- 测试：`data_agent/test_assess_gwm_srtm_v3_document_evidence.py`；
- 正式原始文档：`data/gwm_bench_v0_3_candidate/srtm_v3_document_evidence/raw/20260722T161500Z/`。

协议自哈希为`6e58cf09c93a31bf67040773f27731b292137a2624a37a8bdd4107c4469e7a35`，在任何文档请求前冻结两个来自SRTMGL1 v003 CMR记录的官方链接：LP DAAC/USGS的SRTM Collection User Guide v3 PDF，以及NASA Earthdata Data Use and Citation Guidance。单响应上限12 MB、总量上限16 MB，只允许文档和PDF文本提取；DEM granule、RQI、Pass1、栅格值、高程分层及训练面板均被禁止。

正式成功前保留了两个访问失败边界：`20260722T154500Z`为PDF TLS握手超时、政策页成功的1/2 incomplete snapshot；`20260722T160500Z`为PDF在冻结时限内部分传输、政策页成功的1/2 incomplete snapshot。它们是访问诊断，不是文档科学失败，也没有合并正文。最终采集使用每次仍不超过冻结60秒的可恢复Range续传完成2/2，共`1209977`字节。正式PDF为`1071409`字节、SHA-256=`422d91fef5195706a596fe5fa759d638ad3b509f5f36d77b0382004b3b0aaac9`；提取文本为`40500`字节、SHA-256=`a8c297fc1b5933a42a4cd57d9a5a82068c869d6631674ed5575dfddd97eaa4dc`。所有原文、文本和manifest哈希均通过独立复核，DEM资产下载数仍为0。

七项冻结证据要求全部通过：

- 文档身份明确为SRTM Collection User Guide，覆盖Version 3.0与`SRTMGL1`；
- 明确写出高程单位为meters，参考`WGS84/EGM96 geoid`；
- `SRTMGL1`为1 arc-second、`3601 x 3601`、边界行列重叠的geographic经纬度tile；
- `.HGT`为two-byte 16-bit signed integer、Motorola big-endian、row-major；
- Version 1/2的void sentinel为`-32768`，Version 3.0明确为无void；
- Version 3 void先由ASTER GDEM2填补，不一致部分再用GMTED2010或美国境内NED填补，并由SRTMGL1N/NUM记录像元来源；
- 水体处理明确包含water-body leveling、coastline definition、海洋/湖泊按shoreline elevation平整、SWBD water mask及海岸0米处理。

NASA政策页的最终规范URL为`https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance`。页面说明NASA ESDIS开放访问；未标特别限制的NASA-led mission数据采用CC0，可复制和分发，但不得暗示NASA背书，应acknowledge NASA并引用具体dataset。结合CMR的`AccessConstraints: None`，SRTMGL1 v003的内部研究与复用元数据门通过；这不等于Earthdata受保护asset的认证访问已授权。

因此报告状态为`srtm_v3_document_evidence_complete_dem_metadata_admitted_assets_closed`，`dem_document_evidence_complete=true`、`dem_metadata_admitted=true`。这是B阶段的真实正进展，但边界仍严格：`dem_asset_acquisition_protocol_frozen=false`、`earthdata_asset_access_authorized=false`、`dem_assets_downloaded=false`、`dem_values_read=false`、`srtmgl1n_provenance_values_read=false`、`terrain_strata_materialized=false`。

DEM后续不能只取两块SRTMGL1 HGT。必须先冻结两块`N39W124/N39W123` SRTMGL1与对应SRTMGL1N NUM资产的身份、大小、校验和、认证收据、共同网格和逐像元来源语义；Version 3“无void”不等于无误差，填补区域来源异质，SRTM还是surface elevation而非当然的bare-earth DTM。只有DEM和NUM共同覆盖、解码并通过保守重采样合同后，才允许生成四个等面积高程层。

RQI物理质量语义、2022--2025有效期及Pass1网格兼容性仍失败；`MRMS-GRID-1`、20个Pass1目录缺口、历史输入时可用性和独立参考误差门也都没有被DEM文档补偿。因此流域forcing、训练、通用Geospatial Kernel、通用GWM和K0总体仍为`fail_closed`。

### 12.15 SRTM资产预检与认证协议冻结

已继续关闭12.14留下的“资产身份、精确字节和官方checksum”缺口，但严格停在认证下载之前。该工作分为三层，不能把后一层的协议冻结误写成资产已经取得。

第一层是公开CMR UMM-G资产预检：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/srtm_asset_preflight_protocol.json`；
- 采集器：`scripts/fetch_gwm_srtm_asset_preflight.py`；
- 评估器：`scripts/assess_gwm_srtm_asset_preflight.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/srtm_asset_preflight_report.json`；
- 测试：`data_agent/test_assess_gwm_srtm_asset_preflight.py`。

协议自哈希为`89530d166173e8226ca17d7a33fcf272d54db12647a59c9ed22be52e5cd9f399`。正式采集4/4成功、共`35429`字节，确认SRTMGL1N v003集合`C2763266368-LPCLOUD`，并对`N39W124`、`N39W123`各冻结一块HGT和一块NUM；HGT/NUM官方footprint完全一致，其并集对目标流域覆盖率为`1.0`。但UMM-G只给出正的MB小数，没有精确整数byte size或checksum，因此状态保持`pairing_verified_exact_bytes_and_checksums_missing_asset_protocol_blocked`，没有用换算值补门。

第二层只读取公开CMR ECHO10 XML：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/srtm_echo10_asset_metadata_protocol.json`；
- 采集器：`scripts/fetch_gwm_srtm_echo10_asset_metadata.py`；
- 评估器：`scripts/assess_gwm_srtm_echo10_asset_metadata.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/srtm_echo10_asset_metadata_report.json`；
- 测试：`data_agent/test_assess_gwm_srtm_echo10_asset_metadata.py`；
- 正式原始元数据：`data/gwm_bench_v0_3_candidate/srtm_echo10_asset_metadata/raw/20260723T015500Z/`。

协议自哈希为`fef02c992413083de0ec5baf6d06d536b65b3c86ad2d78011f29ee60f31f0dc1`。4/4响应成功、共`16649`字节；评估器只接受目标ZIP对应的`AdditionalFile`，明确排除browse image checksum。由此取得四个官方冻结资产：

| 资产 | 精确字节 | 官方SHA-256 |
|---|---:|---|
| `N39W124.SRTMGL1.hgt.zip` | 12,521,349 | `01d1c73814e1131aaece210b7060347a3d9b119dbeeaac3832adccf45ebe0e9f` |
| `N39W123.SRTMGL1.hgt.zip` | 12,379,652 | `6f0c48d0ac24ed339d530a11b25131dbc5b87c3b232649e9bb94f603b7d5ae70` |
| `N39W124.SRTMGL1N.num.zip` | 268,752 | `173bfeb23a8883e72737ff0906a8883541b58ace5818fe6eda5505e01ab302f4` |
| `N39W123.SRTMGL1N.num.zip` | 285,265 | `316a7c60ed673585bf755dd71c5a9a05a2eca3260b067132c72a470585cb630b` |

合计`25455018`字节。这里验证的是NASA官方元数据中的预声明checksum，不是下载后现算的digest；本轮仍未跟随任何`lp-prod-protected`链接。

第三层冻结独立的认证资产协议：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/srtm_authenticated_asset_protocol.json`；
- 评估器：`scripts/assess_gwm_srtm_authenticated_asset_protocol.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/srtm_authenticated_asset_protocol_report.json`；
- 测试：`data_agent/test_assess_gwm_srtm_authenticated_asset_protocol.py`。

协议自哈希为`93b39b3ed8829f8629e8b34e02d840097c7a7f602dc5c0b2560c175c1cf076ca`。评估器不仅复核四个上游文件哈希，还把每个资产的ID、tile、角色、collection、filename、精确字节、SHA-256和受保护URL逐项绑定回ECHO10报告。即使重新计算协议自哈希，替换资产元数据、自行打开下载授权或提前打开地形分层门也会被负例测试拒绝。

当前报告状态为`authenticated_asset_protocol_frozen_authorization_required_not_executed`。`dispatch_authorized=false`、`earthdata_asset_access_authorized=false`、`asset_download_allowed=false`、`earthdata_credentials_used=false`，执行计数为0次请求、0字节、0资产；token、header和cookie不得写入日志或manifest。未来即使得到单独明确授权，也必须先按预声明精确字节和SHA-256逐ZIP核验，再允许解压，随后完成HGT/NUM共同网格、边缘重叠和流域内逐像元来源验证，之后才可能读取目标流域值或生成四个等面积高程层。

这一步真正完成的是“可复核、可执行但尚未获准执行”的DEM/NUM获取合同，不是地形证据准入。`all_zip_hashes_verified=false`、`dem_values_read=false`、`num_values_read=false`、`joint_grid_validated=false`、`terrain_strata_materialized=false`。RQI三门、`MRMS-GRID-1`、20个Pass1缺口、历史输入时可用性和独立参考门仍失败。K0继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

### 12.16 SRTM HGT/NUM联合验证协议

在没有把“继续推进”解释成Earthdata下载授权的前提下，已进一步冻结资产取得后的联合验证规则。该步骤仍是纯本地、值前协议工作：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/srtm_hgt_num_joint_validation_protocol.json`；
- 评估器：`scripts/assess_gwm_srtm_hgt_num_joint_validation_protocol.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/srtm_hgt_num_joint_validation_protocol_report.json`；
- 测试：`data_agent/test_assess_gwm_srtm_hgt_num_joint_validation_protocol.py`。

协议自哈希为`ffc821413d8f5b897376065e1c260deb81d4d1c07f5254928ffbd26c4f3a843e`，哈希绑定认证资产协议/报告、SRTM v3文档报告和MRMS流域空间预准入合同。四个输入仍是12.15冻结的两块HGT和两块NUM，压缩总量`25455018`字节，按`3601 x 3601`和每个posting的字节宽度推导出的预期解压总量为`77803206`字节。

ZIP安全顺序被固定为：先核对完整压缩文件的精确字节和预声明SHA-256，四个全部通过后才允许读取任何ZIP中央目录。每个ZIP只能有一个预期的普通HGT或NUM成员；加密、符号链接、绝对路径、父目录穿越、重复成员、意外成员和持久化预解压都被禁止。成员声明大小必须先匹配，随后流式读取还必须通过CRC。下载后现算的digest不得替换ECHO10预声明digest。

科学解码合同被固定为：

- HGT为`3601 x 3601`、north-to-south row order、west-to-east column order、Motorola big-endian signed int16，单位meter，垂直参考`WGS84/EGM96 geoid`；
- Version 3的`-32768`计数必须为0，不能因为官方称void-free就跳过实测检查；
- NUM为同一posting网格的uint8逐点来源信息，只允许官方显式码`1,2,5,11,21,25,31,51,52,53,72`以及ASTER scene count `101--200`、SRTM swath count `201--224`；未知码使整块tile失败；
- 每块HGT与NUM必须shape和posting坐标完全一致；`N39W124`东列与`N39W123`西列的HGT和NUM都必须逐值相同，拼接时共同边界只保留一份；
- 任一ZIP、shape、void、来源码、HGT/NUM配对或共同边界检查失败，都非补偿性地阻断联合验证证书。

这里特别关闭了一个容易被传统栅格处理掩盖的概念错误：SRTM的1 arc-second记录是sample posting，不能未经面积模型直接当作等面积cell。该协议不允许读取目标流域子集或生成高程层；必须另行、且在看到目标流域高程值之前，冻结posting-to-area支撑单元、投影面积、边界裁剪、共享posting去重和四个等面积weighted-quantile strata算法。最近邻面积汇总和经纬度平方权重均被禁止。

报告状态为`joint_validation_protocol_frozen_assets_unavailable_authorization_required_not_executed`，本次打开0个archive、读取0个压缩字节、0个解压字节、0个HGT值和0个NUM值。`earthdata_asset_access_authorized=false`、`assets_downloaded=false`、`joint_grid_validated=false`、`terrain_area_support_protocol_frozen=false`和`terrain_strata_materialized=false`。因此该协议提升的是未来执行的可证伪性和防泄漏性，不改变RQI、MRMS、forcing、训练、通用Geospatial Kernel、通用GWM或K0的`fail_closed`结论。

### 12.17 SRTM posting-to-area与四层高程算法冻结

已完成12.16要求的独立值前面积支撑协议，并提供不接触真实资产的纯数学参考实现：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/srtm_terrain_area_support_protocol.json`；
- 评估器：`scripts/assess_gwm_srtm_terrain_area_support_protocol.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/srtm_terrain_area_support_protocol_report.json`；
- 参考实现：`scripts/gwm_srtm_terrain_area_math.py`；
- 协议测试：`data_agent/test_assess_gwm_srtm_terrain_area_support_protocol.py`；
- 数学测试：`data_agent/test_gwm_srtm_terrain_area_math.py`。

协议自哈希为`c2377c5542f82267ec89fa5dda6146e003916698a0361870273b4c633b331acb`，参考实现SHA-256为`c337977ad31f116e21bd608c19107430ddade40514f46e33ca72a3d27cf02f8d`。协议同时绑定12.16联合验证协议/报告、MRMS流域空间预准入合同/报告及原始USGS流域GeoJSON。任何参考算法代码漂移都会使协议评估失败。

两块`3601 x 3601`源tile在已验证共同列只保留一次后，形成唯一`3601 x 7201`posting mosaic。全局坐标被固定为`latitude = 40 - row/3600`、`longitude = -124 + column/3600`。USGS `11462000`流域bounds为`[-123.202867551, 39.166109828, -122.993739112, 39.39918691]`，严格位于两块tile最外posting中心以内，并留有超过半个posting的外边距；若未来目标几何不满足该条件，必须补相邻tile，不能把外侧支撑截断。

posting-to-area方法固定如下：每个唯一posting在`OGC:CRS84`中取得由相邻posting中点界定的轴对齐Voronoi矩形，即经纬方向各半宽`1/7200`度。该矩形和官方流域以`always_xy`轴序转换到`EPSG:32610`，最终候选必须与流域产生严格正的投影面积交集，并逐单元裁剪。bbox仅可作为空间索引预筛，posting中心落入、bbox落入、degree-squared面积、最近邻重采样以及双线性/三次高程插值均不得作为最终面积方法。所有裁剪面积之和对投影流域面积的相对容差为`1e-9`，覆盖率至少`0.999999`，重复面积比例最多`1e-9`。

四个等面积高程层不采用简单未加权像元分位数。算法按`HGT meter、global row、global column`稳定排序，以每个posting支撑单元在流域内的投影交叠面积为权重，每层目标面积为投影流域面积的四分之一。若一个边界单元跨过25%配额，只把该单元的membership area分到相邻两层，不拆改或插值高程；每个支撑单元最多进入两层。同高程按row/column稳定排序，不增加epsilon或jitter，因此相邻层边界高程允许相同。最后只允许吸收浮点残差，分层面积和总membership面积均按`1e-9`相对容差核验。

水面posting仍计入完整流域面积，但必须分别报告water、land及ASTER/GMTED/NED/SRTM等NUM来源的面积比例。任何void或未知NUM码都使整个流程失败，不得删点后重归一化。SRTM仍表述为surface elevation rank strata，不得升级表述为bare-earth地貌层。

纯数学实现不接受文件或网络输入，合成测试已验证共同列映射、坐标和半posting边界、跨层面积拆分、同高程稳定顺序、每层面积守恒、重复key、非正面积、NaN、大于单层配额和越界索引拒绝。本轮协议与数学专项共`18 passed`。

报告状态为`terrain_area_support_protocol_frozen_joint_certificate_unavailable_not_executed`：物化0个支撑几何、0个地形值、0个DEM/NUM/MRMS读取，输出路径仍为`null`。这关闭的是面积模型和分层算法选择，不是地形证据门；只有获得授权资产、联合验证证书并按本协议实际物化后，`terrain_dem_and_strata`才可能改变。RQI、`MRMS-GRID-1`、20个Pass1缺口、历史输入时可用性及独立参考仍各自非补偿性失败，GWM、TWM、UWM边界和K0总体`fail_closed`不变。

### 12.18 MRMS网格与RQI官方源码证据

已沿`MRMS-GRID-1`和RQI两条剩余主线完成一轮固定commit、固定path、固定Git blob的官方文档/源码裁决，仍未接触任何MRMS栅格资产：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_grid_rqi_document_evidence_protocol.json`；
- 采集器：`scripts/fetch_gwm_mrms_grid_rqi_document_evidence.py`；
- 评估器：`scripts/assess_gwm_mrms_grid_rqi_document_evidence.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_grid_rqi_document_evidence_report.json`；
- 测试：`data_agent/test_assess_gwm_mrms_grid_rqi_document_evidence.py`；
- 正式快照：`data/gwm_bench_v0_3_candidate/mrms_grid_rqi_document_evidence/raw/20260723T030500Z/`。

协议自哈希为`d8e62771afd8f50bbb2797ec769a964b4f93462ace52f12f19f6cf8ffc623061`。完整`urban-data-seeker`仍作为顶层来源路由器；由于`noaa-weather`只实现NCEI/CDO/LCD站点数据，不实现MRMS网格，本轮采用`document-portal-platform` fallback，再落到两个原生官方来源：NSSL的`mrms-support`和EMC的`NCEPLIBS-g2c`。skill只决定来源，不构成科学准入。

正式协议冻结9个请求、单响应最多2 MiB、累计最多6 MiB，并绑定：

- `NOAA-National-Severe-Storms-Laboratory/mrms-support` commit `3edf7c25f503f81a12eb179dbbd3d4dae607e477`；
- `NOAA-EMC/NCEPLIBS-g2c` commit `67a2500f47612846c25ece791e18ca0fde151218`；
- README、v11.5.5/v12.0/v12.2 User Table、CMake测试定义、`tst_mrms.c`和`g2cfile.c`共7个Git blob SHA。

协议明确禁止对RQI、Pass1、Pass2和测试GRIB2执行GET/HEAD/Range，禁止请求任何raster asset、读取栅格值、物化cell crosswalk/空间权重/forcing panel，也禁止发送外部消息。沙箱DNS的`0/9`和直连的`5/9`快照都保留为incomplete传输审计，未并入科学证据。最终代理快照`9/9`成功，共`137014`字节；9个响应正文哈希和7个Git blob身份均由评估器独立复核。

RQI证据纠正了发现阶段的一项错误假设：RQI并非只在v12表中出现。v11.5.5、v12.0和v12.2三张固定版本官方表都包含完全一致的：

- discipline/category/parameter=`209/8/0`；
- name=`RadarQualityIndex`；
- frequency=`2-min`；
- unit=`non-dim`；
- missing=`-1`；
- no coverage=`-3`；
- description=`Radar Quality Index`。

NSSL运行页说明当前为MRMS v12.2，并将表迁移到GitHub的日期标成`2024-07-18`。但版本文件名和资料迁移日期都不是运行生效日期，不能据此构造2022--2025版本区间。三张表也都没有说明beam blockage、range/beam-height degradation、公式、数值解释或质量阈值。因此`rqi_identity_frequency_unit_and_codes=pass`，捕获版本间身份连续性也为`pass`；`rqi_physical_quality_semantics=fail`和`rqi_2022_2025_effective_interval=fail`不变。

网格证据来自NOAA-EMC在2023-08-03合并的官方commit。CMake把样本绑定到NOAA EMC公开测试目录，文件名为`MRMS_MultiSensor_QPE_24H_Pass2_00.00_20230621-110000.grib2`。`g2cfile.c`的维度构造只在`grid_def case 0`生成Latitude/Longitude数组，即Section 3 Grid Definition Template 3.0 regular latitude/longitude；`tst_mrms.c`对该样本声明：

- 纬度维`3500`，经度维`7000`；
- 纬度首末值`54.995`至`20.005`度；
- 纬度坐标增量绝对值`0.01`度；
- 源码测试中的经度首末值为`230.004992`至`160.014992`度，解码器按递减方向生成，增量绝对值`0.01`度。

这些是固定源码对单个2023 Pass2样本的预期，不是本benchmark对GRIB2 Section 3的实际解码。本轮没有请求测试GRIB2。模板、维度和纬度轴可记为source-level `pass`；经度序列不能未经证据自行做模360归一化或方向修复。捕获源码也没有暴露该样本的earth-shape和scanning-mode字段，未定义坐标表示cell center还是cell edge，更没有把Pass1和RQI绑定到同一版本网格。

因此以下门仍为非补偿失败：

- `named_2023_pass2_longitude_geospatial_interpretation=fail`；
- `named_2023_pass2_earth_shape_and_cell_support_convention=fail`；
- `pass1_and_rqi_grid_compatibility=fail`；
- `mrms_grid_1=fail`；
- `radar_coverage_or_quality_support=fail`。

报告状态为`official_document_source_complete_partial_grid_rqi_support_mrms_grid_1_failed`。`official_document_snapshot_complete=true`、`rqi_identity_metadata_admitted=true`、`mrms_grid_dimensions_partially_supported=true`，但`mrms_grid_1_admitted=false`、`pass1_rqi_grid_compatibility_admitted=false`、`cell_crosswalk_materialized=false`、`spatial_weights_materialized=false`、`mrms_raster_values_read=false`。专项测试`6 passed`。

下一步证据需求被压缩为三项：取得覆盖2022--2025的官方版本生效记录；取得明确说明波束遮挡、距离/波束高度影响及数值解释的RQI算法定义；取得每个适用Pass1/RQI版本不可变的Section 3记录，包含earth shape、scanning mode、完整经纬轴和cell支撑约定。在这些记录全部通过前，不得请求MRMS栅格资产或生成流域cell crosswalk。K0继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

### 12.19 MRMS版本变更点与RQI历史证据

已继续沿`K0-DATA-FORCING-ADMISSION`主线完成MRMS版本时间线与RQI变更证据链。边界保持不变：GWM是跨领域地理空间世界模型及共享契约，TWM是国土/土地系统领域实例，UWM是城市系统领域实例，HydroControl只是GWM Kernel验证适配器，不是GWM本体。本轮仍未请求任何MRMS RQI/Pass1/Pass2对象，未读取栅格值，也未物化cell crosswalk或空间权重。

新增正式产物：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_version_rqi_change_evidence_protocol.json`；
- 采集器：`scripts/fetch_gwm_mrms_version_rqi_change_evidence.py`；
- 评估器：`scripts/assess_gwm_mrms_version_rqi_change_evidence.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_version_rqi_change_evidence_report.json`；
- 测试：`data_agent/test_assess_gwm_mrms_version_rqi_change_evidence.py`；
- 正式快照：`data/gwm_bench_v0_3_candidate/mrms_version_rqi_change_evidence/raw/20260723T041500Z/`。

协议canonical SHA-256为`7b284da6f4e90ad5be99e1a4961821bfee33b96d13226efb376ccac3f9461857`。完整`urban-data-seeker`仍作为顶层来源路由器；由于`noaa-weather`不覆盖MRMS版本通知和解码器历史，本轮继续选择`document-portal-platform` fallback，再落到NWS Service Change Notices和NOAA-EMC/wgrib2原生官方来源。skill只负责来源路由，不构成科学准入。

协议在采集前冻结9个请求：NWS通知索引、SCN25-46和SCN26-07两份PDF，以及wgrib2在2020、2023、2025的3个固定commit和3个固定Git blob。两份PDF的原始SHA-256预先声明；`pdftotext -layout`派生文本的工具版本、路径、字节数和SHA-256进入manifest。单响应上限1 MiB、累计上限4 MiB。正式快照`9/9`成功，原始响应共`1,615,390`字节，两份PDF和三份Git blob均通过独立校验。

SCN25-46给出第一条真正的业务生效时间证据：MRMS v12.3.0于`2025-08-05`“on or about”生效。通知明确写明Radar Quality Index将被修改，以改善暖季Multi-Sensor QPE产品性能。因此：

- `v12_3_effective_change_point=pass`；
- `rqi_warm_season_qpe_role=pass`；
- 2025-12-31不能继续使用v12.2语义，`2025_12_31_may_use_v12_2_semantics=fail`。

必须保留一个重要的非合并边界：SCN25-46第5项是RQI及暖季QPE改进，第6项才是QC对ground clutter和beam blockage的改进。它们是两个独立发布条目，不能拼接成“RQI公式包含beam blockage”或“RQI数值直接表示beam blockage”。通知也没有给出RQI公式、尺度方向、数值含义或质量阈值。因此`rqi_formula_and_numeric_interpretation=fail`、`rqi_beam_blockage_relation=fail`。

SCN26-07将v12.3.1生效时间固定为`2026-02-04`，捕获的补丁范围是VCP 212/215下的MPDA处理和KLGX雷达处理，没有明确RQI变更。但“补丁未提RQI”不能反推RQI语义稳定，也不能补足2022--2024版本时间线。

NOAA-EMC/wgrib2的固定源码进一步证明RQI解码身份具有长期连续性：

- 2020 commit `3203dc7be4f5ac699ab6a06a0283f670c55af830`，blob `948e53ff1ba8a82ac28d7848b1c9cfb8cfd98194`；
- 2023 commit `133b5050196763825009375042f4fb34e8c19570`，同一blob迁移到新路径；
- 2025 commit `7000c709de5dd0a2278cbef341a16b7d794530bc`，blob `d067eb1c378b8838f9ef7960f996466c6b671b3d`。

三份表都只有一条完全相同的`RadarQualityIndex`解码行，因此`rqi_long_lived_decoder_identity=pass`。但commit日期只是源码时间，不是MRMS业务版本生效日期；解码器存在不证明业务生产；解码行不变也不证明上游RQI算法或数值语义不变。故`full_2022_2025_version_timeline=fail`仍然成立。

报告状态为`official_notice_decoder_history_complete_v12_3_change_supported_full_timeline_and_rqi_semantics_failed`。新增三个正证据门通过，但`pass1_and_rqi_grid_compatibility=fail`、`mrms_grid_1=fail`和`radar_coverage_or_quality_support=fail`没有改变。`mrms_raster_values_read=false`、`cell_crosswalk_materialized=false`、`spatial_forcing_model_input_admitted=false`、`general_geospatial_kernel_validated=false`。专项测试`7 passed`，MRMS/SRTM/NWM forcing/K0/Kernel readiness整链回归`132 passed`。

下一步按非补偿顺序继续：先补齐2022--2024每个适用MRMS版本的官方实施日期；再取得版本化RQI算法文档，明确公式、尺度方向、数值解释、阈值策略以及beam blockage是否和如何进入RQI；同时取得每个适用Pass1/RQI版本不可变的Section 3元数据，覆盖earth shape、scanning mode、完整轴和cell支撑约定。以上门全部通过前，仍不得请求MRMS栅格资产或生成流域crosswalk。K0固定结论继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

### 12.20 MRMS完整版本日线与v12.2 RQI物理语义

在12.19的v12.3变更点证据之后，已继续完成第二条正式文档证据链，将“完整版本时间线”和“版本化RQI语义”拆开裁决。新增产物：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_timeline_rqi_semantics_evidence_protocol.json`；
- 采集器：`scripts/fetch_gwm_mrms_timeline_rqi_semantics_evidence.py`；
- 评估器：`scripts/assess_gwm_mrms_timeline_rqi_semantics_evidence.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_timeline_rqi_semantics_evidence_report.json`；
- 测试：`data_agent/test_assess_gwm_mrms_timeline_rqi_semantics_evidence.py`；
- 正式快照：`data/gwm_bench_v0_3_candidate/mrms_timeline_rqi_semantics_evidence/raw/20260723T044130Z/`。

协议canonical SHA-256为`47982648d0cc95c3fcec3d675ebf25a5f1909fa50016f45745b0bd91d8eba54e`。冻结时间为`2026-07-23T04:32:00Z`，早于正式manifest的`2026-07-23T04:41:32Z`。协议冻结6个请求：NSSL MRMS build timeline、current/past code updates、NOAA WDTD RQI产品指南、v12.2的SCN21-27 PDF和NWS v12.2 supplemental页。正式快照`6/6`成功，原始响应`328,201`字节，SCN PDF原始哈希和派生文本哈希均通过。仍未请求RQI/Pass1/Pass2对象，未读取任何栅格值。早先时间戳顺序不一致的`20260723T044500Z`快照不进入科学证据。

NSSL build timeline明确声明，表内日期是每个MRMS build在NCEP Central Operations“made operational”的日期。因此2022-01-01至2025-12-31可在operational-day精度下完整分段：

- v12.1.0：`2022-01-01`至`2022-04-21`；
- v12.2.0：`2022-04-22`至`2023-11-27`；
- v12.2.6：`2023-11-28`至`2025-08-04`；
- v12.3.0：`2025-08-05`至`2025-12-31`。

这里保留一个不可静默修复的边界差异：SCN21-27宣布v12.2在`2022-04-21T16:00:00Z`“on or about”生效，而NSSL将实际运行日记录为`2022-04-22`。因此`full_2022_2025_version_timeline=pass`只表示日级覆盖已闭合，`v12_2_transition_subdaily_exact=false`仍明确记录；不能伪造一个更精确的切换时刻。

WDTD指南明确标注`Latest Update: MRMS Version 12.2`，并给出：

- 顶层组成：`RQI = RQI_blk * RQI_hgt`；
- RQI随beam blockage增加、beam height升高而降低，对应QPE不确定性增大；
- `RQI_blk`在遮挡不超过10%时为1，超过50%时为0，中间为线性函数；
- `RQI_hgt`考虑波束轴高度、宽度、freezing level、bright band厚度及相对位置，特定bright-band情形属于指数函数；
- v12输出精度从0.1提高到0.01，Multi-Sensor QPE将RQI用作radar QPE输入权重。

因此以下门从失败提升为通过：

- `v12_2_rqi_top_level_composition=pass`；
- `v12_2_rqi_numeric_quality_direction=pass`；
- `v12_2_rqi_beam_blockage_component=pass`；
- `rqi_beam_blockage_relation=pass`。

但指南没有给出版本化`RQI_hgt`指数方程的完整参数，更重要的是它只覆盖v12.2，而SCN25-46已经证明v12.3在2025-08-05修改了RQI。不得把v12.2公式直接投射到v12.3。因此：

- `v12_2_rqi_hgt_exact_equation=fail`；
- `v12_3_exact_rqi_semantics=fail`；
- `full_2022_2025_rqi_semantic_continuity=fail`。

报告状态为`official_timeline_and_v12_2_rqi_semantics_supported_v12_3_semantics_and_mrms_grid_1_failed`。时间线和v12.2物理语义的关键缺口已经关闭，但这些证据仍不提供Section 3 earth shape、scanning mode、cell-center/edge支撑或Pass1/RQI版本化同网格绑定。故`pass1_and_rqi_grid_compatibility=fail`、`mrms_grid_1=fail`、`radar_coverage_or_quality_support=fail`不变，crosswalk和权重仍为零。

本轮第二条专项测试`7 passed`，两条新增证据链及MRMS/SRTM/NWM forcing/K0/Kernel readiness合并回归`139 passed`。GWM仍是跨领域共享世界模型与Kernel契约，TWM/UWM仍是领域实例，HydroControl仍只是验证适配器。K0固定结论继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

下一步优先级已经收敛：第一，取得v12.3 RQI算法记录，明确修改后的公式、参数、尺度方向和数值解释；第二，如未来需要从组件重构或设阈值，取得`RQI_hgt`的完整版本化指数方程；第三，取得每个适用Pass1/RQI版本不可变的Section 3元数据并明确同网格绑定。在这些门通过前，仍不得请求MRMS栅格资产或物化流域cell crosswalk。

### 12.21 v12.3 RQI变化方向与科学材料证据

已继续沿v12.3 RQI精确语义门完成第三条正式证据链。新增产物：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_v12_3_rqi_scientific_evidence_protocol.json`；
- 采集器：`scripts/fetch_gwm_mrms_v12_3_rqi_scientific_evidence.py`；
- 评估器：`scripts/assess_gwm_mrms_v12_3_rqi_scientific_evidence.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_v12_3_rqi_scientific_evidence_report.json`；
- 测试：`data_agent/test_assess_gwm_mrms_v12_3_rqi_scientific_evidence.py`；
- 正式快照：`data/gwm_bench_v0_3_candidate/mrms_v12_3_rqi_scientific_evidence/raw/20260723T050320Z/`。

协议canonical SHA-256为`7a8254cdb8b2f50cb919cf10415b2e7caaf03d61a40d2ef640d5f980d5e22dbf`，冻结于`2026-07-23T05:00:00Z`，早于正式manifest的`2026-07-23T05:04:37Z`。协议冻结6个请求：NSSL 2025/2026 MRMS会议目录、两条AMS公开摘要API、NOAA/NSSL作者的2026 Radar QPE讲义PDF和NWS v12.3 supplemental页。正式快照`6/6`成功，共`4,570,003`字节；讲义PDF为`4,427,879`字节，原始SHA-256 `ded01ecb47bfb4a41fd11dcfb1fca03626ebd7d7ea28746a580a0be5f5703186`，派生文本也单独哈希。

证据来源角色被严格限定：NSSL官方目录把AMS材料绑定到NOAA/NSSL作者和MRMS QPE研究项目，因此可作为算法背景与变化方向的科学证据；它们不能替代NWS SCN的业务生效日期。正式运行没有栅格化任何讲义页面、没有数字化曲线，也没有请求MRMS RQI/Pass1/Pass2对象或读取栅格值。

2025摘要明确描述了“revised approach to calculating the Radar Quality Index”，目的是改善Multi-Sensor QPE中radar-derived precipitation coverage的保留，并改进跨季节和降水机制的数据融合。2026讲义进一步明确：

- 该组更新于2025年8月进入MRMS v12.3运行；
- RQI refinement用于提高暖季深对流条件下radar data对Multi-Sensor QPE的影响；
- 更新后的RQI允许远雷达距离处更多radar QPE进入Multi-Sensor QPE；
- 曲线的定性自变量包括radar range和0°C height；
- 同一标注位置`36.16N, 115.40W`的示例从v12.2 `RQI=0.02`变为v12.3 `RQI=0.11`。

因此新增通过门：

- `v12_3_rqi_change_direction=pass`；
- `v12_3_rqi_warm_season_deep_convection_role=pass`；
- `v12_3_rqi_far_range_retention_role=pass`；
- `v12_3_labeled_numeric_example=pass`；
- `v12_3_range_and_zero_degree_height_relation=pass`。

但这仍不是完整公式。单点`0.02 -> 0.11`只是示例，不能成为通用v12.2到v12.3转换；讲义曲线不能被数字化后冒充官方公式；材料未给出完整方程、参数、breakpoints或尺度。NWS v12.3 supplemental正文只覆盖ProbSevere v3格式变化，也没有RQI算法细节。因此`v12_3_exact_rqi_formula=fail`、`v12_3_universal_numeric_mapping=fail`和`full_2022_2025_rqi_semantic_continuity=fail`继续成立。

同时已检查NCEPLIBS-g2c当前`develop`源码树和`tests/tst_mrms.c`历史。2023后的相关变化只有2024 clang-format，没有新增earth shape、scanning mode、cell support或Pass1/RQI同网格断言。以已有精确坐标常量和产品名进行公开源码反查，也没有找到可回到NOAA权威仓库核验的新Section 3记录。因此不能用第三方镜像、STAC投影字段或常识性经度归一化替代官方版本化Section 3证据。

报告状态为`v12_3_rqi_change_direction_and_msqpe_role_supported_exact_formula_and_mrms_grid_1_failed`。`pass1_and_rqi_grid_compatibility=fail`、`mrms_grid_1=fail`和`radar_coverage_or_quality_support=fail`不变；`cell_crosswalk_materialized=false`、`spatial_weights_materialized=false`、`general_geospatial_kernel_validated=false`。专项测试`7 passed`，MRMS/SRTM/NWM forcing/K0/Kernel readiness合并回归`146 passed`。

下一步只剩两条高价值路径：取得完整的v12.3 RQI版本化算法记录；取得每个适用Pass1/RQI版本不可变的Section 3或官方等价网格定义。若公开材料仍无结果，应将这两项转为受控官方信息请求，而不是继续从图像、样例值或第三方镜像反推。K0继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

### 12.22 13A.1交叉引用与RQI/融合方程补充询证

已沿上一节讲义中的明确交叉引用“See Steve Martinaitis talk 13A.1”完成第四条正式公开证据链。新增产物：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_v12_3_rqi_cross_reference_evidence_protocol.json`；
- 采集器：`scripts/fetch_gwm_mrms_v12_3_rqi_cross_reference_evidence.py`；
- 评估器：`scripts/assess_gwm_mrms_v12_3_rqi_cross_reference_evidence.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_v12_3_rqi_cross_reference_evidence_report.json`；
- 测试：`data_agent/test_assess_gwm_mrms_v12_3_rqi_cross_reference_evidence.py`；
- 正式快照：`data/gwm_bench_v0_3_candidate/mrms_v12_3_rqi_cross_reference_evidence/raw/20260723T065753Z/`。

协议canonical SHA-256为`0539edf838425aeda785675ed290770240f9614dbf61bb153d2adbc8b8f01b83`，冻结于`2026-07-23T06:55:00Z`，早于正式manifest的`2026-07-23T06:57:53Z`。正式快照只采集AMS Paper 474267摘要API和对应MediaFiles元数据API，`2/2`成功，共`8,261`字节。此前两个不完整传输快照不进入科学证据。正式运行没有下载讲义、没有栅格化页面、没有数字化曲线、没有请求MRMS RQI/Pass1/Pass2对象，也没有读取栅格值。

既有NSSL 2026官方目录快照明确把Paper 474267绑定为Martinaitis等人的报告“Evaluating Precipitation Accuracy and Coverage with an Updated MRMS Multisensor QPE”，报告号`13A.1`。该摘要新增了三个可复核事实：

- 问题背景包括在极远雷达距离仍可探测的对流风暴；
- 新MSQPE逻辑包含“changes to the Radar Quality Index coverage in warm season environments”；
- 同一组更新还包含“changes to the blending equations”。

这不是“RQI与融合方程已证明数学耦合”的证据，而是两类并行更新均需要版本化复现的证据。对于Geospatial Kernel，含义非常具体：不能只取得v12.3 RQI公式就声称已经重建radar QPE在MSQPE中的实际贡献；还必须取得适用的多传感器融合方程，明确RQI如何进入radar权重，以及gauge、model、climatology、topography和environmental输入如何归一化、门控与回退。因此新增通过门：

- `v12_3_rqi_cross_referenced_evaluation_role=pass`；
- `v12_3_parallel_blending_equation_change_disclosed=pass`；
- `v12_3_far_range_convective_problem_context=pass`。

但AMS公开记录同时显示`hasHandouts=0`、`ChildList_Files=[]`，MediaFiles端点也为空。因此`public_13a_1_handout_available=fail`。这个结论只表示正式快照时没有公开附件，不能证明不存在内部或非公开算法记录。摘要中的“currently running on a realtime testing platform”属于科研开发语境，不能覆盖NWS SCN和NSSL build timeline已经裁决的业务生效日期。

报告状态为`official_cross_reference_supports_parallel_rqi_and_blending_changes_exact_equations_and_mrms_grid_1_failed`。现在数值复现门被更精确地拆为：

- `v12_2_rqi_hgt_exact_equation=fail`；
- `v12_3_exact_rqi_formula=fail`；
- `v12_3_exact_blending_equations=fail`；
- `v12_3_joint_numeric_reproduction=fail`；
- `pass1_and_rqi_grid_compatibility=fail`；
- `mrms_grid_1=fail`。

公开材料路径已到达合理边界后，已生成一个新的补充官方询证包，但严格保持未发送。新增产物：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_request_protocol.json`；
- 生成器：`scripts/build_gwm_mrms_rqi_grid_supplemental_request.py`；
- 报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_request_report.json`；
- 人工可读草稿：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_request.md`；
- RFC 822草稿：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_request.eml`；
- 测试：`data_agent/test_build_gwm_mrms_rqi_grid_supplemental_request.py`。

询证协议canonical SHA-256为`8d4f7847c8667dfb79641242dd78f5c0bcd490ccef1d0d02eceae6802579f940`，将剩余问题固化为四个不可互相补偿的合同：

1. `MRMS-RQI-V12.2-HGT-1`：v12.2/v12.2.6完整`RQI_hgt`方程及版本差异；
2. `MRMS-RQI-V12.3-1`：生产v12.3 RQI方程、变量、单位、系数、breakpoints、clipping、scale和生效范围；
3. `MRMS-MS-QPE-BLEND-V12.3-1`：适用的MSQPE融合方程、RQI在radar权重中的精确角色及其他输入的归一化和回退逻辑；
4. `MRMS-PASS1-RQI-GRID-EQUIV-1`：v12.1.0、v12.2.0、v12.2.6、v12.3.0逐版本Section 3或官方等价记录，并显式断言同期Pass1/RQI是否cell-for-cell相同。

生成报告状态为`supplemental_request_prepared_not_sent`。草稿只指向已有官方页面验证的一般MRMS支持地址，`authorized_recipient_addresses=[]`、`dispatch_authorized=false`、`external_message_sent=false`且EML包含`X-Unsent: 1`。生成过程没有发起网络请求或外部消息，没有请求数据资产，也没有改变任何科学门。只有用户明确授权后才可发送；即便收到回复，也必须按版本、publisher、identifier、date和effective scope逐合同裁决，非版本化邮件说明不能直接开门。

本轮两组专项测试合计`13 passed`；MRMS、SRTM、NWM forcing、K0和Kernel readiness合并回归`159 passed`。GWM继续表示跨领域地理空间世界模型及共享Kernel契约，TWM/UWM继续表示领域实例，HydroControl继续只是验证适配器。K0固定保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。下一步不应再从曲线、单点示例或第三方网格推断，而应等待或在获得用户授权后发送补充询证，并为正式回复准备逐合同adjudicator。

### 12.23 MRMS补充询证响应接收与两阶段裁决

已继续把未来官方回复的处理路径固化为fail-closed代码，而不是等收到邮件后临时解释。新增产物：

- 响应接收模板：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_response_intake.json`；
- 裁决器：`scripts/adjudicate_gwm_mrms_rqi_grid_supplemental_response.py`；
- 当前裁决报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_response_adjudication_report.json`；
- 测试：`data_agent/test_adjudicate_gwm_mrms_rqi_grid_supplemental_response.py`。

响应接收模板被精确绑定到补充询证协议和生成报告：协议文件SHA-256为`768bccc7e06cd5b06720eb0ea865809d13c644c1c46d85e2092f6c57b377a31a`，canonical SHA-256为`8d4f7847c8667dfb79641242dd78f5c0bcd490ccef1d0d02eceae6802579f940`，询证报告SHA-256为`c209fa69eb6e58ec712ad521a0c3713536f86ed46e6ed99ae443409be98af77f`。默认intake本身SHA-256为`5b44fcf01ad260f1bfbb32b6366b44710d839ecd936e97522cd8e0b7cb0d9e92`。

裁决器采用严格的两阶段语义：

1. 机器接收与结构审查：核验case或records-request编号、响应机构、官方地址、接收时间、响应引用、联系或dispatch引用；所有响应附件必须位于项目边界内并通过SHA-256；四个合同必须按冻结顺序完整出现；每个required field必须绑定已核验附件、稳定record identifier和非空rationale；任一conflict或limitation都会阻止结构准入。
2. 人工科学裁决：即使四个合同在结构上全部齐全，机器也只允许状态进入`all_contracts_eligible_for_manual_scientific_adjudication`。它不会把任何合同自动改为pass，不会修改既有冻结报告，也不会准入模型输入、训练、cell crosswalk或空间权重。之后仍必须建立单独版本化的人工科学裁决，逐项判断公式、参数、版本、生效范围和网格定义是否真正满足证据合同。

这一设计防止三类错误：第一，“收到NOAA邮件”被误当成科学门通过；第二，字段看似齐全但引用的是未哈希、无版本或无生效范围的记录；第三，一个合同的完整回复补偿另一个合同的缺失。四个合同继续不可互相补偿。

当前报告状态为`awaiting_official_response`：`response_received=false`、官方响应身份不完整、响应附件为零、四个合同均未审查。所有门继续保持：

- `v12_2_rqi_hgt_exact_equation=fail`；
- `v12_3_exact_rqi_formula=fail`；
- `v12_3_exact_blending_equations=fail`；
- `v12_3_joint_numeric_reproduction=fail`；
- `pass1_and_rqi_grid_compatibility=fail`；
- `mrms_grid_1=fail`；
- `radar_coverage_or_quality_support=fail`。

响应裁决专项测试`7 passed`，合并回归现为`166 passed`。没有发送邮件，没有收到外部响应，没有请求或读取MRMS栅格，也没有生成cell crosswalk或空间权重。K0继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。在用户明确授权外发前，下一项可执行工作应继续完善“人工科学裁决协议和准入证书”的冻结模板，但不能假定官方回复内容。

### 12.24 MRMS人工科学裁决协议与子证书边界

已继续完成上一节指定的下一项工作，在没有官方回复的前提下先冻结人工科学裁决规则。新增产物：

- 协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_manual_scientific_adjudication_protocol.json`；
- 未签署模板：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_manual_scientific_adjudication_template.json`；
- 裁决器：`scripts/adjudicate_gwm_mrms_rqi_grid_manual_scientific_admission.py`；
- 当前报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_manual_scientific_admission_report.json`；
- 测试：`data_agent/test_adjudicate_gwm_mrms_rqi_grid_manual_scientific_admission.py`。

协议canonical SHA-256为`0a60c82ea6d54653feea897143374f43ddd4b2409eba3c6be333c23d610bba8b`，协议文件SHA-256为`b574f42e7f8f3a447a7893e2d804284ec9b06840e2cde05d611ecfe3a4d95445`。它绑定上一节的响应intake和响应裁决报告；因为上游状态仍为`awaiting_official_response`，本版本协议状态被冻结为`frozen_deferred_upstream_response_not_ready`，不能通过编辑未签署模板伪造上游就绪。

人工裁决要求明显高于“找两个人签字”：

- 必须有两名reviewer，reviewer ID互异；
- 必须填写姓名、机构、专业资格、conflict disclosure、无冲突结论、attestation和reviewed_at；
- 两名reviewer都必须逐字覆盖合同冻结的全部`required_fields`，合同级笼统`pass`无效；
- 每个合同必须引用上游响应裁决器已经哈希核验的附件；
- 官方记录必须具有publisher、identifier、version、record date和effective scope；
- 任一partial、conflicting、未说明limitation或缺字段合同都不能被其他合同补偿。

三个公式合同还必须满足可执行复现要求：存在项目边界内、SHA-256通过的executable transcription；合成边界测试数量大于零且全部通过；如果官方记录提供test vectors，必须全部一致；版本和生效范围必须核验；不得使用讲义曲线数字化或单点`0.02 -> 0.11`示例冒充公式。网格合同则要求v12.1.0、v12.2.0、v12.2.6和v12.3.0四个版本分别提供Pass1/RQI Section 3或官方等价记录，完整核验earth shape、scanning mode、axes、cell support和明确的cell-for-cell等价声明；不得自行推断longitude normalization，裁决阶段仍不得物化crosswalk。

合同和门的映射已经冻结：

- `MRMS-RQI-V12.2-HGT-1`控制`v12_2_rqi_hgt_exact_equation`；
- `MRMS-RQI-V12.3-1`控制`v12_3_exact_rqi_formula`；
- `MRMS-MS-QPE-BLEND-V12.3-1`控制`v12_3_exact_blending_equations`；
- `MRMS-PASS1-RQI-GRID-EQUIV-1`同时控制`pass1_and_rqi_grid_compatibility`和`mrms_grid_1`；
- v12.3 RQI与融合方程必须同时通过，`v12_3_joint_numeric_reproduction`才能通过；
- 四个合同必须全部通过，`radar_coverage_or_quality_support`才能通过。

即使未来四个合同全部通过并签发`MRMS scientific subcertificate`，该子证书仍不能直接pass K0，不能准入MRMS raster values，不能生成cell crosswalk或spatial weights，也不能验证通用Geospatial Kernel或通用GWM。它只关闭MRMS科学语义与网格子门；完整forcing admission和独立多领域泛化仍须另行通过。

当前报告状态为`deferred_upstream_response_not_ready`，上游响应未就绪，两名reviewer均为空，四个合同均fail，子证书未签发。专项测试`8 passed`，合并回归增至`174 passed`。没有发送外部消息，没有请求或读取MRMS栅格，没有生成空间权重。K0继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

### 12.25 MRMS补充询证精确外发授权门

已继续完成外发前的精确授权和回执边界，但没有把用户的“继续完善”解释为发送邮件授权。新增产物：

- dispatch协议：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_dispatch_protocol.json`；
- 未授权模板：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_dispatch_authorization.json`；
- 未发送回执模板：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_dispatch_receipt_template.json`；
- 只验证不发送的guard：`scripts/verify_gwm_mrms_rqi_grid_supplemental_dispatch.py`；
- 当前验证报告：`benchmarks/gwm_bench_v0_3_candidate/mrms_rqi_grid_supplemental_dispatch_verification_report.json`；
- 测试：`data_agent/test_verify_gwm_mrms_rqi_grid_supplemental_dispatch.py`。

dispatch协议canonical SHA-256为`f0e8b8bb0c79fab7d57d102e637331ea7e3e08001a05a6a38e693daddd99d2c6`，协议文件SHA-256为`dfdb5bc1d10f61d355a79438c40f7ea237496eb6bf6ae178b2d6a19c82b7db33`。协议将允许外发的消息固定为：

- 唯一`To`：`idp-support@noaa.gov`；
- `CC=[]`、`BCC=[]`；
- 精确subject：`Supplemental request for MRMS v12.3 RQI, multisensor blending equations, and Pass1/RQI grid equivalence`；
- body SHA-256：`7053ebe05e3dee51efb4e4f52c1b51e86337137f0db3647e3154116545f41cc6`；
- EML SHA-256：`199e079d4994f2d30a219e5a70a0134345b95a3194734de51873cc4ed1420c37`；
- 附件数：0；
- 最大授权发送次数：1。

guard已经验证当前EML的文件哈希、To、CC、BCC、subject、解码后的正文哈希、附件数和`X-Unsent: 1`全部精确匹配。它自身被协议禁止执行网络请求、打开邮件客户端、修改EML、增加收件人或增加附件。`conversation_continuation_may_be_treated_as_authorization=false`明确表示“请继续”“继续完善”等一般项目指令不是外发授权。

有效授权必须同时填写approver姓名、身份或角色、批准时间、明确authorization statement，并使用固定scope literal `send_exact_bound_message_once_to_exact_primary_recipient`；authorized recipient必须精确等于唯一To，send count必须为1，prior send count必须为0，正文修改和附件都不得授权。任何消息哈希、收件人或发送状态变化都会使授权失效。

即使未来授权完全有效，guard也只产生确定性的dispatch token，状态为`dispatch_authorized_not_sent`；token不是发送回执。实际发送后还必须另行生成hash-bound receipt，记录真实recipient、sent_at、transport、provider message ID、provider response和回执附件哈希。授权、token和回执均不是科学证据，不能改变RQI、网格或K0门。

当前授权模板SHA-256为`6da8f49ecb4d7dc3d2633c63bb0f8e42f3ef3cb92993d3ac54cfb0ad82c1b9c2`，状态为`authorization_required`；验证报告状态为`dispatch_blocked_authorization_required`，`dispatch_authorized=false`、`dispatch_token=null`、`external_message_sent=false`、`network_request_made=false`、`mail_client_opened=false`。专项测试`8 passed`，合并回归增至`182 passed`。K0继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

### 12.26 Paper6/SCCA共享因果校准契约与rollout绑定

已把Paper6的SCCA能力从TWM/UWM侧的外部因果证据，进一步抽象为GWM共享Geospatial Kernel的可选因果校准契约。新增实现：

- 共享契约模块：`data_agent/uwm/geospatial_kernel/causal_calibration.py`；
- 包导出：`data_agent/uwm/geospatial_kernel/__init__.py`；
- rollout可选绑定：`data_agent/uwm/geospatial_kernel/counterfactual_rollout.py`；
- 聚焦测试：`data_agent/test_gwm_geospatial_causal_calibration_contract.py`。

虽然代码仍位于历史形成的`data_agent/uwm/geospatial_kernel`包路径内，新schema使用`gwm.geospatial_kernel.causal_calibration_contract.v1`，语义所有权属于跨领域GWM共享Kernel，而不是UWM专有模型。公开API包括：

- `build_scca_causal_calibration_contract(...)`：把Paper6/SCCA报告桥接为共享契约；
- `validate_causal_calibration_contract(...)`：验证结构、来源哈希、声明边界和自洽性；
- `bind_causal_calibration_to_rollout(...)`：把通过验证的契约确定性绑定到rollout审计段。

契约显式记录estimand的unit、treatment/action、outcome、treatment time和horizon；记录direct target、relation types、neighborhood hops和mapping version；记录design、adjustment set、overlap、consistency、exchangeability boundary、interference assumption和time-varying confounders；并为direct、spillover、total、uncertainty以及balance、overlap、placebo、negative controls、spatial residual、geographic holdout、temporal placebo和sensitivity保留结构化字段。来源报告、artifact hashes、契约本身和rollout绑定均采用SHA-256绑定。

本轮最重要的边界不是“接入一个因果系数”，而是阻止未识别的系数进入模拟状态。Paper6明确是空间因果诊断工作流，不是新的因果估计器或识别定理。因此SCCA桥接契约固定：

- `observed_policy_outcome_ready=false`；
- `longitudinal_causal_identification_ready=false`；
- `spatiotemporal_interference_identification_ready=false`；
- `effect_application_admitted=false`；
- `identified_causal_effect=false`；
- `empirical_policy_effect_claim=false`；
- `general_geospatial_kernel_validated=false`；
- `gwm_k0_validated=false`。

即使SCCA自身的balance、空间残差和credibility gate通过，当前也只可作为`causal_calibration_support`、`spatial_interference_diagnostic`和`evidence_grade_signal`。它不能替代GWM simulator，不能替代TWM/UWM领域planner，也不能把观测关联自动解释为已识别的时空因果效应。时变处理、滞后时变混杂、动态处理策略、longitudinal AIPW/MSM、正式的时空干扰暴露映射、多期政策event study和真实政策holdout仍是后续缺口。

rollout在未提供契约时保持原输出完全不变；提供契约时，仅增加hash-bound `causal_calibration`审计段并更新rollout digest。`baseline`、`intervention`、`alternative`、`direct_state_delta`和`spillover_state_delta`受到独立摘要保护且不被因果估计修改。任何试图把effect application、已识别因果效应、通用GWM验证或K0验证改为true的契约都会校验失败。

聚焦与共享Kernel回归为`56 passed`；MRMS、SRTM、NWM forcing、K0 readiness、共享Kernel和新因果契约合并回归为`238 passed in 3.27s`。K0结论没有变化：工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。本轮没有发送外部消息，没有请求或读取MRMS栅格，没有生成cell crosswalk或空间权重。

### 12.27 纵向时空因果设计与非补偿式readiness gate

已在上一节SCCA因果校准契约之上，新增GWM共享的纵向时空因果设计契约：

- 实现：`data_agent/uwm/geospatial_kernel/spatiotemporal_causal_design.py`；
- 包导出：`data_agent/uwm/geospatial_kernel/__init__.py`；
- SCCA嵌套校验：`data_agent/uwm/geospatial_kernel/causal_calibration.py`；
- 测试：`data_agent/test_gwm_spatiotemporal_causal_design_contract.py`。

新schema为`gwm.geospatial_kernel.spatiotemporal_causal_design.v1`。它不是纵向估计器，也不把Paper6改写为新的识别定理；它先把未来数值估计必须满足的数据结构、时序和证据条件固化为机器可验证合同。公开API包括：

- `build_spatiotemporal_causal_design_contract(...)`；
- `validate_spatiotemporal_causal_design_contract(...)`；
- `bind_spatiotemporal_design_to_causal_calibration(...)`；
- `validate_spatiotemporal_causal_design_binding(...)`。

设计合同显式记录study、estimand、panel design、temporal ordering、interference mapping、identification strategy、逐门证据和provenance。它支持的设计描述包括point intervention with longitudinal outcomes、time-varying treatment和dynamic treatment regime；识别策略枚举包括MSM/IPW、longitudinal g-formula、sequential AIPW、longitudinal TMLE以及带空间干扰诊断的event study。这里的“支持”仅表示合同可以准确描述并审查这些策略，不表示仓库已经实现或验证这些数值估计器。

11个longitudinal design gate不可互相补偿：

- unit-time唯一性；
- 时序核验；
- treatment先于outcome；
- pre-treatment covariates核验；
- time-varying confounders已测量；
- treatment-confounder feedback已声明；
- 逐期positivity已诊断；
- censoring和missingness已诊断；
- interference exposure mapping已版本化；
- network-time alignment已核验；
- 无未来信息泄漏。

8个estimation gate同样不可互相补偿：longitudinal estimator executed、sequential balance、weight stability、pretrend/preperiod stability、temporal placebo、geographic holdout、uncertainty estimated以及observed policy outcome available。每个通过门都必须具有非空evidence refs；只填写`passed=true`而没有证据引用不能形成readiness。

合同区分三个状态：`longitudinal_design_ready`、`spatiotemporal_interference_design_ready`和`estimator_execution_ready`。设计门全通过不能补偿估计门缺失；即使合成测试把全部19个门都置为有证据的通过状态，仍固定：

- `effect_application_admitted=false`；
- `identified_policy_effect=false`；
- `general_geospatial_kernel_validated=false`；
- `gwm_k0_validated=false`；
- `domain_generalization_validated=false`。

未测量或状态未知的treatment-confounder feedback会形成结构性blocker，不能被其他诊断补偿。动态处理缺少time-varying confounders、错误的`L_t -> A_t -> Y_(t+1)`顺序、缺少pre/post periods、未知network time mode或未知identification strategy也会阻断readiness。source bundle、artifact hashes、设计合同、SCCA绑定和最终rollout继续逐层SHA-256绑定。

纵向设计可以嵌入上一节的SCCA契约，但嵌入后只新增`longitudinal_design_contract_ready`和`longitudinal_estimator_execution_ready`等审计状态。SCCA主契约的`longitudinal_causal_identification_ready=false`、`observed_policy_outcome_ready=false`和`effect_application_admitted=false`不变。端到端测试确认，绑定完整纵向设计后，rollout的`baseline`、`intervention`、`alternative`、`direct_state_delta`和`spillover_state_delta`仍完全不变。

共享Kernel回归为`67 passed`；MRMS、SRTM、NWM forcing、K0 readiness、共享Kernel、SCCA契约和纵向时空设计契约合并回归为`249 passed in 3.23s`。K0现场结论继续是工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。本轮没有发送外部消息，没有请求或读取MRMS栅格，没有生成cell crosswalk或空间权重。

### 12.28 AI Urban Scientist驱动的纵向面板来源准入与Chicago pilot

已按完整`AI-Urban-Sci-Skill-v1/skills/urban-data-seeker`工作流继续推进上一节的数据基础：先按数据类型拆解，再用确定性router校验，随后只打开三个直接相关下游skill：`legistar-platform`、`socrata-platform`和`census-acs`。路由结论为：

- 政策事件：`legistar-platform`，`platform_fingerprint`，confidence high；
- 建筑许可结果：`socrata-platform`，`platform_fingerprint`，confidence high；
- 社会经济协变量：`census-acs`，`exact_source`，confidence high；
- tract geometry同时由router给出`us-tiger-boundaries` exact-source候选，但本轮没有打开第四个下游skill，也没有下载TIGER ZIP。

新增共享来源合同及产物：

- 通用实现：`data_agent/uwm/geospatial_kernel/longitudinal_panel_sources.py`；
- Chicago候选生成器：`scripts/build_gwm_chicago_longitudinal_panel_source_candidate.py`；
- 冻结候选：`benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/source_candidate_contract.json`；
- 测试：`data_agent/test_gwm_longitudinal_panel_source_contract.py`；
- AI Urban Scientist P0 gap matrix已增加Chicago第二城市候选，但重庆仍是原有主路线。

新schema为`gwm.geospatial_kernel.longitudinal_panel_source_contract.v1`，当前合同digest为`ce8e26eacd1f96192643259cd14e06c681d137bf78ea3c8a975f080ce1fe49df`。来源角色被固定为五个不可互相补偿的合同：`treatment_events`、`observed_outcomes`、`time_varying_confounders`、`spatial_units`和`interference_network`。每个角色可由一个或多个来源共同构成，但同角色的全部来源都必须通过，不能由一个好来源补偿另一个阻塞来源。另有六个不可补偿crosswalk gate：treatment-to-unit、outcome-to-unit、confounder-to-unit、unit-time alignment、network-to-unit-time和no-future-information-leakage。

Chicago eLMS官方API产生了本轮正证据。Swagger可访问，API schema约49,083字节；对exact matter detail的probe确认：

- matter ID：`86390664-2D38-F111-88B3-001DD8033B18`；
- record number：`O2026-0024863`；
- category：`ZONING RECLASSIFICATIONS`；
- title：`Zoning Reclassification Map No. 16-G at 6716 S Bishop St - App No. 23063T1`；
- status/substatus：`90-Final`/`Passed`；
- introduction：`2026-04-15T15:00:00+00:00`；
- final action：`2026-07-15T15:00:00+00:00`；
- detail中包含actions、City Council votes、Final Ordinance、Application以及Final Narrative and Plans等附件URL。

这只能证明一个稳定、已通过的zoning treatment record候选。`finalActionDate`不是自动的effective date，地址文本不是treatment polygon，Narrative and Plans附件尚未进入项目、未解析、未核验空间范围。附件HEAD返回200和`Content-Length=291862`；随后尺寸探针实际又完成了291,862字节整文件传输到`/dev/null`。没有保存或解析该附件，也没有批量下载，但不能把本轮全部网络请求描述为metadata/sample-only；合同已经显式记录`single_attachment_full_transfer_to_null=true`和`network_requests_bounded_to_metadata_and_samples=false`。

其他来源保持fail-closed：

- Chicago Socrata Building Permits view `ydr8-5enu`的metadata和3行sample均返回403，标记`browser_or_waf`，没有把403误判为需要认证，也没有请求full export；
- 2024 ACS5 Cook County tract协变量route已经固定变量和estimate/MOE配对，但当前环境返回API-key boundary或timeout，未取得JSON rows；并显式记录ACS5 vintage是重叠五年估计，不是独立年度点观测；
- 2024 Illinois TIGER tract ZIP HEAD返回Cloudflare 403，没有下载ZIP，没有验证GEOID/geometry，也没有构造tract adjacency。

因此即使eLMS单条sample status为pass，treatment角色仍因license、完整时间覆盖、effective date和geometry未核验而不是metadata-ready；另外四个角色同样未就绪。当前固定结论为：

- `all_source_metadata_ready=false`；
- `all_source_samples_ready=false`；
- `all_crosswalks_ready=false`；
- `panel_materialization_ready=false`；
- `panel_materialization_admitted=false`；
- `causal_estimation_admitted=false`；
- `effect_application_admitted=false`。

`seed_spatiotemporal_gate_evidence_from_panel_sources(...)`已经把来源合同接到上一节纵向设计合同，但它只会产生关闭的design/estimation gates。即使未来五类来源和六个crosswalk全部通过，来源合同也只能产生`panel_materialization_ready=true`，不能自行产生`panel_materialization_admitted=true`；下载与物化仍需要独立执行授权。unit-time唯一性、时序、positivity、weight stability、placebo和holdout还必须在物化面板上独立执行，不能由catalog/source readiness代替。

共享Kernel及三层因果/来源合同回归为`77 passed`；加入AI Urban Scientist adapter以及MRMS、SRTM、NWM forcing和K0 readiness后的合并回归为`262 passed in 3.34s`。K0结论未改变，Chicago pilot也不是第二城市泛化验证。本轮没有发送外部消息，没有请求或读取MRMS栅格，没有生成任何训练面板、tract crosswalk或interference network。

### 12.29 纵向面板行级验证与时空因果设计门绑定

已在12.28节的来源准入合同之上继续实现面板行级验证层。新增：

- 实现：`data_agent/uwm/geospatial_kernel/longitudinal_panel_validation.py`；
- shared Kernel导出：`data_agent/uwm/geospatial_kernel/__init__.py`；
- 测试：`data_agent/test_gwm_longitudinal_panel_validation.py`。

新schema为`gwm.geospatial_kernel.longitudinal_panel_validation.v1`，公开API包括：

- `build_longitudinal_panel_validation_contract(...)`：对内存中的panel rows与dynamic network rows执行确定性审计，并仅在合同中保存规范化行哈希、计数和审计摘要，不把测试行嵌入合同；
- `validate_longitudinal_panel_validation_contract(...)`：复核嵌套来源合同、字段映射、时间策略、缺失策略、物化声明、manifest、audit引用、readiness、admission、claim boundary和合同SHA-256；
- `seed_spatiotemporal_gate_evidence_from_panel_validation(...)`：把面板能够直接证明的检查映射到12.27节的时空因果设计门，其余门保持关闭。

行级验证包含16个不可补偿检查：必需panel/network列、unit-time唯一性、稳定unit/source ID、treatment/outcome角色分离、`panel_time <= L_t <= A_t < Y_(t+1)`、treatment先于outcome、逐unit的pre/post覆盖、时变混杂完整性、真实outcome存在、missingness/censoring声明、treatment-to-unit crosswalk、network端点crosswalk、干扰映射版本、逐unit-time网络vintage对齐、无未来信息泄漏，以及五类来源artifact hash完整覆盖。任何一个检查失败都会使`row_validation_ready=false`，不能由其他检查补偿。

合同明确分离两种证据类别：

- `synthetic_fixture`只用于证明验证器本身能够发现重复索引、未来泄漏、网络版本错位、错误删失声明和哈希篡改；即使16项检查全部通过，`empirical_panel_evidence_ready=false`，全部19个时空因果设计/估计门仍关闭；
- `materialized_empirical_panel`只有在来源五角色和六个crosswalk已经全部ready、存在独立`authorization_ref`、物化时间和storage ref、来源artifact hashes完整、16项行级检查全部通过时，才可令`empirical_panel_evidence_ready=true`。

即使经验面板证据ready，新层也只打开能够由面板结构本身直接证明的门：unit-time唯一性、时序、treatment先于outcome、pre-treatment covariates、时变混杂、干扰映射版本、network-time alignment、无未来泄漏和observed policy outcome availability。它只证明missingness/censoring字段和策略已经声明，不再自行打开`censoring_and_missingness_diagnosed`；该门必须由后续数值诊断负责。它也不会自行打开`treatment_confounder_feedback_declared`、`positivity_by_time_diagnosed`，以及longitudinal estimator execution、sequential balance、weight stability、pretrend、placebo、geographic holdout或uncertainty门。跨层测试已确认：一个完全通过的hash-bound经验面板送入时空因果设计合同后，设计仍精确阻塞在feedback、positivity和censoring diagnostics三个设计门，`estimator_execution_ready=false`且`effect_application_admitted=false`。

Chicago pilot当前没有进入该验证器：12.28节候选仍是source discovery/probe合同，`panel_materialization_ready=false`，没有真实Chicago panel rows、tract crosswalk或dynamic interference network。不能用本轮合成fixture替代Chicago证据，也不能因为验证器已经实现就宣称Paper6获得经验因果识别。

本轮四层因果/来源/面板聚焦回归为`42 passed`；MRMS、SRTM、NWM forcing只读评估、K0 readiness、shared Kernel、AI Urban adapter及新验证层的筛选宽回归为`224 passed in 3.46s`。一次覆盖全部`test_gwm_*.py`的过宽回归在前10%后等待现有NWM Azure value compilation活动/快照锁，已主动停止；没有把部分结果计为通过，也没有修改或物化NWM资产。K0结论继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

下一步应继续实现两个独立层，不能直接进入效果应用：第一，基于真实面板的逐期positivity、sequential balance、weight stability和censoring diagnostics；第二，显式的treatment-confounder feedback审计与dynamic interference exposure构造。只有Chicago或另一城市的官方来源、空间crosswalk和时间对齐面板真正物化并通过本节合同后，这两层的结果才可形成经验设计证据。

### 12.30 纵向positivity、balance、权重与删失诊断层

已完成12.29节指定的第一类独立诊断层，但没有进入结果模型或效果应用。新增：

- 实现：`data_agent/uwm/geospatial_kernel/longitudinal_causal_diagnostics.py`；
- shared Kernel导出：`data_agent/uwm/geospatial_kernel/__init__.py`；
- 测试：`data_agent/test_gwm_longitudinal_causal_diagnostics.py`；
- 同时收紧12.29节panel gate mapping：仅声明missingness/censoring不再等于完成数值诊断。

新schema为`gwm.geospatial_kernel.longitudinal_causal_diagnostics.v1`，公开API包括：

- `build_longitudinal_causal_diagnostic_contract(...)`：把诊断行与已验证panel的完整行SHA-256和unit-time索引绑定，逐期计算positivity、weighted balance、treatment weights、censoring/IPCW和combined weights；
- `validate_longitudinal_causal_diagnostic_contract(...)`：验证嵌套panel合同、模型与数据hash、字段、阈值、交叉拟合、diagnostic checks、readiness、admission和claim boundary；
- `seed_spatiotemporal_gate_evidence_from_longitudinal_diagnostics(...)`：先继承panel能够证明的design evidence，再只覆盖positivity、censoring、sequential balance和weight stability四个直接相关门。

诊断合同包含10项不可补偿检查，其中前5项属于执行可信性：panel rows必须与上游hash逐字节语义等价；diagnostic unit-time索引必须唯一且完整覆盖panel；propensity、权重和删失概率必须为有限合法数值；nuisance模型必须声明并实际满足unit-grouped forward-chaining cross-fit，所有同一unit必须位于同一fold且每行training cutoff严格早于panel time；报告权重必须满足冻结的`stabilized_observed_action_and_status_probability_ratio`公式。任一执行检查失败会令`empirical_diagnostic_evidence_ready=false`，不能把后续看似良好的数值作为经验诊断。

后5项阈值检查归为4类诊断，按每个time risk set分别执行：

- positivity同时要求逐期treated/control最小样本量以及每行propensity处于冻结支持区间；
- sequential balance使用treatment weights分别计算每期、每个baseline/time-varying confounder的加权标准化均值差，任何一个`abs(SMD)`超过阈值即失败；
- treatment和combined weights分别检查最大权重、变异系数`CV=SD(w)/mean(w)`以及有效样本比例`ESS/n=(sum(w)^2/sum(w^2))/n`；
- censoring诊断逐期检查删失率、最小survival probability和最大censoring weight，不能由treatment weights稳定性补偿。

合同严格区分“诊断成功执行”和“阈值通过”。例如，一个与公式一致的极端propensity/weight会形成可信的失败诊断：`empirical_diagnostic_evidence_ready=true`，但positivity和weight gate为false且保留hash-bound失败引用。相反，报告权重若与概率公式不一致，或cross-fit training cutoff使用未来信息，则整个诊断执行不被准入。这样不会把数据问题与实现/来源问题混为一类。

经验面板且全部诊断通过时，只能新增以下gate evidence：`positivity_by_time_diagnosed=true`、`censoring_and_missingness_diagnosed=true`、`sequential_balance_passed=true`和`weight_stability_passed=true`。跨层测试确认，完整诊断进入时空设计后仍阻塞在`treatment_confounder_feedback_declared`；估计侧仍阻塞longitudinal estimator、pretrend/preperiod stability、temporal placebo、geographic holdout和uncertainty。诊断权重不是outcome estimator，全部阈值通过也固定保持`causal_identification_ready=false`、`effect_application_admitted=false`、`general_geospatial_kernel_validated=false`和`gwm_k0_validated=false`。

Chicago仍没有真实panel或诊断输入，本节所有正向场景均为合成fixture。合成诊断可以验证公式和fail-closed逻辑，但即使全部通过也保持`empirical_diagnostic_evidence_ready=false`，不能补偿12.28节的source、license、effective date、geometry、ACS、TIGER和network缺口。

本轮五层因果/来源/面板/诊断聚焦回归为`53 passed`，shared Kernel回归为`82 passed`，MRMS、SRTM、NWM forcing只读评估、K0 readiness、shared Kernel和AI Urban adapter的筛选宽回归为`235 passed in 3.72s`。没有发送外部消息，没有获取或物化Chicago面板，没有请求MRMS或SRTM栅格，也没有进入NWM value compilation。K0继续保持工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

下一步应实现显式的treatment-confounder feedback审计和dynamic interference exposure construction，并把它们作为独立hash-bound合同接入设计门。之后才是longitudinal outcome estimator、pretrend/placebo/holdout和uncertainty；不能用本节权重诊断直接替代这些层。

### 12.31 AI Urban Scientist驱动的Chicago真实数据基础补强

本轮把重点从继续增加因果合同切换为补齐真实数据证据，并重新完整执行`AI-Urban-Sci-Skill-v1/skills/urban-data-seeker`。确定性router与下游skill选择为：

- permits outcome：`socrata-platform`，URL/domain fingerprint，confidence high；
- tract confounders：`census-acs`，exact source，confidence high；
- tract geometry：`us-tiger-boundaries`，exact source，confidence high；
- direct routes失败后的fallback：`arcgis-platform`、`data-gov-catalog`和`ckan-platform`。

所有新网络请求均限定为metadata、目录、单地址、单tract或最多3行probe；没有请求full permit export、全Cook County ACS、Illinois TIGER ZIP或全城市tract geometry。原始响应保存到`benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence/`，8个原始JSON合计约66KB；另生成第9个审计报告。全部文件由source contract逐文件记录相对路径、字节数和SHA-256。

#### 12.31.1 Building Permits官方catalog证据

Chicago Socrata metadata、resource JSON、OData和两种v3 bounded query继续统一返回403，因此没有伪造schema或row sample pass。但Data.gov旧CKAN端点的替代GSA v4 Catalog API可访问，并精确返回`ydr8-5enu`：

- organization：`City of Chicago`；
- organization type：`City Government`；
- access level：`public`；
- title：`Building Permits`；
- coverage：2006年至今；
- modified：`2026-07-21`；
- last harvested：`2026-07-21T22:26:46.219904`；
- distributions：JSON、XML、CSV、KML、KMZ和GeoJSON。

因此observed outcome来源的`metadata_probe_status`和`time_coverage_status`已从blocked/review分别提升为pass；但GSA记录没有license，Socrata columns和3行sample仍被WAF阻塞，所以`schema_probe_status=blocked`、`license_status=review`、`sample_validation_status=blocked`，`outcome_to_unit=false`。Catalog metadata不能替代permit rows。

#### 12.31.2 eLMS地址到tract的官方空间链

ArcGIS fallback首先拒绝了无可核验官方owner的permits和tract复制图层；随后在`GIS_chicago` owner下找到City of Chicago官方`Chicago Property Addresses` GeocodeServer和current zoning FeatureServer。对eLMS标题地址`6716 S Bishop St`的bounded query得到：

- match：`6716 S BISHOP ST, 60636`；
- score：100；
- address type：`PointAddress`；
- PIN：`2020302029`；
- ward：16；
- community：`WEST ENGLEWOOD`；
- EPSG:3435 point：`(1167755.5154296386, 1860103.2615483797)`；
- WGS84 point：`(-87.66061727108206, 41.77166529892371)`。

FCC Census Block API对该点返回block FIPS `170316716001013`，由此确定2020 tract GEOID `17031671600`。这使“政策记录地址 -> 官方Chicago point -> 官方FCC block/tract”成立。它仍不是受影响的zoning polygon，因此`treatment_to_unit`继续false并保留正负证据引用。

同点的City current zoning query命中OBJECTID `1661018`、class `RS-3`，但`CASE_NUMBER`、`ORDINANCE_NUM`和`CLERK_DOCNO`均为空；按application `23063`查询也返回0个feature。这个结果被记录为负证据：current zoning layer当前不能作为`O2026-0024863`的treatment polygon，也不能据此推断政策尚未或已经生效。

#### 12.31.3 ACS与geometry的secondary fallback样本

官方Census ACS变量元数据、单tract行请求和TIGERweb仍超时，官方TIGER ZIP与目录仍为403。为了验证数据语义和crosswalk可执行性，保存了明确标注为secondary的Census Reporter单tract样本：

- release：`acs2024_5yr`，years `2020-2024`；
- geography：`Census Tract 6716, Cook, IL`；
- tables：B01003 population、B19013 median household income、B23025 employment status、B25001 housing units；
- estimate和MOE逐列配对完整；
- TIGER2024-derived polygon GEOID：`14000US17031671600`；
- Chicago官方point位于该secondary polygon内。

该fallback证明变量、MOE、GEOID和point-in-polygon链可以执行，但不能升级官方Census ACS或TIGER准入。因此`confounder_to_unit=false`、官方spatial-unit sample仍未通过；只有一个tract polygon也不能构造interference adjacency。

#### 12.31.4 两层hash-bound审计与当前结论

新增：

- 审计器：`scripts/audit_gwm_chicago_longitudinal_data_foundation.py`；
- 审计测试：`data_agent/test_audit_gwm_chicago_longitudinal_data_foundation.py`；
- 更新generator：`scripts/build_gwm_chicago_longitudinal_panel_source_candidate.py`；
- 更新冻结candidate与9个evidence artifacts。

审计器直接解析8个raw JSON并完成9项交叉检查：permits catalog身份和覆盖、Chicago point address、FCC block-to-tract、current zoning context、treatment polygon负证据、secondary ACS、secondary TIGER2024 geometry及point containment。审计状态为`bounded_evidence_valid_not_panel_ready`，9/9检查通过；report digest为`36f293791f0a74f4e8ef9c9b237970a4a6b5763e76381318fd6782075b5af5ec`。

更新后的source contract digest为`80e64de0a46154d6255c637f95f8792a53fc38c23d6478a96429822ee0b9ce9f`。数据比12.28节更完整，但非补偿式状态仍是：

- `all_source_metadata_ready=false`；
- `all_source_samples_ready=false`；
- `all_crosswalks_ready=false`；
- `panel_materialization_ready=false`；
- `panel_materialization_admitted=false`；
- `causal_estimation_admitted=false`；
- `effect_application_admitted=false`。

Chicago数据/因果链聚焦回归为`61 passed`；加入MRMS、SRTM、NWM forcing只读评估、K0 readiness、shared Kernel和AI Urban adapter的筛选宽回归为`240 passed in 3.81s`。本轮没有把secondary来源冒充官方来源，没有物化训练panel或邻接网络，也没有改变K0：工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。

下一步数据工作不应再重复同一WAF probe，而应优先解决三个可交付缺口：获取官方permits columns与小样本或可信的City mirror；获取官方ACS/TIGER资产或可验证的离线官方快照；从Final Ordinance/Narrative确定effective date与affected polygon。三项满足后才能下载全范围数据、构造Chicago tract-month panel和版本化adjacency。

### 12.32 Chicago官方条例、法律边界与Cook County宗地元数据补强

本轮继续按完整`urban-data-seeker`工作流处理真实数据基础，没有新增抽象因果门。条例数据路由由确定性router选择`legistar-platform`，宗地发现使用`data-gov-catalog`；附件下载前核验了eLMS官方matter身份、附件名称、HTTP 200和文件尺寸。只下载了与单一matter直接相关的两个官方小型附件：Final Ordinance 26,692字节、Final Narrative and Plans 291,862字节，总计318,554字节；没有下载全城permits、parcel、ACS或TIGER数据。

新增并hash绑定的原始/派生证据包括：

- eLMS matter `O2026-0024863`完整单条JSON；
- `O2026-0024863 Final Ordinance.pdf`及本地Apple Vision OCR文本；
- `O2026-0024863 Final Narrative and Plans.pdf`及本地Apple Vision OCR文本；
- Data.gov对Cook County Parcel 2021数据集`77tz-riq7`的官方目录记录；
- ArcGIS item `34021b4f3b834a69bf737e6c3344888e`和Cook County Hub layer metadata。

两个PDF均为扫描件，没有可提取文本层。OCR只作为派生证据，结论始终绑定原始PDF的字节数和SHA-256，不把OCR文本替代为官方原文。Final Ordinance明确给出：

- zoning action：`RS-3 Residential Single-Unit -> RM-4.5 Residential Multi-Unit`；
- 北界：West Marquette Road以南166英尺的平行线；
- 南界：West Marquette Road以南191英尺的平行线；
- 东界：South Bishop Street；
- 西界：South Bishop Street以西、与其平行的巷道；
- 因此南北向深度为25英尺；
- 生效规则：`after its passage and due publication`。

Final Narrative确认proposed zoning为`RM-4.5`、lot area为3,115平方英尺、拟保留/改造为2个dwelling units、existing building height为28英尺。eLMS同时记录`finalActionDate=2026-07-15T15:00:00Z`和`lastPublicationDate=2026-07-17T14:25:18Z`。但Swagger只声明`lastPublicationDate`是date-time字段，没有说明它是否就是条例中具有法律效力的`due publication`日期。因此当前只能确认生效规则和两个候选时间戳，仍固定`effective_date_verified=false`，不能直接把7月17日当作因果处理起点。

受影响范围也被更精确地区分为两种状态：

- `legal_treatment_boundary_verified=true`：官方Final Ordinance已经给出完整法律边界；
- `machine_treatment_polygon_verified=false`：尚未取得并交叉核验可计算的官方parcel polygon。

Data.gov进一步发现Cook County官方历史宗地数据`ccgisdata - Parcel 2021`。ArcGIS item owner为`Cook_County_GIS`，source/access information指向Cook County Government/Cook County Clerk，访问为public，许可说明存在，geometry type为`esriGeometryPolygon`，并包含`name`/PIN14、`pin10`、`censustract_geoid`、面积和中心点字段。这解决了“是否存在可用官方宗地源、字段和许可”的发现问题。但县GIS主机对PIN查询、point spatial query、OGC Features和WFS bounded query均超时，Hub query返回403，因此没有取得目标PIN `2020302029`的行或geometry。官方parcel metadata不能替代目标parcel sample。

审计器现处理JSON、PDF和OCR文本三类证据，共16个raw artifacts，15/15项交叉检查通过，状态仍为`bounded_evidence_valid_not_panel_ready`。新report digest为`ce6d2cd50068ade4959ff8a6037e8e1d54636af67779fa4e3a8a1c07f33a605e`；更新后的source contract digest为`d86f38b50c28a5032b54964488b15c541f0e896c099adc82945bdbbc9b0a7072`。Chicago因果链聚焦回归为`58 passed in 1.07s`，加入AI Urban技能审计、shared Kernel readiness、forcing normalization/admission和SRTM面积数学后的筛选回归为`121 passed in 2.06s`。仓库当前没有安装`ruff`，因此没有伪报lint通过；Python语法编译和`git diff --check`均通过。

非补偿式结论没有变化：

- `treatment_to_unit=false`，原因从“只有地址点”收敛为“法律边界已有，但机器polygon和effective onset仍缺”；
- `panel_materialization_ready=false`；
- `panel_materialization_admitted=false`；
- `causal_estimation_admitted=false`；
- `effect_application_admitted=false`；
- Kernel科学支持、领域泛化和K0继续`fail_closed`。

下一步数据优先级应为：第一，通过Cook County官方静态导出、可校验离线快照或恢复后的bounded FeatureServer取得PIN `2020302029` polygon，并与条例3,115平方英尺、25英尺深度和地址点做面积/包含关系核验；第二，从Chicago法定publication记录或City Clerk语义文档核验`due publication`，固定effective onset；第三，继续寻找官方permits字段与单行样本；第四，再获取官方ACS/TIGER全覆盖并构造tract-month panel与版本化邻接。没有前三项时，不应开始效果估计。

### 12.33 Chicago Building Permits官方字段语义与缺失机制补强

本轮继续优先处理真实observed-outcome数据基础，没有新增Kernel抽象合同。`urban-data-seeker`确定性路由将`ydr8-5enu`选择为`socrata-platform`，confidence high、route type为URL/domain fingerprint。Chicago portal metadata、bounded resource sample和Socrata全局目录`api.us.socrata.com`均返回403；结合前序OData/v3结果，继续标记`browser_or_waf`，没有将403解释为认证缺失，也没有请求full export。

为避免继续撞同一WAF入口，本轮改查City of Chicago官方GitHub组织。GitHub repository metadata确认：

- repository：`Chicago/dev.cityofchicago.org`；
- owner：`Chicago`，type为`Organization`；
- visibility：public；
- fork：false；
- description明确说明该仓库提供City of Chicago及其姐妹机构的开发者资源和技术更新。

在固定commit `431215dd236112dfe2e644d327637dd7afb00c3b`中取得三份由`Open Data Portal Team`发布、front matter直接标记`ydr8-5enu`的官方文档：

1. 2019-07-09 `Building Permits Dataset Changes`：记录新增`APPLICATION_START_DATE`、`PROCESSING_TIME`、`COMMUNITY_AREA`、`CENSUS_TRACT`、`WARD`、`XCOORDINATE`、`YCOORDINATE`和`REVIEW_TYPE`，并将`ESTIMATED_COST`改名为`REPORTED_COST`。其中`PROCESSING_TIME`定义为`APPLICATION_START_DATE`到`ISSUE_DATE`的天数。
2. 2017-11-20 `Building Permits - Issue Date`：说明此前约5%记录的主source-system `ISSUE_DATE`为空；City后来只在主字段为空时使用第二数据库字段作为合理回填，不覆盖已有日期。该文档当时声明所有记录均有`ISSUE_DATE`。
3. 2019-07-16 `Building Permits Dataset Contact Columns Removed`：说明15组contractor地址和电话字段因隐私与滥用风险从bulk dataset移除，个别permit的contact address只能通过单许可证查询获得。

这些证据对Paper6/GWM纵向因果设计有三个直接约束：

- `ISSUE_DATE`不是纯单源观测变量，可能来自两个source-system日期字段，必须在数据字典和敏感性分析中声明；
- permit issue只证明许可证发放，不证明construction start，且catalog明确说明缴费前不得开工，不能把`ISSUE_DATE`直接解释为实际建造时点；
- contact字段缺失是制度性隐私删列，不是随机缺失，不能把它作为一般MAR缺失处理或用其缺失模式构造伪混杂变量。

本轮新增4个hash-bound artifact：3份官方字段语义文档和1份官方repository metadata。Chicago审计现覆盖20个raw artifacts，19/19项检查通过，状态仍为`bounded_evidence_valid_not_panel_ready`。新audit report digest为`90b097841f6ae1b7d6a2d47f9df80ed2001beb67d8384474b067242e91d33d0c`，source contract digest为`9a2ce61121588eb95b81a81709f6db7e3e04d68375cf89a0e5545cf79538c2ca`，聚焦回归为`58 passed in 0.95s`。

严格准入状态没有变化：官方历史change log不能替代2026 current columns、字段类型、license或row sample，故`schema_probe_status=blocked`、`sample_validation_status=blocked`、`outcome_to_unit=false`、`panel_materialization_ready=false`、`causal_estimation_admitted=false`、`effect_application_admitted=false`。下一步仍需通过可验证City mirror、恢复后的Socrata bounded query或哈希可核验的官方离线快照，取得当前columns与至少一条去敏permit row；取得后还必须验证permit/CENSUS_TRACT或coordinates到目标tract vintage的crosswalk，不能只凭2019文档中的字段名称打开gate。

### 12.34 Chicago 2026事件的时间窗降级

在补齐permits时间字段语义后，本轮进一步审计了当前事件是否具备纵向效果估计的最小时间窗。结论是：`O2026-0024863`不能继续作为近期Paper6效果估计pilot，只能保留为数据来源、法律边界和空间crosswalk fixture。

冻结证据为：

- City Council passage：`2026-07-15T15:00:00Z`；
- eLMS `lastPublicationDate`：`2026-07-17T14:25:18Z`，但法律生效语义仍未独立核验；
- Building Permits官方catalog modified date：`2026-07-21`；
- target cadence：monthly。

在上述时间界限下，可用的完整post-treatment month为0。即使source columns、license和单行样本立即补齐，也无法满足面板验证器最宽松的“至少一个完整post-treatment period”结构要求，更不可能执行可信的pretrend、temporal placebo、动态权重、geographic holdout或不确定性估计。因此新增hash-bound检查`monthly_post_treatment_horizon_unavailable=true`，并把`unit_time_alignment`显式关闭，reason为`no_complete_monthly_post_treatment_period`。

candidate temporal role现固定为`crosswalk_fixture_not_effect_estimation_pilot`。这不是否定该事件的数据价值：它仍可验证eLMS matter解析、条例OCR、法律边界、地址到PIN/tract链和未来parcel geometry crosswalk；但不能产生政策效果结论。真正的Chicago纵向因果pilot应另选具有充分历史post window的已生效事件，并沿用本候选已经建立的官方source/crosswalk审计链。

审计仍包含20个raw artifacts，检查增加到20/20通过；最新audit digest为`0bc3c98c81585b36360c88b972b747b833c0bde766e59c1137df75de87b9df2e`，source contract digest为`25298a1e433f24d429e9f0630ef5e80658ff2a1a11a6055091a4dbe9dd9d282b`。更新后聚焦回归为`58 passed in 0.89s`。所有panel、causal estimation、effect application、generalization和K0状态继续fail-closed。

下一步路线应分为两条：继续用2026事件完成官方parcel polygon和effective-date语义crosswalk；同时从eLMS检索至少提前12个月生效、具有明确Final Ordinance/Narrative和可定位地址/边界的Chicago历史zoning事件，作为真正的纵向估计候选。历史候选仍必须先通过同一五来源角色、六crosswalk gate和行级面板合同，不能因时间窗较长而降低准入标准。

### 12.35 Chicago历史zoning cohort候选筛选

本轮已经执行12.34节要求的第二条路线，但只做到bounded metadata screening，没有下载历史附件。`urban-data-seeker`路由到`legistar-platform`后，Chicago eLMS `/matter`使用以下非全量过滤条件：

- `finalActionDate < 2025-01-01T00:00:00Z`；
- `status = 90-Final`；
- 至少存在一个`attachmentType = Exhibits`附件；
- full-text query为`Zoning Reclassification`；
- `top=100`，只取第一页。

官方响应的filtered count为290，第一页100条中有88条title确实以`Zoning Reclassification`开头。search响应即使请求attachments也不返回完整附件列表，因此随后只对三个`Passed`、单地址、2024-10-30 final action、2024-11-21 publication的候选执行matter detail probe：

- `O2024-0012247`：1228 W Race Ave，App No. 22539T1；
- `O2024-0012334`：2437 S Troy St，App No. 22544T1；
- `O2024-0012532`：6453 N Bosworth Ave，App No. 22570T1。

三条detail均确认同时存在精确命名的`Final Ordinance.pdf`和`Final Narrative and Plans.pdf`，状态为`90-Final/Passed`。以publication后的首个完整月2024-12起、permits catalog最新完整月之前为界，至少有19个完整post-publication months，时间条件显著优于2026 fixture。

但这仍只是历史cohort筛选种子，不是估计面板：三份Final文件尚未下载和解析，legal boundary、effective date、parcel/tract geometry、permit outcome rows、ACS/TIGER、邻接和干扰暴露均未核验；三个单地块事件也不足以自动保证positivity、平行趋势或外部有效性。当前筛选状态固定为`temporal_and_attachment_screen_pass_not_estimation_ready`，`source_and_crosswalk_ready=false`、`cohort_panel_ready=false`、`causal_estimation_ready=false`。

本轮新增1页官方过滤响应和3条matter detail，共4个JSON artifact；Chicago审计现有24个raw artifacts、23/23检查通过。最新audit digest为`30cee6be64108458c6a98244e9a8fd4b10af29667135bf2237ea838edb62955b`，source contract digest为`438ada9c31ec2c239c20727b6eca75fb4af0e4569ba6ed61b16db760c15ef4a3`，更新后聚焦回归为`58 passed in 0.97s`。2026事件继续只作crosswalk fixture；历史三候选继续只作cohort screening，不改变任何panel、effect、generalization或K0准入状态。

下一步应先对三候选做附件HEAD尺寸审计和地址点地理编码，选择文档体量可控、法律边界清晰且不跨多个tract的候选；随后只下载入选候选的Final Ordinance/Narrative并执行与12.32相同的PDF hash、OCR、zoning transition、publication和geometry审计。最终估计cohort还应扩展到更多历史事件，并预先冻结纳入/排除标准，避免依据结果可得性事后挑选事件。

### 12.36 历史cohort Final文档与法律文本审计

本轮按12.35节预先冻结的三候选整体继续，没有依据文件大小或OCR结果事后只挑一个事件。六份Final附件HEAD均返回200，记录了Content-Length、Content-MD5、ETag和Last-Modified；随后下载三份Final Ordinance和三份Final Narrative and Plans，总计2,898,496字节，没有请求其他历史附件或全量eLMS导出。

原始PDF均通过magic bytes、HEAD字节数和SHA-256联合校验；本地Apple Vision OCR只作为派生文本，继续由原始PDF哈希锚定。三个候选的官方条例和Narrative给出：

- `O2024-0012247`，1228 W Race Ave：`B3-2 -> B2-3`；法律边界的两条南北线分别位于North Elizabeth Avenue以东216和192英尺，因此法律宽度24英尺；lot area 2,088平方英尺；住宅单元由2增至3。
- `O2024-0012532`，6453 N Bosworth Ave：`RS3 -> RM4.5`；两条东西线分别位于West Arthur Avenue以南56.44和87.44英尺，因此法律宽度31英尺；lot area约3,885平方英尺；住宅单元由3增至4。
- `O2024-0012334`，2437 S Troy St：`RT4 -> RM5`；两条东西线分别位于West 25th Street以北232和208英尺，因此法律宽度24英尺；现有3个住宅单元增加2个至5个。OCR/site-plan中的lot area读数仍不够稳定，因此合同保持null，没有猜值。

三个条例都明确写明从passage和due publication之后生效。matter记录的Final Action均为2024-10-30，lastPublicationDate均为2024-11-21，因此时间筛选继续有至少19个完整post-publication months；但eLMS `lastPublicationDate`的法律语义仍未从独立City Clerk文档核验，故`effective_onsets_ready=false`。

同时对三个地址调用City of Chicago官方AddressPoints GeocodeServer，分别返回503、503和504。本轮不使用第三方geocoder替代官方准入，因此`official_point_addresses_ready=false`、PIN/tract crosswalk未建立、`machine_treatment_geometries_ready=false`。法律边界文本已验证不等于机器polygon已验证。

当前历史筛选状态从仅附件metadata提升为`temporal_documents_and_legal_text_ready_geometry_and_outcomes_blocked`：`final_document_evidence_ready=true`、`legal_boundary_text_ready=true`、`zoning_transition_text_ready=true`，但source/crosswalk、cohort panel和causal estimation仍为false。三个单地块事件的项目规模也说明，后续正式cohort需要更多事件和冻结抽样规则，不能仅依赖三条记录承担positivity与泛化。

本轮新增六份PDF、六份OCR文本和一份attachment/geocode preflight ledger，共13个artifact；Chicago审计现有37个raw artifacts、27/27检查通过。最新audit digest为`daf3b4c4b6444dc76d4934d1886b37022efc8050db1a634210ec893ee166a3a2`，source contract digest为`a828d323da3c25bcf1470f1d23c09ce44ebffa0200ce52cffd23d6c85ddba229`。Chicago因果链聚焦回归为`58 passed in 0.97s`，加入AI Urban技能审计、shared Kernel readiness、forcing和SRTM数学后的筛选回归为`121 passed in 2.16s`。所有panel materialization、effect application、generalization和K0状态继续fail-closed。

下一步应在City geocoder恢复后重跑三个单地址probe，取得PointAddress、PIN和EPSG:3435/WGS84坐标；随后用Cook County官方parcel service或可校验官方快照把法律边界、lot area和parcel polygon做三重核验。只有三候选的机器geometry和effective onset完成后，才应继续扩大历史事件cohort和构造tract-month treatment exposure。

### 12.37 历史事件point/tract crosswalk与zoning-map写入验证

2026年7月24日重试时，City of Chicago官方AddressPoints GeocodeServer已经恢复。三个2024候选均返回唯一`PointAddress`，并取得WGS84、EPSG:3435、PIN、ward和community；随后用FCC 2020 Census Block API把三个点固定到三个tract：

- `O2024-0012247`：PIN `1708126021`，tract `17031243400`；
- `O2024-0012334`：PIN `1625115015`，tract `17031300900`；
- `O2024-0012532`：PIN `1132323002`，tract `17031830600`。

新增`historical_event_crosswalk.json`作为可执行机器crosswalk。它逐事件绑定原始响应SHA-256，并检查规范化地址、PointAddress类型、PIN、WGS84范围、FCC block长度和block-to-tract派生。三条事件全部通过，因此`official_point_addresses_ready=true`、`official_pins_ready=true`、`point_to_tract_crosswalks_ready=true`。

同一批点在City of Chicago当前Zoning FeatureServer中均命中唯一polygon，`CLERK_DOCNO`逐条精确等于对应条例号，`ZONE_CLASS`逐条等于条例目标分区，`ORDINANCE_DATE`均为2024-10-30，地址点也均落在返回polygon内。这证明三份条例已经写入城市数字zoning map，故`current_zoning_map_polygons_ready=true`。

但该zoning polygon仍不能冒充法律parcel polygon：Race polygon面积为2,850.84平方英尺，而Narrative lot area为2,088平方英尺，比例1.365344；Bosworth分别为5,450.79和3,885平方英尺，比例1.403035。Troy的法律lot area仍为null。由此继续保持`machine_treatment_geometries_ready=false`，并明确记录`zoning_map_polygon_not_legal_parcel_polygon=true`。Cook County Parcel FeatureServer按PIN和按点查询仍超时，不能用元数据替代目标parcel样本。

Observed outcome与全市空间基础仍未关闭：Chicago Socrata metadata、columns、resource、旧rows和v3端点继续统一返回403；官方Census ACS/TIGER继续超时或403。因此尚未物化tract-month panel、版本化adjacency或动态干扰暴露，Paper6估计器没有在真实Chicago面板上执行。

当前审计包含46个raw artifacts，28/28检查通过，audit digest为`793a21afdbaef363a81e130c6a93dc50e7e5b356e0f49de3e4c3a5f9da92b66b`；事件crosswalk digest为`96231b4c56237e4f2cb297a814d33fa79f4e84cb8ed3fde71589d8564cc323e7`；source contract绑定48个artifact，digest为`0abf230403cad226496efeba641ac7f16e79ef34cb1fe7ff6e6e7a2c0238ec41`。聚焦因果链回归`48 passed`，包含AI Urban路由、shared Kernel readiness、forcing与SRTM面积数学的宽回归`90 passed`。

Kernel级状态没有被局部数据进展越权修改：工程实现`pass`、开发benchmark有效性`pass`、Kernel科学支持`fail`、领域/泛化支持`fail`、总体`fail_closed`。GWM仍表示跨领域地理空间世界模型及共享Kernel；本轮Chicago链只是UWM经验验证实例，不是GWM本身，TWM也未被修改。下一步依次关闭official permit rows、parcel/legal geometry、effective onset、更多预注册历史事件以及official ACS/TIGER adjacency，然后才物化面板并运行pretrend、placebo、interference、geographic holdout和uncertainty。

### 12.38 预注册历史cohort扩展与多源空间crosswalk

本轮没有继续新增Kernel gate，而是把Chicago UWM验证实例从3条历史种子扩展为可重复筛选的多事件cohort。`urban-data-seeker`将条例元数据路由到`legistar-platform`，将zoning、地址点、parcel和边界候选路由到`arcgis-platform`。Chicago eLMS官方`/matter`接口一次有界请求返回完整290条2023--2024候选，原始响应326,900字节。

在查看outcome rows和effect estimates之前冻结选择规则：`90-Final/Passed`、Ordinance、单地址、T1 application、final action位于2023--2024、eLMS publication lag为0--90天、截至2026-07-21至少有12个完整后期月。290条中23条入选，267条按固定理由排除；原3条种子全部保留。入选事件实际均为2024年，具有18--23个完整post-publication months。cohort digest为`35f8d6d5e2523ca3400bc87ada22e539d5511550e1fffe77c71790c1490d622c`。

23条事件的官方空间crosswalk结果为：

- 22/23有按`CLERK_DOCNO`匹配的当前zoning-map footprint；`O2024-0013362`缺少zoning feature；
- 19/23取得`score=100`的官方PointAddress、PIN和WGS84/EPSG:3435坐标；4条batch和单地址retry均未取得精确匹配，未从cohort中事后删除；
- 19/23通过FCC 2020 block-to-tract，且落入19个不同tract；
- 19/23取得City `Parcel Addresses` layer 1中的唯一PIN polygon，地址点均位于parcel内；
- 17/23完成eLMS、zoning polygon、PointAddress、parcel和tract的联合空间一致性；`O2024-0012332`虽然各来源分别有记录，但5824 N Lincoln Ave地址点不在该条例polygon内，点位当前落在无`CLERK_DOCNO`的B3-2 polygon中，因此显式判为不一致；
- `O2024-0008868`合法对应两个zoning polygons和两个目标zone class，crosswalk支持一条例多polygon，没有误判为重复记录。

当前parcel polygon对法律文本形成强交叉检查：Race为2,089.33平方英尺，对Narrative的2,088平方英尺，比例1.000635；Bosworth为3,878.41平方英尺，对约3,885平方英尺，比例0.998304。但City parcel layer没有声明历史vintage，因此只准入`current_parcel_crosswalk`，`machine_legal_treatment_polygon_verified=false`仍保持。

同时完成两个来源负裁决。Chicago official operational MapServer的Census Tract layer 84有878个polygon和`TRACT_FIPS`字段，但唯一`TRACT_CENSUS_YEAR=2000`，不得用于2020 tract panel或邻接。Permit Map layer 12为`SPADE.PWU_PERMITS`，字段语义是public-way-use permits，不得替代Building Permits observed outcome。两个来源均保留为hash-bound负证据。

扩展crosswalk digest为`95f2d7ed8422b4a44df6ffed06a913460915065cada7e6a64b2e87b9c3bc59e4`。总数据审计现有54个artifact、31/31检查通过，audit digest为`6e14094da0e6af7e24f49d48fca10d9c95a2456de02789bdf6413a160485e2a9`；source contract绑定56个artifact，digest为`1cab51d68a4497848fcda3020047aae23a29594bb64370c07701df76f41d35a0`。聚焦回归`56 passed`，宽回归`98 passed`。

当前状态是`treatment cohort materially improved, outcome panel still blocked`。23条cohort规模和19个不同tract只证明地理分散性，不证明positivity；没有Building Permits rows、2020 adjacency、effective onset和完整legal geometry之前，不物化tract-month panel，不运行Paper6 effect estimator，不升级effect、generalization或K0。GWM仍是共享Geospatial Kernel，Chicago只是UWM验证实例，TWM未修改。

### 12.39 Chicago官方Building Records真实outcome样本

本轮继续优先关闭observed-outcome数据阻塞，没有新增Kernel抽象层。`urban-data-seeker`将City of Chicago Building Permit and Inspection Records HTML应用路由到`document-portal-platform`，并用`arcgis-platform`复核官方服务目录。Building Records入口当前可访问，不再受Socrata 403阻塞；访问边界为`interactive_selection_required`，需先读取并接受公开访问用户协议，再提交CSRF保护的地址查询。

新增`probe_gwm_chicago_building_records.py`，固化完整查询链：GET agreement、POST agreement、POST validateaddress、POST doSearch，并对TLS/5xx瞬时故障执行最多三次有限重试。脚本只查询12.38节中已经通过联合空间一致性的17个预注册地址，没有扩展到全市或对照地址。每个结果页原始HTML均落盘并绑定SHA-256，同时解析当前地址级permit表的三列：`PERMIT #`、`DATE ISSUED`、`DESCRIPTION OF WORK`。

17个地址全部返回HTTP 200且精确回显输入地址。真实记录结果为：

- 16个地址存在permit history，1个地址`O2024-0010948`返回零许可；零记录页不渲染表头，因此schema判定采用16个非空页面全部一致，而不是伪造17/17表头；
- 共取得70条官方permit row，稳定许可号既有数字也有历史字母数字格式；
- 1/70条`DESCRIPTION OF WORK`为空，保持原始缺失，不做猜填；
- 18条许可晚于候选eLMS publication date，分布在11个地址；其中Race的`101063756`、Troy的`101066672`/`101066622`和Bosworth的`101058154`等记录与条例后住宅单元变更在文本上相符；
- City页面明确声明，permit issued不证明工程实际实施，也不证明工程符合许可或Municipal Code。因此`DATE ISSUED`只能作为行政许可事件时间，不能当作construction start、completion或已实现的物理状态变化。

这一步把observed outcome从“只有catalog和历史字段说明”提升为“当前官方地址级schema与真实行样本已验证”：`row_schema_verified=true`、`row_sample_verified=true`。但目标变量是tract-month内的完整许可事件计数；17个treated-address history既不覆盖各tract内全部地址，也没有untreated controls。因此`outcome_to_unit=false`、`complete_tract_permit_universe_verified=false`、`untreated_control_outcomes_verified=false`、`tract_month_outcome_panel_ready=false`继续保持。18条post-publication记录也不能解释为因果效果，因为publication尚未被独立验证为法律effective onset。

ArcGIS旁路完成了明确负裁决。City官方`ExternalApps`目录共有32个服务，唯一名称含Permit的服务是`ExternalApps/Permit_Map`；其21个图层中唯一名称含permit的叶图层仍是`SPADE.PWU_PERMITS`，没有Building Permits图层。目录与MapServer root metadata均已hash绑定，因此后续不应再把该ArcGIS服务作为building outcome候选。

当前数据审计含75个raw artifact、39/39检查通过，audit digest为`25334ef06aadc1a2c19f3bba25a2b41b89b663875d96883d5cf7b994c0d0fb43`；Building Records probe digest为`cc2acbfe5afa95abd59fcf745f2c51f7325ce531f41dff075a38f88f804d6131`；source contract绑定77个artifact，digest为`80b2ac047d21226f3802b92324a9810437ad4bb859ca004b1c2fb93a5e059731`。新增与聚焦回归为`76 passed`，包含shared Kernel、Paper6、forcing和SRTM检查的宽回归为`147 passed`。

Kernel状态仍严格分层：工程实现`pass`、开发benchmark`pass`，Kernel科学支持、领域泛化和K0继续`fail_closed`。下一步数据主线不再是寻找单条permit样本，而是取得可批量覆盖完整tract和对照tract的官方Building Permits导出或可验证City mirror；并行关闭official 2020 TIGER adjacency、effective onset与历史legal geometry。只有完成这四项，才能物化真实tract-month panel并运行Paper6的pretrend、placebo、interference、geographic holdout和uncertainty。

### 12.40 Cook County secondary tract geometry与拓扑质量否决

本轮沿`urban-data-seeker -> us-tiger-boundaries`继续关闭2020 tract adjacency阻塞。已确认具体官方候选为`TIGER2020/TRACT/tl_2020_17_tract.zip`，但`www2.census.gov`仍由Cloudflare返回403；Census官方TIGERweb的`Census2020` ArcGIS服务在IPv4、HTTP和HTTPS下均连接超时。因此仍未取得可准入的official TIGER geometry。

为验证Kernel的interference-network构造链而不冒充官方数据，本轮使用已经被合同标记为secondary的Census Reporter `tiger2024` API，执行上限25 MB的受控Cook County tract请求。实际响应825,593 bytes，包含1,332个唯一`14000US17031...` tract、全部为合法非空Polygon，并覆盖17个联合空间一致的事件tract。原始GeoJSON保存为`census_reporter_tiger2024_cook_county_tracts.json`，继续固定`authority_status=verified_secondary_not_official_admission`。

新增`build_gwm_chicago_provisional_tract_adjacency.py`，使用Shapely STRtree构造两种无向拓扑：queen定义为polygon边界至少一点接触，rook定义为共享正长度边界。结果可重复生成1,332个node、2,458条queen edge和1,081条rook edge，17个目标tract全部存在且都有queen邻居。

但“边表生成成功”没有被解释为“网络可用”。拓扑QC显示secondary简化geometry严重破坏边界连续性：queen图有100个connected component和67个isolated tract，rook图有378个component和234个isolated tract，rook/queen edge ratio仅0.439788；`17031242700`、`17031243500`、`17031836000`三个目标tract没有rook邻居。因此`provisional_topology_quality_pass=false`、`provisional_interference_network_usable=false`、`official_adjacency_constructed=false`、`network_to_unit_time=false`。该负结果说明完整feature coverage不足以证明topology quality，不能通过buffer或猜测邻居来强行开gate。

同时修正source candidate的分析单元命名：`target_unit`从错误的`2024_census_tract`改为`2020_census_tract`。FCC crosswalk使用的是2020 block/tract；`tiger2024`只是secondary geometry数据版本，不能混写为tract definition。

当前审计包含77个raw artifact、42/42检查通过，audit digest为`592efdec119ae506a85edf24eefb4c3750de29c381267e3df1bba773bc3a62eb`；provisional adjacency digest为`07520fd49560ff5f747547a6dd068e2d1c5e5cd54cff9b2c07859a1804ac915f`；source contract绑定79个artifact，digest为`80e6f9c04acde0c9e8b5bf450ab474b54b101701f45f39b67da96dbd24a0ae4f`。包含Chicago数据链、Paper6、shared Kernel、forcing和SRTM检查的宽回归为`150 passed`。

下一步不能继续优化这份简化geometry的容差来制造表面连通性。应优先取得官方TIGER/Line原始边界或具有明确unsimplified lineage的政府快照，重新生成queen/rook并要求拓扑QC通过；同时继续寻找完整Building Permits tract universe与untreated controls。Paper6、effect application、泛化和K0继续`fail_closed`。

### 12.41 Official TIGER 2020身份、许可与ISO metadata闭合

本轮继续沿`urban-data-seeker -> us-tiger-boundaries`推进，并用`data-gov-catalog`补充官方目录解析。首先对本机Downloads、Documents、Desktop和项目目录执行文件名与空间格式检索，没有发现`tl_2020_17_tract`、Illinois tract ZIP/shapefile或可验证离线快照，因此没有把未知本地文件纳入证据。

Data.gov v4目录以`Illinois Census Tracts 2020`查询返回唯一精确记录：`TIGER/Line Shapefile, 2020, State, Illinois, Census Tracts`。记录组织为`U.S. Census Bureau, Department of Commerce`、类型为Federal Government，publisher为Census Bureau Geography Division Spatial Data Collection and Products Branch，issued/modified均为2020-01-01，关键词同时包含Illinois、IL、17、Polygon和Census Tract，许可为CC0 public domain。唯一ZIP distribution为`tl_2020_17_tract.zip`，media type为`application/zip`，download URL精确指向`TIGER2020/TRACT/tl_2020_17_tract.zip`。

同时从GSA harvest cache取得48,058 bytes的Census原始ISO 19115 XML。结构化XML解析确认：file identifier为`tl_2020_17_tract.shp.iso.xml`、feature type为`Census Tracts`、reference system为NAD83 `EPSG:4269`、Illinois bbox为`[-91.513079, 36.970298, -87.019935, 42.508481]`，并声明在线TIGER/Line无偿访问。ISO transfer URL与Data.gov distribution逐字一致。

因此official spatial source状态从笼统`review`细化为：`metadata_probe_status=pass`、`license_status=pass`、`geography_coverage_status=pass`、`schema_probe_status=review`、`sample_validation_status=blocked`。实际ZIP仍由`www2.census.gov`返回403，`meta.geo.census.gov`、TIGERweb和`ftp2.census.gov`均连接超时；尚未读取`.shp/.dbf/.prj`字节，也没有实际验证`GEOID/STATEFP/COUNTYFP/TRACTCE`字段。因此`official_tiger_geometry_verified=false`和`official_adjacency_constructed=false`不变。

source candidate的official spatial source同时从错误的2024 URL切换为`source_id=tiger_2020_illinois_tract_boundaries`及`TIGER2020/TRACT/tl_2020_17_tract.zip`；secondary Census Reporter `tiger2024`仅保留为被拓扑QC否决的诊断输入，不再承担official source identity。

当前审计含79个raw artifact、44/44检查通过，audit digest为`c2c89482ffa3390d586d342f4109587f8a2dc703cd7854dfdb81dc28732ddb3a`；source contract绑定81个artifact，digest为`bbc43e8937344c9eebf5a642f04fc686a8d983d21f4c40852746e232d517febd`；宽回归为`150 passed`。下一步应直接解决已确认ZIP的字节获取或导入有完整Census lineage的政府离线快照，不再重复来源发现；另一主线仍是完整Building Permits tract universe与untreated controls。

### 12.42 Official TIGER 2020几何与Cook tract邻接正式准入

本轮解决了12.40和12.41的核心阻塞。命令行访问`www2.census.gov`仍返回403，但使用真实Safari会话打开已经核验的官方URL后成功取得`tl_2020_17_tract.zip`；Safari自动展开为7个shapefile组件。原始压缩包字节没有保留，因此没有伪造ZIP摘要；项目保留全部展开组件并逐文件记录SHA-256，来源仍由Data.gov精确distribution URL和Census ISO metadata共同锚定。

实际文件验证结果为：

- Illinois全州3,265个2020 Census tract；
- Cook County `STATEFP=17, COUNTYFP=031`共1,332个唯一tract；
- geometry全部为合法非空Polygon；
- CRS为NAD83 `EPSG:4269`；
- `STATEFP/COUNTYFP/TRACTCE/GEOID`全部存在，且GEOID可由前三者一致重建；
- 全州bbox与官方ISO metadata逐项一致。

新增`build_gwm_chicago_official_tract_adjacency.py`，只接受上述官方shapefile及既有预注册spatial crosswalk。它用相同的queen/rook定义重建Cook County内部无向图。官方结果与先前次级简化geometry形成了关键对照：

| 指标 | Census Reporter次级简化geometry | Official TIGER 2020 |
|---|---:|---:|
| tract节点 | 1,332 | 1,332 |
| queen边 | 2,458 | 4,410 |
| rook边 | 1,081 | 3,416 |
| queen连通分量 | 100 | 1 |
| rook连通分量 | 378 | 1 |
| queen/rook孤立节点 | 67/234 | 0/0 |
| 目标tract无rook邻居 | 3 | 0 |
| topology QC | fail | pass |

这证明此前的失败来自次级简化geometry破坏边界拓扑，不是Kernel的邻接算法错误。17个联合空间一致事件分别落入17个tract，全部存在于官方图且全部具有rook邻居。官方邻接artifact内部digest为`0febf92459507466e8987ad80f0d9ba0ce0158ab3a251f5e2ad36a9f7d3ce21f`。

门禁只打开已经被证据支持的部分：

- `spatial_units` metadata/sample ready：true；
- `interference_network` metadata/sample ready：true；
- `network_to_unit_time`：true；
- official Cook-internal interference network：admitted；
- cross-county interference、dynamic network：false；
- panel materialization、causal estimation、effect application：false；
- Kernel scientific support、domain generalization和GWM K0：继续`fail_closed`。

没有打开Paper6估计的原因很具体：当前70条Building Records记录仍只是17个treated address的历史，不是完整tract permit universe，也没有untreated controls；official ACS纵向混杂变量、机器法律treatment geometry和独立核验的effective onset仍未闭合。官方邻接解决的是“谁可能影响谁”，没有解决“每个tract-month发生了什么”以及“处理为何可识别”。

当前Chicago审计含87个raw artifact、46/46检查通过，audit digest为`b23cec792c319d80665f2bfa64c9f9f131aac22c7056213cd18f4029e858d53b`；source contract绑定89个artifact，digest为`ff223c18eb036389a3cdd4a373aed7ae1ce1d0301a3f28ff0601dac38af3cb8d`。新增聚焦测试与Chicago、Paper6、shared Kernel、AI Urban skill、forcing和SRTM宽回归为`165 passed`。

下一主线应停止继续寻找tract边界，直接补完整Building Permits tract universe与untreated controls。取得后先物化只含行政许可事件含义的tract-month outcome panel，再依次执行无未来泄漏、positivity/ESS、pretrend、placebo、interference exposure、geographic holdout和uncertainty门禁。GWM仍表示跨领域地理空间世界模型及共享Geospatial Kernel；Chicago只作为UWM经验验证实例，TWM没有被本轮修改。

### 12.43 Chicago官方Building Permits街区月度结果面板物化

本轮使用已经完整安装的AI Urban Scientist数据获取能力继续推进真实数据基础。`urban-data-seeker`将官方Building Permits数据集`ydr8-5enu`确定性路由到`socrata-platform`；命令行访问仍返回95字节HTTP 403，因此按`browser-automation`访问边界，通过隔离的headed Chrome/CDP会话取得官方Socrata元数据、当前行样本、tract汇总、历史/当前tract编码交叉样本和City of Chicago Data Terms of Use。没有保存cookie或凭证，也没有采集已经由City因隐私原因移除的contact字段。

冻结查询窗为`2023-01-01`含至`2026-07-01`不含，共42个完整月。只获取10个非联系字段：`id`、`permit_`、`permit_type`、`application_start_date`、`issue_date`、`work_type`、`reported_cost`、`census_tract`、`latitude`和`longitude`。官方快照共114,896行，分成`25,000 + 25,000 + 25,000 + 25,000 + 14,896`五个有序分片；每个分片均验证HTTP 200、字节数、SHA-256、字段白名单、时间窗、offset、全局`id`顺序以及`id/permit_`唯一性。

同时取得官方TIGER/Line 2020 Illinois PLACE几何。全州1,466个place中，Chicago city的`GEOID=1714000`；与官方Cook County tract做正面积相交后得到799个Chicago tract。这个城市单元全集独立于permit结果和treatment选择，可用于构造包括零事件格在内的结果面板，避免只保留有许可记录的街区所造成的选择偏差。

新增`build_gwm_chicago_permit_tract_month_panel.py`，其实现链为：

1. 验证Socrata metadata、许可、使用条款、CDP capture manifest和五个原始分片的哈希与查询合同；
2. 使用官方TIGER 2020 polygon和点在多边形内判断进行空间归属；坐标可唯一定位时以点位为准，点位缺失时才允许使用可映射到官方2020 GEOID的源`CENSUS_TRACT`；
3. 对Socrata numeric tract丢失前导零做六位补零，但只接受与官方GEOID集合相交的值；Race地址样本确认当前`243400 -> 17031243400`，旧值`2434`不能直接冒充2020 tract；
4. 点位与源tract冲突时保留冲突诊断并使用点位，不静默覆盖证据；无法解析的行保持未解析，不做猜测插补；
5. 在799个tract和42个月的笛卡尔积上零填充，按17个事件tract、84个queen邻接干扰tract和698个queen缓冲区外候选对照tract赋予分析角色。

实际空间归属结果为：85,157行的点位与源tract一致，363行由点位覆盖冲突源tract，27,520行由点位恢复缺失或旧版源tract，198行在无点位时使用有效源tract；共113,230行进入Chicago面板，占原始快照98.549993%。另有1,658行因缺少可用坐标和2020 tract而未解析，8行定位在Chicago city单元全集外。最终面板严格包含`799 × 42 = 33,558`个唯一tract-month，许可计数总和113,230，其中5,289个零事件格。面板digest为`3d8dbcfdb6a28b062b1597102ac65ec6abc4b97bd9a5c321da582c28942ae7b5`。

这一步确实使用了传统常规GIS算法：CRS核验、等面积投影后的polygon面积相交、point-in-polygon、TIGER GEOID连接、queen/rook邻接和空间缓冲角色划分。Geospatial Kernel的增量不在于重新发明这些算法，而在于把它们置于可验证的时空合同中：来源、许可、数据版本、空间归属优先级、缺失机制、冲突处理、时间语义、干扰网络和因果准入边界都成为机器可检查状态。GIS负责可靠地计算空间关系；Kernel负责规定这些空间关系在世界模型的状态更新、干扰传播和因果推断中何时可以被使用、何时必须失败关闭。

为承接真实数据获取，shared Geospatial Kernel的纵向来源合同从只允许probe升级为支持受限批量快照：整库下载授权仍为false；只有`probe_only=false`且`bounded_bulk_download_authorized=true`时才允许`bulk_download_performed=true`。受限数据获取不能自行打开`training_panel_materialized`、`panel_materialization_admitted`或任何因果/effect gate。来源合同现绑定117个artifact，contract digest为`4fe066a1370e0be2fd7141d6d894547de8ba2cdd8ec87b0d6c81ae2bdc0d2e8e`；Chicago数据审计绑定115个artifact，52/52检查通过，audit digest为`6aa07d4af6f191452bbb43d04bb31152668325391124df75097cc337ab957d8b`。

新增聚焦测试与Chicago、Paper6时空因果合同、shared Geospatial Kernel、UWM/DAM-GK、AI Urban Scientist适配、forcing、SRTM、空间拓扑和时间上下文宽回归共`187 passed`。Python语法编译、产物重建一致性和差异格式检查均通过。

当前状态需要分成两层理解：

- 已完成：官方当前metadata/schema/terms、42个月完整官方行快照、官方2020 Chicago tract全集、候选对照结果、零填充tract-month结果面板和固定Cook邻接；
- 仍关闭：完整空间归属、候选对照的全局未处理身份、完整zoning事件全集、机器法律treatment polygon、独立核验的effective onset、官方纵向混杂变量、无未来泄漏全检查、positivity/ESS、pretrend、placebo、动态干扰、地理holdout和不确定性；
- 因而`observed_outcome_panel_materialized=true`，但`tract_month_outcome_panel_ready=false`、`outcome_to_unit=false`、`panel_materialization_ready=false`、`causal_estimation_admitted=false`和`effect_application_admitted=false`；
- `ISSUE_DATE`仍只表示行政许可事件，不代表construction start或completion；698个单元只能称为`candidate_control_outside_queen_buffer`，不能称为已验证untreated controls。

这轮修改发生在GWM共享Geospatial Kernel及其UWM Chicago实证验证链。GWM仍指跨领域地理空间世界模型，UWM仍指城市系统实例，Chicago只是UWM经验场景；TWM仍指国土/土地系统实例，本轮没有修改TWM模型或结论。下一步不应直接运行Paper6效果估计，而应先分析1,658条未解析记录的时间、permit type和缺失机制，判断空间缺失是否与处理或结果相关；并补齐完整历史zoning事件全集与effective onset，冻结真正的untreated/control资格，再获取按月可对齐的官方混杂变量。只有这些门禁通过后，才进入Paper6的时空因果诊断和估计阶段。

### 12.44 Building Permits空间缺失机制与官方坐标恢复

本轮直接执行12.43节的第一优先级，没有把1,658条未解析记录简单删除，也没有把旧`CENSUS_TRACT`强行解释为2020 tract。初步缺失诊断显示，1,658条中1,613条属于`PERMIT – EXPRESS PERMIT PROGRAM`，其未解析率为2.5211%；相比之下Renovation/Alteration为0.1348%、New Construction为0.0432%、Easy Permit为0.0105%。工作类型主要为Monthly Maintenance、Electrical Work、Fire Alarm和Administrative Change。因此空间缺失明显与permit制度/类型相关，不能假设MCAR，也不能仅凭总体缺失比例较小而忽略。

通过原42个月时间窗内的有界Socrata查询，取得全部1,856条缺`LATITUDE`记录的公开项目空间补充字段：street number/direction/name、PIN、community、ward以及`XCOORDINATE/YCOORDINATE`。仍未获取任何`contact_*`字段。补充快照共587,127字节、1,856个唯一`id/permit_`，与原始许可快照的缺纬度ID全集逐项一致；1,672条具有X/Y，1,853条具有街道号和街名。

官方当前样本同时包含X/Y和经纬度。将X/Y按Chicago发布的Illinois State Plane East `EPSG:3435`转换到TIGER的`EPSG:4269`后，经度误差`7.1e-14`度、纬度误差`4.7e-12`度，远低于冻结的`1e-8`度容差。因此面板构建器加入第二点位层：只有合法非零State Plane坐标转换后唯一命中一个官方TIGER polygon才准入。1,629条满足候选坐标范围，其中1,542条恢复了原本未解析的许可，另87条与已有有效源tract一致；没有通过旧tract字符串猜测恢复。

剩余116条涉及47个唯一公开项目地址。新增可重复请求构建器，把`OBJECTID -> address -> permit IDs`映射和请求digest冻结后，一次调用City of Chicago官方AddressPoints `geocodeAddresses`。完整返回47个ResultID：8个地址为`score=100`的`PointAddress`，恢复44条许可；3个92.78分结果把E/W或N/S方向匹配反了，1个O'Hare地址只有76分，35个未匹配。只有100分PointAddress、请求地址前缀一致、有限坐标且唯一命中一个TIGER tract的结果准入，4个模糊匹配全部拒绝。

空间归属结果由此从113,230条提升到114,816条，占114,896条官方快照的99.930372%；未解析量从1,658降到72，另有8条官方坐标落在Chicago city tract全集外。面板仍为严格的`799 × 42 = 33,558`行，许可计数总和114,816，零事件格5,224个。新panel digest为`94067555dbda15a4cc57795d9f90acfcb44530a68ae2905c2cf0bb3305fddeb7`，缺失诊断digest为`6d1085f5994566c8aef934210620418800ca2017873f23f257d66ae4b9305374`。

剩余72条仍非随机：65条属于Express Program，工作类型以24条Monthly Maintenance和21条Administrative Change为主，且26条来自非标准O'Hare地址。它们没有被低分地址结果或旧tract值补齐。当前空间证据优先级固定为：官方发布WGS84点、官方State Plane点、官方AddressPoints精确点、有效2020源tract；每层都要求唯一TIGER polygon命中。

Chicago数据审计现绑定120个artifact、53/53检查通过，audit digest为`057511f9f90fa9aaab4cbb98330704130c567718ec52bc88878339112fece455`；source contract绑定122个artifact，digest为`a08c210e496d2f6cc379b4076dd9c169a6a11f37dcfb796b695b6c7f663f0b83`。状态仍严格分层：`observed_outcome_panel_materialized=true`，但72条未解析意味着`complete_spatial_assignment_ready=false`和`outcome_to_unit=false`；候选对照未验证全局未处理、完整treatment universe/effective onset/longitudinal confounders仍缺，因此`panel_materialization_ready=false`、`causal_estimation_admitted=false`、`effect_application_admitted=false`和GWM K0继续关闭。

新增聚焦测试及Chicago、Paper6时空因果合同、shared Geospatial Kernel、UWM/DAM-GK、AI Urban Scientist适配、forcing、SRTM、空间拓扑和时间上下文宽回归共`188 passed`。

下一步可以对剩余14条带PIN的记录使用City Parcel Addresses polygon做独立PIN交叉验证，但多PIN和历史vintage必须单独裁决；对O'Hare/大型设施类地址应建立facility-level空间语义，而不是降低地址匹配分数。更重要的因果主线仍是完整zoning事件全集、effective onset和纵向混杂变量。GWM仍是共享Geospatial Kernel，Chicago仍是UWM经验验证实例，TWM未被修改。

### 12.45 Chicago跨县城市边界修正与剩余空间证据负裁决

本轮复核发现12.43和12.44把Chicago城市单元全集错误地限制在Cook County。官方TIGER/Line 2020 Illinois PLACE `GEOID=1714000`与全Illinois tract做正面积相交后，Chicago实际包含801个tract：Cook County 799个，DuPage County 2个。新增单元为`17043840000`和`17043840801`，Chicago面积占比分别为0.540772736和0.015454016。前者包含O'Hare官方设施代表点，后者虽然城市面积占比较小，但仍满足预先固定的正面积相交成员规则，不能因当前permit计数或研究便利而删除。

新增`build_gwm_chicago_official_city_tract_adjacency.py`，直接从官方全Illinois tract和Chicago PLACE几何构造城市内部拓扑。801节点的queen图有2,636条边，rook图有1,889条边；两图均为单一连通分量且无孤立节点。两个DuPage单元通过真实共享边界接入Cook单元，因此`network_to_unit_time_ready=true`和`official_cook_dupage_city_internal_network_ready=true`。这只证明Chicago城市内部的固定2020空间网络完整，不证明城市边界外的干扰已观测，所以`outside_city_interference_ready=false`、动态网络和因果估计继续关闭。

Building Permits面板随后按同一801单元全集正式重建。原始官方快照仍为114,896行，空间准入仍为114,816行，未解析仍为72行，城市外仍为8行；新增DuPage单元没有改变许可总量。零填充面板从`799 × 42`修正为`801 × 42 = 33,642`行，17个事件tract、84个queen干扰tract和700个queen缓冲区外候选对照tract，零事件格5,308个。正式panel digest为`352731108199f82fa76b3edaffd0f7bfb295af413fb3c3c10145026b7d1119b3`。

同时完成剩余空间证据裁决。对14条带PIN记录的14个唯一PIN查询官方Parcel Addresses，返回11个唯一parcel polygon，3个PIN无结果；11个polygon都能唯一落入TIGER tract，但没有一条许可地址与当前parcel地址达到准入一致性，另有1条许可包含多个PIN。因此PIN恢复准入数为0；当前parcel也不是历史parcel vintage，不能仅凭PIN把项目位置写入面板。

官方Airports图层只有O'Hare和Midway两个设施代表点，不是机场polygon或项目位置。O'Hare代表点位于`17043840000`，可为共享`10000 N BESSIE COLEMAN DR`地址的26条许可提供facility context，但不能把26个项目全部指定到代表点所在tract。系统因此保留`facility_context_ready=true`，同时固定`facility_level_permit_tract_assignment_ready=false`和`facility_point_not_permit_location=true`。72条未解析记录没有因新增证据而被静默插补。

这次修正进一步明确了传统GIS与Geospatial Kernel的分工。传统GIS算法负责PLACE/tract正面积相交、CRS一致性、point-in-polygon、parcel polygon归属和queen/rook邻接；Geospatial Kernel负责冻结单元成员规则、数据版本、证据优先级、负匹配裁决、网络作用域与因果准入。算法能算出一个空间关系，不等于该关系具备项目位置或因果识别语义；PIN地址不一致和机场代表点正是必须失败关闭的实例。

Chicago数据审计现绑定126个artifact、55/55检查通过，audit digest为`cb1fb6df9c6d5f6074b4f7ad980976e09a70e2f730375b7298ab3aed46bd5a35`；跨县城市邻接digest为`fead03de4916430aa989cf60c7b6710d8bd0e33bbbca29e94cec277b93925b06`；剩余空间裁决digest为`4ca61668bf1ebc68457146ebcd3469899e1f07b226f076ec1013a3d2f234a2f2`；source contract绑定128个artifact，digest为`4856fbe6153d9458ea52a60e99cc3178bf10f2bce12cabc9c1225226365f8b15`。聚焦回归为24 passed；排除既有DAM-GK v0.1冻结哈希漂移检查后的Chicago、Paper6、shared Kernel、AI Urban Scientist、forcing、SRTM、空间拓扑和时间上下文宽回归为234 passed。DAM-GK completion的3项失败来自本轮未修改的`negative_controls.py`、`hydrocontrol_adapter.py`和`hydrocontrol_benchmark.py`与2026-07-20冻结合同摘要不一致，不能在本轮静默重签。

状态边界保持不变：`observed_outcome_panel_materialized=true`，但`complete_spatial_assignment_ready=false`、`outcome_to_unit=false`、`panel_materialization_ready=false`、`causal_estimation_admitted=false`、`effect_application_admitted=false`和GWM K0继续关闭。下一优先级不再是反复地理编码这72条记录，而是补齐完整历史zoning treatment universe、独立核验effective onset和按月对齐的纵向混杂变量，再进入Paper6的positivity/ESS、pretrend、placebo、干扰暴露和地理holdout诊断。GWM仍指跨领域地理空间世界模型及共享Geospatial Kernel；Chicago是UWM实证验证，TWM本轮未修改。
