# 空间语义层 — 技术架构与对比分析

> GIS Data Agent (ADK Edition) PRD P2 F1
> 版本: 1.0 | 日期: 2026-02-27 | Commit: `abbc820`

---

## 目录

- [1. 实现概览](#1-实现概览)
- [2. 技术架构](#2-技术架构)
- [3. 与 MetricFlow 的对比分析](#3-与-metricflow-的对比分析)
- [4. 与知识图谱和本体的关系](#4-与知识图谱和本体的关系)
- [5. 未来演进方向](#5-未来演进方向)

---

## 1. 实现概览

### 1.1 解决的问题

Agent 在每次请求中调用 `describe_table()` 获取列名后，必须猜测字段含义：`zmj` = 面积？`dlmc` = 地类名称？行业数据显示，原始 schema 下 text-to-SQL 准确率约 17%，语义层介入后可提升至约 90%。

### 1.2 设计目标

- 轻量级 YAML 目录 + DB 注册表 + Python 解析器 + prompt 注入
- 遵循项目既有的 `[语义上下文]` 注入模式（与 `[用户空间记忆]`、`[上轮分析上下文]` 同模式）
- 零配置可用（自动发现），渐进增强（手工标注）

### 1.3 文件清单

| 文件 | 用途 | 行数 |
|------|------|------|
| `data_agent/semantic_layer.py` | 核心模块：目录加载、同义词匹配、解析器、上下文构建、自动注册、5 个 ADK 工具 | ~420 |
| `data_agent/semantic_catalog.yaml` | 静态 YAML 目录：15 个语义域、7 个区域组、8 个空间操作、4 个指标模板 | 175 |
| `data_agent/migrations/009_create_semantic_registry.sql` | DB 迁移：`agent_semantic_registry` + `agent_semantic_sources` 两表 | 43 |
| `data_agent/test_semantic_layer.py` | 47 项测试：目录加载、别名匹配、解析、prompt 构建、CRUD 校验、完整性 | ~280 |

修改的文件：

| 文件 | 变更 |
|------|------|
| `database_tools.py` | 增加 `T_SEMANTIC_REGISTRY`/`T_SEMANTIC_SOURCES` 常量；`describe_table()` 中增加自动注册调用 |
| `agent.py` | 导入 5 个语义工具；注册到 GeneralProcessing（全部 5 个）+ PlannerExplorer（3 个只读） |
| `app.py` | 启动时 `ensure_semantic_tables()`；pipeline 执行前注入 `[语义上下文]` |
| `prompts/general.yaml` | 增加 §1 语义上下文优先规则 + §1.5 回退到 describe_table |

---

## 2. 技术架构

### 2.1 三层架构

| 层 | 存储 | 生命周期 | 内容 |
|---|---|---|---|
| **静态知识层** | `semantic_catalog.yaml` | 随代码部署 | 15 个 GIS 语义域（AREA/SLOPE/LAND_USE 等）、中英文别名、区域组、空间操作同义词、指标 SQL 模板 |
| **动态注册层** | PostgreSQL 两表 | 随数据增长 | 表级元数据（display_name, synonyms, CRS）+ 列级标注（domain, aliases, unit） |
| **运行时解析层** | `semantic_layer.py` | 每次请求 | 匹配用户文本 → 合并 DB + 静态结果 → 生成 `[语义上下文]` prompt 块 |

### 2.2 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                     用户输入                                  │
│  "分析和平村各地类的面积分布"                                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│              resolve_semantic_context()                       │
│                   (app.py 调用)                               │
│                                                              │
│  ┌────────────────┐     ┌─────────────────────────────┐      │
│  │  DB 动态注册表  │     │     YAML 静态知识目录         │      │
│  │                │     │  semantic_catalog.yaml       │      │
│  │ ① 表级元数据    │     │                             │      │
│  │ semantic_sources│     │  ④ 15 个语义域 (AREA,       │      │
│  │ - display_name │     │     SLOPE, LAND_USE...)     │      │
│  │ - synonyms     │     │     含中英文别名              │      │
│  │ - geometry_type│     │                             │      │
│  │ - srid         │     │  ⑤ 7 个区域组               │      │
│  │                │     │     华东/华南/华北...         │      │
│  │ ② 列级语义标注  │     │                             │      │
│  │ semantic_registry    │  ⑥ 8 个空间操作              │      │
│  │ - semantic_domain    │     缓冲/裁剪/叠加...        │      │
│  │ - aliases (JSONB)    │                             │      │
│  │ - unit/description   │  ⑦ 4 个指标模板              │      │
│  │                │     │     密度/破碎度/覆盖率        │      │
│  └───────┬────────┘     └──────────┬──────────────────┘      │
│          │                         │                         │
│          ▼                         ▼                         │
│  ┌─────────────────────────────────────────────────┐         │
│  │          _match_aliases() 同义词匹配              │         │
│  │  精确匹配 → 1.0 │ 子串包含 → 0.7 │ 域回退 → 0.5  │         │
│  └─────────────────────────────────────────────────┘         │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │ build_context_prompt│
            │   生成 [语义上下文]   │
            └──────────┬──────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    LLM Prompt                                │
│                                                              │
│  用户原文 + [上轮分析上下文] + [用户空间记忆] + [语义上下文]     │
│                                                              │
│  [语义上下文]                                                 │
│  表 heping_village_8000 (和平村) [Polygon] SRID=4490          │
│    字段: zmj(面积/亩), dlmc(地类名称), slope(坡度/度)          │
│  优先使用以上语义映射，减少对 describe_table 的依赖。            │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
              Agent 直接写出正确 SQL
              SELECT dlmc, SUM(zmj) FROM ...
              (无需猜测 zmj = 面积)
```

### 2.3 同义词匹配算法

三级降级策略，无 ML 依赖，零延迟：

| 级别 | 匹配方式 | 置信度 | 示例 |
|------|---------|--------|------|
| 1 | 精确匹配（大小写不敏感） | 1.0 | 用户输入 "area" 匹配别名 ["area", "zmj", "面积"] |
| 2 | 子串包含（别名 ≥ 2 字符） | 0.7 | 用户输入 "分析面积分布" 包含别名 "面积" |
| 3 | 静态目录域回退 | 0.5 × 原分数 | 无 DB 匹配时回退到 YAML 目录域别名 |

### 2.4 自动发现机制

`describe_table()` 首次调用时触发 `auto_register_table()`：

1. 扫描表的所有列名
2. 逐列与静态目录 15 个域的 `common_aliases` 精确匹配
3. 检测 PostGIS 几何列类型 + SRID
4. 写入 `agent_semantic_registry`（列级）和 `agent_semantic_sources`（表级）
5. 后续查询直接命中 DB 注册表，跳过重复扫描

### 2.5 ADK 工具注册

| 工具函数 | 注册到 | 用途 |
|---------|--------|------|
| `resolve_semantic_context` | GeneralProcessing, PlannerExplorer | Agent 主动调用解析语义上下文 |
| `describe_table_semantic` | GeneralProcessing, PlannerExplorer | 带语义标注的增强版 describe_table |
| `list_semantic_sources` | GeneralProcessing, PlannerExplorer | 列出所有已注册语义数据源 |
| `register_semantic_annotation` | GeneralProcessing | 手工标注/修正列级语义 |
| `register_source_metadata` | GeneralProcessing | 手工标注/修正表级元数据 |

### 2.6 DB Schema

**`agent_semantic_registry`** — 列级标注：

| 列 | 类型 | 说明 |
|---|---|---|
| table_name | VARCHAR(255) | 表名 |
| column_name | VARCHAR(255) | 列名（与 table_name 联合唯一） |
| semantic_domain | VARCHAR(100) | 域类别（AREA, SLOPE, LAND_USE...） |
| aliases | JSONB | 同义词数组 `["面积", "area"]` |
| unit | VARCHAR(50) | 度量单位 |
| description | TEXT | 人类可读描述 |
| is_geometry | BOOLEAN | 是否为几何列 |
| owner_username | VARCHAR(100) | 标注者 |

**`agent_semantic_sources`** — 表级元数据：

| 列 | 类型 | 说明 |
|---|---|---|
| table_name | VARCHAR(255) | 表名（唯一） |
| display_name | VARCHAR(255) | 显示名称（"和平村地块数据"） |
| description | TEXT | 表描述 |
| geometry_type | VARCHAR(50) | 几何类型（Point/Polygon/...） |
| srid | INTEGER | 坐标系（4326/4490） |
| synonyms | JSONB | 表名同义词 `["和平村", "heping"]` |
| suggested_analyses | JSONB | 建议分析类型 `["clustering", "choropleth"]` |
| owner_username | VARCHAR(100) | 所有者 |

### 2.7 静态目录结构（semantic_catalog.yaml）

```yaml
domains:           # 15 个 GIS 语义域
  AREA:
    description: "面积"
    common_aliases: ["area", "zmj", "shape_area", "mj", "面积", "tbmj"]
    typical_unit: "m² 或 亩"
    data_type: numeric
  SLOPE: ...
  LAND_USE: ...
  # ... 共 15 个

region_groups:     # 7 个中国区域组
  华东:
    provinces: ["上海市", "江苏省", "浙江省", ...]
    aliases: ["华东", "华东区域", "East China"]
  # ... 共 7 个

spatial_operations: # 8 个空间操作同义词映射
  buffer:
    tool_name: "create_buffer"
    aliases: ["缓冲", "缓冲区", "范围", "周边", "辐射", "半径"]
  # ... 共 8 个

metric_templates:  # 4 个指标 SQL 模板
  density:
    description: "密度 = 数量 / 面积"
    pattern: "COUNT(*) / (ST_Area(geom::geography) / 1e6)"
    unit: "个/km²"
    synonyms: ["密度", "分布密度", "密集度"]
  # ... 共 4 个
```

---

## 3. 与 MetricFlow 的对比分析

### 3.1 定位差异

| 维度 | MetricFlow (dbt Labs) | 本项目语义层 |
|------|----------------------|-------------|
| **定位** | 通用 BI 语义层 — 企业级指标治理平台 | GIS 领域语义层 — LLM Agent 辅助理解层 |
| **核心问题** | "revenue" 指标在 50 个 BI 报表里定义不一致 | Agent 每次猜 `zmj` = 面积，`dlmc` = 地类 |
| **用户** | 数据分析师、BI 工程师 | LLM Agent（自动消费）、GIS 操作员（偶尔标注） |
| **输出** | 可执行的 SQL 语句 | `[语义上下文]` prompt 文本块 |

### 3.2 架构对比

```
MetricFlow                              本项目
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YAML 定义层                              YAML 定义层
┌──────────────────────┐                ┌──────────────────────┐
│ Semantic Models      │                │ semantic_catalog.yaml │
│ - entities (PK/FK)   │                │ - 15 domains + 别名   │
│ - dimensions         │                │ - 7 region groups    │
│ - measures (agg)     │                │ - 8 spatial ops      │
│ Metrics              │                │ - 4 metric templates │
│ - derived/ratio/cum  │                └──────────┬───────────┘
│ Saved Queries        │                           │
└──────────┬───────────┘                DB 动态层
           │                            ┌──────────┴───────────┐
编译器管线 (5 阶段)                      │ semantic_sources     │
┌──────────┴───────────┐                │ semantic_registry    │
│ QuerySpec            │                │ (auto-discovered)    │
│   ↓                  │                └──────────┬───────────┘
│ Dataflow DAG         │                           │
│   ↓ (优化器)          │                运行时解析
│ SQL Plan IR          │                ┌──────────┴───────────┐
│   ↓ (方言渲染)        │                │ _match_aliases()     │
│ Executable SQL       │                │ 3 级同义词匹配         │
└──────────┬───────────┘                │   ↓                  │
           │                            │ build_context_prompt │
数据仓库执行                             │ → [语义上下文] 文本    │
┌──────────┴───────────┐                └──────────┬───────────┘
│ Snowflake/BQ/PG/...  │                           │
│ → 结果集              │                LLM 消费
└──────────────────────┘                ┌──────────┴───────────┐
                                        │ Agent 读取上下文      │
                                        │ → 自行生成 SQL        │
                                        └──────────────────────┘
```

### 3.3 核心机制逐项对比

#### 3.3.1 元数据建模

| | MetricFlow | 本项目 |
|---|---|---|
| **建模粒度** | entity → dimension → measure → metric 四层 | domain → column annotation 两层 |
| **关系建模** | 显式 entity 声明 PK/FK，构建语义图，支持 2-hop 自动 JOIN | 无关系建模，JOIN 由 Agent/SQL 自行处理 |
| **指标定义** | 5 种指标类型（simple/cumulative/derived/ratio/conversion），带聚合函数、时间窗口 | 4 个 SQL 模板（density/fragmentation/coverage/concentration），仅供 Agent 参考 |
| **时间维度** | 一等公民 — 8 种粒度、time spine 表、累积/半加性度量 | 无时间维度概念 |

差距根因：MetricFlow 面向分析型查询（OLAP），核心是"同一指标在不同维度切片下的一致聚合"。本项目面向空间操作调度，核心是"Agent 理解列名的含义"。

#### 3.3.2 查询编译

| | MetricFlow | 本项目 |
|---|---|---|
| **编译过程** | 5 阶段编译器：QuerySpec → Dataflow DAG → 优化 → SQL Plan IR → 方言渲染 | 无编译器 — 仅文本匹配，生成自然语言上下文 |
| **中间表示** | 两层 IR（Dataflow DAG + SQL Plan），含 15+ 种节点类型 | 无 IR，仅 Python dict (`resolved`) |
| **SQL 生成** | MetricFlow 生成完整可执行 SQL | Agent 自行生成 SQL，语义层只提供字段映射提示 |
| **优化器** | 谓词下推、源扫描合并、JOIN 重排 | 无查询优化 |
| **多方言** | Snowflake / BigQuery / Databricks / Redshift / PG / DuckDB / Trino | 仅 PostgreSQL（PostGIS） |

**这是最大的架构差异**：MetricFlow 是一个 **SQL 编译器**，把高层语义请求编译成低层 SQL。本项目是一个 **提示词增强器**，把语义信息注入 prompt 让 LLM 自己写 SQL。

#### 3.3.3 同义词/映射机制

| | MetricFlow | 本项目 |
|---|---|---|
| **映射方式** | 严格声明式 — YAML 中精确定义 `expr: order_total` 映射到列 | 模糊匹配 — 同义词列表 + 子串匹配 |
| **歧义处理** | 编译时报错（JOIN 歧义、类型不匹配） | 置信度分数（1.0/0.7/0.5），多候选并存 |
| **中文支持** | 无原生支持 | 一等公民 — 别名列表中英混合 |
| **GIS 域知识** | 无 | 内置 15 个 GIS 语义域 + 中国行政区划 + 空间操作词典 |

#### 3.3.4 注册与维护

| | MetricFlow | 本项目 |
|---|---|---|
| **定义方式** | 纯手工 YAML（与 dbt model 1:1 配对） | 自动发现 + 手工修正 |
| **自动化** | 无 — 每个 semantic model 必须手写 | `auto_register_table()` 扫描列名自动匹配域 |
| **维护成本** | 高 — 新表必须写 YAML，CI/CD 校验 | 低 — 首次 `describe_table()` 自动填充 |
| **版本控制** | Git（YAML 文件） | DB 存储（JSONB），无版本历史 |

#### 3.3.5 与 AI/LLM 的集成

| | MetricFlow | 本项目 |
|---|---|---|
| **集成方式** | dbt MCP Server — 6 个工具 | 5 个 ADK 工具 + prompt 注入 |
| **LLM 角色** | 选择调用哪个 metric + 传参 → MetricFlow 生成 SQL | 读取语义上下文 → 自己写 SQL |
| **确定性** | **高** — MetricFlow 生成的 SQL 是确定的 | **中** — Agent 仍可能写错 SQL，语义层只是辅助 |
| **信任链** | LLM → MetricFlow（确定性编译）→ SQL → 数据 | LLM → 语义上下文（建议性）→ LLM 写 SQL → 数据 |

### 3.4 取舍分析

| 设计选择 | MetricFlow | 本项目 | 原因 |
|---|---|---|---|
| SQL 生成权 | MetricFlow 持有 | LLM Agent 持有 | GIS 查询太多样（空间函数、ST_Buffer 等），无法用声明式指标覆盖 |
| 关系建模 | 强制 entity 声明 | 不建模 | GIS 场景多为单表空间分析，跨表 JOIN 少 |
| 注册成本 | 高（手工 YAML） | 低（自动发现） | 用户是 GIS 操作员非数据工程师 |
| 匹配精度 | 100%（声明式） | ~80%（模糊匹配） | 中文 GIS 字段别名极多，需要容错 |
| 可审计性 | 强（编译器管线可检查） | 弱（prompt 注入后 Agent 黑箱） | 当前优先 MVP 可用性 |

### 3.5 可借鉴的改进方向

1. **Semantic Manifest 标准化** — 将语义注册表导出为 JSON manifest，供外部工具消费（类似 OSI）
2. **JOIN 安全矩阵** — 根据 entity 关系自动生成安全的 JOIN 子句，而非完全依赖 LLM
3. **Saved Queries / 指标预编译** — 高频查询模板编译为确定性 SQL，Agent 直接调用
4. **编译时校验** — 在语义注册时验证列名是否真实存在、类型是否匹配

本质上，MetricFlow 走的是 **"把 LLM 排除在 SQL 生成之外"** 的路线，本项目走的是 **"帮助 LLM 更好地生成 SQL"** 的路线。前者确定性高但灵活性低，后者灵活性高但需要容忍 LLM 的不确定性。

---

## 4. 与知识图谱和本体的关系

### 4.1 概念谱系定位

```
抽象程度    低 ←──────────────────────────────────────────→ 高

            元数据目录        语义层          本体           知识图谱
            (Metadata        (Semantic      (Ontology)     (Knowledge
             Catalog)         Layer)                        Graph)
            ┌──────┐        ┌──────┐       ┌──────┐       ┌──────┐
            │列名   │        │列名   │       │概念   │       │实体   │
            │类型   │        │+ 别名 │       │+ 属性 │       │+ 关系 │
            │约束   │        │+ 映射 │       │+ 关系 │       │+ 推理 │
            │       │        │+ 度量 │       │+ 公理 │       │+ 实例 │
            └──────┘        └──────┘       └──────┘       └──────┘

            information      business       formal         instance
            _schema          meaning        semantics      knowledge

            "这列叫 zmj，    "zmj 意思是     "面积 是 度量    "和平村.地块A
             类型 numeric"    面积，单位亩"    的子类，度量     的面积=3.2亩，
                                            必须有单位，     相邻地块B，
                                            面积 可度量      属于耕地"
                                            空间对象"
```

**本项目实现横跨前两层，触及第三层边缘，未进入第四层。**

### 4.2 逐层对照

#### 第一层：元数据目录（已超越）

PostgreSQL `information_schema` 提供纯技术元数据：

```sql
column_name: zmj, data_type: numeric, is_nullable: YES
```

这是 Agent 之前唯一能获取的信息。Agent 看到 `zmj` 只能靠猜。

#### 第二层：语义层（核心实现）

在元数据之上叠加业务语义：

```yaml
# 静态目录 — 域级语义
AREA:
  description: "面积"
  common_aliases: ["area", "zmj", "shape_area", "mj", "面积", "tbmj"]
  typical_unit: "m² 或 亩"
  data_type: numeric

# DB 注册 — 实例级语义
table: heping_village_8000
column: zmj → domain=AREA, aliases=["面积","area"], unit="亩"
```

解决了 "zmj 是什么意思" 的问题。但只有概念→别名的扁平映射和概念→单位/类型的属性标注，概念之间没有关系。

#### 第三层：本体（触及边缘但未正式建模）

本体的核心是概念间的形式化关系。如果用 OWL/RDF 表达：

```turtle
gis:面积      rdf:type        owl:Class .
gis:面积      rdfs:subClassOf gis:度量属性 .
gis:度量属性   rdfs:subClassOf gis:属性 .

gis:面积      gis:hasUnit     gis:平方米, gis:亩 .
gis:面积      gis:canMeasure  gis:空间对象 .
gis:面积      gis:derivedFrom gis:几何体 .

gis:坡度      rdfs:subClassOf gis:地形属性 .
gis:坡度      gis:derivedFrom gis:DEM .

gis:地类编码   owl:equivalentProperty gis:地类名称 .
gis:耕地      rdfs:subClassOf gis:农用地 .
gis:农用地     rdfs:subClassOf gis:土地利用类型 .
```

#### 第四层：知识图谱（完全没有）

知识图谱在本体之上填充实例数据和推理能力：

```
(heping_village_8000, rdf:type, gis:地块数据集)
(heping_village_8000, gis:locatedIn, 和平村)
(和平村, gis:partOf, XX镇)
(XX镇, gis:partOf, XX县)

# 推理: 用户问"华北的耕地面积"
→ 华北 contains 河北省 contains XX县 contains 和平村
→ 和平村有数据集 heping_village_8000
→ 该数据集有面积列 zmj，地类列 dlmc
→ 耕地 subClassOf 农用地，dlbm 编码 01* 为耕地
→ SELECT SUM(zmj) FROM heping_village_8000 WHERE dlbm LIKE '01%'
```

### 4.3 隐含但未显式表达的本体关系

| 关系类型 | 本体中的表达 | 本项目实现 | 差距 |
|---------|------------|-----------|------|
| **is-a（继承）** | 耕地 → 农用地 → 土地利用类型 | 只有扁平的 `LAND_USE` 域，无层级 | 不知道"耕地"是"农用地"的子类 |
| **has-unit（度量单位）** | 面积 hasUnit 亩/m² | `typical_unit: "m² 或 亩"` 只是文本描述 | 不能做单位换算推理 |
| **derived-from（派生）** | 坡度 derivedFrom DEM | `spatial_operations` 仅映射到工具名 | 不知道"坡度分析需要 DEM 数据" |
| **equivalent（等价）** | dlbm ≡ dlmc（编码与名称） | 同属 `LAND_USE` 域，但没标记等价 | 两列混用时不知道是同一概念的不同表达 |
| **part-of（组成）** | 朝阳区 partOf 北京市 partOf 华北 | `region_groups` 只有一级分组 | 不能推理"朝阳区属于华北" |
| **spatial-relation** | 地块A adjacentTo 地块B | 完全没有 | 没有空间拓扑关系建模 |

### 4.4 各组件的本体论定位

| 组件 | 本体论角色 | 形式化等价概念 |
|------|----------|--------------|
| domains (AREA, SLOPE...) | 概念类 (Class) | owl:Class |
| common_aliases | 词汇层同义词 | rdfs:label (多值) |
| typical_unit | 属性约束 | owl:hasValue |
| data_type | 值域约束 | rdfs:range |
| region_groups | 实例枚举 + 组合关系 | owl:oneOf + part-of |
| spatial_operations | 过程性知识 | 无直接本体对应（更像规则/Plan） |
| metric_templates | 派生规则 | SWRL 规则 |
| semantic_sources (DB) | 数据集实例描述 | Named Individual |
| semantic_registry (DB) | 属性-概念绑定 | owl:ObjectProperty |
| auto_register_table() | 自动分类器 | 本体对齐 (Ontology Alignment) |
| _match_aliases() | 词汇匹配 | String Similarity（非逻辑推理） |

### 4.5 能力对比

| 能力 | 本体/知识图谱 | 本项目语义层 |
|------|------------|------------|
| **概念定义** | 形式化公理（OWL） | 别名列表 + 描述文本 |
| **关系推理** | 传递性（A partOf B, B partOf C → A partOf C） | 无推理，硬编码一级映射 |
| **继承** | 耕地 → 农用地 → 土地利用类型 | 所有地类都是扁平的 `LAND_USE` |
| **一致性检查** | 推理机检测矛盾 | 无一致性检查 |
| **查询能力** | SPARQL — 图模式匹配 | 子串匹配 — 模糊文本搜索 |
| **开放世界假设** | 未声明的不等于否定 | 未匹配的就是不匹配 |
| **可解释性** | 推理链路完整可追溯 | 只有置信度分数 |

### 4.6 为什么选择"轻量语义层"而非本体/知识图谱

```
投入产出比:

                        投入 ──────→
          低                                    高
    ┌─────────────────────────────────────────────────┐
高   │                                                 │
    │  ★ 本项目位置                                     │
    │  语义层 + 模糊匹配                                │
    │  投入: ~400 行 Python + 175 行 YAML              │
收   │  收益: 消除 80%+ 的列名猜测                       │
益   │                              ┌─────────────┐     │
    │                              │ 本体建模     │     │
↑   │                              │ 投入: OWL +  │     │
    │                              │  推理机 +    │     │
    │                              │  领域专家    │     │
    │                              │ 收益: +15%   │     │
    │                              │  精度提升    │     │
低   │                              └─────────────┘     │
    └─────────────────────────────────────────────────┘
```

三个实际原因：

1. **LLM 已经是"软推理机"** — Agent 看到 `[语义上下文] zmj(面积/亩)` 后，能自行推断 `SUM(zmj)` 合理、`AVG(zmj)` 合理、`zmj LIKE '%x%'` 不合理。正式本体的推理能力被 LLM 的常识推理部分替代了。

2. **GIS 领域的长尾问题** — 中国国土数据字段命名极不规范（`zmj`、`tbmj`、`SHAPE_Area`、`mj`、`面积_亩` 都可能出现），用形式化本体覆盖所有变体的成本远高于维护一个别名列表。

3. **渐进式而非一次性** — `auto_register_table()` 让系统在零配置下就能工作，随着使用逐步积累标注。正式本体需要领域专家前置建模，这在快速迭代产品中不现实。

---

## 5. 未来演进方向

### 5.1 从 MetricFlow 借鉴

| 方向 | 具体做法 | 预期收益 |
|------|---------|---------|
| Semantic Manifest | 注册表导出为 JSON，供外部工具消费 | 与其他系统互操作 |
| JOIN 安全矩阵 | entity 关系声明 → 自动生成安全 JOIN | 减少跨表查询错误 |
| 指标预编译 | 高频查询模板 → 确定性 SQL | 消除 LLM 不确定性 |
| 编译时校验 | 注册时验证列名/类型真实存在 | 提前发现配置错误 |

### 5.2 向本体/知识图谱渐进演进

最有价值的三步（不需要引入 OWL/RDF 技术栈，在现有 YAML + PostgreSQL 架构上实现）：

1. **域内层级关系** — 给 `LAND_USE` 域增加层级树（耕地 → 农用地 → 土地利用），让 Agent 理解"统计农用地面积"应包含耕地+园地+林地

2. **列间等价/派生关系** — 标记 `dlbm ↔ dlmc`（编码与名称等价）、`slope ← DEM`（坡度从 DEM 派生），让 Agent 知道"做坡度分析需要先有 DEM"

3. **空间层级索引** — 把 `region_groups` 扩展为多级行政区划图（省 → 市 → 区 → 街道），支持传递性查询"朝阳区属于华北吗？"

这三步属于"用工程手段获取本体收益"的务实路线。
