# Data Agent 工具清单

> 系统中所有 Tools 的完整清单：39 个 Toolset 包含 260+ 工具函数，覆盖空间处理、治理质检、因果推断、世界模型、语义算子等全领域。

---

## 工具总数

| 类别 | 数量 |
|------|------|
| **Toolset（工具集）** | 39 个 BaseToolset 子类 |
| **内置工具函数** | 260+（含 ArcPy 可选工具） |
| **用户自定义工具** | 无限（UserToolset 动态加载） |
| **MCP 外部工具** | 按 MCP Server 动态发现 |

---

## 全部 39 个 Toolset 及其工具

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

### 2. GovernanceToolset — 数据治理（18）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `check_gaps` | 检测多边形要素间空隙 |
| 2 | `check_completeness` | 检查属性字段和几何完整率 |
| 3 | `check_attribute_range` | 验证数值字段值域范围 |
| 4 | `check_duplicates` | 检测重复几何和属性组合 |
| 5 | `check_crs_consistency` | 验证坐标系一致性 |
| 6 | `governance_score` | 计算加权治理评分（6 维度 0-100） |
| 7 | `governance_summary` | 生成综合审计报告（问题+建议） |
| 8 | `list_data_standards` | 列出已注册数据标准（GB/T 21010, DLTB 等） |
| 9 | `validate_against_standard` | 对标数据标准验证 |
| 10 | `validate_field_formulas` | 检查字段计算公式正确性 |
| 11 | `generate_gap_matrix` | 生成字段级标准符合矩阵 |
| 12 | `generate_governance_plan` | 生成数据治理改进计划 |
| 13 | `check_logic_consistency` | 验证数据逻辑一致性规则 |
| 14 | `check_temporal_validity` | 验证日期/时间字段范围 |
| 15 | `check_naming_convention` | 检查字段/文件命名规范 |
| 16 | `classify_defects` | 按类型和严重度分类缺陷（A/B/C） |
| 17 | `classify_data_sensitivity` | 数据敏感性分级（PII/机密） |
| 18 | `recommend_data_model` | 推荐数据模型 |

### 3. RemoteSensingToolset — 遥感（13）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `describe_raster` | 栅格元数据描述 |
| 2 | `calculate_ndvi` | NDVI 植被指数计算 |
| 3 | `raster_band_math` | 波段运算 |
| 4 | `classify_raster` | 栅格分类 |
| 5 | `visualize_raster` | 栅格可视化 |
| 6 | `download_lulc` | LULC 土地利用下载（ESA/ESRI 10m） |
| 7 | `download_dem` | DEM 高程下载（Copernicus 30m） |
| 8 | `calculate_spectral_index` | 计算光谱指数（15+ 种：NDVI/EVI/NDWI/NDBI/NBR…） |
| 9 | `list_spectral_indices` | 列出可用光谱指数 |
| 10 | `recommend_indices` | 按任务推荐光谱指数 |
| 11 | `assess_cloud_cover` | 云覆盖评估 |
| 12 | `search_rs_experience` | 遥感经验池检索 |
| 13 | `list_satellite_presets` | 列出卫星数据源预设（Sentinel-2/Landsat/SAR/DEM/LULC） |

### 4. VisualizationToolset — 可视化（11）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `load_admin_boundary` | 加载行政区划底图 |
| 2 | `visualize_optimization_comparison` | DRL 优化前后对比图 |
| 3 | `visualize_interactive_map` | 多图层交互式地图（Folium） |
| 4 | `generate_choropleth` | 分级设色专题图 |
| 5 | `generate_bubble_map` | 比例气泡图 |
| 6 | `visualize_geodataframe` | GeoDataFrame 快速可视化 |
| 7 | `export_map_png` | 地图导出 PNG |
| 8 | `compose_map` | 多图层合成地图 |
| 9 | `generate_3d_map` | 3D 地图（deck.gl 配置） |
| 10 | `control_map_layer` | 自然语言图层控制（增/删/改） |
| 11 | `generate_heatmap` | 热力图 |

### 5. DataCleaningToolset — 数据清洗（11）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `fill_null_values` | 空值填充（mean/median/mode/ffill） |
| 2 | `map_field_codes` | 字段值重映射 |
| 3 | `rename_fields` | 批量重命名字段 |
| 4 | `cast_field_type` | 字段类型转换（string/int/float/date） |
| 5 | `clip_outliers` | 异常值截断/移除 |
| 6 | `standardize_crs` | 统一坐标系 |
| 7 | `add_missing_fields` | 按标准补齐缺失字段 |
| 8 | `mask_sensitive_fields_tool` | PII 敏感字段脱敏 |
| 9 | `auto_fix_defects` | 自动修复检测到的数据缺陷 |
| 10 | `auto_classify_archive` | 按类型和精度自动分类归档 |
| 11 | `batch_standardize_crs` | 批量 CRS 标准化 |

### 6. DataLakeToolset — 数据湖（9）

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

### 7. SemanticLayerToolset — 语义层（9）

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

### 8. KnowledgeBaseToolset — 知识库（9）

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

### 9. ExplorationToolset — 数据探查（9）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `describe_geodataframe` | 数据画像（全面质量预检） |
| 2 | `reproject_spatial_data` | 重投影 |
| 3 | `engineer_spatial_features` | 空间特征工程 |
| 4 | `check_topology` | 拓扑检查 |
| 5 | `check_field_standards` | 字段标准检查 |
| 6 | `check_consistency` | 数据一致性检查 |
| 7 | `list_fgdb_layers` | 列出 FileGDB 图层 |
| 8 | `batch_profile_datasets` | 批量画像目录下所有数据 |
| 9 | `list_dxf_layers` | 列出 DXF 图层 |

### 10. ChartToolset — 统计图表（9）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `create_bar_chart` | ECharts 柱状/分组柱状图 |
| 2 | `create_line_chart` | 折线图 + 趋势分析 |
| 3 | `create_pie_chart` | 饼图/环形图 |
| 4 | `create_scatter_chart` | 散点图（颜色/大小编码） |
| 5 | `create_histogram` | 频率分布直方图 |
| 6 | `create_box_plot` | 箱线图 + 异常值分析 |
| 7 | `create_heatmap_chart` | 相关系数矩阵热力图 |
| 8 | `create_treemap` | 树状图（层次数据） |
| 9 | `create_radar_chart` | 雷达图（多维对比） |

### 11. LocationToolset — 位置服务（8）

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

### 12. TeamToolset — 团队协作（8）

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

### 13. ToolEvolutionToolset — 工具演化（8）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `get_tool_metadata` | 获取工具元数据（描述/成本/可靠性/场景） |
| 2 | `list_tools` | 列出全部工具（过滤+排序） |
| 3 | `suggest_tools_for_task` | 按任务描述推荐工具 |
| 4 | `analyze_tool_failures` | 分析工具失败模式 |
| 5 | `register_tool` | 运行时注册动态工具 |
| 6 | `deactivate_tool` | 停用不可靠工具 |
| 7 | `get_failure_suggestions` | 失败后推荐替代工具 |
| 8 | `tool_evolution_report` | 工具生态健康报告 |

### 14. AdvancedAnalysisToolset — 高级分析（7）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `time_series_forecast` | 时间序列预测（ARIMA/ETS） |
| 2 | `spatial_trend_analysis` | 空间趋势分析 |
| 3 | `what_if_analysis` | 假设分析（What-If） |
| 4 | `scenario_compare` | 多场景对比 |
| 5 | `network_centrality` | 网络中心性 |
| 6 | `community_detection` | 社区检测 |
| 7 | `accessibility_analysis` | 可达性分析 |

### 15. VirtualSourceToolset — 虚拟数据源（7）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `list_virtual_sources_tool` | 列出已注册虚拟源（WFS/STAC/OGC/WMS） |
| 2 | `query_virtual_source_tool` | 查询虚拟源（bbox + CQL 过滤） |
| 3 | `preview_virtual_source_tool` | 快速预览虚拟源数据 |
| 4 | `register_virtual_source_tool` | 注册新虚拟源 |
| 5 | `check_virtual_source_health_tool` | 连接健康检查 |
| 6 | `discover_layers_tool` | 发现可用图层/集合 |
| 7 | `add_wms_layer_tool` | 添加 WMS 图层到地图 |

### 16. CausalInferenceToolset — 统计因果推断（6）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `propensity_score_matching` | 倾向得分匹配（PSM）因果效应估计 |
| 2 | `exposure_response_function` | 暴露-响应函数 |
| 3 | `difference_in_differences` | 双重差分因果分析（DiD） |
| 4 | `spatial_granger_causality` | 空间 Granger 因果检验 |
| 5 | `geographic_causal_mapping` | 地理趋同交叉映射（GCCM） |
| 6 | `causal_forest_analysis` | 因果森林（异质处理效应） |

### 17. DatabaseToolset — 数据库（6）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `query_database` | SQL 查询（参数化，RLS） |
| 2 | `list_tables` | 表列表 |
| 3 | `describe_table` | 表结构描述 |
| 4 | `share_table` | 共享表 |
| 5 | `import_to_postgis` | 导入到 PostGIS |
| 6 | `register_table_ownership` | 注册表所有权 |

### 18. StreamingToolset — 实时流（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `create_iot_stream` | 创建 IoT 数据流 |
| 2 | `list_active_streams` | 活跃流列表 |
| 3 | `stop_data_stream` | 停止数据流 |
| 4 | `get_stream_statistics` | 流统计 |
| 5 | `set_geofence_alert` | 地理围栏告警 |

### 19. SpatialAnalysisTier2Toolset — 高级空间分析（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `idw_interpolation` | IDW 反距离加权插值 |
| 2 | `kriging_interpolation` | Kriging 克里金插值 |
| 3 | `gwr_analysis` | 地理加权回归 (GWR) |
| 4 | `spatial_change_detection` | 多时相变化检测 |
| 5 | `viewshed_analysis` | DEM 可视域分析 |

### 20. AnalysisToolset — 核心分析（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `ffi` | FFI 碎片化指数计算 |
| 2 | `drl_model` | DRL 深度强化学习优化（LongRunningFunctionTool） |
| 3 | `drl_multi_objective` | NSGA-II Pareto 多目标优化 |
| 4 | `train_drl_model` | 训练自定义 DRL 模型 |
| 5 | `list_drl_scenarios` | 列出 DRL 场景模板 |

### 21. WorldModelToolset — 世界模型（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `world_model_predict` | AlphaEarth + LatentDynamicsNet LULC 预测 |
| 2 | `world_model_scenarios` | 列出预测情景（城市蔓延/生态修复/…） |
| 3 | `world_model_status` | 模型权重和 GEE 可用性检查 |
| 4 | `world_model_embedding_coverage` | 查询 AlphaEarth 嵌入缓存覆盖 |
| 5 | `world_model_find_similar` | 向量相似度搜索相似土地利用模式 |

### 22. PrecisionToolset — 套合精度（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `compare_coordinates` | 实测与参考坐标精度对比 |
| 2 | `check_topology_integrity` | 综合拓扑完整性检查 + 评分 |
| 3 | `check_edge_matching` | 相邻图幅接边检查 |
| 4 | `precision_score` | 多维精度综合评分（0-100） |
| 5 | `overlay_precision_check` | 套合精度检查 |

### 23. OperatorToolset — 语义算子（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `clean_data` | 语义清洗算子（自动策略选择：CRS/空值/PII/拓扑） |
| 2 | `integrate_data` | 多源融合语义算子（10 种策略自动路由） |
| 3 | `analyze_data` | 空间分析语义算子（自动选方法） |
| 4 | `visualize_data` | 可视化语义算子（自动选图表类型） |
| 5 | `list_operators` | 列出全部可用语义算子 |

### 24. AdminToolset — 管理（5）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `get_usage_summary` | Token 用量摘要 |
| 2 | `query_audit_log` | 审计日志查询 |
| 3 | `list_templates` | 分析模板列表 |
| 4 | `delete_template` | 删除模板 |
| 5 | `share_template` | 共享模板 |

### 25. FusionToolset — 数据融合（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `profile_fusion_sources` | 融合源画像 |
| 2 | `assess_fusion_compatibility` | 兼容性评估 |
| 3 | `fuse_datasets` | 执行融合（10 种策略） |
| 4 | `validate_fusion_quality` | 质量验证 |

### 26. MemoryToolset — 记忆（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `save_memory` | 保存记忆 |
| 2 | `recall_memories` | 检索记忆 |
| 3 | `list_memories` | 列出记忆 |
| 4 | `delete_memory` | 删除记忆 |

### 27. LLMCausalToolset — LLM 因果推理（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `construct_causal_dag` | 从叙述描述构建因果 DAG |
| 2 | `counterfactual_reasoning` | 反事实推理生成 |
| 3 | `explain_causal_mechanism` | 自然语言因果机制解释 |
| 4 | `generate_what_if_scenarios` | What-If 情景生成 |

### 28. CausalWorldModelToolset — 世界模型因果（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `intervention_predict` | 干预效应预测（含溢出效应） |
| 2 | `counterfactual_comparison` | 平行情景对比生成因果效应图 |
| 3 | `embedding_treatment_effect` | 嵌入空间处理效应提取 |
| 4 | `integrate_statistical_prior` | 统计先验整合到世界模型 |

### 29. StorageToolset — 云存储（4）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `list_lake_assets` | 列出数据湖文件（S3/OBS） |
| 2 | `upload_to_lake` | 上传本地文件到云存储 |
| 3 | `download_from_lake` | 下载云文件到本地 |
| 4 | `get_storage_info` | 存储系统状态和配置 |

### 30. SpatialStatisticsToolset — 空间统计（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `spatial_autocorrelation` | 全局 Moran's I |
| 2 | `local_moran` | 局部 LISA |
| 3 | `hotspot_analysis` | Getis-Ord Gi* 热点分析 |

### 31. KnowledgeGraphToolset — 知识图谱（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `build_knowledge_graph` | 构建知识图谱 |
| 2 | `query_knowledge_graph` | 查询图谱 |
| 3 | `export_knowledge_graph` | 导出图谱 |

### 32. WatershedToolset — 流域（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `extract_watershed` | 流域提取 |
| 2 | `extract_stream_network` | 河网提取 |
| 3 | `compute_flow_accumulation` | 汇流累积计算 |

### 33. NL2SQLToolset — 自然语言查询（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `discover_database_schema` | 发现数据库表结构和列元数据 |
| 2 | `execute_safe_sql` | 执行只读 SQL（安全护栏） |
| 3 | `execute_spatial_query` | 执行参数化空间查询（返回 GeoJSON） |

### 34. ReportToolset — 报告（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `list_report_templates` | 列出报告模板 |
| 2 | `generate_quality_report` | 生成结构化质检报告 |
| 3 | `export_analysis_report` | 导出格式化分析报告 |

### 35. SparkToolset — 分布式计算（3）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `spark_submit_task` | 提交分布式计算任务（L1/L2/L3 自动分层） |
| 2 | `spark_check_tier` | 根据文件大小判断执行层级 |
| 3 | `spark_list_jobs` | 列出近期分布式计算任务 |

### 36. DreamerToolset — Dreamer 世界模型 DRL（2）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `dreamer_optimize` | Dreamer 风格 DRL + 世界模型前瞻辅助奖励 |
| 2 | `dreamer_status` | Dreamer 集成状态和组件健康检查 |

### 37. FileToolset — 文件（2）

| # | 工具名 | 功能 |
|---|--------|------|
| 1 | `list_user_files` | 用户文件列表（本地+云） |
| 2 | `delete_user_file` | 删除文件 |

### 38. McpHubToolset — MCP 外部工具（动态）

从已连接的 MCP 服务器动态发现工具，通过 `McpToolset` 聚合。工具数量取决于已启用的 MCP Server，按 `pipeline` 参数隔离分配。

内置 4 个子系统 MCP 服务器：

| 服务器 | 传输 | 提供的能力 |
|--------|------|-----------|
| cv-service | stdio | YOLO 图斑缺陷检测 |
| cad-parser | stdio | DWG/DXF CAD 解析 |
| tool-mcp-servers | stdio | ArcGIS/QGIS/Blender 专业工具 |
| reference-data | REST | GB/T 24356 标准参考数据 |

### 39. UserToolset — 用户自定义工具（动态）

从 PostgreSQL 加载用户定义的声明式工具模板，动态构建为 `FunctionTool`。支持 5 种模板类型：

| 模板类型 | 用途 | 执行引擎 |
|---------|------|---------|
| `http_call` | 调用外部 REST API | HttpCallEngine |
| `sql_query` | 参数化数据库查询（只读） | SQLQueryEngine |
| `file_transform` | 文件处理管道 | FileTransformEngine |
| `chain` | 串联多个自定义工具（最多 5 步） | ChainEngine |
| `python_sandbox` | Python 沙箱执行（Phase 2） | SandboxEngine |

每用户最多 50 个工具，每工具最多 20 个参数，支持评分/克隆/版本管理。

---

## 按领域统计

```
空间处理 (GeoProcessing)       ██████████████████████████ 26 (10%)
治理 (Governance)              ██████████████████ 18 (7%)
遥感 (RemoteSensing)           █████████████ 13 (5%)
清洗 (DataCleaning)            ███████████ 11 (4%)
可视化 (Visualization)         ███████████ 11 (4%)
图表 (Chart)                   █████████ 9 (3%)
数据湖 (DataLake)              █████████ 9 (3%)
语义层 (SemanticLayer)         █████████ 9 (3%)
知识库 (KnowledgeBase)         █████████ 9 (3%)
探查 (Exploration)             █████████ 9 (3%)
位置服务 (Location)            ████████ 8 (3%)
协作 (Team)                    ████████ 8 (3%)
工具演化 (ToolEvolution)       ████████ 8 (3%)
高级分析 (AdvancedAnalysis)    ███████ 7 (3%)
虚拟源 (VirtualSource)         ███████ 7 (3%)
因果推断 (CausalInference)     ██████ 6 (2%)
数据库 (Database)              ██████ 6 (2%)
空间分析T2 (SpatialT2)        █████ 5 (2%)
流式 (Streaming)               █████ 5 (2%)
分析 (Analysis)                █████ 5 (2%)
世界模型 (WorldModel)          █████ 5 (2%)
精度 (Precision)               █████ 5 (2%)
语义算子 (Operator)            █████ 5 (2%)
管理 (Admin)                   █████ 5 (2%)
融合 (Fusion)                  ████ 4 (2%)
记忆 (Memory)                  ████ 4 (2%)
LLM因果 (LLMCausal)           ████ 4 (2%)
世界因果 (CausalWorldModel)    ████ 4 (2%)
云存储 (Storage)               ████ 4 (2%)
空间统计 (SpatialStats)        ███ 3 (1%)
知识图谱 (KnowledgeGraph)      ███ 3 (1%)
流域 (Watershed)               ███ 3 (1%)
NL2SQL                         ███ 3 (1%)
报告 (Report)                  ███ 3 (1%)
Spark                          ███ 3 (1%)
Dreamer                        ██ 2 (1%)
文件 (File)                    ██ 2 (1%)
MCP 外部                       ▪▪▪ 动态
用户自定义                      ▪▪▪ 动态
```

---

## 新增 Toolset 变更摘要（v12.0 → v16.0）

| 版本 | 新增 Toolset | 工具数 |
|------|-------------|--------|
| v14.0 | ChartToolset, VirtualSourceToolset | 16 |
| v14.5 | GovernanceToolset, DataCleaningToolset | 29 |
| v15.0 | SparkToolset, StorageToolset, WorldModelToolset | 12 |
| v15.5 | DreamerToolset, CausalInferenceToolset, LLMCausalToolset, CausalWorldModelToolset | 16 |
| v15.7 | PrecisionToolset, ReportToolset | 8 |
| v15.8 | NL2SQLToolset | 3 |
| v16.0 | OperatorToolset, ToolEvolutionToolset | 13 |
| **合计** | **+16 Toolset** | **+97 工具** |

已有 Toolset 也有扩展：ExplorationToolset 6→9、RemoteSensingToolset 7→13、AnalysisToolset 3→5、DatabaseToolset 5→6。

---

*本文档基于 GIS Data Agent v16.0 (ADK v1.27.2) 的 39 个 Toolset 源码精确同步，2026-04-02。*
