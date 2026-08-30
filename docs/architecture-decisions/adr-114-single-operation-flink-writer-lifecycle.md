# ADR-114: Single-operation Flink Writer Lifecycle

**Status**: Accepted
**Date**: 2026-08-02
**Related decisions**: [ADR-113](adr-113-partition-replace-update-conflict-isolation.md)
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-113 首次放行 `identity(road_id)` partition-replace update，但隔离 Flink 集群需要设置
`classloader.check-leaked-classloader: false`。当时的 Flink job 在同一 `TableEnvironment` 中顺序执行
baseline `SELECT`、partitioned `INSERT` 和 final `SELECT`。第一个 query job 结束后关闭的 user-code
classloader 被后续 Iceberg partition fanout writer 的 Hadoop configuration 继续引用，Parquet writer 在
close 阶段因此触发 Flink safety-net failure。Zstd 与 Snappy 均出现同一生命周期错误，codec 不是根因。

关闭安全检查可以让该验收通过，但会隐藏共享或长生命周期集群中的真实 classloader 泄漏风险，不能作为
production profile 的默认配置。

## Decision Drivers

- Flink classloader safety check 必须保持开启；
- mutation 的 provider commit 与前后状态验证必须都有独立证据；
- 不能为了 job 内自校验而复用已经完成 query job 的 catalog/configuration 生命周期；
- 修复不得改变 ADR-113 的 snapshot-bound conflict 和 fresh-state retry 语义。

## Decision

受治理的 Flink/Iceberg 有界 mutation job 采用 single-operation lifecycle：

- writer job 只创建 catalog 并执行一次 `INSERT` mutation，不在同一 `TableEnvironment` 中执行前置或后置
  query job；
- admission controller 在启动 writer 前通过已冻结的 Spark snapshot、计划 hash 和 JDBC Catalog pointer
  验证 baseline；
- `TableResult.await()` 只证明 Flink mutation job 完成。随后必须由 JDBC Catalog 验证 parent/current
  snapshot，再由独立 Spark phase 精确回读行内容、revision、commit token 和 time travel；
- 隔离集群显式设置 `classloader.check-leaked-classloader: true`，该值写入验收报告；
- 需要多个 Flink query/mutation 的业务流程必须拆成多个 job，或为每个 operation 建立并单独认证的新
  execution/catalog lifecycle。未经认证不得通过关闭 safety check 兼容。

`ChongqingOsmIcebergPartitionAppendJob` 是该边界的首个实现。它只接收单行 revision 2 plan，打印绑定
road ID、revision 和 64 位 commit token 的 start/commit marker，不读取 baseline，也不自行声明最终表
正确。

## Considered Options

- **继续关闭 leaked-classloader check**：能够通过，但掩盖资源生命周期错误，拒绝作为 production
  默认值。
- **切换 Parquet codec**：Snappy 与 Zstd 均失败，不能解决 configuration/classloader ownership。
- **仅升级 Iceberg/Flink**：当前问题由 job 内跨 query lifecycle 复用触发；在没有兼容矩阵证据前，
  版本升级不是可证明修复。
- **single-operation writer + 独立 verification**：缩小 writer 职责，同时保留完整跨引擎证据链，采用。

## Evidence

`scripts/flink/ChongqingOsmIcebergPartitionAppendJob.java` 替代 ADR-110 的多 query append job，
`scripts/certify_chongqing_osm_spark_flink_update_conflict.py` 显式开启 safety check 后，重新执行 ADR-113 的
同一重庆 OSM 50,366 行真实数据场景。源 GeoParquet SHA-256 仍为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，目标 road ID 仍为
`102262017`，baseline、Flink 后和最终内容 hash 与首轮证据完全一致。

Flink single-operation job 的 start/commit marker 均精确绑定 revision 2 与 commit token；JDBC Catalog
随后确认 Flink child snapshot。陈旧 Spark update 仍被 `ValidationException` 拒绝，fresh retry 仍只替换
目标分区：

```text
5252205136423072678
  -> 4179295500726316257  # Flink single-operation partition append
  -> 5297156501213180690  # Spark fresh-state partition replacement
```

13 项顶层门、4 项 baseline 门、9 项冲突门、6 项 retry 门和 9 项独立回读门全部通过；新增顶层门通过
JobManager REST 观测确认 safety check 实际值为 `true`。MinIO 形成 3 个
metadata JSON、8 个 manifest/list AVRO 和 5 个 Parquet，共 16 个对象；inventory manifest SHA-256 为
`200460b504c9e9300c657641cb2dea78948a75fd9227ed9c0c0b522545dd3111`。16 个对象、全部临时容器与工作目录
均已删除，主库 SourceSync 保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-update-conflict-no-override-report.json`，SHA-256
`4ce57c0237a19e28bb9c3ff3680a2cf80eba503fa7cdda3b45b7818eae8ffd4a`。

## Consequences

- ADR-113 的 classloader override production blocker 已解除；当前受控 partition-replace update path 不再
  依赖关闭安全检查。
- writer job 的成功不等于业务正确。baseline admission、catalog pointer、独立 readback、content hash、
  token 和 time travel 仍是强制证据。
- 原 ADR-110 多 query append job 仍可用于其已认证的无分区场景，但不得直接复用于 partition fanout
  writer；通用多 query Flink job lifecycle 仍未放行。
- 本决策不证明通用 SQL `UPDATE/MERGE`、streaming checkpoint writer、网络分区、HA、K8s 或其他
  Flink/Iceberg 版本的兼容性。

## Revisit Triggers

- Flink、Iceberg、Hadoop、Parquet codec、JDBC Catalog 或 S3FileIO 版本变化；
- writer 从单次 batch mutation 扩展为多 statement、streaming、upsert/delete/merge 或 checkpoint sink；
- verification 被移入 Flink job、controller 自动 retry，或 SourceSync 开始消费 destructive commit；
- production profile 启用 session cluster、Kubernetes Operator、HA 或多集群 writer。
