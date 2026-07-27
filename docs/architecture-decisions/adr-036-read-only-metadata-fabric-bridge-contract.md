# ADR-036：只读 Metadata Fabric Bridge 合同

**Status**: Accepted

**Date**: 2026-07-27

**Decision owners**: Platform Architecture, Metadata Platform, Data Governance, Security

**Related decisions**: [ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) · [ADR-020](adr-020-platform-resource-run-and-evidence-contracts.md) · [ADR-021](adr-021-legacy-crosswalk-and-golden-slice.md)

## Context

ADR-006 已决定以 OpenMetadata、Apache Gravitino 和 GDA Control Ledger 组成三层 Metadata Fabric，但此前仓库只有目标架构，没有可执行的 ResourceURN 映射、provider 版本边界、重放指纹和 authority conflict gate。此时直接启用 OpenMetadata ingestion、Gravitino catalog mutation 或 legacy 双写，会让外部目录在尚未证明身份一致性时获得事实写入权。

首条地类图斑 golden slice 已提供不可变 `ResourceVersion`、内容 checksum、Run、QualityResult、Artifact 和 LineageEvent。因此 AR-1 M1 应先证明同一资源版本能够被两个外部元数据层无歧义解析，再进入 M2/M3 的真实部署和写入。

## Decision

### 1. M1 只读边界

新增 `data_agent.metadata_fabric_bridge`，只允许以下 provider 操作：

- OpenMetadata `GET /api/v1/tables/{id}`；
- Gravitino `GET /api/version`；
- Gravitino `GET /api/metalakes/{metalake}/catalogs/{catalog}/schemas/{schema}/tables/{table}`。

M1 不提供 POST、PUT、PATCH、DELETE，不运行 ingestion，不创建 catalog/table，也不更新 GDA ledger。OpenMetadata 固定 `1.13.1`；Gravitino profile 和 ref 必须固定准确的 `1.3.x` patch，禁止 `latest` 或仅固定 minor line。

### 2. 映射合同

一个 table slice 的 `MetadataFabricBinding` 必须绑定：

- GDA `tenant_id`、`ResourceURN`、`ResourceVersion UUID` 和 `content_sha256`；
- 恰好一个 OpenMetadata table entity ID、FQN 和 entity version；
- 至少一个唯一的 Gravitino metalake/catalog/schema/table 与 provider revision；
- 全量 canonical JSON `binding_sha256`。

GDA `Resource.governance_ref` 和有序 `technical_refs` 必须与 binding 完全一致。bridge 不猜测 identity、不按名称模糊匹配，也不为旧目录自动生成 ResourceVersion。

### 3. Authority gate

OpenMetadata observation 必须返回非删除 entity、owner、固定 entity version，以及 extension 中的 GDA 三元组。Gravitino observation 必须返回成功 code、精确 table name，以及 properties 中的 GDA 三元组和 provider revision。

权威边界保持为：

| 事实 | Authority | Bridge 行为 |
|---|---|---|
| owner、domain、glossary、classification、quality discovery、generic lineage | OpenMetadata | 只读观察并形成 snapshot hash |
| metalake、catalog、schema、table、technical access metadata | Gravitino | 只读观察并形成 snapshot hash |
| ResourceURN、ResourceVersion、content checksum、Run、Policy、Approval、Artifact、Evidence | GDA Control Ledger | 只比较，不允许 provider 覆盖 |

任一 provider 返回不同 ResourceURN、version UUID、content checksum、owner、provider revision，或出现缺失/重复 ref，reconciliation 均为 `blocked`。provider 返回 success 不改变 GDA 事实。

### 4. 安全与证据

- provider API root 必须是无凭据、无 query/fragment 的 HTTPS `/api` URL；
- token 使用 `SecretStr`，不进入 profile dump、exception 或 reconciliation artifact；
- provider payload 中出现 token、password、secret、private key、API/access key 等字段时 fail closed；
- reconciliation 只保存 provider snapshot hash、blocker 和自身 fingerprint，不保存原始 payload；
- `production_provider_verified=false` 是 M1 固定值，合成 fixture 不能证明 live provider、身份、备份恢复或生产准入。

## Acceptance

M1 退出条件：

1. 固定地类图斑 ResourceVersion 可重复得到相同 binding 与 reconciliation fingerprint；
2. 正向 mapping 为 `verified`，且明确 `writes_performed=false`；
3. 删除态、缺 mapping、secret 字段、owner 漂移、GDA identity 漂移、provider revision 漂移、重复 technical ref 和跨 tenant 均 fail closed；
4. mock transport 证明客户端只调用已批准 GET 路径；
5. CI 同时运行模块 validator 与定向测试。

这些条件不等于 ADR-006 的完整退出门。M2/M3 仍需真实部署 OpenMetadata/Gravitino，配置独立 persistence、OIDC、backup/restore 和升级责任，并在同一地类图斑产品上完成受控 ingestion、replay、OpenLineage、Gravitino Spark/Sedona/Flink conformance 和无双写验收。

## Consequences

**Positive**：在引入多套外部控制面前先固定身份和权威冲突语义；provider 故障或脏 payload 不会改变 GDA 真值；后续写入 adapter 可复用相同 binding 和 reconciliation evidence。

**Negative**：M1 不能向用户提供 OpenMetadata 搜索 UI，也不能证明 Gravitino 能作为 production TableCatalogProvider。

**Mitigation**：保持范围为首条 table slice，后续每个 object kind 和 provider 独立增加 contract/conformance；未通过真实 POC 的类型不进入生产 profile。
