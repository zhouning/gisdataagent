# ADR-028：区分 Staging Candidate 验证与真实环境 Promotion 证据

**Status**: Accepted

**Date**: 2026-07-26

**Decision owners**: Platform Architecture, Data Platform, SRE, Security

**Related decisions**: ADR-018、ADR-019、ADR-027

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

原 `.github/workflows/cd-staging.yml` 名为 staging deployment，实际只在 GitHub Runner 上启动临时 PostgreSQL 并运行测试，没有执行独立 migration authority、构建可部署 revision、部署应用或读取 live cluster 状态，却在成功后输出 `Ready for production deployment`。原 production workflow 同样只打印假设性 canary/rollout 命令，仍会形成成功的 deployment 记录。

这种语义把 CI 集成测试、环境部署和 production promotion 混为一体，违反 AR-0 的平台事实边界。即使测试全部通过，也不能证明 registry digest、真实 staging 配置/身份、运行中 revision、健康状态或 golden slice 终局证据存在。

## Decision

1. `cd-staging.yml` 改为 Staging Candidate Validation。它只验证当前 source revision 在临时 CI 环境中能否形成候选产物，不使用 GitHub `staging` environment，也不声称部署。
2. 临时数据库使用项目 PostGIS/pgvector 镜像。数据库管理员只执行扩展/角色 bootstrap、完整 migration catalog 和测试所需管理操作；独立 `agent_user` 在 migration 前建立，并在 migration 后只读导出 ledger。管理员和应用角色的 schema report 必须一致。
3. candidate evidence 绑定完整 Git SHA、本地不可变 Docker image ID、97 条 migration 的 database fingerprint、严格且脱敏的 staging config fingerprint、runtime inventory fingerprint 和 JUnit 汇总。JUnit 只保留数量，不复制 testcase 名称或输出。
4. `data_agent.staging_candidate_evidence` 对 schema pending/drift、配置非 staging/非 strict、runtime baseline 漂移、测试失败、非法 source revision 或非 sha256 image ID 全部 fail closed。
5. candidate evidence 固定输出 `staging_deployed=false`、`live_cluster_verified=false`、`registry_digest_verified=false` 和 `production_promotion_allowed=false`。`candidate_validated` 只表示临时环境内的候选一致性。
6. production workflow 在 live staging verifier 实现前固定失败，不再构建镜像、打印假部署步骤或记录虚假 deployment。恢复 production promotion 前必须验证 registry digest、live Deployment revision、live schema/config/runtime fingerprint、workload identity、健康状态和 golden-slice verdict 绑定到同一 source revision。
7. GitHub artifact 是非权威 evidence bundle。真实 DeploymentRevision 与受保护环境的 live evidence 才能成为 promotion authority；CI、离线 activation preflight 和人工文本确认都不能单独解锁 production。

## Consequences

正面影响：

- CI 通过不再被误报为 staging 已部署；
- migration authority 与普通应用角色在发布候选阶段即可独立验证；
- candidate artifact 可审计、脱敏，并清楚列出缺失的 live evidence；
- 尚未实现的 production 部署路径显式失败，而不是以成功日志掩盖缺口。

限制：

- 当前 workflow 仍需在 GitHub Runner 上实际运行，才能形成远端 candidate artifact；
- 本地 image ID 不是 registry digest，不能直接成为 Kubernetes DeploymentRevision；
- 本 ADR 不实现真实 staging 部署、DolphinScheduler Worker 激活、live smoke/golden slice 或 production rollout。

## Verification

- 单元测试覆盖有效 candidate、schema/config/runtime/test/image 多类阻断、JUnit 汇总脱敏和 CLI JSON 输出；
- Workflow YAML 合同测试固定 candidate-only job、migration/app-role 双报告、严格平台快照、镜像构建、非 promotion summary，以及 production fail-closed；
- 本地临时 `gis-postgis-pgvector:16-3.4` 数据库完成管理员 97/97 migration，普通 `agent_user` 只读报告与管理员 fingerprint 完全一致；
- 本地真实报告组合生成 `candidate_validated`，同时保持全部 live/promotion 字段为 false，输出未包含临时数据库或配置密码。

## Revisit Triggers

- 已有受保护 staging 集群、registry 和 workload identity，可实现 live evidence collector；
- 可以将 registry digest、Kubernetes revision、schema/config/runtime snapshot 和 golden-slice verdict 绑定为签名 DeploymentRevision；
- production rollout/rollback provider 已选定并能返回机器可验证状态，而不是文本日志。
