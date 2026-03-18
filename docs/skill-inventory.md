# Data Agent 技能清单

> 系统中所有 Skills 的完整清单：18 个内置 ADK Skills + 用户自定义 Custom Skills + DB 自定义技能包。

---

## 技能总数

| 类别 | 数量 | 存储 | 来源 |
|------|------|------|------|
| **内置 ADK Skills** | 18 | `data_agent/skills/` 目录 | 开发者预定义 |
| **Custom Skills** | 用户创建（每人上限 20） | PostgreSQL `agent_custom_skills` | 用户前端 CRUD |
| **Skill Bundles** | 用户创建（每人上限 30） | PostgreSQL `agent_skill_bundles` | 用户组合编排 |

---

## 18 个内置 ADK Skills

按领域分组：

### GIS 空间分析（6 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 1 | **buffer-overlay** | 缓冲区与叠加分析。创建缓冲区、执行空间叠加（交集/合并/差集/裁剪），统计面积和属性 | buffer, overlay, clip, 缓冲区, 叠加, 裁剪 |
| 2 | **coordinate-transform** | 坐标系转换与验证。CGCS2000/WGS84/GCJ-02/BD-09 转换，验证坐标系正确性 | CRS, coordinate, 坐标系, EPSG, 重投影 |
| 3 | **geocoding** | 地理编码与距离计算。批量正向/逆向编码、驾车距离、POI 搜索、行政区划 | geocode, 地理编码, 地址, POI, 行政区划 |
| 4 | **land-fragmentation** | 土地碎片化分析与 DRL 优化。FFI 指数计算，深度强化学习用地布局优化 | fragmentation, FFI, 碎片化, DRL, 布局优化 |
| 5 | **site-selection** | 多因素选址分析。排除法 + 加权叠加法，支持学校/医院/工厂等选址场景 | site selection, 选址, 适宜性, 多因素 |
| 6 | **ecological-assessment** | 生态环境评估。NDVI + DEM + LULC 综合生态敏感性评价 | ecology, NDVI, DEM, 生态, 遥感, 植被 |

### 数据治理（3 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 7 | **data-profiling** | 空间数据画像与质量评估。全面画像分析，数据质量评分，改进建议 | profile, 画像, 数据质量, 探查, 概览 |
| 8 | **farmland-compliance** | 耕地合规审计。三调规程 + GB/T 21010 标准，字段/拓扑/面积/编码审计 | audit, compliance, 合规, 国土调查, 三调 |
| 9 | **topology-validation** | 拓扑质量检查。重叠/间隙/自相交检测，严重程度分级，修复建议 | topology, 拓扑, overlap, gap, 自相交 |

### 数据库（2 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 10 | **postgis-analysis** | PostGIS 空间数据库分析。ST_* 函数查询、距离/面积/关系计算 | PostGIS, SQL, 空间查询, ST_, 数据库 |
| 11 | **data-import-export** | 数据入库与导出。SHP/GeoJSON/GPKG/KML/CSV 导入 PostGIS，目录与血缘 | import, 入库, 导出, PostGIS, SHP |

### 可视化（2 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 12 | **thematic-mapping** | 专题地图制作。自动选择最佳地图类型，配置分级方法/色彩/图例 | map, choropleth, 专题图, 热力图, 气泡图 |
| 13 | **3d-visualization** | 三维可视化。deck.gl + MapLibre 3D 拉伸/柱状/弧线/散点图层 | 3D, 三维, extrusion, deck.gl, 拉伸 |

### 分析（2 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 14 | **spatial-clustering** | 空间聚类与热点分析。全局 Moran's I、局部 LISA、Getis-Ord Gi* | cluster, hotspot, 聚类, 热点, Moran |
| 15 | **advanced-analysis** | 高级分析。时间序列预测、假设分析、网络中心性、社区检测、可达性 | 时间序列, 预测, forecast, 假设分析, 网络分析 |

### 融合（1 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 16 | **multi-source-fusion** | 多源数据融合。10 种策略，兼容性评估，质量验证 | fusion, 融合, 多源, merge, join, 数据整合 |

### 通用（1 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 17 | **knowledge-retrieval** | 知识库检索与管理。创建私有 KB、文档上传、语义搜索、RAG 增强 | 知识库, knowledge, RAG, 文档检索, 查询知识 |

### 协作（1 个）

| # | 技能名 | 描述 | 触发关键词 |
|---|--------|------|-----------|
| 18 | **team-collaboration** | 团队协作与知识共享。团队管理、记忆存储、资产共享、审计日志 | team, share, 团队, 协作, 共享, 记忆 |

---

## 技能领域分布

```
GIS 空间分析   ██████████████████ 6 (33%)
数据治理       █████████ 3 (17%)
数据库         ██████ 2 (11%)
可视化         ██████ 2 (11%)
分析           ██████ 2 (11%)
融合           ███ 1 (6%)
通用           ███ 1 (6%)
协作           ███ 1 (6%)
```

---

## 技能加载机制

### 三级增量加载

| 级别 | 加载内容 | 时机 | 开销 |
|------|---------|------|------|
| **L1 Metadata** | name, description, domain, intent_triggers | 应用启动 | 极低（仅读 YAML frontmatter） |
| **L2 Instructions** | 完整 Prompt 文本（可达数千字） | 路由匹配到相关 Skill 时 | 低（读文件） |
| **L3 Resources** | 附加资源文件（参考数据、模板） | Skill 执行时 | 按需 |

### SKILL.md 结构

```yaml
---
name: data-profiling                    # 必须与目录名一致 (kebab-case)
description: "空间数据画像与质量评估技能"   # 简短描述
metadata:
  domain: "governance"                   # 领域分类
  version: "2.0"                         # 版本号
  intent_triggers: "profile, 画像, 数据质量"  # 逗号分隔的触发关键词
---

# 空间数据画像与质量评估技能

## 职责
数据画像是所有空间分析的第一步...

## 分析维度
| 检查项 | 内容 | 关注点 |
|--------|------|--------|
| ... | ... | ... |
```

---

## 用户自定义 Custom Skills

用户可在前端"能力"Tab 创建自定义 Skill，每个 Skill 是一个独立的 LlmAgent：

| 字段 | 说明 | 限制 |
|------|------|------|
| `skill_name` | 技能名称 | 100 字符，字母/中文/连字符 |
| `instruction` | 指令（定义 Agent 行为） | 10,000 字符上限，Prompt 注入检测 |
| `description` | 简短描述 | 可选 |
| `toolset_names` | 工具集选择 | 从 23 个 Toolset 中多选 |
| `trigger_keywords` | 触发关键词 | 逗号分隔，子串匹配 |
| `model_tier` | 模型等级 | fast / standard / premium |
| `is_shared` | 共享 | 可选，共享给其他用户 |

**创建方式**: 前端 CapabilitiesView → "+技能" 按钮 → 填写表单 → 创建

**运行时**: `build_custom_agent(skill)` 从 DB 记录动态构建 `LlmAgent` 实例

---

## Skill Bundles（技能包）

用户可组合多个 Toolset + ADK Skills 为可复用的技能包：

| 字段 | 说明 |
|------|------|
| `bundle_name` | 技能包名称 |
| `toolset_names` | 工具集组合 |
| `skill_names` | ADK Skill 组合 |
| `intent_triggers` | 意图触发 |

**用途**: 预配置的工具+技能组合，一键分配给自定义 Skill 或工作流。

---

*本文档基于 GIS Data Agent v12.0 (ADK v1.27.2) 编写。*
