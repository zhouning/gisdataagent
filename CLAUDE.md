# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GIS Data Agent (ADK Edition) v15.7 — an AI-powered geospatial analysis platform built on **Google Agent Developer Kit (ADK)**. It uses LLM-based semantic routing to dispatch user requests across three specialized pipelines for data governance, land-use optimization (via Deep Reinforcement Learning), and general spatial intelligence. The frontend is a custom React three-panel SPA served via **Chainlit** with password/OAuth2 authentication. Users can self-service extend the platform with custom Skills (agent behaviors), User Tools (declarative templates), and multi-Agent pipeline workflows.

v15.7 adds the **Surveying QC Agent** subsystem: defect taxonomy (30 codes, 5 categories per GB/T 24356), SLA-enforced QC workflow templates, enhanced governance/precision/cleaning toolsets, QC report engine, alert rules, case library, MCP tool selection rules, human review workflow, and 4 independent subsystems under `subsystems/` (CV detection, CAD/3D parser, professional tool MCP servers, reference data service).

## Commands

### Run the application
```bash
$env:PYTHONPATH = "D:\adk"
chainlit run data_agent/app.py -w
```
Default login: `admin` / `admin123` (seeded on first run). In-app self-registration on login page. Note: DB fallback removed — database must be available for authentication.

### Run tests
```bash
# All tests (2650+ tests, 94 test files)
.venv/Scripts/python.exe -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q

# Single test file
.venv/Scripts/python.exe -m pytest data_agent/test_frontend_api.py -v
```

### Build frontend
```bash
cd frontend && npm run build
```

### Environment
- Python virtual environment: `D:\adk\.venv\Scripts\python.exe` (Python 3.13.7)
- Environment variables in `data_agent/.env` (PostgreSQL/PostGIS credentials, Vertex AI config, `CHAINLIT_AUTH_SECRET`)
- Dependencies: `requirements.txt` (329 packages)
- Node.js for frontend: `cd frontend && npm install`

## Architecture

### Authentication & Multi-tenancy
- **Auth flow**: Chainlit login → `@cl.password_auth_callback` / `@cl.oauth_callback` → `cl.User` with role metadata
- **Brute-force protection**: Per-username lockout after 5 consecutive failures (15-minute lockout), in-memory counter in `auth.py`
- **Self-registration**: In-app on LoginPage.tsx (mode toggle login/register) → `POST /auth/register` → `register_user()` in auth.py
- **Account deletion**: `DELETE /api/user/account` → `delete_user_account()` with cascade cleanup (token_usage, memories, share_links, team_members, audit_log, annotations)
- **User identity propagation**: `contextvars.ContextVar` in `user_context.py` — set once per message in `app.py`, read implicitly by all tool functions via `get_user_upload_dir()`
- **File sandbox**: `uploads/{user_id}/` per user. `_generate_output_path()` and `_resolve_path()` in `gis_processors.py` are user-scoped
- **RBAC**: admin (full access), analyst (analysis pipelines), viewer (General pipeline query-only)
- **DB context**: `SET app.current_user` injected before SQL queries in `database_tools.py` (RLS-ready)
- **OAuth**: Conditional — only registered when `OAUTH_GOOGLE_CLIENT_ID` env var is set

### Semantic Intent Router (`intent_router.py`)
Extracted from app.py for modularity. On each user message:
1. `app.py` sets `ContextVar` for user identity (per async task)
2. Handles file uploads (ZIP auto-extraction for `.shp`/`.kml`/`.geojson`/`.gpkg`)
3. Calls `classify_intent()` (in `intent_router.py`) which uses **Gemini 2.0 Flash** to classify user text into one of three intents
4. RBAC check (viewers blocked from Governance/Optimization)
5. Dispatches to the appropriate pipeline
6. Detects `layer_control` in tool responses → injects metadata for NL map control

### Three Pipelines (all defined in `agent.py`)

**Optimization Pipeline** (`data_pipeline`) — `SequentialAgent`:
`ParallelIngestion(Exploration ‖ SemanticPreFetch) → DataProcessing → AnalysisQualityLoop → DataVisualization → DataSummary`

**Governance Pipeline** (`governance_pipeline`) — `SequentialAgent`:
`GovExploration → GovProcessing → GovernanceReportLoop`

**General Pipeline** (`general_pipeline`) — `SequentialAgent`:
`GeneralProcessing → GeneralViz → GeneralSummaryLoop`

Each agent is an ADK `LlmAgent` with specific tools. Agent prompts live in `data_agent/prompts/` (3 YAML files). Agents share state via `output_key` (e.g., `data_profile`, `processed_data`, `analysis_report`).

Note: ADK requires separate agent instances per pipeline (cannot share an agent across two parent agents due to "already has a parent" constraint).

### User Self-Service Extension

**Custom Skills** (`custom_skills.py`): Users create custom LlmAgent instances with tailored instructions, toolset selections, trigger keywords, and model tier. DB-stored, per-user isolation with optional sharing. Frontend CRUD in CapabilitiesView.

**User-Defined Tools** (`user_tools.py` + `user_tool_engines.py`): Declarative tool templates — http_call, sql_query, file_transform, chain. DB-stored, with built-in execution engines. Wrapped as ADK `FunctionTool` via dynamic signature construction. Exposed through `UserToolset(BaseToolset)`.

**Multi-Agent Pipeline Composition**: Users can compose custom Skills as Agent nodes in the WorkflowEditor (ReactFlow DAG editor). The workflow engine supports `pipeline_type: "custom_skill"` steps that dynamically build LlmAgent instances. DAG execution with topological sort enables parallel branches.

### Frontend Architecture
Custom React SPA replacing Chainlit's default UI. Three-panel layout with draggable resizers: Chat | Map | Data.

- **ChatPanel**: Messages, streaming, action cards, NL layer control relay
- **MapPanel**: Leaflet.js 2D map + deck.gl/MapLibre 3D view with toggle, GeoJSON layers, layer control, annotations, basemap switcher (Gaode/Tianditu/CartoDB/OSM), legend
- **Map3DView**: deck.gl + MapLibre GL 3D renderer — extrusion, column, arc, scatterplot layers with hover tooltips
- **DataPanel**: 16 tabs — files, CSV preview, data catalog, pipeline history, token usage dashboard, MCP tools, workflows, suggestions, tasks, templates, analytics, capabilities, knowledge base, virtual sources, marketplace, GeoJSON editor (modularized into `datapanel/` — 17 component files)
- **WorkflowEditor**: ReactFlow-based visual DAG editor with 4 node types (DataInput, Pipeline, Skill Agent, Output)
- **LoginPage**: Login + in-app registration mode toggle
- **AdminDashboard**: Metrics, user management, audit log (admin only)
- **UserSettings**: Account info + self-deletion modal (danger zone)
- **App.tsx**: Auth state, map/data state, layer control, user menu dropdown, resizable panel widths

### Frontend API (123 REST endpoints in `frontend_api.py`)
All endpoints use JWT cookie auth. Routes mounted before Chainlit catch-all via `mount_frontend_api()`.

Key endpoint groups:
- Data catalog + lineage: `/api/catalog`
- Semantic layer: `/api/semantic`
- Pipeline history: `/api/pipeline/history`
- User management: `/api/user/*`
- Map annotations: `/api/annotations`
- Admin: `/api/admin/*`
- MCP Hub CRUD: `/api/mcp/*` (10 endpoints)
- Workflows: `/api/workflows/*` (8 endpoints)
- Custom Skills CRUD: `/api/skills` (5 endpoints)
- Skill Bundles: `/api/bundles` (6 endpoints)
- User-Defined Tools: `/api/user-tools` (6 endpoints)
- Knowledge Base + GraphRAG: `/api/kb/*` (10 endpoints)
- Templates: `/api/templates` (6 endpoints)
- Pipeline Analytics: `/api/analytics/*` (5 endpoints)
- Task Queue: `/api/tasks/*` (4 endpoints)
- Capabilities aggregation: `/api/capabilities`
- Map pending updates: `/api/map/pending`

### Key Modules

| Module | Purpose |
|---|---|
| `agent.py` | Agent definitions, pipeline assembly, factory functions |
| `app.py` | Chainlit UI, RBAC, file uploads, layer control (3267 lines) |
| `intent_router.py` | Semantic intent classification (extracted from app.py) |
| `pipeline_helpers.py` | Tool explanation, progress rendering, error classification (extracted from app.py) |
| `pipeline_runner.py` | Headless pipeline executor — zero UI dependency, PipelineResult dataclass |
| `frontend_api.py` | 92 REST API endpoints (2330 lines) |
| `auth.py` | Password hashing, brute-force protection, registration, Chainlit auth callbacks |
| `user_context.py` | `ContextVar` for user_id/session_id/role propagation; `get_user_upload_dir()` |
| `custom_skills.py` | DB-driven custom Skills: CRUD, validation, agent factory, lazy toolset registry |
| `user_tools.py` | User-defined declarative tools: CRUD, validation, template type checking |
| `user_tool_engines.py` | Tool execution engines (http_call, sql_query, file_transform, chain) + FunctionTool builder |
| `capabilities.py` | Capabilities introspection — list built-in skills + toolsets with metadata |
| `workflow_engine.py` | Workflow engine — CRUD, sequential + DAG execution, Cron, Webhook, custom_skill steps |
| `db_engine.py` | Singleton SQLAlchemy engine with connection pooling |
| `health.py` | K8s health check API + startup diagnostics |
| `observability.py` | Structured logging (JSON) + Prometheus metrics |
| `semantic_layer.py` | Semantic catalog + 3-level hierarchy + 5-min TTL cache |
| `data_catalog.py` | Unified data lake catalog + lineage tracking |
| `fusion/` | Multi-modal data fusion package — 22 modules, 10 strategies, PostGIS push-down |
| `knowledge_graph.py` | Geographic knowledge graph — networkx DiGraph |
| `mcp_hub.py` | MCP Hub Manager — DB + YAML config, 3 transport protocols, CRUD + hot reload |
| `multimodal.py` | Multimodal input processing — image/PDF classification, Gemini Part builders |

### Toolsets (26 registered, 28 .py files in `toolsets/`)
ExplorationToolset, GeoProcessingToolset, VisualizationToolset, AnalysisToolset, DatabaseToolset, SemanticLayerToolset, DataLakeToolset, StreamingToolset, TeamToolset, LocationToolset, MemoryToolset, AdminToolset, FileToolset, RemoteSensingToolset, SpatialStatisticsToolset, McpHubToolset, FusionToolset, KnowledgeGraphToolset, KnowledgeBaseToolset, AdvancedAnalysisToolset, SpatialAnalysisTier2Toolset, WatershedToolset, **UserToolset**, **GovernanceToolset** (18 tools), **DataCleaningToolset** (11 tools), **PrecisionToolset** (5 tools).

### ADK Skills (18 built-in + DB custom skills)
18 fine-grained scenario skills in `data_agent/skills/` (kebab-case dirs). Three-level incremental loading (L1 metadata → L2 instructions → L3 resources).

### Data Loading (`_load_spatial_data` in `agent.py`)
Supported formats: CSV, Excel (.xlsx/.xls), Shapefile, GeoJSON, GPKG, KML, KMZ. CSV/Excel auto-detect coordinate columns (lng/lat, lon/lat, longitude/latitude, x/y).

### DRL Optimization Flow
The DRL model uses `MaskablePPO` (from `sb3_contrib`) with a custom `ParcelScoringPolicy`. Model weights are loaded from `scorer_weights_v7.pt`. The environment performs paired farmland↔forest swaps to minimize fragmentation while maintaining area balance.

### File Conventions
- Generated outputs use UUID suffixes: `{prefix}_{uuid8}.{ext}`
- User uploads scoped to `data_agent/uploads/{user_id}/`
- Path resolution: `_resolve_path()` checks user sandbox → shared uploads → raw path
- Path generation: `_generate_output_path(prefix, ext)` outputs to user sandbox

### CI Pipeline (`.github/workflows/ci.yml`)
- **test**: Ubuntu + PostGIS service, pytest with JUnit XML
- **frontend**: Node.js 20, npm build
- **evaluate**: ADK agent evaluation (main push only, requires GOOGLE_API_KEY secret)

## Tech Stack
- **Framework**: Google ADK v1.27 (`google.adk.agents`, `google.adk.runners`)
- **LLM**: Gemini 2.5 Flash / 2.5 Pro (agents), Gemini 2.0 Flash (router)
- **Frontend**: React 18 + TypeScript + Vite + Leaflet.js + deck.gl + ReactFlow + @chainlit/react-client v0.3.1
- **Backend**: Chainlit + Starlette (202 REST API endpoints)
- **Database**: PostgreSQL 16 + PostGIS 3.4 (22 system tables, 43 migrations)
- **GIS**: GeoPandas, Shapely, Rasterio, PySAL, Folium, mapclassify, branca
- **ML**: PyTorch, Stable Baselines 3, Gymnasium
- **CI**: GitHub Actions (pytest + frontend build + evaluation)
- **Language**: Prompts and UI text are primarily in Chinese; code comments mix Chinese and English

### Subsystems (`subsystems/`, v15.7)
Independent microservices integrated via MCP protocol or REST API:
| Subsystem | Path | Integration | Key Tech |
|-----------|------|-------------|----------|
| CV Detection | `subsystems/cv-service/` | MCP (stdio) | FastAPI + YOLO/ultralytics |
| CAD/3D Parser | `subsystems/cad-parser/` | MCP (stdio) | FastAPI + ezdxf + trimesh |
| Tool MCP Servers | `subsystems/tool-mcp-servers/` | MCP (stdio) | arcgis-mcp (subprocess→arcpy), qgis-mcp, blender-mcp |
| Reference Data | `subsystems/reference-data/` | REST + BaseConnector | FastAPI + PostGIS |

ArcPy environment: `D:/Users/zn198/AppData/Local/ESRI/conda/envs/arcgispro-py3-clone-new2/python.exe` (configured in `data_agent/.env` as `ARCPY_PYTHON_EXE`).

### Surveying QC System (v15.7)
- **Defect Taxonomy**: `data_agent/standards/defect_taxonomy.yaml` — 30 codes, 5 categories (FMT/PRE/TOP/MIS/NRM), severity A/B/C per GB/T 24356
- **QC Workflow Templates**: `data_agent/standards/qc_workflow_templates.yaml` — 3 presets (standard 5-step, quick 2-step, full 7-step) with SLA/timeout per step
- **Alert Engine**: `AlertEngine` in `observability.py` — configurable threshold rules with webhook push
- **MCP Tool Rules**: `ToolRuleEngine` in `mcp_hub.py` — task_type → tool selection with fallback chain
- **Case Library**: `add_case()` / `search_cases()` in `knowledge_base.py` — structured QC experience records
- **Human Review**: `agent_qc_reviews` table — review→mark→fix→approve workflow via `/api/qc/reviews`
- **DB Migrations**: 039 (workflow SLA), 040 (MCP tool rules), 041 (alert rules), 042 (KB case library), 043 (QC reviews)
