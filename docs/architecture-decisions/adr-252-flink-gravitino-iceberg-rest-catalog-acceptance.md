# ADR-252：Flink 通过 Gravitino Iceberg REST catalog 数据面验收

## 状态

Accepted（bounded disposable Flink + Gravitino REST + Spark reread；2026-08-23）

## 背景

ADR-251 已证明 Spark 可以通过 Gravitino Iceberg REST catalog 创建表、演进 schema、追加
数据并把 bounded REST metadata 投影到 GDA architecture ledger，但 Flink 仍只在 JDBC
catalog 路径上有同一类证据。没有 Flink REST 证据，默认湖仓的 batch/stream 计算引擎仍没有
共同的 catalog 数据面合同。

## 决策

扩展 `scripts/certify_gravitino_iceberg_rest_flink.py`，在同一个 disposable MinIO、JDBC
catalog backend 和 Gravitino REST 服务中完成受控跨引擎闭环：

1. Spark 注册本地 catalog alias `rest`，Flink 注册本地 alias `lakehouse`；两者都使用
   Gravitino `RESTCatalog`、`http://gravitino:9001/iceberg` 和 `default_catalog`，表的
   namespace/object 坐标保持相同。
2. Spark prepare、Flink append、Spark verify 共用同一个真实重庆 OSM `interop-plan`，避免
   两个引擎各自生成 fixture。Spark 创建 format-v2 baseline；Flink 读取 baseline，增加
   `flink_commit_tag` 并追加一行；Spark 通过 REST alias 回读最终数据和 baseline
   time-travel。
3. Flink job 只接受 `lakehouse.gda_rest_[0-9a-f]{10}.chongqing_osm_roads` 这一受控表名，
   REST catalog 的 `catalog-name` 固定为 `default_catalog`。Spark 继续把 bounded REST
   table response 投影为 schema/location/snapshot lineage，再由既有 harvester 写入独立
   control ledger。
4. 只有 Gravitino readiness、Flink append 计数、Spark 最终内容、schema evolution、snapshot
   parent chain、baseline time-travel、REST lineage 对齐、ledger replay/RLS/跨租户拒绝及
   全部 disposable 资源清理同时通过，报告才标记 `passed`。

## 验证

报告：`.tmp/gravitino-rest/flink-acceptance-report.json`

- schema：`gda.gravitino_iceberg_rest.flink_acceptance.v1`；status：`passed`
- Spark table：`rest.gda_rest_69fdd61e92.chongqing_osm_roads`
- Flink table：`lakehouse.gda_rest_69fdd61e92.chongqing_osm_roads`
- runtime：Gravitino `gda/gravitino:1.3.0-local-arm64`、Spark
  `gisdataagent/mmfe-spark-runtime:local`、Flink `1.19.3-scala_2.12-java11`；Flink
  Iceberg runtime `1.7.2`、AWS bundle `1.7.2`、PostgreSQL JDBC `42.7.4`，报告中保留
  artifact SHA-256。
- Flink 结果：baseline 3 行，append 1 行，final 4 行；Flink catalog/REST 初始化和
  schema evolution 均通过。
- baseline snapshot：`308738034222278014`，content SHA-256
  `f535325b7baf8fdf49a15595c51d0b119b6bec59dab508270032b6f20dd2354b`。
- child snapshot：`4701535070237727532`，parent 为 baseline；final content SHA-256
  `00715fec972f286e02e22f2e016e14c06820937daf392de291aa32fdaf11abc4`。
- architecture observation：source revision `iceberg-snapshot:4701535070237727532`，
  observation SHA-256 `2d8ab0898ee6246e678619d0ae4ad1ebf2c5aa764d941475af4601a952d98d41`，
  schema candidate `78c7ba100a58cbf961101ec7eef200de8158755f5b7e7eea2580755f14f086d6`，
  physical location candidate `f7056163fbfc9da3bf2ee88f5ec43679947dc7152456d303ff7a1e9a48c719db`。
- ledger：observation/registration 写入、replay 幂等、`unbound -> in_sync`、append-only、
  强制 RLS 和跨租户拒绝均为 `true`。
- cleanup：bucket、catalog/Gravitino/Flink 临时容器、volume、network、work directory
  全部 absent。
- canonical `report_sha256`：`ae3a37bd1316c9dabb8867127d7d5f716a918d7aecf1ca909aecc4b000d40d00`
- 文件 SHA-256：`ece1d903ea68c0c219c751b1c68336b0c1b07233937c250df2a5a55695886fc7`

## 未覆盖范围

本证据只放行单表、单并行度、bounded single-operation 的 Flink REST catalog 数据面互操作。
不宣称生产 Flink/Gravitino HA、OIDC/workload identity、metadata fabric production binding、
backup/restore、PITR、RPO/RTO、跨区域复制、双租户恢复、多表/多并行度 conformance、kill-9
或网络不确定提交、通用 SQL UPDATE/MERGE 冲突隔离，亦不改变 GDA metadata、质量、审批和
DataProduct release 的权威边界。
