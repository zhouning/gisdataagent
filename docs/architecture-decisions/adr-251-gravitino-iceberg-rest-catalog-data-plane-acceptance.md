# ADR-251：Gravitino Iceberg REST catalog 数据面验收

## 状态

Accepted（disposable Gravitino REST + Spark/Iceberg + MinIO + PostgreSQL JDBC；2026-08-23）

## 背景

ADR-248 固定了 Gravitino Iceberg table architecture harvester，ADR-249/250 验证了真实
Spark/Flink/Iceberg snapshot 到 GDA 控制账本的链路，但此前没有真实 Spark 通过 Gravitino
Iceberg REST catalog 写入 MinIO warehouse 的证据。没有这条证据，Gravitino 仍只能被描述为
metadata-plane 或受限 JDBC catalog 观察，不能确认 REST 数据面与 Iceberg snapshot 操作可用。

## 决策

新增 `scripts/certify_gravitino_iceberg_rest_catalog.py` 和
`scripts/spark_gravitino_iceberg_rest_acceptance.py`，建立一次性、隔离、可清理的 REST 数据面
验收：

1. 启动 disposable MinIO、PostgreSQL 16 JDBC backend、固定镜像
   `gda/gravitino:1.3.0-local-arm64` 和现有冻结 Spark runtime；Gravitino endpoint 固定为
   `http://gravitino:9001/iceberg`，catalog prefix 固定为 `default_catalog`。
2. Spark 使用 Iceberg `RESTCatalog`，经 REST 创建隔离 namespace/table，写入 format v2
   baseline，执行 schema evolution，追加带 `flink_commit_tag` 的记录，再读取 snapshots 和
   baseline time-travel。
3. Gravitino 的 REST 隔离 classloader 显式补齐运行所需依赖：已校验的 PostgreSQL JDBC
   `42.7.4`、Glue 目录中的 `reactive-streams-1.0.4` 以及 AWS SDK jar；MinIO 使用
   `s3-path-style-access=true`，避免虚拟主机 DNS 在隔离网络中漂移。
4. REST `GET table` 返回的标准 Iceberg `metadata` 只经过
   `project_iceberg_rest_table_response` 提取 bounded schema/location/snapshot lineage，再送入
   `harvest_gravitino_iceberg_table` 生成 observation、`SchemaVersion` 和 `PhysicalLocation`
   candidate；完整 metadata JSON、manifest 和 data-file 列表不进入控制面。
5. 只有 namespace 创建、baseline/final 内容、schema、snapshot parent chain、time-travel、
   S3 table location 和 REST readiness 全部通过，且容器、卷、网络、bucket 对象和工作目录
   全部清理，报告才可标记 `passed`。

该决策只认证 REST 数据面，不改变 GDA metadata fabric、architecture ledger 或 DataProduct
release 的权威边界；REST table payload 仍需通过既有 harvester/crosswalk 合同进入控制账本。

## 验证

报告：`.tmp/gravitino-rest/acceptance-report.json`

- schema：`gda.gravitino_iceberg_rest.acceptance.v1`；status：`passed`
- Gravitino image ID：`sha256:d355dc7e92f9e3545d717f3eab2cbdf412115f2b82e1e544d7f6235c1eacd5a5`
- Spark image：`gisdataagent/mmfe-spark-runtime:local`
- Spark Iceberg runtime：`1.6.1`；AWS bundle：`1.6.1`；PostgreSQL JDBC：`42.7.4`，报告中均有 SHA-256
- 真实表：`rest.gda_rest_3bba4a9266.chongqing_osm_roads`
- baseline：3 行，snapshot `5285703686342499418`，content SHA-256
  `91c68e4904904973d816045faace9fb24624413328bdc545f8e74a0bbfad42f5`
- final：4 行、2 个 append snapshots；child `4469874545820748282` 的 parent 为 baseline，content
  SHA-256 `4d80d3501cdec7e9c9e73b2c131eeeb251358b71071d978f1112c449986ba33b`
- 通过 checks：REST readiness、namespace/table create、baseline exact、schema evolution、append
  visible、snapshot parent chain、baseline time-travel、S3 location、REST `GET table`、REST lineage
  与 Spark lineage 一致、REST payload 到 architecture candidate projection
- harvester observation：source revision `iceberg-snapshot:4469874545820748282`，schema snapshot
  `06a056d716180d1ea225ce8b408129eb5f91eb714d9e32f99e305a9a2a768fb9`，schema candidate
  `921ca6203da779cc0c5ec0fc84d50c9b2c034612f3730ff28a79bed58107a069`，physical location candidate
  `f2f9ce4308440dbec646ac1f3e631b206ae5354a53547602b2eb1b10713a58f6`
- disposable GDA control ledger：observation 写入、replay 幂等、`unbound -> in_sync`、append-only
  present count、强制 RLS 和跨租户读取拒绝均为 `true`；ledger status 为 `in_sync`，control
  PostgreSQL container 清理成功
- 清理 checks：bucket、catalog/Gravitino/Spark 临时资源、entity volume、network、work directory
  全部 absent
- canonical `report_sha256`：`468bcaec08a5c83bb7539628b3f7222dfde60761dee30181919807b6b1c081d0`
- 文件 SHA-256：`dfef08db0deff8a4bad8a63ef55627f6ee92e70d12a19e4a1ee1796e2b1b9791`

## 未覆盖范围

本证据不宣称 Flink 通过 Gravitino REST、生产 metadata fabric binding、
provider-wide schema/lineage、生产 OIDC/workload identity、HA、backup/restore、PITR、RPO/RTO、
跨区域复制、双租户恢复、多表/多并行度 conformance，或生产唯一 catalog 路径。Gravitino REST
数据面通过后，仍需把 REST provider payload 接入现有 harvester/crosswalk，并完成上述生产门槛。
