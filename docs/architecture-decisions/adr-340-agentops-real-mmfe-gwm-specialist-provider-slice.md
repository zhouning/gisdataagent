# ADR-340：AgentOps 真实 MMFE/GWM specialist provider slice

## 状态

已验证 bounded sandbox slice；不代表 staging/production readiness。

## 背景

ADR-336 的六 specialist TaskGraph 已经能在真实 Temporal 上完成调度、显式重试、receipt
回写和 history replay，但 activity executor 仍是 synthetic。这样只能证明控制流，不能证明
MMFE/GWM 真正消费了平台 Artifact、产生了可追溯输出，也不能证明 provider 输入不会绕过
control plane 直接携带临时路径。

## 决策

1. 在 `TemporalActivityRequest` 中增加可选、hash-bound 的
   `TemporalProviderExecutionSpec`：固定 `provider_ref`、`operation_ref`、参数、输出媒体类型
   和被选中的输入 Artifact UUID。请求仍可携带上游完整 artifact 集合，但 provider 只能读取
   spec 明确选择的 UUID。
2. 通过注入的 `SpecialistArtifactStore` 解析输入并幂等写入输出。Temporal workflow 不读取
   文件路径、不保存 provider 凭据，也不成为 Artifact authority。
3. 首个 provider slice 只认证两项已有 runtime：
   `provider:mmfe.local / mmfe.execute_fusion.v1` 调用现有 MMFE profile/compatibility/alignment/
   execute pipeline；`provider:gwm.local / gwm.render_canonical_observation.v1` 调用现有
   MMFE UWM state-input 到 canonical observation renderer。
4. bounded rehearsal 使用临时 filesystem artifact store；输出 manifest 固化
   `request_sha256`、输入 artifact 列表、lineage、content SHA-256、MMFE quality/strategy 或
   GWM claim boundary。生产接入必须替换为 PostgreSQL Artifact authority + 配置的对象/表存储
   adapter，并保留相同合同。
5. provider 失败返回 typed failed receipt；不自动伪造质量、血缘或生产 readiness。旧的无
   provider spec activity 仍保持兼容，以便历史 workflow replay。

## 结果

2026-08-28 在真实 Temporal `1.29.7` / Python SDK `1.32.0` sandbox 完成 bounded rehearsal：

- 4 个 execution waves、6 个 ToolCall、6 个显式 activity schedule/completion；
- MMFE specialist 使用两个 GeoJSON Artifact，真实执行 `spatial_join`，输出 1 行 GeoJSON，
  quality score `1.0`，输出 checksum 为
  `752544cd18e8c04da3ca799e1232c499a5c5af3dac8cc9387139e2f0791fb069`；
- GWM specialist 使用一个 `mmfe.uwm_state_input.v1` Artifact，真实生成
  `uwm.canonical_observation.v1`，claim boundary 为 `bounded_support`；
- 两个输出均有 source Artifact lineage 和幂等 replay；Temporal history 41 events，
  Replayer replay 通过；
- 报告中 `production_readiness_claimed=false`。

## 证据

- [real specialist rehearsal report](../reports/agentops_temporal_real_specialists_2026-08-28.json)
  （文件 SHA-256：`2081ad7a89d955a2f6d58dc9b2a7e4255efec7557a48f78013b22d0169b8c135`，报告内
  canonical `report_sha256=e0a732c135eb6dedef311cbb3d097d4683fddc84bb98c5e4f81f431eb59129de`）
- [Temporal history export](../reports/agentops_temporal_real_specialists_history_2026-08-28.json)
  （文件 SHA-256：`e23a73781077da13e75881a2a2507225da3759fe743bad9c0c725c02c4679658`）
- [rehearsal script](../../scripts/rehearse_agentops_temporal_real_specialists.py)
- [provider contract tests](../../data_agent/test_agentops_specialist_providers.py)

## 保留边界

该 slice 只覆盖本地 bounded artifact store、一个 Temporal namespace、单 worker runtime 和
两个 provider operation。它不代表 PostgreSQL Artifact authority、MinIO/Iceberg/PostGIS
真实生产 provider、跨引擎一致性、provider cancellation/unknown 对账、NetworkPolicy enforcement、
identity/secret rotation、HA/backup/restore、SLO、shadow/canary、online verdict、incident/
rollback 或 production readiness 已完成。

## 后续切片：PostgreSQL Artifact authority 适配

在同一日期补齐了 provider store 的第二个实现边界：

- `PostgresArtifactAuthoritySpecialistStore` 通过现有 `PlatformGateway` 读取和登记
  `gda_control.artifact`，不新建 AgentOps 目录或第二套写权威；输入解析前必须先通过
  tenant-scoped Artifact UUID 查询，再由注入的 content backend 读取 bytes。
- `FilesystemArtifactContentBackend` 仅作为 disposable content plane；`S3ArtifactContentBackend`
  支持 MinIO/S3-compatible `s3://bucket/key`，可强制 Artifact manifest 绑定不可变
  `VersionId`。URI 不携带凭据，输出写入后以 checksum、media type、manifest 做 authority
  回读校验。
- provider output 的 Artifact UUID、checksum、媒体类型和 manifest 发生冲突时 fail closed；
  相同身份重放只回读已有 Artifact，不再次执行 provider 写入。

真实 bounded rehearsal 使用临时 PostgreSQL database（由 `092`/`094` control ledger/gateway
migration 创建）和临时 filesystem content backend，Temporal server `1.29.7`、Python SDK
`1.32.0`。3 个输入 Artifact 先登记到 PostgreSQL，MMFE/GWM 在真实 Temporal activity 中
读取这些 UUID，2 个输出 Artifact 再登记回 PostgreSQL；4 个 execution waves、6 个
activity schedule/completion、41 个 history events 和 Replayer replay 通过，且输出
authority lookup 通过。报告中的
`artifact_authority.production_readiness_claimed=false` 保留边界。

证据：

- [PostgreSQL Artifact authority rehearsal report](../reports/agentops_temporal_postgres_artifact_authority_2026-08-28.json)
  （文件 SHA-256：`7d2830c4d635ca009aad87619e7cc8a544647a2ffd3231ba197b8ec40ed36a0e`，报告内
  canonical `report_sha256=f72440316dcdfd7777a31103acbd57e6f45ae7459ffbdabde70821a6d487d396`）
- [Temporal history export](../reports/agentops_temporal_postgres_artifact_authority_history_2026-08-28.json)
  （文件 SHA-256：`6202e5503e93d9f4e8a9ab92ccee9552d5086fc0d221b316407e661044ae15bf`）
- [PostgreSQL authority rehearsal script](../../scripts/rehearse_agentops_temporal_postgres_artifact_authority.py)
- [Provider/authority contract tests](../../data_agent/test_agentops_specialist_providers.py)

该切片仍不等于生产 Artifact authority：content backend 仍为临时 filesystem，未完成
MinIO/Iceberg/PostGIS 生产 provider、对象锁/跨区复制、provider cancellation/unknown 对账、
cross-engine conformance、identity/secret rotation、HA/backup/restore、SLO 或 production
readiness。

随后在同一 disposable PostgreSQL/Temporal 环境切换到现有 MinIO `S3ArtifactContentBackend`，
开启临时 bucket versioning 并要求 VersionId：3 个输入和 2 个输出 Artifact 的对象各只有 1
个版本，输出 manifest 均绑定 VersionId，authority lookup、41-event history 和 Replayer
replay 通过。报告的 `artifact_authority.each_object_single_version=true`、
`output_version_ids_bound=true`，但 bucket、凭据和运行仍是本地 sandbox，不能外推为生产
对象锁、跨区复制或 identity rotation。

证据：

- [MinIO/S3 Artifact authority rehearsal report](../reports/agentops_temporal_postgres_artifact_authority_s3_2026-08-28.json)
  （文件 SHA-256：`e70566ca02da49e9cbbb5bb84573e1664515c7653e461b031cfcb6dc2897904a`，报告内
  `report_sha256=344c69a3d91f38ce59456f92a49820aac46c03bd0ca3b6b38b1acfdbc1735b28`）
- [Temporal history export](../reports/agentops_temporal_postgres_artifact_authority_s3_history_2026-08-28.json)
  （文件 SHA-256：`3a8893457e1a61a0491a892f53558861013aecf30ed16c54c5aeebf588dcca84`）
