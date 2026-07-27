# ADR-042: Local Ephemeral OTel Metrics Pipeline

**Status**: Accepted

**Date**: 2026-07-27

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-041](adr-041-local-provider-native-metrics-evidence.md)

**Evidence**: [metadata-fabric-otel-metrics-2026-07-27.json](../evidence/metadata-fabric-otel-metrics-2026-07-27.json)

## Context

ADR-041 已证明 OpenMetadata 与 Gravitino 的 provider-native metrics endpoint 在本地真实可读，但它是两个 endpoint 的 point-in-time 探针，尚未证明指标能通过统一 collector 路径被重复抓取。升级/回滚前需要先建立一个可比较的本地 pipeline baseline，同时不能在 backend、retention、TLS、tenant、alert、SLO 和 owner 尚未冻结时引入第二套长期运行的监控平台。

本决策因此只验证短生命周期的本地 OpenTelemetry metrics pipeline。它不部署 Prometheus Server 或 Grafana，不保留时序数据，不创建 Secret、PVC 或 RBAC，也不把本地 NetworkPolicy manifest 写成 enforcement 已验证。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 继续只用 ADR-041 endpoint 探针 | 无新增组件 | 不能验证统一 scrape/export 路径和重复抓取 | 不足以形成 M2c-2 baseline |
| 立即部署 Prometheus、Grafana 和持久存储 | 接近完整监控栈 | backend、retention、tenant、TLS、alert 和 owner 未冻结，会制造未治理的长期平台 | 延后到生产 observability gate |
| 自研 Gravitino exporter | 可完全控制字段 | 新增维护面和语义责任，已有成熟 JSON Exporter 可用 | 拒绝 |
| 临时 OTel Collector + upstream JSON Exporter | 可验证统一 pipeline、两次 scrape 和 cleanup；无持久状态 | 只证明本地短生命周期路径，不证明持续监控 | 采用，限定为 M2c-2 |

## Decision

### 1. 固定短生命周期组件

`config/metadata-fabric-otel-metrics.local.yaml` 和 `k8s/metadata-fabric-otel-metrics/` 固定：

- OpenTelemetry Collector Contrib `0.135.0` ARM64 image digest `sha256:330e0c7e4f4f60dc94f9657e5fb96ce9cfcf333b9aaa41a5c06b4ce4532de92d`；
- Prometheus JSON Exporter `0.7.0` ARM64 image digest `sha256:62370e6e39818966ae1ddfbb69ebf480c697a313cc05ddd76c910b9fbe6934ec`；
- OpenMetadata 由 Prometheus receiver 直接读取 `openmetadata:8586/prometheus`；
- Gravitino Dropwizard JSON 由 JSON Exporter 将五个白名单 gauge 转成 Prometheus，再由同一 receiver 抓取；
- scrape interval 固定为 5 秒，必须取得两次至少跨越一个完整 interval 的有效 observation。

两个 Deployment 均为单副本、ClusterIP-only、无 ServiceAccount token、non-root、只读根文件系统、drop ALL capabilities。资源只允许存在于 `gda-metadata-sandbox`，统一带 `app.kubernetes.io/part-of=gda-metadata-fabric-otel-metrics`，验证前必须不存在，验证后必须全部删除。

### 2. Evidence 投影

Collector 的 Prometheus 输出不进入仓库。每次 observation 只保存：

- metric family/sample/type/label-name 数量和 inventory SHA-256；
- `openmetadata` 与 `gravitino` 的 `up` 和 `scrape_samples_scraped`；
- ADR-041 的四个 OpenMetadata required family 是否存在；
- 五个 `gda_gravitino_*` 白名单值；
- `gda_pipeline=metadata_fabric_local` 与 provider label 是否存在；
- 两次 observation 时间及间隔。

任一 job `up != 1`、sample count 为零、required family 缺失、常量 label 缺失、原始 metrics 被保留或 observation 间隔不足 5 秒，都必须返回 `blocked`。

### 3. Runtime 与 cleanup

`platform_truth.RUNTIME_INVENTORY` 将 `_OtelPortForward` 登记为 `metadata_otel_metrics_pipeline`，production role 固定为 `local_verification_only`。runner 必须：

1. 读取 cluster、namespace 和两个 provider identity，确认没有同标签预存资源；
2. apply 11 个临时资源并等待两个 Deployment rollout；
3. 只通过随机 loopback port-forward 读取 OTel exporter；
4. 完成两次 scrape 后停止 port-forward，删除全部临时资源；
5. 复核 provider identity 未变、临时资源列表为空。

只读 preflight 可对瞬时 Kubernetes API 连接失败执行最多三次有限重试；apply、指标合同失败和 cleanup 失败保持 fail closed。runner 不创建 credential、PVC 或 RBAC，不修改五个 Metadata Fabric foundation workload。

## Verification

2026-07-27 的真实 Docker Desktop Kubernetes 结果：

- 完整 apply、rollout、两次 scrape 和 cleanup 耗时 `17.336` 秒；
- 两次 observation 相隔 `6.033` 秒，均得到 174 个 metric families、440 个 samples；
- OpenMetadata 两次均为 `up=1`、`scrape_samples_scraped=417`；
- Gravitino 两次均为 `up=1`、`scrape_samples_scraped=5`；
- Gravitino datasource active/max=`0/100`、HTTP threads=`8`、JVM heap used/max=`196582232/1610612736`；
- 两个 Deployment、两个 Service 和两个 ConfigMap identity/config digest 与静态合同一致；
- port-forward 已停止，11 个临时资源全部删除，provider identity 保持不变；
- contract fingerprint `4d41f2aae60e6921f0522b9555edbde10d431ac13864c4a7b9ba231cbee07d79`；
- evidence fingerprint `32842b77d23f23b1cb298ec649771c46bc4ce4004ea1efd311f30d5847c7dc82`。

required CI 校验 profile/manifests、digest、禁止资源、JSONPath、scrape/export 配置、allowlist projection、重复 scrape、cleanup、overclaim、敏感字段、runtime primitive 登记，以及 committed evidence 与当前合同指纹绑定。

## Claim Boundary

允许声明：

- `local_otel_metrics_pipeline_verified=true`；
- `local_repeated_scrape_verified=true`；
- scope 仅为 `local_ephemeral_otel_prometheus_export`；
- 固定版本组件在该次本地运行中成功抓取两个 provider，并在结束后完整清理。

仍固定为 `false`：

- 通用 `otel_pipeline_verified` 与 `production_metrics_verified`；
- `persistent_metrics_storage_verified`、`alert_delivery_verified`、`slo_verified`；
- `metrics_tls_verified`、`tenant_isolation_verified`、`oidc_verified`；
- `network_policy_enforcement_verified`、`upgrade_verified`；
- `writes_to_gda_enabled`、`production_ready`。

## Consequences

**Positive**：Metadata Fabric 现在有可重复的统一 metrics pipeline baseline；OpenMetadata 原生 Prometheus 与 Gravitino JSON translation 通过同一 OTel export surface 验证，后续升级前后可以比较 family fingerprint 和 sample baseline。

**Negative**：该 pipeline 每次运行后即删除，没有持久存储、查询、dashboard、TLS、tenant isolation、alert delivery、SLO 或值班闭环。两次本地 scrape 不能代表长期 availability、容量或生产故障行为。

**Next gate**：冻结 production metrics backend、retention、TLS/workload identity、tenant/label policy、dashboard/alert owner、DataSLO 和 runbook，并在受保护环境验证持续采集、存储、查询、告警投递和故障注入；之后才能把通用 OTel/production metrics 声明改为 true。upgrade/rollback、OIDC、NetworkPolicy enforcement、registry provenance 和外部生产 recovery 仍是独立退出门。
