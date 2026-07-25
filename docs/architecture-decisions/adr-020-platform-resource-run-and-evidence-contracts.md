# ADR-020：冻结平台资源、运行与证据最小合同

**Status**: Accepted

**Date**: 2026-07-24

**Decision owners**: Platform Architecture, Data Platform, DataOps, Security

**Related decisions**: ADR-006、ADR-007、ADR-018、ADR-019、ADR-026

**Related roadmap**: [AR-0 平台事实源](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

GIS Data Agent 已有资产、版本、workflow、run、lineage、STAC、Iceberg 和专项 registry，但身份、版本、执行状态与证据由不同模块分别解释。直接部署 OpenMetadata、Gravitino、DolphinScheduler 或 Temporal 不能自动消除这些冲突；如果没有稳定的跨系统 identity、immutable binding 和 correlation contract，外部平台只会形成更多双写路径。

ADR-006 已决定通用治理归 OpenMetadata、technical metadata federation 归 Gravitino、产品行动证据归 GDA Control Ledger。ADR-007 已决定 DataOps 编排归 DolphinScheduler、durable Agent/GWM workflow 归 Temporal，GDA 只管理统一提交门、关联和终局裁决。本切片需要先把两项决策共同依赖的最小合同落到可执行代码和数据库，而不是开始自研 catalog 或 scheduler。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 继续复用现有资产/workflow/run 表 | 改动最小 | 缺少统一租户 identity、immutable input binding、CAS 状态与跨框架证据语义 | 拒绝 |
| B. 等外部平台部署后直接采用各自模型 | 少建一层 | Resource/Run 会被具体 provider 反向定义，无法切换或关联多系统 | 拒绝 |
| C. 新建通用 metadata catalog 和自研任务队列 | 可以完全定制 | 重复 ADR-006/007 已选成熟系统，扩大长期运维面 | 拒绝 |
| D. 建立最小 GDA control/evidence ledger，并保留 provider adapter 边界 | 先冻结跨系统不变量；可验证；不承担外部系统内部状态 | 需要后续 gateway、legacy crosswalk 和 adapter | **选择** |

## Decision

### 1. 身份与合同

- 平台身份采用 `gda://{tenant}/{kind}/{id}`。虽然合同名为 `ResourceURN`，其接受格式是 URI authority 形式；所有组成必须使用 canonical lowercase，禁止路径穿越和隐式规范化。
- `ResourceVersion` 绑定 tenant、ResourceURN、version key、content SHA-256、authority version reference 和可选 predecessor。predecessor 必须属于同一租户、同一 ResourceURN。
- `PlatformDefinitionVersion` 本身也是 kind 为 `definition` 的 ResourceVersion。其 SHA-256 覆盖 orchestration class、capability、portability、逻辑文档和输入输出合同，不能只 hash provider 编译产物。
- `SubjectContext` 显式包含 tenant、subject identity/type、roles 和 purpose；数据库 run tenant 与 subject tenant 必须相同。

Python 合同位于 `data_agent.platform_contracts`，使用 Pydantic v2 frozen model、`extra="forbid"`、UTC-aware timestamp 和 canonical JSON fingerprint。CLI 提供 `validate` 与 `schema`，用于 CI 门禁和 adapter schema 生成。

### 2. PlatformRun 状态权威

`PlatformRun` 是跨系统运行 correlation 和平台终局裁决，不复制 provider 的完整 workflow history。初始状态固定为 `accepted`、`state_version=0`，状态只能沿以下图迁移：

```text
accepted -> dispatching | failed | cancelled
dispatching -> running | cancelling | reconciling | failed | cancelled
running -> cancelling | reconciling | succeeded | failed | cancelled | timed_out
cancelling -> reconciling | cancelled | failed
reconciling -> dispatching | running | cancelling | succeeded | failed | cancelled | timed_out
```

终态没有出边。除 `succeeded` 外的变更调用 `gda_control.transition_platform_run(...)`；成功按 ADR-026 调用 `gda_control.finalize_platform_run_success(...)`。两者都提供 tenant、expected state version、actor、reason 和 details；数据库以行锁和 CAS 拒绝 stale、skip、自循环与终态重启，并追加同 sequence number 的 `PlatformRunEvent`。

transition 是 `SECURITY DEFINER` 封装，但同时要求参数 tenant 与 session `app.current_tenant` 完全相同。gateway role 只获得所需函数执行权，不能获得 `platform_run` 的直接 UPDATE 权。ADR-026 进一步禁止通用 transition 写 `succeeded`；成功只能通过数据库 evidence gate 调用私有 transition primitive。

### 3. Input、attempt、artifact 与 lineage

- Run input 使用独立 append-only `platform_run_input_binding` 行，不能藏在可变 JSON 或只保存在 provider payload 中。
- `FrameworkAttemptObservation` 保存 DolphinScheduler、Temporal、Spark、Flink、Kubernetes、ArcPy 等外部尝试的不可变观测。provider 报告 `SUCCESS` 不会触发或暗示 PlatformRun 成功；平台仍需核验 artifact、质量和策略。
- `Artifact` 保存稳定 URI、media type、content SHA-256、size 和 manifest。URI 禁止 userinfo credential、query/fragment 签名；本地文件只接受 `file:///absolute/path`。
- `LineageEvent` 保存 version-to-version 的不可变证据，可关联 run、definition 和 artifact；不允许 self-edge。OpenMetadata lineage graph 是可重建投影，不能覆盖事件证据。
- `QualityResult` 保存与 Run/output ResourceVersion、规则版本、metrics、evidence Artifact 和 evaluator 绑定的不可变 verdict；`RunSuccessEvidence` 固定成功裁决采用的 observation、output、quality 和 lineage UUID 集合。

### 4. PostgreSQL control/evidence ledger

迁移 `092_platform_control_ledger.sql` 建立独立 `gda_control` schema：

- `resource`
- `resource_version`
- `platform_definition_version`
- `platform_run`
- `platform_run_input_binding`
- `platform_run_event`
- `framework_attempt_observation`
- `artifact`
- `lineage_event`
- `quality_result`（由后续 migration 096 增加）

所有跨表引用使用 tenant composite foreign key，防止只凭全局 UUID 形成跨租户关联。Version、Definition、input binding、run event、attempt observation、Artifact 和 LineageEvent 通过 trigger 禁止 UPDATE/DELETE。全部表启用并强制 RLS，tenant policy 读取 `app.current_tenant`；未设置 tenant 或没有显式权限时返回零行或拒绝写入。

该 schema 是小型控制/证据账本，不是通用 metadata catalog、scheduler、queue、lease system、object store 或 provider job-state database。

### 5. Legacy 与外部系统边界

- `agent_data_assets`、asset version、workflow、workflow run 和 lineage 等旧表仍服务现有兼容路径。本迁移不自动 backfill，也不修改其写入逻辑。
- 没有可靠 tenant、version identity、checksum 或 authority reference 的旧行，不得猜测性映射到新 ledger。AR-1 crosswalk 必须逐类定义来源、冲突处理、幂等 key、证据和退出条件。
- OpenMetadata、Gravitino、DolphinScheduler 和 Temporal 没有在本切片部署或进入生产写链路。它们仍按 ADR-006/007 通过 POC 与退出门进入。
- 后续 ADR-022 至 ADR-026 已提供 gateway role/API、授权 evidence、outbox/callback 和成功终局门；生产业务切换、常驻 worker、IAM、backup/restore 与 staging 端到端仍未完成，因此不能宣称 production-ready orchestration。

## Consequences

正面影响：

- 外部 catalog、orchestrator 和 compute provider 共享同一 identity、version、run 与 evidence 语言。
- tenant、immutable input、definition hash、状态转换和 artifact 安全同时由 Python 和 PostgreSQL 约束。
- provider observation 与平台终局裁决被明确拆开，避免外部 success 直接发布产品。
- 不需要自研第二套 catalog、scheduler、queue 或 workflow engine。

负面影响与缓解：

- 新 ledger 与旧表会暂时并存；通过显式 crosswalk 和按纵向场景切换，禁止无证据批量回填。
- `SECURITY DEFINER` 需要严格 owner、search path 和 grant 管理；函数固定 search path、强制 tenant context，PUBLIC 全部撤权，并由专用 non-bypass role 和真实 PostgreSQL 测试持续验证。
- 数据库不能自行重算 Python canonical definition fingerprint；gateway 必须先验证 Pydantic 合同，数据库再以 FK 固定该 hash 与 ResourceVersion 的一致性。

## Verification

- Python/静态测试覆盖 URN、version、definition fingerprint、SubjectContext、run binding/transition、QualityResult、RunSuccessEvidence、Artifact、Lineage、JSON Schema、迁移目录与 SQL marker。
- PostgreSQL 回归测试验证 initial event、CAS、append-only、跨租户 FK、最小函数授权、RLS、通用 success 拒绝和 evidence-gated success。
- 项目官方 PostgreSQL 16 / PostGIS 3.4 / pgvector 镜像已真实重放 migration 092-096 并通过 gateway 服务链测试。
- CI 在全量测试前执行 platform contract validator 与 PostgreSQL ledger regression。

## Revisit Triggers

- 新增终局状态或 provider observation profile，需要冻结对应 evidence gate 和最小 grant；
- 首条地类图斑链进入 adapter，需要发布 legacy crosswalk 与 OpenMetadata/Gravitino/DolphinScheduler mapping conformance tests；
- 多区域或高吞吐写入使单 PostgreSQL ledger 达到有证据的瓶颈；
- 需要 OpenLineage、CloudEvents 或外部 SDK wire compatibility 时，在保持领域不变量的前提下版本化 envelope，不直接改写既有事件。
