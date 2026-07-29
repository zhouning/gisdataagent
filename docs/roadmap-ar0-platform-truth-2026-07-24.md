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
6. 单元测试、PostgreSQL 集成验证和 CI 门禁；
7. 结构写入权收敛到 K8s Job、Compose 一次性 service 和 CLI；应用/MCP 启动仅只读验证，Web/普通 worker 不再获得管理员数据库凭据。

2026-07-26 本地 Docker Desktop kind 证据：双节点集群中的 App/Outbox 新 Pod 均就绪且零重启，容器管理员数据库变量为空，应用以普通角色读取 migration ledger 并得到 97/97 `in_sync`；启动日志无 `must be owner of table`，外部 `/health`、`/ready` 均通过。该结果只证明本地部署合同，staging 的独立凭据、升级与故障注入验收仍未完成。

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

### 4.7 本地 authority 与 mainline 治理闭环（staging 待接入）

下一块把 adapter POC 接到地类图斑 golden slice 的真实控制链，而不是再接第二套外部平台：

1. 已建立 authenticated workload SubjectContext、profile workload/evaluator identity 和资源级 PolicyDecision/Approval evidence gate：Run 提交期校验证据引用，DolphinScheduler dispatch 前再次按真实时钟 fail closed，授权失败不调用 provider、不改变 Run；真实 IAM/OIDC、service token provisioning/轮换与 provider 侧最小权限仍待 staging；
2. 已将 DolphinSchedulerDefinitionBinding 持久化为现有 append-only Artifact 的 `execution_plan` 角色：稳定 UUID、版本化 manifest、canonical hash/size 和 definition ResourceVersion 关联均受校验；dispatch/reconcile/cancel 可通过 tenant-scoped gateway 读取 artifact UUID，不新增 binding registry；
3. 已以 tenant-scoped PostgreSQL command outbox 和 authenticated callback 建立耐久 dispatch/reconcile 触发：Run+dispatch、callback observation+reconcile 分别同事务提交，claim 使用 lease/`SKIP LOCKED`，薄 consumer 只调用 adapter；新增 tenant-scoped managed worker（见 [ADR-027](architecture-decisions/adr-027-managed-dolphinscheduler-command-worker.md)），负责严格配置、0600 token 文件、优雅退出、可中断轮询和脱敏 health projection；Kustomize base 已登记默认零副本的 Deployment，并以 CI validator 固定独立 Secret、Pod UID、探针和 NetworkPolicy；staging activation preflight 进一步固定单副本首发、immutable digest、HTTPS provider、ConfigMap fingerprint 和新鲜 Secret key attestation，但仍未在 staging 扩容运行、配置真实 provider callback 或验证告警 SLO；
4. 已新增 immutable QualityResult、content-bound RunSuccessEvidence 和数据库 evidence gate：通用 transition 不能写 `succeeded`；只有精确 workload、DolphinScheduler success observation、内容匹配的 output Artifact、独立 passed QualityResult/evidence 和 input-to-output LineageEvent 完整时才能幂等终结 Run；见 [ADR-026](architecture-decisions/adr-026-evidence-gated-run-success.md)；
5. 已建立 staging candidate truth gate（见 [ADR-028](architecture-decisions/adr-028-staging-candidate-and-promotion-truth.md)）：临时 CI 环境由管理员执行 migration、普通应用角色复核 ledger，并将完整 Git SHA、本地 image ID、schema/config/runtime fingerprint 和 JUnit 汇总绑定为脱敏 evidence；candidate 固定不等于 staging deployment，旧 production 假部署 workflow 已移除并保持 fail closed；本地临时数据库与 evidence 组合已验证，GitHub Runner 尚未实际产出远端 artifact；
6. 已新增只读 live staging collector/verifier（见 [ADR-029](architecture-decisions/adr-029-live-staging-observation-boundary.md)）：通过 Kubernetes UID、Deployment/Pod/EndpointSlice、immutable registry digest、source/candidate/platform fingerprint 注解、应用角色 schema、实际 config/runtime、health/readiness 和真实 golden-slice 合同形成白名单 observation；完整 fixture 可得到 `live_staging_verified=true`，但 v1 因缺受保护 runner provenance 与 artifact attestation 固定 `production_promotion_allowed=false`。Docker Desktop 实采中 candidate、collection、97/97 schema、runtime 和 health 通过；[ADR-030](architecture-decisions/adr-030-runtime-schema-readiness-without-kubernetes-api.md) 已让 App/Outbox 直接以应用角色读取 ledger，并移除 token automount 与无关 RBAC，重采确认该项通过；开发镜像/tag、缺 revision/candidate/platform 注解、非 strict staging config 和缺真实 golden slice 仍被明确阻断；
7. 已新增公共 staging Kustomize template 与结构化 release bundle materializer（见 [ADR-031](architecture-decisions/adr-031-staging-release-bundle-materialization.md)）：Secret/本地 Ingress/Ollama Service 不进入 template，validated candidate、预期 live platform fingerprint 和 registry `@sha256:` image 被绑定到 App/Migration/Outbox/DolphinScheduler 的同一 release manifest；任意容器 tag、敏感 ConfigMap/inline env、本地模型 endpoint、hostPath、token automount 和多副本 App 均 fail closed。`bundle_ready` 固定不等于 registry provenance、staging deployment 或 production promotion；基础设施镜像尚未全部 pin digest，因此仍没有可 apply 的真实 registry bundle；
8. 已建立单次 application candidate build 到 GHCR subject 的发布合同（见 [ADR-032](architecture-decisions/adr-032-ghcr-candidate-provenance.md)）：同一 source revision、本地 image ID、candidate fingerprint、受保护 repository 与远端 raw manifest `sha256` 被结构化绑定，并由 GitHub OIDC provenance action 对 registry subject 请求 attestation；registry evidence 仍固定不自证 attestation、deployment 或 promotion。分支切换曾触发一次 publisher，但已在依赖安装阶段取消，凭据生成、登录、build/push 和 attestation 均未执行，因此仍没有真实 GHCR subject；
9. 已新增独立受保护 provenance verifier（见 [ADR-033](architecture-decisions/adr-033-protected-staging-provenance-verification.md)）：只接受本仓库 `main` 上成功的手工 publisher run，以 repository、signer workflow/digest、source ref/digest、GitHub OIDC issuer、SLSA v1 和 GitHub-hosted runner 固定策略执行 `gh attestation verify`；verified subject 与 candidate/registry fingerprint 绑定，结果自身再 attested，同时仍固定不等于 staging deployment 或 production promotion。[ADR-034](architecture-decisions/adr-034-attested-provenance-release-materialization.md) 进一步区分 publisher `head_sha` 与 verifier `GITHUB_SHA`，verifier 从自身受保护 revision 执行代码并在 evidence 中同时绑定两个 SHA；代码、合成 evidence、protected environment 和 reviewer gate 已配置，但尚无成功 publisher、真实 GHCR subject 或 verifier evidence；
10. 已新增 attested provenance release gate（见 ADR-034）：先按 verifier workflow/revision、main ref、GitHub OIDC、hosted runner 和本地文件 digest 验证 `provenance.json` 自身的 artifact attestation，再校验 provenance/candidate/registry fingerprint，并只允许从 provenance 取得 application image，最后复用 Secret-free bundle materializer；合成链可得到 `verified_for_staging_apply` 和 `registry_digest_verified=true`，但仍固定不等于 apply、live staging 或 production promotion。当前没有受保护环境 overlay、真实 Secret/endpoint、全部基础设施 image digest 和 cluster identity，因此没有新增会伪装可运行状态的 apply workflow；
11. [ADR-035](architecture-decisions/adr-035-github-mainline-history-recovery.md) 已由 owner 接受并执行：旧 `main@f339e13` 由 legacy/archive branch 和 annotated tag 保留，active lineage 通过两个有共同祖先且 required CI 全绿的 PR 提升为 canonical `main@0182406`；default branch、三组 active ruleset 和 `staging-provenance` protected environment 已复核，未使用 force push、unrelated-history merge 或历史重写；
12. canonical mainline 恢复已完成，但首次成功 publisher/verifier run 尚未完成；后续仍须以真实 artifact attestation 运行 release gate，在同一真实 staging 场景跑通 PlatformGateway PostgreSQL、DolphinScheduler 独立 metadata PostgreSQL、托管 outbox worker/callback 和真实 Artifact/Quality/Lineage 终局裁决；部署前为每个 worker process/Pod 分配唯一 worker ID，并验证 status projection、lease 接管和重启 drain，同时对 release/live evidence artifact 做 provenance/attestation；
13. 注入提交超时、callback 重复/乱序、worker 重启、双租户访问、凭据轮换和无双写恢复故障；
14. 验证 schedule、complement/backfill、备份恢复、升级和 master/worker failover 后，再判断 AR-1 是否达到退出门。

Temporal 继续保持目标组件状态，不在这一包并行接入。OpenMetadata/Gravitino 已从 4.8 的只读 M1 合同进入 ADR-037 的本地 M2a foundation sandbox；这仍不是已部署生产权威。

当前完成仅指本地合同、授权 evidence、outbox/callback 代码、数据库成功终局门、托管 worker 代码、默认关闭的部署模板及离线 activation/release preflight、candidate/registry/provenance/artifact-release/live observation evidence gate、合成 golden slice、定向测试、真实 PostgreSQL 16 事务边界和 canonical mainline 治理。`candidate_validated`、`registry_subject_bound`、本地合成 `provenance_verified`、`ready_for_activation`、`ready_for_staging_apply`、`verified_for_staging_apply` 和本地 live collection 都不等于真实镜像已 attested 或 staging 已部署；真实 IAM/OIDC 与 service token 生命周期、首次 GHCR publish/verify、真实 provenance artifact verify、registry-backed live staging revision、worker/callback 扩容运行、golden slice staging 运行链、受保护 release/live evidence provenance、独立 DolphinScheduler metadata PostgreSQL 和真实数据终局证据仍属于 4.7 后续切片。

### 4.8 Metadata Fabric Bridge M1 + M2 + M3-9（本地 Spark/Iceberg REST 互操作已验证）

第八块回到 AR-1 的 metadata control plane，以 [ADR-036](architecture-decisions/adr-036-read-only-metadata-fabric-bridge-contract.md) 固定 OpenMetadata + Gravitino + GDA Control Ledger 的首条 table slice：

1. `MetadataFabricBinding` 将同一 tenant 的 ResourceURN、ResourceVersion UUID、content checksum、一个 OpenMetadata table ref 和至少一个 Gravitino table ref 绑定为 canonical fingerprint；
2. GDA Resource 必须保存完全一致的 governance/technical refs，bridge 不按名称猜测 identity，不生成 ResourceVersion，也不连接旧目录执行 backfill；
3. OpenMetadata `1.13.1` 与 Gravitino `1.3.x` 使用固定 HTTPS `/api` profile；客户端只暴露官方 table GET 和 Gravitino version GET，不提供 mutation；
4. reconciliation 校验删除态、owner、GDA identity、provider revision、重复/缺失 ref 和 snapshot hash；任一漂移输出 `blocked`，provider success 不改变 GDA 真值；
5. provider payload 中出现 secret-bearing 字段时 fail closed，token 不进入 report 或 exception；
6. 地类图斑合成 ResourceVersion 的 binding/reconciliation fingerprint 已冻结，24 个定向测试与 required CI validator 覆盖正向 replay、双租户和 authority/security 负例。
7. [ADR-037](architecture-decisions/adr-037-local-metadata-fabric-foundation-sandbox.md) 已在两节点 ARM64 Docker Desktop Kubernetes 中运行 OpenMetadata `1.13.1`、Gravitino `1.3.0`、两个独立 PostgreSQL 和 OpenSearch；三块 PVC、五个专用 ServiceAccount、ClusterIP-only Service、无 token mount 与外部 Secret 边界均进入静态合同；
8. Secret-free live collector 已验证固定 provider version/revision、176/39 张 PostgreSQL 表、78 个 OpenSearch 索引、三块 PVC identity 和五个 Pod 的受控替换；最终 evidence fingerprint 为 `ac21ee50ba3c1f27f949420cc7e4483963714b6b955bb0157eca1dd39cf102c3`。
9. [ADR-038](architecture-decisions/adr-038-local-metadata-fabric-recovery-rehearsal.md) 已将两个 PostgreSQL custom dump 和 OpenSearch native snapshot 恢复到独立临时 namespace 的三块新 PVC，验证 176/39 张表的 table/row/sequence/extension fingerprints 与 79 个索引的 name/document fingerprints，恢复 source availability 并清理临时资源；repository-backed 复测 evidence fingerprint 为 `da1214294045f8b0abe2e2775b81ef33967eac9ab0e97055ae80212ac0c08a4b`。
10. [ADR-039](architecture-decisions/adr-039-local-locked-metadata-backup-repository.md) 已在独立 namespace/PVC 的 MinIO bucket 启用 versioning 与 Object Lock，将三份真实 artifact 上传并取得 version ID/retention，确认 retained version 删除被拒绝，删除本地副本后按 version 下载并完成 ADR-038 恢复；repository evidence fingerprint 为 `2897f9e6aaae21fb366da0b72edea5cf072d5b2c1aeac0807d263bd0a5f5f133`。
11. [ADR-040](architecture-decisions/adr-040-local-cross-cluster-metadata-recovery.md) 已将 source 固定为 `docker-desktop`、recovery 固定为独立 `kind-gda-metadata-recovery`，从两个 Kubernetes cluster 外的 Docker-host MinIO 以 `COMPLIANCE/1 day`、独立 writer/reader、按 version 下载完成三存储恢复；evidence fingerprint 为 `9eaf8cec9ec2d3763260c271c0c27c1c3251717820d38aadfef0bec7d7a574a8`，且只证明同一 Docker Desktop 主机内的双集群恢复。
12. [ADR-041](architecture-decisions/adr-041-local-provider-native-metrics-evidence.md) 已通过显式 `docker-desktop` context 和短生命周期 loopback port-forward 读取 OpenMetadata Dropwizard/Prometheus 与 Gravitino Dropwizard endpoint，验证健康、连接池、HTTP 线程、JVM 和 required Prometheus family，并只提交 metric inventory/value 白名单投影；evidence fingerprint 为 `ba1ad18deedb4bcc134aa5b413e3e0c03c0b5bf931bae736adc425a8dbceeefc`，且这不是持续 scrape、OTel、告警或 SLO 证据。
13. [ADR-042](architecture-decisions/adr-042-local-ephemeral-otel-metrics-pipeline.md) 已固定 OTel Collector `0.135.0` 与 JSON Exporter `0.7.0` ARM64 digest，临时部署 11 个无 Secret/PVC/RBAC 的资源；OpenMetadata 与 Gravitino 连续两次均为 `up=1`，分别抓到 `417/5` 个 samples，两次间隔 `6.033` 秒，五个 `gda_gravitino_*` family 全部存在；port-forward 和临时资源已完整清理，provider identity 未改变，evidence fingerprint 为 `32842b77d23f23b1cb298ec649771c46bc4ce4004ea1efd311f30d5847c7dc82`。
14. [ADR-043](architecture-decisions/adr-043-local-otel-scrape-failure-recovery.md) 只将临时 Collector 的 Gravitino scrape address 从 `metadata-json-exporter:7979` 结构化替换为 `metadata-json-exporter:1`；baseline 两个 job 均 `up=1`，故障阶段 OpenMetadata 保持 `up=1/417 samples`、Gravitino 精确为 `up=0/0 samples`，恢复 checked-in 配置后重新为 `up=1/5 samples`；三个 port-forward 和 11 个临时资源已清理，provider/ConfigMap identity 未改变，evidence fingerprint 为 `c70211268b62ba2e4b78c2e6d356878d875216a4f5dd7a6b4894bbdff6460a8c`。
15. [ADR-044](architecture-decisions/adr-044-production-observability-readiness-gate.md) 已把 backend/write/query endpoint、retention、TLS/workload identity、tenant label、dashboard/alert/SLO owner、三条最小 DataSLO、通知渠道、runbook 和 protected-environment attestation 固定为 fail-closed profile；当前 profile fingerprint 为 `e3b37626a1732e37570c24fe47f21c8e2084e665fe40143ad488eb2c90ca72fc`，合同有效但 20 项外部生产输入仍 blocked，未选择或部署持续 backend，也没有真实 attestation。
16. [ADR-045](architecture-decisions/adr-045-local-cross-node-network-policy-enforcement.md) 已在 Docker Desktop 两节点 kind 集群中以固定 BusyBox digest 跨节点运行五阶段探针：baseline 双客户端连通、Ingress default-deny 双阻断、selector allow 仅授权端恢复、Egress default-deny 双阻断、DNS + server:8080 allow 后仅授权端恢复；10 个临时资源和 namespace 已清理，provider、node 与 kindnet identity 保持，evidence fingerprint 为 `22b1ebe55e47bd05fee9cc17577c4eac861031b6b5bbb6c417c4b9f1ca29d060`。该结论只适用于本地合成流量，不是 provider policy、tenant isolation 或生产 CNI 证明。
17. [ADR-046](architecture-decisions/adr-046-production-network-policy-readiness-gate.md) 已把 production cluster/Kubernetes/CNI/DNS、双向 default-deny、admission-bound workload identity、八类 workload binding、namespace-per-tenant、十条 provider API/metrics/storage/backup 流量、policy logging、owner、runbook/rollback 和 protected-environment attestation 固定为 fail-closed profile；当前 profile fingerprint 为 `686e6f476c7b36d8a837776b6f48bb42d5c3d45014ef3de7fef3a512ad4ae5d1`，合同有效但 62 项外部生产输入仍 blocked，没有选择或部署生产策略，也没有真实 attestation。
18. [ADR-047](architecture-decisions/adr-047-deterministic-metadata-fabric-ingestion-projection.md) 已将同一地类图斑 target ResourceVersion 的 output Artifact、passed QualityResult、独立 evaluator、LineageEvent、RunSuccessEvidence 和 M1 binding 合成为确定性双 provider projection plan 与 OpenLineage COMPLETE candidate；plan fingerprint 为 `a5c8ef636c03a38d0c6edaacff7d1edeba9c4b8a7f1491c493e9308257c5a94d`，相同 observation replay 为 `no_op`，任何 owner/domain/tag、Gravitino revision 或 target inventory 漂移均 blocked。该合同不含 provider mutation client，`provider_apply_authorized=false`、`writes_to_gda_control=false`、`writes_to_legacy=false`。
19. [ADR-048](architecture-decisions/adr-048-local-authorized-metadata-fabric-ingestion-replay.md) 已将同一 plan 绑定到精确 PolicyDecision、独立 ApprovalRecord 与 execution-plan Artifact，在本地 OpenMetadata/Gravitino 以 natural key 创建并 read-back；首次 apply 创建 8 个目标层级对象，第二次 replay 为 `no_op/0 mutations`，OpenMetadata provider UUID 与 binding candidate 均来自真实回读。apply plan fingerprint 为 `241cb2018c093f76378d265ab8fb617d161c1be7bd4effa6fad361e9db7522c4`，authorization fingerprint 为 `7bc8f577cbdea8d9979b2606278a52176cc2d723a6159c4e1f35ada0f5bb6db0`，evidence fingerprint 为 `3d5fb07267680520d2f03bf27f354787b7253210eb93ab85aae83d5f5a714dbe`。partial inventory 在 mutation 前 blocked，第二 provider 失败会反向补偿当前 attempt 创建的对象；binding candidate 未写 GDA Control。
20. [ADR-049](architecture-decisions/adr-049-tenant-scoped-metadata-fabric-binding-ledger.md) 已新增 migration 097 与 `PlatformGateway` binding commit/read：真实 provider refs、target/source/definition version、execution-plan、精确 PolicyDecision、独立 Approval 和 provider evidence 必须在同一 tenant 下完整匹配后才可追加。空临时 PostgreSQL 首次提交为 `created=true`、第二次精确 replay 为 `created=false`，FORCE RLS、跨租户不可见和 gateway 无 UPDATE/DELETE 均通过；binding UUID 为 `9580cd65-9fd9-5216-90a5-1fd6837e6cfb`，record SHA 为 `19bdbddedc27d2ed8a35119e8f065a47a02345f9bbd3a51075856cb9587f4176`，evidence SHA 为 `518bfed363aba34e539ada19ea1dc708bacc9eba6578ccab165d11bccfc05223`。M3-3 不调用 provider、不写 legacy，也不覆盖含 synthetic UUID 的既有 Resource。
21. [ADR-050](architecture-decisions/adr-050-idempotent-openlineage-http-delivery.md) 已新增 migration 098 与 tenant-scoped lineage outbox；Gateway 只有在 M3-3 binding、execution-plan 和完整 M3-1 source plan 精确匹配后才可 enqueue。真实 loopback HTTP 演练让接收端先提交事件再返回 503，第二次以同一 `Idempotency-Key` 重发并返回 duplicate 200；共 2 个 wire requests、1 次唯一接受、最终 2 attempts/delivered，完成项不再 claim。delivery UUID 为 `49a54408-b3a8-5843-a27d-6395c080af99`，event SHA 为 `4929e51c4126e09415a9fc1578c9401077c5d7c374294e70deeebd29c8216dd2`，evidence SHA 为 `8fa87a34a39b900df0673f11d0301c9f5155ce64ff9502125478ec59a3f0fdb6`。该结论是本地 `at_least_once_with_receiver_idempotency`，不是网络 exactly-once 或生产 receiver 证明。
22. [ADR-051](architecture-decisions/adr-051-local-openmetadata-bounded-provider-identity.md) 已在 OpenMetadata `1.13.1` 创建临时非管理员 bot，effective roles 精确为 provider 强制 `DefaultBotRole` 加项目专用 role；项目新增 policy 仅允许 `table/Create`。bot 创建/read-back 临时 table 分别返回 201/200，创建 policy 返回 403；JWT 轮换后旧值返回 401，新值返回 200，吊销后新值返回 401。table、bot、user、role、policy 与 denial probe 最终均不存在，evidence SHA 为 `61b6a3429ae948f563bfc2bd012d8b586be581704cec646fd5e74b991243f03f`。该 scoped local 结论不包含 Gravitino、OIDC、Kubernetes-to-provider identity exchange 或生产 credential delivery。
23. [ADR-052](architecture-decisions/adr-052-local-gravitino-basic-bounded-provider-identity.md) 已在隔离 Gravitino `1.3.0` namespace 启用 Basic IdP 与 authorization，bounded user 只获得 `lakehouse` 的 `USE_CATALOG` 以及 `lakehouse.published` 的 `USE_SCHEMA`/`CREATE_TABLE`；table create/read 为 200/200，越权 catalog create 为 403，密码轮换使旧值返回 401，IdP 用户删除使替换值返回 401。临时 metalake/catalog/schema/table/user/role、namespace 与 loopback port-forward 均已清理，证据 SHA 为 `f0b0de1f80f079d43318937e0a0cc151a8546e9e307bef204738b1367f9b29fd`。这只是 Gravitino Basic local POC；probe catalog 使用 memory backend，不包含 OIDC、TLS、Kubernetes-to-provider identity exchange、持久生产 catalog 或双 provider production identity。
24. [ADR-053](architecture-decisions/adr-053-production-metadata-fabric-identity-readiness-gate.md) 已将 OIDC federation、双 provider integration、digest-pinned authentication component、workload/tenant claim、Kubernetes ServiceAccount、禁止 direct bypass、short-lived token、M3-5/M3-6 精确 allow/deny contract、TLS/mTLS、持久 Gravitino catalog、tenant isolation、owner/audit/SLO/runbook 与 18 项 protected attestation check 冻结为 fail-closed profile。Gravitino `1.3.0` 镜像只发现 Basic IdP jar，因此生产只允许明确选择并证明 `custom_oidc_authenticator` 或 `identity_aware_proxy`，不假设 native OIDC。当前 profile fingerprint 为 `2e9d5cac3560b853820f923669f6794ead63bcb36a528639fc0e9539e148ee2f`，合同有效但 40 项外部输入 blocked，没有真实 attestation，全部 production identity claims 仍为 `false`。
25. [ADR-054](architecture-decisions/adr-054-local-gravitino-jdbc-catalog-restart-continuity.md) 已在隔离 namespace 中将 Gravitino Iceberg catalog metadata 落到 PostgreSQL JDBC、warehouse 落到独立 PVC，并复用 M3-6 精确 `USE_CATALOG`/`USE_SCHEMA`/`CREATE_TABLE` 角色。依次重启 PostgreSQL 与 Gravitino 后，两者 Pod UID 均变化而 StatefulSet/PVC UID 保持；同一 bounded user 重新认证并读取相同 table fingerprint，catalog create 前后均为 403，namespace/PV 完整清理。evidence fingerprint 为 `34792bb47ad71041a87adeb644439bf9b6aa3f4855cdc98782d6e3b4282bf1aa`。该结果仅证明 Docker Desktop 单集群、本地 Basic/HTTP/file warehouse 的 restart continuity，不等于 production persistent identity binding、OIDC、TLS、备份恢复、Spark/Flink conformance 或生产 ingestion。
26. [ADR-055](architecture-decisions/adr-055-local-spark-iceberg-rest-interoperability.md) 已将 Gravitino API 与 bundled Iceberg REST `1.11.0` 连接到同一 PostgreSQL JDBC catalog 和 file warehouse PVC，并在 `desktop-worker` 运行 Spark `3.5.0` + Iceberg `1.6.1`。bounded Basic user 先创建零行表且 catalog create 返回 403；Spark 经标准 `/iceberg` REST 读取该表、两次 append、增加 nullable `quality`、验证三行 current state、两个 snapshot 与 first-snapshot time travel；随后 Gravitino API 回读相同演进 schema，catalog create 仍为 403，namespace/PV 完整清理。该结果只证明本地同节点共享 RWO PVC 的 engine interoperability；Spark REST 路径仍是无认证 HTTP，cancel/reconcile/lineage、Flink、对象存储、生产身份/TLS 和完整 `spark_conformance_verified` 均未证明。

此处 M1 只证明静态合同和只读 HTTP 边界；M2a 只证明本地 live foundation 与 PVC 重挂载连续性；M2b-1/M2b-2 分别限定在同集群新 PVC 和同集群隔离 repository；M2b-3 的 `local_cross_cluster_recovery_verified=true` 只限定在 `local_same_host_distinct_kubernetes_clusters_external_s3_repository`；M2c-1/M2c-2/M2c-3 分别限定本地 provider metrics、临时双周期 OTel 和单 job scrape recovery；M2c-4/M2d-2 只证明 production observability/NetworkPolicy profile 与 attestation 合同可校验；M2d-1 只证明本地两节点 kindnet 的隔离合成流量；M3-1 的 terminal evidence 与 M3-2 的 PolicyDecision/Approval 仍是 deterministic local fixtures。M3-2 只把 projection 写入本地 provider 并证明 retained target 的单次零写入 replay；M3-3 只把该本地 evidence 对应的 binding 写入临时 GDA Control 账本；M3-4 只向无认证 loopback receiver 发送精确 candidate 并验证 503 后幂等恢复；M3-5 只证明 OpenMetadata 在 provider 强制默认 role 之上的项目新增 grant 限定为 `table/Create`，以及本地 JWT 轮换/吊销和越权拒绝；M3-6 只证明隔离 Gravitino Basic IdP 的 bounded table-create、catalog-create 拒绝、登录轮换/吊销和完整清理；M3-7 只证明 pending production identity profile、profile-bound attestation 和派生 claim 的 fail-closed 合同可校验，没有部署或证明真实身份路径；M3-8 只证明同一 Docker Desktop 集群内 Basic 用户、JDBC metadata 与 file warehouse PVC 在受控 Pod restart 后连续；M3-9 只证明 Spark 经无认证本地 Iceberg REST 在同节点共享 file warehouse PVC 上完成 read/write/schema evolution/snapshot/time travel，并由 Gravitino 回读 schema，不证明生产 failure domain、持久 identity binding、Flink 或完整 engine conformance。M3-2 ingestion 仍使用 bootstrap admin，生产持久 binding、ResourceVersion 和 legacy authority 都未写入；双 provider/生产最小权限、protected workload identity、OIDC、TLS、生产持久 catalog、tenant isolation、真实 receiver/alert/SLO、受保护 provider policy、生产 OpenLineage、生产 ingest/conformance、三项 production gate 和 `production_ready` 仍为 `false`。

## 5. 重新评估条件

出现以下任一情况时重新评估顺序和选型：

- 首个付费/生产试点明确要求特定治理或调度平台。
- 团队规模、首版期限或部署环境发生显著变化。
- 单体控制面在吞吐、隔离或恢复指标上达到已记录的瓶颈。
- 自然资源图斑链无法代表目标客户，应切换为“测绘成果智能质检”纵向试点。
