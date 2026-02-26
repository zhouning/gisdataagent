# GIS Data Agent (ADK Edition)

**Current Version**: v3.2.0 ("Semantic Analyst")

A specialized AI Agent for Geospatial Data Analysis, Governance, and Optimization. Built with Google Agent Developer Kit (ADK), LangChain, and PostGIS.

## 🌟 Key Capabilities

### 1. 🛡️ To G: Data Governance (数据治理)
*   **Automated Audit**: Scans for topological errors (overlaps, self-intersections).
*   **Compliance Check**: Verifies schema against national standards (e.g., GB/T 21010).
*   **Multi-modal Verification**: Cross-checks PDF reports against SHP/DB metrics.

### 2. 🚀 To B: Land Use Optimization (空间优化)
*   **DRL Engine (v7)**: Uses PPO (Proximal Policy Optimization) to optimize land use layout.
*   **Objective**: Reduce fragmentation (FFI) and optimize slope suitability.
*   **Paired Swaps**: Ensures strict "balance of total area" during optimization.

### 3. 🌍 General: Business Spatial Intelligence (商业智能)
*   **Semantic Query**: "Find parcels > 5 mu with slope < 15" -> Auto-maps to DB schema.
*   **Site Selection**: Complex chain reasoning (Query -> Buffer -> Difference -> Filter).
*   **Clustering & Heatmaps**: DBSCAN clustering and KDE heatmaps for point data.
*   **Catchment Analysis**: Buffer and Summarize-Within analysis.

## 🏗️ Architecture

```mermaid
graph TD
    User[User Input] --> Router{Semantic Router\n(Gemini Flash)}
    
    Router -- "Audit/Check" --> Gov[🛡️ Governance Pipeline]
    Router -- "Optimize/Plan" --> Opt[🚀 Optimization Pipeline]
    Router -- "Analyze/Query" --> Gen[🌍 General Pipeline]
    
    subgraph "Governance Pipeline"
        GovExploration --> GovProcessing --> GovReporter
    end
    
    subgraph "Optimization Pipeline"
        DataExploration --> DataProcessing --> DataAnalysis(DRL) --> DataViz --> DataSummary
    end
    
    subgraph "General Pipeline"
        GenProcessing(Tools: Buffer, Cluster, SQL...) --> GenViz(Heatmap/Map) --> GenSummary
    end
```

## 🛠️ Tech Stack

*   **Core**: Python 3.12, Google ADK
*   **LLM**: Gemini 2.0 Flash / Pro
*   **Database**: PostgreSQL 16 + PostGIS 3.4
*   **GIS**: GeoPandas, Shapely, Rasterio, PySAL
*   **Viz**: Folium, Matplotlib, Seaborn
*   **AI**: Stable Baselines 3 (PPO), PyTorch

## 🚀 Getting Started

1.  **Environment Setup**:
    ```bash
    # Install dependencies
    pip install -r requirements.txt
    ```

2.  **Database Config**:
    Edit `data_agent/.env` with your PostGIS credentials.

3.  **Run the Agent**:
    ```bash
    chainlit run data_agent/app.py -w
    ```

## 🗺️ Roadmap

| Version | Feature Set | Status |
| :--- | :--- | :--- |
| v1.0 | Local Files, Basic DRL | ✅ Done |
| v2.0 | Excel Geocoding, Report Gen | ✅ Done |
| v3.0 | PostGIS, Hard Routing | ✅ Done |
| v3.1 | Multi-Pipeline Architecture | ✅ Done |
| v3.2 | **Semantic Layer & Business Suite** | ✅ Current |
| v4.0 | Dynamic Planner & Tool Registry | 🚧 Planned |
| v5.0 | Multi-Modal & 3D (Cesium) | 📅 Future |

## 📂 Project Structure

*   `data_agent/`: Core agent logic.
    *   `app.py`: Intent Router & UI Entry.
    *   `agent.py`: Agent definitions & Tool registration.
    *   `gis_processors.py`: GIS algorithms (Clustering, Buffer, etc.).
    *   `drl_engine.py`: Deep Reinforcement Learning environment.
*   `tests/`: Unit and integration tests.
