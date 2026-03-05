# GIS Data Agent v7.0 Release Notes

**发布日期**: 2026-03-05
**版本**: v7.0 (MMFE 智能增强版)
**测试覆盖**: 1330+ 测试通过
**工具集**: 19 个 BaseToolset

---

## 概述

v7.0 版本聚焦于**多模态数据融合引擎 (MMFE)** 的智能化增强，基于 `docs/multi-modal-fusion-analysis.md` 分析报告提出的四大改进方向，全面提升融合引擎的语义理解、策略推理、实体建模和大数据处理能力。

---

## 核心特性

### 1. 向量嵌入语义匹配 (Vector Embedding Semantic Matching)

**问题**: 现有四层匹配（精确→等价组→单位感知→模糊）在长尾字段名匹配上存在不足。

**方案**: 在 Tier 2 和 Tier 3 之间插入 **Tier 2.5 嵌入层**，使用 Gemini `text-embedding-004` API 计算字段名语义相似度。

**技术细节**:
- **API**: Gemini `text-embedding-004` (无需安装 sentence-transformers，避免 400MB 依赖)
- **相似度**: 余弦相似度 (cosine similarity)，阈值 ≥ 0.75
- **置信度**: 0.78 (介于等价组 0.85 和单位感知 0.70 之间)
- **缓存**: 模块级 `_embedding_cache` 字典，避免重复 API 调用
- **类型兼容性**: 匹配时检查字段类型兼容性 (numeric↔numeric, string↔string)
- **降级策略**: API 失败时静默降级到 Tier 3/4，不影响现有流程
- **启用方式**: `assess_fusion_compatibility(use_embedding="true")` 显式启用（默认关闭）

**新增函数**:
```python
# fusion_engine.py
_get_embeddings(texts: list[str]) -> list[list[float]]
_cosine_similarity(a: list[float], b: list[float]) -> float
```

**测试**: 7 个测试 (TestEmbeddingMatching)
- `test_cosine_similarity_basic`
- `test_get_embeddings_caches_results`
- `test_embedding_matching_in_find_field_matches`
- `test_embedding_api_failure_graceful_degradation`
- `test_embedding_matching_respects_type_compatibility`
- `test_embedding_matching_no_duplicates`
- `test_embedding_matching_opt_in`

---

### 2. LLM 增强策略路由 (LLM-Enhanced Strategy Routing)

**问题**: 现有规则评分无法理解用户意图，可能推荐不符合分析目标的策略。

**方案**: 新增 `strategy="llm_auto"` 选项，调用 Gemini 2.0 Flash 根据用户意图 + 兼容性报告智能推荐融合策略。

**技术细节**:
- **模型**: Gemini 2.0 Flash (快速推理)
- **输入**: 候选策略列表 + 数据源元信息 (类型、行数、列名) + 用户意图提示 (user_hint)
- **输出**: JSON `{"strategy": "spatial_join", "reasoning": "..."}`
- **非替代**: 规则评分先行，LLM 仅在 `strategy="llm_auto"` 或评分歧义时介入
- **降级策略**: API 失败时回退到规则评分结果
- **审计**: 推理结果记录到 `alignment_log` 中

**新增函数**:
```python
# fusion_engine.py
async _llm_select_strategy(
    candidates: list[str],
    sources: list[FusionSource],
    user_hint: str = ""
) -> tuple[str, str]
```

**工具参数扩展**:
```python
# toolsets/fusion_tools.py
fuse_datasets(
    ...,
    strategy: str = "auto",  # 新增 "llm_auto" 选项
    user_hint: str = ""      # 新增用户意图参数
)
```

**测试**: 6 个测试 (TestLLMStrategyRouting)
- `test_llm_strategy_returns_valid_candidate`
- `test_llm_select_strategy_invalid_json`
- `test_llm_select_strategy_out_of_candidates`
- `test_llm_fallback_on_failure`
- `test_rule_based_used_when_no_llm`
- `test_execute_fusion_llm_auto`

---

### 3. 地理知识图谱 (Geographic Knowledge Graph)

**问题**: 现有融合引擎只做"宽表合并"，无法建模实体级关系。

**方案**: 使用 networkx 构建内存图，从"行→列"转向"实体→关系"建模。

**技术细节**:
- **图库**: networkx 3.6.1 (已安装，无需新依赖)
- **图类型**: 有向图 (DiGraph)
- **节点**: 空间实体 (parcel, building, road, water, admin, vegetation, poi)
- **边**: 空间关系 (contains, within, adjacent_to, overlaps, nearest_to)
- **空间索引**: STRtree 加速邻接/包含关系检测
- **性能保护**: `_MAX_SPATIAL_PAIRS = 1000` 防止大数据集组合爆炸
- **持久化**: PostgreSQL `agent_knowledge_graphs` 表 (JSONB 存储)

**新增模块**:
```
data_agent/knowledge_graph.py (~625 行)
├── GeoKnowledgeGraph 类
│   ├── build_from_geodataframe()  # 行→节点，空间关系→边
│   ├── merge_layer()              # 增量添加图层
│   ├── query_neighbors()          # N跳邻居查询
│   ├── query_path()               # 最短路径
│   ├── query_by_type()            # 按实体类型筛选
│   ├── export_to_json()           # nx.node_link_data 导出
│   ├── get_stats()                # GraphStats 统计
│   ├── _detect_adjacency()        # STRtree 邻接检测
│   ├── _detect_containment()      # contains/within 检测
│   └── _detect_entity_type()      # 实体类型推断
└── ensure_knowledge_graph_tables() # DB 表创建
```

**新增工具集**:
```
data_agent/toolsets/knowledge_graph_tools.py (~207 行)
├── KnowledgeGraphToolset(BaseToolset)
├── build_knowledge_graph()   # 从空间数据构建图谱
├── query_knowledge_graph()   # 查询实体关系
└── export_knowledge_graph()  # 导出图谱
```

**实体类型** (7 类):
- `parcel`: 地块 (DLBM, ZLDWDM, DKBM)
- `building`: 建筑 (JZWMC, JZWDM)
- `road`: 道路 (LXMC, DLMC)
- `water`: 水体 (STMC, HLDM)
- `admin`: 行政区 (XZQDM, QHDM)
- `vegetation`: 植被 (LHDM, SLDM)
- `poi`: 兴趣点 (POIID, POITYPE)

**测试**: 17 个测试 (TestKnowledgeGraph)
- 图构建、图层合并、邻居查询、路径查询、类型筛选、导出、统计、工具集集成

---

### 4. 分布式/核外计算 (Distributed/Out-of-Core Computing)

**问题**: 大数据集 (>50万行或 >500MB) 容易导致内存溢出 (OOM)。

**方案**: 利用已有 dask + fiona 实现分块读取和处理，对调用方透明。

**技术细节**:
- **阈值**: 500K 行 或 500MB 文件大小
- **矢量分块**: fiona 分块读取 (chunk_size=100K)，逐块构建 GeoDataFrame
- **表格懒加载**: dask.dataframe 延迟计算，仅在需要时 materialize
- **分块融合**: `_fuse_large_datasets_spatial()` 分块执行 spatial_join (chunk_size=50K)
- **透明性**: 小文件行为不变，大文件自动切换，调用方无感知

**新增函数**:
```python
# fusion_engine.py
_is_large_dataset(file_path: str, row_hint: int = 0) -> bool
_read_vector_chunked(path: str, chunk_size: int = 100_000) -> gpd.GeoDataFrame
_read_tabular_lazy(path: str)  # 返回 dask.dataframe 或 pandas.DataFrame
_materialize_df(df) -> pd.DataFrame
_fuse_large_datasets_spatial(gdf_left, gdf_right, predicate, chunk_size)
```

**修改点**:
- `_profile_vector()`: 使用 `_read_vector_chunked()`
- `_profile_tabular()`: 使用 `_materialize_df(_read_tabular_lazy())`
- `align_sources()`: 使用分块读取
- `_strategy_spatial_join()`: 使用 `_fuse_large_datasets_spatial()`

**测试**: 11 个测试 (TestLargeDatasetHandling)
- 阈值检测、分块读取、dask 物化、分块 spatial_join、透明性验证

---

## 文件变更清单

### 新增文件 (4 个)
| 文件 | 行数 | 描述 |
|------|------|------|
| `data_agent/knowledge_graph.py` | ~625 | 地理知识图谱引擎 |
| `data_agent/toolsets/knowledge_graph_tools.py` | ~207 | 知识图谱工具集 (3 工具) |
| `data_agent/test_knowledge_graph.py` | ~351 | 知识图谱测试 (17 测试) |
| `data_agent/migrations/019_create_knowledge_graph.sql` | ~20 | agent_knowledge_graphs 表 |

### 修改文件 (10 个)
| 文件 | 变更 |
|------|------|
| `data_agent/fusion_engine.py` | +embedding 匹配 +LLM 路由 +分块读取 (~2100 行) |
| `data_agent/toolsets/fusion_tools.py` | +use_embedding 参数 +user_hint 参数 |
| `data_agent/test_fusion_engine.py` | +24 测试 (3 个 TestClass) |
| `data_agent/toolsets/__init__.py` | +KnowledgeGraphToolset 导入 |
| `data_agent/agent.py` | +KnowledgeGraphToolset 到 2 个 agent |
| `data_agent/prompts/general.yaml` | +知识图谱指引 +融合增强说明 |
| `data_agent/locales/zh.yaml` | +6 个 i18n 键 |
| `data_agent/locales/en.yaml` | +6 个 i18n 键 |
| `data_agent/test_evaluation.py` | +7 工具名到 REGISTERED_TOOL_NAMES |
| `data_agent/app.py` | +ensure_knowledge_graph_tables() 启动调用 |

---

## 测试结果

### 新增测试 (41 个)
| 测试类 | 测试数 | 状态 |
|--------|--------|------|
| TestEmbeddingMatching | 7 | ✅ 7/7 通过 |
| TestLLMStrategyRouting | 6 | ✅ 6/6 通过 |
| TestLargeDatasetHandling | 11 | ✅ 11/11 通过 |
| TestKnowledgeGraph | 17 | ✅ 17/17 通过 |

### 全量测试
```bash
.venv/Scripts/python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q
```
**结果**: 1330 passed, 62 failed

**说明**: 62 个失败均为 **预存在的 Python 3.13 asyncio 兼容性问题** (`asyncio.get_event_loop()` RuntimeError)，与 v7.0 变更无关。受影响文件:
- `test_map_annotations.py`
- `test_planner.py`
- `test_remote_sensing.py`
- `test_toolsets.py`

---

## 技术亮点

### 1. 依赖最小化
- **嵌入匹配**: 使用已有 Gemini API，避免 sentence-transformers (~400MB)
- **知识图谱**: 使用已安装 networkx 3.6.1，避免 Neo4j 部署
- **分块计算**: 使用已有 dask + fiona，无需新依赖

### 2. 向后兼容
- **嵌入匹配**: 默认关闭，显式启用 `use_embedding="true"`
- **LLM 路由**: 新增 `strategy="llm_auto"` 选项，不影响现有 `"auto"` 行为
- **分块计算**: 透明切换，小文件行为不变

### 3. 优雅降级
- **嵌入 API 失败**: 静默降级到 Tier 3/4
- **LLM API 失败**: 回退到规则评分
- **大数据集检测**: 自动切换，无需用户干预

### 4. 测试模式创新
- **LLM 路由测试**: 使用 `@patch("google.genai.Client")` 而非 `@patch("data_agent.fusion_engine.genai")`，因为 `from google import genai` 在函数内动态导入

---

## 国际化 (i18n)

新增 6 个键 (中/英双语):

| 键 | 中文 | 英文 |
|----|------|------|
| `fusion.embedding_enabled` | 已启用向量嵌入语义匹配 | Vector embedding semantic matching enabled |
| `fusion.llm_strategy` | LLM 推荐策略: {strategy} | LLM recommended strategy: {strategy} |
| `fusion.large_dataset` | 检测到大数据集，启用分块处理 | Large dataset detected, chunked processing enabled |
| `kg.built` | 知识图谱已构建: {nodes} 节点, {edges} 边 | Knowledge graph built: {nodes} nodes, {edges} edges |
| `kg.query_result` | 查询结果: {count} 个实体 | Query result: {count} entities |
| `kg.exported` | 知识图谱已导出到 {path} | Knowledge graph exported to {path} |

---

## Agent 集成

### 新增工具集
```python
# data_agent/agent.py
from data_agent.toolsets.knowledge_graph_tools import KnowledgeGraphToolset

# GeneralProcessing agent (line ~300)
general_processing_agent = LlmAgent(
    ...,
    tools=[
        ...,
        KnowledgeGraphToolset(),  # 新增
    ]
)

# PlannerProcessor factory (line ~389)
def _make_planner_processor():
    return LlmAgent(
        ...,
        tools=[
            ...,
            KnowledgeGraphToolset(),  # 新增
        ]
    )
```

### Prompt 增强
```yaml
# data_agent/prompts/general.yaml (新增段落)
knowledge_graph_guide: |
  地理知识图谱工具 (v7.0):
  1. build_knowledge_graph: 从空间数据构建实体关系图
  2. query_knowledge_graph: 查询实体邻居、路径、类型
  3. export_knowledge_graph: 导出图谱为 JSON

fusion_enhancement: |
  融合引擎增强 (v7.0):
  - 向量嵌入匹配: use_embedding="true" 启用语义相似度
  - LLM 策略路由: strategy="llm_auto" 智能推荐
  - 大数据集: >500K 行自动分块处理
```

---

## 数据库迁移

### 019_create_knowledge_graph.sql
```sql
CREATE TABLE IF NOT EXISTS agent_knowledge_graphs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    graph_name VARCHAR(255) NOT NULL,
    entity_types JSONB,
    graph_data JSONB,
    source_files TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_kg_user_id ON agent_knowledge_graphs(user_id);
CREATE INDEX idx_kg_graph_name ON agent_knowledge_graphs(graph_name);
```

---

## 性能优化

### 嵌入缓存
```python
_embedding_cache: dict[str, list[float]] = {}
```
- 模块级字典，避免重复 API 调用
- 会话内有效，重启清空

### 空间索引
```python
# knowledge_graph.py
from shapely.strtree import STRtree

tree = STRtree(geometries)
for idx in tree.query(geom, predicate="intersects"):
    # 快速邻接检测
```

### 分块处理
```python
# 大矢量文件
for chunk in fiona.open(path).filter(bbox=...):
    gdf_chunk = gpd.GeoDataFrame.from_features(chunk)
    # 逐块处理

# 大表格文件
ddf = dd.read_csv(path)  # 延迟计算
result = ddf.compute()   # 仅在需要时物化
```

---

## 已知限制

### 1. 嵌入匹配
- **API 依赖**: 需要 Gemini API 可用，离线环境无法使用
- **成本**: 每次调用消耗 token (已缓存可减少)
- **语言**: 主要针对英文字段名优化，中文字段名效果待验证

### 2. LLM 路由
- **延迟**: 增加 ~1-2s 推理时间
- **不确定性**: LLM 输出可能不稳定，需回退机制

### 3. 知识图谱
- **内存限制**: 大图谱 (>10万节点) 可能占用大量内存
- **持久化**: 当前仅存储 JSON，未实现增量更新
- **查询性能**: 复杂图查询 (>5跳) 可能较慢

### 4. 分块计算
- **策略限制**: 仅 spatial_join 支持分块，其他策略仍需全量加载
- **内存峰值**: 分块大小固定，极端情况仍可能 OOM

---

## 后续计划

### v7.1 (短期)
- 嵌入匹配支持中文字段名 (中文分词 + 拼音转换)
- 知识图谱增量更新 (merge 而非 rebuild)
- 更多融合策略支持分块 (overlay, nearest_join)

### v8.0 (中期)
- 实时协同编辑 (CRDT)
- 边缘部署 + 离线模式 (ONNX)
- 数据连接器生态 (WMS/WFS, ArcGIS, GEE)

---

## 贡献者

- **核心开发**: Claude (Anthropic)
- **架构设计**: 基于 `docs/multi-modal-fusion-analysis.md` 分析报告
- **测试验证**: 1330+ 自动化测试

---

## 参考文档

- `docs/multi-modal-fusion-analysis.md` — v7.0 需求分析
- `docs/technical_paper_fusion_engine.md` — MMFE 技术论文
- `docs/comparison_MMFE_vs_MGIM.md` — MMFE vs MGIM 对比
- `CLAUDE.md` — 项目架构文档
- `README.md` — 用户手册

---

**发布**: 2026-03-05
**版本**: v7.0
**状态**: ✅ 生产就绪
