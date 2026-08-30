# ADR-285：混合 partition spec 先受控 rewrite，再执行 equality delete

**状态**：Accepted（2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-282](adr-282-spark-flink-iceberg-partition-evolution.md)、[ADR-283](adr-283-spark-sql-mixed-spec-destructive-write.md)、[ADR-284](adr-284-spark-flink-mixed-spec-equality-delete.md)

## 背景

ADR-284 证明了当前 JDBC Catalog + Spark/Flink provider 不能把一个跨 spec 的 equality delete
传播到旧 spec：equality-delete file 会生成，但旧 spec 0 的同一 `road_id` 仍可见。平台已经加入
fail-closed admission，混合 `data_spec_ids=[0,1]` 不得直接提交 equality delete。

这条路径需要一个可验收的处置方式。第一次试验使用 Spark `INSERT OVERWRITE`，结果只按当前分区
视角替换了 spec 1 文件，旧 spec 0 文件仍在，不能称为全量 rewrite。因此本 ADR 采用显式两步：
先把源行物化为独立 DataFrame，删除表中全部当前数据，再按当前 spec append 回写；只有回写完成、
活动 data files 只剩 current spec 后，才放行 Flink equality delete。

## 验证切片

真实切片按以下顺序执行：

1. Spark 创建 format-v2、`road_id` identifier field 的无分区 baseline。
2. Spark 执行 `ADD PARTITION FIELD identity(road_id)`；Flink append revision=2，形成 spec 0/spec 1
   混合表。
3. 受控 rewrite 读取并校验 Flink snapshot 的 4 行，提交 `DELETE FROM table WHERE road_id IS NOT NULL`，
   再用独立 DataFrame `writeTo(table).append()` 回写。
4. Spark 校验 rewrite 前的 time-travel、rewrite 后的行集、`table.files.spec_id` 和 snapshot parent；
   Flink 提交 equality delete，Spark 独立读取最终表、delete file 和 snapshot 链。

## 结果

真实 PostgreSQL JDBC Catalog + MinIO/S3FileIO + Spark 3.5/Iceberg 1.6.1 + Flink 1.19/Iceberg 1.7.2
组合通过：

- rewrite 前 admission 对 `data_spec_ids=[0,1]` 返回 `rejected`，原因包含
  `mixed_partition_specs_detected`、`cross_spec_equality_delete_unsupported` 和
  `controlled_rewrite_required_before_equality_delete`；
- rewrite 的活动文件先被清空，再以 spec 1 回写；旧 spec 0 文件不再属于当前表，rewrite 前后行集和
  内容 fingerprint 一致；
- 真实 snapshot operation 为 `append -> overwrite -> delete -> append -> delete`，其中第一个
  `delete` 是全量受控清空，第二个 `delete` 是 Flink equality delete；rewrite append snapshot 成为
  equality delete 的父 snapshot；
- rewrite 后 admission 对 `data_spec_ids=[1]` 返回 `admitted`；Flink 物化 `content=2`、
  `record_count=1`、`equality_ids=[1]` 的 Parquet delete file，最终 `road_id=102262017` 的 revision=1
  和 revision=2 均不可见，guard 行保留；
- 容器、对象前缀、工作目录清理通过，主库 SourceSync 保持 `[0,0,0]`。

## 决策

在当前 provider 版本矩阵下，混合 partition spec 的 equality delete 必须经过受控 rewrite admission。
`build_iceberg_equality_delete_admission` 继续作为入口：混合 spec 未 rewrite 时拒绝；rewrite 完成且
活动数据只属于 current spec 时才允许 equality delete。`INSERT OVERWRITE` 不作为跨 spec 全量 rewrite
证据，除非后续 provider 版本有独立的全量文件范围证明。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_mixed_spec_equality_delete.py --controlled-rewrite`  
Spark runner：`scripts/spark_chongqing_osm_iceberg_mixed_spec_equality_delete.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_mixed_spec_equality_delete.py`  
报告：`docs/reports/chongqing_osm_spark_flink_mixed_spec_rewrite_equality_delete_2026-08-25.json`  
报告 SHA-256：`863f025c25c86d8887d37acb65705db389e999299bf35aec9edd7b2f79b78428`

## 放行边界

本 ADR 放行：单表、一次 `identity(road_id)` evolution、单并行度 Flink append、一次显式 delete+append
controlled rewrite、rewrite 后单键 Flink equality delete，以及 baseline/rewrite/final time-travel 和
活动文件 spec 对账。

仍未放行：自动 compaction/rewrite service、rewrite 与并发 writer 的冲突恢复、混合 spec UPDATE/MERGE、
多个 equality-delete files 的业务语义、schema/partition 多次 evolution、REST/Gravitino conformance、
生产 HA/RPO/RTO、Kubernetes、跨系统 exactly-once 和生产 SLO。
