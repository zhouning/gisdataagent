# ADR-105: Flink Event Stream and SourceSync Certification Boundary

**Status**: Accepted
**Date**: 2026-08-02
**Related roadmap**: [GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2

## Context

ADR-104 已证明 Spark/Iceberg micro-batch 可以用统一 `SourceSyncCommit` 推进平台 checkpoint，
但 AR-2 仍缺少 Flink 的运行证据：事件时间、watermark、checkpoint、失败恢复、重复事件、迟到事件和
源端删除均未在真实 runtime 中验证。仓库本地已有 `flink:1.19.3-scala_2.12-java11`，但该官方基础
镜像只包含 SQL Client 和 filesystem connector，不包含 PyFlink、Iceberg/Flink 或 Debezium/PostgreSQL
CDC connector。

把缺失 connector 当作已有能力会制造错误的平台声明；为了一个十条事件的确定性验收立即引入 Kafka、
Debezium 和常驻 Flink 集群，又会把尚未由 freshness/SLO 证明必要的运维复杂度带入默认 Compose。

## Options Considered

| 方案 | 收益 | 代价与风险 | 决定 |
|---|---|---|---|
| 直接建设 PostgreSQL CDC -> Flink -> Iceberg | 接近完整目标链 | 需新增、锁定并认证 CDC/Iceberg connector，故障面难以归因 | 后续独立认证 |
| 使用 Flink filesystem connector 的真实事件流 | 先隔离证明 Flink 原生事件时间、checkpoint/restart 和 exactly-once 文件提交 | 不证明 log-based CDC 或 Iceberg interoperability | 采用 |
| 用 Python 模拟流处理 | 实现快 | 不提供 Flink runtime、checkpoint 或 connector 证据 | 拒绝 |

## Decision

首个 Flink 证据切片使用已发布重庆 OSM 道路 `v1.2.0` 的 Silver GeoParquet。认证器从 50,366 条真实
道路中确定性选择四条，保留道路 ID、名称和 geometry WKB SHA-256，生成不可变 insert/update/delete
事件切片。事件故意包含：

- watermark 容差内的乱序 update；
- watermark 推进后的迟到 update；
- 同 event ID 的重复 delete；
- insert、update 和 hard delete；
- completed checkpoint 后的一次主动进程内 task failure。

Java job 使用 Flink 1.19.3 DataStream API、operator state offset、event-time timer 和 side output。
source offset、去重状态和待触发事件都由 Flink checkpoint 管理；第一次 attempt 在 completed
checkpoint 后失败，fixed-delay restart 只允许一次恢复。accepted changelog 与 duplicate/late audit
分别通过 Flink `FileSink` 提交到隔离、版本化 Bronze 目录。验收器只读取已提交 part files，重建最终
road state，并把 completed checkpoint IDs、accepted/rejected manifest SHA-256、最终内容 SHA-256 和
对账计数写入 `SourceSyncCommit.target_commit_ref`。

provider 写入前必须调用 `find_source_slice_commit()`。首个 Run 未命中才执行 Flink；第二个合法 Run
命中同一 source slice 后跳过 provider，再由 SourceSync authority 返回原 commit。Flink checkpoint 是
provider evidence，平台 `SourceSyncCheckpoint` 仍是 cursor 的唯一权威。

本认证使用短生命周期本地 Docker 容器和 Flink `local` execution target，不属于 Docker Compose
常驻服务，也不运行在 Kubernetes。容器退出后自动删除；随机 PostgreSQL database、checkpoint、编译
依赖和 Bronze 目录均在核验后精确清理。

## Evidence

`scripts/certify_chongqing_osm_flink_stream.py` 使用
`scripts/flink/ChongqingOsmEventStreamJob.java` 完成真实运行。源 Silver GeoParquet 为 50,366 行、
SHA-256 `8e2f274669bf9fecc62dbadc00fd6f72b3b18c71878acdc6b363868b83a37c6f`；事件切片
SHA-256 `de849033e4454c90d6fb718dce4639beb2f5bf0222692099252fbbed463a03ec`。
runtime image ID 为 `sha256:1bf0a2e91e8640900914dfd54ed605776778b1d978257e72438547004e49c6a9`，
Java source 和编译 JAR SHA-256 分别为
`4e59278356fe088ef8df6f2d069b89e2b357daf9dc45dc969846d2ad9410d199` 与
`930450be537beb8be8f402fd60fe8ba0ac920989fd74f608b0e1c7d095abd68f`。

Flink 在 checkpoint `6`、source offset `5` 后主动失败，attempt `1` 从 offset `5` 恢复。十条输入形成
8 条唯一 accepted event、1 条 duplicate audit 和 1 条 late audit；watermark 容差内的乱序 update
进入结果，超窗 update 被隔离，两个 delete 均从最终状态移除目标，最终保留 2 条道路，内容 SHA-256
为 `2f460622b1ecbcb772d12aff9889c6368d108cc29222055ba38791860223b0d5`。

SourceSync checkpoint 从 0 精确推进到 1，仅存在一个 commit 和一次 provider write。第二个 Run 在写前
命中原 commit，未再次启动 Flink。随机数据库和工作目录已删除，主 Compose 三张 SourceSync 表前后
均为 0 行。9 项端到端门和 11 项 Flink 行为门全部通过；报告：
`.tmp/source-sync-certification/chongqing-osm-flink-report.json`，SHA-256
`f02add8a4a953712d58a2b0973fbab271c583c5182e1889ab88da750e86bc673`。

## Consequences

- 现在可以声明 Flink 1.19.3 的受控真实事件流已覆盖 checkpoint/restart、offset、watermark、迟到/乱序、
  duplicate、源端删除、exactly-once filesystem sink、对账和 SourceSync replay。
- 不声明 PostgreSQL log-based CDC、Flink/Iceberg interoperability、跨系统 exactly-once、生产吞吐/
  freshness SLO、多集群 HA 或 Kubernetes runtime 已完成。
- 默认 Compose 不新增常驻 Flink、Kafka 或 Debezium 服务；生产 workload 和 SLO 证明需要持续 runtime
  后再冻结部署 profile。
- 下一项 connector 认证应固定 PostgreSQL CDC 和 Iceberg/Flink 的准确版本矩阵，并复用本 ADR 的同一
  source-slice、checkpoint、failure 和 SourceSync evidence contract。

## Revisit Triggers

- 代表生产 source 要求 log-based CDC，而 filesystem event slice 无法满足 freshness 或 delete 语义；
- Flink/Iceberg connector 版本矩阵完成兼容性、schema evolution 和 recovery 认证；
- 持续任务的可用性或恢复 SLO 要求 session/application cluster、Kubernetes HA 或外部 state backend。
