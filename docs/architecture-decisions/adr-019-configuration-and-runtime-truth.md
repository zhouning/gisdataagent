# ADR-019：配置与运行时事实源采用增量式合同门禁

**Status**: Accepted

**Date**: 2026-07-24

**Decision owners**: Platform Architecture, Data Platform, SRE, Security

**Related roadmap**: [AR-0 平台事实源](../roadmap-ar0-platform-truth-2026-07-24.md)

## Context

应用的配置读取分散在生产 Python 模块、Compose、Kubernetes 和 `.env` 中。基线扫描发现 193 个被直接读取的环境变量，但此前没有统一的类型、默认值、密钥边界或环境策略。`app.py` 还使用 `load_dotenv(..., override=True)`，使镜像内 `.env` 可以覆盖部署系统注入的值。

数据库同时存在 `DATABASE_URL` 和 `POSTGRES_*` 两种配置路径。CI 只设置前者，部分数据库模块只读取后者，导致测试可能落入“未配置数据库”的降级分支。后台执行也分散在 APScheduler、自有队列、SparkGateway、stream loop、outbox worker 和裸 `asyncio.create_task` 中，缺少可审查的所有者、耐久性和替换目标。

本阶段约束：

- 不能在一个 AR-0 切片内重写所有配置调用方或替换全部运行时。
- 不能引入新的配置服务、调度平台或密钥存储作为没有生产证据的第二事实源。
- staging/production 必须 fail closed；development/test 仍需支持不连接全部外部依赖的开发模式。
- 配置快照、日志和环境比较产物不能包含密钥明文。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| A. 只补充部署文档 | 改动最小 | 无法阻止源码、默认值和运行时继续漂移 | 拒绝 |
| B. 立即迁移所有配置到新框架，并同时替换所有后台运行时 | 最终形态统一 | 跨越过多模块；在 PlatformRun 和编排合同冻结前容易制造另一套临时框架 | 延后 |
| C. 建立关键配置类型注册表、脱敏快照、源码指纹和运行时清单，再增量迁移调用方 | 先封住新增漂移；范围可验证；保留后续替换空间 | 存量 193 个变量不会在本切片全部成为统一读取 API | **选择** |

## Decision

1. `data_agent.platform_truth` 是 AR-0 配置与运行时合同入口，只依赖 Python 标准库，可在应用框架和外部 SDK 初始化前运行。
2. `GDA_DEPLOYMENT_PROFILE` 支持 `development`、`test`、`staging` 和 `production`。development/test 将缺失外部依赖报告为 warning 并允许启动；staging/production 将关键缺失或非法值作为启动错误。后两者的 strict 模式不能被环境变量关闭。
3. 部署环境优先于仓库 `.env`。本地 `.env` 只填补未设置值，不得覆盖 Compose、Kubernetes 或进程环境。
4. `DATABASE_URL` 是应用数据库连接的首选事实源；未设置时才由 `POSTGRES_*` 安全编码生成。两组配置同时存在且指向不同数据库时报告冲突。需要管理员身份的 migration 入口必须显式清除 `DATABASE_URL`，再使用 admin 组件。
5. 配置报告包含类型、owner、来源、是否配置、脱敏值和稳定 SHA-256 指纹。密钥只记录 configured/unset 状态，密钥变化不会进入日志、JSON 或指纹明文。
6. 当前注册表覆盖数据库、认证、对象存储、模型、核心运行时、ArcPy MCP、日志和 DolphinScheduler 托管 worker 等 79 个关键项。其余存量直接读取由完整 AST 指纹冻结；增加、删除或移动直接读取都必须显式评审并更新基线。
7. 后台运行时以 `RuntimeSpec` 登记 ID、类型、owner、耐久性、状态权威、生产角色、代码证据和目标形态。AST 同时冻结线程、进程池、subprocess、scheduler 和 async task 原语；未登记路径或原语指纹变化使 CI 失败。DolphinScheduler command worker 只拥有进程生命周期，命令状态仍由 PostgreSQL outbox 权威管理。
8. `legacy`、`governed` 和 `ephemeral` 是事实分类，不是完成状态。存在 `replacement_required` 的运行时进入 `production_blockers`；静态清单可合法，但 `production_ready` 必须保持 false，直到统一 PlatformRun/编排退出门通过。
9. CI 运行 `python -m data_agent.platform_truth validate`。CLI 另提供 `snapshot`、`runtime` 和 `compare`，供环境导出与漂移比较。

## Trade-offs

- 接受本阶段仍有存量模块直接读取环境变量；AST 基线防止范围静默扩大，后续按 owner 迁移。
- 接受进程内运行时继续服务兼容路径；它们不能再被宣称为耐久或生产权威运行时。
- 不使用配置值本身生成密钥指纹，因此只能比较“是否配置/来源”，不能证明两个环境使用相同密钥。这避免了可离线猜测的密钥摘要进入产物。
- AST 只识别字面量环境键和已知运行原语；动态键必须由注册表和代码评审补充，不能把扫描结果等同于完整运行时证明。

## Consequences

正面影响：

- 部署注入值不再被镜像内 `.env` 覆盖。
- CI 的 `DATABASE_URL` 与运行时数据库访问使用同一优先级，密码、用户名和库名被正确编码。
- staging/production 的关键配置错误在模型客户端、数据库连接或业务请求之前失败。
- 新增后台线程、任务、scheduler 或直接环境读取会形成明确 diff，而不是无声进入生产。
- 环境可以导出不含密钥的 config/runtime fingerprint 并进行比较。

负面影响与缓解：

- 源码指纹对有意移动代码也敏感；通过更新注册表、ADR/PR 说明和基线完成显式接受。
- 应用启动会报告 development 缺失依赖 warning；日志按 key/code 聚合，不输出密钥值。
- 多个 legacy runtime 仍是生产阻塞项；按 [System-of-Record 矩阵](../system-of-record-matrix-2026-07-24.md) 和 ADR-007 逐项迁移，不在本 ADR 中伪造统一性。

## Verification

- 9 个单元测试覆盖密钥脱敏、production fail-closed、development 降级、数据库优先级/冲突/编码、源码基线、未登记运行时和快照比较。
- 静态报告确认 193 个环境键读取基线匹配、17 个运行原语文件均已登记、无解析错误和未登记路径；新增 worker 的 provider、tenant、lease、poll 和 health 配置已进入注册表。
- Compose development/staging/production 合并配置通过解析；Kubernetes manifests 可由 Kustomize 构建。

## Revisit Triggers

- 关键配置已完成统一读取迁移，需要将 193 个源码读取基线缩减为只允许平台配置模块访问；
- 引入 Vault、云 Secret Manager、配置服务或 workload identity，需要增加 secret reference/version 合同；
- PlatformRun 与 DolphinScheduler/Temporal adapter 通过真实故障恢复验收，可以移除对应 legacy runtime blocker；
- 需要证明跨环境使用相同密钥版本时，改为比较密钥管理系统的不可逆 version ID，而不是密钥值摘要；
- 多进程、多租户或远程 worker 使静态源码扫描不足，需要运行时注册与 admission policy。
