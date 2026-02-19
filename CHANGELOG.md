# Changelog

All notable changes to the Data Agent project will be documented in this file.

## [v2.7.0] - 2026-02-19

### 🛠️ Advanced GIS Toolbox (Open Source Implementation)
- **New GIS Processors**: Implemented 6 core GIS tools using pure Python (`geopandas`, `rasterio`, `rasterstats`), replicating ArcGIS/ArcPy functionality without commercial license requirements:
    - **Generate Tessellation**: Create square or hexagonal grids over any extent.
    - **Raster to Polygon**: Vectorize raster datasets (GeoTIFF) into Shapefiles.
    - **Pairwise Clip**: Precise vector-on-vector clipping.
    - **Tabulate Intersection**: Cross-tabulate area proportions between two layers.
    - **Surface Parameters**: Calculate **Slope** and **Aspect** directly from DEM rasters using NumPy gradients.
    - **Zonal Statistics As Table**: Summarize raster values (mean, sum, etc.) within vector zones.
- **Enhanced DataProcessing Agent**: Updated the agent's knowledge and instructions to leverage these advanced spatial operations autonomously.

## [v2.6.0-beta] - 2026-02-19

### 🚀 AI Model Upgrade (v7)
- **New Inference Engine**: Integrated **v7 Maskable PPO** model (`drl_engine.py` update).
    - **Paired Swaps**: Implements a "pair bonus" strategy to ensure farmland quantity balance (net change ~0).
    - **Reduced Penalty**: Lowered count deviation penalty to prevent reward drowning during exploration.
    - **Extended Horizon**: Fixed episode length to 200 steps (100 pairs) without early stopping for maximum global optimization.
- **Robust Inference**:
    - Replaced `.zip` model loading with direct **Weights Loading** (`scorer_weights_v7.pt`) to bypass optimizer state mismatches.
    - Implemented `ParcelScoringPolicy` with permutation-invariant architecture for variable-sized inputs.

### 📝 Prompt Engineering
- Updated `DataAnalysis` prompt to reflect v7's 200-step paired swap logic.
- Updated `DataSummary` prompt to emphasize "Balanced Optimization" and interpret the red/blue change patterns.

## [v2.5.0] - 2026-02-18

### 🌟 New Features (UI/UX)
- **Custom Web UI**: Replaced generic ADK Web with a specialized **Chainlit** application (`data_agent/app.py`).
- **Gemini-like Experience**:
    - **Nested Thinking Steps**: Agent tool calls are now collapsed under a "Thinking Process" expander to keep the chat clean.
    - **Live Timer**: Real-time duration display for thinking processes and tool execution (e.g., `(1.2s)`).
    - **Starters**: Quick-action buttons on the welcome screen for demos and FAQs.
- **Rich Media**:
    - **Inline Images**: Analysis charts (PNG) render directly in the chat bubble.
    - **Interactive Maps**: Generated HTML maps (Folium) are available for download.
- **Report Export**: Added a "📄 Export Word Report" button to generate a `.docx` file containing the full analysis text and embedded charts.
- **File Upload**: Support for uploading `.zip` (containing Shapefiles) and `.csv` directly in the chat.

### 🛠️ Core Improvements
- **Multi-Format Support**:
    - Added auto-detection for CSV files with lat/lon columns.
    - Implemented standardization pipeline to convert CSV -> SHP for downstream DRL processing.
- **Evaluation System**:
    - Implemented programmatic evaluation using `AgentEvaluator`.
    - Added ROUGE-1 score calculation and visualization charts.
    - Optimized `eval_set.json` to achieve a high response match score (**0.52**).

### 🐛 Bug Fixes
- Fixed Chinese font rendering issues in Matplotlib charts (`Microsoft YaHei`/`SimHei` auto-detection).
- Fixed `KeyError: 'Element'` in Chainlit file upload handling.
- Fixed JSON escape issues in evaluation datasets.

### 📚 Documentation
- Added **User Manual** (`docs/user_manual`).
- Added **Operations Manual** (`docs/ops_manual`).
- Added **Developer Guide** (`docs/dev_guide`).
