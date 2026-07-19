# ADR-006: 采用 OpenMetadata + Apache Gravitino 构建双层 Metadata Fabric

**Status**: Accepted

**Date**: 2026-07-19

**Decision owners**: Platform Architecture, Data Governance, Security, GIS Engineering

**Supersedes**: ADR-002 的“首期自建 PostgreSQL metadata control plane”框架选型；其中的 `ResourceURN`、版本、权限和证据约束仍然有效，但不再把通用 catalog/governance 或跨引擎 technical catalog 作为自研目标。

**Related decisions**: ADR-001、ADR-004、ADR-005、ADR-007

## Context

GIS Data Agent 已有 `MetadataManager`、`agent_data_assets`、局部 lineage、semantic registry、STAC/Iceberg manifest、Standards、model/prompt/tool registry。这些模块都不具备企业级元数据中心应有的连接器生态、资产发现、治理协作、全文/语义检索、数据产品、质量测试、血缘可视化、事件、审计和可运营 UI。

前一轮只选择 OpenMetadata，遗漏了 Apache Gravitino 的关键定位：它不是另一个业务 catalog UI，而是面向 filestore、关系库、event stream 和 lakehouse 的 technical metadata lake、跨 catalog federation 与多地域 metadata plane。GIS Data Agent 默认 MinIO + Iceberg、Spark + Flink、可配置云和私有化的组合，必须有这个层的明确位置。

但 Gravitino 官方 1.3 文档同时声明：多引擎查询当前明确支持 Trino，Spark/Flink 支持仍在 roadmap。因此不能把它未经验证地指定为默认 Spark/Flink 的唯一 Iceberg catalog。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 自建 PostgreSQL catalog/metadata framework | 与现有代码衔接直接 | 要自行建设连接器、搜索、治理 UI、质量、血缘图、跨 catalog federation、升级与生态 | 不选 |
| B. OpenMetadata 单独承担治理与技术 catalog | 治理、质量、lineage、搜索、协作完整 | 不是面向多引擎 lakehouse federation 的 metadata lake；会把 technical catalog/provider 适配压力留给 GDA | 不选 |
| C. Gravitino 单独承担全部元数据 | direct metadata management、metalake、catalog federation、geo-distribution、data/AI asset 方向强 | 不提供 OpenMetadata 级别的业务治理、质量、ownership/glossary/lineage 工作台；Spark/Flink 互操作仍需验证 | 不选 |
| D. DataHub | active metadata、扩展模型、connector 和 lineage 生态成熟 | 默认架构对 Kafka/search 等依赖更重；不能替代 Gravitino 的 technical metadata lake 定位 | 保留为未来替代候选，不作为默认 |
| E. OpenMetadata + Gravitino + GDA Control Ledger | 治理、technical federation、产品/行动证据三层职责清晰 | 多系统集成和 authority mapping 更严格 | **选择** |
| F. 云 provider catalog | 云服务整合强 | 私有化、多云、可移植性和扩展控制不足 | 作为 provider adapter，不作为产品内核 |

## Decision

### 1. 三层 Metadata Fabric

```text
OpenMetadata
  Enterprise governance catalog
  owner/steward, domain, glossary, classification, quality, generic lineage, discovery

Apache Gravitino
  Technical metadata lake and federation
  metalake, catalog, schema, table/fileset/topic, cross-catalog/region access plane

GIS Data Agent Control Ledger
  ResourceURN mapping, immutable definitions/inputs, policy/approval,
  PlatformRun, artifact/evidence, action/outcome, GWM-specific facts
```

OpenMetadata 采用自托管 1.13.1 认证基线。Gravitino 采用 1.3.x 认证线，准确 patch、connector 和 API compatibility 由 AR-1 的 MinIO/Iceberg/Spark/Flink POC 固化；二者均禁止使用浮动 `latest` 镜像。

### 2. 权威边界与禁止双写

| 事实 | 写权威 | GDA 保存内容 |
|---|---|---|
| owner、domain、glossary、classification、业务描述、通用质量、generic lineage、discovery/search | OpenMetadata | `entityLink/entityId`、版本化引用、用于回放的 evidence snapshot/hash |
| metalake/catalog/schema/table/fileset/topic、catalog namespace、跨 catalog/region technical access metadata | Gravitino | `metalake/catalog/object` reference、catalog revision、provider binding、conformance evidence |
| object/table/job 的物理内容、snapshot/checkpoint、外部 job 状态 | storage/table/compute provider | provider reference、snapshot/job revision、采集时间和 hash |
| ResourceURN、DefinitionVersion、InputBinding、PlatformRun、PolicyDecision、Approval、ChangeSet、Artifact、Action、Outcome、GWM evidence | GIS Data Agent Control Ledger | 专属领域真值，不复制为 catalog 自由字段 |

稳定 `gda://{tenant}/{kind}/{id}` 映射到一个 OpenMetadata entity 和零到多个 Gravitino object。GDA 不接受 generic metadata 的自由写入；OpenMetadata 不手工维护 Gravitino technical object；Gravitino 不取代产品发布、审批或 GWM/action 真值。

### 3. Gravitino 的生产准入边界

Gravitino 从 AR-1 起进入首批 technical metadata/federation POC，不推迟到条件规模阶段。它的角色分两步：

1. **立即验证**：metalake/catalog namespace、MinIO/Iceberg technical metadata、provider identity、跨环境引用、OpenMetadata bridge、审计和 disaster recovery。
2. **认证后提升**：只有 Spark/Sedona 与 Flink 对同一 Iceberg 表通过 create/read/write/schema evolution/snapshot/time travel/cancel/reconcile/lineage 的真实 conformance 后，Gravitino 才能成为该 DeploymentProfile 的 `TableCatalogProvider` 或统一 technical access plane。

在此之前，默认 Lakehouse 仍通过独立、已认证的 Iceberg REST catalog provider 运行；Gravitino 不得成为未验证的 Spark/Flink 单点依赖。PostGIS、STAC、GWM/Agent 专属对象也只在 connector/extension 已认证时纳入其 technical object model。

### 4. GIS、语义、质量和安全集成

- `gda-metadata-fabric-bridge` 包含 OpenMetadata governance adapter、Gravitino technical catalog adapter、ResourceURN crosswalk 和 OpenLineage emitter；不 fork 任一上游项目。
- 空间/时态/证据字段通过 OpenMetadata custom properties/术语和 Gravitino catalog property/reference 双向关联，首期至少覆盖 CRS、axis order、geometry type、spatial extent、resolution、valid/event time、source/evidence class、contract version。
- OpenMetadata 的 test suite 承担 completeness/freshness/schema/SQL 质量；GIS Data Agent typed operators 承担 geometry validity、topology、面积守恒、时空一致性和 evidence ceiling，结果回写为可发现质量事实。
- GDA gateway 先完成 `SubjectContext + PolicyDecision`；随后通过 Gravitino provider credential/access plane 和底层 RLS/bucket/engine identity 纵深执行。任何 catalog 权限都不能单独替代空间、时间、行列或行动授权。

### 5. 采集、血缘与调度

- DolphinScheduler 统一触发和审计 OpenMetadata/Gravitino ingestion、reconciliation、reindex 与 bridge replay，禁止另建 catalog scheduler。
- `gda-lineage-emitter` 将 DolphinScheduler、Temporal、Spark/Flink adapter 和发布器的版本化 OpenLineage event 关联到 `PlatformRun`，再由 bridge 投影到 OpenMetadata；Gravitino 保存 technical object relationship，GDA 保存 action/evidence 因果链。

## Migration Plan

1. **M0 - Foundation**：在独立 namespace 部署 OpenMetadata PostgreSQL/OpenSearch 和 Gravitino metadata store，配置 OIDC、backup/PITR、OTel/Prometheus、upgrade rehearsal；不导入生产写流量。
2. **M1 - Fabric contract**：发布 `gda-metadata-fabric-bridge`、ResourceURN/entity/object mapping、GIS properties、OpenLineage envelope、authority matrix 和 conflict tests。
3. **M2 - Gravitino conformance POC**：以地类图斑 MinIO/Iceberg slice 验证 Gravitino technical catalog；Spark/Sedona 和 Flink 必须分别跑真实读写、schema evolution、snapshot、cancel/reconcile 和 lineage，不以文档或 Trino 成功替代。
4. **M3 - Governance slice**：将 OpenMetadata ingestion、owner/domain/contract/quality/impact 和 Gravitino technical references 接入同一 DataProductVersion；完成 PostGIS/STAC bridge。
5. **M4 - Cutover**：`MetadataManager` 和局部 registry 改为 bridge facade；旧 JSONB 只读兼容，禁止新增 generic metadata 写入。
6. **M5 - Expansion**：接入 Azure、其他 catalog、跨区域 federation、MMFE、Agent/GWM 可发现资产；每个 provider 独立认证。

## Acceptance Criteria

- 一个真实 DataProductVersion 可从 OpenMetadata 检索 owner/domain/contract/质量/血缘，也可解析其 Gravitino technical object、Iceberg snapshot、Spark/Flink job、STAC item 和 `PlatformRun`。
- ResourceURN、OpenMetadata entity、Gravitino object、物理 snapshot 和 Artifact 映射无未解释多对多；bridge replay 不产生重复对象或隐式覆盖。
- Gravitino 未通过 Spark/Sedona/Flink 双引擎 conformance 时，平台自动拒绝其作为该 profile 的 production TableCatalogProvider；已认证的替代 Iceberg catalog 继续运行。
- schema/CRS/policy/quality 变更产生可审计 impact set；无权主体和 Agent context 看不到受限字段、asset、catalog relation 或 lineage。
- catalog reindex、Gravitino metadata restore、bridge replay 和 GDA backup restore 不丢失产品/行动控制真值。

## Consequences

**Positive**：不再自研治理 catalog 或跨引擎 technical metadata lake；为多云、多 catalog、Trino/后续多引擎与数据/AI asset federation 预留正确层次；GIS Data Agent 可聚焦空间语义、行动与 GWM。

**Negative**：新增 OpenMetadata、Gravitino、search backend 与双 bridge 运维面；Spark/Flink 互操作成熟度必须以真实证据决定，不能由 marketing 推断。

**Mitigation**：独立数据库/namespace、版本 pin、authority contract tests、bridge replay、升级 sandbox、备份恢复演练、provider conformance gate，以及不 fork OpenMetadata/Gravitino core。

## Revisit Triggers

- Gravitino 无法通过 MinIO/Iceberg/Spark/Sedona/Flink、私有化、安全或升级兼容性验收；
- OpenMetadata 无法通过治理、空间扩展、性能或升级兼容性验收；
- DataHub 或云 catalog 在一套可量化 TCO/功能矩阵上更优；此时替换 provider/adapter，不改写 GDA contracts。
