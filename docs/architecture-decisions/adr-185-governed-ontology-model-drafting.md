# ADR-185: 受治理的自然资源本体草稿建模与变更提交

## Status

Accepted

## Context

GIS Data Agent 的活动本体是 PostgreSQL 权威模型和不可变发布包。现有工作台可以查询、遍历、查看属性继承、映射、溯源和校验，但不能让领域专家维护模型草稿。

Ontology Playground 提供了实体、属性、关系表单、实时图预览和撤销重做等有价值的交互模式。然而，直接使用其内部模型会丢失 GIS Data Agent 的稳定 URI、`kind`、几何类型、SKOS/PROV/SHACL、映射证据以及版本治理语义。

本决策只解决“草稿建模和审阅前准备”，不把浏览器变成生产发布器。

## Options Considered

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 直接嵌入 Ontology Playground | 建设速度快，交互完整 | React/RDF/URI/语义和版本契约不兼容 | 不采用 |
| 在活动版本表上直接编辑 | 数据模型复用率高 | 破坏已发布内容不可变和回滚边界 | 禁止 |
| 文件或浏览器本地草稿 | 无需数据库迁移 | 无法协作、审计、恢复，不能成为权威输入 | 仅可作临时 UI 状态 |
| PostgreSQL 基线指针 + append-only 草稿命令 | 稳定、可审计、支持乐观并发和 diff | 需要物化、校验和发布适配 | 选择 |

## Decision

新增 `gda_ontology.ontology_draft` 和 `gda_ontology.ontology_draft_change`：

1. 每个草稿绑定一个已发布的 `base_version_id` 和 `base_content_sha256`。
2. 每次编辑保存为一个带序号的 canonical change，而不是更新活动本体记录。
3. 服务端在事务内检查草稿状态、基线 revision、稳定 URI、实体引用、基数和继承环。
4. 服务端提供草稿模型、结构校验和语义 diff；结构校验通过后只允许提交到 `in_review`，该状态不代表完整质量门通过或允许发布。
5. 只有现有审批和 ontology publisher 流程可以把草稿物化为新的 SemVer 不可变包并切换 active pointer。
6. 公开 CIM viewer 继续只读，不能访问草稿路由。

### 首期实际能力

- 以活动发布版本的精确 hash 建立草稿，并显示基线是否仍为 active。
- 编辑策划领域范围内的实体类、数据属性和对象关系；技术代码、稳定 ID/URI 和关系端点身份受服务端约束。
- 支持属性 datatype、基数、关系端点、`subClassOf` 无环、重复代码和稳定 URI 冲突等结构校验。
- 以 deterministic diff 展示新增、修改、弃用和移除；每次变更进入 append-only history，并使用 revision 乐观并发和幂等键。
- 在编辑器中提供追加式撤销/重做、错误定位、校验报告和审阅提交。提交只产生 `in_review` 状态和审计事件。

首期不编辑来源概念全集，也不在浏览器中维护完整 OWL axiom、任意 SHACL restriction、映射证据或发布包 manifest。这样可以让 GIS 领域专家维护约 246 个策划模型对象，同时保留 5,284 个来源概念的只读权威性。

### 质量门与发布边界

`validate` 和 `submit` 当前只执行草稿结构门。报告会明确列出 SHACL、8 个 competency questions、OWL-RL、provenance/completeness 等后续质量门为 `pending_release_validation`，并返回 `publication_allowed: false`。因此 `in_review` 不是已批准或已发布；只有人工审批、现有 ontology compiler/publisher 完成完整质量门并创建新的不可变 SemVer 包后，才允许切换 active pointer。

路由层仅允许 `admin` 和 `standard_editor` 写入；`standard_reviewer` 可审阅读取，普通 `analyst` 和未认证请求不能访问草稿数据。数据库迁移只向运行角色授予两张草稿表的定向权限，变更历史禁止 UPDATE/DELETE，草稿基线身份由触发器锁定。

## Consequences

- **Positive**：活动版本不可变；变更有作者、顺序、版本基线和审计证据；可以处理并发编辑冲突；编辑器可以借鉴 Playground 但不继承其简化语义。
- **Negative**：需要将命令重放到 canonical DTO，并为发布器增加后续物化适配；首期编辑范围必须限制在策划领域模型。
- **Mitigation**：保留原始 change payload；以 P0 校验 URI/hash 和语义 diff；在审阅批准及任何生产发布前运行现有 SHACL、competency question、OWL-RL 和 provenance 质量门。草稿接口始终返回 `publication_allowed=false`。

## Revisit Trigger

- 需要多人实时协同同一草稿时，引入锁或 CRDT 前先测量冲突率。
- 需要支持完整 OWL axiom/SHACL 编辑时，扩展 change schema 和 RDF AST/extension store，而不是放宽未知字段丢失。
- 发布器具备草稿物化能力并通过回归测试后，才开放 `approved -> published` 的自动化流水线。
