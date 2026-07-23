# GWM-Bench Foundation V5.0

当前状态：`RUNTIME_R4_EVALUATOR_SEALED_PREDICTIONS_PENDING`。

V5.0把V4的一次2025行动考试改成四次轮流考试。2015、2019、2022、2025四个纽约出租车真实收费
行动分别作为一次外层留出测试，其余三个事件用于训练；模型不能读取当前留出事件的行动后目标。

V5只新增一个问题：以V4中表现最好的历史AR为底座后，DAM-GK只预测“行动修正量”，正确行动语义和
空间范围能否在四个事件上稳定改善强基线，并且所有错误行动对照都更差。

V5是分析者已见结果的回顾性多行动鲁棒性benchmark，不声称盲测或政策因果识别。Benchmark完成不
要求模型获胜，失败也必须发布。

当前已经完成：

- 冻结机器协议：`suite_protocol.json`；
- 本地源数据预检：76/76通过，V5不需要新下载；
- RC1四事件、四外层折数据物化：`rc1_bundle/`；
- 独立数据与防泄漏验证：147/147通过；
- 验证报告：`rc1_bundle/bundle_verification.json`；
- 多折提交合同和评分器构造测试：23/23通过；
- Runtime-R4与评分器封存：19/19通过，`runtime_r4_evaluator_seal.json`。

复现命令：

```bash
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/preflight_v5_draft.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/materialize_v5_rc1_bundle.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/verify_v5_rc1_bundle.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/run_evaluator_conformance.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/freeze_runtime_r4_evaluator.py
```

数据层、Runtime-R4合同、提交格式和评分器现在都已经冻结。下一步是按冻结规则实现运行器，再执行四模型、
七项负对照、四个外层折和三个随机种子；模型运行期间不得读取任何当前折答案。

机器协议：`suite_protocol.json`。

中文定义：
`docs/research/GWM_BENCHMARK_V5_0_DEFINITION_AND_EXECUTION_PLAN_2026-07-23.md`。
