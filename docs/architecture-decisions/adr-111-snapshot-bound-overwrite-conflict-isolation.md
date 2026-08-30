# ADR-111: Snapshot-bound Spark/Flink Overwrite Conflict Isolation

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-110 已证明 Spark/Flink 对同一 Iceberg 表并发 append 时可以乐观重基并收敛，但 append 不删除其他
writer 的 data file。全表 overwrite 若在读取三行 baseline 后与 Flink append 竞争，陈旧 writer 一旦按
当前表状态完成替换，就可能无声删除 Flink 新行，构成 lost update。

Spark DataFrameWriter 的 `overwrite(true)` 和 `overwritePartitions()` 不提供“在 executor barrier 前
冻结 Iceberg base snapshot”这一可审计合同。writer transaction 可能在数据任务之后才建立或刷新，因此
不能把 DataFrame 已从 baseline 计算出来等同于 overwrite commit 已绑定该 baseline。

## Decision

受治理的 Spark 破坏性写必须显式建立 snapshot-bound Iceberg transaction，不能只依赖通用
DataFrameWriter overwrite API。当前全表 overwrite adapter 使用 Iceberg 1.6.1 原生 `OverwriteFiles`：

- 从 Spark catalog 加载 Iceberg table，核对 `currentSnapshot` 与控制面冻结的 baseline snapshot；
- 在 Flink 写入前创建 `newOverwrite()`，使用 `overwriteByRowFilter(alwaysTrue)`、
  `validateFromSnapshot(baseline)`、`conflictDetectionFilter(alwaysTrue)`、
  `validateNoConflictingData()` 和 `validateNoConflictingDeletes()`；
- transaction ready 后才允许 Flink append。确认 JDBC Catalog pointer 已推进到 Flink child snapshot 后
  再调用 Spark commit；此时必须得到 Iceberg `ValidationException`，且 catalog、行内容和 Spark commit
  token 均不得变化；
- 冲突不是自动成功。只有新运行重新读取 Flink 后的 fresh state、重新计算完整替换内容并通过既有质量与
  策略门后，才允许创建新的 overwrite transaction；
- provider reject 或 retry commit 都不直接推进 SourceSync，也不能创建 `DataProductVersion`。

该决策只放行当前版本矩阵上的单表、无分区、batch 全表 overwrite 冲突隔离和一次显式 fresh-state
retry。delete、row-level update、merge、自动 retry policy 和并发 streaming writer 必须单独认证。

## Considered Options

- **直接使用 DataFrameWriter overwrite**：无法证明 transaction 在 barrier 前绑定 baseline，拒绝作为
  受治理并发边界；它仍可用于不存在并发 writer 的显式 retry 执行阶段。
- **所有 writer 依赖外部互斥锁**：只能约束服从同一锁协议的 writer，不能防止独立 Flink 或其他引擎
  修改 catalog，不能单独满足跨引擎隔离。
- **snapshot-bound Iceberg transaction + 显式 fresh-state retry**：冲突检查与 catalog commit 使用同一
  provider 协议，并保留确定性审计证据，采用该方案。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_overwrite_conflict.py` 调用
`scripts/spark_chongqing_osm_iceberg_overwrite_conflict.py` 和 ADR-110 已冻结的
`ChongqingOsmIcebergConcurrentAppendJob`。输入绑定重庆 OSM 道路 `v1.2.0` 的 50,366 行 Silver
GeoParquet；源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`。

Spark 创建三行 baseline snapshot `5155044637988858882`，并建立绑定该 snapshot 的全表 overwrite
transaction。Flink 随后追加第四行并把 catalog 推进到 snapshot `1596887077901406126`。释放 Spark 后，
Iceberg 返回 `ValidationException`；overwrite 未提交，catalog metadata location 与 SHA-256 均保持
Flink 状态，四行内容 SHA-256 为
`3f99c28995aafc9c3c08fed3cf9f9e2f4e85091bf5d68b6a0b456a7640660a4c`，Spark commit token 出现 0 次。

独立 Spark retry 先精确读取该四行状态，再更新目标道路 `102262017` 并保留 Flink 行，形成 overwrite
snapshot `1436372087137840733`。最终四行内容 SHA-256 为
`187fab0e975414cc94309f71f859d4d25fc026306e3cebc4469aa6e88bb07d2b`，Flink/Spark token 各出现一次：

```text
5155044637988858882
  -> 1596887077901406126  # Flink append
  -> 1436372087137840733  # Spark fresh-state overwrite retry
```

12 项顶层门、7 项冲突门、5 项 retry 门和 7 项独立回读门全部通过。MinIO 实际形成 3 个 metadata JSON、
8 个 manifest/list AVRO 和 5 个 Parquet，共 16 个对象；inventory manifest SHA-256 为
`91c8a971b0ccba3e52cb2c97ceb34e9e5ad59a9241af75a63100264b1c165cbc`。16 个对象、Spark/Flink/Catalog
容器和工作目录均已删除，主库三张 SourceSync 表保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-overwrite-conflict-report.json`，SHA-256
`640684c15c5c88283751b0460107af89309598fd19c9a030f01be1627881bcb3`。

## Consequences

- 现在可以声明当前冻结版本矩阵在受控单表 batch 全表 overwrite 与 Flink append 竞争时，陈旧 Spark
  writer fail closed；显式 fresh-state retry 不丢 Flink 写入，且历史状态可 time travel。
- Data Platform 的 destructive-write adapter 必须把 baseline snapshot、conflict filter、provider
  validation、retry source snapshot 和 commit token 作为审计合同，不能只记录最终 Spark job 状态。
- 冲突后没有新 snapshot，不推进 SourceSync；retry 是新的显式阶段，不冒充原 transaction 自动成功。
- 本证据不覆盖 delete、row-level update、merge、partition/schema evolution、自动 retry/fairness、并发
  streaming writer、kill -9/网络分区、REST/Gravitino、跨系统 exactly-once、生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- 表引入 partition evolution、row-level delete、merge-on-read、delete file 或 branching/tag；
- retry 从人工/显式运行改为 controller 自动执行，或 SourceSync 开始消费 destructive commit；
- production profile 启用 REST/Gravitino、Kubernetes Operator、HA 或多集群 writer。
