# 元数据管理体系实施指南

> 版本：v1.0 (2026-03-28)
>
> 目标：基于完整元数据架构，实施数据资产管理优化

---

## 一、文档关系

本指南整合了三份文档的内容：

| 文档 | 定位 | 关系 |
|------|------|------|
| `metadata_management_architecture.md` | **架构设计** | 完整的四层元数据体系架构 |
| `data_asset_management_optimization.md` | **问题分析** | 当前痛点 + 快速优化方案 |
| 本文档 | **实施指南** | 架构落地 + 分阶段实施 |

**核心思路**：用完整的元数据架构解决数据资产管理的实际问题。

---

## 二、问题与方案映射

### 2.1 问题 A：文件来源未标记

**现象**：无法区分上传的原始数据、生成的结果、临时文件

**架构方案**：
- `operational_metadata.source.type`: `uploaded` | `generated` | `temp`
- `operational_metadata.creation.tool`: 记录生成工具
- `operational_metadata.creation.params`: 记录生成参数

**实施**：
1. 上传时：`app.py` 文件处理 → 标记 `source.type = "uploaded"`
2. 生成时：`gis_processors.py` → 标记 `source.type = "generated"` + `creation.tool`

### 2.2 问题 B：地理元数据缺失

**现象**：查询"与重庆相关的数据"不精确

**架构方案**：
- `technical_metadata.spatial.extent`: 自动提取 bbox
- `business_metadata.geography.region_tags`: 推理地区标签 ["重庆市", "西南"]
- `MetadataEnricher.enrich_geography()`: bbox → 地区标签映射

**实施**：
1. `MetadataExtractor` 从文件提取 bbox
2. `MetadataEnricher` 根据 bbox 匹配省级行政区
3. 添加所属大区标签（西南、华东等）

### 2.3 问题 C：数据目录注册不完整

**现象**：上传文件未注册，数据目录与实际文件不同步

**架构方案**：
- 统一注册入口：`MetadataManager.register_asset()`
- 上传流程集成：`app.py` 文件保存后自动注册
- 生成流程集成：`gis_processors.py` 输出后自动注册

---

## 三、分阶段实施策略

### Phase 1: 最小可行方案 (MVP, 2 天)

**目标**：解决最紧迫的问题 — 文件分类 + 地区标签

**范围**：
1. 数据库迁移：新增 `source_type` 和 `region_tags` 字段到现有 `agent_data_catalog` 表
2. 简化版 `MetadataEnricher`：只实现 `enrich_geography()` 和 `enrich_domain()`
3. 上传流程集成：提取 bbox + 匹配地区 + 注册
4. 改进 `list_user_files()`：按 source_type 分类展示

**不包含**：
- 新表 `agent_data_assets`（继续使用现有 `agent_data_catalog`）
- 完整的 JSONB 元数据结构
- `MetadataManager` 完整实现

**交付物**：
- Migration 044a: `ALTER TABLE agent_data_catalog ADD COLUMN source_type, region_tags`
- `metadata_enricher.py` (简化版，150 行)
- `app.py` 上传集成 (20 行)
- `toolsets/file_tools.py` 改进 (30 行)

### Phase 2: 完整元数据架构 (1 周)

**目标**：实施完整的四层元数据体系

**范围**：
1. 创建新表 `agent_data_assets` (JSONB 结构)
2. 数据迁移：从 `agent_data_catalog` 迁移到 `agent_data_assets`
3. 实现完整的 `MetadataManager` + `MetadataExtractor` + `MetadataEnricher`
4. 新增 `search_user_data()` 工具
5. 集成到 GIS 处理流程

**交付物**：
- Migration 044b: 完整表结构 + 数据迁移
- `metadata_manager.py` (300 行)
- `metadata_extractor.py` (200 行)
- `metadata_enricher.py` (完整版，250 行)
- `toolsets/exploration_tools.py` 新增 `search_user_data` (60 行)

### Phase 3: 前端可视化 (3 天)

**目标**：元数据可视化 + 高级搜索

**范围**：
1. 元数据详情面板：展示四层元数据
2. 数据目录增强：地区标签筛选、来源类型筛选
3. 高级搜索界面：多条件组合查询

**交付物**：
- `frontend/src/components/MetadataPanel.tsx`
- `datapanel/CatalogTab.tsx` 增强
- `datapanel/SearchTab.tsx` (新)

---

## 四、推荐实施路径

### 路径 A: 快速见效 (推荐)

**适用场景**：需要快速解决当前痛点，后续逐步完善

**步骤**：
1. **Week 1**: Phase 1 MVP (2 天) + 测试验证 (1 天)
2. **Week 2**: 用户试用 + 收集反馈
3. **Week 3-4**: Phase 2 完整架构
4. **Week 5**: Phase 3 前端可视化

**优势**：
- 2 天内见效，快速验证方案
- 渐进式演进，风险可控
- 用户反馈驱动后续开发

### 路径 B: 一步到位

**适用场景**：有充足时间，追求架构完整性

**步骤**：
1. **Week 1-2**: Phase 2 完整架构实施
2. **Week 3**: Phase 3 前端可视化
3. **Week 4**: 测试 + 文档

**优势**：
- 架构完整，避免二次重构
- 功能完备，一次性交付

**劣势**：
- 交付周期长，见效慢
- 前期投入大

---

## 五、技术决策

### 5.1 数据库表结构选择

**选项 1: 扩展现有表 `agent_data_catalog`**

```sql
ALTER TABLE agent_data_catalog
  ADD COLUMN source_type VARCHAR(20),
  ADD COLUMN region_tags JSONB;
```

**优势**：
- 改动最小，风险低
- 无需数据迁移
- 向后兼容

**劣势**：
- 表结构臃肿（已有 20+ 列）
- 元数据分散，不易扩展

**选项 2: 新建表 `agent_data_assets` (JSONB)**

```sql
CREATE TABLE agent_data_assets (
    id SERIAL PRIMARY KEY,
    technical_metadata JSONB,
    business_metadata JSONB,
    operational_metadata JSONB,
    lineage_metadata JSONB
);
```

**优势**：
- 结构清晰，易扩展
- JSONB 灵活，支持任意元数据
- 符合架构设计

**劣势**：
- 需要数据迁移
- 改动较大

**推荐**：
- **Phase 1 MVP**: 选项 1（快速见效）
- **Phase 2**: 迁移到选项 2（长期架构）

### 5.2 地区标签匹配策略

**选项 1: 硬编码 bbox 字典**

```python
REGION_BBOXES = {
    "重庆市": (105.28, 28.16, 110.19, 32.20),
    "四川省": (97.35, 26.05, 108.55, 34.32),
}
```

**优势**：简单快速，无外部依赖

**劣势**：维护成本高，精度有限

**选项 2: PostGIS 空间查询**

```sql
SELECT name FROM china_provinces
WHERE ST_Intersects(geom, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326));
```

**优势**：精确，易维护

**劣势**：需要省界数据

**推荐**：
- **Phase 1**: 选项 1（硬编码 10 个重点省份）
- **Phase 2**: 选项 2（PostGIS 查询）

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 历史数据无元数据 | 查询不完整 | 后台任务批量补充 |
| bbox 提取性能 | 大文件慢 | 异步处理 + 进度提示 |
| 地区匹配误差 | 边界地区多标签 | 可接受，用户可手动修正 |
| 数据迁移失败 | 服务中断 | 先测试环境验证，保留回滚脚本 |

---

## 七、验收标准

### Phase 1 MVP

- [ ] 用户上传文件后，`agent_data_catalog` 自动记录 `source_type = "uploaded"`
- [ ] 用户上传重庆范围的 shapefile，自动标记 `region_tags = ["重庆市", "西南"]`
- [ ] `list_user_files()` 返回分类展示：原始数据 / 分析结果
- [ ] 查询"我有哪些与重庆相关的数据"返回精确结果

### Phase 2 完整架构

- [ ] `agent_data_assets` 表创建成功，数据迁移完成
- [ ] `MetadataManager.register_asset()` 可注册完整四层元数据
- [ ] `search_user_data(region="重庆")` 返回正确结果
- [ ] GIS 处理生成的文件自动记录血缘关系

### Phase 3 前端

- [ ] 数据目录 Tab 支持按地区、来源类型筛选
- [ ] 点击数据集显示元数据详情面板
- [ ] 高级搜索支持多条件组合

---

## 八、下一步行动

**决策点**：选择实施路径

1. **路径 A (推荐)**：Phase 1 MVP (2 天) → 试用反馈 → Phase 2
2. **路径 B**：直接实施 Phase 2 完整架构 (2 周)

**需要确认**：
- 优先级：快速见效 vs 架构完整？
- 时间预算：2 天 vs 2 周？
- 是否需要前端可视化（Phase 3）？

**建议**：先实施 Phase 1 MVP，验证方案有效性后再决定是否继续 Phase 2。
