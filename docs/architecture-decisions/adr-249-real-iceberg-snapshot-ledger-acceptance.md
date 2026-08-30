# ADR-249：真实 Iceberg snapshot 到架构账本的联合验收

## 状态

Accepted（disposable Spark/Flink/Iceberg + MinIO + PostgreSQL ledger；2026-08-23）

## 背景

ADR-248 先固定了 Iceberg/Gravitino table payload 的观察合同，但当时只有契约级 fixture，
还没有真实 Iceberg snapshot 进入 `ArchitectureProviderObservation`。这使得 schema/location
候选虽可计算，仍缺少真实 metadata/data object 和控制账本之间的证据链。

## 决策

新增 `scripts/certify_iceberg_architecture_observation.py`，复用现有冻结的 Spark/Flink Iceberg
runtime、Iceberg JDBC catalog 和对象存储边界：

1. 在 disposable MinIO 的隔离 prefix 中用 Spark 创建真实 Iceberg format v2 表；
2. 启动真实 Flink 1.19 作业，读取 Spark baseline，增加 `flink_commit_tag` 列并追加一行；
3. 再由 Spark 读取最终 snapshot，验证 schema evolution、内容精确匹配、snapshot parent chain、
   append 数量和 baseline snapshot time-travel；
4. 从两次 Spark 观察返回的真实 schema、row content fingerprint、snapshot ID 和有界 parent chain
   组装受限 table contract，通过 `data_agent.iceberg_architecture_harvester` 生成两条
   observation/candidate；
5. 用独立 disposable PostgreSQL 应用控制账本迁移，通过 `PlatformGateway` 写入 observation、
   schema、contract、physical location 和 binding；
6. 验证 `unbound -> in_sync`、后续 schema/location drift、同 observation 幂等、append-only、
   强制 RLS 和跨租户拒绝；
7. provider、catalog、ledger、bucket、Flink、临时网络和工作目录全部清理。

该脚本故意没有把 JDBC catalog 叫作 Gravitino REST catalog。它证明的是真实 Spark/Flink/Iceberg
provider 到 GDA ledger 的合同；Gravitino REST table read、snapshot recovery、跨 catalog 互操作和
生产运行能力仍需后续独立验收。

## 验证

报告：`.tmp/iceberg-architecture/acceptance-report.json`

- schema：`gda.iceberg_architecture.acceptance.v1`
- status：`passed`
- Spark baseline snapshot：`3379225455652360291`；Flink append/schema-evolution child snapshot：
  `3726182389816928569`
- harvester 已校验并报告有界 snapshot lineage：baseline 为 root append，evolved observation 为
  `3379225455652360291 -> 3726182389816928569`，child parent 必须指向已出现的前序 snapshot
- Flink 作业结果：baseline 3 行，最终 4 行，追加 1 行；Spark verify 的
  `final_content_exact`、`flink_append_visible_to_spark`、`flink_schema_evolution_visible`、
  `snapshot_parent_chain_exact`、baseline time-travel 和两次 append 均为 `true`
- canonical `report_sha256`：`b53ef5d3fdab781ea99b5701879c84167dcb57654365d8f6999f604cebfdd1a8`
- 文件 SHA-256：`693409258b97ab1545850b67f23f69c31b17964aa2dab286aa25e19dc1d5af59`
- provider：`gisdataagent/mmfe-spark-runtime:local` + Spark Iceberg 1.6.1、Flink Iceberg 1.7.2、
  `org.apache.iceberg.jdbc.JdbcCatalog` 和固定 MinIO 镜像
- ledger：`unbound`、`in_sync`、后续 `schema_and_location_drift`、幂等 replay、append-only 两条
  present observation、RLS enabled/forced、跨租户拒绝
- 清理：bucket、MinIO container/volume/network、Flink container、catalog container、control
  PostgreSQL container、work directory 全部不存在

## 未覆盖范围

本证据仍未覆盖 Gravitino REST catalog interoperability、snapshot checkpoint/recovery、生产 HA、
backup/restore、PITR、RPO/RTO、跨区域复制、双租户恢复、自动 successor release、生产 identity 和
多表/多并行度 conformance。不得把本 acceptance 等同于 Iceberg production foundation 完成。
