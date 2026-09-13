# GWM-Bench Foundation V2.0-rc1

## 当前状态

`V2.0-rc1` 已冻结，验收状态为 `PASS_LABELS_PENDING`。

这句话的意思是：数据、TWM预测、FLUS预测和未来评分程序均已固定；当前没有成绩，也不应有成绩，
因为完整2026标签最早只能在 `2027-01-01` 后导出。

## 与V1.0的区别

- V1.0是历史回测，证明数据和比较流程可以工作。
- V2.0是事先封存的未来盲测，回答模型在不知道答案时是否有效。
- V2.0是否完成不取决于TWM必须获胜。TWM失败或结果不显著也必须发布。

## 三条测试轨道

| 轨道 | 作用 | RC1状态 |
| --- | --- | --- |
| `RUNTIME-R1` | 检查状态/行动/空间图契约、哈希、确定性回放、无标签路由和审计链 | 已就绪 |
| `CONTROLLED-C1` | 在128个受控样本上检查DAM-GK门控、关系、拓扑、时滞和状态变化 | 已就绪 |
| `OBSERVED-O2` | 在20地区、1,055节点上比较TWM、FLUS和两个内部基线的2026预测 | 预测已封存，等待标签 |

`RUNTIME-R1` 只证明本benchmark的运行契约可复核，不声称共享跨领域GWM Runtime Kernel产品已经完成。
`CONTROLLED-C1` 只证明受控机制恢复，不声称识别了真实政策因果效果。

## 已冻结预测

| 模型 | 2021-2026行数 | SHA256 | 预测2026变化数 |
| --- | ---: | --- | ---: |
| TWM V2三种子集成 | 6,330 | `2a4987cb75a1d43f04e85b765633af1e185415a0143edf79da3bb9eb683b1312` | 43 |
| FLUS完整栅格三种子集成 | 6,330 | `05d7f3ae4b3bafed328c9600adb2e729bd2c606bf2caea458fd565031a13006c` | 22 |

这些变化数只是预测描述，不是成绩。

## 验收与状态检查

在仓库根目录运行：

```bash
.venv/bin/python benchmarks/gwm_bench_foundation_v2_0_rc1/verify_v2_rc1.py
.venv/bin/python benchmarks/gwm_bench_foundation_v2_0_rc1/score_v2_2026_hidden.py --check-readiness
```

当前预期输出分别为：

```text
GWM-Bench Foundation V2.0-rc1: PASS_LABELS_PENDING
rc1_ready_labels_pending
```

总协议在 `suite_protocol.json`，其冻结指纹为：

```text
a4f9d43eafe1490956bd88e6bf0614a21b673b098fb5c1c628d775bfb5cb5e72
```

## 转为V2.0 final

只能在 `2027-01-01` 之后执行：

1. 导出并注册20个地区完整的2025和2026 Dynamic World年度标签；
2. 检查地区集合、栅格、文件哈希和时间窗口；
3. 不修改模型、阈值、预测或评分程序；
4. 运行一次 `score_v2_2026_hidden.py`；
5. 无论TWM胜负，发布TWM、FLUS和内部基线的完整结果。

在此之前不得运行最终评分，也不得把RC1写成V2.0 final。
