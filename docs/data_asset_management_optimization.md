# 数据资产管理优化方案

> 版本：v1.0 (2026-03-28)
>
> 目标：解决"我有哪些数据？"返回杂乱、"与重庆相关的数据？"不精确等数据检索体验问题

---

## 一、问题分析

### 1.1 现象

| 用户操作 | 期望结果 | 实际结果 |
|----------|----------|----------|
| "我有哪些数据？" | 按类别分组展示：原始数据、分析结果、临时文件 | 平铺列表，所有文件混在一起 |
| "与重庆相关的数据？" | 精确返回空间范围覆盖重庆的数据集 | 不精确，可能返回无关数据或遗漏相关数据 |
| "上次分析生成的结果在哪？" | 返回最近一次 pipeline 生成的输出文件 | 无法区分哪些是生成的、哪些是上传的 |

### 1.2 根因

**A. 文件来源未标记**

当前 `list_user_files()` 只做目录扫描，不区分文件来源：
- 用户上传的原始数据（如 shapefile）
- Pipeline 生成的中间/结果文件（如 buffer_xxx.geojson）
- 临时文件（如解压的 .dbf/.prj 等 sidecar 文件）

**B. 地理元数据缺失**

数据目录 `agent_data_catalog` 虽然有 `spatial_extent` (bbox) 字段，但：
- 上传文件时未自动提取 bbox
- 没有语义化的地区标签（如"重庆"、"西南"）
- 语义层 `semantic_layer.py` 有地区分组知识，但未关联到数据目录

**C. 数据目录注册不完整**

- 用户上传文件时：只存到磁盘，未注册到 `agent_data_catalog`
- Pipeline 生成文件时：通过 `auto_register_from_path()` 注册，但元数据不完整
- 结果：数据目录和实际文件不同步

### 1.3 现有基础设施

| 组件 | 已有能力 | 缺失能力 |
|------|----------|----------|
| `data_catalog.py` | tags, spatial_extent, creation_tool, source_assets | source_type, region_tags, theme |
| `semantic_layer.py` | 地区分组（西南→重庆）、领域映射 | 未关联到数据目录 |
| `file_tools.py` | list_user_files, delete_user_file | 分类展示、元数据查询 |
| `gis_processors.py` | auto_register_from_path | 上传时自动注册 |
| `app.py` 上传处理 | 文件类型分类、zip 解压 | 元数据提取和注册 |

---

## 二、方案设计

### 2.1 核心改动（3 个层面）

```
┌─────────────────────────────────────────────────┐
│  Layer 1: 数据注册增强                            │
│  - 上传时自动注册到 data_catalog                   │
│  - 标记 source_type: uploaded / generated / temp  │
│  - 自动提取空间范围 (bbox)                         │
│  - 自动匹配地区标签 (region_tags)                  │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Layer 2: 数据检索增强                            │
│  - list_user_files 改为分类展示                    │
│  - 新增 search_user_data 支持语义检索              │
│  - 支持按地区、主题、来源类型过滤                    │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│  Layer 3: Agent 提示词优化                        │
│  - 引导 Agent 使用 search_user_data 替代简单列表   │
│  - 对"我有哪些数据"类问题返回结构化摘要             │
└─────────────────────────────────────────────────┘
```

### 2.2 数据库变更

在 `agent_data_catalog` 表新增 2 个字段：

```sql
ALTER TABLE agent_data_catalog
  ADD COLUMN IF NOT EXISTS source_type VARCHAR(20) DEFAULT 'unknown',
  ADD COLUMN IF NOT EXISTS region_tags JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN agent_data_catalog.source_type IS '数据来源: uploaded(用户上传), generated(系统生成), temp(临时文件)';
COMMENT ON COLUMN agent_data_catalog.region_tags IS '地区标签: ["重庆市","西南"]';
```

### 2.3 文件注册增强

**上传时注册** (`app.py` 文件上传处理)：

```python
# 在文件上传成功后，自动注册到数据目录
from data_agent.data_catalog import register_asset

# 提取空间元数据
bbox = extract_bbox(file_path)  # 从 GeoJSON/Shapefile 提取
region_tags = match_regions(bbox)  # 根据 bbox 匹配地区

register_asset(
    asset_name=filename,
    asset_type=detect_type(file_path),
    format=suffix,
    storage_path=str(file_path),
    spatial_extent=bbox,
    source_type="uploaded",
    region_tags=region_tags,
    tags=["用户上传"],
    owner_username=user_id,
)
```

**生成时注册** (`gis_processors.py` 输出路径生成)：

```python
# auto_register_from_path 增强
register_asset(
    ...,
    source_type="generated",
    region_tags=match_regions(bbox),
    tags=["分析结果", creation_tool],
)
```

### 2.4 地区匹配逻辑

利用已有的 `semantic_layer.py` 地区分组知识：

```python
# 新增函数: data_catalog.py
REGION_BBOXES = {
    "重庆市": (105.28, 28.16, 110.19, 32.20),
    "四川省": (97.35, 26.05, 108.55, 34.32),
    "上海市": (120.86, 30.68, 122.12, 31.87),
    # ... 省级行政区 bbox
}

REGION_GROUPS = {
    "西南": ["四川省", "云南省", "贵州省", "西藏自治区", "重庆市"],
    "华东": ["上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省"],
    # ... 从 semantic_catalog.yaml 加载
}

def match_regions(bbox: dict) -> list[str]:
    """根据数据的空间范围匹配地区标签。"""
    if not bbox:
        return []
    tags = []
    data_box = (bbox["minx"], bbox["miny"], bbox["maxx"], bbox["maxy"])
    for region, region_box in REGION_BBOXES.items():
        if boxes_overlap(data_box, region_box):
            tags.append(region)
            # 添加所属大区
            for group, provinces in REGION_GROUPS.items():
                if region in provinces:
                    tags.append(group)
    return list(set(tags))
```

### 2.5 数据检索增强

**改进 `list_user_files()`**：

```python
# 改进后的输出格式
def list_user_files() -> str:
    """列出用户数据文件，按来源分类展示。"""
    # 从 data_catalog 查询，按 source_type 分组

    return """
📁 用户数据概览 (共 12 个文件)

📥 原始数据 (3 个)
  1. 重庆耕地.shp (2.3MB) [重庆市, 西南] — 2026-03-25 上传
  2. 四川林地.geojson (1.1MB) [四川省, 西南] — 2026-03-24 上传
  3. 全国DEM.tif (45MB) [全国] — 2026-03-20 上传

📊 分析结果 (5 个)
  4. buffer_重庆耕地_a3f2.geojson (3.1MB) [重庆市] — 缓冲区分析
  5. ffi_result_b7c1.geojson (2.8MB) [重庆市] — 碎片化指数计算
  6. optimized_layout_c9d4.geojson (2.9MB) [重庆市] — DRL优化结果
  7. quality_report_d1e5.docx (0.5MB) — 质检报告
  8. heatmap_f2g6.html (1.2MB) [重庆市] — 热力图

🔧 临时文件 (4 个)
  9-12. .dbf/.prj/.shx/.cpg sidecar 文件
"""
```

**新增 `search_user_data()`**：

```python
def search_user_data(query: str = "", region: str = "", source_type: str = "") -> str:
    """按条件检索用户数据。

    Args:
        query: 关键词（文件名、标签、描述）
        region: 地区名称（如"重庆"、"西南"）
        source_type: 来源类型（uploaded/generated/all）
    """
    # SQL: SELECT * FROM agent_data_catalog
    #   WHERE owner_username = :user
    #     AND (region_tags @> :region_json OR :region = '')
    #     AND (source_type = :stype OR :stype = 'all')
    #     AND (asset_name ILIKE :query OR tags::text ILIKE :query)
```

### 2.6 Agent 提示词优化

在 ExplorationToolset 的 Agent 指令中添加引导：

```
当用户询问"我有哪些数据"或类似问题时：
1. 优先使用 search_user_data() 而非 list_user_files()
2. 按来源分类展示：原始数据、分析结果、临时文件
3. 包含地区标签和文件大小信息
4. 如果用户指定了地区（如"重庆"），使用 region 参数过滤

当用户询问"与XX相关的数据"时：
1. 使用 search_user_data(region="XX") 精确检索
2. 如果无精确匹配，扩大到所属大区（如"重庆"→"西南"）
```

---

## 三、实施计划

### Phase 1: 数据库 + 注册增强（核心）

| 文件 | 改动 | 预计行数 |
|------|------|----------|
| `data_catalog.py` | 新增 source_type/region_tags 字段、match_regions()、extract_bbox() | ~80 行 |
| `app.py` | 上传后调用 register_asset() 注册到目录 | ~15 行 |
| `gis_processors.py` | auto_register_from_path() 增加 source_type="generated" | ~10 行 |
| DB migration 044 | ALTER TABLE 新增 2 个字段 | ~10 行 |

### Phase 2: 检索增强

| 文件 | 改动 | 预计行数 |
|------|------|----------|
| `toolsets/file_tools.py` | 改进 list_user_files() 分类展示 | ~40 行 |
| `toolsets/exploration_tools.py` | 新增 search_user_data() 工具函数 | ~60 行 |

### Phase 3: Agent 提示词

| 文件 | 改动 | 预计行数 |
|------|------|----------|
| `prompts/general_pipeline.yaml` | 添加数据检索引导指令 | ~10 行 |

---

## 四、预期效果

### 改进前

```
用户: 我有哪些与重庆相关的数据？
Agent: 您的文件列表：
  - 重庆耕地.shp (2.3MB)
  - buffer_a3f2.geojson (3.1MB)
  - ffi_result_b7c1.geojson (2.8MB)
  - 重庆耕地.dbf (1.2MB)
  - 重庆耕地.prj (0.1KB)
  - optimized_layout_c9d4.geojson (2.9MB)
  - heatmap_f2g6.html (1.2MB)
  - 四川林地.geojson (1.1MB)  ← 不相关但也列出了
  ...（杂乱无章）
```

### 改进后

```
用户: 我有哪些与重庆相关的数据？
Agent: 找到 5 个与重庆相关的数据集：

📥 原始数据 (1 个)
  1. 重庆耕地.shp (2.3MB) — 2026-03-25 上传，覆盖重庆市主城区

📊 分析结果 (3 个)
  2. buffer_重庆耕地_a3f2.geojson (3.1MB) — 缓冲区分析结果
  3. ffi_result_b7c1.geojson (2.8MB) — 碎片化指数计算结果 (FFI=0.42)
  4. optimized_layout_c9d4.geojson (2.9MB) — DRL空间布局优化结果

📈 可视化 (1 个)
  5. heatmap_f2g6.html (1.2MB) — 重庆耕地热力图

提示：这些数据来自 3 次分析流程，最近一次是 2026-03-28 的 DRL 优化。
```

---

## 五、风险与注意事项

1. **历史数据迁移**：已有文件没有 source_type 和 region_tags，需要一次性扫描补充
2. **bbox 提取性能**：大文件（>100MB）的 bbox 提取可能较慢，需异步处理
3. **地区匹配精度**：省级 bbox 是矩形近似，边界地区可能匹配到多个省份（可接受）
4. **向后兼容**：新增字段有默认值，不影响现有功能
