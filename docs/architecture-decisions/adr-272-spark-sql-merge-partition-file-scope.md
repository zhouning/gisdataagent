# ADR-272：Spark SQL MERGE 跨分区多文件写入范围对账

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-262](adr-262-spark-sql-merge-multi-target-update.md)、[ADR-271](adr-271-spark-sql-merge-cross-target-survivorship.md)

## 背景

ADR-262 和 ADR-271 已证明一次 SQL `MERGE` 可以更新两个 target，但证据只覆盖行集和 snapshot
链，没有把逻辑 target 映射到 Iceberg 的物理 data files。跨分区 destructive write 如果误触 guard
分区，行集可能暂时看似正确，后续 compaction 或回滚却会扩大影响范围。

## 决策

在 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO、`identity(road_id)` 单表 profile 中，
为该切片增加可选的 `file_scope_contract`：

1. MERGE 前后读取同一表的 Iceberg `table.files` metadata，记录 `file_path`、完整 `partition`
   struct 和解析出的 `road_id`。
2. 按 `road_id` 比较 before/after 文件集合；两个 target 分区必须发生替换，预先选定的 guard
   分区必须保持完全相同，变化分区集合必须精确等于 target 集合。
3. 保留 baseline/Flink/final snapshot parent、time-travel、对象图、清理和 SourceSync 对账。
4. 该合同只在显式 plan 中启用，既有多目标回归默认不改变。

## 取舍

选择 Iceberg `table.files` 是因为它直接反映 provider 当前 snapshot 的 data-file 视图，能把
逻辑分区范围和物理对象集合放进同一份验收报告。代价是合同依赖 Iceberg metadata-table schema，
因此实现会在缺少 `file_path` 或 `partition` 时 fail closed；本切片不把结果推广到 partition evolution、
delete-file/MOR、跨 catalog 或生产 HA。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_partition_file_scope.py`  
Spark writer：`scripts/spark_chongqing_osm_iceberg_sql_merge_partition_file_scope.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_partition_file_scope.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_partition_file_scope_2026-08-24.json`

## 放行边界

本 ADR 放行：单表、两个 identity 分区、一次 matched-update MERGE 的物理文件范围对账。

仍未放行：通用 partition evolution、混合分支/多 source row 的跨分区写入、MOR delete files、
跨系统 exactly-once、自动 retry/backoff、provider abort recovery、HA/RPO/RTO、REST/Gravitino
destructive-write conformance 和生产规模 SLO。
