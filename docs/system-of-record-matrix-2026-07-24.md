# GIS Data Agent System-of-Record 矩阵

日期：2026-07-27

阶段：AR-0 `in_progress`；AR-1 gateway、成功终局 evidence gate、DolphinScheduler adapter sandbox POC、Metadata Fabric M1、M2a 本地 foundation/重启连续性与 M2b-1 本地三存储恢复已验证，生产切换仍 `in_progress`

适用分支：`feat/ar1-metadata-fabric-recovery-rehearsal`

## 判定规则

- **Authority**：唯一允许创建权威版本或改变生命周期状态的写入方。
- **Projection**：可重建的索引、缓存、服务视图或协议投影，不能反向覆盖权威事实。
- **Attempt observation**：Spark、Flink、ArcPy、LLM 或编排框架对一次尝试的观测，不等于平台 Run 的最终状态。
- 当前实现与目标边界分别记录；目标合同、配置存在或接口可调用都不代表已生产验证。

## 权威矩阵

| 事实域 | 当前权威/状态 | 非权威副本或投影 | 目标权威与迁移规则 | Owner | 阶段 |
|---|---|---|---|---|---|
| SQL schema 历史 | PostgreSQL `schema_migrations`，以完整 migration ID + checksum 为权威 | migration CLI 的 JSON 报告 | 保持现有 ledger；任何 drift fail closed | Data Platform | AR-0，已验证 |
| 部署配置策略 | Compose/K8s/进程环境；`platform_truth.CONFIG_SPECS` 定义关键类型与策略；DolphinScheduler worker 有默认零副本、外部 ConfigMap/Secret 驱动的 Kustomize 模板、静态 validator 和 staging activation preflight | `.env` 仅补默认；脱敏 snapshot、Secret key attestation、未扩容 Deployment 和 `ready_for_activation` 都是观测/模板 | 版本化 DeploymentProfile + secret reference；部署环境始终优先；模板或 preflight 通过都不等于环境已启用 | Platform/SRE/Security | AR-0，部分实现；worker 模板/preflight 本地已验证 |
| 环境发布与晋级 | publisher `31862363442`、protected verifier `31862984294` 与 staging deploy/observe `31863077257` 已将 `main@5fffc85`、GHCR digest、attested release、cluster/namespace identity 和 live revision 绑定；schema/config/runtime/health/rollout 通过，golden slice 缺失使 promotion fail closed | 旧 mainline、feature branch、CI artifact、JSON、离线 report、单独的 staging deployment 或人工批准都不能成为 production 发布权威 | 由受保护 environment 的 DeploymentRevision 绑定 OCI、provenance artifact、release manifest、golden slice 与全部 live verdict | Platform/SRE/Security/Repository Owner | AR-1 真实 staging 已部署 -> golden slice/production exit gates 待完成 |
| 后台运行时清单 | `platform_truth.RUNTIME_INVENTORY` 是代码层登记；`gda_control` 已有受控 PlatformRun 写入口；DolphinScheduler adapter 与 tenant-scoped managed command worker 已有代码和本地测试，但尚无生产业务调用方，多数执行状态仍分散 | AST primitive report、worker status JSON、FrameworkAttemptObservation、DolphinScheduler instance state | PlatformRun ledger 唯一登记最终状态；framework/provider attempt 只能回报观测；worker status 仅为进程健康投影 | Platform Architecture | AR-1 adapter/worker 本地已验证 -> staging 控制链待接入 |
| 原始文件/对象 | 当前 local uploads、S3/MinIO/OBS 均可能被直接写入，权威边界未统一 | 临时上传、下载缓存、预览文件 | Landing object 以 immutable URI + checksum + retention 为权威；本地 scratch 可删除 | Data Platform | AR-2 |
| 湖仓表与 snapshot | Iceberg/STAC/S3A 有局部实现，尚无通用发布权威 | STAC item、GeoParquet export | Iceberg catalog snapshot 是分析表版本权威；对象是物理内容，STAC 是发现投影 | Data Platform | AR-2 |
| 在线空间数据 | PostGIS 业务表是当前编辑/查询事实，部分临时表混入 | Martin MVT、API JSON、导出文件 | 已批准 DataProductVersion 物化到 PostGIS；不能由瓦片或临时表反向定义产品版本 | GIS/Data Platform | AR-2 -> AR-4 |
| 数据资产身份与版本 | `gda_control.resource/resource_version` 已实现 identity、hash、predecessor、tenant FK 和幂等 gateway 写入；`agent_data_assets`、`agent_asset_versions` 仍是兼容写路径 | UI catalog、search index、STAC | GDA ledger 管身份与版本绑定；旧行只有在 tenant、authority identity、checksum 和 version evidence 完整时才可形成 eligible plan；OpenMetadata 管治理目录，Gravitino 管技术对象映射 | Metadata Platform | AR-1 gateway 已验证 -> 生产切换待验收 |
| 技术元数据 | PostGIS schema、Iceberg/STAC 和专项 JSONB 各自记录；M1 已冻结 Gravitino table ref/provider revision/只读 reconciliation；M2a 已运行 Gravitino `1.3.0` + 独立 PostgreSQL，并验证本地 PVC/schema 重启连续性；M2b-1 已将 logical dump 恢复到独立新 PVC 并匹配 39 张表的 table/row/sequence/extension fingerprints，但未创建 production catalog | harvester 结果、合成 Gravitino response、本地 sandbox/recovery observation | 源系统技术对象是原始证据；Gravitino 映射并联邦，不能覆盖业务 ResourceVersion | Metadata Platform | AR-1 M1 + 本地 M2a/M2b-1 已验证 -> 生产恢复/M3 conformance 待执行 |
| 治理目录 | 当前 catalog、tag、standard、semantic registry 分散；M1 已冻结 OpenMetadata table ID/FQN/version、owner 与 GDA identity 的只读 reconciliation；M2a 已运行 OpenMetadata `1.13.1` + 独立 PostgreSQL/OpenSearch 并验证本地 PVC/schema/index 重启连续性；M2b-1 已将 PostgreSQL dump/OpenSearch snapshot 恢复到独立新 PVC 并匹配 176 张表与 79 个索引的内容 fingerprints，但未接入真实 GDA Resource | 搜索/页面视图、合成 OpenMetadata response、本地 sandbox/recovery observation | OpenMetadata 为 owner/glossary/classification/quality discoverability 权威；GDA ledger 保留审批证据 | Governance | AR-1 M1 + 本地 M2a/M2b-1 已验证 -> 生产恢复/M3 ingestion 待执行 |
| 血缘 | `gda_control.lineage_event` 已实现 immutable version edge 和幂等 gateway ingest；`agent_asset_lineage` 旧记录仍是可变 asset edge | OpenMetadata lineage graph、UI DAG | 只有 source/target ResourceVersion 与 event checksum 证据完整的旧记录可形成 eligible plan；目录图只作可重建投影 | Data Platform | AR-1 gateway 已验证 -> adapter 待接入 |
| Definition | `gda_control.platform_definition_version` 已绑定 definition ResourceVersion、完整逻辑 hash 和原子 gateway registration；3.4.2 adapter 可编译、创建并上线 provider DAG；binding 已以 append-only `execution_plan` Artifact 持久化并可按 tenant + artifact UUID 读取，旧 workflow/template/YAML 仍在写入 | 编辑器状态、DolphinScheduler DAG/definition | 旧 workflow 必须规范化并完整 hash 后才可形成 PlatformDefinitionVersion；provider binding 作为 ExecutionPlanArtifact/evidence，不可反写 definition | DataOps | AR-1 binding persistence 代码已验证 -> staging 调用链待验收 |
| Run 最终状态 | `gda_control.platform_run/event` 已实现受控 submit/read/CAS；通用 transition 已禁止 `succeeded`，专用数据库 finalizer 只接受精确 workload、DolphinScheduler success observation、内容匹配 output、独立 passed QualityResult/evidence 和 input-to-output lineage；adapter standalone API path 已验证，但端到端 staging 尚未完成，legacy 路径继续运行 | Redis progress、日志、DolphinScheduler state、attempt observation | 旧 run 到 PlatformRun 永久 prohibited；已有 PlatformRun correlation 时才可转为 observation；provider 终态只进入 `reconciling`，ledger 经证据门唯一裁决成功 | DataOps/AgentOps | AR-1 success authority 本地/PostgreSQL 已验证 -> staging/生产切换待验收 |
| 调度与补数 | APScheduler、自进化 scheduler 和调用方定时逻辑并存；DolphinScheduler POC 只验证 manual start/list/variables/STOP | UI schedule 列表 | DolphinScheduler 管 DataOps schedule/complement；Temporal 只管需要 durable signal/compensation 的 Agent/GWM workflow | DataOps/AgentOps | AR-1 manual correlation 已验证；schedule/complement/failover 待验收 |
| 事件交付 | Standards outbox 已数据库耐久；`gda_control.platform_command_outbox` 已为 DolphinScheduler dispatch/reconcile 提供 tenant RLS、lease claim、幂等 callback、薄 consumer library 和 managed worker process；其他 WebSocket/bot/feedback 多为 best effort | command delivery status、消费者 claim、worker status JSON、WebSocket 消息 | command/event 与源事实同事务入 outbox，幂等 consumer 交付；worker status、outbox 状态、缓存或 socket 都不是 Run/业务权威 | Platform/Integrations | AR-1 command delivery/worker 代码已验证 -> staging worker/callback 待部署 |
| 质量结果 | `gda_control.quality_result` 已提供 tenant RLS、append-only gateway 写入，绑定 Run、output ResourceVersion、rule version、verdict、metrics、evidence Artifact 和独立 evaluator；standards、QC、MMFE 专项结果仍未迁移 | dashboard、OpenMetadata quality summary | GDA ledger 保存产品终局所需的不可变 verdict/evidence；OpenMetadata 与 UI 只作可重建发现投影；旧结果缺稳定版本和证据时不得升级为终局依据 | Governance/DataOps | AR-1 最小成功证据已验证 -> 真实规则/staging 待接入 |
| 标准与语义定义 | `std_*`、semantic registry 和 YAML 共同存在，生命周期未统一 | prompt/context、搜索索引 | 版本化 Standard/SemanticDefinition 经审批后为权威；Agent context 只消费批准版本 | Governance | AR-1 -> AR-3 |
| 身份与权限 | Chainlit user 可显式绑定 tenant；versioned API 从认证 principal 派生 SubjectContext；`gda_control_gateway` 是 non-login/non-bypass 最小权限角色；Run 可引用强类型 PolicyDecision/Approval Artifact，DolphinScheduler dispatch 已绑定配置的 workload/evaluator 并在 provider 调用前校验证据 | session/cache、前端菜单权限、provider token profile | IdP/workload identity 提供真实 service identity；PolicyDecision/Approval 继续绑定不可变资源与 execution plan；完成 OIDC/IAM provisioning、轮换、吊销和 provider 最小权限后才能生产切换 | Security | AR-1 dispatch authorization 代码已验证 -> staging IAM 待验收 |
| GIS 服务定义与 active revision | Martin、REST/MVT/STAC endpoints 和配置直接暴露 | Ingress、tile cache、客户端图层 | GIS Service Control Plane 管 Service/Layer/Style/TMS/DeploymentRevision；provider/Gateway 仅执行 | GIS Platform | AR-4 |
| 缓存与进度 | Redis、进程内 dict/task map | UI progress、tile/context cache | 永不作为资产、Run、workflow 或产品权威；丢失后必须从 ledger/provider 重建 | SRE/Platform | 持续约束 |
| Agent/Prompt/Model bundle | 多个 registry 与 YAML 存在，尚无统一 deployment revision | trace、eval dashboard | AgentSpecBundle + EvaluationBinding + DeploymentRevision；只消费已发布 DataProductVersion | AgentOps | AR-5 |
| Trace、反馈与成本 | OTel、feedback、token/cost 表局部存在 | 聚合指标与报表 | 不可变 observation 绑定 AgentRun/ToolCall；在线 verdict/incident 决定晋级或回滚 | AgentOps/SRE | AR-5 |
| MMFE/GWM 产物 | 专项文件、表和 registry 并存 | 可视化、报告、Agent 上下文 | 作为已发布 DataProductVersion 的消费者/生产者；不得反向定义 Raw 或治理事实 | Data for AI/GWM | AR-6/AR-7 |

## 当前强制边界

1. Redis、进程内 task、WebSocket、MVT、STAC、搜索索引和 UI 状态都不能成为最终事实源。
2. 一个 provider 返回 success 只形成 attempt observation；通用 transition 不能写 `succeeded`，必须由数据库 finalizer 验证 output hash、独立 passed QualityResult/evidence 和 input-to-output lineage。
3. OpenMetadata、Gravitino、DolphinScheduler 和 Temporal 在完整真实 POC/退出门前不得写成当前生产权威；OpenMetadata/Gravitino 的 M2a foundation 与 M2b-1 同集群恢复只证明本地单副本 live/PVC/逻辑恢复，不改变此边界。
4. 新增 registry、metadata table、queue、scheduler 或后台任务前，必须先更新本矩阵、runtime inventory、owner 和迁移/恢复策略。
5. 自然资源地类图斑纵向链是首个验证载体：其 input checksum、标准版本、DataProductVersion、QualityResult、LineageEvent、RunRef 和 serving revision 必须贯通后，才能宣称控制面闭环。
6. `gda_control` 已有测试验证的 gateway role/API，但没有生产业务调用方；gateway 可用不等于生产运行链已经切换。
7. 旧资产、workflow、run 和 lineage 行缺少稳定 tenant/version/checksum 证据时禁止自动 backfill，也不得猜测生成 ResourceVersion。
8. `platform_crosswalk` 只验证仓库 inventory、候选 payload 和 golden fixture；它不得连接数据库、分配 identity、回填旧表或写入 `gda_control`。
9. DolphinScheduler standalone 使用 H2 和默认开发身份，只能证明 adapter API/correlation 合同；不能作为生产 metadata DB、身份、隔离、高可用、备份恢复或升级证据。
10. workload/evaluator subject 配置和授权 Artifact gate 不是生产 IAM 的替代品；没有 staging 的 credential provisioning、轮换、吊销与 provider 最小权限证据时，不得宣称 workload identity 完成。
11. `platform_command_outbox` 只拥有投递状态；callback 只触发 reconcile，不能把 provider payload 直接写成 PlatformRun 状态或平台终局。
12. QualityResult evaluator 必须是 workload，且成功终局中的 evaluator 不能等于 Run workload；该代码级职责分离不替代生产 IAM。
13. `candidate_validated`、`registry_subject_bound`、GitHub provenance action 成功、CI artifact、离线 preflight、未独立 attested 的 live observation JSON 或人工批准都不能单独授权 production；缺少同一 source revision 的 OCI subject 独立验证、registry/live revision/identity/health/golden-slice 绑定及受保护 provenance 时，promotion 必须失败。
14. Metadata Fabric M1 只允许 OpenMetadata/Gravitino GET；M2a 与 M2b-1 只运行本地 foundation/recovery 且 `writes_to_gda_enabled=false`。`backup_restore_verified=true` 只适用于 `local_same_cluster_new_namespace_and_pvcs`；M1 snapshot、M2a Pod/PVC 与 M2b-1 evidence 都不等于 production provider、TableCatalogProvider、生产 backup/restore、OIDC、upgrade 或写权威。任一 provider identity、owner、version、checksum、revision、PVC 或持久化 marker 漂移都必须阻断，不能反向覆盖 GDA ResourceVersion。

## 已建立的 AR-0/AR-1 entry 证据

- 五张 legacy 表及资产兼容视图的 schema、writer、API marker inventory 已冻结，当前 fingerprint 为 `f81c5142e0355531ea0a59e8e68608834c088dee02a9bdf2a013f6d5489376ba`；未登记直接写入方会使 CI 失败。
- crosswalk planner 固定 `eligible`、`blocked`、`prohibited` 三种结果。当前没有对全量旧数据安全执行自动 backfill 的路径。
- 合成地类图斑 golden slice 已绑定 DLTB 标准证据、3 个 Resource、3 个 ResourceVersion、12 个平台合同（含 QualityResult 与 RunSuccessEvidence）、owner、SLO、rollback point 和消费者；fixture fingerprint 为 `9c18a58248c7f34666cc2eb1a959694725dead05fdab7bf855e57ee71b2091b5`。
- `gda_control_gateway` 的最小 grant、FORCE RLS、跨租户拒绝、禁止直接 RunEvent/UPDATE/DELETE，以及服务层 Definition -> Run -> attempt/artifact/lineage 全链已在真实 PostgreSQL 验证。
- 十二个 versioned API 已校验认证角色、tenant 和 actor，未绑定 tenant 的历史/OAuth/bot 身份默认拒绝；生产调用链仍写旧表，尚未切换到 gateway。
- DolphinScheduler 3.4.2 adapter 已固定 create/online/start/list/variables/control 路由、四字段 Run correlation、未知结果禁止盲目重提和 provider 非终局边界；binding artifact 具备稳定 UUID、canonical 完整性校验、幂等追加和 tenant-scoped 读取；真实 ARM64 standalone 完成 Shell DAG 精确关联，`STOP` 到达 `READY_STOP`，但未形成生产终局裁决证据。
- PolicyDecision/Approval 已形成强类型、内容寻址的 append-only Artifact，PlatformRun 保存不可变 UUID 引用；gateway 在提交期校验精确资源 scope，adapter 在 dispatch 前强制 workload/evaluator identity、action、effect、有效期和审批关系，失败时不会触达 provider 或改变 Run。
- migration 095 已建立 tenant/workload-scoped dispatch/reconcile outbox；真实 PostgreSQL 测试已覆盖最小权限、Run+dispatch/callback+reconcile 原子写、完成后幂等 replay、错误 workload 空领取、lease 接管、stale worker 拒绝和 fail/retry/complete，但尚无 staging 常驻 consumer 或真实 provider callback 运行证据。
- managed DolphinScheduler command worker 已提供严格 env/config、0600 token file、tenant/workload-scoped polling、SIGINT/SIGTERM drain、interruptible wait、脱敏原子 status 和 fail-closed health CLI；默认零副本 Kustomize 模板由 Pod UID 生成 worker ID，只向 PostgreSQL NetworkPolicy 增加该 selector，主容器无原始 provider Secret、Kubernetes API token 或 RBAC。protected run `31872815368` 已验证 historical release/current verifier revision 分离、observer 最小权限、single-replica render、blocked evidence attestation/upload 和 no-scale boundary；evidence fingerprint `1babf26cadfe39da364a1505d39cddf44d7e04abd38b32babbc0eadbece1ebce` 精确记录 ConfigMap/Secret attestation 绑定缺失及 worker Deployment 不存在，真实 provider identity、worker rollout/callback 仍未运行。
- migration 096 已建立 append-only QualityResult 和专用成功 finalizer；真实 PostgreSQL 16 测试已证明 gateway 不能执行私有 transition 或用通用 transition 写 `succeeded`，错误 output hash、failed quality、缺失 lineage、篡改 evidence fingerprint 均拒绝，有效证据成功且 replay 幂等。该证据仍是合成数据和本地数据库，不是 staging/生产运行证明。
- staging candidate run `31862363442` 已在 GitHub-hosted runner 绑定 `main@5fffc85`、489 项测试、97/97 schema、严格脱敏 config/runtime 和 application image，并把真实 GHCR subject 固定为 `sha256:4475c8bfe8c2037aa48feb9d941740cf3d25569de99ded9ddf3173d43b409762`；candidate 本身仍固定不声明 deployment/promotion。
- protected verifier run `31862984294` 已独立验证 publisher/repository/workflow/ref/digest/issuer/runner policy 和 OCI attestation，产出再 attested 的 provenance/release evidence；publisher/verifier revision 仍分离，成功 verifier 不单独授权 deployment 或 production。
- protected staging run `31863077257` 已实际 apply migration/application 并只读实采：97/97 schema、registry digest、config/runtime、rollout、EndpointSlice 和 health/readiness 全部通过，App ready 且零重启，`staging_deployed=true`；最终仅因 `golden_slice: live golden-slice evidence is missing` 阻断，`production_promotion_allowed=false`。该 workflow failure 是预期晋级门，不是应用部署失败。
- Metadata Fabric M1 已将地类图斑目标 ResourceVersion 绑定到一个 OpenMetadata table ref 和一个 Gravitino table ref，冻结 binding/reconciliation fingerprint；只读客户端、authority drift、重复/缺失映射、跨 tenant 和 secret-bearing payload 负例已进入 required CI。M2a 进一步在两节点 ARM64 Docker Desktop Kubernetes 运行 OpenMetadata `1.13.1`、Gravitino `1.3.0`、两个独立 PostgreSQL 和 OpenSearch；Secret-free evidence 已证明五个 Pod 替换、三块 PVC identity、176/39 张表和 78 个索引前后连续，fingerprint 为 `ac21ee50ba3c1f27f949420cc7e4483963714b6b955bb0157eca1dd39cf102c3`。M2b-1 又将两份 PostgreSQL dump 和 OpenSearch snapshot 恢复到独立临时 namespace 的三块新 PVC，匹配 176/39 张表与 79 个索引的内容 fingerprints，恢复 source availability 并完成 cleanup；evidence fingerprint 为 `ebb0db3646010d427601c5d06760f984c742a7a4b6fa143fd2d6c7833246ab30`。生产恢复、RPO/RTO、跨集群、OIDC、升级、网络策略执行和真实 ingestion flags 仍为 false。

## 下一验收证据

- 补齐 production 的 schema/config/runtime snapshot、registry/live DeploymentRevision、release/live artifact attestation 和 staging-to-production environment compare 报告；
- staging 的 migration role、应用 login membership、连接池 role/tenant 复位、双租户 API 和 success finalization 运行产物；
- DolphinScheduler adapter 的真实 IAM/OIDC、service token provisioning/轮换、provider 最小权限、binding artifact staging 接入、managed outbox worker/provider callback 实际扩容部署、唯一 worker ID、status/lease 故障恢复和无双写证据；
- 首条真实图斑链对 golden slice 的 output hash、独立质量结果/evidence、血缘、发布 revision 和 rollback 演练；
- OpenMetadata/Gravitino M2b 的生产 backup target/retention、PITR/跨集群恢复、RPO/RTO、OIDC/workload identity、NetworkPolicy enforcement、upgrade/rollback、registry provenance、metrics/OTel 和 owner/runbook，以及同一地类图斑 ResourceVersion 的 M3 受控 ingestion/replay、OpenLineage、无双写和 Gravitino Spark/Sedona/Flink conformance；M1 fixture、M2a PVC 重启与 M2b-1 同集群恢复 evidence 均不计入生产退出门；
- DolphinScheduler/Temporal sandbox 的独立数据库、备份恢复、身份、版本和升级责任证明；DolphinScheduler standalone/H2 不计入此退出门。
