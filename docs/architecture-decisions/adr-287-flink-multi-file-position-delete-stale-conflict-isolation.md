# ADR-287：Flink 多文件 position-delete stale commit 冲突隔离

**状态**：Accepted（2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-286](adr-286-flink-multi-file-position-delete-write.md)、[ADR-255](adr-255-flink-position-delete-stale-conflict-isolation.md)

## 背景

ADR-286 证明单次 Flink `RowDelta` 可以在两个不同 data file 上写入两条 position delete，但只覆盖
顺序成功提交。多文件 writer 如果继续绑定旧 snapshot，平台需要同时证明：Iceberg 会拒绝整个
RowDelta、两个目标不会部分提交，以及已经写出的 delete file 不会成为对象存储孤儿。

## 决策

沿用 ADR-286 的单表、无分区、单并行度 writer，增加仅用于验收的 `--expect-conflict` 路径：

1. Spark 先物化两个 data file，并记录两个目标道路的 `_file/_pos` 和 baseline snapshot。
2. Flink 正常 writer 先提交同一 multi-file delete，推进 catalog；第二个 writer 仍使用旧 baseline
   和不同 token，构造包含两个 position 记录的单一 `RowDelta`。
3. 旧 snapshot 绑定必须进入 Iceberg validation；只接受 `ValidationException`，不得在客户端用
   snapshot 比较代替 provider 冲突判断。
4. validation 拒绝后，writer 通过 table `FileIO` 删除本次刚物化的 delete file，并输出
   `orphan_cleanup=true`。验收必须证明 catalog metadata location、snapshot 数量和最终读集与
   第一次成功提交完全一致。

## 真实结果

- 正常 multi-file position delete 仍通过；两个目标分别位于不同 data file，一个 Parquet delete file
  含两条精确 `(file_path, pos)` 记录。
- stale writer 的 baseline snapshot 为 `5517918308088270181`，观察到已推进的 current snapshot
  `245893804169684350`，Iceberg 返回 validation rejection；stale token 没有生成 snapshot。
- 冲突前后 catalog metadata location、snapshot 数量（3）和 current snapshot 完全一致，独立 Spark
  仍只读到 guard 行；本次未提交 delete file 清理标记为 `orphan_cleanup=true`。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_flink_spark_multi_file_position_delete.py`  
Flink writer：`scripts/flink/ChongqingOsmIcebergMultiPositionDeleteWriteJob.java`  
聚焦测试：`data_agent/test_chongqing_osm_flink_spark_multi_file_position_delete.py`  
冲突报告：`docs/reports/chongqing_osm_flink_spark_multi_file_position_delete_conflict_2026-08-25.json`  
冲突报告 SHA-256：`86cbcfce87dd165b935e957c16fdb213be05c54f4b83298abb6ad3733ddb2df5`  
正常报告 SHA-256：`3f3240f581513e6aa5a96e1ac04aad56a11ddb124f629c9bc6b63a8639cf7de4`  
writer 源码 SHA-256：`9d80c379f122fa15363fb6ff635118288820f5a723ba62deadc334b0a56ed042`

## 放行边界

本 ADR 放行：无分区表、两个 data file、单并行度 Flink 单 RowDelta 的 stale snapshot 整体拒绝、
catalog 不变和失败 delete file 清理。

仍未放行：分区或超过两个 data file、多个并发/多个 delete file、自动 retry、compaction、checkpoint
exactly-once、provider abort recovery、SQL UPDATE/MERGE、REST/Gravitino conformance、生产 HA/RPO/RTO、
Kubernetes 和生产 SLO。
