# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GIS Data Agent (ADK Edition) v7.0 — an AI-powered geospatial analysis platform built on **Google Agent Developer Kit (ADK)**. It uses LLM-based semantic routing to dispatch user requests across three specialized pipelines for data governance, land-use optimization (via Deep Reinforcement Learning), and general spatial intelligence. The frontend is a custom React three-panel SPA served via **Chainlit** with password/OAuth2 authentication.

## Commands

### Run the application
```bash
chainlit run data_agent/app.py -w
```
Default login: `admin` / `admin123` (seeded on first run). In-app self-registration on login page.

### Run tests
```bash
# All tests (1330+ tests)
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
- **Self-registration**: In-app on LoginPage.tsx (mode toggle login/register) → `POST /auth/register` → `register_user()` in auth.py
- **Account deletion**: `DELETE /api/user/account` → `delete_user_account()` with cascade cleanup (token_usage, memories, share_links, team_members, audit_log, annotations)
- **User identity propagation**: `contextvars.ContextVar` in `user_context.py` — set once per message in `app.py`, read implicitly by all tool functions via `get_user_upload_dir()`
- **File sandbox**: `uploads/{user_id}/` per user. `_generate_output_path()` and `_resolve_path()` in `gis_processors.py` are user-scoped
- **RBAC**: admin (full access), analyst (analysis pipelines), viewer (General pipeline query-only)
- **DB context**: `SET app.current_user` injected before SQL queries in `database_tools.py` (RLS-ready)
- **OAuth**: Conditional — only registered when `OAUTH_GOOGLE_CLIENT_ID` env var is set

### Semantic Intent Router (`app.py`)
Entry point. On each user message:
1. Sets `ContextVar` for user identity (per async task)
2. Handles file uploads (ZIP auto-extraction for `.shp`/`.kml`/`.geojson`/`.gpkg`)
3. Calls `classify_intent()` which uses **Gemini 2.0 Flash** to classify user text into one of three intents
4. RBAC check (viewers blocked from Governance/Optimization)
5. Dispatches to the appropriate pipeline
6. Detects `layer_control` in tool responses → injects metadata for NL map control

### Three Pipelines (all defined in `agent.py`)

**Optimization Pipeline** (`data_pipeline`) — `SequentialAgent`:
`KnowledgeAgent → DataEngineering(Exploration → Processing) → DataAnalysis → DataVisualization → DataSummary`

**Governance Pipeline** (`governance_pipeline`) — `SequentialAgent`:
`GovExploration → GovProcessing → GovernanceReporter`

**General Pipeline** (`general_pipeline`) — `SequentialAgent`:
`GeneralProcessing → GeneralViz → GeneralSummary`

Each agent is an ADK `LlmAgent` with specific tools. Agent prompts live in `data_agent/prompts/` (3 YAML files). Agents share state via `output_key` (e.g., `data_profile`, `processed_data`, `analysis_report`).

Note: ADK requires separate agent instances per pipeline (cannot share an agent across two parent agents due to "already has a parent" constraint).

### Frontend Architecture
Custom React SPA replacing Chainlit's default UI. Three-panel layout: Chat (320px) | Map (flex-1) | Data (360px).

- **ChatPanel**: Messages, streaming, action cards, NL layer control relay
- **MapPanel**: Leaflet.js 2D map + deck.gl/MapLibre 3D view with toggle, GeoJSON layers, layer control, annotations, basemap switcher (Gaode/Tianditu/CartoDB/OSM), legend
- **Map3DView**: deck.gl + MapLibre GL 3D renderer — extrusion, column, arc, scatterplot layers with hover tooltips
- **DataPanel**: 7 tabs — files, CSV preview, data catalog, pipeline history, token usage dashboard, MCP tools, workflows
- **LoginPage**: Login + in-app registration mode toggle
- **AdminDashboard**: Metrics, user management, audit log (admin only)
- **UserSettings**: Account info + self-deletion modal (danger zone)
- **App.tsx**: Auth state, map/data state, layer control, user menu dropdown

### Frontend API (31 REST endpoints in `frontend_api.py`)
All endpoints use JWT cookie auth. Routes mounted before Chainlit catch-all via `mount_frontend_api()`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/catalog`, `/api/catalog/{id}`, `/api/catalog/{id}/lineage` | Data lake catalog + lineage |
| GET | `/api/semantic/domains`, `/api/semantic/hierarchy/{domain}` | Semantic layer browsing |
| GET | `/api/pipeline/history` | Pipeline run history |
| GET | `/api/user/token-usage` | Token usage + pipeline breakdown |
| DELETE | `/api/user/account` | Self-delete account |
| GET/POST | `/api/annotations`, PUT/DELETE `/api/annotations/{id}` | Map annotations CRUD |
| GET | `/api/config/basemaps` | Basemap configuration |
| GET/PUT/DELETE | `/api/admin/users`, `/api/admin/users/{username}/role`, `/api/admin/metrics/summary` | Admin endpoints |
| GET | `/api/mcp/servers`, `/api/mcp/tools` | MCP server status + tool listing |
| POST | `/api/mcp/servers/{name}/toggle`, `/api/mcp/servers/{name}/reconnect` | MCP server management (admin) |
| GET/POST | `/api/workflows` | Workflow list + create |
| GET/PUT/DELETE | `/api/workflows/{id}` | Workflow detail, update, delete |
| POST | `/api/workflows/{id}/execute` | Execute workflow |
| GET | `/api/workflows/{id}/runs` | Workflow execution history |

### Key Modules

| Module | Purpose |
|---|---|
| `agent.py` | Agent definitions, pipeline assembly, tool functions |
| `app.py` | Chainlit UI, auth, semantic router, RBAC, file uploads, layer control |
| `frontend_api.py` | 31 REST API endpoints for React frontend |
| `auth.py` | Password hashing, registration, account deletion, Chainlit auth callbacks |
| `user_context.py` | `ContextVar` for user_id/session_id/role propagation; `get_user_upload_dir()` |
| `db_engine.py` | Singleton SQLAlchemy engine with connection pooling |
| `health.py` | K8s health check API + startup diagnostics |
| `observability.py` | Structured logging (JSON) + Prometheus metrics |
| `semantic_layer.py` | Semantic catalog + 3-level hierarchy + 5-min TTL cache |
| `data_catalog.py` | Unified data lake catalog + lineage tracking |
| `map_annotations.py` | Collaborative map annotation CRUD |
| `token_tracker.py` | Per-user LLM usage tracking + pipeline breakdown |
| `audit_logger.py` | Enterprise audit trail |
| `gis_processors.py` | GIS operations: tessellation, buffer, clip, overlay, clustering, zonal stats |
| `database_tools.py` | PostgreSQL/PostGIS integration via SQLAlchemy; RLS; user context |
| `drl_engine.py` | Gymnasium environment (`LandUseOptEnv`) for land-use optimization |
| `memory.py` | Persistent per-user spatial memory |
| `report_generator.py` | Markdown → Word (.docx) report generation |
| `toolsets/skill_bundles.py` | 5 named toolset groupings for agent configuration |
| `mcp_hub.py` | MCP Hub Manager — config-driven MCP server connection + tool aggregation |
| `toolsets/mcp_hub_toolset.py` | BaseToolset wrapper bridging MCP Hub to ADK agents |
| `multimodal.py` | Multimodal input processing — image/PDF classification, Gemini Part builders |
| `workflow_engine.py` | Multi-step workflow engine — CRUD, execution, webhook push, cron scheduling |
| `fusion_engine.py` | Multi-modal data fusion — profiling, compatibility, alignment, 10 fusion strategies |
| `knowledge_graph.py` | Geographic knowledge graph — networkx-based entity-relationship modeling |
| `evals/agent.py` | Evaluation umbrella agent — wraps 4 pipelines as sub_agents for ADK AgentEvaluator |
| `run_evaluation.py` | Multi-pipeline ADK evaluation runner with per-metric scoring and charts |

### Toolsets (19 modules in `toolsets/`)
Exploration, GeoProcessing, Visualization (10 tools incl. `generate_3d_map`, `control_map_layer`), Analysis, Database, SemanticLayer (9 tools), DataLake (8 tools), Streaming (5 tools), Team (8 tools), Location, Memory, Admin, File, RemoteSensing, SpatialStatistics, SkillBundles, McpHub, Fusion (4 tools), KnowledgeGraph (3 tools).

### Data Loading (`_load_spatial_data` in `agent.py`)
Supported formats: CSV, Excel (.xlsx/.xls), Shapefile, GeoJSON, GPKG, KML, KMZ. CSV/Excel auto-detect coordinate columns (lng/lat, lon/lat, longitude/latitude, x/y).

### Multimodal Input (`multimodal.py`)
File uploads are classified by `classify_upload()` into spatial/image/pdf/document types. Images are resized and embedded as `types.Part(inline_data=Blob)` for Gemini vision. PDFs are processed with dual strategy: text extraction via pypdf (appended to prompt) + native PDF Blob for Gemini. Voice input uses browser Web Speech API (frontend-only, `zh-CN`/`en-US`).

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
- **Framework**: Google ADK v1.21 (`google.adk.agents`, `google.adk.runners`)
- **LLM**: Gemini 2.5 Flash / 2.5 Pro (agents), Gemini 2.0 Flash (router)
- **Frontend**: React 18 + TypeScript + Vite + Leaflet.js + @chainlit/react-client v0.3.1
- **Backend**: Chainlit + Starlette (31 REST API endpoints)
- **Database**: PostgreSQL 16 + PostGIS 3.4
- **GIS**: GeoPandas, Shapely, Rasterio, PySAL, Folium, mapclassify, branca
- **ML**: PyTorch, Stable Baselines 3, Gymnasium
- **CI**: GitHub Actions (pytest + frontend build + evaluation)
- **Language**: Prompts and UI text are primarily in Chinese; code comments mix Chinese and English
