# ADR-263：Spark SQL MERGE 的多个 matched branch

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-260](adr-260-spark-sql-merge-multi-branch-update-insert.md)、[ADR-261](adr-261-spark-sql-merge-matched-delete.md)、[ADR-262](adr-262-spark-sql-merge-multi-target-update.md)

## 背景

ADR-260 和 ADR-261 分别验证了 update/insert 与 matched-delete；ADR-262 验证了两个 target
在同一 matched-update 分支中更新。真实批次还需要根据 source 行的 action 在多个 matched
branch 之间做确定性选择。本切片验证一个条件 delete branch 加一个默认 update branch，确保
branch 顺序不会把 delete 行错误地写成 update。

## 决策

在 Spark 3.5 / Iceberg 1.6.1 / JDBC Catalog / S3FileIO 版本矩阵下放行：

1. 三行重庆 OSM baseline 上，Flink 先将 `102262017` 提交为 revision 2。
2. Spark source 只有两条唯一 row：`102262017 + expected_revision=2 + action=delete`，以及
   另一条 baseline road `102262020 + expected_revision=1 + action=update`。
3. 使用一个真实 SQL `MERGE`，branch 顺序固定为：
   `WHEN MATCHED AND source.action = 'delete' THEN DELETE`，随后是默认的
   `WHEN MATCHED THEN UPDATE SET`。
4. delete target 的 revision 1 必须保留、revision 2 必须删除；update target 必须产生 revision 2。
   两个 branch 在同一个 child snapshot 内完成，不能部分提交。

source row 的 action、expected revision、token 和 source row id 由上游显式生成；本 ADR 不放行
自动 branch 推断、复杂谓词或更多 branch。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 两个 branch 拆成两次写入 | 单步容易理解 | 产生多个 snapshot，批次有中间状态 |
| 先由上游拆成 delete/update 两个表 | provider 逻辑简单 | branch 选择移出平台，难以证明单批次原子性 |
| 一个 SQL MERGE 按条件 branch 顺序执行 | 单 snapshot、branch 选择可审计、source action 可回放 | 当前仅覆盖一个条件 delete + 一个默认 update |

选择第三项。branch ordering、cardinality 和 target 结果都写入真实 phase report。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_multi_matched_branch.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_multi_matched_branch.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_multi_matched_branch.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_multi_matched_branch_2026-08-24.json`  
报告 SHA-256：`3ea49d71aa9ee2e1177da08a42e3154e40bc9a65a8e70e91a58dd086eb5a795f`

- 真实重庆 OSM source 绑定 50,366 个要素；delete target 的 revision 2 被删除，revision 1 保留；
  update target 得到 revision 2。
- snapshot 链为 `append -> append -> overwrite`；delete branch token 为 0，update branch token
  为 1；最终三行内容、baseline/Flink/final time-travel 和对象图全部通过。
- 报告 10 项顶层门通过；Catalog/Flink/Spark/MinIO、对象前缀、工作目录清理通过，主库
  SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、两条唯一 source row、两个不同 target row、一个条件 matched-delete branch
加一个默认 matched-update branch 的单次 SQL `MERGE`。

仍未放行：更多 branch、多个 not-matched branch、重复 source row 自动去重、复杂谓词/join/subquery、
跨分区/多文件 destructive write、自动 retry、streaming recovery、REST/Gravitino destructive-write
conformance、生产 HA/RPO/RTO 和 Kubernetes runtime。

## Revisit trigger

当 branch 数量、优先级或条件复杂度增加时，必须重新定义 branch ordering、cardinality、冲突检测、
time-travel 和 recovery contract，不在本 ADR 上扩大范围。
