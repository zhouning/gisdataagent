# TWM 存储架构说明：从权威原始数据到世界模型状态输入

日期：2026-06-29
适用范围：GIS Data Agent 中 Territory World Model, TWM 的生产级数据流转、物理存储分层、MMFE 入模、状态快照、训练样本、推演输出和多模态向量存储选型。

## 1. 核心结论

TWM 的主数据链路应按以下顺序组织：

```text
自然资源权威源系统
  -> Raw/Landing 原始落地区
  -> Lakehouse 标准化与版本化区
  -> MMFE 多模态语义融合区
  -> TWM renderer/state builder 状态构建区
  -> TWM state snapshot 与 dynamics training dataset
  -> simulator / dynamics / planner / validation
  -> 审计报告、地图瓦片、Notebook、API 输出
```

这里的 TWM renderer 不是前端地图渲染器，而是世界模型语境中的“状态构建器/状态编译器”。它负责把 MMFE 已融合的数据、规则、证据、空间关系、时序观测和特征向量编译为 TWM 可消费的状态输入。前端地图渲染器只负责可视化，不应承担状态语义构建职责。

## 2. 分层物理存储

| 环节 | 主要内容 | 推荐物理存储 | 说明 |
|---|---|---|---|
| 权威源系统 | 自然资源部及地方部门已有库、业务系统、档案系统 | 对方现有数据库、文件库、专网系统 | 不作为 TWM 直接改写对象，只通过批量导出、API、数据交换或专线同步进入落地区。 |
| Raw/Landing 原始落地区 | 原始矢量、栅格、表格、文档、影像、审批附件、元数据 | MinIO/S3/HDFS/NAS，对象存储优先 | 保留原始文件、原始 CRS、原始字段、原始时间戳和 checksum，用于审计与重跑。 |
| Lakehouse 标准化区 | 清洗后的矢量、表格、时序、网格、影像索引 | Iceberg + Parquet/GeoParquet；COG/STAC；MinIO/S3/HDFS | 作为大规模分析事实层，支持 schema evolution、分区、快照、时间旅行和 Spark/Sedona 读取。 |
| 空间计算区 | 空间连接、叠加分析、栅格统计、格网聚合、时空窗口分析 | Apache Spark + Apache Sedona；PostGIS 作为交互式空间库 | Sedona 负责大数据量批处理；PostGIS 负责低延迟查询、规则命中、API 和人工复核。 |
| MMFE 融合区 | 对象、关系、规则、证据、语义标签、多模态特征 | Iceberg/GeoParquet + Postgres/PostGIS + 对象存储 artifact | MMFE 输出的结构化语义包是 TWM 状态构建的直接上游。 |
| 多模态特征区 | 文本 embedding、遥感/AlphaEarth/GeoFM embedding、图像 chip embedding、未来 latent state 表征 | Iceberg vector tables 或 Lance/LanceDB sidecar | 不作为主事实存储。只保存高维向量、索引和特征版本，必须回连到 Iceberg/PostGIS 中的 object_id、evidence_id、snapshot_id。 |
| TWM 状态元数据区 | project、scenario、state、object、relation、rule hit、evidence、forecast、rollout 元数据 | PostgreSQL/PostGIS + JSONB | 适合 API、Agent 工具、审计链和小规模交互式读写。 |
| TWM 大状态快照区 | 大规模状态快照、训练样本、rollout 轨迹、候选方案矩阵 | Iceberg + Parquet/GeoParquet；必要时配套 Zarr/COG | 适合千万到亿级对象、长时序、多区域训练和回放。 |
| 模型与实验资产区 | dynamics candidate、future_latent_state head、训练配置、指标、校准报告 | 对象存储 + Postgres model registry | 模型文件放对象存储，指标和版本索引入库。 |
| 输出发布区 | 地图瓦片、Notebook、HTML 地图、报告、审计包、API 查询结果 | MinIO/S3 artifact + tile store + Postgres 索引 | 面向用户查看和复核，不应反向成为事实源。 |

## 3. 状态输入的数据流转

### 3.1 权威数据进入 Raw/Landing

原始数据进入 TWM 前不应被直接覆盖或重写。每个落地资产需要至少保留：

- 来源单位、来源系统、批次号、提取时间。
- 原始文件路径、checksum、坐标系、时间范围、空间范围。
- 数据密级、共享范围、脱敏规则。
- 与后续标准化表、MMFE 输出、TWM 状态快照的 lineage id。

这一层的目标是可追溯，而不是高性能分析。

### 3.2 Raw/Landing 进入 Lakehouse

Lakehouse 是 TWM 的大规模事实分析底座。推荐采用：

- MinIO/S3/HDFS 作为对象存储。
- Iceberg 作为表格式，承载结构化和半结构化事实表。
- GeoParquet 承载矢量要素和空间字段。
- COG/STAC 承载栅格和影像资产发现。
- Spark + Sedona 作为大规模空间计算引擎。

这一层解决的是生产数据量问题：大范围、多时相、多源数据不能依赖单机 GeoPandas 或只靠 PostGIS 承载所有批处理。

### 3.3 Lakehouse 进入 MMFE

MMFE 负责把原始自然资源数据转成 TWM 可理解的语义结构：

- 对象：地块、项目、规划区、保护区、行政单元、网格单元、遥感斑块。
- 关系：包含、相交、邻接、连通、归属、冲突、审批关联、证据引用。
- 规则：法定管控规则、用途管制规则、生态红线规则、耕地保护规则、审批一致性规则。
- 证据：遥感观测、规划文本、审批记录、地类变更、人工复核、统计年报。
- 特征：显式 GIS 特征、多模态语义 embedding、GeoFM/AlphaEarth embedding、时序变化特征。

MMFE 输出可以同时写入 Iceberg/GeoParquet 和 PostGIS：前者用于批处理和训练，后者用于交互查询、规则复核和 API。

### 3.4 MMFE 进入 TWM renderer/state builder

TWM renderer/state builder 的职责是把 MMFE 语义包编译为模型状态输入。它至少需要做五类工作：

- 统一状态边界：确定 project、scenario、time horizon、spatial extent、object granularity。
- 构建层级 token：parcel/block/township/county 或 grid/region/nation 等层级结构。
- 编译状态特征：显式 GIS 指标、规则命中、证据质量、历史变化、语义向量和 latent vector。
- 构建 action/context：政策情景、规划约束、干预动作、需求规模、保护目标、开发强度。
- 生成可审计 snapshot：状态输入必须带 schema version、source lineage、feature version、quality report。

因此，原始数据不是直接输出给 TWM；更准确的关系是：

```text
原始权威数据 -> Lakehouse 标准化 -> MMFE 语义融合 -> TWM state builder -> TWM 状态输入
```

## 4. TWM 内部存储边界

TWM 内部不应只有一个数据库。不同数据形态应该分开存储：

- 元数据与审计链：PostgreSQL/PostGIS + JSONB。
- 大规模状态快照：Iceberg + Parquet/GeoParquet。
- 高维向量：Iceberg vector tables 或 Lance/LanceDB sidecar。
- 栅格/影像资产：COG/STAC + object storage。
- 模型权重与评估报告：object storage + model registry。
- Notebook、HTML 地图和可视化产物：object storage artifact。

这个边界的关键原则是：PostGIS 负责治理交互与空间索引，Iceberg 负责生产规模事实表和训练数据，MinIO/S3 负责所有大对象与版本化资产，Sedona 负责大数据量空间计算。

## 5. 是否需要 Lance/LanceDB

结论：TWM 的基础链路不强制需要 Lance/LanceDB；但在多模态 embedding、GeoFM/AlphaEarth 特征、图像 chip 检索、文本证据检索、future_latent_state 高维表征规模化之后，建议把 Lance/LanceDB 作为可选的“多模态向量侧车层”，不要把它作为主 lakehouse 或主事实存储。

### 5.1 不建议 Lance/LanceDB 承担的职责

Lance/LanceDB 不应替代以下组件：

- 不替代 Iceberg：Iceberg 仍是结构化事实表、时空观测、训练样本和快照版本的主存储。
- 不替代 PostGIS：PostGIS 仍是空间规则、API 查询、人工复核和审计链的核心交互库。
- 不替代 STAC/COG：遥感影像和栅格资产仍应以 COG/STAC 管理。
- 不作为权威数据源：权威事实必须来自自然资源业务系统、Raw/Landing 和 Lakehouse lineage。

原因是 TWM 的生产场景需要强 schema、时间旅行、批量扫描、空间谓词、审计 lineage 和跨引擎兼容；这些不是 Lance/LanceDB 的主要优势。

### 5.2 Lance/LanceDB 适合承担的职责

Lance/LanceDB 适合放在多模态特征区，承担以下能力：

- 管理大规模 embedding：文本政策、审批附件、遥感 chip、街景/现场照片、GeoFM/AlphaEarth 特征。
- 向量近邻检索：按地块、网格、证据片段、影像 chip 找相似对象。
- 多模态 RAG：Agent 查询“类似违规形态”“相似规划冲突”“相似历史演化片区”时提供候选召回。
- 模型训练加速：为 future_latent_state、representation learning 和 candidate ranking 提供高维特征切片。
- 表征版本管理：保存 feature_model_version、embedding_dim、normalization、source_snapshot_id。

### 5.3 推荐集成方式

推荐把 Lance/LanceDB 作为 sidecar，而不是主链路：

```text
Iceberg/PostGIS 主事实对象
  object_id / evidence_id / snapshot_id
        |
        v
Lance/LanceDB 向量数据集
  vector, vector_type, model_version, source_uri, quality_flags
        |
        v
TWM state builder 按需拉取向量特征
```

MinIO/S3 上可以同时承载 Iceberg warehouse 和 Lance dataset，但命名空间必须分离：

```text
s3://gis-agent-lakehouse/warehouse/iceberg/...
s3://gis-agent-lakehouse/raw/...
s3://gis-agent-lakehouse/curated/mmfe/...
s3://gis-agent-lakehouse/features/lance/...
s3://gis-agent-lakehouse/artifacts/twm/...
```

TWM 状态快照只记录向量引用和特征版本，不应把巨大的向量数组全部塞进 JSONB。训练或推演时再从 Lance/Iceberg 特征表读取。

### 5.4 引入 Lance/LanceDB 的触发条件

建议满足任一条件后再正式引入：

- embedding 数量达到百万级以上，并且需要低延迟 ANN 检索。
- 多模态证据检索成为 TWM 规划、复核或 Agent 问答的常用路径。
- GeoFM/AlphaEarth/遥感 chip embedding 需要频繁参与 future_latent_state 或 dynamics 训练。
- Iceberg 批量扫描可以完成训练，但无法满足交互式相似检索延迟。
- 需要在 Notebook 或 API 中快速查看“与当前地块状态相似的历史样本/区域/证据”。

如果只是批量训练，Iceberg + Parquet 中保存向量列也可以先满足需求；如果要做交互式语义/图像/遥感相似检索，再引入 LanceDB 更合理。

## 6. 对当前 TWM 的落地建议

当前阶段建议按优先级推进：

1. 固化 MinIO + Iceberg + Sedona + PostGIS 的主数据湖链路，保证大数据量空间分析、版本化和审计 lineage。
2. 将 MMFE 输出的 object/relation/rule/evidence/feature 明确映射到 TWM state snapshot schema。
3. 对 future_latent_state v2 继续保留高维 latent vector，但在状态元数据中只保存摘要、版本和引用；大规模向量表放 Iceberg 或 Lance sidecar。
4. 先定义 `vector_feature_ref` 契约，包括 `object_id`、`snapshot_id`、`vector_type`、`model_version`、`uri`、`embedding_dim`、`quality_flags`。
5. 等真实多模态数据和 GeoFM/AlphaEarth 批量特征进入后，再决定是否从 Iceberg vector tables 升级到 Lance/LanceDB。

也就是说，Lance/LanceDB 是 TWM 迈向多模态世界模型的有价值增强，但不是当前架构的必需前提。主事实、主审计和主训练快照仍应稳定落在 Iceberg/PostGIS/MinIO 这条链路上。

## 7. 推荐目标架构

```text
                 权威自然资源源系统
                         |
                         v
        Raw/Landing: MinIO/S3/HDFS/NAS + checksum
                         |
                         v
       Lakehouse: Iceberg + GeoParquet + COG/STAC
                         |
                 Spark + Sedona 批处理
                         |
                         v
      MMFE: object / relation / rule / evidence / feature
             |                           |
             v                           v
PostgreSQL/PostGIS + JSONB       Iceberg state/training snapshots
             |                           |
             +------------+--------------+
                          |
                          v
             TWM renderer / state builder
                          |
                          v
 future_latent_state / dynamics / simulator / planner / validation
                          |
                          v
        reports / notebooks / tiles / audit packages / API

可选侧车：
MMFE/TWM feature refs -> Lance/LanceDB vector datasets -> 相似检索、多模态 RAG、latent training acceleration
```
