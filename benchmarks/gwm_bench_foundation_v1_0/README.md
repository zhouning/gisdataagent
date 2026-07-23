# GWM-Bench Foundation Historical v1.0

## 结论

这个目录是 GWM benchmark 的历史回测 v1.0 交付入口。

- 状态：`historical_backtest_ready`
- 可以做：在冻结的 20 个地区、1,055 个节点上复现数据校验，运行统一评分器，比较最终 TWM 与 FLUS。
- 不代表：2026 前瞻隐藏评测已经完成，也不代表所有 GWM 场景均已验证。

底层数据仍保存在 `benchmarks/gwm_bench_foundation_v0_1/`。v1.0 不复制约 1.5 GB 的已有资产，
而是用 `release_manifest.json` 固定它们的路径、大小、SHA256 和最终指标。

## 一键验收

在仓库根目录运行：

```bash
.venv/bin/python benchmarks/gwm_bench_foundation_v1_0/verify_release.py
```

通过时输出：

```text
GWM-Bench Foundation Historical v1.0: PASS
```

并生成 `acceptance_report.json`。验收内容包括：

1. 9 个物化数据表的文件哈希与原始 bundle manifest 一致；
2. 13 项独立数据检查全部通过，总计 271,698 次逐值比较；
3. 最终 TWM 和 FLUS 的预测、评分与报告文件没有变化；
4. 最终主指标仍为 TWM `0.249212`、FLUS `0.153434`；
5. 说明文档和 5 张数据图完整，Word 文件实际内嵌 5 张图片；
6. 2026 前瞻评测保持 `pending_full_calendar_2026_labels`，不会被误写成已经完成。

## 最终口径

| 项目 | 冻结值 |
| --- | ---: |
| 地区数 | 20 |
| 唯一节点数 | 1,055 |
| 有向空间边数 | 3,338 |
| 历史目标年份 | 2019、2020 |
| 评分行数 | 2,110 |
| 最终 TWM 主指标 | 0.249212 |
| FLUS 主指标 | 0.153434 |
| TWM 相对提升 | 62.4% |

完整数据、架构与结果说明见：

- `docs/research/GWM_BENCHMARK_DATA_ARCHITECTURE_AND_TWM_FLUS_COMPARISON_2026-07-23.md`
- `docs/research/GWM_BENCHMARK_DATA_ARCHITECTURE_AND_TWM_FLUS_COMPARISON_2026-07-23.docx`

## 结论边界

历史 v1.0 可以作为当前可运行、可复核的 benchmark 使用。最终 TWM 是在历史标签已经存在后完成的
开发结果，因此这里的 TWM-FLUS 对比属于历史回测证据。完整 2026 标签最早只能在
`2027-01-01` 后导出；在那之前，不得把历史回测结果表述成前瞻盲测结果。
