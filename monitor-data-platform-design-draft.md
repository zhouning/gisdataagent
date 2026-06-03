# 监测数据底座技术调研与设计草稿

> 文档状态：调研草稿
> 日期：2026-06-02
> 说明：本文档汇总了项目前期技术调研结论和初步设计方案，供团队评审参考。

---

## 目录

1. [项目背景与定位](#1-项目背景与定位)
2. [前端地图框架调研](#2-前端地图框架调研)
3. [数据建模方法论](#3-数据建模方法论)
4. [时空数据底座建模设计](#4-时空数据底座建模设计)
5. [数据关联关系设计](#5-数据关联关系设计)
6. [图数据库方案](#6-图数据库方案)
7. [AI 集成方案](#7-ai-集成方案)
8. [Schema 设计](#8-schema-设计)
9. [建模工具选型](#9-建模工具选型)
10. [业务用户操作设计](#10-业务用户操作设计)
11. [技术栈总览](#11-技术栈总览)
12. [待决事项](#12-待决事项)

---

## 1. 项目背景与定位

### 1.1 项目目标

建设一套监测数据底座平台，以时空数据为核心，汇聚遥感影像、无人机数据、监控视频、文本文档、业务矢量图斑等多源异构数据，梳理图斑之间的演化关系，为后续接入 AI 能力做好准备。

### 1.2 数据特征

| 数据类型 | 数据形态 | 数据量级 | 存储范式 |
|---------|---------|---------|---------|
| 遥感影像 | 栅格（多波段 TIFF） | 单景 1~10GB，总量 PB 级 | 对象存储 + COG 格式 |
| 无人机数据 | 正射影像 + 视频 + 点云 | 单次飞行 10~100GB | 对象存储 + 瓦片化 |
| 监控视频 | 流媒体（H.264/H.265） | 每路 2~8Mbps，7×24 连续 | 视频存储/流媒体服务 |
| 文本 | 结构化/半结构化 | 报告、巡查记录、监测日志 | 关系型数据库 + 全文索引 |
| 业务矢量图斑 | 矢量（Polygon/Line/Point） | 万~百万条要素 | 空间数据库（PostGIS） |

### 1.3 核心业务诉求

- 梳理图斑之间的演化关系（延续、扩张、收缩、分裂、合并、新增、消失、类型变更）
- 支持多源异构数据的统一管理和关联查询
- 为后续 AI 分析能力（变化预测、模式识别、智能推理）做好数据准备
- 交付给政府客户后，业务人员可无代码操作

---

## 2. 前端地图框架调研

### 2.1 MapLibre GL JS 调研结论

**结论：MapLibre GL JS 是开源矢量地图渲染的事实标准，值得长期投入。**

| 维度 | 评估 |
|------|------|
| 定位 | WebGL 驱动的矢量瓦片渲染引擎，Mapbox GL JS 的开源分叉 |
| 许可证 | BSD-3（完全免费，企业友好） |
| 原生投影 | EPSG:3857（Web Mercator）+ Globe（v5 新增） |
| 社区健康度 | GitHub 10,500+ Stars，673+ 贡献者，npm 周下载量 210 万+ |
| 企业赞助 | AWS（$648K）、Microsoft（$310K）、Meta（$300K） |
| 治理 | Linux Foundation LFX Insights 跟踪 |
| 版本进展 | v5（2025）已发布 Globe 投影，v6 即将推出 + WebGPU 支持 |

### 2.2 坐标系问题

MapLibre 原生只支持 EPSG:3857 和 Globe，不支持 CGCS2000（EPSG:4490）等非墨卡托投影。

**应对方案：**
- 底图用天地图等提供的 EPSG:3857 瓦片服务
- 业务数据在服务端做坐标转换（CGCS2000 → WGS84/3857）
- GeoJSON 数据接受 WGS84 经纬度坐标，MapLibre 内部自动投影到 3857 渲染

### 2.3 与其他框架对比

| 框架 | 定位 | 适用场景 | 本项目选用 |
|------|------|---------|:---:|
| MapLibre GL JS | 矢量瓦片渲染 | 交互式矢量地图、大数据可视化 | ✅ |
| Leaflet | 轻量 2D 地图 | 简单标记/弹窗 | ❌ 功能不足 |
| OpenLayers | 全功能 GIS | 专业 GIS 分析 | ❌ 过重 |
| CesiumJS | 3D 地球 | 3D 地形/倾斜摄影/BIM | 🔶 可选补充 |
| Mapbox GL JS | MapLibre 商业上游 | 预算充足的商业项目 | ❌ BSL 许可 |

### 2.4 选型建议

采用 **MapLibre GL JS** 作为 2D 地图主框架，如后续需要 3D 场景可补充 **CesiumJS**。学习投入优先级：

1. MapLibre GL JS 核心 API + Style Spec（必学）
2. Turf.js 空间分析（前端 GIS 补充）
3. 矢量瓦片服务端（Martin / pg_tileserv）
4. deck.gl 大数据可视化（按需）

---

## 3. 数据建模方法论

### 3.1 三大建模流派

| 流派 | 核心思想 | 适用场景 | 本项目采用 |
|------|---------|---------|:---:|
| Kimball 维度建模 | 事实表 + 维度表，自底向上 | 快速交付报表/BI 分析 | ✅ 主方法 |
| Inmon 范式建模 | 3NF ER 模型，自顶向下 | 大型企业全局一致性 | ❌ 太重 |
| Data Vault 2.0 | Hub + Link + Satellite | 多源异构、审计要求高 | 🔶 可借鉴 |

**2025 年趋势：混合架构。** 在 Medallion Architecture 中，Bronze 层保留原始数据，Silver 层用 Data Vault 做集成（可审计），Gold 层用 Kimball 维度模型面向业务分析。

### 3.2 本项目的建模特殊性

与传统数据中台（电商/金融）不同，本项目是时空数据底座：

- 5 种数据类型、5 种存储范式，不能用一套模型硬套
- 图斑演化关系是核心业务对象，需要图数据库表达
- 空间和时间是天然的关联键

### 3.3 建模流程

```
Step 1: 数据域划分（按数据物理形态 + 采集方式）
Step 2: 统一元数据模型设计（参考 STAC 标准）
Step 3: 各数据域的明细表/维度表/事实表设计
Step 4: 汇总层设计
Step 5: 关联关系定义
Step 6: 图数据库 Schema 设计
```

---

## 4. 时空数据底座建模设计

### 4.1 数据分类体系

```
监测数据底座
├── 遥感数据域
│   ├── 光学卫星影像（Sentinel-2、高分系列等）
│   ├── SAR 雷达影像（Sentinel-1、高分三号）
│   └── 高光谱/热红外
│
├── 无人机数据域
│   ├── 正射影像（DOM）
│   ├── 数字高程模型（DEM/DSM）
│   ├── 倾斜摄影三维模型
│   ├── 无人机视频
│   └── 点云数据
│
├── 视频监控数据域
│   ├── 固定监控视频流
│   ├── 球机/云台抓拍
│   └── AI 识别事件片段
│
├── 矢量图斑数据域
│   ├── 土地利用现状图斑
│   ├── 规划管控图斑
│   ├── 变化检测图斑
│   ├── 权属/宗地图斑
│   └── 业务巡查轨迹
│
└── 文本文档数据域
    ├── 监测报告
    ├── 巡查记录
    ├── 政策法规文档
    └── 监测日志/告警日志
```

### 4.2 数仓分层架构

```
数据源（MySQL/API/日志/文件）
  │
  ▼
ODS 贴源层（原始数据 1:1 同步，不做清洗）
  │
  ▼
DIM 公共维度层（一致性维度表：区域、地类、时间、数据来源）
DWD 明细层（数据清洗、标准化、维度退化）
  │
  ▼
DWS 汇总层（按主题域轻度汇总）
  │
  ▼
ADS 应用层（面向具体业务场景：报表、大屏、AI 分析）
```

### 4.3 核心表结构（初步）

#### 维度表

| 表名 | 说明 | 关键字段 |
|------|------|---------|
| dim_date | 时间维度 | date_id, date_value, year, month, quarter |
| dim_region | 行政区划维度 | region_id, region_code, region_name, region_level, geom |
| dim_land_class | 地类维度 | land_class_id, land_class_code, land_class_name, level |
| dim_data_source | 数据来源维度 | source_id, source_name, source_type, resolution |
| dim_monitor_camera | 监控摄像头 | camera_id, camera_code, camera_name, geom, fov_direction |

#### 事实表/明细表

| 表名 | 说明 | 关键字段 |
|------|------|---------|
| dwd_patch | 图斑明细表（核心） | patch_id, period, land_class_id, area, geom, region_id, status |
| dwd_land_change_monitor | 土地变化监测事实表 | record_id, monitor_date, patch_id, before_class_id, after_class_id, change_type |
| biz_monitor_event | 业务事件表 | event_id, event_type, event_time, geom, event_detail(JSONB) |
| biz_event_lineage | 事件流程关联表 | task_id, upstream_event_id, downstream_event_id, relation_type |
| dwd_monitor_document | 监测文档表 | doc_id, doc_title, doc_type, region_id, related_patch, file_path |

#### 汇总层

| 表名 | 说明 |
|------|------|
| dws_region_monthly_change | 按区域+月份+地类的变化汇总 |
| dws_h3_monthly_coverage | 按 H3 格子+月份的数据覆盖统计 |

#### 元数据层

| 表名 | 说明 |
|------|------|
| stac_imagery_catalog | 遥感影像元数据（STAC 标准） |
| meta_data_lineage | 数据血缘表 |

### 4.4 遥感影像存储方案

| 要素 | 方案 |
|------|------|
| 影像格式 | COG（Cloud Optimized GeoTIFF），OGC 标准 |
| 存储位置 | MinIO（自建）或阿里云 OSS |
| 元数据索引 | STAC Catalog → PostgreSQL 存储元数据 JSON |
| 服务发布 | TiTiler / GeoServer |
| 前端渲染 | MapLibre GL JS + COG 动态加载 |

### 4.5 统一元数据模型（参考 STAC）

采用 STAC（SpatioTemporal Asset Catalog）标准描述各类时空数据的元数据：

- 标识：id, data_domain, data_type
- 空间：geometry(GeoJSON), bbox, crs
- 时间：datetime, start_datetime, end_datetime
- 来源：platform, provider
- 资产：assets[].href, assets[].type

STAC 已被 NASA、USGS、Microsoft Planetary Computer、OGC、Esri 等广泛采纳，是遥感影像元数据管理的事实标准。

---

## 5. 数据关联关系设计

### 5.1 五种关联维度

| 关联维度 | 举例 | 策略 |
|---------|------|------|
| 空间关联 | 图斑与覆盖它的遥感影像 | H3 粗筛 + GiST 精算 |
| 时间关联 | 同时段的无人机飞行与监控视频 | 时间窗口实时查询 |
| 业务流程关联 | 变化检测图斑 → 核查记录 → 报告 | 显式存储（外键+流程 ID） |
| 派生/血缘关联 | 影像 → NDVI → 植被分类图 | 显式存储（血缘表） |
| 语义关联 | 巡查记录提到某个图斑编号 | NLP 抽取/人工标注 |

### 5.2 空间关联：H3 网格编码

采用 Uber 开源的 H3 六边形网格系统做统一空间索引：

| H3 层级 | 六边形边长 | 适用场景 |
|---------|-----------|---------|
| Res 5 | ~8.5 km | 区县级分析 |
| Res 7 | ~1.2 km | 乡镇级/图斑级 |
| Res 9 | ~174 m | 精细图斑关联 |
| Res 11 | ~25 m | 摄像头/设备级 |

**查询策略：H3 粗筛（B-Tree，毫秒级） → GiST 精算（百毫秒级） → 业务过滤（毫秒级）。**

### 5.3 业务流程关联

设计 `biz_monitor_event` + `biz_event_lineage` 两张表，记录监测业务的完整事件链：

```
影像获取 → AI变化检测 → 生成变化图斑 → 无人机派遣 → 现场核查 → 生成报告 → 案件结案
```

每条事件记录包含 event_type、event_time、operator、geom、event_detail(JSONB)，通过 task_id 串联整个流程。

### 5.4 数据血缘关联

设计 `meta_data_lineage` 表记录数据的派生关系：

```
原始影像 → NDVI产品（NDVI_CALC 算法）
原始影像 → 变化检测结果（CHANGE_DETECT 算法）
变化检测结果 → 变化图斑（VECTORIZE 算法）
变化图斑 → 统计报表（AGGREGATE 流程）
```

---

## 6. 图数据库方案

### 6.1 引入原因

本项目核心诉求是梳理图斑之间的演化关系，关系是第一公民。图数据库在以下场景优于关系型数据库：

- 3 层以上的关系链路追踪
- 10 种以上关联类型
- 图斑完整演化链条的可视化
- 为 AI 训练（GNN、知识图谱嵌入）提供天然的数据结构

### 6.2 选型结论

| 数据库 | 推荐度 | 原因 |
|--------|:---:|------|
| **NebulaGraph** | ⭐⭐⭐⭐⭐ | 国产开源、原生分布式、十亿级边性能优异、信创兼容 |
| Neo4j Community | ⭐⭐⭐ | 生态最成熟、Cypher 强大，但社区版单节点限制 |
| Apache AGE | ⭐⭐⭐⭐ | PG 图扩展，零额外组件，适合试水 |

**推荐方案：NebulaGraph 作为独立图数据库，与 PostgreSQL 并行部署。**

### 6.3 图数据库 Schema 设计

#### 节点类型（Tag）

| Tag 名称 | 关键属性 | 说明 |
|---------|---------|------|
| patch | patch_id, period, land_class, area, h3_index, region_code | 图斑节点 |
| imagery | imagery_id, title, platform, capture_time, gsd, cloud_cover | 影像节点 |
| region | region_code, region_name, region_level | 区域节点 |

#### 边类型（Edge Type）

| Edge 名称 | 关键属性 | 说明 |
|-----------|---------|------|
| **evolve_to** | evolve_type, overlap_ratio, area_change, class_changed, confidence, verify_status | **图斑演化关系（核心）** |
| covered_by | overlap_ratio, band_info | 图斑被影像覆盖 |
| belong_to | — | 图斑属于区域 |
| trigger | event_type, event_id | 图斑触发业务事件 |
| derived_from | process_name, process_time | 数据派生关系 |
| verified_by | result | 图斑被无人机/人工核查 |

### 6.4 演化关系的 8 种类型

| 演化类型 | 含义 | 判定条件 |
|---------|------|---------|
| continue | 延续（边界和类型基本不变） | IoU > 0.8 且地类不变 |
| type_change | 类型变更（边界不变，地类变了） | IoU > 0.8 且地类变化 |
| expand | 扩张（面积增大） | 旧被新覆盖 > 80%，新面积 > 旧面积 |
| shrink | 收缩（面积减小） | 新被旧覆盖 > 80%，新面积 < 旧面积 |
| split | 分裂（一个变多个） | 1 个旧图斑对应 2+ 个新图斑 |
| merge | 合并（多个变一个） | 2+ 个旧图斑对应 1 个新图斑 |
| appear | 新增（上期不存在） | 新图斑与任何旧图斑 IoU < 0.1 |
| disappear | 消失（下期不存在） | 旧图斑与任何新图斑 IoU < 0.1 |

### 6.5 双库协作模式

```
PostgreSQL + PostGIS          NebulaGraph
├── 存：实体数据               ├── 存：关联关系
│   属性、空间、业务字段        │   演化边、血缘边、事件边
│                             │
├── 空间查询                   ├── 链路追踪
│   ST_Intersects 等           │   N 跳关系遍历
│                             │
└── 聚合统计                   └── 图算法
    GROUP BY 等                   中心性、路径分析
```

### 6.6 分阶段引入策略

| 阶段 | 方案 | 时间 |
|------|------|------|
| Phase 1 | PostgreSQL + 关联表 + H3 编码，不加图数据库 | 现在 |
| Phase 2 | 部署 NebulaGraph，迁移关联关系到图数据库 | 3~6 个月后 |
| Phase 3 | 构建时空知识图谱，接入 AI 推理 | 长期演进 |

---

## 7. AI 集成方案

### 7.1 三种查询模式

| 模式 | 说明 | 安全性 | 灵活性 | 落地难度 |
|------|------|--------|--------|---------|
| Function Calling（工具调用） | AI 调用预封装的工具函数 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 低 |
| Text-to-SQL / Text-to-Cypher | AI 把自然语言翻译成查询语句 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 中 |
| GraphRAG（图增强检索） | 从图数据库检索子图辅助 AI 推理 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 中高 |

**建议：先做模式 A，再扩展 B 和 C。**

### 7.2 Function Calling：12 个核心工具

| 工具名称 | 说明 | 查询目标 |
|---------|------|---------|
| search_patches | 按条件搜索图斑 | PostgreSQL |
| get_patch_detail | 获取单个图斑完整信息 | PostgreSQL |
| query_patch_evolution | 查询图斑演化历史链条 | 图数据库 |
| query_evolution_stats | 统计某区域某时期的演化情况 | 图数据库 |
| find_change_patches | 查找指定条件下的变化图斑 | PostgreSQL + 图数据库 |
| search_imagery | 按空间范围和时间搜索影像 | STAC 元数据 |
| get_imagery_for_patch | 查找覆盖某图斑的影像 | PostgreSQL（空间查询） |
| search_cameras_near | 查找某位置附近的摄像头 | PostgreSQL（空间查询） |
| search_uav_flights | 查找某区域/时间的无人机飞行记录 | PostgreSQL |
| get_patch_full_context | 获取图斑全生命周期上下文 | PG + 图数据库联合 |
| analyze_region_trend | 分析某区域多年土地利用变化趋势 | 图数据库 + PostgreSQL |
| search_reports | 全文搜索监测报告 | Elasticsearch |

### 7.3 技术实现：MCP 协议

采用 Anthropic 推出的 MCP（Model Context Protocol）标准，将工具函数暴露给 AI：

- Python + FastMCP 构建 MCP Server
- 每个工具函数用 `@mcp.tool()` 装饰器注册
- AI 客户端通过 MCP 协议调用工具
- Schema 文档通过 MCP Resource 按需加载

### 7.4 Text-to-SQL / Text-to-Cypher

- 给 AI 喂完整的 Schema 文档（表结构 + 业务语义 + 查询示例）
- 安全护栏：只允许 SELECT、加 LIMIT、超时保护、敏感词过滤
- 关键：Schema 文档质量决定 AI 生成查询的准确率

### 7.5 GraphRAG

适用于深度推理场景（"为什么变了""有什么共同特征""是否有违规模式"）：

1. 从用户问题中提取关键实体
2. 从图数据库检索相关子图（2~3 跳扩展）
3. 将子图转化为自然语言上下文
4. LLM 基于上下文综合分析回答

### 7.6 AI 为图斑演化数据提供的能力

- 导出 GNN 训练数据（节点特征 + 边特征 → PyTorch Geometric / DGL）
- 导出时序分类训练数据（连续 N 期属性序列 → 变化类型预测）
- 导出知识图谱嵌入训练数据（三元组 → 关系推理）

---

## 8. Schema 设计

### 8.1 Schema 的定义

Schema 不是单纯的建表语句，而是给 AI 看的"数据库使用手册"，包含 5 层内容：

| 层次 | 内容 | 解决的问题 |
|------|------|-----------|
| 第 1 层：表清单 | 有哪些表、每张表干什么 | AI 知道查哪张表 |
| 第 2 层：字段定义 | CREATE TABLE + 类型 | AI 知道有哪些列 |
| 第 3 层：关系说明 | JOIN 条件、空间关联方式 | AI 知道表怎么连 |
| 第 4 层：业务语义 | 枚举值、单位、业务规则 | AI 理解业务含义 |
| 第 5 层：查询示例 | 10~15 个典型 SQL/Cypher | AI 学习怎么写查询 |

### 8.2 Schema 的存储

- 数据库里存"机器读的 Schema"（information_schema，DDL）
- 独立 Markdown 文档存"AI 读的 Schema"（含业务语义、查询示例）
- 两份合并后作为 AI 的 System Prompt

### 8.3 存储位置

```
docs/03-development/
├── ai-schema.md              # AI Schema 文档（合并版）
├── db-schema-postgres.md     # PostgreSQL Schema 说明
└── db-schema-graph.md        # 图数据库 Schema 说明
```

### 8.4 维护方式

- 脚本自动从数据库导出 DDL 部分
- 人工补充业务语义和查询示例
- 文件进 Git 版本管理
- 每次改表结构必须同步更新

---

## 9. 建模工具选型

### 9.1 传统工具评估

| 工具 | 定位 | 本项目适用性 |
|------|------|:---:|
| Enterprise Architect | 综合架构建模（UML） | ❌ 太重，不支持图数据库 |
| PowerDesigner | 传统企业级建模 | ❌ SAP 已标记即将停止支持 |
| ERwin | 行业级建模 | ❌ 价格高，不支持图数据库 |
| Dataphin | 阿里 OneData 产品化 | 🔶 如果上阿里云可考虑 |

### 9.2 推荐方案：分层建模，代码驱动

| 层次 | 工具 | 产出 | 说明 |
|------|------|------|------|
| 概念模型 | Draw.io | ER 图（.drawio） | 免费、轻量、给甲方/PM 看 |
| 逻辑模型 | DBML + DBeaver | 表结构定义（.dbml） | 文本格式、进 Git |
| 物理模型 | Flyway | SQL 迁移脚本（.sql） | 可执行、自动版本管理 |
| 图模型 | nGQL 脚本 | NebulaGraph Schema（.ngql） | 图数据库原生 |
| AI Schema | Markdown | db-schema.md | AI 可读、人工维护 |

**核心区别：传统做法是"工具驱动"（EA 画图 → 导出 DDL），本项目采用"代码驱动"（DDL 就是代码，Git 管理，自动部署）。**

### 9.3 验收交付策略

如甲方要求交付 EA 模型文件：
- 日常开发用轻量工具（DBML + SQL）
- 验收时从实际数据库反向生成 ER 图（DBeaver 导出 或 EA 逆向工程）
- EA 只是交付工具，不是日常开发工具

---

## 10. 业务用户操作设计

### 10.1 操作分类

| 类型 | 频率 | 操作内容 | 操作人 |
|------|------|---------|--------|
| 日常操作 | 每周 | 入库数据、复核关系、浏览地图、AI 问答 | 业务操作员 |
| 扩展操作 | 每月/每季 | 新增数据类型、修改匹配规则、调整编码体系 | 业务主管/管理员 |
| 配置操作 | 一次性 | 配置数据源、配置定时任务 | 系统管理员 |

### 10.2 核心操作界面设计

#### 操作 ①：数据入库（四步向导）

```
Step 1: 上传文件（拖拽上传，自动识别格式和坐标系）
Step 2: 字段映射（系统自动匹配，用户确认/修正）
Step 3: 预览确认（质量检查 + 演化关系预匹配结果）
Step 4: 确认入库（写入 PG + 图数据库）
```

设计要点：
- 支持 Shapefile、GeoJSON、Excel、CSV 等格式
- 字段自动映射（模糊匹配算法）
- 入库前自动做空间叠加匹配，预览演化关系分布
- 地类编码自动转换（支持多种编码体系）

#### 操作 ②：关系复核工作台

- 左侧：待复核列表（按置信度排序）
- 右侧：地图对比视图（T1/T2 两期图斑叠加 + 影像底图）
- 操作：一键确认 / 修正演化类型 / 标记误检 / 拖拽手动关联
- 置信度 > 0.7 的自动确认，低于的进入人工复核队列

#### 操作 ③：新增数据类型（模板化）

- 提供预置模板（IoT 传感器、统计报表、调查记录等）
- 表单式定义字段（名称、类型、是否必填）
- 配置空间关联方式和时间关联方式
- 系统自动建表（PG + 图数据库 Tag）+ 更新 AI Schema

#### 操作 ④：AI 助手

- 聊天界面，自然语言提问
- 支持数据查询、统计分析、深度推理
- 后端通过 MCP 协议调用 12 个工具函数

### 10.3 角色权限

| 角色 | 日常操作 | 扩展操作 | 配置操作 |
|------|---------|---------|---------|
| 业务操作员 | ✅ 入库、复核、浏览、AI 问答 | ❌ | ❌ |
| 业务主管 | ✅ 全部日常 + 统计报表 | ✅ 修改规则、管理编码 | ❌ |
| 系统管理员 | ✅ 全部 | ✅ 全部 | ✅ 数据源、定时任务、用户权限 |

### 10.4 产品功能模块

```
📊 数据全景          ← 全局概览（地图 + 统计图表）
📥 数据入库          ← 上传/导入数据的向导入口
🔗 关系管理          ← 核心模块
  ├─ 关系复核工作台   ← 审核 AI 匹配的演化关系
  ├─ 关系浏览        ← 查看图斑演化链条（图谱可视化）
  └─ 手动关联        ← 人工建立两个数据之间的关系
🗺️ 地图浏览         ← 在地图上查看所有数据
🤖 AI 助手          ← 自然语言对话查数据
📦 数据类型管理      ← 新增/修改数据类型
⚙️ 系统配置         ← 匹配规则、编码转换、定时任务
```

### 10.5 前端技术方案

| 模块 | 技术方案 |
|------|---------|
| 地图渲染 | MapLibre GL JS |
| 栅格影像 | TiTiler（COG 动态切片） |
| 矢量瓦片 | Martin / pg_tileserv |
| 图谱可视化 | D3.js / AntV G6 |
| 视频播放 | flv.js / hls.js |
| 图表统计 | ECharts |
| UI 组件库 | Element Plus |
| AI 对话 | Chat UI 组件 → MCP Server |

---

## 11. 技术栈总览

### 11.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    前端应用层                                  │
│         Vue 3 + MapLibre GL JS + Element Plus + ECharts     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      AI 服务层                                │
│           MCP Server + Function Calling + GraphRAG          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     数据服务层                                 │
│  Martin(矢量瓦片) · TiTiler(栅格) · STAC API · SRS(视频)    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     数据存储层                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │PostgreSQL│  │ Nebula-  │  │  MinIO   │  │Elastic-  │   │
│  │+ PostGIS │  │ Graph    │  │ (对象存储) │  │ search   │   │
│  │          │  │          │  │          │  │          │   │
│  │矢量图斑   │  │演化关系   │  │遥感影像   │  │文本文档   │   │
│  │业务数据   │  │数据血缘   │  │无人机数据 │  │报告日志   │   │
│  │元数据     │  │事件链条   │  │视频片段   │  │          │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 技术选型汇总

| 层次 | 组件 | 技术选型 |
|------|------|---------|
| 前端框架 | Web 框架 | Vue 3 |
| 前端地图 | 2D 地图 | MapLibre GL JS |
| 前端地图 | 3D 场景（可选） | CesiumJS |
| 前端 UI | 组件库 | Element Plus |
| 前端图表 | 统计图表 | ECharts |
| 前端图谱 | 关系可视化 | D3.js / AntV G6 |
| 后端框架 | API 服务 | Python (FastAPI) 或 Java (Spring Boot) |
| 空间数据库 | 矢量 + 业务 | PostgreSQL + PostGIS |
| 图数据库 | 关系 + 血缘 | NebulaGraph |
| 对象存储 | 影像 + 文件 | MinIO |
| 影像格式 | 栅格存储 | COG (Cloud Optimized GeoTIFF) |
| 矢量瓦片 | 服务发布 | Martin / pg_tileserv |
| 栅格服务 | 影像切片 | TiTiler |
| 视频服务 | 流媒体 | SRS / ZLMediaKit |
| 全文检索 | 文本搜索 | Elasticsearch / OpenSearch |
| 元数据 | 数据目录 | STAC FastAPI |
| AI 协议 | 工具调用 | MCP (Model Context Protocol) |
| 数据库迁移 | DDL 管理 | Flyway |
| 空间索引 | 网格编码 | H3 (Uber) |
| 建模设计 | 逻辑模型 | DBML |
| 建模设计 | 概念模型 | Draw.io |
| 容器化 | 部署 | Docker + Docker Compose |

---

## 12. 待决事项

| 编号 | 事项 | 决策人 | 优先级 |
|------|------|--------|--------|
| D-01 | 后端技术栈确认（Python/Java/Go） | 全栈工程师 | 高 |
| D-02 | 坐标系统一方案（CGCS2000 vs WGS84） | PM + 全栈 | 高 |
| D-03 | NebulaGraph vs Apache AGE 最终选型 | 全栈工程师 | 高 |
| D-04 | AI 大模型选型（GPT-4/Claude/通义千问/文心） | PM | 高 |
| D-05 | 部署环境确认（私有云/阿里云/华为云） | PM | 高 |
| D-06 | 甲方是否要求交付 EA 模型文件 | PM | 中 |
| D-07 | 是否需要支持 3D 场景（CesiumJS） | PM | 中 |
| D-08 | 视频监控对接方案（海康/大华私有云 vs 自建 SRS） | 全栈工程师 | 中 |
| D-09 | 信创要求范围（操作系统/数据库/GIS 平台） | PM | 中 |
| D-10 | 图斑演化匹配的阈值参数（需业务确认） | PM + 业务方 | 高 |

---

## 附录 A：关键术语表

| 术语 | 说明 |
|------|------|
| STAC | SpatioTemporal Asset Catalog，时空资产目录，OGC 标准 |
| COG | Cloud Optimized GeoTIFF，云优化 GeoTIFF，OGC 标准 |
| H3 | Uber 开源的六边形层次空间索引系统 |
| MVT | Mapbox Vector Tile，矢量瓦片格式 |
| MCP | Model Context Protocol，Anthropic 推出的 AI 工具调用协议 |
| GNN | Graph Neural Network，图神经网络 |
| GraphRAG | 基于图数据库的检索增强生成 |
| IoU | Intersection over Union，交并比，空间重叠度量 |
| GiST | Generalized Search Tree，PostgreSQL 空间索引类型 |
| nGQL | NebulaGraph Query Language，NebulaGraph 查询语言 |
| DBML | Database Markup Language，数据库标记语言 |
| Flyway | 数据库迁移工具 |

## 附录 B：参考资料

- MapLibre GL JS：https://maplibre.org
- STAC 规范：https://stacspec.org
- OGC COG 标准：https://www.ogc.org/standards/ogc-cloud-optimized-geotiff/
- H3 空间索引：https://h3geo.org
- PostGIS 文档：https://postgis.net/docs/
- NebulaGraph 文档：https://docs.nebula-graph.com.cn
- MCP 协议：https://modelcontextprotocol.io
- Neo4j Text2Cypher：https://neo4j.com/blog/genai/text2cypher-guide/
- 阿里 OneData 方法论：阿里云 DataWorks / Dataphin 文档
- 自然资源"一张图"：中国测绘学会相关文献
