# ADR-286：Flink 单 RowDelta 跨两个 data file 的 position-delete 写入

**状态**：Accepted（2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-120](adr-120-flink-spark-position-delete-write-interoperability.md)、[ADR-255](adr-255-flink-position-delete-stale-conflict-isolation.md)

## 背景

ADR-120 只证明 Flink 可以针对一个无分区 data file 的一个 row position 写入 position-delete，ADR-255
又只证明同一文件、单行 stale commit 会被拒绝并清理未提交 delete file。平台要处理真实湖仓表，不能把
“一个 delete file 只有一条记录”当作多文件写入已经成立。

本 ADR 增加一个严格 bounded 的物理范围切片：Spark 先把三条重庆 OSM 道路写成两个 data file，两个目标
道路分别位于不同文件；Flink 单并行度、单次 RowDelta 在同一个 Parquet position-delete file 中写入两条
`(file_path, pos)` 记录；Spark 独立检查两个原 data file、delete file payload 和最终读集。

## 决策

当前 provider 允许一个 Flink RowDelta 同时绑定两个 data file：writer 必须在提交前验证两份
`dataFilePath` 存在、绑定 baseline snapshot，并以 fail-closed 的 `Expressions.alwaysTrue()` conflict
filter 拒绝任何并发 data/delete file 变化。delete file 的 `record_count` 必须等于两条 position 记录，且
每条记录必须精确指向 baseline 的 `_file/_pos`。

## 真实结果

- 两个 Spark append snapshot 物化两个 data file，目标道路物理位置分别为 `(file A, 0)` 和 `(file B, 0)`；
- Flink 单任务提交一个 `content=1`、Parquet、`record_count=2`、`equality_ids=[]` delete file；
- Spark 独立读回只剩 guard 道路，两个原 data file 保留，snapshot parent 链为
  `append -> append -> delete`；
- 物理 Parquet payload 直读得到两条精确 `(file_path, pos)`，对象图、容器和工作目录清理通过，主库
  SourceSync 保持 `[0,0,0]`。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_flink_spark_multi_file_position_delete.py`  
Spark runner：`scripts/spark_chongqing_osm_iceberg_multi_file_position_delete.py`  
Flink writer：`scripts/flink/ChongqingOsmIcebergMultiPositionDeleteWriteJob.java`  
聚焦测试：`data_agent/test_chongqing_osm_flink_spark_multi_file_position_delete.py`  
报告：`docs/reports/chongqing_osm_flink_spark_multi_file_position_delete_2026-08-25.json`  
报告 SHA-256：`3f3240f581513e6aa5a96e1ac04aad56a11ddb124f629c9bc6b63a8639cf7de4`

## 放行边界

本 ADR 放行：无分区表、两个 data file、一次单并行度 Flink RowDelta、一个包含两条 position 记录的
delete file，以及 Spark/Flink 顺序读写的物理范围对账。

仍未放行：分区表、超过两个 data file、多个 delete file、范围/复合业务条件、并发 position/MOR writer、
stale multi-file retry、自动 compaction、SQL UPDATE/MERGE、checkpoint exactly-once、REST/Gravitino
conformance、生产 HA/RPO/RTO、Kubernetes 和生产 SLO。
