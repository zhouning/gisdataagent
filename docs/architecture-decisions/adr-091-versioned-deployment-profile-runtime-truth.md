# ADR-091：用版本化 DeploymentProfile 冻结配置与运行时真值

**Status**: Accepted

**Date**: 2026-07-31

**Decision owners**: Data Platform, Platform Architecture, SRE

**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-0

## Context

同名 Compose service 并不能证明容器来自同一部署画像。主 Compose 与 Gemma4 demo
拥有不同的 Compose 文件、network 和 logical volume，但 Docker 中的容器名和服务名
仍可能被后一次启动覆盖。此前开发环境的 Redis 就实际继承自 Gemma4 profile；只看
`docker compose ps` 的 running/healthy 状态无法发现这种污染。

单一层面的健康证据同样不足：声明的 Compose 配置可能与现有容器不同；容器健康可能
掩盖应用到依赖的连接失败；HTTP 200 可能实际返回前端 fallback HTML；代码中的迁移和
标准版本也可能与容器镜像、数据库事实分叉。另一方面，直接保存完整 Compose config、
环境变量、host bind path 或数据样本会把凭据和本地信息写入验收证据。

AR-0 因此需要一个可版本化、可机器验证且不含 secret 的 DeploymentProfile，区分
“配置存在”“运行时可达”“技术验收通过”和“允许晋级”。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 继续依赖 Compose YAML 和人工检查 | 无新增合同 | 无法证明现有容器来源、volume identity 和应用内事实 | 拒绝 |
| 保存完整 `docker compose config` 和 `docker inspect` | 事实丰富 | 容易泄漏 secret、host path，报告噪声大且不稳定 | 拒绝 |
| 只检查 `/health` 和 `/ready` | 实现简单 | 无法发现 profile 污染、迁移/标准漂移和伪 HTTP 200 | 拒绝 |
| 严格非敏感画像 + 多层只读 verifier | 身份明确、可复现、fail closed | 每个环境需维护并批准独立基线 | **选择** |

## Decision

1. 每个部署环境使用仓库内版本化 JSON `DeploymentProfile`。v1 首先覆盖 Compose，
   schema 使用严格 Pydantic model，未知字段、非法引用、重复 service/volume、绝对
   host path 和带凭据的 URL 均被拒绝。
2. 画像声明 environment、`llm_mode`、Compose project/files/profiles/network、service
   来源和运行模式、logical volume、迁移 fingerprint、released standard、capability、
   HTTP probe 和治理状态。`required`、`one_shot`、`optional` 与
   `optional_not_enabled` 必须显式区分。
3. Compose fingerprint 基于规范化模型生成；敏感环境变量值和 host bind source 在
   hash 前被移除。fingerprint 用于比较配置身份，不能反向替代 secret manager、
   credential rotation 或数据证据。
4. verifier 只读验证五层事实：
   - 声明配置：Compose config、project、service、network、volume 和规范化 fingerprint；
   - 容器事实：service 状态、health、Compose source label、实际 network 和 named volume；
   - 应用内事实：容器所见 migration catalog/database fingerprint、released standard
     identity 和应用到 Redis 的连接；
   - HTTP 行为：路由存在、状态码、content type 和约定 JSON status；
   - 治理放行：platform owner、治理状态和 promotion blockers。
5. 任一技术检查失败都使 `technical_pass=false`。source file、network 或 volume 不一致
   另外标记 `profile_contamination=true`。这些失败不自动重建容器、不迁移数据，也不
   修改 volume。
6. `promotion_ready` 只有在技术检查全部通过、治理状态为 `verified` 且 blockers 为空时
   才为 true。开发环境技术通过不能覆盖 business steward、license、SLO、备份恢复或
   staging/production/customer 环境证据；`--static-only` 报告必须追加
   `runtime_verification` blocker，永远不能授权晋级。
7. verifier 报告只输出 check ID、期望值、非敏感实际值、capability 状态和治理门槛；
   禁止输出 Compose environment value、secret、原始样本或绝对路径。
8. `/health` 和 `/ready` 必须在 Chainlit frontend fallback 之前注册并返回 JSON；容器
   HEALTHCHECK 探测 `/health`。运行镜像必须包含 DeploymentProfile，并安装应用实际使用
   的 Redis client，使容器内 probe 与本地合同一致。

## Development Runtime Result

2026-07-31 对主 Compose 开发环境执行完整只读验证：

- Compose config fingerprint 为
  `76dffa0747271f4ae587faf5c851922d5044305b964bc269742182c3a67546ec`；
- db、app、MinIO 和 Redis 均来自主 Compose 文件、主 network 和预期 named volume，
  required service 全部 healthy，one-shot migration 与 bucket init 均 exited 0；
- migration catalog/database 均为 93 条，fingerprint 为
  `53ddf178936f4b6ce909bf553e66f33270d9cf815a87458e60de332f69af9ee4`；
- released standard 为 `NR_ONE_MAP_TWM_CORE_2026@2026-06-16-draft`，174 个数据元，
  fingerprint 为
  `a9b58ea766e1f7fd0f203b07bb23e3848e1db7dad560ebf04843b83a5b713630`；
- PostGIS、object storage、Redis、GDA MVT、liveness 和 readiness 均达到 runtime，
  Martin 明确为 `optional_not_enabled`；MVT 未认证探测按合同返回 JSON 401；
- 最终 `technical_pass=true`、`profile_contamination=false`、
  `promotion_ready=false`。promotion blockers 为 `business_steward`、
  `license_status`、`slo` 和 `backup_restore`。

首次验证发现 Redis 来自 Gemma4 Compose 文件、network 和 volume。修复只按主 Compose
重建 Redis container，没有删除、合并或复制任何 volume。验证还暴露并修复了 health
route 被 frontend fallback 截获、Docker HEALTHCHECK 探测错误入口、镜像缺少画像文件和
Redis 运行依赖等真实缺陷。

Gemma4 demo 画像已版本化并通过严格 schema、fingerprint 和脱敏合同测试；本 ADR 不把
当前主 Compose 的运行证据外推为 Gemma4、staging、production 或客户环境已验证。

## Consequences

### Positive

- service running 不再等同于 profile 正确，跨 Compose 污染成为机器可读失败。
- schema、标准、依赖连接、HTTP 行为和部署身份可以在同一报告中对账。
- 技术健康与业务放行明确分离，缺 owner、license、SLO 或恢复证据时自动拒绝晋级。
- 报告可进入 CI/验收产物而不携带运行凭据、本地路径或业务样本。

### Negative

- Compose config 或预期 service/volume 变化必须评审并更新 fingerprint，存在维护成本。
- 当前 v1 只实现 Compose；Kubernetes、云托管和客户环境需要同一语义的 provider-specific
  collector，不能伪装成已支持。
- verifier 证明观察时刻的运行事实，不替代持续监控、容量测试、备份恢复或安全评审。

## Verification

- DeploymentProfile、fingerprint、运行时污染、内部 probe 和报告脱敏定向测试与标准
  映射验收：37 passed。
- Ruff 定向检查、Python 编译检查和 `git diff --check` 通过。
- 主 Compose 完整 live verifier 无 failed check，并生成
  `gis-data-agent.deployment-profile-verification.v1` 报告。
- 报告和两个版本化画像的字符串值扫描未发现用户绝对路径、凭据赋值或真实数据样本名。

## Revisit Triggers

- Kubernetes、云托管或客户环境进入可运行验收，需要扩展 deployment type 与 collector；
- capability 迁移到统一 metadata fabric 后，需要以稳定 ResourceURN 引用 provider binding；
- secret/reference、SLO、backup/restore 或签名证据进入正式 release bundle；
- 多节点、滚动发布或动态 volume placement 使单一 Compose project 语义不再充分。
