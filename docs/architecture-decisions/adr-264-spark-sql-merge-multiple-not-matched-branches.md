# ADR-264：Spark SQL MERGE 的多个 not-matched branch

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-260](adr-260-spark-sql-merge-multi-branch-update-insert.md)、[ADR-263](adr-263-spark-sql-merge-multiple-matched-branches.md)

## 背景

ADR-260 已验证一个 matched-update 与一个 not-matched-insert 的混合批次，ADR-263 已验证
条件 matched-delete 与默认 matched-update 的 branch ordering。实际 source batch 还会把多个
不存在于 target 的道路按 action 分流到不同的插入策略。本切片验证条件 not-matched branch
和默认 not-matched branch 在一次 SQL `MERGE` 中共同提交，并保留明确的 source action、token
和最终对象证据。

## 决策

在 Spark 3.5 / Iceberg 1.6.1 / JDBC Catalog / S3FileIO 版本矩阵下放行一个 bounded slice：

1. 建立三行重庆 OSM baseline，使用 identity(`road_id`) 分区和 format-v2。
2. Flink 先将 `102262017` 写到 revision 2，形成 baseline child snapshot。
3. Spark source 只包含两条唯一、均未命中 target 的 source row：`102262028` 的
   `action=insert_priority` 和 `102262030` 的 `action=insert_default`。
4. 使用单个 SQL `MERGE`，branch 顺序固定为：
   `WHEN NOT MATCHED AND source.action = 'insert_priority' THEN INSERT`，随后是
   `WHEN NOT MATCHED THEN INSERT`。
5. 两条 source row 必须各插入一次，并在同一个 child snapshot 中完成；不能更新或覆盖
   baseline/Flink 已有 row，也不能产生第二次 MERGE。

source row 的 action、expected revision、result revision、token 和 source row id 均由上游
显式生成。本 ADR 不放行自动 branch 推断或复杂匹配谓词。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 两个 branch 拆成两次写入 | 单步逻辑简单 | 产生多个 snapshot，批次出现中间状态 |
| 先由上游拆成两个输入表 | provider 逻辑简单 | branch 选择移出平台，无法证明单批次原子性 |
| 一个 SQL MERGE 按条件 branch 顺序执行 | 单 snapshot、action 可审计、source 可回放 | 当前只覆盖两个 not-matched insert branch |

选择第三项。branch 条件、token、最终 row 集合、snapshot 链和对象图均写入真实 phase report。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_multi_not_matched_branch.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_multi_not_matched_branch.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_multi_not_matched_branch.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_multi_not_matched_branch_2026-08-24.json`  
报告 SHA-256：`ba4a6dc862cc407a13b10c7322675791c199ceb58292da8a5e7062a7ef5ab5b6`

- 真实重庆 OSM source 绑定 50,366 个要素；两个新 road 均不存在于 Flink target state。
- 最终状态为 6 行：baseline 3 行、Flink revision 2 一行、两个 SQL insert 各一行；两个 branch
  token 各出现一次，未发生 matched update。
- snapshot 链为 `append -> append -> append`；baseline/Flink/final time-travel、6 个 parquet、
  6 个 manifest、3 个 metadata 对象和 15 个临时对象清理均通过。
- 报告 10 项顶层检查通过；Catalog/Flink/Spark/MinIO、容器、对象前缀、工作目录清理通过，
  主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、两条唯一 source row、两个均未匹配 target 的 not-matched insert branch、
简单 ON 谓词、单次 SQL `MERGE`。

仍未放行：matched branch 与 not-matched branch 混合的更多组合、更多 not-matched branch、重复
source row 自动去重、复杂谓词/join/subquery、跨分区/多文件 destructive write、自动 retry、
streaming recovery、REST/Gravitino destructive-write conformance、生产 HA/RPO/RTO 和 Kubernetes
runtime。

## Revisit trigger

当 branch 数量、优先级、source cardinality 或条件复杂度增加时，必须重新定义 branch ordering、
cardinality、冲突检测、snapshot、time-travel 和 recovery contract，不在本 ADR 上扩大范围。
