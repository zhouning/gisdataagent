# GIS Data Agent 下一代 Data Platform Roadmap（AR-0 主线）

日期：2026-07-24  
分支：`feat/ar0-platform-truth`  
基线：`origin/feat/v12-extensible-platform@ebd99f8`

## 1. 决策摘要

项目应继续推进，但短期目标不是继续增加 Agent、World Model 或独立页面，而是先把现有能力收敛为可信的数据平台底座。当前 Roadmap 的总体顺序正确：

```text
AR-0 Schema / Config / Runtime Truth
  -> AR-1 Metadata + Orchestration Control Planes
  -> AR-2 Geospatial Lakehouse Vertical Slice
  -> AR-3 Data Product Engineering
  -> AR-4 Asset / GIS Service Operations
  -> AR-5 AgentOps
  -> AR-6 MMFE
  -> AR-7 GWM
  -> AR-8 Conditional Scale / Ecosystem
```

需要调整的是 AR-1 的进入方式。OpenMetadata、OpenSearch、Gravitino、DolphinScheduler、Temporal 不应一次性全部进入主链路。先冻结平台合同与权威边界，再以 POC 和退出门决定外部系统是否进入，能避免在产品闭环形成之前承担多套控制面的运维成本。

## 2. 当前基线判断

最新主线已经具备较宽的 GIS 能力面、ArcPy MCP 集成、STAC/Iceberg 相关能力和多个专项工作流，但平台事实仍然分散：

- 数据库 migration 存在历史编号冲突，旧 runner 失败后继续启动，没有 checksum 和环境指纹。
- APScheduler、自有 TaskQueue、Spark 作业状态和 `asyncio.create_task` 并存，缺少统一运行状态合同。
- 元数据分布在 `agent_data_assets`、lineage、STAC、Iceberg 及专项 registry，尚未形成权威归属矩阵。
- Roadmap 已提出多套外部平台，但代码依赖和真实集成尚未形成可验收基线。

因此 AR-0 不是基础设施整理，而是后续所有控制面、Lakehouse 和 AgentOps 可验证的前置产品能力。

## 3. 分阶段 Roadmap

### AR-0：平台事实源（2-4 周）

交付：

- 唯一 migration ID、内容 checksum、并发锁和 fail-closed 执行。
- 遗留编号冲突的前向收敛，不改写已发布 SQL 历史。
- 将历史上只由应用 `ensure_*` 隐式创建的 migration 前置表纳入 SQL 权威链路。
- schema fingerprint、环境状态导出和环境差异报告。
- 配置项 schema、默认值、密钥边界和启动时配置快照。
- runtime inventory：所有调度器、队列、后台任务和作业状态写入点。
- System-of-Record 矩阵：资产、版本、血缘、质量、作业、权限分别由谁权威管理。

退出门：

- 空库、遗留库、重复启动和并发启动结果一致。
- 修改已执行 SQL、出现新编号冲突或迁移失败时，CI/启动/K8s Job 全部失败。
- staging 与 production 可以导出并比较 schema/config/runtime 指纹。
- 新功能不得增加未登记的元数据表或后台执行机制。

### AR-1：最小控制面（4-8 周）

交付：

- 内部统一 `AssetContract`、`LineageEvent`、`QualityResult`、`RunState` 和 `PolicyDecision`。
- Metadata Adapter：先对 OpenMetadata 做真实数据规模 POC，再决定是否成为治理权威。
- Orchestrator Adapter：保持 ADR-007 的目标职责分工，但 AR-1 首个纵向场景只引入所需的一套；DolphinScheduler 由 DataOps DAG 门触发，Temporal 由 Agent/GWMOps durable workflow 门触发。
- Gravitino 与 OpenSearch 只在统一目录/跨引擎访问或检索指标证明必要时引入。

退出门：

- 每类事实只有一个权威写入方，其他系统通过事件或适配器同步。
- 外部平台故障不导致核心资产合同失真，并有明确降级/退出路径。
- 至少一个真实工作流可从创建、调度、恢复、审计走完全链路。

### AR-2：Geospatial Lakehouse 纵向闭环（6-10 周）

默认试点采用“自然资源地类图斑 DataOps 链”：数据接入 -> CRS/几何质检 -> 标准化 -> 版本化 -> 血缘 -> Iceberg 发布 -> STAC/服务发现 -> 变更审计。它比单点 Agent 演示更能验证平台合同，也能复用现有 GIS、质量和目录能力。

退出门：

- 同一数据产品可重放、可追溯、可回滚，质量和血缘随版本发布。
- 对象存储、Iceberg、STAC 与服务层之间不存在人工复制的事实源。
- 一套生产级样本通过性能、成本、权限和灾备验收。

### AR-3 至 AR-5：产品化与运营闭环（8-16 周）

- AR-3：Data Product 模板、合同测试、SLA/SLO、发布审批和消费反馈。
- AR-4：GIS 服务生命周期、缓存/切片、依赖影响分析和退役流程。
- AR-5：Agent 评测、工具权限、预算、运行追踪、回放和人工审批。

只有当 Agent 的输入数据版本、工具调用和输出产品都可追溯时，AgentOps 才进入生产主线。

### AR-6 至 AR-8：条件式扩展

MMFE、GWM 和生态扩展继续保留为战略方向，但必须由已发布 Data Product、稳定控制面和可量化业务指标触发。它们不能再反向定义底层平台合同。

## 4. 当前开发包

### 4.1 Migration truth（已完成）

第一块可验收切片包括：

1. migration catalog 静态校验；
2. 稳定 ID 与 checksum 账本；
3. 遗留 schema ledger 前向升级；
4. SQL 失败、账本漂移和启动失败的统一退出语义；
5. schema 状态导出与跨环境比较；
6. 单元测试、PostgreSQL 集成验证和 CI 门禁。

### 4.2 Config / runtime truth（本次实现）

第二块切片包括：

1. 关键配置类型、owner、默认值、环境 profile 和密钥边界；
2. development/test 可降级、staging/production fail-closed 的启动语义；
3. `DATABASE_URL` 优先级、冲突检查与数据库调用方收敛；
4. 不含密钥的 config snapshot/fingerprint 与环境 compare；
5. 全量环境读取和后台运行原语的 AST 指纹门禁；
6. legacy/governed/ephemeral runtime inventory、owner 和替换目标；
7. [ADR-019](architecture-decisions/adr-019-configuration-and-runtime-truth.md) 与 [System-of-Record 矩阵](system-of-record-matrix-2026-07-24.md)。

OpenMetadata、Gravitino、DolphinScheduler 或 Temporal 的部署仍不进入本分支。下一步先冻结 Resource/Definition/Run/Artifact/Lineage 最小合同和首条图斑链，再用真实 POC 与退出门选择 AR-1 的最小组合。

## 5. 重新评估条件

出现以下任一情况时重新评估顺序和选型：

- 首个付费/生产试点明确要求特定治理或调度平台。
- 团队规模、首版期限或部署环境发生显著变化。
- 单体控制面在吞吐、隔离或恢复指标上达到已记录的瓶颈。
- 自然资源图斑链无法代表目标客户，应切换为“测绘成果智能质检”纵向试点。
