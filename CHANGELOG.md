# Changelog

All notable changes to the Data Agent project will be documented in this file.

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
