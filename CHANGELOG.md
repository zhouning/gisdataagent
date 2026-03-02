# Changelog

All notable changes to the GIS Data Agent project.

## [v4.0.0] - 2026-03-02 (Frontend Integration, CI & Post-Launch Enhancement)

### Feature — React-Integrated Self-Registration (F1)
- **In-app registration**: Login page now includes register mode toggle (username, email, password, confirm password, display name fields). Calls `POST /auth/register` directly.
- **Email support**: `register_user()` accepts optional email parameter with regex validation. `email` column added to `agent_app_users` table.
- **Migration**: `015_add_email_column.sql` adds email column.

### Feature — Token Usage Dashboard (F2)
- **UsageView component** in DataPanel: 5th tab ("用量") showing daily count progress bar, monthly token summary, and pipeline breakdown visualization.
- **Pipeline breakdown API**: `get_pipeline_breakdown()` in `token_tracker.py` returns `[{pipeline_type, count, tokens}]` grouped by pipeline for current month.
- **Auto-refresh**: Dashboard refreshes every 30 seconds.

### Feature — Natural Language Layer Control (F3)
- **`control_map_layer()` tool**: 5 actions — show, hide, style, remove, list. Supports color/opacity customization.
- **Pipeline**: Tool result → `app.py` detects `layer_control` key → injects metadata → ChatPanel `onLayerControl` → App state → MapPanel `useEffect` handler.
- **MapPanel integration**: Reacts to control commands by toggling layer visibility, updating styles, or removing layers from the Leaflet map.

### Feature — Collaborative Map Annotations (F4)
- **`map_annotations.py`** (new): CRUD functions for annotations with PostgreSQL storage (`agent_map_annotations` table).
- **4 REST endpoints**: GET/POST `/api/annotations`, PUT/DELETE `/api/annotations/{id}`.
- **MapPanel UI**: Annotation toggle button (pencil icon), click-to-add with popup form (title + comment), marker rendering with resolve/delete actions.
- **Team scope**: Users see own annotations + team annotations. Delete requires ownership verification.
- **Migration**: `016_create_map_annotations.sql`.

### Feature — Tianditu Compliant Basemap (F5)
- **`GET /api/config/basemaps`**: Returns `{gaode_enabled, tianditu_enabled, tianditu_token}` based on environment configuration.
- **Dynamic basemap loading**: MapPanel fetches basemap config on mount. Tianditu Vec + Img layers loaded conditionally when token is available.
- **Static basemaps**: Gaode (高德) added as permanent option alongside CartoDB and OpenStreetMap.

### Feature — Toolset Optimization — Skill Bundles (F6)
- **`skill_bundles.py`** (new): `SkillBundle` dataclass with 5 named bundles:
  - `SPATIAL_ANALYSIS`: Exploration + GeoProcessing + Location + RemoteSensing + SpatialStatistics + Analysis
  - `DATA_QUALITY`: Exploration + Database + File + SemanticLayer + DataLake
  - `VISUALIZATION`: Visualization tools (9 tools including layer control)
  - `DATABASE`: Database + DataLake
  - `COLLABORATION`: Memory + Admin + Team + DataLake
- **Intent matching**: `get_bundles_for_intent()` and `build_toolsets_for_intent()` for dynamic toolset assembly.
- **Filter presets**: AUDIT_TOOLS, TRANSFORM_TOOLS, DB_READ, GENERAL_VIZ, SEMANTIC_READONLY.

### Feature — User Account Self-Deletion (F7)
- **`delete_user_account()`** in `auth.py`: Password verification → cascade delete (token_usage, memories, share_links, team_members, audit_log, annotations) → remove upload directory → delete user account.
- **Admin protection**: Admins cannot delete themselves via this method.
- **`DELETE /api/user/account`**: REST endpoint with password confirmation in request body.
- **`UserSettings.tsx`** (new): Modal component with user info display and danger zone for account deletion.
- **User menu**: Header avatar click reveals dropdown menu with "账户设置" (settings) and "退出登录" (logout) options.

### Feature — CI Pipeline + Evaluation (F8)
- **`.github/workflows/ci.yml`** (new): 3 jobs:
  - `test`: Ubuntu + PostGIS service container, pytest with JUnit XML output
  - `frontend`: Node.js 20, `npm ci && npm run build`
  - `evaluate`: ADK agent evaluation on main push (requires GOOGLE_API_KEY secret)
- **JSON eval summary**: `run_evaluation.py` now writes `eval_results/eval_summary.json` with scores and pass/fail status.
- **Additional eval cases**: Governance check + general spatial query test cases added to `eval_set.json`.

### Changed
- **Frontend API**: 17 REST endpoints (up from 11), organized into catalog, semantic, pipeline, user, admin, annotation, and config groups.
- **Toolset count**: 16 BaseToolset modules (up from 15, added skill_bundles.py).
- **Visualization tools**: 9 tools (up from 8, added control_map_layer).
- **DataPanel tabs**: 5 tabs (files, CSV, catalog, history, usage — added usage tab).
- **App.tsx**: User dropdown menu, UserSettings modal integration, layer control wiring.

### Tests
- **Total**: 923 tests passing (up from 882).
- New tests: frontend API (47 tests including delete account, basemap config, annotations), map annotations (11), skill bundles (5), layer control (7).

---

## [v4.0.0-beta] - 2026-03-01 (Data Lake, Lineage & Hierarchy Enhancement)

### Feature — Unified Data Lake Integration
- **Data Catalog** (`data_catalog.py`): Unified `agent_data_catalog` table managing assets across local files, OBS cloud, and PostGIS backends. 8 ADK tools via `DataLakeToolset`: `list_data_assets`, `describe_data_asset`, `search_data_assets` (fuzzy + substring matching), `register_data_asset`, `tag_data_asset`, `delete_data_asset`, `share_data_asset` (admin-only), `get_data_lineage`.
- **Auto-registration**: Tool outputs automatically registered in catalog via `register_tool_output()` in `app.py`. File uploads registered on ingest.

### Feature — Data Lineage Tracking
- **Source tracking**: `source_assets` JSONB field in data catalog now populated automatically from tool arguments. `_extract_source_paths()` scans tool args for file path keys.
- **`get_data_lineage()`** ADK tool: Trace data provenance chain — ancestors (what was it derived from), descendants (what was derived from it), or both directions. Recursive chain walking up to 10 levels.

### Feature — Health Check API
- **`health.py`** (new): K8s-ready health endpoints — `/health` (liveness), `/ready` (readiness, 503 if DB down), `/api/admin/system-info` (admin HMAC auth).
- **Subsystem checks**: Database latency, OBS cloud storage, Redis, session service.
- **Startup diagnostics**: `format_startup_summary()` prints ASCII banner with all subsystem statuses and feature flags.
- **K8s probes**: `app-deployment.yaml` updated to use `/health` and `/ready`.

### Feature — 3-Level Semantic Hierarchy
- **Sub-children**: LAND_USE hierarchy extended from 2 levels (parent→child) to 3 levels (parent→child→sub_child). Added sub-categories following China's Third National Land Survey codes:
  - 耕地 → 旱地[0101], 水浇地[0102], 水田[0103]
  - 园地 → 果园[0201], 茶园[0202], 其他园地[0204]
  - 林地 → 有林地[0301], 灌木林地[0302], 其他林地[0307]
  - 草地 → 天然牧草地[0401], 人工牧草地[0402], 其他草地[0403]
- **`browse_hierarchy()`** ADK tool: Agents can explore the full taxonomy tree. Returns structured tree + formatted text display.
- **`_match_hierarchy()`**: Sub-child matching with most-specific-first priority. Returns `level: "sub_child"` with 4-digit code prefix.
- **`expand_hierarchy()`**: Expanding a child with sub_children returns sub_children for finer granularity.
- **SQL filters**: Sub-child matches generate 4-digit LIKE patterns (e.g., `dlbm LIKE '0103%'`).

### Feature — Bot Integration (DingTalk + Feishu)
- **DingTalk bot** (`dingtalk_bot.py`): Enterprise callback with HMAC signature verification.
- **Feishu bot** (`feishu_bot.py`): Lark/Feishu with event challenge + AES decryption.
- **Shared infrastructure** (`bot_base.py`): TokenCache, RateLimiter, MessageDedup.

### Feature — Real-time Streams
- **Stream engine** (`stream_engine.py`): Redis Streams with in-memory fallback.
- **5 ADK tools**: create_iot_stream, set_geofence_alert, query_trajectory, aggregate_stream_window, list_active_streams.
- **Geofence**: Point-in-polygon check for real-time location alerts.

### Feature — Team Collaboration
- **Team management** (`team_manager.py`): 8 tools for team CRUD, member management, resource sharing.
- **RLS extended**: Team members can access tables/templates owned by fellow team members.

### Feature — Remote Sensing
- **5 raster tools**: describe_raster, calculate_ndvi, raster_band_math, classify_raster, visualize_raster.
- **Data download**: download_lulc (Sentinel-2 10m, 2017-2024), download_dem (Copernicus 30m).

### Tests
- **Total**: 836 tests passing (up from 538).
- New test files: test_health.py (24), test_data_catalog.py expanded (+19 lineage), test_semantic_layer.py expanded (+16 hierarchy), test_stream_engine.py (36), test_team.py (30), test_dingtalk_bot.py, test_feishu_bot.py (55 combined).

## [v4.0.0-alpha.2] - 2026-02-27 (Architecture Polish & Semantic Enhancement)

### Performance — Connection Pool Singleton
- **`db_engine.py`** (new): Singleton SQLAlchemy engine with connection pooling (`pool_size=5, max_overflow=10, pool_recycle=1800s, pool_pre_ping=True`). Replaces 50 per-function `create_engine()` calls across 10 modules.
- **Refactored modules**: `database_tools.py`, `memory.py`, `semantic_layer.py`, `audit_logger.py`, `token_tracker.py`, `sharing.py`, `template_manager.py`, `auth.py`, `app.py`, `utils.py` — all now use `from .db_engine import get_engine`.
- **`reset_engine()`**: For testing and graceful shutdown.

### Performance — Semantic Layer Query Cache
- **TTL cache** (5 min) for `agent_semantic_sources` and `agent_semantic_registry` DB queries in `semantic_layer.py`. Eliminates redundant DB lookups on every user message.
- **`invalidate_semantic_cache()`**: Called automatically on write operations (register, annotate, auto-register).

### Feature — Domain Hierarchy (LAND_USE)
- **Hierarchy tree** in `semantic_catalog.yaml`: 3 parent categories (农用地, 建设用地, 未利用地) with 9 child land-use types, each with code prefixes and Chinese/English aliases.
- **`_match_hierarchy()`**: Matches "耕地" → child (code_prefix 01, parent 农用地); "农用地" → parent (expands to 耕地+园地+林地+草地).
- **Prompt injection**: `build_context_prompt()` outputs hierarchy info like "地类筛选: 农用地 (包含 耕地[01*], 园地[02*], 林地[03*], 草地[04*])".

### Feature — Column Equivalence Mappings
- **Equivalences** in `semantic_catalog.yaml`: dlbm↔dlmc (地类编码↔名称), xzqdm↔xzqmc (行政区代码↔名称), qsdwdm↔qsdwmc (权属代码↔名称).
- **`_match_equivalences()`**: When a column like `dlbm` is matched, automatically associates its equivalent `dlmc`.
- **Prompt injection**: Outputs "等价列: dlbm ↔ dlmc (地类编码 ↔ 地类名称)".

### Documentation
- **README.md** rewritten for v4.0-alpha: updated architecture diagram (Mermaid), full feature matrix, Docker quick start, project structure, test guide.
- **3 demo scenarios** (`demos/`): Retail site selection, land governance audit, population analysis — each with sample data generation and headless pipeline execution.
- **Docker quickstart** (`demos/docker-quickstart.sh`): One-command setup script.

### Tests
- **`test_db_engine.py`** (new, 5 tests): Singleton behavior, no-DB fallback, pool config verification.
- **Semantic layer tests** expanded (31 new → 63 total): Hierarchy matching (child/parent), equivalence matching, cache invalidation, prompt output verification.
- **All test mock targets** updated: 6 test files (`test_rls.py`, `test_integration.py`, `test_semantic_layer.py`, `test_template_manager.py`, `test_token_tracker.py`, `test_audit.py`, `test_memory.py`, `test_wecom.py`) now mock `get_engine` instead of `create_engine`/`get_db_connection_url`.
- **Total**: 538 tests passing.

## [v4.0.0-alpha] - 2026-02-24 (Secure & Enhanced Platform)

### Added — OBS Cloud Storage (S3-Compatible)
- **OBS Storage Module** (`obs_storage.py`): Huawei Cloud OBS integration via standard S3 protocol (boto3). Thread-safe singleton client, user-scoped S3 keys (`{user_id}/{filename}`). Shapefile bundle upload/download auto-handles sidecar files (.cpg/.dbf/.prj/.shx/.sbn/.sbx/.shp.xml). Graceful degradation to local-only mode when OBS env vars not configured.
- **Cloud Fallback** (`gis_processors.py`): `_resolve_path()` now falls back to OBS download when file not found locally. Transparent to all 30+ tools — no signature changes needed.
- **Upload Sync** (`app.py`): Uploaded files automatically synced to OBS after local copy. Tool output files synced to OBS after each `function_response`. Report exports synced to OBS.
- **Cloud-Aware File Management** (`agent.py`): `list_user_files()` shows merged local+cloud view with `[云端]`/`[仅本地]` tags. `delete_user_file()` deletes from both local and cloud storage.
- **Startup Health Check**: `ensure_obs_connection()` verifies bucket access at startup with status logging.

### Added — Session Persistence
- **DatabaseSessionService** (`app.py`): ADK sessions now persist to PostgreSQL via `asyncpg`. `_create_session_service()` attempts `DatabaseSessionService` with graceful fallback to `InMemorySessionService` when `asyncpg` is unavailable or DB unreachable. Tables (`sessions`, `events`, `app_states`, `user_states`) auto-created by ADK on first use. Page refresh / server restart no longer loses conversation history.
- **Async DB URL** (`database_tools.py`): `get_async_db_url()` converts sync PostgreSQL URL to `postgresql+asyncpg://` scheme for async session driver.

### Added — Analysis Explainability
- **Tool Descriptions** (`app.py`): `TOOL_DESCRIPTIONS` dict (40+ entries) maps each tool to a Chinese method name and parameter labels. Displayed in Chainlit Step.input during tool execution.
- **Human-readable Formatting** (`app.py`): `_format_tool_explanation()` converts raw tool args dict into formatted Chinese text with method name header and labeled parameters. File paths shortened to basename; long values truncated.
- **Smart Result Display** (`app.py`): `function_response` handler now extracts meaningful output (file paths, status messages) instead of showing generic "执行成功" for all tools.

### Added — Dynamic Planner
- **Dynamic Planner** (`agent.py`): LlmAgent-based orchestrator replaces fixed SequentialAgent pipelines. Uses ADK `transfer_to_agent` for dynamic sub-agent delegation. 5 specialist agents: Explorer (data quality/DB), Processor (GIS ops/geocoding), Analyzer (FFI/DRL), Visualizer (maps/charts), Reporter (reports). Handles composite, conditional, and cross-pipeline requests. Feature flag `DYNAMIC_PLANNER` (default true); set to false for legacy mode. Safety: `RunConfig(max_llm_calls=50)`.

### Added — Plan Mode, Quality Gate, Model Tiering
- **Plan Mode Confirmation** (`app.py`): OPTIMIZATION/GOVERNANCE intents trigger a lightweight analysis plan (via Gemini 2.0 Flash) shown to user with confirm/modify/cancel buttons before execution. Approved plan injected as `[分析方案]` block into agent prompt. New `plan_generation_prompt` in `prompts.yaml`.
- **Quality Gate** (`agent.py`): `_quality_gate_check()` validates tool output files post-execution. Checks: SHP feature count + CRS, CSV data rows, HTML/PNG minimum size, zero-byte detection. Critical failures trigger auto-retry via `_self_correction_after_tool`; warnings annotated and passed through.
- **Model Tiering** (`agent.py`): Three-tier model strategy for Planner agents. `MODEL_FAST` (gemini-2.0-flash) for Explorer/Visualizer, `MODEL_STANDARD` (gemini-2.5-flash) for Processor/Analyzer/Planner root, `MODEL_PREMIUM` (gemini-2.5-pro) for Reporter. Legacy pipeline agents unchanged.

### Added — Security & Multi-tenancy
- **User Authentication**: Chainlit password login + Google OAuth2 (conditional on env vars).
- **Per-user File Sandbox**: All uploads and outputs scoped to `uploads/{user_id}/`.
- **RBAC**: Three roles (admin/analyst/viewer). Viewers blocked from Governance & Optimization pipelines.
- **Database User Context**: Injects `SET app.current_user` before SQL queries (RLS-ready).
- **Auth Module** (`auth.py`): Password hashing (PBKDF2-SHA256), `app_users` table, auto-seeded admin (admin/admin123).
- **User Context Module** (`user_context.py`): `ContextVar`-based identity propagation across async tool chains.
- **SQL Migration**: `migrations/001_create_users.sql` for user management table.
- **Row-Level Security (RLS)**: PostgreSQL RLS policies enforce data isolation at the database level.
    - `user_memories` table: users can only read/write their own memories; admin sees all.
    - `token_usage` table: users can only see their own consumption records; admin sees all.
    - `table_ownership` registry: tracks ownership of dynamically-imported PostGIS tables. Users see own + shared tables; admin sees all.
    - `_inject_user_context(conn)` helper: injects both `app.current_user` and `app.current_user_role` via `set_config()` before every DML operation across `database_tools.py`, `memory.py`, and `token_tracker.py`.
    - `_load_spatial_data()` fixed: passes `conn` (with context) to `gpd.read_postgis()` instead of `engine` (which opened a new context-less connection).
    - `list_tables()` / `describe_table()` rewritten to check `table_ownership` registry with RLS auto-filtering.
    - `register_table_ownership()`: UPSERT into registry after PostGIS imports.
    - `share_table()`: admin-only tool to mark tables as shared (accessible to all users).
    - `ensure_table_ownership_table()`: startup initializer with superuser/bypassrls warning.
    - `import_shp_to_pg.py`: `--owner` and `--shared` CLI args; auto-registers ownership after import.
    - SQL Migration: `migrations/004_enable_rls.sql` — RLS policies, `FORCE ROW LEVEL SECURITY`, pre-seeds existing spatial tables as admin-shared.

### Added — Data Quality & Import
- **Open-Source GIS Tools** (`gis_processors.py`): 5 new tools replacing ArcPy equivalents, built on GeoPandas/Shapely/Pandas:
    - `polygon_neighbors`: Polygon adjacency analysis — detects neighboring polygons via spatial index, outputs CSV with shared boundary length and node count. Auto-projects to planar CRS for accurate measurement.
    - `add_field`: Add new attribute field with type (TEXT/FLOAT/INTEGER/DOUBLE) and optional default value.
    - `add_join`: Attribute table join (left join) by common field. Supports CSV and Shapefile as join source.
    - `calculate_field`: Field expression calculator using `!field!` ArcGIS syntax (converted to safe `df.eval()`). Supports arithmetic and field references.
    - `summary_statistics`: GroupBy aggregation with ArcGIS-style stats format (`"field SUM;field MEAN"`). Supports SUM/MEAN/MIN/MAX/COUNT/STD/FIRST/LAST with optional case field grouping.
- **Data Quality Pre-check**: `describe_geodataframe()` expanded from 1 check (CRS) to 7 checks:
    - Null values per column, null/empty geometries, anomalous coords (0,0), out-of-bounds coords, duplicate geometries, mixed geometry types, attribute statistics.
    - Returns severity levels: `pass` / `warning` / `critical`.
- **Excel Import**: `.xlsx` / `.xls` with auto-detection of coordinate columns (same as CSV).
- **KML/KMZ Import**: Direct KML reading via pyogrio; KMZ auto-extraction of contained .kml.
- **ZIP Enhancement**: ZIP extraction now searches for `.kml`, `.geojson`, `.gpkg` (fallback after `.shp`).

### Added — Visualization
- **Choropleth Map** (`generate_choropleth`): Value-based polygon coloring with 3 classification methods (quantile, equal_interval, natural_breaks), 7 color schemes, floating legend.
- **Bubble Map** (`generate_bubble_map`): Size-scaled circle markers for point data with optional color ramp. Supports same 7 color schemes and 4 basemaps.
- **Basemap Switching**: All interactive maps now offer 4 basemaps: CartoDB positron, OpenStreetMap, CartoDB Dark, Gaode (高德).
- **Heatmap / KDE** (`generate_heatmap`): Kernel Density Estimation raster heatmap via scipy.
- **Spatial Distance Query** (`find_within_distance`): Find features within/beyond a given distance.

### Added — Geocoding & Public Data
- **Amap (高德) Geocoding**: Primary geocoding via Gaode Maps API with Nominatim fallback.
- **Reverse Geocoding** (`reverse_geocode`): Coordinates-to-address conversion via Amap regeocode API. Adds province/city/district columns.
- **POI Nearby Search** (`search_nearby_poi`): Search points of interest (banks, hospitals, restaurants, etc.) within a specified radius around any coordinate. Returns Shapefile with name, type, address, distance.
- **POI Keyword Search** (`search_poi_by_keyword`): Search POIs by keyword within a city or district (e.g., "find all Starbucks in Beijing"). Returns Shapefile with full POI attributes.
- **Admin Boundary** (`get_admin_boundary`): Download administrative district boundary polygons as Shapefile. Supports optional `with_sub_districts` flag to include child district boundaries (handles municipalities/直辖市 hierarchy automatically).

### Added — UX & Safety
- **Real-time Progress Feedback**: Pipeline execution now shows hierarchical progress:
    - **Pipeline-level**: Top-level step showing pipeline name and elapsed time.
    - **Agent-level**: Stage indicators (e.g., "阶段 2/6: 正在数据质量审计...") tracking SequentialAgent transitions via `event.author`.
    - **Tool-level**: Chinese status labels (e.g., "正在批量地理编码..." → "批量地理编码 ✓ (2.3s)") for all 30+ tool functions.
- **Multi-turn Dialogue Context**: Users can reference prior results ("上面的结果", "刚才的数据") across conversation turns.
    - After each turn, generated file paths + analysis summary stored in session.
    - Next turn's prompt automatically injected with `[上轮分析上下文]` block.
    - Intent router uses previous pipeline as fallback when user references prior context.
- **PostGIS Direct Visualization**: All 7 visualization tools (`generate_choropleth`, `visualize_interactive_map`, etc.) now accept PostGIS table names directly as `file_path`. `_load_spatial_data()` auto-detects table names (no extension + alphanumeric pattern) and reads via `gpd.read_postgis()`. Eliminates the need to export SHP before visualization.
- **File Size Limit**: Uploads exceeding 100 MB are rejected with user notification.
- **Upload Data Preview**: Immediate markdown preview after file upload showing feature count, CRS, geometry type, bounding box, and first 5 rows.
- **Map Export PNG** (`export_map_png`): High-DPI static map image export with contextily basemap, optional value column coloring and title.
- **Ambiguous Intent Clarification**: When the intent router cannot confidently classify a request, it prompts the user to select the desired pipeline via interactive action buttons.
- **User Data Management**: `list_user_files` and `delete_user_file` tools allow users to view and clean up their uploaded/generated files within their sandbox.
- **Natural Language Map Control**: `visualize_interactive_map` and `generate_choropleth` now accept optional `center_lat`, `center_lng`, `zoom` parameters. Agents can translate location names to coordinates for map positioning.
- **Tianditu Basemap** (天地图): All interactive maps support Tianditu vector + label layers when `TIANDITU_TOKEN` env var is configured. Basemap code unified via `_add_basemap_layers()` helper.
- **Driving Distance** (`calculate_driving_distance`): Two-point driving distance/time via Amap Driving Route API, with Haversine straight-line distance as reference.
- **Method Statement**: All three Summary agents (GeneralSummary, DataSummary, GovernanceReporter) now mandatorily include a "分析方法" paragraph with method name, parameters, and data source.
- **Self-Correction** (`after_tool_callback`): When a tool returns an error, contextual hints are automatically appended (e.g., "please call describe_table to get real column names"). Retry limit of 3 per tool per invocation prevents infinite loops. Applied to 5 key agents.
- **Spatial Memory System** (`memory.py`): Persistent per-user memory stored in PostgreSQL (`user_memories` table with JSONB). Supports 4 memory types: `region` (常用区域), `viz_preference` (可视化偏好), `analysis_result` (历史分析), `custom`. Auto-saves analysis results after each pipeline run. Users can save/recall/list/delete memories via natural language. Visualization preferences automatically injected into agent prompts as defaults.
- **Enhanced Report Generation**: Professional Word/PDF reports with page headers/footers, page numbers, pipeline-specific titles (优化/治理/通用), author metadata, date stamps, and styled heading hierarchy. Export button now available for all three pipelines (previously only Optimization/Governance). PDF export via `docx2pdf` with graceful fallback to Word if conversion unavailable.
- **Token Usage Tracking** (`token_tracker.py`): Per-user LLM token consumption tracking stored in PostgreSQL (`token_usage` table). Records input/output tokens per pipeline run. Daily analysis limit (configurable via `DAILY_ANALYSIS_LIMIT` env var, default 20/day, admin exempt). Monthly token limit support (`MONTHLY_TOKEN_LIMIT` env var, default unlimited). Usage summary queryable via natural language (e.g., "我今天用了多少token"). Tokens accumulated from ADK `event.usage_metadata` and intent router `response.usage_metadata`.
- **ArcPy Integration** (`arcpy_tools.py` + `arcpy_worker.py`): Optional parallel GIS engine via persistent subprocess bridge. 8 tools: `arcpy_buffer`, `arcpy_clip`, `arcpy_dissolve` (ArcPy-unique: field dissolve with multi-stat aggregation), `arcpy_project`, `arcpy_check_geometry` (enhanced geometry validation), `arcpy_repair_geometry` (ArcPy-unique: auto-fix invalid geometries), `arcpy_slope`, `arcpy_zonal_statistics`. Enabled via `ARCPY_PYTHON_EXE` env var pointing to ArcGIS Pro Python. JSON-line IPC protocol over stdin/stdout with persistent worker process (avoids ~3-5s ArcPy cold start). Graceful degradation when ArcPy unavailable.

### Changed
- **Path Consolidation**: Removed duplicate `_generate_output_path` / `_resolve_path` from `agent.py`; unified on `gis_processors.py` versions (user-scoped).
- **File Path Regex**: `extract_file_paths()` now recognizes `.xlsx`, `.xls`, `.kml`, `.kmz`, `.geojson`, `.gpkg`.
- **Prompts**: Added choropleth, bubble map, and reverse geocoding guidance to agent instructions.

### Fixed
- Chainlit `@cl.oauth_callback` made conditional to avoid crash when no OAuth provider configured.

---## [v3.2.0] - 2026-02-23 (Semantic Analyst)
### Added
- **Semantic Intent Router**: Replaced keyword matching with LLM-based intent classification (Governance vs Optimization vs General).
- **Spatial Semantic Layer**: `describe_table` tool allows agents to inspect DB schema and map natural language queries to actual columns.
- **Business Analysis Suite**:
    - `perform_clustering`: DBSCAN clustering.
    - `create_buffer`: Buffer zone analysis.
    - `overlay_difference`: Erase/Difference analysis.
    - `summarize_within`: Zonal statistics.
- **Visualization**: Support for Heatmaps (`L.heatLayer`) and Clustered Markers (`L.circleMarker`) in `visualize_interactive_map`.

### Changed
- **Architecture**: `GeneralPipeline` prompt hardened to support complex reasoning chains (e.g., Site Selection).
- **UX**: Export button is now hidden for simple General queries to reduce noise.
- **Database**: `list_tables` now identifies Spatial tables.

### Fixed
- Fixed `GeneralViz` crashing on empty input.
- Fixed session argument error in `app.py`.

## [v3.1.0] - 2026-02-20
### Added
- **Hard Routing**: Split monolithic agent into Governance, Optimization, and General pipelines.
- **PostGIS Integration**: Full read/write support for PostgreSQL.

## [v2.0.0] - 2025-12-15
- Excel Geocoding.
- Word Report Generation.
