# ADR-110: Spark/Flink Concurrent Iceberg Append Convergence

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-107 至 ADR-109 已依次证明 Spark/Flink 对同一 MinIO Iceberg 表的版本互操作、Flink checkpoint
恢复，以及 cancel/ack-loss 后的确定性对账，但这些运行均按 writer 串行发生。它们不能证明两个引擎
同时基于一个表状态执行 append 时，Iceberg catalog pointer 竞争是否会造成丢行、重复 commit、断裂
snapshot chain 或不可回读的中间状态。

跨引擎并发也不能作为一个笼统能力一次性放行。append 可以通过乐观提交重基收敛，而 overwrite、
delete、update 和 merge 会引入 data-file/row-level 冲突，必须分别验证冲突隔离、重试与控制面推进语义。

## Decision

接受受控单表 Spark/Flink 并发 append 作为 AR-2 已验证能力，但不把结论外推到破坏性写入。验收必须
制造可观测的真实竞争窗口，而不是依赖启动时间近似并发：

- Spark 在确认表仍指向三行 baseline snapshot 后启动 append，并在 executor 内写入 ready marker 后
  等待 release；
- ready 出现后才允许 Flink 读取同一 baseline 并提交一行，随后独立读取 JDBC Catalog，确认 pointer
  已推进到 Flink child snapshot；
- 只有上述确认完成后才释放 Spark。Spark 必须把自己的一行重基到 Flink child snapshot 上并成功提交；
- 独立 Spark verification 必须证明五行精确、road ID 唯一、两个 commit token 各出现一次、三个 append
  snapshot 形成线性 parent chain，并能 time travel 回 baseline 与 Flink 后状态；
- catalog、warehouse 和 barrier 都使用随机隔离 identity，最终清理对象、容器和工作目录；验收不得推进
  SourceSync 或创建 `DataProductVersion`。

继续使用 ADR-107 冻结的 Spark 3.5/Iceberg 1.6.1、Flink 1.19.3/Iceberg 1.7.2、PostgreSQL 16.14
`JdbcCatalog` 和 MinIO `S3FileIO`。该 runtime 是短生命周期本地 Docker，不加入默认 Compose，也不是
Kubernetes 部署。

## Considered Options

- **强制所有跨引擎写串行化**：实现简单，但会隐藏 Iceberg 乐观并发能力，也无法为后续冲突策略提供
  真实基线，因此不作为唯一方案。
- **依赖 Iceberg 文档或单元测试声明兼容**：不能证明当前版本矩阵、JDBC Catalog 和 S3FileIO 的实际
  提交顺序及对象图，予以拒绝。
- **受控 barrier 制造确定性竞争并独立回读**：可以证明精确时序、最终内容和历史状态，采用该方案。

## Evidence

`scripts/certify_chongqing_osm_spark_flink_concurrent_append.py` 调用
`scripts/spark_chongqing_osm_iceberg_concurrent_append.py` 与
`scripts/flink/ChongqingOsmIcebergConcurrentAppendJob.java` 完成真实运行。输入绑定重庆 OSM 道路
`v1.2.0` 的 50,366 行 Silver GeoParquet，源文件 SHA-256 为
`8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`，确定性选取五条道路。

Spark 建立三行 baseline snapshot `5379117650934058376` 并进入 executor barrier。Flink 追加第四行后，
JDBC Catalog pointer 已真实推进到 child snapshot `4439076645016410702`；Spark 随后获准继续，并以该
Flink snapshot 为 parent 提交第五行 snapshot `5154545790044336212`：

```text
5379117650934058376
  -> 4439076645016410702  # Flink append
  -> 5154545790044336212  # Spark rebased append
```

baseline、Flink 后状态和最终状态的内容 SHA-256 分别为
`dc4a154bcfc8cf5fb76df5e7d23d4d4456e43e207b9ca7a90092010e821b273e`、
`3f99c28995aafc9c3c08fed3cf9f9e2f4e85091bf5d68b6a0b456a7640660a4c` 和
`4a417f890b55c3d71d2dfdf5d4c5b2db85f222d4308901b1cf2ec57a36290639`。最终五行、唯一 road ID、
writer 计数、两个唯一 commit token、线性 chain 及两个历史状态 time travel 均精确通过。

9 项顶层门全部通过。MinIO 实际形成 3 个 metadata JSON、6 个 manifest/list AVRO 和 4 个 Parquet，
共 13 个对象；inventory manifest SHA-256 为
`beec2cd30e548d267e8f21a426395f2564799063b9ba4d556070c9c33bbdeb65`。13 个对象、Spark/Flink/Catalog
容器和工作目录均已删除，主库三张 SourceSync 表保持 `0/0/0`。报告：
`.tmp/source-sync-certification/chongqing-osm-spark-flink-concurrent-append-report.json`，SHA-256
`e70c5d487e5264fbdd42ac5b4f336936df1831e5392451d0f4fda9bb4034354d`。

## Consequences

- 现在可以声明当前冻结版本矩阵在受控单表 batch append 竞争中完成 Spark/Flink 乐观重基，未丢行、
  未重复 commit，并保留可回读的中间状态。
- 不能声明 overwrite、delete、update、merge 的冲突隔离或 lost-update 防护；这些操作必须通过独立
  确定性冲突验收，证明一个 writer fail closed 或安全重试，且 SourceSync/产品发布不会错误推进。
- 本证据不覆盖并发 streaming checkpoint writer、多并行度吞吐/公平性、kill -9/网络分区、跨系统
  exactly-once、REST/Gravitino catalog、生产 SLO、HA 或 Kubernetes runtime。
- AR-2 下一项跨引擎写证据聚焦 overwrite 或 merge 冲突；append convergence 不再作为未完成项。

## Revisit Triggers

- Spark、Flink、Iceberg、JDBC Catalog、S3FileIO 或 MinIO 版本变化；
- table isolation、partition/schema evolution、write distribution 或 commit retry 配置变化；
- writer 扩展为 streaming、多并行度或两个以上并发进程；
- production profile 启用 REST/Gravitino、Kubernetes Operator、HA 或多集群运行。
