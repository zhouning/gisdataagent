# ADR-254：Flink/Iceberg 物理故障窗口的提交不确定性对账

**状态**：Accepted（2026-08-23）  
**关联 Roadmap**：[GIS Data Agent 总体架构 Roadmap](../roadmap.md) AR-2  
**前置决策**：[ADR-109](adr-109-flink-iceberg-cancel-and-uncertain-commit-reconciliation.md)

## 背景

ADR-109 已在真实 Flink/Iceberg/MinIO 环境证明控制面 ACK 丢失时，可以依靠独立 Spark
time-travel probe 找回唯一终态 snapshot，并让 SourceSync 只推进一次。它没有证明 provider
运行时真的被杀死或从网络中移除时，控制面仍然不会猜测提交结果。

这两个窗口的风险不同于普通作业失败：Flink 可能已经完成 Iceberg snapshot，但进程在返回结果
前死亡；也可能在 catalog/object store 请求完成后失去网络。重试 provider 会产生重复 snapshot，
直接推进 cursor 又可能把未提交的数据当成已提交。

## 决策

在既有 reconciliation contract 上增加真实物理故障验收 profile，不改变控制面权威：

1. `scripts/certify_chongqing_osm_flink_iceberg_reconciliation.py` 增加
   `--fault-mode ack-loss|kill|network`。默认 `ack-loss` 保持 ADR-109 的行为。
2. `kill` profile 使用 Docker `SIGKILL` 终止运行 Flink provider container；`network` profile
   使用 Docker `network disconnect` 将同一 provider 从真实 catalog/object-store 网络移除。
   两者都只在 source 已发出四条事件、且日志观察到 offset `4` 的 completed checkpoint 后注入，
   因此故障发生在可观测的提交不确定窗口，而不是人为伪造 provider 结果。
3. 控制面在故障注入前保持 SourceSync checkpoint `0` 和零 commit。故障后由独立 Spark runtime
   读取每个 Iceberg snapshot，按 commit token、parent、operation、行数和内容 SHA-256 找出唯一
   终态；不得以 Flink client 的退出码或日志单独作为提交证明。
4. 唯一终态命中时返回 `committed_unacknowledged`，原子推进 SourceSync `0 -> 1`；重放通过
   source-slice preflight 命中既有 commit，禁止再次调用 provider，第二次 probe 的 snapshot
   列表和内容 hash 必须完全相同。所有不完整、冲突或多终态证据继续 fail closed。
5. 物理故障只证明 bounded isolated runtime 的 reconciliation；不自动宣称 Flink HA、自动
   restart、fencing、Kubernetes recovery、生产 RPO/RTO 或跨系统 exactly-once。

## 取舍

| 方案 | 结果 | 取舍 |
|---|---|---|
| 只模拟“ACK 丢失” | 保留 ADR-109 的稳定性 | 无法证明 provider 进程/网络真的失效 |
| 在提交前随机杀死作业 | 能覆盖更多时序 | 不能稳定区分未提交与提交已发生，证据难以复核 |
| 在终态 checkpoint 后注入容器故障并独立读 snapshot | 结果可重复、故障边界和控制面合同清晰 | 仍是单表、单并行度、disposable runtime，未覆盖生产 HA |

## 真实验证

两个 profile 使用同一真实重庆 OSM source slice（50,366 个源要素，四条选定道路事件），同一
Spark 3.5/Iceberg 1.6.1、Flink 1.19.3/Iceberg 1.7.2、MinIO S3FileIO 和随机 JDBC catalog。

### `kill` profile

- 报告：`.tmp/source-sync-certification/chongqing-osm-flink-iceberg-kill-reconciliation-report.json`
- 文件 SHA-256：`b5dcfcdb5de0a06dbe8c54429ba5b3fca09ddf7aaf2e8507ac86f701877bd936`
- 物理证据：container `Running=false`、退出码 `137`、signal `KILL`。
- 独立 snapshot：唯一终态 `committed_unacknowledged`；重放为 `already_recorded`，无第二个
  snapshot。

### `network` profile

- 报告：`.tmp/source-sync-certification/chongqing-osm-flink-iceberg-network-reconciliation-report.json`
- 文件 SHA-256：`a1f3dc7c157dc764d3f47d3783cddd026a01c9edcf64b2d4a923ca42d09eb58d`
- 物理证据：provider container 从 `gisdataagent_agent-net` 移除，网络成员检查为 false。
- 独立 snapshot：唯一终态 `committed_unacknowledged`；重放为 `already_recorded`，无第二个
  snapshot。

两份报告的所有顶层门均通过，包含 checkpoint 前 cancel 未推进、故障后控制面未确认、snapshot
精确对账、SourceSync exactly-once、DataProductVersion 未发布和对象/容器/数据库/工作目录清理。

## 放行边界

本 ADR 放行：单表、单并行度、单 source slice，在终态 checkpoint 后发生容器 SIGKILL 或 Docker
网络断开时的 fail-closed snapshot reconciliation 和 SourceSync 幂等推进。

仍未放行：生产 Flink HA/restart、自动 fencing/lease、Kubernetes controller、任意时序网络分区、
catalog/object-store 双故障、跨区域恢复、RPO/RTO、跨引擎并发 exactly-once、通用 SQL
UPDATE/MERGE 冲突隔离，以及生产 SLO/Incident 自动化。

