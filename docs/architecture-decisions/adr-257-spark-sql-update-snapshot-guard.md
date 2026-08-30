# ADR-257：Spark SQL UPDATE snapshot guard 冲突隔离

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-113](adr-113-partition-replace-update-conflict-isolation.md)、[ADR-256](adr-256-spark-sql-merge-stale-conflict-isolation.md)

## 背景

ADR-113 的 `overwritePartitions()` 和 ADR-256 的 SQL `MERGE INTO` 分别验证了 partition-replace
与单键 matched-update。SQL `UPDATE` 需要单独认证：它必须只更新满足业务键和 revision 条件的行，
并且在另一个引擎先提交后拒绝陈旧请求。

真实运行发现，当前 Spark 3.5/Iceberg 1.6.1 JDBC Catalog 版本矩阵的 SQL `UPDATE` 不会可靠地把
这种跨会话 stale race 转换成 provider `ValidationException`；直接执行可能产生重复 revision。因此
不能仅依赖 provider 的默认 mutation validation。

## 决策

对 SQL `UPDATE` 采用平台侧 snapshot guard：

1. Spark 建立 identity(`road_id`)、format-v2 copy-on-write baseline，并记录 baseline snapshot。
2. SQL UPDATE 在 barrier 前准备，Flink bounded single-operation `INSERT INTO` 先提交同一
   `road_id` revision 2。
3. barrier 返回后，Spark 清除 table cache、刷新表元数据并读取当前 snapshot；若 current snapshot
   不等于 baseline，直接返回 `snapshot_guard_rejected`，不执行 SQL UPDATE。该拒绝是平台 fail-closed
   控制，不伪装成 provider `ValidationException`。
4. 只有 snapshot 仍为 baseline 时才允许执行 SQL `UPDATE ... WHERE road_id = ... AND revision = ...`。
   fresh retry 必须先读取 Flink child，再以 `expected_revision=2` 更新到 revision 3。
5. 验收器以 Flink child 对象集合为基线，清理 stale 尝试新增的对象，验证 catalog、time travel、
   内容 hash 和 SourceSync 不受影响。

## 取舍

| 方案 | 结果 | 取舍 |
|---|---|---|
| 依赖 Iceberg SQL UPDATE 默认 validation | 实现短 | 当前版本矩阵不能稳定拒绝跨会话 stale race，可能产生错误 revision |
| 先读 snapshot、变化即拒绝，再执行 SQL UPDATE | 平台语义稳定、可观测 | guard 与 UPDATE 之间仍需 provider commit validation；需要 freshness retry |
| 继续使用 `overwritePartitions()` 代替 SQL UPDATE | 可复用既有证据 | 无法证明 SQL UPDATE 语义 |

选择第二项，因为平台需要 fail-closed 的控制面合同，而当前 provider 行为不足以独立承担该合同。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_update_conflict.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_update_conflict.py`  
报告：`.tmp/source-sync-certification/chongqing-osm-spark-flink-sql-update-conflict-report.json`  
报告 SHA-256：`8d92d3cb8f2e6338ef00fc0dc8d65fa9a3ddcadb616ee7cf51a6e4bf9a417d0a`

- 真实重庆 OSM source 为 50,366 个要素；Flink 同键 revision 2 先提交并推进 child snapshot。
- SQL UPDATE snapshot guard 识别 baseline/current snapshot 变化并拒绝 stale request；catalog 保持
  两条 append snapshot，stale token 不在当前数据中。
- fresh-state SQL UPDATE 将 revision 2 更新为 revision 3，形成第三条 overwrite snapshot；
  baseline、Flink child、final time travel 和最终内容 hash 全部通过。
- 最终对象图、容器、对象前缀和工作目录清理通过；主库 SourceSync 前后均为 `0/0/0`。

## 放行边界

本 ADR 放行：当前版本矩阵下 identity-key 单行、单谓词、`SET` 字段更新的 SQL UPDATE snapshot
guard、stale fail-closed、fresh retry、time travel 和对象清理。

仍未放行：UPDATE join/subquery、多表或多行复杂谓词、跨分区 key 变化、MERGE insert/delete/
多 source row、equality/position delete、MOR、自动 retry/checkpoint recovery、REST/Gravitino
destructive-write conformance、生产 HA/RPO/RTO 和 Kubernetes runtime。
