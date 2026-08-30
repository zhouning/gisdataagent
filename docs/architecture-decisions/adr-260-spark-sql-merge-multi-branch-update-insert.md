# ADR-260：Spark SQL MERGE 的 matched-update + not-matched-insert 多分支

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-256](adr-256-spark-sql-merge-stale-conflict-isolation.md)、[ADR-259](adr-259-spark-sql-merge-multi-source-row-conflict-isolation.md)

## 背景

ADR-256 只证明单 source row 的 `WHEN MATCHED THEN UPDATE`，ADR-259 证明重复 source row
必须由 provider cardinality validator 拒绝。湖仓 mutation 还需要一个能同时处理已有道路更新和
新道路插入的 SQL `MERGE`，否则上游只能拆成多个写入操作，难以保持同一 snapshot 边界和可回放
的 branch 证据。

## 决策

在当前 Spark 3.5 / Iceberg 1.6.1 / JDBC Catalog / S3FileIO 版本矩阵下，先放行一个严格的
多分支 slice：

1. 建立三行重庆 OSM baseline，使用 identity(`road_id`) 分区和 format-v2。
2. Flink 先为 baseline 中的一条道路提交 revision 2，形成 baseline 的 child snapshot。
3. Spark 读取该 Flink snapshot，提交一个两行 source：一行绑定
   `road_id + expected_revision=2`，走 `WHEN MATCHED THEN UPDATE` 更新到 revision 3；另一行使用
   baseline 外的真实 OSM road，走 `WHEN NOT MATCHED THEN INSERT` 写入 revision 1。
4. MERGE 必须只产生一条 child snapshot；matched token 和 insert token 各出现一次；baseline 和
   Flink snapshot 均可 time-travel 回读。

两条 source row 的身份、token 和 branch 均由上游显式生成。这个 slice 不自动推断重复 source
优先级，也不把 provider 默认行为扩展成生产 recovery 或跨系统 exactly-once。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 先 update、再 insert 两次提交 | 单步简单 | 两个 snapshot，消费者可能看到半完成状态 |
| 只使用 `INSERT OVERWRITE` 重建分区 | 可控制最终内容 | 丢失 SQL MERGE branch 语义，source-to-target 证据变弱 |
| 单次 SQL MERGE 的 matched-update + not-matched-insert | 一个 snapshot、branch 可审计、保持 time-travel 链 | 当前只覆盖单表、单 target row、单 insert row 和简单 ON 谓词 |

选择第三项。复杂谓词、多个 target row、多个 matched branch、delete branch 和跨分区 key 变化
继续拆成独立 ADR，避免一次放行过大的 mutation 语义。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_multi_branch.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_multi_branch.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_multi_branch.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_multi_branch_2026-08-24.json`  
报告 SHA-256：`95981585330ff72906a482e33922fa5b4a527b6627cd6f5f63e6fbd4dd2432f0`

- 真实重庆 OSM source 绑定 50,366 个要素；目标道路为 `102262017`，插入道路为
  `102262028`，后者不在三行 baseline 中。
- Flink revision 2 append、Spark matched update、Spark not-matched insert、独立 verify 均通过。
- snapshot 链为 `append -> append -> overwrite`；baseline 与 Flink snapshot time-travel 精确回读，
  最终 5 行内容 hash 与 plan 一致；matched/insert token 各出现一次，`(road_id, revision)` 无重复。
- 对象图 materialized（metadata/manifest/parquet 数量门通过）；Catalog、Flink、Spark、MinIO、
  对象前缀和工作目录均清理；主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：当前版本矩阵下单表、identity(`road_id`) 分区、单 target row 的 matched update
和单 baseline 外 row 的 not-matched insert，单次 SQL MERGE snapshot 及 baseline/Flink/final
time-travel 证据。

仍未放行：MERGE delete、多个 matched/not-matched branch、多 target row、复杂谓词/join/subquery、
跨分区或多文件 destructive write、自动去重、自动 retry、streaming checkpoint recovery、
REST/Gravitino destructive-write conformance、生产 HA/RPO/RTO 和 Kubernetes runtime。

## Revisit trigger

当业务需要多个 branch 的优先级、delete 或跨分区 key 变化时，必须分别定义 source cardinality、
branch ordering、冲突检测、time-travel 和 recovery contract，再新增真实验收，不在本 ADR 上扩大范围。
