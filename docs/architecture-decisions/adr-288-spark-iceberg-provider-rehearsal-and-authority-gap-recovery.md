# ADR-288：Spark/Iceberg provider 真实重放与控制面 authority gap 对账

**状态**：Accepted（bounded disposable provider rehearsal，2026-08-25）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-3  
**前置决策**：[ADR-197](adr-197-bound-duckdb-blueprint-provider.md)、[ADR-198](adr-198-managed-duckdb-blueprint-command-worker.md)、[ADR-201](adr-201-duckdb-spatial-blueprint-conformance.md)

## 背景

Blueprint 和跨存储 projection 已经有 Spark/Iceberg provider、固定 worker 和 receipt 合同，但此前
roadmap 仍把 Spark provider 记作未完成，缺少一份完整的真实后端 rehearsal 证据。需要验证 provider
不只会写表，还能在控制面 authority 暂时没有 checkpoint 时恢复 provider receipt，并对 stale plan、重复
snapshot、checkpoint 和 delete 行为保持 fail-closed。

## 决策

沿用既有 `DockerSparkIcebergProjectionProvider`、`LakehouseProjectionRepairExecutor` 和
`PostgresProjectionCheckpointAuthority`，在隔离的 Spark 3.5/Iceberg 1.6.1、MinIO 和临时 PostgreSQL
数据库中执行完整 bounded rehearsal：

1. 使用真实 `heping_changed_parcels.geojson`，物化 445 个 feature、439 个 distinct parcel 的 Iceberg 表。
2. 先让 Spark provider 完成 rebuild，再模拟 provider 已提交但 authority 尚未写入的窗口；重启 executor
   后必须通过 provider receipt replay 恢复同一个 snapshot/commit ref，并只创建一次 checkpoint。
3. 对同内容但不同 idempotency key 的新 snapshot、stale predecessor、checkpoint-only action 和 delete
   分别验证冲突隔离、无重复 mutation、顺序 checkpoint 与 tombstone/receipt 对账。
4. rehearsal 结束必须删除临时 PostgreSQL database、MinIO bucket/container/volume/network；报告明确
   `technical_baseline_unreviewed` 和 `assisted_precheck_not_for_production_decision`，不把该切片升级为生产 SLO。

## 真实结果

- 18 项检查全部通过：真实 Spark/Iceberg rebuild、snapshot receipt、authority-gap replay、幂等 replay、
  same-content 新 snapshot 冲突、stale predecessor fail-closed、checkpoint-only recheck、delete receipt
  replay 和顺序 checkpoint history 均通过。
- Spark image 为 `gisdataagent/mmfe-spark-runtime:local`，image ID 为
  `sha256:f201367640c7583add224796a629150e63d3859ddd7fe9fd47741662a6d415bb`；MinIO image ID 为
  `sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e`。
- 445 个 feature、439 个 distinct parcel 的真实数据字节和 table content fingerprint 均被绑定；临时
  database、bucket、container、volume、network 均清理成功。

## 真实验证

入口：`python -m data_agent.lakehouse_projection_executor_rehearsal`  
真实测试：`data_agent/test_cross_store_projection_compensation_lakehouse_adapter.py::test_real_spark_iceberg_container_mutation_receipt_and_replay`  
报告：`docs/reports/lakehouse_projection_spark_provider_rehearsal_2026-08-25.json`  
报告 SHA-256：`6ef9bfb71170e179cd5c102d875412e1f3e20992f484c8fbad49cedcffe634b7`  
报告内部 fingerprint：`8b5b8afddd43af7dd63a5aed2b3cb2fbf7f2c0aa1c25d786934efca522787156`

## 放行边界

本 ADR 放行：隔离 disposable profile 中 Spark/Iceberg provider 的真实 rebuild、receipt replay、checkpoint
authority-gap recovery、幂等 mutation 和 delete/tombstone 对账。

仍未放行：生产 Spark 集群、DolphinScheduler/Temporal 长任务编排、mid-query lease heartbeat、cancel/reconcile
生产语义、multi-replica HA、NetworkPolicy 实际执行、identity rotation、容量/SLO、staging/production rollout，
以及 Spark/Sedona/Flink/PostGIS/DuckDB 的完整跨引擎 geometry/temporal/GeoParquet conformance。
