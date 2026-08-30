# ADR-281：Spark SQL UPDATE SET 相关 scalar subquery capability probe

**状态**：Accepted（2026-08-25，能力未放行）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-280](adr-280-spark-sql-update-correlated-subquery.md)、[ADR-273](adr-273-spark-sql-update-subquery-scope.md)

## 背景

WHERE 子句中的相关 `EXISTS` 已有真实证据，但 UPDATE 的 SET 表达式使用外层 target key 的相关 scalar subquery 是否被 Spark/Iceberg writer 支持，不能从 SELECT 查询能力推断。若 provider 在 rewrite 阶段拒绝，平台必须在提交前 fail-closed，不能降级成字符串 ID、逐行写入或静默改写业务语义。

## 决策

为该能力建立真实 capability probe。测试使用两个 Flink child 将 target 推进到 revision 2，然后执行：

```sql
SET writer_engine = (
  SELECT scope.writer_engine
  FROM gda_sql_update_scope AS scope
  WHERE scope.scope_road_id = road_id
    AND scope.eligible = true
)
```

probe 要求 Spark/Iceberg `AnalysisException` 出现在提交前，UPDATE 不产生 snapshot、不写入 commit token，行集和 content hash 保持不变，baseline/Flink time-travel 仍可读。报告状态 `passed` 只表示 fail-closed probe 通过；`capability_status=unsupported_fail_closed` 表示当前 runtime 不具备该能力，不能作为已支持的 UPDATE 特性发布。

## 真实验证

入口：`scripts/certify_chongqing_osm_spark_flink_sql_update_scalar_subquery.py`  
worker：`scripts/spark_chongqing_osm_iceberg_sql_update_scalar_subquery.py`  
实现：`scripts/spark_chongqing_osm_iceberg_sql_update_multi_conflict.py`  
测试：`data_agent/test_chongqing_osm_spark_flink_sql_update_scalar_subquery.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_update_scalar_subquery_2026-08-25.json`  
报告 SHA-256：`c6f22f9bd7765f00de0c8b6b0a5ca7cf604ec32b6d38a08316742725e9acc558`

关键事实：provider `AnalysisException`、`probe_update_not_committed=true`、`probe_snapshot_chain_unchanged=true`、`probe_rows_unchanged=true`、`probe_token_absent=true`，最终 snapshot 数量保持 3，主 SourceSync 保持 `[0,0,0]`。

## 边界

本 ADR 不放行 SET 相关 scalar subquery，也不放行 UPDATE JOIN、多表写入、多个匹配 scalar scope row、跨分区/多文件 destructive write、MOR/delete files、自动 retry budget/backoff、provider abort recovery、REST/Gravitino conformance、HA/RPO/RTO 或生产 SLO。
