# ADR-102: Governed Source Definitions and Evidence-Backed Connector Certification

**Status**: Accepted  
**Date**: 2026-08-01  
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

现有 virtual-source connector 已能查询 database、object storage 和 STAC，但它们的主要边界是
交互式查询：调用者传入 `endpoint_url/auth_config/query_config`，connector 返回 provider 自描述或
查询结果。Fernet 加密解决了 virtual source 凭据落库时的明文问题，却没有形成 secret-free 的不可变
source identity，也没有回答某一 provider/version 的 connect、discover、preview 和 profile 是否被
真实执行并认证。

把 connector 类存在、HTTP 返回 200 或 UI 能列出 source 当作平台能力，会让未测试的 discovery、
错误凭据、网络恢复和 schema drift 被误登记为生产能力。另建一套 ingestion connector 则会让 virtual
query 和 DataOps 使用不同的协议实现与错误语义。

## Decision

### Secret-Free Source Contract

`SourceDefinition` 是 owner-bound、版本化、不可变声明，包含 source kind、无 userinfo 的 endpoint、
connector version、只读 query config 和 `CredentialReference`。它拒绝 endpoint 内嵌用户名/密码、
query config 携带 secret 字段及非只读认证。`CredentialReference` 只记录 credential ID、revision、
auth type 和 secret provider；运行时 resolver 才取得实际 secret，definition/report/fingerprint 均不
包含 secret。

credential revision 是 source fingerprint 的一部分，因此轮换不会静默改变既有定义。当前 resolver 是
可注入边界；本地认证使用 mapping 实现，生产可绑定 Vault/Kubernetes Secret/云 secret manager，
不改变 connector SPI。

### Reuse Connectors and Certify Operations

继续复用 `data_agent.connectors`。`BaseConnector.discover()` 为需要 bucket/prefix 等 source-scoped
配置的 provider 提供统一 hook；默认仍委托既有 `get_capabilities()`。

每次 certification 固定执行并记录：

1. `connect`：使用运行时 credential 做只读连通；
2. `discover`：获取 resource/collection/object 和可用 schema；
3. `preview`：最多读取 10 条受控样本；
4. `profile`：从样本生成字段、类型、nullable、geometry/CRS 画像。

每项 `SourceCapability` 必须是 `passed/failed/not_supported/not_evaluated` 之一；`passed` 必须带
evidence SHA-256。前序失败时后续操作保持 `not_evaluated`，不能推断为支持。错误信息会以本次运行时
credential 值进行脱敏。相同 discovery/profile 的 fingerprint 稳定，可用于重复探测和后续 drift
比较。

database connector 通过 SQLAlchemy URL 结构化注入 runtime credential，preview 仅接受单条
`SELECT/WITH` 并在 PostgreSQL transaction 中设置 `READ ONLY`。object-storage connector 对
S3/MinIO 使用 SigV4 `list/get`，不再以未授权 HTTP HEAD 小于 500 作为健康；指定 JSON/GeoJSON
对象时以同一只读 credential 形成字段 schema。STAC connector 同时读取根文档 conformance/version、
`/collections` 及 source-scoped `/search` Item schema，再通过 `/search` preview；bearer/API-key 等
runtime header 必须一致应用到 connect/discover/preview 的每个 HTTP 请求。两类 JSON 输入复用
确定性的嵌套字段路径、JSON 类型和 nullable 规范化，避免 provider-specific schema 语义分叉。

### Drift Boundary

`detect_schema_drift()` 比较两次 `DiscoverySnapshot` 的 resource/field/type/nullability；删除字段、
删除 resource、类型变化和 nullable 收紧判定为 breaking。对象 ETag 变化属于内容变化，不冒充 schema
drift。字段级 `SchemaFieldChange` 明确记录 `added/removed/type_changed/nullable_tightened/
nullable_relaxed`、变化前后类型/nullability 和 breaking verdict。事件总 verdict 必须与字段变化一致。

PostgreSQL 已用隔离 sandbox 完成真实 schema mutation/detection。迁移
`102_source_schema_drift_ledger` 将 `SchemaDriftEvent` 接入既有 PostgreSQL Control Ledger：不可变
evidence 与当前状态投影共存，所有状态变化通过 CAS function 追加 lifecycle event。非 breaking drift
可直接 reconcile；breaking drift 必须先绑定同租户 ApprovalCase ResourceURN 并被批准，不能绕过。
`observe_certification_schema_drift` 只允许同一 source、connector、provider 和不可变 SourceDefinition
的两次 passed certification 进入该账本，失败或定义切换不能产生 drift 事实。迁移 103 已进一步将该
引用接到统一 ApprovalCase authority；具体边界见
[ADR-103](adr-103-unified-approval-case-authority.md)。这仍不代表 provider 会被自动迁移。

## Evidence

`.tmp/source-connector-certification/acceptance-report.json` 使用同一已发布重庆 OSM 道路
`v1.2.0` STAC Item 作为 object 和 HTTP/STAC 输入，完成三类只读认证：

- PostgreSQL 16.14 / PostGIS 3.4.3：按 `query_config.table` 精确发现
  `gda_control.resource` 一张目标表，preview/profile 10 行、10 字段；未指定目标表的通用发现仍以
  50 张表为上限并显式记录 `truncated`；
- MinIO `RELEASE.2025-04-22T22-12-26Z`：通过 S3-compatible API 发现并读取
  `items/v1.2.0.json`，profile 1 个 geometry feature、46 字段、EPSG:4326；
- local STAC API 1.0.0 transport：根 conformance、1 个 collection、search preview/profile
  已通过，输入 Item 来自真实产品 API；该 transport 不是生产 stac-fastapi/pgSTAC 认证。

三类 source 共 12 项 capability 全部通过。完整认证重放得到相同 discovery/profile fingerprint。
错误 PostgreSQL credential、错误 MinIO credential 和 STAC 网络中断均产生失败报告，secret 扫描
通过。本轮 connector、schema drift、migration 和 platform contract 相关回归 128 项通过，2 项因宿主
未设置可选 `DATABASE_URL` 而跳过；真实 PostgreSQL 行为由下述隔离验收覆盖。

`.tmp/source-connector-certification/postgresql-rotation-drift-report.json` 使用一次性随机 schema、表和
只读 login role 进一步完成 PostgreSQL provider 验收：credential revision v1 全部通过；服务端
`ALTER ROLE ... PASSWORD` 后 stale v1 失败，revision v2 通过且 discovery fingerprint 不变；新增
nullable `observed_at TIMESTAMPTZ` 产生非 breaking `added`，`id INTEGER -> BIGINT` 产生 breaking
`type_changed`。只授予 `USAGE + SELECT` 的 role 尝试 `INSERT` 得到 SQLSTATE `42501`；报告未保存
运行时密码，随机 schema 和 role 最终均被删除并二次查询确认不存在。

`.tmp/source-connector-certification/minio-rotation-report.json` 将同一受治理重庆 OSM STAC Item 原样
复制到随机临时 bucket，并创建只允许 list/get 该对象的随机用户和 policy。revision v1 全部通过；
MinIO 服务端为同一 access key 更新 secret 后，stale v1 失败，revision v2 通过且 discovery/profile
fingerprint 不变。未授权 `PutObject` 返回 `AccessDenied`，管理员复查目标对象不存在；报告未保存
两版 runtime secret，临时 user、policy、policy file、object 和 bucket 均被删除并验证。provider
响应只登记 `MinIO/S3-compatible`，精确 release 继续来自 Compose runtime inventory，不从缺失的
S3 response header 推断。

`.tmp/source-connector-certification/stac-rotation-report.json` 使用只在验收期间存活的 authenticated
STAC HTTP transport 服务同一重庆 OSM Item。revision v1 的四项能力通过，错误 token 被拒绝；服务端
切换到 revision v2 后 stale v1 失败，v2 与重复认证通过且 discovery/profile/report fingerprint
稳定，网络中断失败关闭。transport 共记录 15 个授权请求和 2 个未授权请求，只保存 path、verdict 与
accepted revision，不保存 Authorization header/token；server 和 thread 最终均关闭。该证据认证
connector 的真实 HTTP bearer rotation，不认证 production stac-fastapi/pgSTAC provider。

`.tmp/source-connector-certification/drift-ledger-report.json` 在随机临时 PostgreSQL database 中执行
092/094/102/103 四个必要迁移，并通过真实 `SourceSchemaDriftLedger` 与 `ApprovalCaseAuthority` 验证 additive
`observed -> reconciled` 与 breaking `approval_required -> approved -> reconciled`。breaking approval
未登记、pending、过期、目标或 verdict 不匹配，以及直接 reconcile 均被拒绝；requester 自批、重复写、
stale CAS、直接 UPDATE 和跨租户读取也失败关闭。gateway 只有 base table `SELECT/INSERT`、event/lifecycle
`SELECT` 和 transition function `EXECUTE`，没有 base `UPDATE` 或 event/lifecycle `INSERT`。临时 database
已删除；主 Compose 随后通过专用 migration authority 应用迁移 103，105/105 applied records 且
catalog/database fingerprint 一致。

`.tmp/source-connector-certification/object-stac-drift-report.json` 使用真实重庆 OSM 道路 `v1.2.0`
STAC Item，在随机 MinIO bucket 与临时 authenticated STAC transport 中执行同一组非持久 schema
mutation。新增 `properties.gda:schema_drift_probe_v1:string` 在两类 provider 均形成 non-breaking
`added` 并 reconcile；随后 `string -> integer` 均形成 breaking `type_changed` 并停在
`approval_required`。两类 provider 三轮 certification 全部 passed、重复 observation 幂等且 drift
语义一致；12 项行为检查和 8 项清理检查全部通过，报告不含 runtime secret。随机 MinIO
user/policy/bucket、STAC server/thread 和 PostgreSQL database 均已删除，主库未新增 drift 数据。报告
SHA-256 为 `23cf344e592b6519f7d147ed4388dd162745e521be375de6f0301d6d6743efe6`。

## Consequences

- capability matrix 从静态 connector 名单升级为 provider operation 的可审计事实。
- virtual query 和 DataOps source governance 共用 connector 实现，减少协议分叉；原 virtual-source
  persistence 暂保持兼容，后续应迁移为 `SourceDefinition -> CredentialReference` projection。
- 本轮只认证只读接入面，不代表 full/incremental ingestion、duplicate ingestion、CDC、delete、
  watermark/checkpoint 或 reconciliation 已完成。
- PostgreSQL 的真实 credential rotation/schema mutation、MinIO 的真实 credential rotation、
  authenticated STAC transport rotation，以及 JSON/GeoJSON object-storage/STAC schema mutation
  已完成；统一 ApprovalCase 核心 authority 及 schema drift consumer 已完成。production STAC provider、
  非 JSON 对象 schema、三类 source 的重复摄取、provider 自动迁移、双租户和 network retry/resume 仍是
  AR-2 退出门，因此 AR-2 保持 `in_progress`。
