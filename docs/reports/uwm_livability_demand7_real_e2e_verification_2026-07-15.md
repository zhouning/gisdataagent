# 需求7：UWM宜居目标与社区干预规划真实端到端验证

验证日期：2026-07-15
运行环境：本机 Docker `gisdataagent-app-1`，服务地址 `http://127.0.0.1:8000`
测试账号：默认管理员（测试脚本从环境默认值读取）

## 1. 本次实现范围

需求7已经从通用宜居性决策包推进为独立产品，形成以下真实链路：

1. 从全行政单元图状态读取当前宜居代理状态；
2. 采用同源观测分位数形成可追溯目标，而不是人工编造目标值；
3. 读取目标单元经过动作掩码允许的真实动作；
4. 从6,817条已存模拟器转移中提取对应的 step-0 动作条件转移；
5. 计算目标差距收敛、目标单元变化和空间溢出预览；
6. 按目标画像排序干预动作；
7. 将目标行政单元和空间溢出单元发送到中间地图；
8. 对24个月和5年预测执行结构化 Fail-Closed。

## 2. 真实数据基础

- 状态节点：1,017
- 空间边：7,932
- 可选动作：1,137
- 已存回放转移：6,817
- 行政边界：1,017个重庆乡镇级真实边界要素
- 验证目标单元：`涪陵区|蔺市镇|498`
- 目标单元可用动作：3项

源产品：

- `data/uwm_public_proxy/chongqing_central/admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json`
- `data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_full_admin_graph_2026_07_08/uwm_full_admin_graph_model_based_graph_search.json`
- `data/uwm_public_proxy/chongqing_central/admin_units/chongqing_township_admin_units.geojson`

## 3. 目标与规划机制

平衡画像使用风险指标P25和正向指标P75作为同源观测基准。社区服务画像将服务可达性目标提高到同源观测P90；公平宜居画像对公平性和宜居性使用P90。该机制只改变数据派生目标和指标权重，不引入无来源政策目标。

规划器对每个可行动作执行：

- 当前状态读取；
- 目标差距计算；
- 已存动作条件转移匹配；
- 目标单元投影状态计算；
- 空间溢出节点提取；
- 加权目标差距收敛排序；
- 回放奖励作为次级排序依据；
- 证据等级和禁止声明同步输出。

## 4. 真实验证结果

社区服务优先画像对 `涪陵区|蔺市镇|498` 推荐：`add_community_service`（新增社区服务设施）。

目标单元的真实已存转移增量：

- 服务可达性：`+0.221413`
- 公平性：`+0.0761563`
- 宜居性：`+0.066776695`

环境舒适优先画像推荐：`increase_green_infrastructure`，证明目标画像确实改变动作排序，而不是固定返回同一答案。

地图验证：

- 目标行政单元图层包含1个真实边界要素；
- 空间溢出预览图层包含真实相邻/传播单元边界；
- 服务不足图层完整显示目标区县内低于当前目标画像服务可达性阈值的行政单元，避免把无关全市图层强行推送到局部决策地图；
- 地图载荷记录目标单元、动作ID和证据等级。

## 5. 时间尺度证据门

`simulator_step` 可运行，但仅支持 bounded simulator scenario。以下尺度被明确阻断：

- `24_month`：`calendar_horizon_calibration_missing`
- `five_year`：`calendar_horizon_calibration_missing`

系统不会把两步模型回放改名为24个月或5年。要开放日历预测，至少需要客户口径纵向宜居面板、带日历时间的动作暴露历史、24个月/5年留出验证和观察到的干预结果面板。

## 6. 声明边界

本产品当前可以声明：

- 真实代理状态上的目标差距；
- 同一快照中的动作条件模拟；
- 有边界的空间传播预览；
- 基于已存模拟器转移的干预优先级。

本产品当前不能声明：

- 24个月或5年真实预测；
- 观察到的政策实施效果；
- 因果政策效应；
- 已吸收社区意见后的需求结论；
- 正式政策承诺或审批结论。

## 7. 验证命令与产物

后端与前端契约测试：

```bash
.venv/bin/python -m pytest -q data_agent/test_uwm_livability_demand7.py data_agent/test_uwm_livability_demand7_frontend_contract.py
```

结果：`6 passed`。

前端生产构建：

```bash
npm --prefix frontend run build
```

结果：TypeScript和Vite构建成功。

真实Docker浏览器测试：

```bash
/Users/zhouning/miniconda3/bin/python tests/e2e/demand7_real_e2e.py
```

测试产物位于：`tests/e2e/artifacts/demand7/`，包括overview、规划结果、地图载荷、Fail-Closed结果和界面截图。测试过程未使用mock响应。
