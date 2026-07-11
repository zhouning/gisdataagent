# 福禄镇 S1 门控 S7 小学选址真实数据验证

## 验证目标

验证现有福禄镇小学候选地块排序不会在缺少权威 S1 需求证据时被呈现为正式选址建议。

## 数据来源

- 现有 S7 产品：`/private/tmp/traditional_livability_s7_fulu_real/uwm_traditional_livability_s7.json`
- Phase 1A S1 产品：`/private/tmp/traditional_livability_phase1a_real/uwm_traditional_livability_s1.json`
- Phase 1A 设施产品：`/private/tmp/traditional_livability_phase1a_real/uwm_traditional_livability_facility_product.json`
- 新门控产品：`/private/tmp/traditional_livability_s7_gated_fulu_real`

## 真实结果

- 规划范围：和平村、斑竹村，共2个
- 原始候选排名：28个
- 原算法条件选中行：3个
- Demand Gate：`need_unresolved`
- 输出状态：`conditional_candidate_ranking_available`
- 权威选址建议可用：否
- 虚构人口、学龄人口、容量、学位、缺口或服务半径：0

全部28个候选及3个原算法选中行均标记：

`not_a_site_recommendation=true`

这3个选中行只表示在“假设需要新增小学”条件下，贪心 location-allocation 算法的前三轮空间选择，不是主选或备选建议。

## 未解决的需求证据

当前不能证明小学新增需求，原因包括：

- 缺少权威 S1 FP/FPP metric profile；
- 缺少权威综合判断矩阵；
- 缺少和平村、斑竹村的权威人口、学龄人口或需求单元；
- 缺少学校容量、招生、学位和运营状态；
- 设施库存不完整；
- 缺少完整村级步行网络；
- 规划数据仅覆盖两个村样本；
- 缺少地块权属、征拆、开发控制、工程量和财务数据。

## 正确解释

当前结果只能解释为：

> 小学新增需求尚未被权威 S1 指标证明。结果仅表示假设需要新增小学情况下，基于住宅用地面积和1500米投影直线距离代理的候选地块排序，不构成选址建议。

1500米来自原 S7 条件式排序参数，不代表法定服务半径、步行时间、路网服务区或学校容量范围。

## 世界模型边界

本功能属于传统静态 GIS：

- 没有人口增长预测；
- 没有学位需求时间演化；
- 没有社区行为响应；
- 没有政策效果预测；
- 没有 UWM rollout。

## 自动验证

验证结果：通过。

- 单一 bundle：通过
- Demand Gate unresolved：通过
- 仅条件式排序：通过
- 所有候选均为非建议：通过
- 权威建议关闭：通过
- 无虚构值：通过
- UWM claim关闭：通过

验证摘要：`sha256:a1ed5409c61bf69b65061a2b5d6ccb4816324addd9fef67fa22b23af8a6bd1b8`
