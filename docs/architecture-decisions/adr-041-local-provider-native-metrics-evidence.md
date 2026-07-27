# ADR-041: Local Provider-Native Metrics Evidence

**Status**: Accepted

**Date**: 2026-07-27

**Decision owners**: Metadata Platform, SRE, Security, Platform Architecture

**Related decisions**: [ADR-019](adr-019-configuration-and-runtime-truth.md) · [ADR-037](adr-037-local-metadata-fabric-foundation-sandbox.md) · [ADR-040](adr-040-local-cross-cluster-metadata-recovery.md)

**Evidence**: [metadata-fabric-provider-metrics-2026-07-27.json](../evidence/metadata-fabric-provider-metrics-2026-07-27.json)

## Context

ADR-037 已证明固定版本的 OpenMetadata 与 Gravitino 能在本地 Kubernetes 中持续运行，ADR-038 至 ADR-040 又逐步验证了恢复路径。但这些证据只读取 readiness、版本和存储内容，尚未证明所选 provider 版本真实暴露了可用于后续容量基线和故障诊断的指标。

当前没有已批准的 production metrics backend、OTel Collector、TLS identity、告警路由、值班 owner 或 DataSLO。因此本决策只验证 provider-native endpoint 与有界健康指标，不把“能读取 `/metrics`”写成生产可观测性、告警或 SLO 已完成。

## Options Considered

| 方案 | 优点 | 代价/风险 | 结论 |
|---|---|---|---|
| 只保留 readiness/health endpoint | 无新增 runtime | 看不到 JVM、连接池、HTTP 线程和请求指标，不能形成容量基线 | 拒绝作为 metrics evidence |
| 立即部署 Prometheus + OTel Collector | 接近目标形态 | backend、TLS、retention、tenant、告警和 owner 均未冻结，容易制造第二套未治理平台 | 延后到 M2c 后续 gate |
| 通过 `kubectl exec` 读取容器内 endpoint | 不需要端口转发 | 依赖容器 shell/curl，扩大执行面，也不能验证 Service 端口 | 拒绝 |
| 显式 context 的 loopback port-forward + 白名单投影 | 同时验证 Service、endpoint 和真实 payload；不暴露外网端口 | 只是短生命周期本地探针，不是持续 scrape pipeline | 采用，限定为 M2c-1 本地证据 |

## Decision

### 1. 固定 provider metrics 合同

`config/metadata-fabric-provider-metrics.local.yaml` 只允许 `docker-desktop` 的 `gda-metadata-sandbox`：

- OpenMetadata `1.13.1`、`deployment/openmetadata`、ClusterIP Service `openmetadata:8586`，读取 Dropwizard `/metrics` 和 Prometheus `/prometheus`；
- Gravitino `1.3.0`、`statefulset/metadata-gravitino`、ClusterIP Service `metadata-gravitino:8090`，读取 Dropwizard `/metrics`；
- profile 中所有 live、production、OTel、alert、SLO、TLS、OIDC、NetworkPolicy、upgrade、GDA write 和 production-ready 声明默认保持 `false`。

collector 对每次 `kubectl` 调用显式传入 `--context docker-desktop`。两个 Service 只通过随机 loopback 端口短暂访问，不新增 Ingress、NodePort、Service、RBAC 或 Kubernetes Secret 读取。

### 2. Evidence 投影

Dropwizard payload 只保留版本、五类 section 的数量、全部 metric name inventory 的 SHA-256，以及白名单 gauge 的名称和值。OpenMetadata Prometheus payload 只保留 family/sample/type/label-name 数量和 inventory SHA-256；不保存 sample label value、完整 payload 或请求级数据。

最低验证集合为：

- OpenMetadata aggregate health 与 database pool total/max；
- OpenMetadata `auth_attempts`、`db_connections`、`http_server_requests_sec_seconds` 和 `jvm_memory_used_bytes` family；
- Gravitino datasource active/max connections、HTTP total threads 与 JVM heap used/max。

任一 endpoint、content type、provider image、workload UID、Ready replica、required metric、健康约束或指纹缺失都必须返回 `blocked`。

### 3. Runtime 与 cleanup

`platform_truth.RUNTIME_INVENTORY` 将 `_PortForward` 登记为 `metadata_provider_metrics_collector`，production role 固定为 `local_verification_only`。每个 provider 在读取完成或失败后都必须停止 port-forward；evidence 必须同时证明没有修改 provider resource、没有请求 Kubernetes credential-bearing resource。

它不是 scheduler、daemon、Prometheus target、OTel pipeline 或平台 Run 状态权威。唯一持久结果是 committed、敏感字段扫描通过且绑定当前静态合同指纹的 evidence。

## Verification

2026-07-27 的真实本地只读采集结果：

- 采集耗时 `3.772` 秒，两个 loopback port-forward 均已停止；
- OpenMetadata Dropwizard `4.0.0` 返回 111 gauges、10 counters、3 histograms、24 meters、16 timers；aggregate health=`1/0`，database pool total/max=`20/20`；
- OpenMetadata Prometheus 返回 160 metric families、417 samples、4 类 metric type 和 23 个 label names；四个 required family 全部存在；
- Gravitino Dropwizard `4.0.0` 返回 76 gauges、680 meters、152 timers；datasource active/max=`0/100`，HTTP threads=`8`，JVM heap used/max=`126327640/1610612736`；
- collector 未修改 provider resource，也未请求 Kubernetes credential-bearing resource；
- contract fingerprint `55961f899a66fb22934ecda924e4f41e228a562c00314737bdf0f9eee1210b05`；
- evidence fingerprint `ba1ad18deedb4bcc134aa5b413e3e0c03c0b5bf931bae736adc425a8dbceeefc`。

required CI 校验静态 profile、解析投影、负向 overclaim、required metric、敏感字段、cleanup、显式 context、runtime primitive 登记，以及 committed evidence 与当前合同指纹绑定。

## Claim Boundary

允许声明：

- `local_provider_metrics_verified=true`；
- scope 仅为 `local_provider_native_endpoints_via_loopback_port_forward`；
- 指定版本 OpenMetadata/Gravitino 的上述 required metrics 在该次本地观测中存在且满足健康约束。

仍固定为 `false`：

- `production_metrics_verified`、`otel_pipeline_verified`；
- `alert_delivery_verified`、`slo_verified`、`metrics_tls_verified`；
- `oidc_verified`、`network_policy_enforcement_verified`、`upgrade_verified`；
- `writes_to_gda_enabled`、`production_ready`。

## Consequences

**Positive**：Metadata Fabric 第一次拥有真实、可重放、敏感字段受控的 provider metrics baseline；后续 upgrade/rollback 和容量验证可以比较稳定 inventory，而不需要把原始 metrics payload 提交进仓库。

**Negative**：探针是 point-in-time 本地采集，不具备持续 scrape、retention、TLS、tenant isolation、dashboard、告警投递或值班闭环。metric inventory fingerprint 可能随 provider patch 或运行配置改变，升级前必须显式审查差异。

**Next gate**：冻结 production metrics backend、OTel Collector、TLS/workload identity、retention、tenant/label policy、dashboard/alert owner 与 DataSLO；以受保护环境 evidence 验证持续采集、告警投递、故障注入和 upgrade/rollback 前后基线。外部生产 recovery、OIDC、NetworkPolicy enforcement、registry provenance 与 owner/runbook 仍是独立退出门。
