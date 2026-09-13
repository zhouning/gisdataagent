# ADR-002：统一元数据控制面

**Status**: Superseded by [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md)

**Date**: 2026-07-19

**Decision owners**: Platform Architecture, Data Governance, Security, GIS Engineering

**Related review**: [GIS Data Agent 企业级架构复审](../architecture-review-2026-07-19.md)

**Related decisions**: [ADR-001 可插拔地理空间存储、计算与服务边界](adr-001-geospatial-lakehouse-and-postgis-boundary.md) · [ADR-004 传统平台能力下限与 Human/Agent 双入口](adr-004-capability-floor-and-dual-entry-agentic-platform.md) · [ADR-005 DataOps 与 AgentOps 双运营闭环](adr-005-dataops-and-agentops-operating-loops.md) · [ADR-006 OpenMetadata + Gravitino Metadata Fabric](adr-006-openmetadata-governance-and-active-metadata-platform.md)

> **Supersession note (2026-07-19)**：本 ADR 中关于统一身份、不可变版本、authority matrix、空间/时间/证据字段和专属控制领域的约束继续有效；“自建 PostgreSQL metadata framework 作为首期选择”已被 ADR-006 替代。OpenMetadata 承担治理 catalog、质量与协作，Gravitino 承担 technical metadata lake/federation，GIS Data Agent 仅保留其专属的 control/evidence contracts。

## Context

项目已有 `agent_data_assets`、四类 JSONB metadata、`agent_asset_lineage`、dataset intake、semantic registry、Standards Platform、STAC、Iceberg manifest 以及 model/prompt/tool 等多个 registry。这些组件解决了局部问题，但没有共同资源标识、不可变版本、采集状态、权威冲突规则和跨系统影响分析。

元数据中心必须覆盖空间与非空间资产，也必须覆盖数据生产对象和 AI/GWM 对象；它不能只是一张文件目录表，也不能成为存放所有内容的新数据库。

约束：支持私有化；当前团队不适合立即运维 DataHub/OpenMetadata、图数据库和搜索集群的完整组合；PostgreSQL 已是治理控制数据的主要载体；现有接口需要增量迁移。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 延续多个 registry + API 聚合 | 改动小 | 多写源、版本冲突和血缘断裂继续存在 | 不选 |
| B. 自建 PostgreSQL metadata control plane | 复用现有栈、事务/RLS/JSONB 成熟、适合增量演进 | 需要自行实现 harvester、搜索投影和权威规则 | **首期选择** |
| C. 立即引入 OpenMetadata/DataHub | 连接器、搜索、血缘 UI 和生态丰富 | 私有化运维、双向同步和第二写权威复杂 | 条件评审 |
| D. 图数据库作为元数据权威 | 影响分析表达自然 | 事务、权限、schema/version 与现有系统重复 | 不选；可作读投影 |

## Decision

### 1. 权威与边界

- PostgreSQL 中的 metadata control schema 是资源身份、版本、合同、owner、policy binding、质量摘要、血缘事件和产品状态的唯一写权威。
- Storage/Table/Compute provider 保存物理内容、snapshot/checkpoint 和外部 job 状态；默认包括 MinIO/S3、Iceberg、Spark/Flink，云 profile 可绑定 ADLS 等云存储与认证计算服务，轻量 profile 可绑定 PostGIS/DuckDB。STAC 保存地理发现投影。元数据中心引用并同步这些事实，不复制其全部内容。
- 搜索索引、图/RDF、STAC 和 Agent context 都是可重建读投影，不成为第二写权威。

### 2. 核心模型

首期核心对象：

```text
Namespace
Resource(ResourceURN, kind, owner, tenant, lifecycle)
ResourceVersion(version_id, resource_urn, schema_ref, content_hash, valid_time)
PhysicalLocation(system, locator, snapshot_or_revision, checksum)
DeploymentProfile -> StorageBinding / TableFormatCatalogBinding / ComputeBinding
EngineProvider -> EngineCapability -> CertificationResult
SchemaVersion -> Field
DataContractVersion
DataProductVersion -> Projection
PolicyBinding / Classification / Tag / GlossaryTerm
QualityAssessment
LineageEvent(source_version, target_version, run_id, operation)
MetadataSource / HarvestRun / HarvestObservation
```

`kind` 首期至少覆盖 object、table、raster、document、stream、workflow、model、prompt、tool、dataset、data_product、projection、GWM observation/scenario。

JSONB 只保存各 kind 的扩展属性；标识、版本、状态、owner、位置、权限、质量和血缘关系使用受约束列/表。

### 3. 采集和变更

- 为 PostGIS/DuckDB information schema、Iceberg/云湖表 catalog/snapshot、STAC、对象存储 manifest、Spark/Flink/云 job、workflow、Standards、model/prompt/tool 建立 provider-aware adapter/harvester。
- 记录 provider、region、engine/version、capability、credential reference、binding revision、cost class 和 conformance status；不把 secret 内容写入元数据。
- Harvester 使用 source revision、cursor 和 observation hash 幂等运行；发现删除时先标记 tombstone，不立即物理删除历史版本。
- API 写入、pipeline 发布和 harvester 观察都生成 `MetadataChangeEvent`；transactional outbox 保证提交与事件一致。
- 冲突按 authority matrix 解析：owner/steward 维护业务描述和分类；物理系统维护技术结构；pipeline run 维护产物和运行血缘；policy service 维护访问规则。低权威来源不能静默覆盖高权威字段。

### 4. Lineage

- `LineageEvent` 是新血缘写权威，边投影由事件生成。
- 运行血缘由统一调度控制面根据 input/output binding 自动记录；人工关系必须带 actor、reason、evidence 和 approval。
- `lineage_metadata` JSONB 和现有 `agent_asset_lineage` 通过迁移 adapter 兼容读取，停止并行自由写入后再退役。
- 影响分析同时检查 schema compatibility、quality、policy、product/projection 和 active schedule，不只遍历资产边。

### 5. 安全

- 所有 command/query 携带 `SubjectContext(tenant, subject, roles, purpose, trace)`。
- repository 在单个事务中注入 RLS GUC，并执行显式资源授权；表 owner 连接不能成为常规应用身份。
- metadata search 只能返回调用者有权发现的资源；受限字段、样本、位置和 lineage 节点可按策略隐藏。
- sort/filter/layer 等动态字段必须来自服务端枚举，不允许请求文本进入 SQL identifier。

### 6. API 与 SLO

首期提供 resource resolve、version detail、search、location、contract、quality、lineage/impact、harvest status 和 change feed API。每个结果返回 authority、observed_at、freshness 和 source。

AR-0 冻结 freshness、harvest latency、search latency 和 impact completeness SLO；在真实规模基准前不预设虚假数字。

## Migration Strategy

1. 盘点 `agent_data_assets`、lineage、intake、semantic、Standards、STAC/Iceberg 与 AI registry，生成 crosswalk 和重复项报告。
2. 建立 ResourceURN 规则和只读 projection，不立刻替换旧 API。
3. 让 AR-2 地类图斑链只通过新 API 创建版本、位置、质量和血缘。
4. 双读校验，禁止双写；旧写入口改为调用 control plane command。
5. 达到一致性门后停止 JSONB lineage 和局部 registry 的权威写入。

## Consequences

### Positive

- 所有存储、pipeline、AI 和 GWM 对象有统一身份、版本和影响链。
- metadata freshness、schema drift、质量失败和上游变化能驱动统一重算/审批。
- 保留现有 PostgreSQL 与组件投资，不引入第二治理写权威。

### Negative

- 需要设计 canonical model、authority matrix 和多系统 harvester。
- 迁移期间要维护兼容投影并处理历史脏数据。
- PostgreSQL 搜索/图遍历在大规模下可能成为瓶颈。

### Mitigation

- 先覆盖首条 vertical slice 所需 kind 和查询，不一次建全域模型。
- 用 contract tests、source checksum、双读 diff 和 metadata quality dashboard 控制迁移。
- 只有 PostgreSQL 的搜索/遍历 SLO 被真实负载击穿后，才增加 OpenSearch/graph 读投影。

## Revisit Triggers

- 资源规模、全文/向量搜索或 lineage traversal 使 PostgreSQL 读投影无法达到冻结 SLO。
- 外部生态要求 OpenMetadata/DataHub 双向互操作，且 adapter 成本高于采用成本。
- 跨组织 metadata federation 成为已批准产品需求。
- 元数据写吞吐或区域容灾要求超出单一 PostgreSQL 控制面的能力。
