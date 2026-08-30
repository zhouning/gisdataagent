# ADR-255：Flink position-delete/MOR stale commit 冲突隔离

**状态**：Accepted（2026-08-23）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-120](adr-120-flink-spark-position-delete-write-interoperability.md)

## 背景

ADR-116 和 ADR-120 分别证明了 Spark 产生的 MOR position delete 可以由 Flink 读取，以及
Flink TaskManager 可以写入一个受控的 position-delete file。两份证据都是顺序单写：
如果第二个 writer 仍绑定旧 snapshot，之前没有真实证据证明 Iceberg 会拒绝它，也没有证明
失败尝试不会把未提交 delete file 留在对象存储中。

这不是普通的 SQL delete 问题。position delete 绑定 Iceberg data file 和 row position，
并发 writer 必须同时验证 baseline snapshot、被删除文件和 conflicting delete files；失败时
还要处理已经物化但尚未进入 metadata 的 provider 文件。

## 决策

在现有 ChongqingOsmIcebergPositionDeleteWriteJob 上增加仅供验收使用的 --expect-conflict 模式：

1. 第一个 Flink TaskManager job 使用真实 _file/_pos 绑定和单次 RowDelta.commit()，
   在三行无分区 format-v2 MOR 表上提交唯一 position delete。
2. 第二个 Flink TaskManager job 继续使用第一个 snapshot 之前的 baseline、同一物理文件/
   position 和不同 commit token；它跳过“当前 snapshot 必须等于 baseline”的客户端早期检查，
   让 Iceberg validateFromSnapshot、validateDeletedFiles、validateNoConflictingDataFiles
   和 validateNoConflictingDeleteFiles 决定结果。
3. 只接受 ValidationException 作为 stale conflict。writer 输出明确的 baseline/current
   snapshot、target key、stale token 和 orphan_cleanup=true marker；其它异常不算通过。
4. validation 失败后，writer 通过 table FileIO 删除刚刚物化、但未提交的 delete file。
   独立 Spark verify 必须看到只有原 data file 和第一个 committed delete file，catalog
   metadata location、snapshot count 和最终两行内容均保持不变。
5. 该切片不推进 SourceSync 或 DataProductVersion；它只认证 provider destructive-write
   conflict boundary 和失败 artifact 清理。

## 取舍

| 方案 | 结果 | 取舍 |
|---|---|---|
| 继续只认证顺序 position delete | 实现最小 | 无法证明 stale writer 的冲突隔离 |
| 用 Spark SQL DELETE 代替第二个 Flink position writer | 编排简单 | 不能证明 Flink position-delete/MOR writer 的实际合同 |
| 第二个 Flink writer 绑定旧 snapshot，并在 validation 失败后清理 orphan file | 物理 writer、Iceberg validation、catalog 和对象清理都有独立证据 | 仍是单表、单文件、单并行度 bounded profile |

## 真实验证

报告：.tmp/source-sync-certification/chongqing-osm-flink-spark-position-delete-conflict-report.json

- 文件 SHA-256：8cf105c2f3cafbff2e2df1193bc5422e86fd98f8edc648db5c926ccccebe1320
- 重庆 OSM source：50,366 个要素；三行真实 baseline，目标道路 102262020 的 position 为 1。
- 第一次 Flink commit：snapshot 1566495413450845634，parent 为 baseline 245703841079777048。
- 第二次 stale writer：baseline 仍为 245703841079777048，观察到当前 snapshot
  1566495413450845634，得到 iceberg_validation_exception；stale token 没有 snapshot，
  orphan_cleanup=true。
- 独立 Spark 回读：两行最终内容、baseline time travel、唯一 position delete file 和
  snapshot chain 全部准确；对象图为 2 个 metadata JSON、4 个 manifest/list AVRO、2 个
  Parquet。
- 16 项顶层门和清理门通过；catalog/Flink 容器、对象前缀、隔离数据库和工作目录全部清理，
  主库 SourceSync 保持 0/0/0。

正常单写回归报告：

- .tmp/source-sync-certification/chongqing-osm-flink-spark-position-delete-write-regression-report.json
- 文件 SHA-256：f53d522413274cb32b02fdb83128f04ee7223fa593cd96dea9404e43485319fd
- 原有 12 项 position-delete writer 门全部通过。

## 放行边界

本 ADR 放行：同一无分区 format-v2 MOR 表、同一 data file/row position、单并行度 Flink
position-delete writer 在 stale snapshot 下的 fail-closed 冲突拒绝和未提交 delete file 清理。

仍未放行：分区或多文件 position delete、多个并发 streaming writer、通用 SQL UPDATE/MERGE、
自动 retry/checkpoint recovery、跨系统 exactly-once、REST/Gravitino catalog、生产 HA/RPO/RTO
和 Kubernetes runtime。

