# NL2Semantic2SQL 冷启动接入流程设计

## Understanding Summary

- 目标不是继续针对重庆 benchmark 调参，而是设计一套面向任意新表/新域的 NL2Semantic2SQL 冷启动接入流程。
- 范围是尽量通用的新数据接入，不限定道路/建筑/POI/图斑，也不限定某一行业。
- 接入方式采用半自动模式：系统先自动扫描与生成语义草稿，再由管理员确认关键语义后激活。
- 成功标准是新数据首轮接入后达到 80%+ 的效果，而不是仅仅“能跑”。
- 需要把 semantic → schema → SQL → 安全执行 → few-shot 沉淀这条链标准化，而不是继续依赖一次性 register 脚本。
- few-shot、semantic registry、列别名、表间关系推断都应纳入接入流程，而不是散落在运行时逻辑中。
- 设计目标是产品化能力，不是刷榜技巧。

## Assumptions

- 新数据主要以 PostgreSQL/PostGIS 表结构形式进入系统。
- 允许平台管理员参与一次轻量审核，但不希望人工从零逐字段配置。
- 首轮 80%+ 是上线门槛，不要求零配置全自动立即达到。
- few-shot 必须按域隔离，不能全局混用。
- 运行时 NL2SQL 主链路已经可用，新的设计优先新增前置接入层，而不是重写运行时。

## Recommended Approach

采用“半自动语义接入流水线 + 显式状态机 + 人工确认关键语义 + 冷启动验收 + 域隔离 few-shot”。

核心思想：
1. 把“如何让新数据变得可问”从脚本与人工经验中抽离出来，做成独立产品子系统。
2. 保持运行时 NL2SQL 主链路不变，只改变 semantic layer 的激活来源。
3. 将 draft 与 active 严格隔离，避免错误语义和 few-shot 污染生产层。
4. 用冷启动评测作为激活门槛，而不是靠人工主观判断“看起来可以”。

## Architecture

### 1. 前置接入流水线

新增一个独立前置子系统，而不是继续扩展 `register_*_semantic.py`。

流水线包括：
- **Schema Intake**：扫描表、字段、类型、geometry、主键候选、示例值、行数、索引、表注释。
- **Semantic Drafting**：生成 display_name、字段 aliases、semantic_domain、join_candidates、风险标签。
- **Human Review Gate**：由管理员确认主查询表、关键字段、允许 join、禁用字段、开放范围。
- **Activation + Evaluation**：自动跑冷启动评测；通过后写入 active semantic 层。

### 2. 运行时主链路保持不变

保留现有：
- `data_agent/nl2sql_grounding.py`
- `data_agent/sql_postprocessor.py`
- `data_agent/nl2sql_executor.py`
- `data_agent/reference_queries.py`

新的前置系统只负责决定：哪些表、哪些字段、哪些 few-shot 可以进入 active 层。

## State Machine

每个新数据集的接入采用显式状态机：

- `discovered`：系统发现新表，仅记录 schema 画像。
- `drafted`：系统生成语义草稿，但不进入生产语义层。
- `reviewed`：管理员确认关键语义。
- `validated`：冷启动评测通过（>=80%）。
- `active`：正式供 NL2SQL 使用，开始 few-shot 沉淀。

设计原则：draft 与 active 严格隔离，不允许未经审核的草稿直接污染生产 semantic layer。

## Data Model

建议新增以下元数据实体：

### `dataset_intake_jobs`
- 作用：记录一次接入任务
- 关键字段：`job_id`, `source_type`, `source_ref`, `status`, `started_at`, `finished_at`, `error`

### `dataset_profiles`
- 作用：记录原始结构画像
- 关键字段：表名、字段列表、geometry 类型、行数、示例值、索引信息、风险标签

### `semantic_drafts`
- 作用：记录自动生成的语义草稿
- 关键字段：`display_name`, `description`, `aliases`, `semantic_domain`, `join_candidates`, `confidence`

### `semantic_activations`
- 作用：记录哪一版草稿被激活
- 关键字段：`dataset_id`, `draft_version`, `activated_by`, `activated_at`, `eval_score`

active 层仍然复用当前生产语义表：
- `agent_semantic_sources`
- `agent_semantic_registry`

但只有 `activate()` 阶段才允许写入。

## Human Review Boundary

### 自动生成
系统自动生成：
- 表 display_name / description / 候选业务主题
- 字段 aliases / semantic_domain / 单位候选
- join_candidates
- 风险标签（PII、超大表、无 geometry、时间列缺失、枚举值稀疏）

### 必须人工确认
必须人工确认：
- 关键字段
- 允许进入 NL2SQL 的 join 关系
- 禁止暴露字段
- 自动别名中不可靠的部分
- 数据域是否达到“可开放给 NL2SQL”的程度

审核目标是“确认 20% 的关键语义，系统自动补足 80% 的普通元数据”。

## Cold-Start Validation

激活前必须先经过冷启动验证。每个新域自动生成一组验收题，至少覆盖：
- 字段过滤
- 分组聚合
- 跨表 join
- 空间关系
- Top-K / LIMIT
- Security Rejection
- Anti-Illusion

只有达到首轮 80%+，才允许从 `reviewed` 升到 `validated/active`。

## Few-shot Strategy

few-shot 不能全局混用，建议按域隔离：
- `domain_id`
- `dataset_id`
- `project_id`（可选）

检索顺序建议：
1. 当前数据域成功样例
2. 同类领域样例
3. 全局通用 SQL 模板

这样可以避免当前重庆图斑/POI few-shot 污染新行业数据。

## API Surface

建议最小接口集：
- `POST /api/intake/scan`
- `GET /api/intake/{job_id}`
- `GET /api/intake/{dataset_id}/draft`
- `POST /api/intake/{dataset_id}/review`
- `POST /api/intake/{dataset_id}/validate`
- `POST /api/intake/{dataset_id}/activate`

## Testing Strategy

### 1. Intake 测试
验证 schema 扫描：geometry、主键候选、示例值、空表/脏表/超大表处理。

### 2. Draft 质量测试
验证别名建议、semantic_domain、join_candidates、风险标记是否合理。

### 3. Cold-start Eval
这是上线门槛：每个新域自动生成标准题并评测，达到 80%+ 才激活。

### 4. 线上回归
持续观测：成功率、自纠错触发率、拒绝率、few-shot 命中率、用户纠错反馈。

## Non-Functional Defaults

- **性能**：单次接入扫描 < 5 分钟；单次 NL2SQL 查询反馈 < 30 秒。
- **规模**：支持百万行表冷启动，超大表默认采样/限流。
- **安全**：新域默认只开 SELECT；高风险字段默认禁用。
- **可靠性**：接入流程可重复执行、可回滚到上一个 active 版本。
- **维护**：由平台管理员负责审核，不要求开发手工改代码。

## Rollout Plan

### Phase A：接入底座
- schema 扫描
- dataset profile 持久化
- semantic draft 生成
- 审核接口
- activation 版本记录

目标：把新数据接入从脚本行为变成产品能力。

### Phase B：验证闭环
- 自动生成接入验收题
- 跑增强版 NL2SQL eval
- 生成 scorecard
- 达标后允许 activation

目标：把“首轮 80%+”制度化。

### Phase C：持续学习闭环
- 域隔离 few-shot
- auto-curate 成功样例
- bad case 回流
- 重新 validate 时利用历史沉淀

目标：从一次性接入升级为持续学习。

## Edge Cases

- **无 geometry 的纯统计表**：标记为 `tabular-only`，允许 NL2SQL，但不进入空间语义草稿。
- **多 geometry 列**：必须人工指定默认空间列，否则不允许激活。
- **超大表**：intake 只取样，不做全表 profile；验证题避免全量返回。
- **弱关联数据**：join 置信度不足时不自动开放跨表查询。
- **敏感字段**：默认不进入 aliases，不进入 few-shot，不开放自由查询。

## Rollback and Release

- 每次 activation 形成一个版本快照。
- 如果上线后出现误召回、错误 join、幻觉率升高、few-shot 污染，直接回滚到上一个 active 版本。
- 发布分两级：
  - `validated`：管理员可见
  - `active`：普通用户可见

## Decision Log

1. 采用半自动接入，而非全自动或纯人工。
2. 将冷启动接入做成独立前置流水线，而不是继续扩展一次性注册脚本。
3. 引入显式接入状态机（discovered → drafted → reviewed → validated → active）。
4. 自动生成大部分语义草稿，但关键字段/join/禁用字段由人工确认。
5. 引入冷启动验收门槛与域隔离 few-shot。
6. 引入 profile / draft / activation 三层元数据，而不是把扫描结果直接写入正式 semantic 表。
7. 分 3 阶段落地，而不是一次把接入、验证、学习闭环全部同时实现。
8. 用四层测试 + 激活门槛 + 回滚机制保证冷启动质量。
9. 复用现有 NL2SQL 运行时，只新增前置 intake 子系统。
10. activation 必须版本化，并支持管理员级灰度开放与一键回滚。

## Implementation Handoff

下一步实现建议按以下顺序进行：
1. 新增 intake 元数据表与 CRUD/状态机
2. 实现 schema intake + dataset profile 生成
3. 实现 semantic draft 生成与审核接口
4. 实现 activation 写入 active semantic 层
5. 实现 cold-start eval 与 scorecard
6. 实现域隔离 few-shot 与 bad case 回流
