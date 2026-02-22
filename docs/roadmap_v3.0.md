# Data Agent v3.0 Roadmap: The "Spatial Analyst" Evolution

> **Vision**: Transform from a specialized optimization tool into a general-purpose **"AI Spatial Analyst"** that empowers non-GIS experts to make location-based decisions.
>
> **Philosophy**: "The best GIS interface is no interface." (Interface Disappearance Principle)

---

## 1. Strategic Positioning (Refined via PRD)

Based on the [Product Requirements Document](../PRD_GIS_Data_Agent_V1.md) and [Benchmark Analysis](../标杆产品分析_OpenClaw_OpenAI_Frontier.md), we target the **"High GIS Capability + High Agent Capability"** quadrant—a currently vacant market position.

### Core Value Proposition
*   **For**: Data Analysts (Persona A) & Decision Makers (Persona C).
*   **Who**: Need spatial insights (Site selection, Sales territory) but lack ArcGIS skills.
*   **The Product**: Acts as a "Spatial Analyst Colleague" rather than just a tool.
*   **Differentiation**: Unlike generic agents (Julius), we have deep GIS kernels; Unlike specialized GIS (ArcGIS), we offer zero-learning-curve interaction.

---

## 2. Technical Pillars

### 🟢 Pillar 1: Universal Access (The "Excel Bridge")
*   **Problem**: 90% of business data lives in Excel with addresses, not Shapefiles with coordinates.
*   **Solution**: Seamless ingestion of non-spatial data.
*   **Key Tech**: `pandas` + `Geocoding API` (Gaode/Baidu) + Auto-Coordinate Recognition.

### 🔵 Pillar 2: Business Spatial Intelligence (BSI)
*   **Problem**: Users need answers to "Where?" (Where to open a store? Where are customers?), not just "How optimized?".
*   **Solution**: A suite of commercial geography models.
*   **Key Tech**: `DBSCAN` (Clustering), `KDE` (Heatmaps), `Buffer Analysis` (Catchment), `NetworkX` (Drive-time).

### 🔴 Pillar 3: Spatial Semantic Layer (Enterprise Readiness)
*   **Problem**: Agents struggle to map business concepts ("East Region Sales") to spatial files (`east_poly.shp`).
*   **Solution**: A "System 2" memory layer that maps business entities to spatial objects.
*   **Key Tech**: Vector Store (Chroma/Milvus) + Structured Metadata (JSON-LD).

---

## 3. Feature Roadmap

### Phase 3.0: The "Business Analyst" Update (Q2 2026)
*Target: Persona A (Data Analyst) - Completing the P0 Requirements*

| Priority | Feature | Description | Status |
| :--- | :--- | :--- | :--- |
| **P0** | **Excel/CSV Ingestion** | Full support for `.xlsx` and `.csv`. Auto-detect Address/LatLon columns. | ✅ DONE |
| **P0** | **Geocoding Agent** | "Turn addresses into points". Batch geocoding via API with caching. | ✅ DONE |
| **P0** | **Professional Reporting** | Native Word table rendering for audit reports. | ✅ DONE |
| **P0** | **Clustering Tool** | "Where are the clusters?" DBSCAN/K-Means integration for store/customer grouping. | TODO |
| **P0** | **Heatmap Engine** | "Where is the hotspot?" Kernel Density Estimation (KDE) visualization. | TODO |
| **P1** | **Buffer/Catchment** | "Who lives within 3km?" Geometric buffering and simple overlap stats. | TODO |

### Phase 3.1: The "Smart Interaction" Update (Q3 2026)
*Target: Usability & Retention - Implementing "Spatial Memory"*

| Priority | Feature | Description | PRD Ref |
| :--- | :--- | :--- | :--- |
| **P1** | **Spatial Memory** | Remember user preferences ("I focus on Chaoyang District") and historical context. | 5.2.1 |
| **P1** | **Interactive Layer Control** | NL control: "Show/Hide layer", "Change style to red". | 5.1.3 |
| **P1** | **Analysis Explanation** | "Why this result?" Step-by-step logic transparency (Chain of Thought display). | 5.2.3 |

### Phase 3.2: The "Enterprise Infrastructure" Update (Q4 2026)
*Target: Persona C (Enterprise) - Scalability & Collaboration*

| Priority | Feature | Description | PRD Ref |
| :--- | :--- | :--- | :--- |
| **P1** | **Router Agent** | Hard routing architecture to split traffic into specialized pipelines (e.g., Governance vs. Optimization) to reduce token cost and latency. | Arch |
| **P2** | **PostGIS Backend** | Migration from file-based (GeoPandas) to DB-based (PostGIS) for TB-scale data. | 5.1.2 |
| **P2** | **Spatial Semantic Layer** | Knowledge graph mapping business terms to spatial assets. | 5.3 (F1) |
| **P2** | **Docker/Helm** | Cloud-native deployment artifacts for private cloud. | 5.3 (F5) |

---

## 4. Architecture Evolution (v2.9 -> v3.0)

### Current Architecture (v2.9 - Soft Routing)
*   **Sequential Pipeline**: `Input -> Knowledge -> Engineering -> Analysis -> Viz -> Summary`
*   **Logic**: Single track. Agents use prompt-based logic ("Skip if governance") to handle branches.
*   **Pros/Cons**: Low complexity but high token consumption for simple tasks.

### Target Architecture (v3.0 - Hard Routing)
```mermaid
graph TD
    UserInput --> RouterAgent[🚦 Intent Router]
    
    RouterAgent -->|Intent: "Audit/Check"| GovPipe[🛡️ Governance Pipeline]
    RouterAgent -->|Intent: "Optimize"| OptPipe[🚀 Optimization Pipeline]
    RouterAgent -->|Intent: "Query"| QAPipe[💬 Q&A Pipeline]
    
    subgraph "Shared Resources"
        SpatialMemory[(Spatial Memory)]
        ToolRegistry[GIS Toolset]
    end
    
    GovPipe --> ToolRegistry
    OptPipe --> ToolRegistry
```

## 5. Success Metrics (KPIs)

## 5. Success Metrics (KPIs)

*   **Time-to-Map**: User uploads raw Excel -> Interactive Map in **< 2 minutes**.
*   **Analysis Success Rate**: > 85% of natural language spatial queries correctly executed.
*   **Retention**: Users return for > 5 sessions/month (driven by Spatial Memory).
