# Data Agent 工具清单

> 系统中所有 Tools 的完整清单：23 个 Toolset 包含 143+ 工具函数，覆盖空间处理、数据库、可视化、遥感、融合等全领域。

---

## 工具总数

| 类别 | 数量 |
|------|------|
| **Toolset（工具集）** | 23 个 BaseToolset 子类 |
| **内置工具函数** | 143+ 个（含 ArcPy 可选工具） |
| **用户自定义工具** | 无限（UserToolset 动态加载） |
| **MCP 外部工具** | 按 MCP Server 动态发现 |

---

## 全部 23 个 Toolset 及其工具

### 1. GeoProcessingToolset — 空间处理（18 核心 + 8 ArcPy = 26）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `generate_tessellation` | 生成规则网格（六边形/方形） |
| 2 | `raster_to_polygon` | 栅格转矢量 |
| 3 | `pairwise_clip` | 逐要素裁剪 |
| 4 | `tabulate_intersection` | 交叉表面积统计 |
| 5 | `surface_parameters` | DEM 坡度/坡向计算 |
| 6 | `zonal_statistics_as_table` | 分区统计 |
| 7 | `perform_clustering` | DBSCAN 空间聚类 |
| 8 | `create_buffer` | 缓冲区创建 |
| 9 | `summarize_within` | 区域内汇总统计 |
| 10 | `overlay_difference` | 叠加差集分析 |
| 11 | `generate_heatmap` | KDE 核密度热力图 |
| 12 | `find_within_distance` | 距离范围内搜索 |
| 13 | `polygon_neighbors` | 邻域多边形分析 |
| 14 | `add_field` | 添加字段 |
| 15 | `add_join` | 属性连接 |
| 16 | `calculate_field` | 字段计算（表达式） |
| 17 | `summary_statistics` | 汇总统计 |
| 18 | `filter_vector_data` | 矢量数据过滤 |
| | **ArcPy 可选工具（8）** | |
| 19 | `arcpy_buffer` | ArcPy 缓冲区 |
| 20 | `arcpy_clip` | ArcPy 裁剪 |
| 21 | `arcpy_dissolve` | ArcPy 融合 |
| 22 | `arcpy_project` | ArcPy 投影变换 |
| 23 | `arcpy_repair_geometry` | ArcPy 几何修复 |
| 24 | `arcpy_slope` | ArcPy 坡度分析 |
| 25 | `arcpy_zonal_statistics` | ArcPy 分区统计 |
| 26 | `arcpy_extract_watershed` | ArcPy 流域提取 |

### 2. VisualizationToolset — 可视化（11）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `visualize_interactive_map` | 交互式地图（Folium） |
| 2 | `generate_choropleth` | 分级设色地图 |
| 3 | `generate_bubble_map` | 比例气泡图 |
| 4 | `generate_heatmap` | 热力图 |
| 5 | `visualize_geodataframe` | GeoDataFrame 快速可视化 |
| 6 | `visualize_optimization_comparison` | DRL 优化前后对比图 |
| 7 | `export_map_png` | 地图导出 PNG |
| 8 | `compose_map` | 多图层合成地图 |
| 9 | `generate_3d_map` | 3D 地图（deck.gl 配置） |
| 10 | `control_map_layer` | 自然语言图层控制 |
| 11 | `f` *(内部)* | |

### 3. DataLakeToolset — 数据湖（10）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `list_data_assets` | 列出数据资产 |
| 2 | `describe_data_asset` | 资产详情 |
| 3 | `search_data_assets` | 搜索资产（中文 n-gram） |
| 4 | `register_data_asset` | 注册新资产 |
| 5 | `tag_data_asset` | 打标签 |
| 6 | `delete_data_asset` | 删除资产 |
| 7 | `share_data_asset` | 共享资产 |
| 8 | `get_data_lineage` | 数据血缘追踪 |
| 9 | `download_cloud_asset` | OBS 云资产下载 |

### 4. SemanticLayerToolset — 语义层（10）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `resolve_semantic_context` | 解析语义上下文 |
| 2 | `describe_table_semantic` | 表语义描述 |
| 3 | `register_semantic_annotation` | 注册语义标注 |
| 4 | `register_source_metadata` | 注册源元数据 |
| 5 | `list_semantic_sources` | 列出语义源 |
| 6 | `register_semantic_domain` | 注册语义域 |
| 7 | `discover_column_equivalences` | 发现列等价关系 |
| 8 | `export_semantic_model` | 导出语义模型 |
| 9 | `browse_hierarchy` | 浏览语义层级 |

### 5. KnowledgeBaseToolset — 知识库（10）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `create_knowledge_base` | 创建知识库 |
| 2 | `add_document_to_kb` | 添加文档 |
| 3 | `search_knowledge_base` | 语义搜索 |
| 4 | `get_kb_context` | 获取 KB 上下文（RAG） |
| 5 | `list_knowledge_bases` | 列出知识库 |
| 6 | `delete_knowledge_base` | 删除知识库 |
| 7 | `graph_rag_search_tool` | GraphRAG 图增强搜索 |
| 8 | `build_kb_graph_tool` | 构建实体图谱 |
| 9 | `get_kb_entity_graph_tool` | 获取实体关系图 |

### 6. LocationToolset — 位置服务（9）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `batch_geocode` | 批量地理编码 |
| 2 | `reverse_geocode` | 逆地理编码 |
| 3 | `calculate_driving_distance` | 驾车距离计算 |
| 4 | `search_nearby_poi` | 附近 POI 搜索 |
| 5 | `search_poi_by_keyword` | 关键词 POI 搜索 |
| 6 | `get_admin_boundary` | 行政区划边界 |
| 7 | `get_population_data` | 人口数据 |
| 8 | `aggregate_population` | 人口聚合统计 |

### 7. TeamToolset — 团队协作（9）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `create_team` | 创建团队 |
| 2 | `list_my_teams` | 我的团队 |
| 3 | `invite_to_team` | 邀请成员 |
| 4 | `remove_from_team` | 移除成员 |
| 5 | `list_team_members` | 成员列表 |
| 6 | `list_team_resources` | 团队资源 |
| 7 | `leave_team` | 退出团队 |
| 8 | `delete_team` | 删除团队 |

### 8. AdvancedAnalysisToolset — 高级分析（8）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `time_series_forecast` | 时间序列预测（ARIMA/ETS） |
| 2 | `spatial_trend_analysis` | 空间趋势分析 |
| 3 | `what_if_analysis` | 假设分析（What-If） |
| 4 | `scenario_compare` | 多场景对比 |
| 5 | `network_centrality` | 网络中心性 |
| 6 | `community_detection` | 社区检测 |
| 7 | `accessibility_analysis` | 可达性分析 |

### 9. RemoteSensingToolset — 遥感（8）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `describe_raster` | 栅格描述 |
| 2 | `calculate_ndvi` | NDVI 植被指数 |
| 3 | `raster_band_math` | 波段运算 |
| 4 | `classify_raster` | 栅格分类 |
| 5 | `visualize_raster` | 栅格可视化 |
| 6 | `download_lulc` | LULC 土地利用下载 |
| 7 | `download_dem` | DEM 高程下载（Copernicus 30m） |

### 10. ExplorationToolset — 数据探查（7）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `describe_geodataframe` | 数据画像（全面质量预检） |
| 2 | `reproject_spatial_data` | 重投影 |
| 3 | `engineer_spatial_features` | 空间特征工程 |
| 4 | `check_topology` | 拓扑检查 |
| 5 | `check_field_standards` | 字段标准检查 |
| 6 | `check_consistency` | 数据一致性检查 |

### 11. AdminToolset — 管理（6）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `get_usage_summary` | Token 用量摘要 |
| 2 | `query_audit_log` | 审计日志查询 |
| 3 | `list_templates` | 分析模板列表 |
| 4 | `delete_template` | 删除模板 |
| 5 | `share_template` | 共享模板 |

### 12. DatabaseToolset — 数据库（6）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `query_database` | SQL 查询（参数化） |
| 2 | `list_tables` | 表列表 |
| 3 | `describe_table` | 表结构描述 |
| 4 | `share_table` | 共享表 |
| 5 | `import_to_postgis` | 导入到 PostGIS |

### 13. SpatialAnalysisTier2Toolset — 高级空间分析（6）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `idw_interpolation` | IDW 反距离加权插值 |
| 2 | `kriging_interpolation` | Kriging 克里金插值 |
| 3 | `gwr_analysis` | 地理加权回归 (GWR) |
| 4 | `spatial_change_detection` | 多时相变化检测 |
| 5 | `viewshed_analysis` | DEM 可视域分析 |

### 14. StreamingToolset — 实时流（6）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `create_iot_stream` | 创建 IoT 数据流 |
| 2 | `list_active_streams` | 活跃流列表 |
| 3 | `stop_data_stream` | 停止数据流 |
| 4 | `get_stream_statistics` | 流统计 |
| 5 | `set_geofence_alert` | 地理围栏告警 |

### 15. FusionToolset — 数据融合（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `profile_fusion_sources` | 融合源画像 |
| 2 | `assess_fusion_compatibility` | 兼容性评估 |
| 3 | `fuse_datasets` | 执行融合 |
| 4 | `validate_fusion_quality` | 质量验证 |

### 16. MemoryToolset — 记忆（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `save_memory` | 保存记忆 |
| 2 | `recall_memories` | 检索记忆 |
| 3 | `list_memories` | 列出记忆 |
| 4 | `delete_memory` | 删除记忆 |

### 17. SpatialStatisticsToolset — 空间统计（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `spatial_autocorrelation` | 全局 Moran's I |
| 2 | `local_moran` | 局部 LISA |
| 3 | `hotspot_analysis` | Getis-Ord Gi* 热点分析 |

### 18. KnowledgeGraphToolset — 知识图谱（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `build_knowledge_graph` | 构建知识图谱 |
| 2 | `query_knowledge_graph` | 查询图谱 |
| 3 | `export_knowledge_graph` | 导出图谱 |

### 19. WatershedToolset — 流域（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `extract_watershed` | 流域提取 |
| 2 | `extract_stream_network` | 河网提取 |
| 3 | `compute_flow_accumulation` | 汇流累积计算 |

### 20. AnalysisToolset — 核心分析（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `ffi` | FFI 碎片化指数计算 |
| 2 | `drl_model` | DRL 深度强化学习优化（LongRunningFunctionTool） |
| 3 | `drl_multi_objective` | Pareto 多目标优化 |

### 21. FileToolset — 文件（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `list_user_files` | 用户文件列表 |
| 2 | `delete_user_file` | 删除文件 |

### 22. McpHubToolset — MCP 外部工具（动态）

从 MCP 服务器动态发现工具，数量取决于已连接的 MCP Server。

### 23. UserToolset — 用户自定义工具（动态）

从 PostgreSQL 加载用户定义的声明式工具模板，动态构建为 FunctionTool。

---

## 按领域统计

```
空间处理 (GeoProcessing)     ██████████████████████████ 26 (18%)
可视化 (Visualization)       ███████████ 11 (8%)
数据湖 (DataLake)            ██████████ 10 (7%)
语义层 (SemanticLayer)       ██████████ 10 (7%)
知识库 (KnowledgeBase)       ██████████ 10 (7%)
位置服务 (Location)          █████████ 9 (6%)
团队协作 (Team)              █████████ 9 (6%)
高级分析 (AdvancedAnalysis)  ████████ 8 (6%)
遥感 (RemoteSensing)         ████████ 8 (6%)
数据探查 (Exploration)       ███████ 7 (5%)
管理 (Admin)                 ██████ 6 (4%)
数据库 (Database)            ██████ 6 (4%)
空间分析Tier2 (SpatialT2)   ██████ 6 (4%)
实时流 (Streaming)           ██████ 6 (4%)
融合 (Fusion)                █████ 5 (3%)
记忆 (Memory)                █████ 5 (3%)
空间统计 (SpatialStats)      ████ 4 (3%)
知识图谱 (KnowledgeGraph)    ████ 4 (3%)
流域 (Watershed)             ████ 4 (3%)
核心分析 (Analysis)          ███ 3 (2%)
文件 (File)                  ███ 3 (2%)
MCP 外部                     ▪▪▪ 动态
用户自定义                    ▪▪▪ 动态
```

---

*本文档基于 GIS Data Agent v12.0 (ADK v1.27.2) 的 23 个 Toolset 源码编写。*
