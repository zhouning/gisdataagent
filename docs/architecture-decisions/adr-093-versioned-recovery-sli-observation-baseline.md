# ADR-093：用版本化单次观测冻结恢复 SLI 基线，不自动产生 SLO

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Platform Architecture, SRE

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## Context

ADR-092 已证明主 Compose 开发环境的 PostGIS 和 MinIO 可以在隔离目标中完成逻辑恢复，
并给出容量、阶段耗时和端到端耗时。但单个 `/tmp` 报告会随开发机清理而丢失，仅把
459.499 秒写进文档也无法证明这个数字来自哪一个 DeploymentProfile、哪一份数据身份和
哪次恢复证据。

另一方面，直接把一次开发机观测写成 RTO，或者按该耗时自动推导 SLO/RPO，会把技术事实
错误升级成业务承诺。RTO 还需要替代实例准备、切流、依赖恢复和业务验收；RPO 需要备份
频率、WAL/PITR、对象版本和跨系统一致性证据，不能从 restore duration 推导。

AR-0 需要的是可重复校验的 SLI 起点，以及对“观测值”和“目标值”的机器可读隔离。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 只在 ADR 中记录耗时 | 简单 | 无法绑定 profile、数据身份或源报告，易形成陈旧数字 | 拒绝 |
| 用单次耗时自动设置 RTO/SLO | 快速得到目标 | 没有业务审批，混淆恢复阶段和完整服务恢复 | 拒绝 |
| 原样提交全部命令输出和对象清单 | 信息最多 | 可能泄漏路径、凭据、对象 key 和样本 | 拒绝 |
| 严格观测合同 + 脱敏证据 + 重建校验 | 可审计、可重复，保持治理边界 | 每个 profile 和样本需独立维护 | **选择** |

## Decision

1. 新增 `gis-data-agent.recovery-sli-baseline.v1` 严格合同。每个 baseline 绑定
   `profile_id`、environment、Compose config SHA-256、恢复报告 schema、观测时间和报告
   规范化 JSON SHA-256；未知字段和非有限数值 fail closed。
2. v1 只接受 `sample_count=1` 和
   `interpretation=single_observation_not_objective`。schema 不定义 SLO、RPO 或 RTO 数值
   字段，新增 `rto_seconds` 等目标字段会被拒绝。
3. 数据库基线保存源库容量、dump 容量和逻辑身份 SHA-256。逻辑身份包含 migration、
   released standard、扩展、geometry column 和代表表计数，但排除恢复目标的物理存储
   layout bytes。
4. 对象存储基线保存 bucket 数、对象总数、总字节和逻辑身份 SHA-256。身份 hash 绑定逻辑
   bucket 与逐内容 inventory fingerprint；基线不保存对象 key、本地路径或原始样本。
5. 阶段 SLI 分别记录数据库 backup、database restore、object rehearsal 和 end-to-end
   duration。end-to-end 必须不短于已观测阶段之和，避免不可能的时间报告。
6. 脱敏 `gis-data-agent.recovery-rehearsal.v1` 源报告与基线一起版本化。校验器必须从源报告
   重新构建完整 baseline 并逐字段相等；只校验 profile 或只比较 source/restored 内部一致
   都不能通过。
7. 治理状态固定为 `sli_status=observed_not_approved`、`slo_status=not_approved`、
   `rpo_status=not_defined`、`rto_status=not_approved` 和 `promotion_ready=false`。profile
   blocker 与恢复 limitation 必须完整保留。
8. 不新增 SLI registry、scheduler、数据库表或长期服务。版本化 JSON、既有
   DeploymentProfile、恢复报告和只读 CLI 足以完成 AR-0 当前证据冻结。

## Development Baseline Result

`main-compose-dev-20260731` 已绑定主 Compose 开发画像和 2026-07-31 完整恢复报告：

- 源 PostgreSQL 为 6,655,269,911 bytes，dump 为 3,028,622,216 bytes；
- database backup 258.598 秒，database restore 187.532 秒；
- MinIO 两个逻辑 bucket 共 213 个对象、2,288,430,300 bytes，object rehearsal 7.364 秒；
- end-to-end 为 459.499 秒；
- 数据库逻辑身份、对象存储逻辑身份和报告证据分别使用独立 SHA-256 绑定；
- verifier 的 profile、Compose config、治理、报告证据和观测重建五项检查全部通过；
- 最终 `technical_pass=true`、`promotion_ready=false`。

完整 live 演练后，恢复实现只增加了冗余的 host-side MinIO cleanup `finally`；定向测试已
重跑，但未为这项 cleanup-only 变化再次执行 7.6 分钟全量演练。因此该 baseline 只陈述
其观测时间点的事实，不声明当前代码或其他机器将重复相同耗时。

## Consequences

### Positive

- 恢复容量和耗时从文档数字升级为可机器重建的版本化证据。
- 单次观测无法在 schema 内伪装成已批准 RTO/SLO。
- 报告格式化或 key 顺序变化不影响规范化证据身份，语义内容漂移一定失败。
- 不暴露对象 key、host path、credential 或数据样本。

### Negative

- 单个样本不能估计方差、p95/p99、容量曲线或并发影响。
- 开发机 Compose 结果不能外推到 Gemma4、staging、production、customer 或云 provider。
- 当前报告没有 WAL/PITR、跨系统 consistency marker、offsite/encryption 或完整切流阶段。

## Verification

- 严格 schema、目标字段拒绝、profile 绑定、报告内容漂移和无报告 fail-closed 测试通过。
- 版本化 baseline 从版本化源报告重建后五项 check 全部为 true。
- baseline 和 evidence 字符串扫描未发现用户绝对路径、临时路径、credential、对象 key 或
  样本值。
- 定向 pytest、Ruff、Python compile 和 `git diff --check` 纳入回归。

## Revisit Triggers

- 同一 profile 获得多次、受控硬件和负载下的样本后，引入分布统计，但仍与目标审批分离；
- 业务 owner 和 SRE 明确服务等级后，用独立版本化 approval 合同记录 SLO/RPO/RTO；
- WAL/PITR、MinIO versioning/replication、加密、异地和联合一致性通过后，扩展恢复阶段；
- AR-2 建立 DataProductVersion、Iceberg catalog 和 STAC projection 后，纳入 rebuild SLI。
