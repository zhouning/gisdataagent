# ADR-267：Spark SQL MERGE 复杂 AND/OR/IN 谓词的 bounded 语义

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-265](adr-265-spark-sql-merge-mixed-branches.md)、[ADR-266](adr-266-spark-sql-merge-automatic-fresh-retry.md)

## 背景

前置切片已经覆盖单个简单等值 `ON` 谓词、四分支 `MERGE` 和 cardinality
fail-closed。生产 SQL 还会把 source 的版本条件、动作条件和 target 属性组合在一起；只验证简单
等值谓词不足以证明条件分支不会误更新或把 guard row 当作 insert。

本切片验证单表、单次 Spark SQL `MERGE` 的组合谓词：

```sql
target.road_id = source.road_id
AND target.revision = source.expected_revision
AND (
  source.action = 'promote'
  OR (source.action = 'refresh' AND target.road_id IN (102262020))
)
```

source 包含两条应更新的 row（`102262017/promote`、`102262020/refresh`）和一条
`102262024/ignore` guard row。guard row 的 road ID 存在于 target，但 action 不满足谓词，预期不
更新、不插入、不产生有效提交 token。

## 决策

在 Spark 3.5、Iceberg 1.6.1、JDBC Catalog、S3FileIO 和单表 identity-key profile 下放行这个
bounded slice：

1. 以三行真实重庆 OSM baseline 建表，Flink 先追加 `102262017` 的 revision 2。
2. Spark 用上述 `AND/OR/IN` 组合 `ON` 谓词执行一次 `MERGE`，同时处理两条 matched-update
   source row 和一条 guard row。
3. 目标更新必须各出现一次，最终表为四行；guard road 仍是 baseline revision 1，guard token
   不得出现在有效结果中。
4. 提交必须形成 Flink child 的单个 overwrite snapshot，并可独立读取 baseline、Flink child 和
   final snapshot。

复杂谓词只决定匹配，不替代 source 版本绑定、质量门或业务去重规则；该切片不引入自动重试。

## 取舍

| 方案 | 优点 | 代价 |
|---|---|---|
| 只保留等值 `ON` 谓词 | 实现和验证最简单 | 无法覆盖动作条件、版本条件组合造成的误匹配风险 |
| 在单表内认证 `AND/OR/IN` 组合 | 覆盖常见条件组合，能证明 guard row fail-closed | 仍未覆盖 join/subquery、跨表和跨分区文件语义 |
| 同时放行跨分区、多文件和自动 retry | 一次覆盖面更大 | 无法区分谓词语义、物理写入和重试编排的故障边界 |

选择第二项，保持每片证据的故障边界可定位。

## 真实验证

验收入口：`scripts/certify_chongqing_osm_spark_flink_sql_merge_complex_predicate.py`  
Spark phase：`scripts/spark_chongqing_osm_iceberg_sql_merge_complex_predicate.py`  
聚焦测试：`data_agent/test_chongqing_osm_spark_flink_sql_merge_complex_predicate.py`  
报告：`docs/reports/chongqing_osm_spark_flink_sql_merge_complex_predicate_2026-08-24.json`  
报告 SHA-256：`cd55e5621fe2e5d7c4965259369f52a34a8fb1478226f77d6f7c8a0d34028031`

- 10 项顶层检查全部通过，真实 source 绑定 50,366 个重庆 OSM 要素。
- 两条有效 matched-update token 各出现一次；guard token 未出现，`102262024` 保持 revision 1。
- 最终四行内容精确，快照链为 `append -> append -> overwrite`，final snapshot 是 Flink child。
- baseline/Flink/final time-travel、17 个物理对象、供应链 artifact/classloader 检查和独立最终
  回读均通过。
- Spark、Flink、Catalog 容器、对象前缀和工作目录清理通过；主库 SourceSync 前后均为 `[0, 0, 0]`。

## 放行边界

本 ADR 放行：单表、单次 SQL `MERGE`、两条 matched-update 与一条不满足条件的 guard source row，
以及 `AND/OR/IN` 组合 `ON` 谓词的 fail-closed 匹配语义。

仍未放行：SQL UPDATE 复杂谓词、join/subquery、多表、跨分区/多文件 destructive write、更多
branch、自动 deduplication、自动 retry budget/退避、混合分支并发冲突、REST/Gravitino destructive-
write conformance、生产 HA/RPO/RTO、Kubernetes recovery 和跨系统 exactly-once。

## Revisit trigger

当谓词需要 join/subquery、跨表条件、分区裁剪或多文件写入时，必须新增对应 conformance 和
冲突/回滚证据；不得把本 ADR 的单表结果扩展为通用 SQL MERGE 或生产 writer recovery 承诺。
