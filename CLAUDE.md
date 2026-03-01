# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GIS Data Agent (ADK Edition) v4.0-beta — an AI-powered geospatial analysis platform built on **Google Agent Developer Kit (ADK)**. It uses LLM-based semantic routing to dispatch user requests across three specialized pipelines for data governance, land-use optimization (via Deep Reinforcement Learning), and general spatial intelligence. The UI is served via **Chainlit** with password/OAuth2 authentication.

## Commands

### Run the application
```bash
chainlit run data_agent/app.py -w
```
Default login: `admin` / `admin123` (seeded on first run).

### Run tests (unittest-based)
```bash
# Single test file
python -m pytest data_agent/test_database.py

# All tests
python -m pytest data_agent/test_*.py
```

### Environment
- Python virtual environment: `D:\adk\.venv\Scripts\python.exe` (Python 3.13.7)
- Environment variables in `data_agent/.env` (PostgreSQL/PostGIS credentials, Vertex AI config, `CHAINLIT_AUTH_SECRET`)
- No requirements.txt — dependencies managed directly in venv via pip

## Architecture

### Authentication & Multi-tenancy
- **Auth flow**: Chainlit login → `@cl.password_auth_callback` / `@cl.oauth_callback` → `cl.User` with role metadata
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

### Three Pipelines (all defined in `agent.py`)

**Optimization Pipeline** (`data_pipeline`) — `SequentialAgent`:
`KnowledgeAgent → DataEngineering(Exploration → Processing) → DataAnalysis → DataVisualization → DataSummary`

**Governance Pipeline** (`governance_pipeline`) — `SequentialAgent`:
`GovExploration → GovProcessing → GovernanceReporter`

**General Pipeline** (`general_pipeline`) — `SequentialAgent`:
`GeneralProcessing → GeneralViz → GeneralSummary`

Each agent is an ADK `LlmAgent` with specific tools. Agent prompts live in `data_agent/prompts.yaml`. Agents share state via `output_key` (e.g., `data_profile`, `processed_data`, `analysis_report`).

Note: ADK requires separate agent instances per pipeline (cannot share an agent across two parent agents due to "already has a parent" constraint).

### Key Modules

| Module | Purpose |
|---|---|
| `agent.py` | All agent definitions, tool functions (visualization, FFI, DRL, choropleth), pipeline assembly |
| `app.py` | Chainlit UI, auth integration, semantic router, file upload handling, RBAC, report export |
| `user_context.py` | `ContextVar` for user_id/session_id/role propagation; `get_user_upload_dir()` |
| `auth.py` | Password hashing, `app_users` table management, Chainlit auth callbacks |
| `gis_processors.py` | GIS operations: tessellation, raster-to-polygon, clip, overlay, clustering, buffer, zonal stats, heatmap, distance query |
| `database_tools.py` | PostgreSQL/PostGIS integration via SQLAlchemy; spatial queries return SHP, non-spatial return CSV; injects user context |
| `drl_engine.py` | Gymnasium environment (`LandUseOptEnv`) for land-use layout optimization |
| `FFI.py` | Farmland Fragmentation Index — 6 landscape metrics (NP, LPI, PD, LSI, AWMSI, AI) |
| `doc_auditor.py` | PDF-to-shapefile consistency checking for governance |
| `geocoding.py` | Batch address-to-coordinates (Amap primary, Nominatim fallback) |
| `report_generator.py` | Markdown → Word (.docx) report generation |
| `parcel_scoring_policy.py` | Custom MaskablePPO policy network for the DRL model |
| `prompts.yaml` | All LLM instruction prompts (Chinese, with LaTeX/table formatting rules) |
| `migrations/` | SQL migration scripts (001_create_users.sql) |

### Data Loading (`_load_spatial_data` in `agent.py`)
Supported formats: CSV, Excel (.xlsx/.xls), Shapefile, GeoJSON, GPKG, KML, KMZ. CSV/Excel auto-detect coordinate columns (lng/lat, lon/lat, longitude/latitude, x/y).

### DRL Optimization Flow
The DRL model uses `MaskablePPO` (from `sb3_contrib`) with a custom `ParcelScoringPolicy`. Model weights are loaded from `scorer_weights_v7.pt`. The environment performs paired farmland↔forest swaps to minimize fragmentation while maintaining area balance.

### File Conventions
- Generated outputs use UUID suffixes: `{prefix}_{uuid8}.{ext}`
- User uploads scoped to `data_agent/uploads/{user_id}/`
- Path resolution: `_resolve_path()` checks user sandbox → shared uploads → raw path
- Path generation: `_generate_output_path(prefix, ext)` outputs to user sandbox

## Tech Stack
- **Framework**: Google ADK (`google.adk.agents`, `google.adk.runners`)
- **LLM**: Gemini 2.5 Flash (agents), Gemini 2.0 Flash (router)
- **UI**: Chainlit (with password + OAuth2 auth)
- **Database**: PostgreSQL 16 + PostGIS 3.4
- **GIS**: GeoPandas, Shapely, Rasterio, PySAL, Folium, mapclassify, branca
- **ML**: PyTorch, Stable Baselines 3, Gymnasium
- **Language**: Prompts and UI text are primarily in Chinese; code comments mix Chinese and English
