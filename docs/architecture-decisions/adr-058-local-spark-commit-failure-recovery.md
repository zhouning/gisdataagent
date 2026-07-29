# ADR-058: Local Spark Commit-Failure Recovery

- Status: Accepted
- Date: 2026-07-30
- Owners: Metadata Platform / Data Engineering / SRE / Security
- Scope: AR-1 Metadata Fabric M3-12

## Context

[ADR-006](adr-006-openmetadata-governance-and-active-metadata-platform.md) 要求 Spark/Sedona 与 Flink 的 conformance 覆盖 create、read、write、schema evolution、snapshot、time travel、cancel、reconcile 和 lineage。[ADR-056](adr-056-local-spark-object-store-interoperability.md) 已在 Docker Desktop 两节点 Kubernetes 中证明 Spark `3.5.0`、Iceberg `1.6.1`、Gravitino `1.3.0` 与跨节点 MinIO S3 API 的前五项互操作，但没有注入 catalog commit failure。[ADR-057](adr-057-production-object-store-readiness-gate.md) 只建立生产对象存储的 provider-neutral readiness contract；provider、账户、identity、KMS 和受保护环境仍由 owner 决策，因此不能把生产对象存储 attestation 作为本切片前提。

下一项独立且可执行的风险是 Iceberg REST table commit 在到达 catalog 前失败：平台必须证明失败尝试不会产生可见 snapshot、row 或 referenced data file，调用方随后对同一逻辑写入做一次显式重试时只产生一个新的可见效果。

## Options

| 方案 | 优点 | 风险 | 决定 |
|---|---|---|---|
| 只依赖既有成功路径 | 无新增运行成本 | 不证明失败原子性与重试恢复 | 拒绝 |
| 在 provider commit 返回后丢弃响应 | 可演练 uncertain outcome | 需要先定义 reconcile/idempotency key，范围扩大到未知提交结果 | 后续切片 |
| 在 Spark driver 内以 loopback proxy 于转发前返回 HTTP 503 | 故障边界确定；可证明 provider 未收到失败提交 | 只覆盖单 driver、本地 REST 路径 | 采用，限定为 M3-12 |
| 直接在生产对象存储和受保护 catalog 注入故障 | 最接近生产 | provider/identity/环境尚未批准 | 阻塞，不在本切片 |

## Decision

1. 复用 M3-10 的 Gravitino PostgreSQL JDBC catalog、MinIO S3 warehouse、bounded Basic role 和两节点 placement，但使用独立 namespace `gda-metadata-spark-commit-failure`。MinIO 固定在 `desktop-control-plane`，PostgreSQL、Gravitino 和 Spark 固定在 `desktop-worker`；Spark 与 Gravitino 不挂载 warehouse PVC。
2. Spark driver 启动只监听 `127.0.0.1:19001` 的 `ThreadingHTTPServer`，catalog URI 指向该 loopback proxy。代理只把包含 Iceberg `requirements` 与 `updates` 的 table commit 识别为提交请求。
3. 首次 baseline append 正常转发。失败模式只在第二个逻辑 append 前开启，并在转发前返回 HTTP 503；REST client 最多重试一次，因此 evidence 必须精确记录两个 failed commit requests，且两者都不得到达 Gravitino。失败写调用返回后立即关闭故障模式。
4. 失败前后必须保持同一个 snapshot、两行和一个 referenced Parquet。随后对同一 `spark-recovery` 行执行一次显式 append，最终必须是父子相连的两个 append snapshots、三行和两个 referenced Parquet。
5. 除 Spark metadata tables 外，还必须直接读取 MinIO object inventory。最终对象必须精确为 2 个 Parquet、3 个 Iceberg metadata JSON 和 4 个 Avro manifest，共 9 个；分类清单必须覆盖全部对象，禁止失败写留下孤儿 data file。
6. Job 必须 `suspend: true`、`backoffLimit: 0`、禁用 ServiceAccount token automount、无 warehouse PVC、受限 security context。运行时 Secret 只由 runner 临时生成，不进入 profile、manifest、日志或 evidence。
7. namespace、两块临时 PV 和两个 loopback port-forward 必须全部清理后，`local_spark_commit_failure_recovery_verified` 才可为 `true`。

## Checked Evidence

- Contract fingerprint: `6d8944ab80246dc65891aa81118cb8b73f7ecad699be9a2af5e62d8260c41002`
- Evidence fingerprint: `39571cdac1e4043bcfc2d03a73b2b12ff925210daf8ae36bc640b8cb14d89401`
- Dependency evidence fingerprint: `05844457efb378581fb7fc2e7ed3c706819b2d8fa5a52b2f82577051d38c2cd1`
- Failure boundary: `iceberg_rest_table_commit / pre_forward_http_503`
- Proxy requests: 2 failed commit requests, 2 forwarded successful commit requests
- Visible state: baseline `1 snapshot / 2 rows / 1 data file`; failed attempt unchanged; retry `2 snapshots / 3 rows / 2 data files`
- Direct object inventory: `2 data + 3 metadata + 4 manifest = 9 objects`
- Cleanup: namespace absent, both PVs absent, all port-forwards stopped

## Boundaries

`local_failed_commit_atomicity_verified=true` 表示失败提交没有改变可见 Iceberg table state；它不是分布式事务或网络 exactly-once。`local_exactly_once_visible_effect_verified=true` 只表示测试调用方在已知 pre-forward 失败后，对同一逻辑行执行一次显式重试，最终只出现一行和一个新 snapshot。

本 evidence 不覆盖 provider 已提交但响应丢失的 uncertain outcome，不覆盖 cancel、reconcile、lineage、Flink、Spark/Sedona 空间语义、生产对象存储、独立 failure domain、protected workload identity、OIDC、TLS、KMS、tenant isolation 或生产 ingestion。因此 `spark_cancel_verified`、`spark_reconcile_verified`、`spark_lineage_verified`、`spark_conformance_verified`、`flink_conformance_verified`、`production_object_store_verified` 和 `production_ready` 均保持 `false`。

## Consequences

**Positive**：M3-10 的成功路径现在补上一个可重复、机器校验的 pre-forward commit failure 原子性和确定性重试证据；失败写产生的对象泄漏也由直接 S3 inventory fail closed。

**Negative**：M3-12 仍不能回答“provider 可能已提交但客户端不知道”的 reconcile 问题，也不把本地 MinIO 提升为生产对象存储。下一项 engine reliability slice 应定义 uncertain commit outcome 的 operation identity、状态查询和 reconcile 合同，或继续补齐 cancel/lineage/Flink conformance；生产 provider attestation 仍由 M3-11 blockers 驱动。
