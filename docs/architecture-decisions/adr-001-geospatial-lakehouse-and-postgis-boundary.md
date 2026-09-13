# ADR-001：可插拔地理空间存储、计算与服务边界

**Status**: Accepted

**Date**: 2026-07-19

**Decision owners**: Platform Architecture, Data Platform, GIS Engineering

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md)

**Related decisions**: [ADR-002 统一元数据控制面](adr-002-unified-metadata-control-plane.md) · [ADR-003 统一调度与作业控制面](adr-003-unified-orchestration-and-job-control-plane.md) · [ADR-004 能力下限与 Human/Agent 双入口](adr-004-capability-floor-and-dual-entry-agentic-platform.md) · [ADR-005 DataOps 与 AgentOps 双运营闭环](adr-005-dataops-and-agentops-operating-loops.md)

## Context

GIS Data Agent 已同时使用本地文件、PostgreSQL/PostGIS、MinIO/S3、治理元数据、MMFE、STAC 合同和独立 Spark/Sedona/Iceberg 作业。产品同时要求支持默认私有化湖仓、云平台托管能力和轻量存算一体部署。当前既没有统一规定哪一处保存原始证据、分析表、治理权威、在线空间视图和 AI/GWM 快照，也没有把存储与计算后端建模为可替换能力，导致以下问题：

- 用户文件、随机 PostGIS 表和实验输出都可能被当作数据真值。
- ODS/DWD/DWS/ADS 只存在于设计文档，没有形成强制运行时。
- MinIO、Iceberg、STAC 和 PostGIS 的职责重叠或停留在 spec。
- 治理、Agent 和 GWM 能力绕过统一数据产品版本直接消费数据。
- 无法稳定提供 snapshot、time travel、重放、回滚和跨引擎 lineage。
- pipeline 和元数据直接绑定具体 URI、表或执行器，切换云平台或轻量引擎会形成分叉实现。

约束：当前团队规模不适合全面微服务；必须支持私有化和云平台部署；默认数据湖存储为 MinIO，默认批流计算为 Spark/Sedona 与 Flink；空间编辑和低延迟查询仍需要 PostGIS；PostGIS 或 DuckDB 可承载轻量存算一体场景；遥感和多模态大对象不能无条件进入单一关系数据库；已有组件应增量演进。

## Options Considered

| Option | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. PostGIS-centric | 简单，空间 SQL 和在线服务成熟 | 大对象、历史快照、批量扫描、schema 演进和跨引擎训练受限 | 不选作统一分析真值；保留 serving/operational 职责 |
| B. 文件/对象存储 + 临时表 | 接入快，适合原型 | 缺 ACID、catalog、版本、治理和一致消费 | 淘汰为主线，仅保留 Raw 和临时工作区 |
| C. 固定 MinIO/S3 + Iceberg + Spark/Flink，PostGIS serving | 开放格式、批流扩展与空间在线服务兼得 | 无法满足云托管替换与轻量部署 | 不选作平台合同；作为默认 lakehouse profile |
| D. 完整分布式 lakehouse + federation immediately | 扩展性和查询面广 | 团队、负载和 SLO 证据不足，复杂度过高 | 延后，满足触发条件后再评审 |
| E. 稳定逻辑合同 + 可配置 storage/compute profile | 同一产品生命周期覆盖默认湖仓、云托管和轻量存算一体 | 需要 capability model、adapter certification 和跨引擎一致性测试 | **选择** |

## Decision

### 1. 逻辑真值不绑定物理引擎

- Landing/Raw 的不可变对象或贴源表版本及 manifest 是原始证据真值；轻量 profile 可以使用 PostGIS/DuckDB 的 append-only Raw schema/table，但必须保留 source checksum 和可导出 manifest。
- ODS/Bronze、DIM/DWD/Silver、DWS/Gold 的分析真值是元数据中心登记的不可变 `TableSnapshot/ResourceVersion`。默认湖仓 profile 使用 Iceberg snapshot；认证的云湖表或轻量引擎使用其等价 version/checkpoint 机制。
- PostgreSQL 是治理权威、产品合同、版本、质量、血缘、审批和审计真值。
- PostGIS operational 表可以是编辑事务的源系统，但有效变更必须产生版本/事件并重新进入 Raw/ODS，不得直接修改 Silver/Gold；ADS/Serving 空间投影从 DataProductVersion 可重建。
- STAC 是地理资产发现和交换目录；对象内容由所选对象存储的 locator、version 和 checksum 约束。
- AI Dataset 和 GWM Observation 是 DataProductVersion 的派生投影，不产生新的上游真值。

### 2. 可配置引擎合同

存储、湖表/目录和计算是三个可独立配置的维度，不把某个云产品名称写入 JobDefinition：

```text
DeploymentProfile
  -> StorageBinding(object/blob, warehouse, artifact, serving)
  -> TableFormatCatalogBinding(format, catalog, snapshot capability)
  -> ComputeBinding(batch, stream, interactive, spatial)
  -> EngineCapability + CredentialReference + Region/Cost/SLO
```

- `DataProductBlueprint` 声明数据层、规模、延迟、事务、空间、主权、成本和 SLO 需求；placement policy 解析为版本化 binding。
- `JobDefinitionVersion` 声明所需 capability 和 `portability_class = portable | engine_family | provider_native`，不直接硬编码 endpoint。
- portable typed TaskGraph 可由 provider compiler 生成 `ExecutionPlanArtifact` 并通过跨引擎 golden test；Spark/Flink 原生代码、特定 SQL dialect 或云原生作业必须声明 engine family/provider binding。迁移会产生新的 DefinitionVersion 和 changeset，不能静默转译或换引擎。
- `Run` 固化实际选择的 engine binding/version、input snapshot、配置和 artifact location，保证审计与重放。
- provider adapter 必须实现 discover/read/write/commit/rollback/checkpoint/cancel/reconcile/metrics 中其声明支持的能力；未认证能力不得被调度。

### 3. 部署 profiles

| Profile | 存储 | 湖表/目录 | 计算 | 适用边界 |
|---|---|---|---|---|
| **Default Lakehouse** | MinIO（S3 API）保存 Raw、COG、warehouse 和 artifact | Iceberg + 可配置 catalog | Spark/Sedona 批处理；Flink 流处理；PostGIS/DuckDB 交互与空间下推 | 默认私有化和标准生产部署 |
| **Cloud Managed** | 云对象/数据湖存储，例如 Azure Blob / ADLS Gen2 | 认证的 Iceberg 或云湖表/catalog adapter | 云 Spark 兼容批处理和 Flink 兼容/托管流执行器，例如 Azure 相关计算服务 | 利用云 IAM、弹性、区域、HA 与托管运维；具体服务逐项认证 |
| **Lightweight Integrated** | PostGIS 数据库或 DuckDB 数据库/文件；Raw 可用不可变 schema/table，大对象可外接对象存储 | schema/table/view + 受控 snapshot/export manifest | PostGIS SQL/空间算子或 DuckDB/Spatial 单机向量化执行 | 单机、边缘、开发、较小数据集；不宣称分布式扩展或无限并发写 |
| **Hybrid** | 按数据家族组合以上 binding | 保持统一 ResourceVersion/DataProductVersion | 每个 task 按 capability 路由 | 迁移、云地协同、轻重任务混合 |

默认值是产品提供的开箱配置，不是不可替换的架构边界。profile 切换由管理员策略或受审批 changeset 完成，Agent 不能自行跨 region/provider 迁移数据。云 profile 只有在 identity、加密、version/checkpoint、lineage、取消、监控、备份恢复和成本归因通过 certification 后才标记支持。

### 4. 格式与数据家族

- 矢量、表格和时序事实：Parquet/GeoParquet managed by Iceberg。首期跨引擎空间合同使用 `geometry_wkb + srid + bbox + optional h3/geohash`；原生 geometry/GeoParquet metadata 必须通过 Spark/Sedona、PyArrow/GeoPandas 和目标查询引擎的互操作测试后才能成为权威合同。
- 栅格和遥感：COG in object storage + STAC；索引、统计和派生事实可入 Iceberg。
- 文档、视频、点云、3D 和模型 artifact：对象存储 + manifest；结构化元数据和特征引用入治理库或 Iceberg。
- 默认 batch executor 是 Spark/Sedona，默认 stream executor 是 Flink；交互和小数据可路由到 DuckDB/Spatial、PostGIS pushdown 或本地 Python/GeoPandas。
- 轻量 profile 可以在 PostGIS 或 DuckDB 内实现多个逻辑层，但必须保留 layer、version、quality 和 lineage 边界；不得用“同一个数据库”取消分层。
- Iceberg 分区由查询 workload 决定，优先低基数时间、区域或受控空间分桶；不得默认按 `product_id`、object ID 或 geometry 等高基数字段分区。

### 5. 分层映射

只维护一套物理层：

```text
Landing/Raw -> ODS/Bronze -> DIM+DWD/Silver -> DWS/Gold -> ADS/Serving
```

禁止再建设与 Bronze/Silver/Gold 平行且含义重复的第二套 ODS/DWD/DWS 数据副本。轻量 profile 可以用 schema/table/view/snapshot 表达这些逻辑层；物理合并不能消除发布门和版本边界。

### 6. 发布和回滚

- 所有 serving、STAC、Agent、AI 和 GWM 投影由 DataProductVersion 发布。
- 发布记录输入 snapshot、代码/规则/标准版本、quality verdict、ACL、output hash 和 rollback pointer。
- PostGIS serving 表不得被下游当成未声明版本的上游输入。
- 失败发布不得推进 active product version；重试必须幂等。

### 7. 控制面部署形态

- 控制面继续采用模块化单体，以 PostgreSQL 为单一治理写权威。
- 首期 control、operational 和 serving 可以同 PostgreSQL 集群部署，但必须使用独立 schema、角色、连接池和备份/恢复边界；资源争用、RPO/RTO 或故障隔离基准失败后再物理拆库。
- Spark/Sedona、Flink、云计算服务、PostGIS 和 DuckDB 都通过统一 executor contract 调用；调度控制面不依赖某一执行器内部状态作为唯一运行真值。
- 开发 first slice 可以使用 Hadoop catalog；生产/多写场景必须在进入试点前评审 REST Catalog、HA、锁和灾备。
- 图、RDF、搜索、LanceDB、Trino 和 Kafka 不能仅因可用而自动成为主线依赖；Flink 是默认 stream executor，但高吞吐 CDC/事件总线及其额外基础设施仍按 workload 认证。

## Rationale

1. 默认 MinIO + Iceberg 提供当前 PostGIS/文件路径缺失的 snapshot、schema evolution、time travel 和批量数据管理能力，同时 provider contract 保留云替换能力。
2. PostGIS 保留其最强领域：空间编辑、索引、低延迟查询、在线服务和地图物化。
3. COG/STAC 避免把大栅格强行表格化，同时保留标准化发现和窗口读取。
4. PostgreSQL 中已有大量治理表，继续作为控制权威比立即引入第二 metadata platform 更可控。
5. Spark/Flink 默认 profile 覆盖标准批流生产，PostGIS/DuckDB 轻量 profile 避免小场景承担不必要的分布式运维。
6. 逻辑合同与 provider 分离，使同一 Definition 和 DataProductVersion 可跨私有化、Azure 等云平台和边缘环境演进。

## Trade-offs Accepted

- 分析真值与在线 serving 之间存在受控物化副本。
- 需要明确 snapshot-to-serving lineage、幂等发布和一致性监控。
- 团队必须维护 provider capability matrix、认证套件和不同 profile 的运维边界。
- 第一期不会获得跨所有引擎的透明联邦 SQL；消费者通过产品投影和受控 API 访问。

## Consequences

### Positive

- 数据分层、治理、湖仓、在线 GIS 和 AI/GWM 消费进入同一产品生命周期。
- 可以对原始证据、分析快照和在线视图区分真值、版本和回滚责任。
- 计算和存储可以按真实规模演进，不需要先拆分全面微服务。

### Negative

- 需要新增通用 storage/table/compute SPI、默认 Iceberg writer、Flink executor、catalog 运维、发布器和 projection rebuild 工具。
- PostGIS 与 Iceberg schema、geometry encoding 和权限映射需要契约测试。
- 对象、表、产品和 artifact 标识必须统一，否则 lineage 仍会断裂。
- 同一逻辑任务跨引擎可能出现数值、geometry、时间、水位线和 exactly-once 语义差异。

### Mitigation

- 先完成一个自然资源 vertical slice，再扩展数据家族。
- 每层使用 contract tests、golden reconciliation、content hash 和 end-to-end replay。
- 默认、云托管和轻量 profile 使用同一 conformance suite；跨引擎结果在批准容差内等价。
- 发布状态机统一记录 snapshot ID、serving build ID、STAC item ID 和 product version。
- 不达到实际负载门槛时不启用额外分布式组件。

## Revisit Triggers

出现以下任一情况时重新评审：

- PostGIS serving 重建无法达到冻结的 RTO/SLO。
- Iceberg catalog 出现多写、HA、租户隔离或灾备需求。
- 交互式跨湖仓/PostGIS 查询成为稳定产品需求，受控投影不能满足。
- embedding 达到百万级且 ANN 延迟不达标，需要专用向量读投影。
- 跨组织语义互操作无法由 PostgreSQL/JSON package/STAC/OGC 接口满足。
- 实际 workload 证明独立服务扩缩容或故障隔离收益超过模块化单体成本。
- 新 storage/compute provider 无法满足必需的 snapshot/checkpoint、权限、取消、reconcile、lineage、RPO/RTO 或成本归因合同。
