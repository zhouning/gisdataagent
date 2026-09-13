# GWM-Bench Foundation V5.0

当前状态：`PASS_V5_BENCHMARK_COMPLETE_ACTION_TRANSFER_NOT_SUPPORTED`。

V5.0把2015、2019、2022、2025四个纽约出租车真实收费行动轮流作为外层留出测试。每折只用另外三个
行动训练，以V4最强历史AR为底座，由DAM-GK预测行动修正量：

```text
final_prediction = frozen_history_AR + DAM_GK_action_residual
```

Benchmark已经完成，完成验证15/15通过。当前行动迁移主张没有通过：正确行动模型比同结构无行动模型好约
1.08%，但仍落后于历史AR；四折平均技能为-2.52%，八项冻结门槛全部失败。

## 已完成

- 本地源数据预检：76/76通过，V5不需要新增下载；
- 四事件、四外层折RC1数据物化：67,328行；
- 独立数据与防泄漏验证：147/147通过；
- 提交合同与评分器构造测试：23/23通过；
- Runtime-R4与评分器预测前封存：19/19通过；
- Runtime-R4烟雾验证：15/15通过；
- 4模型、7负对照、4折、3随机种子的正式预测；
- 27份种子级多折预测和116份逐折预测；
- 全部逐折预测从checkpoint零差值重放：12/12通过；
- 预测承诺绑定400个模型文件；
- 冻结评分器正式评分和15/15完成验收。

## 最终结果

主指标越低越好：

| 方法 | 分数 |
| --- | ---: |
| Date +4w负对照 | 0.358918 |
| 固定邻接空间AR | 0.361416 |
| 历史AR底座 | 0.362616 |
| Action deleted | 0.362616 |
| Exposure shuffle | 0.364012 |
| Component permutation | 0.364847 |
| DAM-GK正确行动残差 | 0.368389 |
| Date -4w | 0.370308 |
| Cross-event swap | 0.371179 |
| DAM-GK无行动残差 | 0.372408 |
| Wrong spatial scope | 0.381496 |

四折技能：2015为-15.35%，2019为-13.91%，2022为+10.78%，2025为+8.39%。

## 关键复核命令

以下命令会重建或刷新正式产物，不能当作无副作用的`--help`命令运行：

```bash
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/preflight_v5_draft.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/materialize_v5_rc1_bundle.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/verify_v5_rc1_bundle.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/run_evaluator_conformance.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/freeze_runtime_r4_evaluator.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/run_runtime_r4_predictions.py --mode smoke --fold holdout_2015
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/verify_runtime_r4_smoke.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/run_runtime_r4_predictions.py --mode formal
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/replay_runtime_r4_predictions.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/commit_runtime_r4_predictions.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/action_transfer_evaluator.py \
  --prediction-commitment benchmarks/gwm_bench_foundation_v5_0_draft/predictions/prediction_commitment.json \
  --output benchmarks/gwm_bench_foundation_v5_0_draft/final_results/action_transfer_results.json
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/verify_v5_completion.py
.venv/bin/python benchmarks/gwm_bench_foundation_v5_0_draft/render_v5_final_figures.py
```

## 文档与机器结果

- 最终中文报告：`docs/research/GWM_BENCHMARK_V5_0_FINAL_REPORT_2026-07-23.md`；
- 定义与执行记录：`docs/research/GWM_BENCHMARK_V5_0_DEFINITION_AND_EXECUTION_PLAN_2026-07-23.md`；
- 机器协议：`suite_protocol.json`；
- 正式结果：`final_results/action_transfer_results.json`；
- 完成验证：`final_results/completion_verification.json`；
- 预测承诺：`predictions/prediction_commitment.json`；
- 重放报告：`predictions/runtime_replay_report.json`。

声明边界：V5支持四个已知纽约出租车行动上的可复现模型留出评测和Runtime-R4审计证据；不支持政策因果
效果、分析者盲测、运营预测、跨城市泛化或完整通用GWM / UWM / DAM-GK已经成立。
