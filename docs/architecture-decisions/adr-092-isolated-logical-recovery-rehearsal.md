# ADR-092：采用隔离逻辑恢复与内容指纹作为恢复证据

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Platform Architecture, SRE

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0 / AR-2

## Context

仓库原有每日 PostgreSQL dump 和 7 天保留配置，但没有自动恢复验证，也没有把 MinIO、
PostGIS serving、migration ledger、released standard 和真实数据状态联合对账。原脚本还把
已经压缩的 PostgreSQL custom-format 输出再次 gzip，运维文档则示例直接对当前
`gis_agent` 执行 `pg_restore --clean`。这些做法既不能证明备份可恢复，也可能破坏在线库。

当前主 Compose 开发环境的 PostgreSQL 约 6.6 GB，MinIO lakehouse 约 2.29 GB。数据库
包含 93 条 migration、174 个 released standard 数据元以及真实重庆 TWM 状态、关系和
证据数据，已经足以执行有意义的恢复演练；不能继续用空库或 mock 作为灾备证据。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 只检查 dump 文件存在和非零 | 快、成本低 | 不能发现角色、扩展、约束和数据恢复失败 | 拒绝 |
| 在当前数据库执行 `pg_restore --clean` | 接近原文档 | 可能删除在线对象，无法隔离失败 | 拒绝 |
| 只比较 MinIO object count/size/ETag | 实现简单 | multipart ETag 不是稳定内容哈希，可能误判 | 拒绝 |
| 新建备份服务、registry 和 scheduler | 可扩展 | AR-0 阶段重复现有调度/控制面，复杂度过高 | 延后 |
| 一次性隔离容器 + 临时介质/bucket + 内容对账 | 不触碰源、证据真实、失败可清理 | I/O 成本高，仍不是生产 DR | **选择** |

## Decision

1. 恢复演练复用版本化 DeploymentProfile 和现有 Compose，不新增 registry、scheduler、
   queue 或常驻备份服务。运行前必须先通过完整 live deployment verifier；profile 污染
   或技术检查失败时不得开始备份。
2. PostgreSQL 使用 `pg_dump --format=custom --no-owner --no-acl`。dump 记录非敏感大小与
   SHA-256；日常备份写入 `.partial` 后原子 rename，不再重复 gzip。
3. 数据库恢复目标是 `--network none` 的临时 PostGIS 容器及其新匿名 volume，必须证明
   未挂载任何主 Compose named volume。结束时只删除该临时容器及其匿名 volume。
4. PostgreSQL cluster role 不在逻辑 dump 中。恢复目标预置无登录 `agent_user` 和
   `agent_reader` 以满足策略/对象引用；目标业务库必须从 `template0` 创建，避免 PostGIS
   镜像预装扩展与 dump 中扩展对象冲突。
5. `pg_restore` 使用 `--exit-on-error --single-transaction --no-owner --no-acl`。任何对象、
   约束、容量或角色错误都失败关闭，不接受部分恢复。
6. 数据库恢复后必须同时对账：
   - migration count 和 catalog/database fingerprint；
   - released standard doc/version/status、174 个数据元及元素内容 fingerprint；
   - ltree、PostGIS、pgvector 版本和 geometry column 数；
   - `twm_state_object`、`twm_state_relation`、`twm_evidence_item` 的精确行数。
7. 每个 MinIO bucket 执行 source → 临时本地介质 → 临时 restore bucket → 第二本地介质。
   两个本地对象树按相对 key、字节数和逐文件 SHA-256 生成 inventory fingerprint。不得用
   multipart ETag 替代内容身份，也不得在报告中输出 object key。
8. 临时 restore bucket 使用不可预测的 `gda-recovery-*` 名称并由 shell trap 清理；报告
   不保留绝对路径、凭据、对象 key 或数据样本。失败报告只输出 stage 和 error type。
9. 技术演练通过仍不等于 promotion 或 DR。报告固定保留 `backup_restore`、未定义 RPO、
   未批准 RTO、未验证异地副本、未验证加密和未证明跨系统时间点一致性等 blocker。
   观测耗时只能作为 baseline，不能自动成为 SLO。

## Development Rehearsal Result

2026-07-31 主 Compose 全量隔离演练最终通过：

- PostgreSQL source 约 6.66 GB；custom-format dump 3,028,622,216 bytes，备份耗时
  258.598 秒，隔离恢复耗时 187.532 秒；
- source/restored migration 均为 93 条，fingerprint 为
  `53ddf178936f4b6ce909bf553e66f33270d9cf815a87458e60de332f69af9ee4`；
- source/restored standard 均为 `NR_ONE_MAP_TWM_CORE_2026@2026-06-16-draft`、released、
  174 个数据元，fingerprint 为
  `a9b58ea766e1f7fd0f203b07bb23e3848e1db7dad560ebf04843b83a5b713630`；
- source/restored `twm_state_object=777332`、`twm_state_relation=1433322`、
  `twm_evidence_item=29556`，扩展版本和 4 个 geometry column 一致；
- `gis-agent-lakehouse` 的 213 个对象、2,288,430,300 bytes 在恢复前后具有相同内容
  inventory fingerprint
  `9ca34e97812d8190428351e5f550a7288829b8924c0fe1deabf06beaadb2a5a9`；空 uploads bucket
  同样得到显式零对象证据；
- 端到端观测耗时 459.499 秒，`technical_pass=true`、`promotion_ready=false`；
- 演练结束后没有 `gda-recovery-*` container、volume 或 bucket，应用 health/ready 仍为 ok。

前三次 fail-closed 运行分别暴露 cluster role 缺失、非空 PostGIS 模板对象冲突和
multipart ETag 不稳定。所有缺陷都被修复为合同和测试，没有通过忽略 restore error、
跳过对象或只比较数量来绕过。

## Consequences

### Positive

- dump 成功第一次被提升为可恢复、可对账的真实证据。
- 恢复失败不接触当前数据库、named volume 或业务 bucket。
- 数据标准、真实 TWM 状态与对象存储内容进入同一恢复证据链。
- 恢复耗时和容量成为可重复观测值，为后续 SLO/RPO/RTO 审批提供基线。

### Negative

- 每次演练需要约 3 GB dump、约 4.6 GB 对象临时介质和多次 I/O，不适合高频执行。
- 逻辑恢复没有证明 WAL/PITR、跨 PostGIS/MinIO 一致快照、异地副本或密钥恢复。
- 开发机单节点结果不能外推为 staging、production、客户环境或云 provider 已验证。

## Verification

- recovery contract、bucket/path 校验、内容 fingerprint、failure redaction、migration
  fingerprint、逻辑/物理身份边界和失败分类定向测试通过。
- 主 Compose 完整 live verifier 通过后执行真实全量备份恢复；所有 source/restored
  identity 和 count 一致。
- Ruff、Python 编译、shell syntax、Compose config 和 `git diff --check` 纳入回归。
- 报告字符串扫描不得包含用户绝对路径、凭据赋值、object key 或真实样本值。

## Revisit Triggers

- 批准 RPO/RTO 后，引入 PostgreSQL WAL/PITR、MinIO versioning/replication 和联合
  consistency marker；
- AR-2 形成 Iceberg catalog、STAC projection 和 DataProductVersion 后，扩展到 snapshot
  pointer、catalog metadata、serving projection 与 rebuild 演练；
- staging/production/customer profile 建立独立备份账号、KMS/secret reference 和异地
  target 后，运行同语义 provider adapter；
- 数据规模或恢复窗口使逻辑 dump/restore 无法达到批准 SLO 时，评估物理备份和增量方案。
