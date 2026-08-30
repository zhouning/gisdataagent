# ADR-266：Spark SQL MERGE cardinality 拒绝后的自动 fresh-state retry

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-259](adr-259-spark-sql-merge-multi-source-row-conflict-isolation.md)

## 背景

ADR-259 已证明重复 source row 必须 fail-closed，并由外部 phase 显式提交去重后的 fresh
source。这个边界保护了数据，但把重试编排留给调用方；调用方如果在失败后重新启动 writer，
容易丢失冲突上下文、snapshot 身份和 retry 证据。本切片把“拒绝、确认 catalog 未推进、读取
Flink child、提交 policy-bound fresh source”收敛到同一个 Spark worker 进程中。

## 决策

在 Spark 3.5 / Iceberg 1.6.1 / JDBC Catalog / S3FileIO 版本矩阵下放行一个 bounded slice：

1. 建立三行重庆 OSM baseline，Flink 先为 `102262017` 写入 revision 2。
2. Spark worker 提交两条绑定同一 `road_id + expected_revision=1` 的 source row；Spark
   cardinality validator 必须拒绝，两个 stale token 不得落库，catalog 必须保持 Flink child。
3. 同一 worker 读取 release marker 的 Flink snapshot 身份，确认当前行集和 snapshot 与
   `after_flink_rows` 完全一致，然后自动提交一条上游已确定的 `fresh-source-deduplicated`
   row（`expected_revision=2`、result revision 3）。
4. fresh retry 必须形成 Flink child 的 overwrite snapshot，并输出 conflict/retry 聚合证据。

本 ADR 自动化的是 retry 编排和 fresh-state admission，不自动决定重复 source row 的优先级，
不自动生成 deduplication 业务规则。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 失败后由调用方重新启动 retry | 改动小 | 冲突上下文和 snapshot 绑定容易丢失 |
| worker 内拒绝后自动校验 fresh state 并 retry | retry 证据连续、snapshot 身份受控、可审计 | fresh source 仍需上游显式确定 |
| worker 自动选择重复 source 的优先级 | 调用方简单 | 把未经审批的业务去重规则藏入平台 |

选择第二项；第三项仍由单独的 deduplication contract 决定。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_auto_retry.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_auto_retry.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_auto_retry.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_auto_retry_2026-08-24.json`  
报告 SHA-256：`497e99a92844dd01505f8d7a6c975ae4e477bfe84250d77fde863831dfda7cfd`

- 真实重庆 OSM source 绑定 50,366 个要素；重复 source 的两个 stale token 均为 0。
- Spark 真实观察到 `MergeRowsExec$BitmapCardinalityValidator` cardinality rejection；catalog
  保持 `append -> append`，随后同一 worker 自动 fresh retry 形成第三条 overwrite snapshot。
- 最终 4 行内容、baseline/Flink/final time-travel、3 个 metadata、7 个 manifest、5 个 parquet
  对象图全部通过。
- 报告 10 项顶层检查通过；容器、对象前缀、工作目录清理通过，主库 SourceSync 前后均为
  `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、单 target、两条重复 source row 的 cardinality fail-closed，以及同一 Spark
worker 内绑定 Flink child snapshot 的单次 fresh retry。

仍未放行：自动 deduplication 规则、多个 target/跨分区 retry、复杂谓词、自动 retry budget/退避、
streaming checkpoint recovery、REST/Gravitino destructive-write conformance、生产 HA/RPO/RTO、
Kubernetes recovery controller 和跨系统 exactly-once。

## Revisit trigger

当 retry 需要自动选择 source、跨多个 target 或处理连续失败/退避预算时，必须新增 deduplication、
retry budget、fencing、checkpoint/recovery 和 incident 证据，不在本 ADR 上扩大范围。
