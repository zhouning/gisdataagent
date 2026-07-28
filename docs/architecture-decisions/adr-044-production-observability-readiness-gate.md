# ADR-044: Production Observability Readiness Gate

**Status**: Accepted

**Date**: 2026-07-28

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-041](adr-041-local-provider-native-metrics-evidence.md) · [ADR-042](adr-042-local-ephemeral-otel-metrics-pipeline.md) · [ADR-043](adr-043-local-otel-scrape-failure-recovery.md)

## Context

M2c-1 至 M2c-3 已证明 OpenMetadata/Gravitino 原生指标、本地临时 OTel 双周期抓取和单 job scrape failure/recovery，但没有冻结 production metrics backend、retention、TLS/workload identity、tenant label policy、dashboard/alert/SLO owner、DataSLO 或 runbook，也没有真实 alert delivery attestation。继续直接部署 Prometheus/Grafana 或把本地 `up=0` 解释为生产告警就绪都会越过这些未决输入。

本切片需要把生产观测退出条件从文档清单变成机器可验证的合同，同时允许 checked-in profile 如实表达“合同结构有效，但外部决策尚未完成”。门禁本身不应持有凭据、部署长期组件或单独授权整个 GIS Data Agent 进入生产。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 直接选择并部署 Prometheus/Grafana | 快速得到可见界面 | backend、owner、identity 和 retention 未获批准；会把技术默认值写成生产决策 | 拒绝 |
| 继续只在 roadmap 维护缺口 | 无新增代码 | 无法在 CI 或受保护环境阻止 placeholder、过期证明和生产 overclaim | 拒绝 |
| 单个 YAML 同时保存配置和运行证明 | 文件少 | 静态意图与时效证据混淆，旧证明容易随配置漂移继续生效 | 拒绝 |
| 版本化 profile + 独立、新鲜且绑定 profile 的 attestation | 决策和观测职责清楚；可 fail closed；不要求提前选 backend | 增加 profile/attestation 管理责任 | 采用，限定为 M2c-4 |

## Decision

### 1. Checked-in profile 只声明意图和未决项

`config/metadata-fabric-observability.production.yaml` 固定：

- OpenMetadata `1.13.1` 与 Gravitino `1.3.0` provider baseline；
- backend 类型、持久 write/query HTTPS endpoint、durable storage 和至少 30 天 retention；
- TLS 1.2+、workload identity reference、`gda_tenant_id` isolation 和 required label inventory；
- dashboard、alert、SLO owner，通知渠道引用，三条最小 DataSLO 和版本化 runbook；
- 所有自报 production claim 必须保持 `false`。

`null`、空 SLO inventory 和 `decision_status=pending` 是合法的显式 blockers，因此当前 profile 可以通过 schema/边界检查，但不能进入 protected verification。任何 placeholder、HTTP/loopback/cluster-local endpoint、敏感字段、未知 backend、短于 30 天的 retention、provider version 漂移或自报生产结论都使 profile 无效。

### 2. Readiness 由独立 attestation 派生

`data_agent.metadata_fabric_observability_gate` 将结果分成三层：

1. `profile_valid`：结构、版本和安全边界可信；
2. `ready_for_protected_verification`：backend、identity、owner、SLO 和 runbook 决策齐全；
3. `production_observability_gate_passed`：另有受保护 production 环境 attestation，且 attestation 绑定当前 profile fingerprint。

attestation 必须绑定 source revision、provider versions、backend endpoint/retention 和 runbook version；必须记录持续采集、持久存储、历史查询、TLS、workload identity、tenant isolation、dashboard、告警触发通知、恢复通知、DataSLO 评估和 runbook 响应均为 `passed`。观测时间不得早于验证时刻 24 小时，expiry 必须在未来且最长七天，证据 URI 必须为非本机 HTTPS。配置变更、provider 版本变化、过期或任一检查失败都会关闭门禁。

### 3. 门禁不等于整个平台生产就绪

即使完整 profile 与 attestation 使 `production_observability_gate_passed=true`，报告中的 `production_ready` 仍固定为 `false`。外部生产 recovery、OIDC、NetworkPolicy enforcement、upgrade/rollback、registry provenance、M3 ingestion 和其他 AR-0/AR-1 退出门仍须独立通过。

`validate` 只检查 checked-in profile 是否有效，因此当前 pending profile 在 CI 中返回成功；`evaluate` 必须同时提供 attestation，且仅在观测门禁实际通过时返回成功；`verify` 检查报告 fingerprint、结果一致性和整体生产 overclaim。

## Verification

当前 checked-in profile：

- profile fingerprint：`e3b37626a1732e37570c24fe47f21c8e2084e665fe40143ad488eb2c90ca72fc`；
- `profile_valid=true`，`ready_for_protected_verification=false`；
- 20 个 blockers 精确覆盖 provider environment binding、backend/retention、workload identity、tenant isolation、owner/channel、三条 SLO 和 runbook；
- `production_observability_gate_passed=false`，`production_ready=false`。

定向测试覆盖 pending profile、完整 profile/缺 attestation、完整且新鲜的绑定 attestation、placeholder、HTTP/loopback endpoint、缺 owner/SLO/runbook、敏感字段、self-asserted claim、过期证明、profile/provider/backend/runbook 漂移、恢复通知失败、报告篡改和 malformed YAML。

## Claim Boundary

允许声明：

- M2c-4 production observability readiness contract 已建立；
- 当前 checked-in profile 合同有效，并能机器可读地列出 blockers；
- 合成完整 profile/attestation 能验证门禁逻辑。

当前不得声明：

- 已选择或部署生产 metrics backend；
- 已验证持久 metrics storage、TLS/workload identity 或 tenant isolation；
- 已建立生产 dashboard、真实 alert delivery、DataSLO 或 runbook 响应；
- `production_observability_gate_passed=true` 或 `production_ready=true`。

## Consequences

**Positive**：未冻结的生产选择不再隐含在代码或 roadmap 文本里；受保护环境能使用同一 fail-closed gate 检查配置与新鲜证据，配置漂移会使旧 attestation 失效。

**Negative**：M2c-4 本身不会增加持续采集、历史查询或告警能力；在 backend、identity 和运营 owner 获批前，门禁将持续保持 blocked。

**Next gate**：由 SRE、Security 和 Metadata Platform 批准 production profile，在受保护环境部署选定 backend，生成绑定当前 source/profile 的真实 attestation，并验证 firing/recovery notification 与 runbook 响应。随后仍需分别完成外部生产 recovery、OIDC、NetworkPolicy enforcement、upgrade/rollback、registry provenance 和 M3 conformance。
