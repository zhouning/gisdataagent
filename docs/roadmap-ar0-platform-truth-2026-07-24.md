# GIS Data Agent 下一代 Data Platform Roadmap（AR-0 主线）

日期：2026-07-24  
分支：`feat/ar1-dolphinscheduler-adapter`
基线：`feat/ar1-control-gateway@de03615`

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

### 4.2 Config / runtime truth（已完成）

第二块切片包括：

1. 关键配置类型、owner、默认值、环境 profile 和密钥边界；
2. development/test 可降级、staging/production fail-closed 的启动语义；
3. `DATABASE_URL` 优先级、冲突检查与数据库调用方收敛；
4. 不含密钥的 config snapshot/fingerprint 与环境 compare；
5. 全量环境读取和后台运行原语的 AST 指纹门禁；
6. legacy/governed/ephemeral runtime inventory、owner 和替换目标；
7. [ADR-019](architecture-decisions/adr-019-configuration-and-runtime-truth.md) 与 [System-of-Record 矩阵](system-of-record-matrix-2026-07-24.md)。

### 4.3 Resource / Run / Evidence contracts（已完成）

第三块切片包括：

1. canonical `ResourceURN`、immutable `ResourceVersion` 与 Definition fingerprint；
2. `SubjectContext`、Run input binding、CAS 状态图与 append-only RunEvent；
3. provider attempt observation 与 PlatformRun 终局裁决分离；
4. stable Artifact URI/checksum 与 version-to-version LineageEvent；
5. 独立 `gda_control` schema、tenant composite FK、FORCE RLS 和 fail-closed privilege；
6. Pydantic JSON Schema/validator、PostgreSQL 回归测试与 CI 门禁；
7. [ADR-020](architecture-decisions/adr-020-platform-resource-run-and-evidence-contracts.md) 与更新后的 [System-of-Record 矩阵](system-of-record-matrix-2026-07-24.md)。

此切片没有自动回填旧资产/workflow/run/lineage 表，也没有部署 OpenMetadata、Gravitino、DolphinScheduler 或 Temporal。`gda_control` 当前是已编译、已验证但尚未接入生产调用链的控制/证据账本。

### 4.4 Legacy crosswalk / golden slice（已完成）

第四块切片包括：

1. 冻结 `agent_data_assets`、`agent_asset_versions`、`agent_workflows`、`agent_workflow_runs`、`agent_asset_lineage` 的 schema、writer 和 API marker inventory；
2. CI 扫描未登记直接写入方，新增或漂移的 legacy writer 必须先更新 inventory；
3. 以 `eligible`、`blocked`、`prohibited` 三种结果输出只读 crosswalk plan，不连接数据库、不生成 identity、不执行 backfill；
4. 旧 workflow run 永久禁止直接映射为 PlatformRun，只能在已有 PlatformRun correlation 时形成 FrameworkAttemptObservation；
5. 固定带 DLTB 标准证据的合成地类图斑输入、golden result、ResourceVersion、Definition、Run、Artifact 和 LineageEvent；
6. 固定 owner、SLO、rollback point、消费者与终局裁决条件；
7. [ADR-021](architecture-decisions/adr-021-legacy-crosswalk-and-golden-slice.md)、CI validator 与更新后的 [System-of-Record 矩阵](system-of-record-matrix-2026-07-24.md)。

此切片建立的是迁移判定与验收证据，不是生产迁移工具。五张旧表继续服务兼容调用方，`gda_control` 仍未进入生产写链路；任何真实数据迁移都必须由后续 adapter 提供 tenant、authority identity、checksum、correlation 和幂等证据。

### 4.5 AR-1 controlled write gateway（已完成）

第五块切片包括：

1. `NOLOGIN`、`NOINHERIT`、`NOBYPASSRLS` 的 `gda_control_gateway` 数据库角色和最小 `SELECT/INSERT/EXECUTE` grant；
2. transaction-local role 与 tenant context，连接池事务结束后自动复位；
3. Resource/ResourceVersion 幂等登记和 Definition bundle 原子事务；
4. PlatformRun/input 原子提交、幂等 key、读取与 CAS transition；
5. FrameworkAttemptObservation、Artifact 和 LineageEvent 幂等追加，禁止直接伪造 RunEvent；
6. 十二个 `/api/platform/v1` 路由、`platform_operator`、JWT tenant context、actor/tenant spoofing 拒绝和统一错误 envelope；
7. 静态 validator、真实 PostgreSQL 角色/服务链测试、CI 门禁、[ADR-022](architecture-decisions/adr-022-platform-control-gateway.md) 与更新后的 [System-of-Record 矩阵](system-of-record-matrix-2026-07-24.md)。

此切片证明新的受控写入口可用，但没有切换任何生产业务调用方。现有 legacy 表仍是兼容写路径，OpenMetadata、Gravitino、DolphinScheduler 和 Temporal 仍未部署或接入。生产部署还要求 migration/DBA 具备 role 管理权限、应用 login 获得 gateway role membership，并先在 staging 完成双租户和连接池复位验收。

### 4.6 DolphinScheduler correlation adapter（Sandbox POC 已完成）

第六块选择 orchestration-first，只实现 DolphinScheduler DataOps run correlation：

1. 固定 Apache DolphinScheduler `3.4.2`、API profile `3.4` 和官方路由；
2. 编译 provider-native DAG，注入稳定 definition/correlation 参数，拒绝内联 secret；
3. create 后显式 `ONLINE`，形成带 compiled hash 和 provider version 的 binding；
4. PlatformRun 在外部提交前进入 `dispatching`，timeout/网络未知结果进入 `reconciling`，禁止盲目重提；
5. instance variables 四字段精确关联；未知分页、缺失变量、扫描上限和多结果均 fail closed；
6. provider 终态只写 attempt observation 并等待平台终局裁决；
7. `STOP` 前先 CAS 到 `cancelling`，不因 provider 接受命令直接写 `cancelled`；
8. 16 个定向测试、静态 CI validator、只读 probe 和 [ADR-023](architecture-decisions/adr-023-dolphinscheduler-correlation-adapter.md)。

真实 `3.4.2` ARM64 standalone 已验证 create -> online -> start -> list -> variables -> exact correlation，Shell instance 到达 `SUCCESS`；长任务接受 `STOP` 后进入 `READY_STOP`。standalone 使用 H2 和开发身份，因此这些是 adapter HTTP/correlation 证据，不是生产部署、高可用、最终取消裁决或 AR-1 全部退出门。

### 4.7 下一开发包（本地 authority 闭环已完成，staging 待接入）

下一块把 adapter POC 接到地类图斑 golden slice 的真实控制链，而不是再接第二套外部平台：

1. 已建立 authenticated workload SubjectContext、profile workload/evaluator identity 和资源级 PolicyDecision/Approval evidence gate：Run 提交期校验证据引用，DolphinScheduler dispatch 前再次按真实时钟 fail closed，授权失败不调用 provider、不改变 Run；真实 IAM/OIDC、service token provisioning/轮换与 provider 侧最小权限仍待 staging；
2. 已将 DolphinSchedulerDefinitionBinding 持久化为现有 append-only Artifact 的 `execution_plan` 角色：稳定 UUID、版本化 manifest、canonical hash/size 和 definition ResourceVersion 关联均受校验；dispatch/reconcile/cancel 可通过 tenant-scoped gateway 读取 artifact UUID，不新增 binding registry；
3. 已以 tenant-scoped PostgreSQL command outbox 和 authenticated callback 建立耐久 dispatch/reconcile 触发：Run+dispatch、callback observation+reconcile 分别同事务提交，claim 使用 lease/`SKIP LOCKED`，薄 consumer 只调用 adapter；新增 tenant-scoped managed worker（见 [ADR-027](architecture-decisions/adr-027-managed-dolphinscheduler-command-worker.md)），负责严格配置、0600 token 文件、优雅退出、可中断轮询和脱敏 health projection；Kustomize base 已登记默认零副本的 Deployment，并以 CI validator 固定独立 Secret、Pod UID、探针和 NetworkPolicy；staging activation preflight 进一步固定单副本首发、immutable digest、HTTPS provider、ConfigMap fingerprint 和新鲜 Secret key attestation，但仍未在 staging 扩容运行、配置真实 provider callback 或验证告警 SLO；
4. 已新增 immutable QualityResult、content-bound RunSuccessEvidence 和数据库 evidence gate：通用 transition 不能写 `succeeded`；只有精确 workload、DolphinScheduler success observation、内容匹配的 output Artifact、独立 passed QualityResult/evidence 和 input-to-output LineageEvent 完整时才能幂等终结 Run；见 [ADR-026](architecture-decisions/adr-026-evidence-gated-run-success.md)；
5. 下一步在同一 staging 场景跑通 PlatformGateway PostgreSQL、DolphinScheduler 独立 metadata PostgreSQL、托管 outbox worker/callback 和真实 Artifact/Quality/Lineage 终局裁决；部署前为每个 worker process/Pod 分配唯一 worker ID，并验证 status projection、lease 接管和重启 drain；
6. 注入提交超时、callback 重复/乱序、worker 重启、双租户访问、凭据轮换和无双写恢复故障；
7. 验证 schedule、complement/backfill、备份恢复、升级和 master/worker failover 后，再判断 AR-1 是否达到退出门。

OpenMetadata/Gravitino 和 Temporal 继续保持目标组件状态，不在这一包并行接入。

当前完成仅指本地合同、授权 evidence、outbox/callback 代码、数据库成功终局门、托管 worker 代码、默认关闭的部署模板及离线 activation preflight、合成 golden slice、定向测试和真实 PostgreSQL 16 事务边界。`ready_for_activation` 不等于已部署；真实 IAM/OIDC 与 service token 生命周期、worker/callback staging 扩容运行、golden slice staging 运行链、独立 DolphinScheduler metadata PostgreSQL 和真实数据终局证据仍属于 4.7 后续切片。

## 5. 重新评估条件

出现以下任一情况时重新评估顺序和选型：

- 首个付费/生产试点明确要求特定治理或调度平台。
- 团队规模、首版期限或部署环境发生显著变化。
- 单体控制面在吞吐、隔离或恢复指标上达到已记录的瓶颈。
- 自然资源图斑链无法代表目标客户，应切换为“测绘成果智能质检”纵向试点。
