# 自然资源真实数据接入、本体与存储流转分析

**文档状态**：架构分析稿

**日期**：2026-08-05

**适用范围**：GIS Data Agent 自然资源本体 2.3 与客户真实数据接入

## 1. 核心结论

数据清单中的所有业务记录不应全部进入本体库。

自然资源本体负责定义“有哪些对象、属性、关系、约束，以及这些语义对应哪些表和字段”；真实图斑、宗地、建筑、栅格等记录主要进入数据湖仓，PostGIS 保存需要在线查询或编辑的数据投影。

系统应遵循以下原则：

- 湖仓保存数据。
- 本体保存语义。
- PostGIS 提供在线空间服务和事务能力。
- 治理库管理身份、版本、质量、血缘、审批和发布。
- Agent 通过本体与 Schema 映射定位真实数据，而不是到本体库中查询全部业务记录。

## 2. 各类存储的职责

| 存储 | 应保存的内容 | 权威边界 |
|---|---|---|
| 数据湖 Raw | 原始文件、GeoParquet、Parquet、COG、文档、接入快照、manifest、校验码 | 原始证据真值 |
| Iceberg 湖仓 | ODS/Bronze、Silver、Gold 的标准化记录和历史快照 | 分析数据真值 |
| PostgreSQL 治理库 | 数据源、接入任务、资产、版本、质量、血缘、审批、发布状态 | 治理与版本真值 |
| PostGIS | 地图浏览、空间查询、热点数据、在线编辑、当前版本投影 | 通常是可重建的服务副本；在线编辑表可作为事务源 |
| `gda_ontology` | 类、属性定义、关系、约束、代码体系、Schema 映射、来源证据 | 本体模型真值 |
| Fuseki | 本体的 RDF/SPARQL 只读投影 | 可重建，不是写权威 |

关键不是完全避免数据重复，而是保证每种数据只有一个明确权威。同一条图斑可以同时存在于 Raw、Iceberg 和 PostGIS，但它们分别承担证据、分析和服务职责。

## 3. 正式接入后的推荐数据流

```text
客户文件 / ArcGIS 服务 / 数据库 / API
        |
        v
数据源登记、权限和接入任务
        |
        v
冻结源数据版本或提取范围
        |
        v
不可变 Raw 快照
GeoParquet / Parquet / COG / 原始附件
        |
        v
结构、坐标系、代码值、几何和质量检查
        |
        v
本体语义对齐
“这张表描述什么对象、每个字段对应什么领域属性”
        |
        v
ODS/Bronze 贴源结构
        |
        v
Silver 标准化、统一编码、实体标识、时态处理
        |
        v
Gold 主题融合和跨表关联
        |
        v
DataProductVersion 正式发布
        |
        v
PostGIS / STAC / API / Agent 查询
```

元数据和血缘应在每一步旁路登记：

```text
SourceResourceVersion
  -> RawSnapshot
  -> Iceberg TableSnapshot
  -> DataProductVersion
  -> PostGISServingBuild / STAC Item
```

本体映射是另一条独立但有关联的链路：

```text
物理表/字段
  -> SchemaArtifact / SchemaField
  -> 已确认语义映射
  -> 本体类 / 属性 / 关系
  -> OntologyVersion 2.3
```

两条链通过稳定标识和版本号连接，而不是通过向本体库复制全部业务记录连接。

## 4. 数据是否一定先进入数据湖

正式纳管并要求可审计、可重放的数据，逻辑上应先形成不可变 Raw 版本。但是，物理执行不一定严格串行。

GIS Data Agent 当前的 ArcGIS 接入会分页读取数据，同时写入 Raw GeoParquet 和 PostGIS 暂存表。质量检查通过后，再提交 Raw 快照、原子切换 PostGIS 表、登记资产版本和血缘。因此准确表述是：

> 逻辑上 Raw 是前置证据；物理上多个目标可以并行暂存，所有发布条件满足后再统一对外生效。

以下数据不一定立即复制进入湖：

- 只做预览或目录注册的外部服务；
- 因保密或许可限制只能联邦查询的数据；
- 尚未批准物化的数据；
- 轻量部署中使用 append-only PostGIS/DuckDB 保存的等价 Raw 快照。

即便不进入默认 MinIO/S3，也必须保留不可变版本、来源校验码和可导出 manifest，不能只留下一个持续变化的在线表。

## 5. 地类图斑 DLTB 示例

假设客户交付 1000 万条地类图斑：

- 1000 万条图斑、完整字段和几何进入 Raw 和 Iceberg。
- 当前有效图斑及必要空间索引发布到 PostGIS。
- DLTB 表结构、字段类型、坐标系和主键进入元数据控制面。
- “地块”“土地利用状态”“行政区”“权利主体”等概念进入本体。
- `DLTB 描述地块`、`DLBM 对应地类代码`、`TBMJ 对应图斑面积`等映射进入本体映射模块。
- `OBJECTID=12345` 的完整属性和 geometry 不进入本体模型库。

Agent 执行“查询某县永久基本农田内的现状建设用地图斑”时，运行链路应为：

```text
本体识别业务概念和关系
  -> 语义映射定位实际表、字段和代码
  -> 选择当前已发布 DataProductVersion
  -> 在 PostGIS 或 Iceberg 执行空间查询
  -> 返回结果，并附带数据版本和本体版本
```

本体负责理解和定位，数据引擎负责保存和计算。

## 6. 本体模型与实例知识图谱的边界

需要严格区分两类模型：

- 本体模型（TBox）：地块是什么、有哪些属性、与登记单元有什么关系。
- 实例知识图谱（ABox）：地块 `DK-001` 属于主体 `QLR-008`，关联登记单元 `BDCDY-009`。

如果客户以后要求从一个具体地块开始，逐级浏览真实关联对象，可以增加独立的“实例语义层”或“实体关系索引”，但不建议把全部 geometry 和字段复制进 Fuseki。

推荐采用混合模式：

- 保存对象稳定 ID、类型、关键关系、有效期和数据版本引用；
- 具体属性按需从 PostGIS 或 Iceberg 读取；
- 大规模关系可以在湖仓或关系索引中物化；
- 只有真实性能测试证明有必要时，才增加专用图数据库读投影；
- 实例图与领域本体分别版本化，避免业务事实污染本体类层次。

本体中的 SKOS 标准代码概念、参考分类和少量领域基准个体可以保留；这不等于把全国自然资源业务记录全部本体化。

## 7. 三类数据变化的流转方式

### 7.1 全量批次

生成新的 Raw 快照和 Iceberg snapshot，完成质量检查后形成新的 DataProductVersion，再整体切换 PostGIS 服务投影。旧版本不覆盖，可用于审计、回放和回滚。

### 7.2 CDC 或增量同步

源系统必须提供稳定的更新时间、水位线、日志序列或变更跟踪合同。新增、修改、删除先追加为 Raw 变更事件，再合并到 Iceberg，形成新的产品版本，最后增量刷新或重建 PostGIS。

删除必须使用明确的 tombstone 或失效状态表达，不能直接物理删除历史证据。

### 7.3 在线空间编辑

PostGIS operational 表可以承担事务编辑，但一次有效修改必须通过 outbox 或 CDC 重新进入 Raw/ODS，并生成新版本和血缘。不能只修改 PostGIS 而不留下湖仓记录。

在线编辑表与只读 serving 表应在逻辑上分离，避免刷新服务投影时覆盖尚未归档的业务事务。

## 8. 发布、一致性、失败恢复和回滚

跨数据湖、PostGIS、治理库和本体投影无法依赖单个数据库事务完成，应采用版本化发布状态机：

```text
prepared -> validating -> publishing -> active
                         -> failed
```

基本要求如下：

- Raw 使用 manifest、checksum 和 `_SUCCESS` 表示完整提交。
- PostGIS 使用运行级暂存表和原子切换发布完整快照。
- 只有全部必需输出及质量门通过后，才推进 active DataProductVersion。
- 重试必须使用稳定 run ID、目标版本 ID 和内容 hash，防止重复发布。
- 发布失败可能留下未引用的孤立快照，但不能让它成为活动版本。
- OpenMetadata、STAC、Fuseki 等读投影允许最终一致，但必须绑定权威版本和 package hash。
- 回滚通过切换 active version 指针实现，再据此重建 PostGIS 或其他服务投影，不反向篡改历史记录。

## 9. 当前 GIS Data Agent 已具备的能力

当前实现已经具备以下基础：

- ArcGIS 对象 ID 快照冻结和分页读取；
- 不可变 GeoParquet、manifest 和 `_SUCCESS`；
- 可选 PostGIS 暂存及原子表切换；
- 接入任务、运行批次、质量、资产版本和血缘登记；
- Iceberg 物化、质量、血缘和发布合同；
- PostgreSQL 本体权威与 Fuseki 只读投影；
- 接入失败后的租约恢复、幂等重放和版本去重基础。

当前 ArcGIS 接入只支持 `full_snapshot`。Raw 直接写入 Iceberg 目前不是该连接器的主链路，而是由后续 curated-zone 作业将已提交 GeoParquet 提升为 Iceberg snapshot。

## 10. 客户正式接入前需要补齐的能力

- 文件、GDB、数据库、栅格等各类连接器；
- 数据清单项到 EA/标准 Schema、本体 2.3 的运行时映射注册；
- Raw 到 Iceberg 各层的统一生产管线；
- 跨系统稳定业务对象 ID 和双时态模型；
- CDC、水位线、删除语义和跨库一致性；
- 代码值、几何、唯一性、关联完整性等领域质量规则；
- PostGIS 投影重建、湖仓对账、版本回滚和权限继承；
- 受限数据的联邦查询、脱敏和用途控制；
- 是否建设实例语义索引及其存储形态的规模和 SLO 评估；
- 根据客户数据量、更新频率和查询模式确定 Iceberg 分区及 PostGIS 投影范围。

## 11. 建议的最终定位

自然资源本体 2.3 应继续作为领域语义和 Schema 映射的权威模型，而不扩展成保存全部业务记录的数据库。

真实数据接入后，GIS Data Agent 应形成以下闭环：

```text
本体定义领域语义
  -> Schema 映射绑定真实数据
  -> 湖仓保存版本化业务事实
  -> PostGIS 提供在线空间查询和编辑
  -> 治理库记录质量、血缘和发布状态
  -> Agent 组合语义解析与真实数据计算
```

只有在客户明确提出对象级多跳浏览、跨数据集实体解析或关系推理，并且性能测试证明按需查询不能满足 SLO 时，才应建设独立的实例知识图谱。该实例图应作为可重建的数据产品投影，而不是改变本体模型库的职责。

## 12. 关联架构决策

- [ADR-001：可插拔地理空间存储、计算与服务边界](../architecture-decisions/adr-001-geospatial-lakehouse-and-postgis-boundary.md)
- [ADR-127：ArcGIS 接入控制面与数据面](adr-127-arcgis-ingestion-control-and-data-plane.md)
- [ADR-139：自然资源本体运行时](../architecture-decisions/adr-139-natural-resource-ontology-runtime.md)
- [ADR-140：策划型自然资源领域本体与来源映射分层](../architecture-decisions/adr-140-curated-natural-resource-domain-ontology.md)
- [ADR-163：清单基线驱动的自然资源本体证据扩展](../architecture-decisions/adr-163-natural-resource-ontology-evidence-expansion.md)
