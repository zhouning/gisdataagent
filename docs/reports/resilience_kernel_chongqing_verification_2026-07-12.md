# 重庆韧性世界模型Kernel基础验证报告（需求19）

- 日期：2026-07-12
- Schema：`uwm.resilience_kernel_foundation.v1`
- Bundle：`resilience-kernel-723a9c0cb5cf2457af90`
- Digest：`sha256:b5aa936f1223d83e68fd98191d45300e56223e00e4f289835f0a5d5610a4d077`

## 真实产品结果

- 韧性状态节点：1,017。
- 原始网络图边：5,085。
- 采用的明确边界邻接边：250。
- 证据门禁：7类。
- 需求25韧性依赖任务：6项。
- 开放转移机制：0。
- 伪造值：0。

节点绑定道路网络、公共服务、应急设施和环境证据语境。图仅采用源产品中明确标记的边界邻接关系；相似度权重、道路差异和距离均未转换为灾害传播系数，所有 `propagation_parameter` 为 `null`。

## 当前Rollout

危险扰动转移、灾害传播、响应能力、恢复转移、干预效果和反事实六类机制全部为 `closed`。`future_trajectory` 为 `null`。

产品不生成灾害损失、脆弱性、死亡、响应有效性、恢复时间、恢复概率、干预收益或稳健性评分。

## 验证

- 聚焦后端测试：14 passed。
- 图边来源、传播参数、门禁状态和关闭Rollout独立校验：通过。
- 前端TypeScript/Vite生产构建：通过。
- 最大声明：`observed_resilience_context_spatial_graph_and_fail_closed_kernel_readiness`。
