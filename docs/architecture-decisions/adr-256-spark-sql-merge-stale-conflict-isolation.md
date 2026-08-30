# ADR-256：Spark SQL MERGE stale snapshot 冲突隔离

**状态**：Accepted（2026-08-23）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-113](adr-113-partition-replace-update-conflict-isolation.md)、[ADR-255](adr-255-flink-position-delete-stale-conflict-isolation.md)

## 背景

已有 update 证据使用 Iceberg `OverwriteFiles` 和 `overwritePartitions()` 完成 identity-partition
replace；ADR-104 的 `MERGE INTO` 只覆盖顺序 micro-batch 的正常写入。两者都不能证明 Spark SQL
`MERGE INTO` 在另一个引擎先推进同一业务键之后会拒绝陈旧提交，也不能证明失败的 MERGE 尝试不会
把未提交对象留在 lakehouse。

## 决策

本阶段增加一个可重复的单键 SQL MERGE profile：

1. Spark 在 identity(`road_id`)、format-v2 copy-on-write 表建立三行重庆 OSM baseline，并绑定
   `expected_revision=1` 的 SQL MERGE source。
2. Spark source scan 通过 acceptance barrier 停在提交前；Flink bounded single-operation
   `INSERT INTO` 为同一 `road_id` 提交 revision 2，推进 JDBC Catalog child snapshot 后释放
   Spark MERGE。
3. MERGE 的 `ON` 条件同时绑定 `road_id` 和 `expected_revision`，只允许一个 matched row 更新
   revision、payload、writer 和 commit token。只接受真实 Iceberg `ValidationException` 作为 stale
   conflict；catalog 不得新增 snapshot，stale token 不得出现在当前数据中。
4. 验收器以 Flink child 提交后的对象集合为基线，枚举并逐对象删除 stale MERGE 新产生的对象，
   同时验证 catalog metadata location、snapshot chain 和 Flink 数据文件没有被误删。
5. 独立 Spark retry 先读取 Flink child state，再以 `expected_revision=2` 执行 fresh SQL MERGE
   将 revision 2 更新为 revision 3；独立 Spark verify 回读 baseline、Flink child 和最终 snapshot
   的 time travel 内容。

该切片不推进 SourceSync 或 DataProductVersion；它认证的是 provider SQL mutation 的冲突边界和
失败 artifact 处理。

## 真实验证

验收入口：
`scripts/certify_chongqing_osm_spark_flink_sql_merge_conflict.py`  
Spark phase：
`scripts/spark_chongqing_osm_iceberg_sql_merge_conflict.py`

报告：`.tmp/source-sync-certification/chongqing-osm-spark-flink-sql-merge-conflict-report.json`  
报告 SHA-256：`4cb13c93cccba85425c31af22d6753e6619d7f7f0a10a60606185722943e08c0`

- 真实重庆 OSM source 为 50,366 个要素；baseline、Flink revision 2、SQL retry revision 3
  均由确定性 token 和内容 hash 绑定。
- stale SQL MERGE 返回 provider `ValidationException`；catalog 保持两条 append snapshot，
  stale token 数为 0，baseline 与 Flink child 四行内容不变。
- fresh SQL MERGE 生成第三条 `overwrite` snapshot，parent 精确为 Flink child；最终四行、
  baseline time travel、Flink time travel 和 final time travel 全部通过。
- 本次 stale MERGE 没有产生新对象（`detected_keys=[]`）；验收仍执行了按对象清理门。最终对象图
  为 3 个 metadata JSON、7 个 manifest/list AVRO、5 个 Parquet，共 15 个对象。
- Spark、Flink、JDBC Catalog 容器、对象前缀和工作目录清理通过；主库 SourceSync 前后均为
  `0/0/0`。

## 放行边界

本 ADR 放行：当前 Spark 3.5/Iceberg 1.6.1/JDBC Catalog/S3FileIO 版本矩阵下，identity-key
单键、单 source row、`WHEN MATCHED THEN UPDATE` 的 bounded SQL MERGE stale snapshot 拒绝、
fresh-state retry、time travel 和对象清理。

仍未放行：SQL `UPDATE` 的独立语义、MERGE 的 insert/delete 分支、多 source row 或多目标匹配、
跨分区 key 变化、partition evolution、equality/position delete、MOR、多并发 streaming writer、
自动 retry/checkpoint recovery、REST/Gravitino destructive-write conformance、跨系统 exactly-once、
生产 HA/RPO/RTO 和 Kubernetes runtime。
