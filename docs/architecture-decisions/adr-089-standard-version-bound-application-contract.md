# ADR-089：标准版本绑定的智能落标合同

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Data Governance, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-3

**Related decisions**: [ADR-002 统一元数据控制面](adr-002-unified-metadata-control-plane.md) · [ADR-005 DataOps 与 AgentOps 双运营闭环](adr-005-dataops-and-agentops-operating-loops.md)

## Context

虚拟数据源已有 embedding 字段匹配和 `schema_mapping`，但目标是硬编码 canonical GIS 词汇，结果只保存为源字段到目标名称的 JSON。它不能回答目标标准及版本、数据元身份、推荐证据、人工确认人和历史替代关系，也不能阻止一个映射引用错误标准版本的数据元。

AR-3 要求数据合同、质量、安全、审批和产品版本使用统一生命周期。当前统一 `ChangeSet`、`ApprovalCase` 和 `DataProductVersion` 尚未落地，因此本决策只建立可被未来 ChangeSet 引用的标准应用工件，不创建平行发布、审批或资产 registry。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 继续扩展 canonical JSON | 改动小、兼容现状 | 无标准版本、数据元 FK、证据和审计 | 不选 |
| B. 把标准绑定元数据嵌入 `schema_mapping` JSON | 单表实现快 | 数据库无法保证跨版本引用完整性，难以影响分析 | 不选 |
| C. 建立引用现有标准权威源的 mapping contract | 可审计、可约束、可演进并兼容现有执行 | 新增两张关系/工件表 | **选择** |

## Decision

### 1. 权威身份

- 映射合同必须引用状态为 `released` 的 `std_document_version`。
- 每个字段绑定必须引用该版本内的 `std_data_element`；数据库使用复合外键失败关闭。
- 目标字段名由服务端从 `bound_column` 或 `code` 解析，客户端不能伪造。
- `std_*` 继续是标准权威源，不复制标准目录和数据元 registry。

### 2. 智能推荐边界

候选评分组合字段名称、标准代码/中英文名/别名、数据类型和 embedding。输出保留各分量、候选列表、置信度差和 `recommended/review_required/unmatched/conflict` 状态。

标准数据元已有 embedding 时必须复用持久化向量；仅对源字段计算新向量。目标 embedding 缺失时才允许批量回退计算。模型不可直接写权威数据，同一目标出现多个源字段时必须进入冲突复核。

候选必须先绑定标准业务表（`bound_table`）。真实标准中 `BSM`、`YSDM`、`XZQDM`
等代码跨业务域重复，全标准评分会制造伪歧义；未知或空白目标业务表必须失败关闭，不能
通过扩大候选域提高表面召回率。

### 3. 确认与执行

`std_application_mapping_contract` 和 `std_application_field_mapping` 保存标准版本、源画像 hash、数据元 ID、证据、确认人、映射 hash 和替代状态。同一源只能有一个 `confirmed` 合同。

确认合同与更新虚拟源 `schema_mapping` 在同一 PostgreSQL 事务内完成。重复确认相同内容返回相同合同。当前执行范围严格限定为查询时 `rename`：

```text
released standard + source profile
 -> proposal
 -> human confirmation
 -> immutable mapping evidence
 -> query-time rename
```

它不创建 `DataProductVersion`，不修改 Raw，不宣称已执行类型、单位、值域、CRS 或 geometry 转换。

### 4. 后续接入

AR-3 的统一对象可用后，mapping contract 作为 `ChangeSet` 工件进入 preview、quality/security gate、`ApprovalCase`、新 `ResourceVersion/DataProductVersion`、lineage、promotion 和 rollback，不再新增本地审批状态机。

## Trade-offs

- 仅有 released 标准可用于正式候选，draft 标准的实验映射需走独立 preview，避免未审定内容进入执行合同。
- 当前只执行 rename，智能落标的类型、值域、单位和空间转换仍未完成；这种保守边界换取可验证和可回滚的起点。
- 虚拟源尚无不可变 `ResourceVersion`，所以先记录采样画像 hash。AR-2 提供 ResourceVersion 后应把 `source_ref` 升级为版本身份。
- 首条真实数据验收允许低置信字段进入人工复核而不强制自动推荐，因此以冻结的
  precision/recall gate 衡量提案，不要求自动 mapping 与人工 golden 完全相等；错误自动
  推荐仍由 precision 和 unexpected recommendation gate 失败关闭。

## Consequences

### Positive

- 任一确认映射可以追溯到标准版本、数据元、推荐证据和确认人。
- 跨标准版本绑定由数据库拒绝，而不是依赖 UI 或 LLM 自律。
- 旧 canonical API 保持兼容，允许渐进迁移。

### Negative

- 在 ResourceVersion 和统一 ApprovalCase 到位前，合同只是治理工件，不是可发布数据产品。
- 大型标准的候选交互仍需后续增加服务端搜索、分页和 benchmark。

### Mitigation

- 用重庆 DEM、OSM 道路、CLCD、建筑、POI/AOI、人口和 TAP 数据建立黄金映射与 holdout。
- 后续执行器只能从确认合同编译确定性转换计划，并由独立质量复验决定 promotion。

## 2026-07-31 Real-data Acceptance Checkpoint

首条验收集冻结为重庆自然资源样例中的 JQDLTB golden，以及 OSM 道路和中心城区建筑
两个跨域负向 holdout。协议同时绑定原始压缩包 SHA-256、Shapefile 全 sidecar bundle
SHA-256、released 标准版本及 174 个数据元的规范化 fingerprint；任一身份漂移都会在
评分前失败关闭。

- JQDLTB：1,555 个 Polygon、25 个字段、EPSG:4523；人工 golden 15 项。
- OSM 道路：50,366 个 LineString、10 个字段；目标域错误绑定负向 holdout。
- 中心城区建筑：107,452 个 Polygon、2 个字段；目标域错误绑定负向 holdout。
- 执行固定为 `llm_mode=disabled`，不调用 embedding 或 LLM，不持久化源样本值和绝对路径。
- JQDLTB 自动推荐 9/15，precision = 1.0、recall = 0.6、unexpected = 0；其余字段保留为
  review/conflict。两个负向 holdout 均为零自动推荐。

该 checkpoint 仅证明冻结字节、冻结标准与当前确定性评分器之间的技术可复现性。
`business_steward=pending_assignment` 和
`license_status=pending_internal_evaluation_only` 仍阻断 promotion；它不证明类型、值域、
单位、CRS、geometry 转换或 Raw -> DataProductVersion 已实现，也不把 AR-2/AR-3 标记完成。

可复跑协议和脱敏证据位于
[`benchmarks/standard_mapping_chongqing_v0_1`](../../benchmarks/standard_mapping_chongqing_v0_1/README.md)。

## Revisit Triggers

- AR-2 提供稳定 `ResourceVersion` 身份。
- AR-3 提供统一 `ChangeSet`、`ApprovalCase` 和 `DataProductVersion`。
- 真实标准的数据元规模使全量目标列表或 embedding 载入超过冻结的延迟/成本 SLO。
