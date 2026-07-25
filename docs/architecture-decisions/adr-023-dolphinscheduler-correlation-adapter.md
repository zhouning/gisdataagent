# ADR-023：固定 DolphinScheduler 3.4.2 PlatformRun Correlation Adapter

**Status**: Accepted

**Date**: 2026-07-24

**Decision owners**: Platform Architecture, DataOps, Data Platform, Security

**Related decisions**: ADR-007、ADR-020、ADR-021、ADR-022、ADR-024、ADR-025、ADR-026

**Related roadmap**: [AR-0/AR-1 平台事实与最小控制面](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-007 已选择 DolphinScheduler 承担 DataOps 编排，ADR-022 已提供受控 PlatformRun 写入口，但二者之间尚无可执行的 correlation contract。若调用方把 provider 状态直接写成平台终态、在超时后盲目重提，或把 access token 和任务密钥内联进 Definition，会重新制造多写源、重复运行和凭据泄露风险。

当前代码仍是模块化单体。AR-1 需要先验证一个窄适配器，而不是增加 scheduler、queue、微服务或第二个 Run authority。

约束：

- API 和 server 版本必须固定，不能依赖浮动 `latest`；
- Definition 编译结果、provider binding 和 Run correlation 必须可复核；
- 外部提交的网络超时属于未知结果，不能被当作明确失败后自动重提；
- DolphinScheduler 终态只提供 attempt evidence，不能自行裁决 GDA 平台终态；
- 凭据不得出现在 Definition、日志、错误消息或命令行参数中。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 由现有 workflow API 直接调用 DolphinScheduler 并镜像状态 | 接入快 | 绕过 PlatformRun CAS，超时和重复提交语义不明确 | 拒绝 |
| B. 新建独立 orchestration microservice 和内部队列 | 故障域独立 | 当前规模下增加部署、事务、鉴权和第二套恢复机制 | 拒绝 |
| C. 模块化单体 adapter，复用 PlatformGateway | 范围小，可用真实 API 与 PostgreSQL 分别验证，保留后续拆分路径 | 暂不包含生产身份、回调和高可用部署 | **选择** |

## Decision

### 1. 固定版本和 HTTP profile

适配器固定 Apache DolphinScheduler `3.4.2` 与 API profile `3.4`。官方发布地址和以下路由作为 CI 可验证合同：

- `POST /projects/{projectCode}/workflow-definition`；
- `POST /projects/{projectCode}/workflow-definition/{code}/release`，`releaseState=ONLINE`；
- `POST /projects/{projectCode}/executors/start-workflow-instance`；
- `GET /projects/{projectCode}/workflow-instances`；
- `GET /projects/{projectCode}/workflow-instances/{id}/view-variables`；
- `POST /projects/{projectCode}/executors/execute`。

客户端保留部署 context path，以 `token` header 认证。版本升级必须重新运行静态、mock、真实 sandbox 和 provider failure conformance，不能只改常量。

### 2. Definition 编译和发布

只有 `orchestration_class=dataops` 的 PlatformDefinitionVersion 可以编译。`definition_document.dolphinscheduler` 保存 provider-native DAG 文档；编译器注入稳定的 definition id、URN、tenant 和 hash 参数，排序后产生 `compiled_sha256`。任何常见 token、password、secret、private key 或 access key 字段含有内联值时 fail closed。

创建 workflow 后必须显式上线，只有上线成功才返回 `DolphinSchedulerDefinitionBinding`。binding 固定 project code、workflow definition code/version、compiled hash、API profile 和 server version。

binding 通过现有 append-only `gda_control.artifact` 持久化，不新增 registry 或数据表。artifact 固定 `artifact_role=execution_plan`、`run_id=NULL`，并以 `resource_version_id` 关联 PlatformDefinitionVersion；版本化 envelope、canonical content hash/size、artifact key、PostgreSQL URI 和 artifact UUID 必须相互一致。UUID 从完整 binding 确定性生成，重复写入沿用 gateway 的幂等冲突检查。dispatch、reconcile 和 cancel 可以接收内存 binding，也可以通过 tenant-scoped PlatformGateway 读取 artifact UUID；任何缺失或篡改均 fail closed。

binding publish、dispatch、reconcile 和 cancel 必须使用 profile 配置的 workload subject，并与 Run 的 authenticated workload SubjectContext 完全一致。dispatch 只能使用已持久化的 binding Artifact；任何仅存在于内存、无法从 tenant-scoped gateway 恢复的 binding 都不得提交 provider。

### 3. PlatformRun correlation

手工启动通过 `startParams` 携带：

- `gda_run_id`；
- `gda_tenant_id`；
- `gda_definition_version_id`；
- `gda_idempotency_key`。

对账必须读取 instance variables 并要求四项完全相等；零个结果返回 not found，多个结果 fail closed。未知分页结构、缺失 correlation variables 或达到配置的扫描页数上限也必须 fail closed，不能被解释成空结果。adapter 先把 PlatformRun 从 `accepted` CAS 到 `dispatching`，再提交外部运行。网络或 timeout 后先查询 correlation；不可见时转到 `reconciling`，后续调用不得盲目重提。

在上述 CAS 和任何 provider 调用前，adapter 必须重新加载 Run 引用的 PolicyDecision、可选 Approval 和 execution-plan Artifact，并按 ADR-024 验证精确资源 scope、`dolphinscheduler.dispatch` action、allow effect、有效期、职责分离和配置的 evaluator workload。失败时 provider 调用数和 Run transition 数都必须为零。

### 4. 状态和取消边界

运行中 provider state 可以把 `dispatching/reconciling` 投影为 `running`。`SUCCESS`、`FAILURE`、`STOP`、`KILL` 等 provider 终态只能追加 FrameworkAttemptObservation，并将 PlatformRun 移到 `reconciling`。ADR-026 已使通用 transition 无法写 `succeeded`；成功必须由数据库核验 output Artifact、独立 passed QualityResult/evidence 和 input-to-output LineageEvent。其他终态仍按各自状态规则处理。

取消先对 PlatformRun 做 CAS 到 `cancelling`，再发送 DolphinScheduler `STOP`。请求失败仍由后续 reconcile 处理，不能因 provider 接受命令就直接写 `cancelled`。

### 5. 凭据和部署边界

只读 probe 从 mode `0600` 的 token file 读取凭据，报告不输出 token。当前 standalone sandbox 使用内存 H2 和默认开发身份，只用于合同验证；它不满足生产 metadata PostgreSQL、OIDC/workload identity、tenant/project 隔离、备份恢复、高可用、升级或容量验收。

## Consequences

正面影响：

- PlatformRun 与 DolphinScheduler instance 有可恢复的稳定关联；
- provider binding 成为可按 definition version 复核的不可变 execution-plan evidence；
- 未知提交结果不会触发重复 DataOps 运行；
- provider 终态与平台终局裁决保持分离；
- 模块化单体继续复用既有 gateway、CAS、RLS 和 evidence 合同。

限制与缓解：

- binding artifact、授权 evidence gate、workload/evaluator 配置绑定和 tenant-scoped gateway 读取已完成，但生产调用方尚未切换，不能视为 staging IAM 或控制链验收；
- ADR-025 已实现 callback/outbox 合同与有界 consumer library，ADR-027 已补齐可受管 worker 进程代码，但尚未部署常驻 worker、配置 provider callback 或验证告警/恢复 SLO；
- ADR-026 已在本地合同和真实 PostgreSQL 16 上封闭 success authority，但尚未用真实 staging DAG 和数据产物验证该链；
- 真实 standalone 验证了客户端路由，但 PlatformGateway + DolphinScheduler + PostgreSQL 的同一端到端场景仍待 staging 验证；
- 尚未验证 schedule、complement/backfill、master/worker failover、独立 metadata DB 或 backup/restore，不能宣称 AR-1 退出门完成。

## Verification

- 36 个定向测试覆盖编译 fingerprint、内联密钥拒绝、context path、token redaction/文件权限、创建/上线、binding artifact round-trip/篡改拒绝/幂等 replay/UUID 驱动、workload/evaluator identity、PolicyDecision/Approval gate、startParams、变量关联、分页/扫描上限、未知结果、丢失响应恢复、非终局 provider state、取消和多 correlation 拒绝。
- 静态 validator 已进入 CI，固定版本、路由、上线、binding persistence、未知结果与平台裁决边界。
- 官方 ARM64 standalone image `apache/dolphinscheduler-standalone-server:3.4.2`（digest `sha256:485a1b37dd1c4088c8c8335f9fccbd229e5e703c32e21f318eb00cbb60b1af9d`）通过只读 probe。
- 真实 Shell DAG 完成 create -> online -> start -> list -> variables -> exact correlation，instance 到达 `SUCCESS`，六个 `gda_*` 参数可见。
- 真实长任务从 `RUNNING_EXECUTION` 接受 `STOP` 并进入 `READY_STOP`；这只证明控制命令与过渡状态，不等于平台取消终态验收。
- gateway PostgreSQL 回归已验证 provider `SUCCESS` 本身不能写平台成功，只有 ADR-026 完整证据集合可以幂等终结 Run。

## Revisit Triggers

- DolphinScheduler 3.4.x API、认证 header、instance variables 或状态枚举发生变化；
- 生产 workload identity 无法使用 token profile，需要 OIDC 或受控 credential broker；
- correlation 分页扫描达到容量瓶颈，需要带索引的 provider metadata 或回调投影；
- 独立扩缩、故障域、吞吐或发布节奏证明模块化单体 adapter 不再足够；
- schedule/complement/backfill 或 Spark/Flink plugin conformance 无法通过真实负载验收。
