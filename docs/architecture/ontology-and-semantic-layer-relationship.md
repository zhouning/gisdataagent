# GIS Data Agent 本体模型与语义层的关系

## 结论

在 GIS Data Agent 中，本体模型是“语义定义和治理层”，语义层是“面向 Agent 查询的语义服务层”。

```text
本体模型
定义业务概念、属性、关系、约束和稳定标识
        ↓
映射与治理
绑定数据模型、源表、源字段、Gold 视图和质量状态
        ↓
语义层
把这些语义转换成 Agent 可检索、可过滤、可生成 SQL 的上下文
        ↓
NL2SQL / 空间分析 / 指标计算 / 结果解释
```

## 1. 本体模型负责定义语义

当前 GIS Data Agent 的本体运行时位于 `data_agent/ontology/`，管理的主要内容包括：

- 领域类，例如 `Building`、`Plot`、`Road`、`Asset`；
- 数据属性，例如建筑用途、物理状态、面积、观测时间；
- 对象关系，例如 `Building locatedIn Plot`；
- 继承关系、状态、过程、角色和观测；
- 值域、基数、几何语义和约束；
- 稳定 URI、版本、内容哈希、溯源和审阅状态；
- 本体类、属性、关系与源对象的映射。

本体回答的是：

> “建筑是什么？建筑和地块有什么关系？物理状态有哪些合法含义？这个关系是否经过治理确认？”

自然资源本体和 DMT 本体通过 `ontology_key` 隔离。它们可以共享技术运行时，但各自拥有独立的命名空间、版本和概念集合。

相关实现见 [OntologyService](../../data_agent/ontology/service.py) 和 [registry.py](../../data_agent/ontology/registry.py)。

## 2. 语义层负责让 Agent 使用这些语义

当前项目中的语义层主要由以下几类内容组成：

- `agent_semantic_sources`：数据源或表级元数据；
- `agent_semantic_registry`：字段别名、语义域、单位、描述、几何标记；
- `agent_semantic_domains`：业务分类层级和自定义域；
- `agent_semantic_models`：实体、维度、度量、指标和空间维度；
- `semantic_catalog.yaml`：静态领域词典、空间操作和指标模板；
- Gold 语义视图契约；
- 语义解析、字段匹配和 SQL 过滤生成逻辑。

语义层回答的是：

> “用户说‘建筑面积’时应该匹配哪个字段？这个字段的单位是什么？应该使用哪张表或哪个 Gold 视图？能否生成面积统计 SQL？”

例如，语义层会把：

```text
“统计住宅建筑面积最大的地块”
```

解析成类似：

```text
候选数据源：gold.vw_plot_building_address
候选属性：building_use、building_area
过滤条件：building_use = 住宅
聚合方式：SUM(building_area)
排序方式：DESC
空间输出：geom
```

`data_agent/semantic_layer.py` 中的 `resolve_semantic_context()` 会匹配表名、显示名、同义词、字段别名、语义域、区域和空间操作；`build_context_prompt()` 再把这些内容注入 NL2SQL 提示词。

前端的“语义层”页面也主要管理这些表级和字段级标注，见 [SemanticLayerTab.tsx](../../frontend/src/components/datapanel/SemanticLayerTab.tsx)。

## 3. 二者之间的对应关系

| 本体模型 | 语义层 | 作用 |
|---|---|---|
| `Building` 类 | 表或 Gold 视图中的建筑数据源 | 确定查询对象 |
| `physicalStatus` 属性 | `physical_status` 字段的别名、描述和语义域 | 确定字段含义 |
| `locatedIn` 关系 | JOIN 路径或语义视图依赖 | 确定如何关联 |
| 值域和状态约束 | 过滤值、代码表、枚举语义 | 限制合法条件 |
| 几何属性和空间关系 | `geom`、SRID、空间操作 | 约束空间查询 |
| 本体映射状态 | 表/字段启用状态、质量状态、置信度 | 决定是否允许进入查询 |
| 本体版本 | 语义模型版本、视图契约版本 | 保证查询结果可复现 |

因此，本体模型可以被看作语义层的“规范来源”，语义层则是本体面向 Agent、SQL 和数据服务的“运行投影”。

## 4. 当前代码中的真实关系

当前系统已经具备两套能力，但还不是完全打通的单一运行链路。

### 本体查询链路

本体服务可以执行受治理的本体查询，例如：

- 概念解释；
- 层级浏览；
- 关系路径；
- 状态转换规则；
- Schema 映射查询；
- RDF/SHACL 投影。

这条链路由 `OntologyService` 和 `OntologyQueryEngine` 管理，主要解决“业务概念和本体关系是什么”。

### 语义问数链路

NL2SQL 目前主要走：

```text
用户问题
  ↓
resolve_semantic_context()
  ↓
匹配表、字段、别名、语义域、空间操作
  ↓
build_context_prompt()
  ↓
生成 SQL
  ↓
PostGIS / 数据库执行
```

`nl2sql_grounding.py` 会调用语义层解析结果来构建候选表和提示上下文。这条链路主要解决“如何把自然语言问题落到可执行查询”。

从当前代码看，`semantic_layer.py` 并不会自动调用 `OntologyService`。因此目前存在这样的情况：

- 语义层可以使用表级和字段级标注独立工作；
- 本体服务也可以独立执行概念和关系查询；
- 两者之间已有映射和治理基础，但还没有形成“本体版本自动驱动语义层”的强制绑定。

换句话说，当前是“并行能力 + 部分映射”，还不是完整的：

```text
OntologyService → Semantic Layer → NL2SQL
```

## 5. DMT 中的实际例子

DMT 本体可以定义：

```text
Building
  ├── buildingUse
  ├── physicalStatus
  ├── geometry
  └── locatedIn → Plot
```

语义层则需要把这些概念落实到可查询对象，例如：

```text
Gold 视图：gold.vw_plot_building_address
字段：
  building_id
  building_use
  physical_status
  geom
  plot_id
  district_id
```

用户提问：

> “某地块中有哪些仍在使用的建筑？”

本体模型负责识别：

- “地块”是 `Plot`；
- “建筑”是 `Building`；
- “位于”对应 `locatedIn`；
- “仍在使用”是建筑状态条件，而不是任意字符串匹配。

语义层负责落实：

- 使用哪个 Gold 视图；
- 使用 `plot_id` 和 `building_id`；
- 过滤 `physical_status` 的合法值；
- 应用 `is_current = true`；
- 返回 `geom` 和数据质量信息。

DMT 的 [Gold 语义视图契约](../customer/dmt_data_model_v1/model/dmt_semantic_view_contracts.md) 就是本体语义和实际查询服务之间的中间契约。

## 6. 两者不能混淆

本体模型不是：

- 一组表名和字段别名；
- 一个 NL2SQL 提示词；
- 一个 Gold 视图；
- 保存业务记录的数据库；
- 单纯的知识图谱实例数据。

语义层也不是：

- 本体类和关系的唯一权威来源；
- 任意字段别名的集合；
- 可以自行推断业务含义的模糊匹配器。

尤其要注意，语义层中的别名和自动匹配只能帮助召回候选。它不能替代本体治理，也不能自动确认：

- 业务主键；
- 跨源唯一关系；
- 权威数据源；
- 空间匹配规则；
- 敏感字段是否允许进入默认查询；
- 两个行业中的同名对象是否真的等价。

## 7. 更合理的目标架构

后续建议把二者明确组织成三层：

```text
本体权威层
  类、属性、关系、值域、约束、版本、来源证据
        ↓
语义绑定层
  ontology_key、concept_id、property_id、relation_id
  对应表、字段、Gold 视图、指标、空间操作
        ↓
语义服务层
  同义词解析、查询上下文、SQL 模板、指标计算、权限和质量门禁
```

具体来说：

1. 语义层的表和字段标注应引用本体的稳定 ID，而不是只保存字符串别名；
2. 每个语义模型应绑定 `ontology_key` 和本体版本；
3. 本体属性应能反向检查是否有可用字段或 Gold 视图实现；
4. 本体关系应能反向检查是否存在可信 JOIN 或空间关系；
5. 只有 `confirmed` 映射、已确认 SRID、主键和敏感级别的数据，才进入默认 Agent 查询；
6. `candidate` 或 `review_required` 映射可以用于审阅和提示，但不应作为无条件事实执行。

## 一句话概括

> 本体模型规定“语义是什么”，语义层负责“如何让 Agent 使用这些语义”；本体是规范和治理依据，语义层是查询和服务投影。
