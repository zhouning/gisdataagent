# ADR-082：公共轻量 DataOps Run 采用同步执行与独立成功证据门

**Status**: Accepted

**Date**: 2026-08-17

**Decision owners**: Data Platform, DataOps, Platform Architecture, Governance

**Related decisions**: ADR-020、ADR-026、ADR-081

## Context

M3-34 已把显式 public/open source 写入不可变 Landing，但尚未证明平台能消费真实空间数据并形成可服务的数据产品版本。继续增加 readiness contract 无法回答核心问题：同一 Landing ResourceVersion 是否能被一个受控 Definition/Run 解包、标准化、质量检查、发布、记录血缘并由数据库裁决成功。

这条公共路径规模较小、无需等待或补偿，也不需要分布式调度。强行伪装成 DolphinScheduler attempt 会制造错误运行事实；新增服务、调度器或账本则会重复现有平台控制面。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 把本地执行记录为 DolphinScheduler | 可复用 migration 096 | observation 与真实执行器不符，破坏审计可信度 | 拒绝 |
| 为公共路径新增服务、表和调度器 | 可独立演进 | 重复 Resource/Run/Artifact/Quality/Lineage authority | 拒绝 |
| 复用控制账本，增加受限 synchronous success profile | 最小增量，运行事实真实，完整复用证据链 | 只适合短时本地任务，不提供生产调度能力 | **选择** |

## Decision

### 1. 复用既有平台对象

公共轻量执行复用 `Resource`、`ResourceVersion`、`PlatformDefinitionVersion`、`PlatformRun`、`Artifact`、`QualityResult`、`LineageEvent` 和 `FrameworkAttemptObservation`。逻辑 Definition 使用 `orchestration_class=synchronous`，不绑定具体 source；Run 的 immutable input binding 绑定实际 Landing ResourceVersion。

Definition 的发布主体和时间属于 Definition version 本身，不随每次 Run 变化。目标 Resource 只记录稳定 source ResourceURN，目标 ResourceVersion 再记录精确 source ResourceVersion。

### 2. 执行器形成真实内容寻址数据面

`public_dataops_run.py` 接受 GeoJSON 或安全 ZIP。ZIP extraction 拒绝路径穿越、符号链接、加密 entry、无效名称、超限 entry 和超限解压体积；Shapefile/GeoPackage 通过 GeoPandas 读取并归一化为 EPSG:4326。

发布前使用 Shapely 检查 feature count、null/empty/invalid geometry、geometry type 和 bbox。通过后写入不可覆盖的 content-addressed GeoJSON；独立 evaluator 生成另一条 content-addressed quality evidence。相同输入、配置和执行时间重放不得重写任一文件。

### 3. 本地 attempt 不伪装为调度器

真实 observation 固定为：

- `framework_kind=legacy`；
- `evidence.schema=gda.public_dataops_attempt.v1`；
- `evidence.execution_mode=local_inline`；
- `observed_state=success`。

`legacy` 在此只表示已登记的本地 inline executor，不表示旧 Run 获得迁移权威，也不证明 DolphinScheduler execution。

### 4. 数据库继续拥有成功终局

已应用 migration 096 保持 checksum-frozen。migration 099 新增独立的 `finalize_synchronous_platform_run_success(...)`，完整保留 tenant、actor、state/CAS、replay、success evidence fingerprint、content-bound output、独立 passed quality 和 input-to-output lineage 检查，并额外强制 synchronous Run 与上述 local inline observation profile。

新函数为 `SECURITY DEFINER`，PUBLIC 无执行权，只有 `gda_control_gateway` 可调用。Gateway 先读取 Run；只有 synchronous Run 选择新函数，其他 orchestration class 继续调用 migration 096 的 DolphinScheduler finalizer。

## Consequences

正面影响：

- 首次形成真实 `Landing -> Run -> GeoJSON -> Quality -> Lineage -> succeeded` 公共数据垂直切片；
- 文件、平台对象和数据库终态均可确定重放，不新增第二套权威；
- 本地执行与调度器执行在 observation 和 finalizer 层明确分离；
- 可移植 Definition 能被同 tenant 的多个公共 source 重用。

限制与缓解：

- 当前 serving 是本地 content-addressed GeoJSON，不是 active service revision；下一可执行里程碑必须增加消费者可访问的版本化发布、切换和回滚；
- 当前为同步短任务，不提供 schedule、补数、队列、checkpoint 或故障恢复；这些仍由 DolphinScheduler/Spark/Flink profile 验收；
- 本地文件系统不证明 object lock、跨节点 durability、backup/RPO/RTO 或生产 identity；`production_ready=false`；
- 本决策不改变重庆 protected admission，`source_content_admitted` 仍为 false。

## Verification

- 13 个聚焦单元测试覆盖确定性输出、重放、质量、ZIP 安全、独立 evaluator、篡改和 CLI；
- 7 个 PostgreSQL 测试覆盖成功终态、无重复重放，以及错误 framework/schema/mode、同主体 evaluator、未绑定 output/lineage 的拒绝；
- Natural Earth 110m public-domain ZIP 实际产生 177 个 EPSG:4326 feature、1,065,275-byte GeoJSON 和完整账本链，重放未创建新文件或账本记录；
- 机器可读实测证据见 `docs/evidence/public-dataops-run-2026-08-17.json`。

## Revisit Triggers

- 同步任务达到必须异步排队、取消、checkpoint 或恢复的规模；
- 版本化 GeoJSON 需要 active revision、HTTP gateway、cache、consumer impact 或 rollback；
- 同一 Definition 接入 PostGIS、STAC、DuckDB 或 lakehouse provider，需要 profile conformance 与 golden equivalence。
