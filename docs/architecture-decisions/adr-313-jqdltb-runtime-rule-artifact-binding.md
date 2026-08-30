# ADR-313: JQDLTB 执行绑定语义规则和面积规则 Artifact

**状态**: Accepted for AR-0 implementation

**日期**: 2026-08-26

**相关路线**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## 背景

JQDLTB transformation contract 已经把 `SJNF/MSSM` 的 source fields、semantic ref、method 和 SHA-256 写入审批计划，也把 `use_geometry` 的面积规则 ref/SHA 写入计划。但 executor 原先只根据 contract 文本执行 first-non-blank，并没有读取或校验对应规则 artifact；审批对象和实际运行规则之间存在脱钩风险。

## 决策

执行器在任何输出目录创建前加载并校验所有批准规则：

- `SJNF`、`MSSM`：`gda.jqdltb_derivation_rule.v1`，校验 artifact SHA-256、target field、排序后的 source fields、semantic contract ref、method；当前只接受 `first non-blank approved source value`。
- `use_geometry`：`gda.jqdltb_geometry_area_rule.v1`，校验 artifact SHA-256、rule ref、`source_crs`、`TBMJ` target、`square_metre` unit、`0.01` tolerance 和 `planar_geometry_area_in_source_crs` method。
- `business_correction`：校验 correction 文件 SHA-256、每行 `TBBH` 唯一且存在于源、每个非正面积源记录都有有效 `TBMJ/TBDLMJ` 更正；遗漏、无效值、重复键、对正常记录的多余更正均 fail closed 或显式质量失败。

## 取舍

- **继续只信 contract 里的 method 文本**：改动小，但 contract 和运行字节可能漂移，拒绝。
- **把规则复制进执行器代码**：运行确定，但无法让业务批准一个版本化规则 artifact，拒绝。
- **contract + 内容寻址 rule artifact 双绑定**：需要为调度运行提供额外路径，但审批、执行和证据可以对账，采用。

## 结果

- 业务可以先提交完整 strategy；工程运行时不再有未验证的语义规则旁路。
- `transformation-evidence.json` 的记录统计包含 derivation rule binding 和 geometry area rule binding。
- 规则漂移在写层前失败，不产生半成品。
- 业务批准门和 DataProductVersion 发布门保持不变。

## 证据

- [Executor](../../data_agent/jqdltb_transformation_executor.py)
- [DataOps runtime wiring](../../data_agent/dataops_executor.py)
- [Focused executor tests](../../data_agent/test_jqdltb_transformation_executor.py)
- 41 项 JQDLTB/AR-0 回归通过；随后在 disposable PostGIS 16.4/PostGIS 3.4.3 中补跑数据库发布门，`1 passed`。认证报告为 `.tmp/jqdltb-data-product-release/acceptance-report-2026-08-26.json`，文件 SHA-256 为 `86cb83fc01222a065379c03b506ade8bd5ef4a44534bf973c9a49231a9eb43e4`。报告标记 `production_claim=false`、`real_business_approval_claim=false`，容器已清理。

## 重评触发条件

- 新增 derivation method、面积计算 CRS/单位或 correction 格式；
- 规则 artifact 从本地文件迁移到对象存储/metadata authority；
- 需要在不重跑 transformation 的情况下更新业务语义。
