# ADR-113: Partition-replace Update Conflict Isolation

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-112 已证明无分区 copy-on-write 表上的 key delete 可以拒绝同 key Flink insert，但尚未覆盖目标行已
存在、表按业务键分区时的 update。若 Spark 从 revision 1 计算更新，而 Flink 随后在同一 `road_id`
分区追加 revision 2，陈旧 Spark 直接覆盖该分区会丢失 Flink payload。

通用 Spark DataFrameWriter 不能在并发 barrier 前证明 overwrite transaction 已绑定读取 snapshot；通用
SQL `UPDATE/MERGE` 还会引入 delete file、merge-on-read 和匹配语义。本阶段只验证 identity-key 分区的
受控 partition-replace update，不把它扩张为通用行级 mutation 能力。

## Decision

`identity(road_id)`、Iceberg format v2、copy-on-write 表的受治理 partition-replace update 使用两段式协议：

- 冲突授权阶段建立 Iceberg `OverwriteFiles` intent，使用目标 key row filter、
  `validateFromSnapshot(baseline)`、相同 conflict filter、`validateNoConflictingData()` 和
  `validateNoConflictingDeletes()`；intent 冻结 baseline snapshot、目标 `road_id`、预期陈旧内容 hash 和
  update token，不把 DataFrame 已完成计算等同于 provider authorization；
- Flink 在同一 `road_id` 分区追加 revision 2 并推进 JDBC Catalog 后，才允许 Spark 提交该陈旧 intent。
  provider 必须返回 `ValidationException`，不得产生 Spark snapshot/token，revision 1 和 2 必须同时可读；
- 冲突后的 retry 是新运行。它必须重新读取精确 Flink snapshot，选择最新 revision 2 payload，生成
  revision 3，并通过 `overwritePartitions()` 只替换目标分区；
- revision 3 必须保留 Flink 的道路名称和 geometry hash。两个非目标道路分区、baseline time travel 和
  Flink 后状态 time travel 均不得变化；
- reject 和 retry 都不推进 SourceSync，也不创建 `DataProductVersion`。

该版本矩阵的 Flink 1.19.3 + Iceberg 1.7.2 partition fanout writer 在关闭 Parquet writer 时仍访问 Hadoop
configuration。隔离验收集群显式设置 `classloader.check-leaked-classloader: false`；该 override 必须作为
runtime evidence 暴露，不能静默推广到共享或生产集群。

## Considered Options

- **直接 `overwritePartitions()` 提交陈旧结果**：transaction 建立时点不可审计，可能在 Flink 后状态上
  静默覆盖，不采用。
- **把 revision 2 当冲突后最终状态**：没有完成原 update 目标，也无法证明 fresh retry，不能放行。
- **snapshot-bound conflict authorization + fresh partition replacement**：provider 负责原子冲突拒绝，
  retry 明确吸收竞争 writer payload，并把变更限制在一个分区，采用该方案。
- **改用 Snappy 绕过 classloader 问题**：真实负向运行证明 Snappy 与 Zstd 都触发相同 Hadoop
  configuration 生命周期问题，因此不把 codec 变化冒充根因修复。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_update_conflict.py` 调用
`scripts/spark_chongqing_osm_iceberg_update_conflict.py` 和 ADR-110 冻结的 Flink append job。输入绑定重庆
OSM 道路 `v1.2.0` 的 50,366 行 Silver GeoParquet；源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`。

Spark 创建三行、三个 `road_id` identity partition 的 baseline snapshot `5125053196470084126`。目标道路
`102262017` 的 revision 1 已存在。Flink 对同 key 追加带新名称 payload 的 revision 2，形成 child
snapshot `6552403297174906855`。释放 Spark 后得到 `ValidationException`；陈旧 update 没有 snapshot，
Spark token 为 0，revision 1/2 均可读，catalog metadata 保持 Flink child。

独立 Spark retry 从 Flink snapshot 重读，在保留 Flink 名称和 geometry hash 后生成 revision 3，并只替换
目标分区，形成 overwrite snapshot `1241786455542081258`。最终仍是三个唯一 road ID，两个非目标分区
不变，内容 SHA-256 为 `5f2a978e994d715e522c9d77123947d02567be9adb38da520eada1bc548233ca`：

```text
5125053196470084126
  -> 6552403297174906855  # Flink appends revision 2 in the target partition
  -> 1241786455542081258  # Spark fresh-state partition replacement to revision 3
```

12 项顶层门、4 项 baseline 门、9 项冲突门、6 项 retry 门和 9 项独立回读门全部通过。MinIO 实际形成
3 个 metadata JSON、8 个 manifest/list AVRO 和 5 个 Parquet，共 16 个对象；inventory manifest
SHA-256 为 `53e08b7a4daed6fcf25c76a586c6c1639da972a2f3783dbfa5b155d0e020158f`。16 个对象、
Spark/Flink/Catalog 容器和工作目录均已删除，主库三张 SourceSync 表保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-update-conflict-report.json`，SHA-256
`a1f1ca87aad779493dfb8bab6a1c4e0469b20c6f4aa62cd51f814fe62bb4ddce`。

## Consequences

- 当前冻结版本矩阵可声明：同一 identity-key 分区发生 Flink revision append 时，陈旧 Spark
  partition-replace update fail closed；fresh retry 吸收 Flink payload 且不损失非目标分区。
- destructive-write adapter 必须记录 baseline、target filter、provider validation、retry source
  snapshot、partition spec、revision 选择规则和 commit token；最终 job success 不能替代这些证据。
- 当前 Flink classloader override 是明确的 production blocker。升级版本或移除 override 后必须重新执行
  partitioned writer 回归，不能将本地隔离验收直接映射为生产 Flink/K8s 配置。
- 本证据不覆盖通用 SQL `UPDATE/MERGE`、equality/position delete、merge-on-read、partition evolution、
  自动 retry、streaming writer、网络分区、REST/Gravitino、生产 SLO、HA 或 K8s。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO、MinIO 或 Parquet/Hadoop codec 版本变化；
- 可以移除 `classloader.check-leaked-classloader: false`，或生产 profile 需要共享 session cluster；
- update 扩展为 SQL `UPDATE/MERGE`、跨分区 key 变化、复合键、delete file 或 merge-on-read；
- retry 改为 controller 自动执行，或 SourceSync 开始消费 destructive commit；
- production profile 启用 REST/Gravitino、Kubernetes Operator、HA 或多集群 writer。
