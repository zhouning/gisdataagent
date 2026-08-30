# ADR-029：Live Staging Observation 与 Promotion Authority 边界

**Status**: Accepted

**Date**: 2026-07-26

**Decision owners**: Platform Architecture, Data Platform, SRE, Security

**Related decisions**: ADR-027、ADR-028

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-028 已把 CI candidate 与真实 staging deployment 分开，但 production 仍缺少机器可验证的 live observation。单独查看 `kubectl rollout status`、Pod Ready 或 HTTP 200 不能证明运行镜像来自指定 source revision，也不能证明 schema、配置、运行时清单和 golden-slice 终局属于同一 Deployment。

Docker Desktop 当前实例证明了该风险：应用 Deployment 为 1/1 Ready，`/health` 与 `/ready` 正常，应用角色可读取 97/97 in-sync migration ledger，且已禁用 service-account token 自动挂载；但运行镜像是本地 tag，Pod template 没有 source/candidate/environment/platform fingerprint 注解，实际 profile 是 development，旧镜像也未输出 environment-access baseline，且没有真实 golden-slice 证据。把这些状态称为 staging verified 会继续制造平台事实错误。

## Options Considered

| 方案 | 优点 | 缺点 | 决定 |
|---|---|---|---|
| 只在 workflow 中编写 `kubectl`/`curl` shell | 实现快 | 难以单测、字段容易泄漏、日志成功语义不稳定 | 拒绝 |
| 引入 Kubernetes Python SDK 和新的 DeploymentRevision 数据库 | API 完整 | 增加依赖与第二套未成熟权威，当前没有真实 staging provenance | 延后 |
| 标准库 collector + 纯 JSON verifier | 只读、字段白名单、可离线复核、可在真实 staging 直接运行 | v1 仍需外部 provenance/attestation 才能晋级 | 采用 |

## Decision

1. 新增 `data_agent.staging_live_evidence`，提供 `collect` 与 `validate`。collector 仅通过参数数组调用 `kubectl`，不使用 shell，不读取 Kubernetes Secret，也不保存完整 Deployment、ConfigMap 或应用响应；输出只保留验证所需字段。
2. 新增 `data_agent.staging_release_evidence` 作为接触集群前唯一 admission 合同。它重新验证 candidate、registry 和 protected provenance 三份 evidence 的内容 fingerprint、source/verifier revision、GHCR repository/digest/image、OIDC policy 和交叉引用，再绑定 schema/config/environment-access/runtime fingerprint。只有完整一致时才输出 `staging_apply_allowed=true`；该值不表示已经部署，且始终保持 production promotion 为 false。
3. protected provenance workflow 必须从同一个成功 candidate run 下载 candidate 与 registry evidence，在独立校验 OCI provenance 后生成 release bundle；provenance JSON 和 release JSON 分别取得 artifact attestation，完整四文件 bundle 作为单一 artifact 上传。后续 staging deploy 不能从 workflow 输入或手工参数自行拼装镜像与指纹。
4. 集群身份使用 `kube-system` namespace UID，环境身份使用独立 `gis-agent-staging` namespace UID。两者的 expected value 必须来自受保护环境配置，不能由本次观察值自动接受；受保护 staging 明确拒绝开发 namespace `gis-agent`。
5. live Deployment Pod template 必须绑定 `org.opencontainers.image.revision`、candidate/release evidence fingerprint、`staging` environment、schema/environment-access/runtime fingerprint 和预期 platform fingerprint。v1 固定单副本 staging，直到逐 Pod config/runtime/health 采集实现；镜像不仅必须为 registry `@sha256:` digest，还必须精确等于 attested release image。Deployment generation/replica/Available/Progressing、Pod runtime image ID、ServiceAccount、禁用 token 挂载和 ready EndpointSlice Pod UID 必须一致。
6. collector 在运行中的 app container 内以普通应用凭据执行 migration `status` 和 platform `snapshot`，并通过 Kubernetes Service proxy 读取 `/health`、`/ready`。schema fingerprint 和 runtime fingerprint 必须与 candidate 对齐。
7. candidate 的临时 config fingerprint 不要求等于真实 staging config fingerprint。真实 config、environment-access baseline 与 runtime 重新组成 live platform fingerprint，并必须等于 Deployment Pod template 注解；environment-access fingerprint 和 runtime fingerprint 还必须与 candidate 对齐。这样既允许环境特定 endpoint/bucket，又禁止代码读取面或运行机制发生未声明漂移。
8. golden-slice evidence 采用固定字段白名单，绑定 source revision、Deployment UID、registry digest、live schema/config/environment-access/runtime fingerprint、Run、output Artifact、QualityResult、LineageEvent 和 RunSuccessEvidence fingerprint；额外字段、过期证据或内容 fingerprint 不一致均 fail closed。
9. `live_staging_verified=true` 只表示 observation 内部一致。v1 固定 `promotion_authority_verified=false`、`production_promotion_allowed=false`。production workflow 在受保护 runner identity、artifact attestation 和同 revision approval 接入前继续固定失败。
10. staging workload 采用 preflight、migration、application 三阶段 apply。preflight Job 从环境预置 ConfigMap/Secret 读取实际配置，但只输出最小脱敏 platform snapshot，且无 Kubernetes API token 和数据库 admin credential；migration Job 是唯一 schema writer；application init container 只用 application role 等待 ledger `in_sync`。renderer 不创建 Namespace、ConfigMap、Secret、数据库、缓存、对象存储、Ingress 或 worker；私有 GHCR 凭据只通过环境预置 image-pull Secret 的名称引用。
11. `staging-live` workflow 只能消费准确 upstream run-id 的固定名 release bundle。它先验证 release 文件的 GitHub artifact attestation，再从已签署内容解析 verifier revision、检出对应代码并核对 protected cluster/namespace UID。runner 必须能管理限定的 workload 资源并完成 observation，但必须没有读取或管理 Secret/ConfigMap、创建/修改 namespace 的权限。没有真实 golden slice 时，即使 rollout 与 live collection 成功，workflow 仍必须以失败结束并保持 production promotion 为 false。
12. workload rollout 与业务 golden 验收拆为两个受保护门。部署 workflow 继续 fail closed 并上传已 attested collection、candidate 与 release；数据责任人完成 post-rollout、evidence-gated `PlatformRun` 后，显式提交 deployment run ID 与 golden Run ID 到独立 `Verify - Protected Staging Golden Slice` workflow。验收 workflow 使用只读 observer kubeconfig，不得 create/patch/delete workload、Secret 或 ConfigMap；它重新采集 live observation，在部署 Pod 内用 `SET TRANSACTION READ ONLY`、`gda_control_gateway` 和 tenant RLS 读取精确 Run，而不自动选择“最近成功任务”。
13. `data_agent.staging_golden_slice` 必须验证 Run 属于环境冻结的 tenant、capability、definition version 和 input ResourceVersion，且 submitted/started/terminal、provider observation、output、quality 与 lineage 时间均不早于当前 ready Pod。终态事件必须为数据库 evidence-gated `succeeded`；DolphinScheduler observation、content-bound output Artifact、独立 passed QualityResult、input-to-output LineageEvent 必须形成唯一集合。Run success 与 quality fingerprint 均由 verifier 重新计算，不接受账本字段的无条件透传。
14. golden slice 白名单进一步绑定 tenant、capability、definition version/fingerprint、input/output ResourceVersion。独立 workflow 验证 deployment collection 与 release attestation，检出 release 指定的精确 verifier revision，完成 live evidence 后为 collection、golden slice 与 verdict 生成 attestation。即使完整 staging 验证通过，`promotion_authority_verified` 与 `production_promotion_allowed` 仍固定为 false。
15. 新增只读 `staging_environment_readiness` 作为环境启用前的机器准入清单。它只读取 GitHub workflow、受保护执行源、environment、runner、run 和 artifact 元数据，并且只报告变量/Secret 名称是否存在，不输出值；默认不访问 Kubernetes。`gda.staging_environment_readiness.v2` 分别判断远端四段 workflow 与九个受保护 release-source 文件是否和本地已审合同一致、GitHub 元数据读取是否完整、两个 environment 的 review/no-bypass/branch policy、`gda-staging` runner、所需配置名称、显式 cluster identity observation 以及 candidate/provenance/deploy/golden 各阶段 artifact 是否出现。workflow YAML 与其 evidence builder、release verifier、preflight/manifest renderer、live collector/verifier、golden ledger/verifier 必须共同进入默认分支；只同步 YAML 不构成 repository contract ready。任一 GitHub API 分页或必需 endpoint 读取失败也必须 fail closed，不能用已读取的部分 artifact 误判 ready。配置 UID 不能替代集群观察，artifact 名存在也不替代后续 attestation/content verifier；任一前置门缺失时 `status=blocked`、AR-0 保持 `in_progress` 且 production promotion 固定禁止。
16. golden 账本读取与证据判定必须使用 release 绑定的受保护 verifier revision，不能调用候选镜像内的 `data_agent.staging_golden_slice`。受保护 revision 提供单独的 `staging_golden_ledger.sql`；workflow 将该 SQL 经 stdin 交给 Pod 内 `/usr/bin/psql -X`，在 `BEGIN READ ONLY`、`SET LOCAL ROLE gda_control_gateway` 和 tenant RLS 下只导出恰好一行白名单 JSON。JSON 只通过管道进入 runner 上的受保护 Python verifier，不落 runner 文件系统或 artifact；verifier 对字段闭集、唯一行、环境冻结身份、时间门和两类 fingerprint 独立重算后才生成 golden slice。该边界消除候选应用 Python 代码对 verdict 的控制，但 PostgreSQL client 仍运行在候选容器中，因此不能替代后续独立 observer runtime 或 production promotion authority。

## Consequences

正面影响：

- rollout、身份、配置、数据库、健康和业务终局第一次形成同一机器可验证边界；
- collector 不读取 Secret，且不会把完整 Kubernetes annotation、非必要配置或健康 detail 写入 artifact；
- 部署输入从松散的多个 artifact 收敛为受保护 verifier 生成并签署的 release bundle，篡改任一 candidate、digest、provenance policy 或交叉 fingerprint 都会在集群访问前阻断；
- 当前本地开发集群可以被真实观察，但会因客观缺口阻断，不会被包装成 staging 成功；
- 后续 provenance gate 可直接签署稳定 evidence fingerprint，不需要重新定义 observation 内容。
- 环境实际配置在接触 schema 和应用 rollout 前先得到 fail-closed preflight；完整 config entries、环境访问路径和 runtime inventory 不进入 Job 日志或 staging artifact；
- staging apply 的资源所有权被限制在 GIS Data Agent workload，现有开发集群和环境方管理的数据服务不会被 overlay 接管。
- rollout 与业务验收不再被压缩成一个超时敏感步骤；失败的部署门可以保留可审计 observation，后续只能由明确、post-rollout 的受治理 Run 关闭 golden gate；
- 历史成功 Run、其他 capability、其他 definition/input 或当前 Pod 之前的 Run 不能被复用为 staging golden evidence；质量和 Run success 指纹即使账本字段被错误复制，也会在只读 verifier 中重新计算并阻断。

限制：

- `kube-system` UID 是实用的 cluster identity，不是密码学集群证明；
- v1 只从单个 app Pod 读取 process config/runtime，因此不接受多副本 staging；
- JSON 文件可被本地伪造，因此未 attested observation 不能成为 promotion authority；
- v1 不创建真实 golden-slice、registry push、worker activation 或 production rollout。
- v1 不自动触发领域 DataOps Run；环境方仍需配置冻结的 tenant/capability/definition/input，并由数据责任人在真实 staging 完成该 Run 后显式发起验收；
- release admission 本身不持有集群权限；workload-only deploy workflow 仍需环境方预置受保护 runner、独立 namespace、ConfigMap、Secret、数据服务和固定 cluster/namespace identity。
- readiness 报告是运行链的前置清单，不会创建 environment/runner、触发 workflow、读取 Kubernetes 或签发 promotion authority；这些外部状态仍须由环境责任人显式提供。
- golden SQL 仍通过已部署 Pod 的网络和应用数据库凭据访问账本；v1 依赖镜像内系统 PostgreSQL client，尚未证明独立 observer image/workload identity。候选容器 compromise 属于 production promotion 前仍需关闭的残余风险。

## Verification

- 行为测试覆盖完整 live binding、candidate/revision/digest/identity/schema/config/health/golden drift、过期/缺失 evidence、CLI fail closed 和 collector 字段白名单；
- 完整 fixture 可得到 `live_staging_verified=true`，同时保持 production promotion 为 false；
- release fixture 可得到 `staging_apply_allowed=true`，同时保持 `staging_deployed=false` 和 production promotion 为 false；candidate 内容、registry digest、provenance policy 漂移即使重算局部 fingerprint 仍会 fail closed；
- 2026-08-13 Docker Desktop 实采的 collection/health 通过；Deployment 1/1 Ready、schema ledger 97/97 in sync、runtime baseline 匹配且 token 自动挂载已关闭；由于没有成功的同 revision candidate artifact，schema/runtime 不能完成 candidate 绑定；本地 tag、缺 revision/candidate/environment/platform 注解、development profile、缺 environment-access baseline 和 golden-slice 均输出分域阻断；
- collector 输出未包含测试注入的 Secret、完整 last-applied annotation、health detail 或 platform config entries。
- workload/preflight/live evidence 与 deploy workflow 合同测试覆盖三阶段顺序、固定 artifact/run-id、release attestation、cluster/namespace identity、精确 release digest、Secret 非读取边界和无 golden slice 固定失败；全部 staging 相关回归为 `42 passed`，Ruff、YAML parse 与 scoped diff check 通过。
- golden slice builder 与独立 protected workflow 覆盖 post-rollout 时间门、capability/definition/input 绑定、失败/陈旧/跨能力 Run、独立质量、fingerprint 重算、digest drift、observer 无写权限及 production authority 固定 false；全部 staging 相关回归扩大为 `53 passed`，Ruff 与 workflow YAML parse 通过。
- staging readiness collector/verifier 覆盖完整 ready、workflow 与受保护 release-source 远端合同漂移、GitHub 元数据部分读取 fail closed、404 已确认缺失与真实读取故障分离、缺 environment/runner/artifact、变量与 Secret 值不外泄、deploy 预期失败但 observation 存在，以及 CLI blocked exit；2026-08-13 最新真实 GitHub 只读报告把最前置动作收紧为将四段 staging workflow 与九个受保护执行源作为同一 release-source bundle 进入 `main`。当时远端缺 deploy/golden workflow，九个源均未与本地合同一致（其中四个不存在），仅有 `staging-provenance` environment，`staging-live` 不存在，repository runner 为 0，四阶段 artifact 均不存在；readiness 聚焦回归 `9 passed`，完整 staging 合同回归 `68 passed`，未访问 Kubernetes，也未修改 GitHub 状态。
- protected golden verifier 回归进一步覆盖受保护 SQL 的 read-only/RLS/参数化合同、0/1/多行导出、字段闭集、stdin 管道、候选应用 Python 禁用和临时 ledger 不落盘；workflow 只 attest 脱敏后的 collection/golden/verdict。该修改仅关闭 verifier revision 混淆，不声称真实 staging Run 已执行。
- 三阶段 manifest 已用空 kubeconfig 尝试本地 `kubectl --dry-run=client --validate=false`；kubectl v1.36 仍强制访问 `localhost:8080` 做 API discovery 并失败，因此没有连接或修改 Docker Desktop。真实 workflow 会在受保护 staging 上先执行 server dry-run。

## Revisit Triggers

- 已有受保护 staging runner，可通过 GitHub OIDC、Sigstore 或等价机制证明 collector identity 与 artifact provenance；
- 真实 staging overlay 能绑定 registry digest、candidate/platform fingerprint 和固定 cluster/namespace identity；
- 首条真实地类图斑 golden-slice 已由受保护 workflow 从数据库权威导出并取得 artifact attestation，而不是仅通过离线 fixture。
