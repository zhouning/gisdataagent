# ADR-043: Local OTel Scrape Failure Detection and Recovery

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-041](adr-041-local-provider-native-metrics-evidence.md) · [ADR-042](adr-042-local-ephemeral-otel-metrics-pipeline.md)

**Evidence**: [metadata-fabric-otel-failure-rehearsal-2026-07-28.json](../evidence/metadata-fabric-otel-failure-rehearsal-2026-07-28.json)

## Context

ADR-042 已建立 OpenMetadata 与 Gravitino 经同一临时 OTel export surface 重复抓取的本地 baseline，但只覆盖两个 job 都健康的路径。下一步需要证明统一 pipeline 能区分单一 provider scrape 故障、不会把另一个 provider 一并判为失败，并能在恢复配置后重新取得完整指标。

production metrics backend、retention、TLS/workload identity、tenant label policy、alert/SLO owner 和 runbook 仍未冻结。本决策因此不引入 Prometheus Server、Grafana、PVC、Secret 或 RBAC，也不把本地 `up` 检测写成告警已投递或 SLO 已验证。故障注入只作用于每次演练后即删除的 Collector 配置，不修改 OpenMetadata、Gravitino 或任何业务数据。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 等待完整生产 observability stack 后再验证 | 一次覆盖长期存储、查询和告警 | backend/owner 等关键输入未冻结，当前无法形成可审计结论 | 不阻塞最小本地故障基线 |
| 停止或重启 Gravitino | 故障接近 provider unavailable | 会影响共享 foundation workload，扩大演练范围 | 拒绝 |
| 删除 JSON Exporter Service 或 Deployment | 能让 Gravitino translation 失败 | 改变临时资源 inventory，难以证明只变更一个 scrape endpoint | 拒绝 |
| 只替换临时 Collector 的 Gravitino scrape address | 不影响 provider；OpenMetadata job 可作为隔离对照；可精确恢复 | 只证明本地 scrape failure/recovery，不证明 alert delivery | 采用，限定为 M2c-3 |

## Decision

### 1. 结构化、单点故障注入

`config/metadata-fabric-otel-failure-rehearsal.local.yaml` 固定：

- base contract 为 ADR-042 的 `gda.metadata_fabric_otel_metrics_contract.v1`；
- 仅允许修改 `metadata-otel-collector-config` 中 `job_name=gravitino` 的 `__address__` relabel；
- 原地址必须为 `metadata-json-exporter:7979`，故障地址固定为 `metadata-json-exporter:1`；
- 变换必须结构化解析内嵌 YAML，并证明除该 replacement 外的 Collector 配置完全一致；
- 故障 ConfigMap 必须保留 namespace 和临时资源标签，ConfigMap UID 必须跨 baseline/fault/recovery 保持不变。

端口 1 不在现有 Collector egress policy 允许范围内，也没有对应 Service port。该变换只阻断临时 Collector 到 Gravitino translation endpoint 的抓取，不停止 JSON Exporter，不修改或重启两个 metadata provider。

### 2. 三阶段验收

runner 必须使用三个彼此独立的短生命周期 loopback port-forward，依次形成：

1. **baseline**：OpenMetadata 和 Gravitino 都为 `up=1`，required family 与 samples 全部存在；
2. **fault**：OpenMetadata 继续 `up=1` 且 samples 大于零；Gravitino 必须为 `up=0`、`scrape_samples_scraped=0`，五个 `gda_gravitino_*` family 不得残留；
3. **recovery**：重新 apply ADR-042 的 checked-in Kustomize 配置并重启临时 Collector，两个 job 恢复 `up=1`，五个 Gravitino family 全部恢复。

每个阶段只保存 allowlisted `up`/sample 值、family/type/label inventory fingerprint、缺失 family 清单和配置 SHA-256，不保留原始 metrics payload。

### 3. Fail-closed cleanup 和运行时边界

`platform_truth.RUNTIME_INVENTORY` 将 runner 登记为 `metadata_otel_failure_rehearsal`，production role 固定为 `local_verification_only`。runner 必须：

- 在 apply 前确认 11 个 ADR-042 临时资源均不存在，并记录 provider identity；
- 等待初始、故障和恢复 Collector rollout 完成；
- 无论阶段成功或失败都停止已启动的 port-forward；
- 如果故障已注入但正常恢复流程未完成，先 best-effort 恢复 checked-in 配置，再删除全部临时资源；
- 删除后确认剩余资源为空，并确认 OpenMetadata/Gravitino identity 未改变。

任何 stage、配置哈希、ConfigMap UID、port-forward stop、cleanup 或 provider identity 检查失败，evidence 都必须为 `blocked`。observation 中的 contract fingerprint 必须等于当前代码生成的静态合同，防止旧证据在合同漂移后继续生效。

## Verification

2026-07-28 的真实 Docker Desktop Kubernetes 结果：

- 完整 apply、baseline、故障注入、恢复和 cleanup 耗时 `33.766` 秒；
- baseline：OpenMetadata/Gravitino 均 `up=1`，分别抓到 `417/5` 个 samples；
- fault：OpenMetadata 维持 `up=1`、417 samples，Gravitino 为 `up=0`、0 samples，五个 allowlisted Gravitino family 全部缺失；
- recovery：OpenMetadata/Gravitino 重新为 `up=1`，分别抓到 `417/5` 个 samples，五个 Gravitino family 全部恢复；
- baseline/fault/recovery Collector config SHA-256 分别为 `c600738d523b052e849d820f2ac616f9c34285b82094058f6ab2e98345d9ed63`、`6e9196902febd5c35f4bfa47c5687e139f21deeaff58fe29a5988eace42f79d3`、`c600738d523b052e849d820f2ac616f9c34285b82094058f6ab2e98345d9ed63`，ConfigMap UID 未变；
- 三个 port-forward 全部停止，11 个临时资源全部删除，provider identity 保持不变；
- contract fingerprint `917af171390e32d731a5b6b95843a2fbbb28c1c99223ed490f773416a2096aac`；
- evidence fingerprint `c70211268b62ba2e4b78c2e6d356878d875216a4f5dd7a6b4894bbdff6460a8c`。

required CI 校验 profile、结构化 endpoint 变换、claim boundary、三阶段摘要、故障未出现、恢复失败、cleanup 失败、敏感字段、evidence 篡改、current-contract 绑定、runtime inventory 登记和 committed evidence 完整性。

## Claim Boundary

允许声明：

- `local_otel_scrape_failure_recovery_verified=true`；
- scope 仅为 `local_ephemeral_otel_scrape_failure_recovery`；
- 固定版本临时 Collector 在该次本地运行中检测到隔离的 Gravitino scrape failure，并在恢复 checked-in 配置后重新抓取成功。

仍固定为 `false`：

- 通用 `otel_pipeline_verified` 与 `production_metrics_verified`；
- `persistent_metrics_storage_verified`、`alert_delivery_verified`、`slo_verified`；
- `metrics_tls_verified`、`tenant_isolation_verified`、`oidc_verified`；
- `network_policy_enforcement_verified`、`upgrade_verified`；
- `writes_to_gda_enabled`、`production_ready`。

## Consequences

**Positive**：Metadata Fabric 现在有可重复的本地 failure/recovery baseline，能证明一个 scrape job 失败时另一个 job 仍可被观测，并能验证 checked-in 配置恢复后指标 family 和 sample baseline 回归。

**Negative**：该演练没有持续 backend、历史查询、dashboard、告警规则、通知渠道、DataSLO、值班 owner 或受保护环境运行。观察到 `up=0` 不等于告警已创建、投递或由 owner 响应。

**Next gate**：冻结 production metrics backend、retention、TLS/workload identity、tenant/label policy、dashboard/alert owner、DataSLO 和 runbook，在受保护环境验证持续采集、存储、查询、真实告警投递、静默/恢复通知和 runbook 响应；之后才能把通用 OTel/production metrics、alert 或 SLO 声明改为 true。upgrade/rollback、OIDC、NetworkPolicy enforcement、registry provenance 和外部生产 recovery 仍是独立退出门。
