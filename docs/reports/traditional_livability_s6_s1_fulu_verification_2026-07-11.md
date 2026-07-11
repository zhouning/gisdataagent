# 福禄镇 S6→S1 传统宜居性闭环真实数据验证

## 验证范围

本次验证使用已经构建的真实本地产品：

- Phase 1A 设施产品：`/private/tmp/traditional_livability_phase1a_real/uwm_traditional_livability_facility_product.json`
- 福禄镇 S6 资源：`/private/tmp/traditional_livability_s6_fulu_real/uwm_traditional_livability_s6_resources.json`
- 新闭环产品：`/private/tmp/traditional_livability_s6_s1_fulu_real`

该验证测试 S6 语义确认和空间筛查之后，是否能够生成可审计的 S1 交接产品，以及当权威 FP/FPP 数据缺失时是否正确关闭 S1 达标判断。

## 真实数据摘要

- 设施产品记录数：76,292
- 福禄本地 S6 设施对象：7
- 规划范围：和平村、斑竹村，共2个
- bundle ID：`traditional-livability-s6-s1-2e83e6b961717d45387c`
- 设施库存完整：否；原产品明确记录采样上限
- 人工或合成设施记录：0
- 新增虚构人口、面积、容量或服务半径：0

## 验证结论

闭环合同、产品版本绑定和证据边界通过验证，但 S1 业务执行保持关闭。关闭原因是：

1. 缦少客户或主管部门发布的权威 S1 FP/FPP metric profile；
2. 缺少权威 FP/FPP 2×2 综合判断矩阵；
3. 缺少和平村、斑竹村对应口径的权威人口或需求单元；
4. 当前设施产品没有完整设施面积和容量字段；
5. 设施库存是采样产品，不足以支持“全区无缺口”结论。

因此本次最高结论是：S6→S1 工作流合同和数据交接已经落地，S1 合规或达标结论尚不具备权威数据基础。系统返回 `s1_execution_ready=false`，没有使用其他 UWM 阈值、S6 的150米筛查距离或内部经验值替代缺失标准。

## 方法边界

- 本功能属于传统确定性 GIS 和规则分析。
- 基线与拟建快照重算不是 UWM rollout。
- 未评估未来人口增长、诱发需求、社区适应或政策效果。
- S6 的150米距离仅用于空间初筛，不作为 S1 服务半径。
- 没有权威 profile 时，不输出达标、不达标或批准建议。

## 自动验证

自动验证结果：通过。

- single bundle ID：通过
- 两个规划范围：通过
- 真实设施库存存在：通过
- 无权威 profile 时保持 unavailable：通过
- S1 执行关闭：通过
- 无虚构值：通过
- UWM claim 关闭：通过

验证摘要：`sha256:6736c2c981f269c43612dab92f0aae80aae686da54f98dcccc7393a15f30e92a`
