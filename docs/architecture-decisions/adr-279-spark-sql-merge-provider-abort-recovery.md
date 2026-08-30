# ADR-279：Spark SQL MERGE provider abort recovery

**状态**：Accepted（2026-08-24）  
**关联 Roadmap**：[GIS Data Agent 总体架构](../roadmap.md) AR-2  
**前置决策**：[ADR-254](adr-254-flink-iceberg-physical-fault-uncertainty-reconciliation.md)、[ADR-278](adr-278-spark-sql-merge-cross-process-successful-retry.md)

## 背景

Spark SQL MERGE 可能已经完成 Iceberg commit，但 provider worker 在把提交结果返回给调用方之前被终止。此时重试方不能根据“调用失败”再次写入；必须先读取 JDBC Catalog 和对象存储，确认已经存在的 snapshot、parent、最终行集和 commit token，再决定是否需要动作。

## 决策

在隔离的 PostgreSQL JDBC Catalog、MinIO、Flink 和 Spark runtime 上执行一个单表、单 target、单次 destructive write slice：

1. baseline snapshot 由 Spark 创建，Flink 将 target 推进到 revision 2。
2. Spark abort-after-commit worker 在 revision 2 上执行 fresh SQL MERGE，提交 revision 3 后写入 host-mounted commit marker。
3. certifier 在 marker 持久化后对 Spark 容器发送 SIGKILL，接受该 worker 的非零退出作为预期故障注入结果。
4. 独立 Spark abort-reconcile worker 读取 marker、JDBC Catalog 和 MinIO，对账状态标为 committed_unacknowledged，不重放写入。
5. 独立 verify worker 校验 baseline/Flink/final time-travel、snapshot parent 链、最终行集、token 唯一性和对象图。

## 放行边界

本 ADR 放行 bounded 单表、单 target、单次 Spark SQL MERGE 的 provider abort 后 snapshot reconciliation。它不放行生产 HA、自动 restart、Kubernetes recovery、fencing/lease、任意时序网络分区、跨系统 exactly-once、生产 RPO/RTO/SLO、REST/Gravitino destructive-write conformance，也不覆盖 SQL UPDATE join/subquery、MERGE delete/insert、多表或通用多文件写入。

## 真实验证

入口：scripts/certify_chongqing_osm_spark_flink_sql_merge_provider_abort_recovery.py  
worker：scripts/spark_chongqing_osm_iceberg_sql_merge_auto_retry.py  
worker entrypoint：scripts/spark_chongqing_osm_iceberg_sql_merge_abort_recovery.py  
测试：data_agent/test_chongqing_osm_spark_flink_sql_merge_provider_abort_recovery.py  
报告：docs/reports/chongqing_osm_spark_flink_sql_merge_provider_abort_recovery_2026-08-24.json  
报告 SHA-256：f21b14eeb64449b24395139841d45bbbf6a67fa88df4112aff21741eb2771e20

报告中的关键事实：provider_container_killed=true、reconciliation_status=committed_unacknowledged、最终 snapshot 数量为 3、marker snapshot 为 current snapshot、reconciliation 未新增 snapshot、最终 commit token 只出现一次，且主 SourceSync 计数保持 [0,0,0]。
