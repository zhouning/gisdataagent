# ADR-021：冻结 Legacy Crosswalk 与地类图斑 Golden Slice

**Status**: Accepted

**Date**: 2026-07-24

**Decision owners**: Platform Architecture, Data Platform, DataOps, Governance

**Related decisions**: ADR-002、ADR-003、ADR-006、ADR-007、ADR-020

**Related roadmap**: [AR-0 平台事实源](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

ADR-020 已冻结 Resource、ResourceVersion、PlatformDefinitionVersion、PlatformRun、Artifact 和 LineageEvent 的最小合同，但现有业务仍通过旧资产、版本、workflow、run 和 lineage 表运行。旧表缺少统一 tenant、immutable identity、content checksum、definition version 或 PlatformRun correlation，且部分事实可原地更新或删除。

直接按字段相似度批量回填会制造不可证明的 ResourceVersion 和运行终局状态。另一方面，如果只写文字映射表，后续新增 writer 或 API 时不会触发失败，迁移边界会继续漂移。AR-0 还需要一个可重放的 GIS 样本，证明新合同能够贯通 input version、definition、run、attempt、artifact 和 lineage，而不是只在孤立模型测试中成立。

约束：

- 本开发包不能连接生产数据库、修改旧表或写入 `gda_control`；
- 缺少 tenant、authority identity、checksum、correlation 或 timestamp 证据时必须 fail closed；
- provider 或 legacy run 状态不能升级为平台终局裁决；
- golden 数据必须明确为合成测试数据，不得被误用为生产标准样本；
- 不因验收夹具引入新的 catalog、scheduler、queue 或通用迁移框架。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 按同名字段自动 backfill | 迁移速度快 | tenant、identity、version 和 run 语义不可证明，会永久污染新账本 | 拒绝 |
| B. 只维护文档 crosswalk | 实现成本低 | 不能发现新增 writer、marker 漂移或 payload 违反合同 | 拒绝 |
| C. 建立双写兼容层并逐步修正 | 可以尽快产生新记录 | 在 gateway、幂等和故障语义未建立前形成两个权威写入方 | 拒绝 |
| D. 显式 registry + 只读 evidence-gated planner + golden fixture | 边界可执行、可审计；不会猜测或写库；能形成 AR-1 输入 | 真实迁移和生产链路仍需后续 adapter/gateway | **选择** |

## Decision

### 1. 冻结 legacy inventory

`data_agent.platform_crosswalk` 显式登记以下五张表：

- `agent_data_assets`
- `agent_asset_versions`
- `agent_workflows`
- `agent_workflow_runs`
- `agent_asset_lineage`

每项登记当前语义、schema marker、直接 writer marker、mutation API marker、blocker 和允许的目标合同。validator 会扫描仓库内直接 SQL 写入；出现未登记 writer、marker 消失或目标合同未知时返回非零退出码。inventory 是仓库级迁移边界，不宣称覆盖外部脚本或生产数据库中无法从代码发现的写入方。

### 2. Crosswalk 只生成计划

每个候选必须提供 source table、legacy key、source row SHA-256、带时区的 extraction time、adapter identity 和完整 target payload。planner 复用冻结的 Pydantic 平台合同，结果只有：

- `eligible`：目标 payload 已满足合同，可以交给后续受控 adapter；
- `blocked`：映射类型允许，但必要证据或字段不完整；
- `prohibited`：来源不在 inventory、目标类型不允许，或规则永久禁止该映射。

planner 不连接数据库、不分配 UUID、不回填、不修改旧表，也不写入 `gda_control`。`eligible` 只代表候选合同完整，不代表已获迁移授权或已验证生产来源真实性。

### 3. Legacy run 不能成为 PlatformRun

`agent_workflow_runs -> PlatformRun` 永久标记为 `prohibited`。旧 run 的 mutable status、checkpoint、retry 和 naive timestamp 只能作为 provider/process evidence；在已经存在 PlatformRun correlation，且 observation envelope 具备 tenant、attempt number、external run identity、checksum 和 aware timestamp 时，才允许形成 `FrameworkAttemptObservation`。

### 4. 固定地类图斑 golden slice

`land_use_parcel_golden.json` 是明确标记 `synthetic: true`、`not_for_production: true` 的合成 GeoJSON fixture。它引用仓库中的 DLTB 标准 marker，并固定：

- 3 个 Resource 与 definition/source/target ResourceVersion；
- PlatformDefinitionVersion、SubjectContext、initial PlatformRun 和合法状态转换；
- legacy attempt observation、output Artifact、LineageEvent；
- required fields、结构性 geometry 检查、BSM 唯一性、总面积；
- owner、runtime SLO、rollback point、消费者和终局裁决条件。

validator 重算 input/output、attempt evidence 和 lineage event fingerprint，并检查合同间 identity 关联。该 fixture 是 AR-0 合同验收基线，不是拓扑正确性、CRS 精度、生产性能或完整 DLTB 合规性的替代品；这些留给 AR-2 真实纵向链验证。

### 5. CI 门禁

CI 在全量测试之前运行 `python -m data_agent.platform_crosswalk validate`。inventory、crosswalk policy 或 golden fixture 任一漂移都会阻断合并，除非变更同时显式更新 registry、证据 hash、测试与本 ADR/矩阵中的边界。

## Consequences

正面影响：

- 旧表到新合同的允许、阻断和永久禁止路径从文字约定变成可执行规则。
- 新增直接 writer 会立即暴露，不会静默扩大 legacy 事实源。
- provider attempt 与平台终局状态继续保持严格分离。
- 首个 GIS 样本可同时验证 identity、version、run、artifact、quality 和 lineage 关联。

负面影响与缓解：

- 没有自动迁移能力；AR-1 adapter 必须提供来源证据、幂等 key、冲突处理与审计后才能写入。
- 静态 writer 扫描无法发现运行时拼装 SQL、数据库外部客户端或生产 hotfix；通过生产数据库审计、gateway 单写权限和切换前 inventory 补充来缓解。
- golden quality 只覆盖最小结构断言；AR-2 使用真实数据增加 CRS、拓扑、标准合规、性能、权限与灾备验收。

## Verification

- repository inventory 当前覆盖 5 张 legacy 表及资产兼容视图写入路径，fingerprint 为 `f81c5142e0355531ea0a59e8e68608834c088dee02a9bdf2a013f6d5489376ba`。
- golden fixture fingerprint 为 `b226622af6544cf0368d5a29f9e744aa1e3aed5511193c8e69f2f9f4ce5e7aac`；input/output fingerprint 分别为 `b37cf0a49954d2421ac8d48122952c490e3930dc3a389b0329246cbe95669aa4` 和 `7c6abe2639707fa8c78265024d500784e4a40ab9ba8c9206558eaceb6fb5ead8`，canonical output size 为 `956` bytes。
- golden 验证贯通 3 个 Resource、3 个 ResourceVersion、9 个平台合同和 3 条合法 Run transition；输出包含 3 个 feature、0 个结构性 geometry error、0 个必填缺失、0 个重复 BSM，总面积为 `17500.50`。
- 定向测试覆盖未登记 writer、eligible/blocked/prohibited、naive timestamp、legacy run 隔离、fixture 篡改和 canonical JSON 稳定性。

## Revisit Triggers

- AR-1 gateway/adapter 需要真实写入时，必须增加 role、tenant context、idempotency、conflict 和 transaction contract；
- 发现静态扫描无法覆盖的外部 writer 或动态 SQL 路径；
- 首条真实地类图斑链需要扩展 DLTB 质量规则或替换 synthetic fixture；
- 旧表进入只读或退役阶段，需要记录生产审计、双读比较和 rollback 完成证据；
- wire format 需要与 OpenLineage、CloudEvents 或外部 metadata/orchestrator SDK 对齐。
