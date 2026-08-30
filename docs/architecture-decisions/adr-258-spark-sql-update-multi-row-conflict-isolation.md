# ADR-258：多行 Spark SQL UPDATE 的 snapshot guard 冲突隔离

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-257](adr-257-spark-sql-update-snapshot-guard.md)

## 背景

ADR-257 只证明了单键、单行 SQL `UPDATE` 的 snapshot guard。湖仓里的批量修订通常会命中多个
业务键；如果 guard 只保护单行，操作可能出现一个目标已提交、另一个目标未提交的部分结果。
这次切片验证一个明确的多行合同：同一条 SQL `UPDATE` 使用
`road_id IN (id1, id2) AND revision = 1`，两个目标要么整体拒绝，要么整体提交。

## 决策

沿用 ADR-257 的平台侧 snapshot guard，并把 guard 的原子性扩大到整个多行语句：

1. Spark 在 identity(`road_id`)、format-v2 表上建立三行 baseline，记录 baseline snapshot。
2. Spark 在 barrier 前准备一条多行 SQL `UPDATE`；Flink 先以两个独立 bounded append 分别提交
   两个目标道路的 revision 2，形成两个连续的 child snapshot。
3. barrier 释放后 Spark 刷新 Catalog snapshot。只要 current snapshot 不等于 baseline，整条
   多行 UPDATE 返回 `snapshot_guard_rejected`，不发起 SQL UPDATE，也不允许部分目标落库。
4. fresh retry 从 Flink child 重新读取两个 revision-2 行，用同一条 SQL UPDATE 将两个目标一次性
   更新到 revision 3，并验证最终提交是一个 overwrite snapshot。
5. 验收器以 Flink child 对象集合为基线，检查 stale token、快照链、time travel、内容 hash、对象图
   和 SourceSync；失败尝试产生的对象逐对象清理。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 每个目标独立执行单行 UPDATE | 单个目标可重试 | 可能产生部分成功，无法满足批量修订的原子合同 |
| 一条多行 UPDATE + snapshot guard | 语义简单，guard 拒绝时整个语句 fail-closed | 一个目标冲突会阻塞整批；fresh retry 必须重新读取整批状态 |
| 依赖 provider 默认 mutation validation | 平台代码少 | 当前 Spark 3.5/Iceberg 1.6.1/JDBC Catalog 矩阵不能稳定把 stale SQL UPDATE race 转成 `ValidationException` |

选择第二项。多目标操作的可预测性优先于单目标吞吐，批量重试由上层调度器负责。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_update_multi_conflict.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_update_multi_conflict.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_update_multi_conflict.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_update_multi_conflict_2026-08-24.json`  
报告 SHA-256：`bfd1ad94cb07db586857b9bed243ff32e30ecd7b1b0146699ab042807cd8212b`

- 真实重庆 OSM source 绑定 50,366 个要素；选定道路 `102262017`、`102262020`。
- baseline 为 1 个 append snapshot；两个 Flink revision-2 append 将链推进到 3 个 snapshot。
- stale 多行 UPDATE 被 guard 整体拒绝，两个目标都保留 revision 1/2，stale token 计数为 0，catalog
  未新增 snapshot。
- fresh retry 一次性更新两个目标到 revision 3，形成第 4 个 `overwrite` snapshot；baseline、Flink
  child、final time travel 和最终内容 hash 均通过。
- 最终对象图为 4 个 metadata、10 个 manifest、7 个 parquet；对象前缀、Spark/Flink/Catalog
  容器和工作目录均清理，主库 SourceSync 前后均为 `0/0/0`。

## 放行边界

本 ADR 放行：当前版本矩阵下 identity-key、单表、两个目标、简单 `IN` 谓词、同一 expected
revision 的多行 SQL UPDATE snapshot guard、整体 stale fail-closed、整体 fresh retry、time
travel 和对象清理。

仍未放行：任意复杂谓词、join/subquery、多表 UPDATE、跨分区 key 变化、分区/多文件 destructive
write、SQL MERGE 多分支或多 source row、自动 retry/checkpoint recovery、REST/Gravitino
destructive-write conformance、生产 HA/RPO/RTO 和 Kubernetes runtime。

## Revisit trigger

当 provider 升级到能够稳定返回跨会话 stale `ValidationException`，或业务需要大于两个目标、复杂
谓词和跨分区更新时，重新评估 guard 与批量 retry 的实现边界，并增加相应的 provider conformance。
