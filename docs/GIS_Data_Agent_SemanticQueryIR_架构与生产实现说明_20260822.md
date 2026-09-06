# GIS Data Agent SemanticQueryIR 架构与生产实现说明

**文档类型**：技术架构设计、实现边界与生产落地说明

**版本**：v1.3

**日期**：2026-08-30

**适用范围**：GIS Data Agent、NL2Semantic2SQL、PostgreSQL/PostGIS 业务源、Liveability 与 Makani 数据源
**状态**：生产目标设计；当前实现状态单独标注，不把目标描述成已完成事实

## 1. 执行摘要

SemanticQueryIR 中的 IR 是 **Intermediate Representation**，中文为“中间表示”。在本项目中，`SemanticQueryIR` 是位于自然语言理解和物理 SQL 执行之间的、版本化的结构化查询意图合同。

它回答的是：

> 用户想查询哪些业务概念、采用什么操作、使用哪些维度和指标、有哪些过滤和空间关系、希望得到什么结果形状。

它不回答：

> 具体使用哪张物理表、哪个物理字段、哪一个数据库连接、怎样拼接任意 SQL。

生产实现的基本链路是：

```text
自然语言
  -> Policy precheck
  -> TaskFrame
  -> 语义资产召回
  -> 确定性路由
  -> SemanticQueryIR
  -> IR / 本体 / 语义 / 粒度 / 空间 / 策略校验
  -> LogicalPlan
  -> 语义绑定
  -> 确定性 SQL Compiler
  -> PhysicalPlan
  -> 数据源准入与只读执行
  -> ResultContract + Trace + Evidence
```

最重要的生产边界是：

1. 大模型最多生成受限的逻辑 IR，不生成可直接执行的 SQL。
2. 物理表和字段由已发布语义层绑定，不由模型自由选择。
3. 关系和空间谓词必须来自已审核本体/语义关系。
4. SQL 由确定性编译器生成，用户值使用参数绑定。
5. 任何校验失败都必须结构化拒绝、澄清或显式走迁移期 legacy fallback，不能静默改路线。
6. Benchmark 的 Gold SQL 和 Gold 结果只属于评测控制面，不能进入运行时 Prompt、语义层或缓存。

当前真实状态需要明确区分：

| 能力 | 当前状态 |
| --- | --- |
| 审核指标合同的确定性模板执行 | 已有生产执行路径 |
| 治理式自由问数（模型生成物理 SQL，随后校验） | 当前默认基线 `baseline_sql` |
| `gda.semantic_query_ir.v1` 类型和计划模型 | 已实现部分类型合同 |
| `AdHocSemanticQueryIR` 到 PostgreSQL/PostGIS 编译 | 已有可执行受限子集，profile 为 `semantic_ir_experimental` |
| 完整自由问数 SemanticQueryIR 生产主链 | 尚未整体晋级 |
| 以真实业务库配对 Benchmark 证明新路线优于基线 | 小范围真实配对已持平；完整能力范围的优势仍未证明 |

这里要区分两种“IR 产物”：

1. **基线观察性产物**：`baseline_sql` 先生成并通过治理校验 SQL，再由
   `build_shadow_semantic_plan_evidence()` 反向构造 IR；它的
   `execution_authority=false`，不能影响执行结果。
2. **候选可执行产物**：`semantic_ir_experimental` 由模型直接生成受限
   `AdHocSemanticQueryIR`，禁止携带 SQL、物理表名和 `selected_tables`；经过 IR schema、
   active binding、关系/空间、SQL guard、源准入和预算校验后，由
   `build_compiled_ad_hoc_semantic_plan()` 生成参数化 SQL 执行。

候选路线虽然可执行，但仍是受限 canary：未覆盖的 capability 必须结构化失败，不能静默
回退到模型直接写 SQL。当前默认入口仍是 `baseline_sql`，两条路线是否调整默认关系只能由
相同冻结题集的重复 paired evidence 决定。

## 2. 为什么需要 SemanticQueryIR

### 2.1 直接生成物理 SQL 的结构问题

传统 NL2SQL 让模型直接输出：

```text
自然语言 -> 模型 -> SELECT ... FROM public.some_table ...
```

即使在 SQL 解析、schema 白名单、只读检查和 PostGIS 校验之后，这条路径仍有结构性风险：

- 模型必须同时解决业务概念理解和物理资产选择；
- 表名相似、字段同名、历史表和同步表容易造成错误命中；
- 指标粒度、去重键和业务口径可能在 SQL 形成后才被发现；
- 空间关系、SRID、单位和几何角色容易依赖事后 SQL 修补；
- SQL 文本难以作为跨引擎、跨版本的稳定查询合同；
- 失败很难归因于意图理解、语义召回、关系选择、计划生成还是 SQL 编译。

### 2.2 IR 的结构性改进

SemanticQueryIR 将问题拆成两层：

```text
逻辑层：用户要查什么
  -> SemanticQueryIR

物理层：当前数据源如何执行
  -> Semantic binding + LogicalPlan + PhysicalPlan + SQL
```

这样可以让本体、语义层和元数据在 SQL 生成之前发挥作用，而不是只在 SQL 生成后做拦截。

### 2.3 IR 不是 JSON 包装的 SQL

如果 IR 中携带 `SELECT`、`FROM`、物理表名、物理字段名和任意表达式，然后再把它序列化成 JSON，它只是“SQL 换了外壳”，没有解决根本问题。

合格的 SemanticQueryIR 必须满足：

- 模型侧只使用稳定的逻辑实体和逻辑字段标识；
- 物理绑定在服务端语义层中解析；
- 允许的操作、聚合、过滤和空间关系由类型合同限定；
- 任意表达式和任意 SQL 不属于模型输出面；
- IR 可以被独立校验、指纹化、编译和重放。

## 3. IR 的标准边界

### 3.1 IR 是否有统一国际标准

没有一个名为“SemanticQueryIR”的统一国际标准。`Intermediate Representation` 是编译器和数据库系统中的通用架构概念，不是某个固定 JSON 格式。

与本项目相关的开放或成熟方案包括：

| 方案 | 主要定位 | 与本项目的关系 |
| --- | --- | --- |
| Substrait | 跨引擎关系查询计划与代数的开放规范 | 可作为 LogicalPlan/PhysicalPlan 的外部映射目标 |
| Apache Calcite RelNode | 关系代数和优化计划 API | 可借鉴算子模型，不直接作为内部 API 合同 |
| Apache Arrow Substrait 生态 | 跨语言、跨引擎计划交换 | 适合编译器互操作和 conformance 测试 |
| W3C SPARQL Algebra | RDF 查询代数 | 可参考图查询语义，不直接覆盖关系型 GIS 查询 |
| OGC GeoSPARQL | 地理空间 RDF 查询与谓词 | 可参考空间概念和谓词，不是完整 NL2SQL IR |
| OSSIE | 语义模型交换与分析语义 | 适合作为语义层交换投影，不是本项目运行时 IR |
| OKF | 人和 Agent 可读取的知识包 | 适合作为语义解释与知识上下文投影 |

因此，项目应明确表述为：

> `gda.semantic_query_ir.v1` 是 GIS Data Agent 的项目级、版本化语义查询中间表示合同；它借鉴关系代数和 GIS 空间操作思想，并保留向 Substrait 等标准映射的可能，但不声称自身就是某个现成国际标准。

### 3.2 为什么需要项目级合同

Substrait 等标准解决的是“查询计划如何交换和执行”，而 GIS Data Agent 还需要表达：

- 本体概念引用；
- 语义资产版本和 source scope；
- 指标合同和粒度；
- 数据源准入与权限；
- 多语言意图和澄清状态；
- 空间角色、SRID、距离单位和 CRS 策略；
- UI 可读证据和结果等价指纹。

这些项目治理信息需要作为外围合同与 IR 关联，而不应全部硬塞进通用关系代数。

## 4. 分层架构和职责边界

### 4.1 总体架构

```text
                    控制面
  技术元数据 / 本体 / 语义层 / 权限 / 版本 / Benchmark
        |              |             |          |
        v              v             v          v
  source scope   ontology refs   active bindings  policy
        \              |             /          /
         +------ ContextAsset Resolver ------+
                          |
                          v
                   SemanticQueryIR
                          |
                    Validators
                          |
                     LogicalPlan
                          |
                 deterministic compiler
                          |
                    PhysicalPlan
                          |
                 Postgres/PostGIS executor
                          |
               ResultContract / Evidence
```

现有架构评审图中的目标路线如下，图中将元数据控制面、TaskFrame、上下文资产、认证模板、自由问数 IR、逻辑计划、PostGIS 编译器、物理计划和显式旧路线能力缺口放在同一条生产链路中：

![统一 SemanticQueryIR 目标架构](/Users/zhouning/gisdataagent/docs/designs/assets/abu_dhabi_nl2semantic2sql_architecture/05_target_ir_architecture.png)

### 4.2 各层回答的问题

| 层 | 核心问题 | 典型内容 | 是否直接执行 |
| --- | --- | --- | --- |
| 技术元数据 | 物理上有哪些对象 | DB、schema、表、字段、类型、SRID、指纹 | 否 |
| 本体模型 | 业务世界有什么概念和关系 | 设施、道路、行政区、包含、邻接、分类 | 否 |
| 语义层 | 逻辑概念如何绑定为可执行资产 | entity、field、metric、grain、relationship、权限 | 间接提供准入 |
| ContextAsset | 当前问题允许看到哪些语义资产 | top-K 资产、字段、关系、指标、证据 | 否 |
| TaskFrame | 用户这次问题的初步结构 | 语言、操作、范围、结果形状、歧义 | 否 |
| SemanticQueryIR | 这次具体想查什么 | 投影、指标、过滤、连接、空间关系 | 否 |
| LogicalPlan | 用哪些引擎无关算子完成 | scan、join、filter、aggregate、sort | 否 |
| PhysicalPlan | 当前引擎如何执行 | 表、字段、参数、引擎、SQL 指纹 | 是执行前计划 |
| ResultContract | 结果如何被验证和展示 | schema、行数、指纹、截断、口径 | 否 |

### 4.3 本体的作用

本体不是 IR，也不是 SQL 编译器。它在生产链路中承担四类职责：

1. **概念 grounding**：把“设施”“行政区”“道路”等自然语言映射到稳定概念。
2. **关系约束**：声明“设施在行政区内”“地块属于分区”等合法关系候选。
3. **分类和同义词**：支持多语言标签、别名、父子分类和业务术语。
4. **语义解释**：为 IR 的实体、字段和空间谓词提供可解释来源。

本体存在并不意味着查询可执行。还必须存在 active semantic binding、source admission、权限和完整能力支持。

### 4.4 语义层的作用

语义层是 IR 到 SQL 的关键桥梁。它至少提供：

- `semantic_entity -> physical_table`；
- `semantic_field -> physical_field`；
- 字段角色（dimension、measure、identifier、geometry）；
- 指标聚合、去重键和粒度；
- 审核关系和空间关系；
- 单位、CRS、SRID 和数据质量约束；
- source_id、database、schema、discovery fingerprint；
- activation gate、review status 和版本。

IR 只引用逻辑标识，编译器从 active semantic layer 解析物理落点。

元数据控制面与 NL2Semantic2SQL 的关系如下。技术元数据负责发现事实，本体负责概念和关系，ContextAsset 负责在线窄化，SemanticQueryIR 和 validator 负责本次查询意图，compiler 和 source admission 负责执行准入：

![元数据控制面与 SemanticQueryIR 全链路关系](/Users/zhouning/gisdataagent/docs/designs/assets/abu_dhabi_nl2semantic2sql_architecture/03_metadata_relationship.png)

## 5. 生产查询链路

### 5.1 端到端流程

```text
1. 接收自然语言问题
2. 预检查权限、只读、敏感数据、来源范围和预算
3. 识别语言和基础操作，生成 TaskFrame
4. 从已发布本体/语义资产索引召回候选
5. 进行权限、source、review_status、版本和能力过滤
6. 确定性路由到 metric、template、IR 或澄清
7. 模型/规则仅提出受限 SemanticQueryIR
8. 校验 IR 的结构、概念、字段、指标、粒度、关系和空间能力
9. 将 IR 转为 LogicalPlan
10. 根据语义绑定编译为 PhysicalPlan 和参数化 SQL
11. 进行 SQL、只读、schema、表列、资源和 source admission 检查
12. 调用注册虚拟数据源执行只读查询
13. 生成 ResultContract、Trace、Evidence 和可读展示
```

### 5.2 确定性路由

路由由服务端 release policy 决定，不能由用户或模型直接指定：

```text
Policy precheck 失败
  -> 拒绝

唯一命中 active MetricDefinition
  -> reviewed metric contract

命中 active CertifiedQueryTemplate
  -> certified template

问题能由已认证 IR capability 表达
  -> SemanticQueryIR

问题超出能力但属于迁移白名单
  -> 显式 legacy fallback，并记录 gap

资产歧义、权限不足或关系未审核
  -> 澄清或拒绝
```

生产系统不能使用“失败后偷偷换路线”的逻辑。若发生 fallback，结果必须标识 `legacy_fallback`，并从新 IR 编译器的通过率中剔除。

### 5.3 大模型的生产职责

大模型可以用于：

- 从自然语言提取 TaskFrame；
- 在召回的逻辑资产中选择实体和字段；
- 生成受限 IR；
- 解释澄清问题和失败原因。

大模型不可以：

- 自行看到并挑选所有物理表；
- 输出物理表、物理字段和连接串作为执行授权；
- 生成 raw SQL 作为 IR 字段；
- 自行声明一个未审核的 join 或空间关系；
- 读取 Benchmark Gold SQL 或 Gold 结果；
- 失败后自行决定改走基线。

## 6. SemanticQueryIR 合同

### 6.1 当前正式版本标识

当前设计使用：

```text
gda.semantic_query_ir.v1
```

代码中同时存在当前受限的模型侧子集：

```text
gda.ad_hoc_semantic_query_ir.v1
```

二者不得混称：

- `SemanticQueryIR` 是统一生产目标合同；
- `AdHocSemanticQueryIR` 是当前可执行 Canary 的受限子集。

### 6.2 顶层结构

当前 `SemanticQueryIR` 顶层字段包括：

```yaml
schema_id: gda.semantic_query_ir.v1
route: reviewed_metric_contract | governed_sql_ast
semantic_version: <immutable-or-semver>
metric_contract_version: <optional>
metric_contract_id: <optional>
task_frame: <TaskFrame>
sources: [<SemanticSourceRef>]
operation: detail | aggregate
projections: [<SemanticProjection>]
predicates: [<SemanticPredicate>]
joins: [<SemanticJoin>]
group_expression_sha256s: [<sha256>]
order_by: [<SemanticOrder>]
result_limit: 1..1000000
limit_enforcement: sql | source_executor
```

### 6.3 TaskFrame

`TaskFrame` 是问题级上下文，不是执行计划：

```yaml
schema_id: gda.semantic_task_frame.v1
question_sha256: <sha256>
language: zh | en | ar
operation: detail | aggregate
source_ids: [12]
```

生产版本应继续扩展但保持向后兼容：

- 目标业务对象和候选概念；
- 时间范围和时间语义；
- 空间范围和空间关系；
- 结果形状（table、scalar、chart、map）；
- 歧义和澄清状态；
- 查询预算和用户策略上下文。

### 6.4 逻辑字段引用

模型面对的是：

```yaml
semantic_entity: liveability.facility
semantic_field: lifecycle_stage
```

而不是：

```yaml
table: public.dim_facilities
field: stage
```

物理标识只能由语义层和编译器解析。

### 6.5 投影、维度和指标

投影具有 `output_name`、`role`、`field_ref`、`aggregate` 和可选的 `derived_measure`。

支持的角色：

```text
attribute  非聚合属性
dimension  分组维度
metric     聚合指标
```

当前支持的基础聚合：

```text
count
count_distinct
sum
avg
min
max
```

当前支持的安全派生空间度量包括面积平方米和面积平方公里，但必须满足几何字段角色、单位和 CRS 合同。

### 6.6 过滤

当前过滤操作包括：

```text
eq、neq、in、not_in、gt、gte、lt、lte、contains、prefix、is_null、not_null
```

过滤值由参数绑定传入，不能被拼接为 SQL 文本。`is_null` 和 `not_null` 不携带值；`in` 和 `not_in` 必须携带非空值集合；普通标量过滤必须只有一个值。

### 6.7 连接和空间关系

IR 的连接包含：

```yaml
left_field_ref: <logical field>
right_field_ref: <logical field>
kind: equality | spatial
operator: eq | st_covers | st_contains | st_dwithin | st_within | st_intersects
distance_metres: <only for st_dwithin>
```

连接必须同时满足：

- 两端属于不同逻辑实体；
- 等值连接只能使用 `eq`；
- 空间连接不能使用 `eq`；
- `st_dwithin` 必须有有限距离；
- 关系在语义层中已审核并且端点、几何角色、SRID 和单位一致；
- 多实体图必须连通，不能存在孤立实体。

### 6.8 结果限制与排序

`result_limit` 是硬上限，必须同时满足产品 query policy 和 source executor 限制。聚合问题的默认排序可由 compiler 提供，但必须在证据中标记排序来源，不能让结果顺序隐式不稳定。

## 7. IR 校验体系

### 7.1 校验顺序

```text
Schema validation
  -> source scope
  -> semantic asset active/version
  -> ontology concept and relation
  -> field role/type/unit
  -> metric grain/additivity
  -> join graph and reviewed relation
  -> spatial CRS/SRID/distance
  -> policy/security/budget
  -> logical-plan coherence
```

校验失败必须返回机器可读的 `reason_codes`，例如：

```text
semantic_entity_not_active_or_ambiguous
semantic_field_not_active_or_ambiguous
semantic_ir_join_graph_disconnected
semantic_ir_not_activated
semantic_geometry_projection_rejected
semantic_derived_measure_requires_geometry
semantic_filter_operator_unsupported
```

### 7.2 不可绕过的检查

无论 metric、template、IR 还是 legacy 路线，都必须经过：

- 只读和单语句检查；
- source/schema 白名单；
- 物理表和字段准入；
- 已审核关系检查；
- 空间函数、SRID 和距离检查；
- LIMIT、超时和资源预算；
- 数据库执行前 schema/fingerprint 检查；
- 结果行数和截断证据。

IR 路线只是把更多语义检查前移，并不能取消 SQL 和数据库层安全检查。

## 8. LogicalPlan 与 PhysicalPlan

### 8.1 LogicalPlan

LogicalPlan 与数据库引擎无关，当前节点类型包括：

```text
scan
join
filter
aggregate
project
sort
limit
```

示例：

```text
scan(liveability.facility)
  -> aggregate(count facility_id)
  -> group_by(lifecycle_stage)
  -> sort(lifecycle_stage asc)
  -> limit(1000)
```

LogicalPlan 用于：

- 检查 IR 是否形成连贯算子图；
- 进行跨引擎规划；
- 做逻辑计划 golden 测试；
- 将“意图正确”和“SQL 细节正确”分开诊断。

### 8.2 PhysicalPlan

PhysicalPlan 绑定具体执行引擎和物理资产：

```yaml
schema_id: gda.semantic_physical_plan.v1
engine: postgresql_postgis
dialect: postgres
compilation_mode: compiled_semantic_ir
logical_plan_sha256: <sha256>
statement_sha256: <sha256>
source_ids: [12]
tables: [public.dim_facilities]
columns: [public.dim_facilities.stage, public.dim_facilities.facility_uuid]
spatial_operators: []
read_only: true
```

PhysicalPlan 必须携带精确 source、语义版本、资源版本和发现指纹，防止语义层和实际数据库结构漂移后继续执行。

## 9. 确定性 SQL Compiler

### 9.1 定义

确定性编译器是一个按照固定、可测试规则，将合法 IR/LogicalPlan 和 active semantic binding 转换成参数化 SQL 的程序。

它不是：

- 缓存；
- 大模型；
- SQL 修补脚本的集合；
- 把历史问题保存下来再返回；
- 允许模型输出 SQL 后换一个包装。

### 9.2 编译职责

编译器负责：

1. 解析逻辑实体到物理表；
2. 解析逻辑字段到物理字段；
3. 生成 compiler-owned alias；
4. 生成 SELECT、JOIN、WHERE、GROUP BY、ORDER BY 和 LIMIT；
5. 生成空间函数和 CRS 转换；
6. 将用户输入转为命名参数；
7. 生成 LogicalPlan、PhysicalPlan 和 SQL 指纹；
8. 在缺少唯一绑定或能力不支持时失败，不猜测。

### 9.3 示例

用户问题：

```text
按生命周期阶段统计设施数量
```

逻辑 IR：

```yaml
schema_id: gda.ad_hoc_semantic_query_ir.v1
language: zh
status: query
semantic_entity: liveability.facility
projections:
  - output_name: lifecycle_stage
    role: dimension
    field_ref:
      semantic_entity: liveability.facility
      semantic_field: lifecycle_stage
  - output_name: facility_count
    role: metric
    aggregate: count
    field_ref:
      semantic_entity: liveability.facility
      semantic_field: facility_id
```

语义层绑定：

```text
liveability.facility -> public.dim_facilities
lifecycle_stage     -> stage
facility_id         -> facility_uuid
```

编译器输出：

```sql
SELECT gda_source."stage" AS "lifecycle_stage",
       COUNT(gda_source."facility_uuid") AS "facility_count"
FROM public.dim_facilities AS gda_source
GROUP BY gda_source."stage"
ORDER BY "lifecycle_stage"
LIMIT 1000
```

真实生产实现中的表名来自语义层，不来自模型输出。

### 9.4 确定性的验证方式

相同以下输入时，SQL 结构必须稳定：

- IR 内容；
- semantic version；
- source/discovery fingerprint；
- active binding 版本；
- compiler version；
- policy version。

SQL 文本不要求与 Gold SQL 字符串完全相同，但结果合同应等价。评测比较结果列、类型、排序、行数、数值容差、空间谓词语义和结果指纹。

## 10. GIS 能力设计

### 10.1 GIS 不是平行管线

GIS 能力应作为 SemanticQueryIR 的 capability，而不是另建一条不受 IR 约束的空间问数管线：

```text
普通关系能力 + 空间能力
  -> 同一个 TaskFrame / SemanticQueryIR / LogicalPlan
```

### 10.2 空间语义对象

空间语义至少包含：

- geometry entity 和 geometry field；
- geometry type（Point、Polygon、LineString 等）；
- SRID/CRS；
- 空间关系（within、contains、covers、intersects、dwithin）；
- 距离单位和测量 CRS；
- 空间容器角色（行政区、社区、分区）；
- 几何质量和有效性约束。

### 10.3 空间校验

空间编译前应检查：

1. 左右端点均为已审核几何字段；
2. 关系方向与本体/语义关系一致；
3. SRID 可比，必要时按配置做确定性转换；
4. `dwithin` 距离非负且单位明确；
5. 不能把 raw geometry 当作普通展示字段无约束返回；
6. 空间函数属于允许 capability；
7. 结果行数和空间查询预算受控。

## 11. 两个业务源和跨库边界

### 11.1 当前业务源

```text
source A: liveability_data_20260730/public
source B: makani_sync_full/public
```

每个 source 必须有独立的：

- source_id；
- database/schema scope；
- discovery fingerprint；
- semantic version；
- table/field bindings；
- ontology mappings；
- relationship review state；
- query policy。

### 11.2 跨源查询的默认原则

不能把两个数据库连接串交给模型，也不能允许 IR 随意创建跨库物理 JOIN。生产跨源查询采用“应用层联邦”优先：

```text
FederatedSemanticQueryIR
  -> 每个 source 一个审核 metric/template 子计划
  -> 每个 source 独立编译和只读执行
  -> 应用层按明确 merge strategy 合并
```

当前联邦 IR 合同明确：

```yaml
cross_database_sql: false
cross_source_join: false
merge_strategy: independent_sections
```

只有在未来完成跨源主键、语义关系、权限、数据一致性和独立 Benchmark 后，才能增加跨源 JOIN capability。跨库结果必须明确标识各源、各子计划和合并规则。

## 12. 生产与实验实现的差异

### 12.1 当前默认基线

```text
自然语言
  -> grounding
  -> Gemini 3.7 Flash 生成物理 SQL
  -> SQL postprocess
  -> semantic SQL validator
  -> runtime guard
  -> 只读执行
```

唯一命中审核指标合同的查询可以跳过模型，直接使用服务端模板。

### 12.2 当前 IR Canary

```text
自然语言
  -> Gemini 3.7 Flash 生成 AdHocSemanticQueryIR
  -> semantic validator
  -> PostGIS compiler
  -> SQL validator
  -> 只读执行
```

代码明确禁止 IR 提案携带 SQL、物理表名和 `selected_tables`。但该路径目前使用 `semantic_ir_experimental` profile，说明它仍是受限候选路线，不能宣称已经覆盖全部生产自由问数能力。

### 12.3 生产化 IR 的晋级定义

生产化不是改字符串，而是满足以下条件：

| 门 | 必须证明的内容 |
| --- | --- |
| 合同门 | `gda.semantic_query_ir.v1` 兼容性、schema、版本和迁移策略 |
| 语义门 | 所有可执行逻辑引用都有唯一 active binding |
| 安全门 | 物理资产、关系、空间和只读约束均不可绕过 |
| 编译门 | 支持 capability 有确定性 compiler 和 LLM-free golden tests |
| 数据门 | 真实 PostgreSQL/PostGIS source admission 和 schema drift 检查 |
| 效果门 | 与 baseline 在冻结题集上配对结果等价/准确率达标 |
| 稳定门 | 重复运行、并发、p50/p95、超时和错误分布达标 |
| 运营门 | UI、Trace、版本、回放和故障归因完整 |
| 发布门 | shadow -> canary -> selective serve -> default new |

### 12.4 真实 Gemini 测试如何证明准确率不是答案硬编码

2026-08-30 的工程审计把“高准确率”拆成可验证的输入、路由、执行和评测证据。Makani
稳定恢复批次选取 180 道题，其中 153 道为业务语言题、27 道为技术目录控制题；180 道
均实际调用 `gemini-3.7-flash`，均走 `governed_free_form_llm`，没有使用直接指标合同
路由，180/180 通过结果合同。该批次使用同一启动字节快照，并在每道题开始前重新校验
benchmark/语义 artifact。

反硬编码审计脚本
[`scripts/audit_abu_dhabi_nl2sql_integrity.py`](../scripts/audit_abu_dhabi_nl2sql_integrity.py)
对当前运行时代码进行 AST 字符串常量和 prompt 渲染检查，结果为：

- 2823 个 case ID、2820 个问题文本在运行时代码中 0 命中；
- 930 个具体物理表名、928 个指标/Gold ID 和 canonical SQL 在运行时代码常量中 0 命中；
- 运行时不导入 benchmark/evaluator；
- 两份语义层中完整 benchmark case ID 和完整问题原文 0 命中；
- Gold SQL、Gold 结果、expected result 和源行标记不进入 baseline/IR prompt；
- benchmark 逐题声明不得用于 prompt/runtime asset；
- 稳定恢复批次 180/180 均为 Gemini 自由生成路由，确定性指标直达路由为 0；
- 180 个问题全部唯一，模型版本全部为 Gemini 3.7 Flash，生成 SQL 有 65 个唯一指纹。

因此，reviewed metric contract 的 canonical SQL 只能被理解为产品语义配置（有版本、表列
校验、审核状态和 checksum），不能等同于按题目作弊。它只覆盖明确的业务指标模式；普通
问题仍由 Gemini 在受限 grounding 上下文中生成提案，之后由 validator/compiler 和源准入
决定能否执行。审计快照位于
[`abu_dhabi_nl2sql_integrity_audit_20260830.json`](customer/abu_dhabi_liveability_site_validation/abu_dhabi_nl2sql_integrity_audit_20260830.json)。

这些证据支持“冻结、已审核、Gold 可验证子集内接近 100%”的结论，不支持“两个数据库所有
表和所有自然语言问法已经 100%”的结论。Liveability 当前 386/387 的 99.742% 是独立
cohort 的诊断结果，未重新调用模型；Makani 2328 题的 99.729% 是未启用最新 artifact
不可变门禁的历史全量测量。新的发布分数必须由同一冻结输入完整重跑得到。

### 12.5 实测后的职责分解与瓶颈定位

真实结果说明，`SemanticQueryIR` 不能被当作一个单独提高准确率的模型输出格式。高准确率
由整条链共同产生，而 IR 的价值主要在于把其中更多职责从模型收回确定性系统：

| 责任 | 当前 baseline | IR candidate | 实测反馈 |
|---|---|---|---|
| 问题理解 | Gemini | Gemini | 历史全量 4 个 unexpected refusal，仍是模型稳定性问题 |
| 资产解析 | 语义 grounding + Gemini 提表 | 语义 grounding + IR 逻辑实体 | 历史全量 2320/2325；唯一 binding 和字段身份是关键 |
| 指标口径 | reviewed contract 或 prompt | reviewed contract / IR metric ref | 审核合同可确定执行，但不能覆盖任意自由问题 |
| 物理绑定 | 模型提出，validator 审核 | compiler 从 active binding 解析 | IR 的核心治理收益 |
| SQL 生成 | Gemini | compiler | baseline 当前覆盖更广；IR capability 仍需逐项补齐 |
| 执行安全 | 两路线共用 guard/source admission | 两路线共用 guard/source admission | 180 与历史 2328 的 source governance 均为 100% |
| 正确性判定 | 独立 Gold result contract | 同一 comparator | 不能用 SQL 文本或路线状态代替结果等价 |

| 运行指标 | 180 题稳定恢复 | 2328 题历史全量诊断 |
|---|---:|---:|
| 最终通过 | 180/180 | 2323/2328（99.7852%） |
| `governed_free_form_llm` | 180 | 2305 |
| 确定性指标合同 | 0 | 16 |
| 平均生成延迟 | 8385.945 ms | 9949.508 ms |
| P95 生成延迟 | 21543.852 ms | 20548.730 ms |

因此，IR 晋级的判断标准不是“结构更先进”，而是同一 capability 下是否在结果等价、安全、
稳定性、延迟、失败可解释性和 compiler 覆盖上达到发布门。当前证据继续支持
`baseline_sql` 默认、`semantic_ir_experimental` 受限 canary 的组合。

## 13. Benchmark 设计

### 13.1 Benchmark 的目标

Benchmark 不是用来训练运行时，也不是用来制造命中合同的捷径。它必须回答：

- IR 是否正确表达问题意图；
- 语义召回是否找到正确业务资产；
- 关系和空间能力是否正确；
- compiler 是否生成等价结果；
- 新路线是否比基线更准确、稳定、可解释或成本更低。

### 13.2 题集分层

至少分为：

| Track | 典型能力 |
| --- | --- |
| Detail | 单实体明细、过滤、排序、limit |
| Aggregate | count、avg、sum、min、max、group-by |
| Metric | 去重、口径、指标合同、粒度 |
| Relation | 审核等值 join、维度补充 |
| GIS | within、contains、covers、intersects、dwithin、面积 |
| Time | 时间范围、比较、快照和生命周期 |
| Federation | 两个 source 独立子计划与应用层合并 |
| Adversarial | 歧义、未审核关系、越权、敏感数据和不支持能力 |

每个 track 应有 validation、holdout 和 challenge split，不能只用简单的“1+1”问题。

### 13.3 Gold 的层级

Gold 不应只有 Gold SQL。应至少包括：

```text
Gold TaskFrame
Gold semantic assets
Gold ontology concept / relation
Gold logical plan
Gold result contract
Gold SQL（仅 evaluator 使用）
```

Gold SQL 只是评测参考，不是运行时提示，更不能写入语义层。

### 13.4 两条路线如何比较

Baseline 和 IR 必须在相同条件下配对运行：

- 同一题集 manifest；
- 同一真实 source 快照；
- 同一 metadata/discovery/profile fingerprint；
- 同一本体和语义版本；
- 同一模型、推理参数、并发、超时和执行器；
- 同一 evaluator 版本。

比较指标包括：

- asset resolution recall；
- IR validity rate；
- logical-plan correctness；
- result-contract equivalence；
- exact/semantic answer accuracy；
- safety rejection recall；
- compiler failure rate；
- legacy fallback rate；
- p50/p95 总耗时和数据库耗时；
- token、模型调用次数和执行成本；
- 跨轮稳定性。

不能用 SQL 文本相似度代替结果等价，也不能把审核指标合同控制题当作 IR 编译器增益。

### 13.5 生产评测禁止事项

- 不允许按照 benchmark case_id 写分支；
- 不允许把题目、Gold SQL、Gold 结果注入 Prompt；
- 不允许针对真实表名写特例；
- 不允许 IR 失败后静默回退并计为 IR 成功；
- 不允许使用历史结果缓存冒充重新执行；
- 不允许只报告通过题，不报告 unsupported、澄清和安全拒绝。

Benchmark 子系统本身也必须与运行时隔离。冻结 manifest、source/语义指纹和 Gold 权威进入评测控制面；baseline 和候选路线分别运行，由统一评估器按结果合同比较，再把分层结果和失败分类投影到 UI，不把 Gold 反向注入问数链路：

![Benchmark 控制面、执行面和发布门](/Users/zhouning/gisdataagent/docs/designs/assets/abu_dhabi_nl2semantic2sql_architecture/08_benchmark_subsystem.png)

## 14. UI 和可解释性

人工验证者需要在 GIS Data Agent 左侧对话框及相关管理视图中看到本次查询的可读证据。普通用户优先显示业务概念和口径，管理员可展开受控技术细节。

### 14.1 问数结果应显示

```text
查询结果
总耗时 / 数据库耗时 / 模型耗时
返回行数和当前展示范围
命中语义资产
采用路线：metric / template / semantic_ir / baseline / fallback
本体版本和语义版本
数据源、数据库、schema 和只读状态
IR 摘要：实体、维度、指标、过滤、空间关系
校验结论和失败原因
编译器版本与 SQL hash
结果等价指纹
```

### 14.2 管理视图应显示

- 数据源发现状态、表/字段数量、fingerprint；
- 本体概念、关系、审核状态和来源；
- 语义实体到物理表/字段的绑定；
- metric/template/IR capability 的激活状态；
- Benchmark manifest、分层结果和基线/候选差异；
- 失败按理解、召回、语义、IR、编译、执行分类。

Gold SQL、Gold 结果、凭据和未脱敏内部错误不得展示给普通运行时用户。

## 15. 当前代码映射

| 模块 | 作用 | 当前状态 |
| --- | --- | --- |
| `data_agent/semantic_query_ir.py` | IR、校验、LogicalPlan、PhysicalPlan、PostGIS 编译和联邦 IR 类型 | 已实现部分合同和受限编译器 |
| `governed_virtual_nl2sql.py` | baseline/Canary 入口、上下文召回、运行时治理 | baseline 默认，IR profile 隔离 |
| `abu_dhabi_nl2semantic2sql_v2_evaluator.py` | 路线证据校验和配对评测支撑 | 已完成小范围真实源配对；完整能力配对仍需扩展 |
| `abu_dhabi_semantic_candidates.py` | 业务资产候选和审核边界 | 已有候选/发布机制 |
| `abu_dhabi_dictionary_semantic_publisher.py` | 数据字典到语义发布输入 | 已有字典对齐和发布工具 |
| `abu_dhabi_relationship_candidates.py` | 关系候选生成 | 候选默认不具备执行授权 |
| `abu_dhabi_federated_benchmark.py` | 跨源独立子计划/合并评测 | 当前坚持不做跨数据库 SQL |

代码中的关键模型：

```text
SemanticTaskFrame
SemanticModelFieldRef
SemanticIRProjection
SemanticFilter
SemanticIRJoin
AdHocSemanticQueryIR
SemanticQueryIR
SemanticIRValidationReport
SemanticLogicalPlan
SemanticPhysicalPlan
FederatedSemanticQueryIR
```

## 16. 生产实施路线

### 阶段 0：合同冻结

- 冻结 `gda.semantic_query_ir.v1` schema；
- 定义错误码、版本兼容和弃用策略；
- 约束模型输出面；
- 为每个字段和操作建立 capability registry。

验收：schema、validator 和反例测试稳定，模型无法输出物理 SQL 逃生字段。

### 阶段 1：语义和元数据收敛

- 完成 Liveability 与 Makani 全量技术元数据登记；
- 对候选资产按 source、表、字段、关系和业务概念分层审核；
- 建立本体概念到语义资产的稳定 crosswalk；
- 所有 active binding 关联 discovery fingerprint。

验收：支持问题的每个逻辑引用都有唯一 active binding，未审核候选不能执行。

### 阶段 2：IR vertical slice

优先生产化以下能力：

```text
单实体 detail/filter/order/limit
基础 aggregate/group-by
count/count_distinct/avg
审核等值 join
within/contains/covers/intersects
面积平方米/平方公里
```

验收：LLM-free golden、PostGIS source admission、结果合同等价和安全测试通过。

### 阶段 3：真实配对 Benchmark

- 在当前 LAN 环境中冻结 manifest 和 source fingerprint；
- baseline 与 IR 同题、同数据、同配置配对执行；
- 先小探针，再完整 validation/holdout/challenge；
- 多轮运行统计稳定性和置信区间；
- 失败必须归因到 capability，不得改 Prompt 特例。

验收：每个 capability 达到预先批准阈值，新路线在安全、结果正确性和稳定性上不低于基线，优势以数据证明。

### 阶段 4：Selective serve

- 仅对已通过 capability gate 的问题进入 IR 默认服务；
- 其他问题显式保持 baseline 或澄清；
- UI 显示路线和 fallback；
- 监控 compiler failure、fallback、延迟和结果投诉。

### 阶段 5：Default new 与旧路线收敛

- IR 路线成为已认证能力的默认路线；
- baseline 仅作为明确的迁移兼容路线；
- 每个 legacy capability 设定退出条件和截止时间；
- 不因追求统一而强行覆盖尚未认证的复杂 SQL。

## 17. 架构决策和取舍

### ADR-SQIR-001：模型输出逻辑 IR，不输出物理 SQL

**决策**：生产模型输出受限 SemanticQueryIR。

**理由**：将物理资产绑定和 SQL 生成收回系统控制面，降低表选择、注入和口径漂移风险。

**代价**：需要建设语义层、compiler 和 capability registry，复杂查询不能立即覆盖。
**重审条件**：若某类能力无法通过 IR 或澄清表达，先加入明确 capability，再评估是否扩展模型权限。

### ADR-SQIR-002：项目级 IR，保留标准映射

**决策**：内部使用 `gda.semantic_query_ir.v1`，LogicalPlan 设计保持向 Substrait 映射的兼容性。

**理由**：项目需要 source、ontology、semantic version、GIS 和 evidence 字段，单一外部标准不足以承担全部治理需求。

**代价**：需要维护版本和转换器。
**重审条件**：Substrait 或其他标准满足项目治理扩展且具备稳定版本后，可增加标准化交换格式。

### ADR-SQIR-003：应用层联邦优先

**决策**：跨库默认独立子计划和应用层合并，不生成跨数据库 SQL。

**理由**：两个业务源独立治理，跨源 JOIN 的关系、权限、一致性和失败语义需要单独证明。

**代价**：不能立即支持任意跨源关联。
**重审条件**：跨源关系、数据一致性、权限和 Benchmark 全部具备后，按 capability 增加。

## 18. 结论

SemanticQueryIR 是将 GIS Data Agent 从“模型生成物理 SQL”推进到“模型理解业务意图，系统治理和编译查询”的关键中间合同。

它的生产形态必须是：

```text
模型/规则生成逻辑 IR
  -> 本体和语义层约束
  -> 版本化校验
  -> 引擎无关 LogicalPlan
  -> active binding 驱动的确定性 Compiler
  -> PhysicalPlan
  -> 只读执行与可审计证据
```

当前项目已经有 IR 类型、受限编译器、计划证据和联邦独立分段设计，但自由问数 IR 仍处于实验/Canary 级别。面向产品和生产的正确推进方式，是按 capability 逐项完成语义覆盖、compiler、真实配对 Benchmark、安全测试、稳定性测试和 UI 证据，再按发布门逐步切流，而不是把实验标记改成生产标记。

相关现有设计与实现：

- [统一 NL2Semantic2SQL 架构设计](/Users/zhouning/gisdataagent/docs/designs/abu_dhabi_unified_nl2semantic2sql_architecture_design_2026-08-20.md)
- [语义召回技术实现说明](/Users/zhouning/gisdataagent/docs/NL2Semantic2SQL_语义召回技术实现说明_20260822.md)
- [SemanticQueryIR 实现](/Users/zhouning/gisdataagent/data_agent/semantic_query_ir.py)
- [治理式 NL2SQL 入口](/Users/zhouning/gisdataagent/data_agent/governed_virtual_nl2sql.py)

## 19. 2026-09-02 实测更新（当前发布资产）

本节覆盖 2026-09-02 在局域网环境使用当前 Liveability 发布资产和
`gemini-3.7-flash` 的新证据。它不覆盖历史报告中的旧语义层或旧源指纹。

### 19.1 当前资产和最新表卡

- 当前源：`source_id=12`，数据库 `liveability_data_20260730`，地址
  `10.255.254.109:5444`，发现指纹
  `5c921e81ad6755b1dddb1f9d93184fdfaf5b3eb50681564b53db6e3866702052`。
- 当前语义层：
  `liveability_data_20260730_semantic_layer_v21_answerability_data_quality_20260902.json`。
- 当前本体：
  `liveability_data_20260730_ontology_v20_answerability_data_quality_20260902.json`。
- 最新客户表卡：`/Users/zhouning/Downloads/阿布扎比/liveability_kb.zip`，SHA-256
  `b4e23bc718a02dd536071492f41fcc26535f8f9693fa228bf3635a5ec6fcc00f`；165/165
  张表匹配，3479/3479 个显式字段匹配。表卡只作为版本化语义证据，不含 Gold 结果注入。
- 当前技术目录为 176 张资源、3778 个字段；业务语义审核仍未全覆盖，故“技术配置完整”
  不等于“全库业务可回答”。

### 19.2 Semantic IR 全量基线

使用 v8 冻结 benchmark（76 题，其中 27 个 Gold 查询题、49 个拒答/澄清/不可用边界题），
同一 v21 语义层、同一源指纹、`gemini-3.7-flash`、`reasoning=medium`，无 Gold SQL/结果
进入运行时，得到：

| 指标 | `semantic_ir_experimental` |
|---|---:|
| 产品合同通过 | 50/76（65.79%） |
| Gold 严格结果等价 | 5/27（18.52%） |
| 查询执行成功 | 14/27（51.85%） |
| 基础设施失败 | 0 |
| 拒答 precision / recall | 86.54% / 91.84% |

主要失败是双极值、分段及成员明细、条件聚合、Top-N 分组、复合投影和模型随机拒答；这些
是能力覆盖和模型稳定性问题，不应通过增加题号分支或固定答案修复。结论是：
`baseline_sql` 仍为默认生产路线，IR 继续保持候选/影子路线。

### 19.3 本轮协议归一化与聚合条件修复

针对 Gemini 的可复现表示层变体，新增了无损归一化：`proposal` 单容器、
`projection_type`、`op/val`、数组形式 OR filter、`field_alias`、`order_item`、展示
metadata，以及逻辑字段中的空格/连字符分隔差异。归一化不增加实体、字段、关系、过滤
值或 SQL 能力；所有结果仍必须经过同一 Pydantic IR、active binding、关系审核、只读门禁
和确定性编译器。冲突或无法证明等价的表示继续失败关闭。

同时增加了通用 `having_filters` 能力：行级 `filters` 编译为 `WHERE`，明确声明聚合、
字段、操作符和值的 `having_filters` 编译为 `HAVING`。因此“按设施类型汇总后筛选总需求
大于 0”不会被错误地改写成逐行过滤。该能力不绑定任何题号或 Gold 结果，适用于所有
已审核的数值字段。

回归验证：聚焦产品/IR/候选/记分卡套件共 306 passed；其中协议归一化专项为 25 项，
不能把测试数量等同于业务准确率。F016 双极值真实端到端复测报告
`liveability_customer_strict_v8_gemini37flash_semantic_ir_f016_extreme_v33_20260902.json`
显示：1/1 查询执行成功、1/1 Gold 结果等价、基础设施失败 0；生成的 SQL 使用受控
`HAVING SUM(demand_current)>0`、CTE 和 `UNION ALL`，而不是题号分支或固定答案。该单题
结果不能替代 27 题全量配对指标，历史全量 IR 基线仍为 14/27 执行成功（51.85%）。

### 19.4 发布边界

当前证据不能支持“两库全库任意问数已完成”或“准确率接近 100%”的泛化声明。完整目标仍
需完成业务语义、关系/口径审核、全库字段和操作覆盖、双路线 paired/stability benchmark，
并将不可回答项明确登记为数据质量、语义缺口、关系未审核、指标口径未确认或空数据问题。

## 20. 2026-09-04 当前 v34 语义层与 Semantic IR 回归更新

### 20.1 当前运行资产

- 当前源仍为 `source_id=12`：`liveability_data_20260730/public`，端点
  `10.255.254.109:5444`，发现指纹
  `5c921e81ad6755b1dddb1f9d93184fdfaf5b3eb50681564b53db6e3866702052`。
- 本轮运行语义层：
  `docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_semantic_layer_v34_enum_domains_20260904.json`。
- 对应本体：
  `docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_ontology_v33_enum_domains_20260904.json`。
- 语义层和本体均由最新表卡 `liveability_kb.zip` 生成，表卡 SHA-256 为
  `b4e23bc718a02dd536071492f41fcc26535f8f9693fa228bf3635a5ec6fcc00f`；165/165 张表卡、
  3479/3479 个字段匹配。该覆盖表示表卡到物理元数据的覆盖，不表示 3479 个字段都已经
  获得可执行的业务口径审核。

### 20.2 两项通用修复

1. **Gemini 协议容器归一化**：模型偶尔将 `partition_by` 单元素数组输出成字符串，或将
   `distinct_rows` 输出成 `"false"`。系统现在只对这些可证明等价的表示进行归一化，随后
   仍经过严格 Pydantic schema、语义白名单、关系审核和编译门禁；冲突值和未知结构继续
   失败关闭。该修复不增加字段、表、关系、过滤值或 SQL 能力。
2. **枚举源值大小写冲突修复**：表卡语义可能同时出现 `AP50` 与 `ap50`。编译器现在以
   `source_value_domain_observed` 的当前只读审计值作为执行拼写，避免大小写碰撞把合法的
   `Target stage` 映射成不存在的物理值。该修复只选择已观测的源值，不发明新值。

### 20.3 真实 76 题回归结果

报告：
`docs/customer/abu_dhabi_liveability_site_validation/liveability_v36_gemini37flash_semantic_ir_full76_representation_enumfix_20260904.json`。

| 指标 | v35 修复前 | v36 修复后 |
| --- | ---: | ---: |
| 总题通过 | 73/76（96.05%） | **76/76（100%）** |
| 业务语言查询题 Gold 等价 | 25/28（89.29%） | **28/28（100%）** |
| 查询执行成功 | 26/28（92.86%） | **28/28（100%）** |
| 拒答 precision / recall | 100% / 100% | **100% / 100%** |
| 基础设施失败 | 0 | **0** |
| 平均模型延迟 | 7165 ms | **6748 ms** |
| P95 模型延迟 | 12367 ms | **13870 ms** |

三道失败题的独立归因如下：F016 和 F052 是 Gemini 输出容器类型错误，F019 是语义层
枚举键大小写碰撞；三题均通过通用修复后重测。F019 的当前源只读诊断实际返回 8 个区，
与新 Gold 合同一致，因此不是业务数据库漂移。

### 20.4 反作弊和发布边界

本轮 76 题仍使用 Gemini `semantic_ir_experimental`，Gold SQL、Gold 结果、题号和源行
均未进入运行时 prompt 或语义资产；修复代码没有新增题号分支。结果中的“100%”只表示
当前 v14 冻结 benchmark 的 76 个样本在当前 v34 语义层和 source_id=12 上通过，不能外推
为两库全库任意问题 100% 可回答。`baseline_sql` 仍是默认生产路线，Semantic IR 仍为
候选/影子路线，发布切换需要 paired baseline、重复稳定性、全库语义审核和关系/指标合同
覆盖证据。

### 20.5 后续推进

- 对 baseline 剩余失败题 F024、F030、F034、F099 做同样的通用归因和配对重测；
- 将 165 张表卡继续拆成“技术元数据已覆盖 / 业务语义已审核 / 可执行指标或关系已审核”
  三种状态，在系统语义层 UI 中可见；
- 扩展全库 benchmark：每张表、字段角色、枚举值域、时间阶段、空间关系、聚合、排序、
  可视化和拒答边界均需有代表性题型；
- 对 Makani 与 Liveability 分别运行 baseline 与 Semantic IR 的同源 paired/stability
  评测，不能把不同源、不同语义版本的历史百分比拼接成一个总准确率。

## 21. 2026-09-05 v37 双路线配对回归

在业务源恢复后，使用同一 v37 语义层和同一 v14 冻结 benchmark 完成 baseline 与
`semantic_ir_experimental` 的配对实测。baseline v51：75/76 总题通过、28/28 查询执行、
27/28 Gold 等价；Semantic IR v52：76/76 总题通过、28/28 查询执行、28/28 Gold 等价；
两条路线拒答均为 48/48，precision/recall 均为 100%，基础设施失败均为 0。

配对报告：
`docs/customer/abu_dhabi_liveability_site_validation/liveability_v51_v52_dual_route_pairwise_20260905.json`。
唯一 baseline 差异是 F032：baseline 遗漏了问题要求的 `needed_ap50` 度量列，Semantic IR
通过同一题。F024 在本轮按已发布的等价结果合同通过。候选路线 release gate 仍关闭，需重复稳定性与更大范围全库 benchmark 后再
考虑晋级。运行时现已增加通用排名投影门禁，缺少首要排序度量时触发模型重试，不添加题目特判。反硬编码审计报告：
`docs/customer/abu_dhabi_liveability_site_validation/abu_dhabi_nl2sql_integrity_audit_20260905.json`，
结果通过且未发现题目、Gold 或固定答案泄漏。

## 2026-09-06 语义标准互操作

`data_agent.semantic_interop` 提供统一的标准投影与显式导入。业务本体 overlay 支持
OWL/RDF Turtle、JSON-LD、SKOS、SHACL；多语言语义层支持上述 RDF 格式、内部 YAML 和
Apache Ossie Core Metadata Specification `0.2.0.dev0` YAML。Ossie 仅是语义交换格式，
不替代 SemanticQueryIR 的类型合同、空间编译器、源指纹和执行门禁。完整运行时信息通过
GDA 扩展携带，严格导入验证扩展 hash；无扩展的外部模型只能 projection-only，禁止直接执行。
