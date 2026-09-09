# 阿布扎比 SWMM–ANUGA 同步双向耦合执行器

## 1. 代码位置

核心实现：

```text
data_agent/uwm/abu_dhabi_flood/swmm_anuga_coupled_runner.py
data_agent/uwm/abu_dhabi_flood/swmm_dynamic_toolkit.py
```

客户 DTM 局部试点准备和运行脚本：

```text
scripts/prepare_abu_dhabi_bidirectional_pilot_grid.py
scripts/run_abu_dhabi_swmm_anuga_bidirectional_pilot.py
```

## 2. 同步窗口算法

每个 300 秒交换窗口执行以下步骤：

1. 读取上一个 ANUGA 状态的地表水位；
2. 依据 SWMM 节点水头和地表水位计算有符号水头差交换率；
3. 将 `-Q` 写入 SWMM 节点外部侧向流，完成地表回流或网络向地表的对应扣减；
4. 推进 SWMM 一个交换窗口；
5. 读取节点溢流率，将 SWMM 溢流与有符号水头差交换合成为 ANUGA 单元源项；
6. 推进 ANUGA 同一交换窗口；
7. 读取地表水位、地表存水和边界通量；
8. 计算下一窗口交换率，并写出本窗口质量守恒回执。

负交换率会作为 ANUGA 地表汇项，同时以相反符号写回 SWMM。对于局部干涸单元，反向交换率按可用水量限幅，避免从没有水的单元抽取水量。

## 3. 质量回执字段

每个窗口的回执位于 `bidirectional_coupling_receipt.json` 的 `windows` 数组，重点字段包括：

- `total_swmm_to_anuga_m3`：SWMM 向二维表面传递的水量；
- `total_anuga_to_swmm_m3`：二维表面回流到 SWMM 的水量；
- `anuga_requested_signed_source_m3`：请求施加到二维的带符号源项体积；
- `anuga_applied_signed_source_m3`：ANUGA 实际累计施加的带符号源项体积；
- `exchange_application_relative_difference`：请求与实际源项的相对差；
- `surface_mass_balance_residual_m3`：二维地表存水、源项和边界通量的质量残差；
- `quality_passed`：本窗口质量门是否通过。

当前试点使用 0.5% 的源项实际应用相对容差和 1e-3 m³ 的地表质量残差门槛。容差是数值求解器窗口积分误差门槛，不是对工程数据准确性的替代。

## 4. 客户真实数据试点结果

试点输入：

```text
客户 SWMM：/Users/zhouning/Downloads/阿布扎比/GDB提交版_模型工作区_20260821/customer_stormwater_pilot_01_diagnostic.inp
客户 DTM：/Users/zhouning/Downloads/阿布扎比/DTM_z40_customer/AUH_DTM_5m_Z40.TIF
```

试点空间范围使用 8 个客户节点周边的 25 m DTM 局部网格；运行 1,800 秒，分成 6 个 300 秒交换窗口。结果目录：

```text
/Users/zhouning/Downloads/阿布扎比/双向耦合试点_客户DTM_20260909
```

回执中 `status=completed`、`quality_passed=true`，并且既有 SWMM→ANUGA，也有 ANUGA→SWMM 的非零交换量。

## 5. 全市规模试点进展与扩展工作

已进一步用全市客户 SWMM 输入和客户 DTM 运行 250 m 单窗口压力试点：5,000 个节点绑定、300 秒同步窗口、200 条接口明细保留（其余接口仍参与计算但回执按上限截取）。该试点 `status=completed`、`quality_passed=true`，用于验证全市节点循环、内存和回执截断策略。它不是最终 146,823 节点×180 分钟生产运行，后者还需要完整接口属性和性能验收。

## 6. 从全市压力试点扩展到生产全流程还要完成的工程工作

1. 从客户全市 SWMM 节点和雨水口数据生成完整的 `CouplingInterfaceBinding`；
2. 将井口高程、开口面积、堵塞系数、最大交换流量等客户字段接入，而不是使用试点默认参数；
3. 将局部二维适配器扩展到客户 DTM 100 m 全市网格；
4. 处理域外节点、海域节点、岸线节点和海水边界；
5. 运行 100 m 全市短时双向试验，确认内存、运行时和回执大小；
6. 再扩展到 180 分钟、300 分钟和 2/5/10/25/50/100 年一遇及历史暴雨场景；
7. 将每个时间帧和质量回执接入 GIS Data Agent 的地图与时间轴。
