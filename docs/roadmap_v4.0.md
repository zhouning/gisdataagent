# Roadmap v4.0: Autonomous & Secure Enterprise Agent

**Goal**: Transform the GIS Data Agent from a "Semantic Analyst" (v3.2) into an **"Autonomous, Secure Enterprise Platform"**.

This release focuses on two pillars:
1.  🧠 **Autonomy**: Dynamic task planning and self-correction.
2.  🛡️ **Security**: Multi-tenancy, AuthN/AuthZ, and RLS (Row-Level Security).

---

## 🏛️ Pillar 1: Enterprise Security Architecture (企业级安全架构)

### 1.1 Identity & Authentication (身份认证)
*   **Chainlit Auth Integration**: Implement `@cl.password_auth_callback` or OAuth2 (Google/GitHub/SSO).
*   **Session Persistence**: Move sessions from `InMemorySessionService` to `DatabaseSessionService` (PostgreSQL/Redis) to survive restarts.
*   **User Management**: Create a `users` table with `id`, `username`, `password_hash`, `role`.

### 1.2 Data Isolation (数据隔离) - *Critical*
*   **File System Sandbox**:
    *   Refactor `UPLOAD_DIR` to structured paths: `uploads/{user_id}/{session_id}/`.
    *   Update `_resolve_path` in `agent.py` to strictly limit file access to the current user's sandbox.
*   **Database Multi-tenancy (RLS)**:
    *   **Strategy**: Use PostgreSQL **Row-Level Security (RLS)**.
    *   **Schema**: Add `owner_id` column to all business tables (`heping_village_8000`, etc.).
    *   **Policy**: `CREATE POLICY user_data ON table USING (owner_id = current_setting('app.current_user'));`
    *   **Context Injection**: Modify `database_tools.py` to inject `SET app.current_user = '{user_id}'` upon connection.

### 1.3 RBAC (Role-Based Access Control)
*   **Roles**:
    *   `ADMIN`: Full access (Governance, Optimization, User Mgmt).
    *   `ANALYST`: Read/Write data, Analysis pipelines (General, Optimization).
    *   **VIEWER**: Read-only, View Reports/Maps (General - Query Mode only).
*   **Router Enforcement**: Update `app.py` semantic router to check `user.role` before dispatching to sensitive pipelines (e.g., block `GovernancePipeline` for Viewers).

---

## 🧠 Pillar 2: Autonomous Planning (自主规划)

### 2.1 Dynamic Planner Agent
*   **Problem**: Current pipelines (`SequentialAgent`) are brittle. Complex intent ("Find site X, then do Y, unless Z") requires dynamic branching.
*   **Solution**: Implement a **ReAct / Plan-and-Solve** loop.
    *   **Planner**: Break down user goal into a DAG (Directed Acyclic Graph) of tasks.
    *   **Executor**: Execute tasks step-by-step.
    *   **Reflector**: Check execution results. If `error`, modify plan and retry.

### 2.2 ADK Skills Integration & Dynamic Toolset
*   **Problem**: `agent.py` tool list and system prompts are growing too large for the context window, causing instruction conflicts and token bloat.
*   **Solution**: Implement **ADK Skills (`google.adk.skills`)** and `SkillToolset`.
    *   **Mechanism**: Refactor monolithic prompts and tools into modular skills (e.g., `spatial_clustering_skill`, `report_generator_skill`, `gis_compliance_skill`). Encapsulate L1/L2 instructions, static assets (reports/logos), and references. Dynamically load these skills using `SkillToolset` based on the active task or user intent.
    *   **Benefit**: Drastically reduces context window usage, eliminates prompt conflicts, and provides a scalable architecture to manage 100+ GIS tools and domain knowledge.

### 2.3 Self-Correction (自我纠错)
*   **Mechanism**: Catch `Exception` in tool execution -> Feed traceback to LLM -> LLM generates corrected parameters -> Retry tool.
*   **Scenario**: "Column 'area' not found" -> LLM checks schema -> Retries with 'shape_area'.

---

## 🌊 Pillar 3: Data Lake Architecture (数据湖架构)

### 3.1 Cloud-Native Storage (云原生存储)
*   **Problem**: Currently, files are stored locally in the `uploads/` directory, which is not scalable for distributed deployments or enterprise-grade data volume.
*   **Solution**: Integrate **Huawei Cloud OBS (Object Storage Service)** as the centralized Data Lake using the **standard S3 protocol**.
    *   **Endpoint**: `https://obs.cn-north-4.myhuaweicloud.com` (or configurable).
    *   **Authentication**: Secure AK/SK (Access Key & Secret Key) injection via `.env` or Key Vault.
    *   **Advantage**: Huawei OBS is fully compatible with native S3 APIs. We will use `boto3` instead of proprietary SDKs, ensuring vendor lock-in prevention and broad ecosystem compatibility (e.g., GeoPandas `s3://` support).

### 3.2 Storage Abstraction Layer (存储抽象层)
*   **Design**: Implement a unified `StorageBackend` interface (e.g., `BaseStorage`, `LocalStorage`, `S3Storage`) to decouple file operations from the file system.
*   **Operations**: `upload_file`, `download_file`, `generate_presigned_url`, `list_files`, `delete_file`.
*   **Migration**: Replace all hardcoded `os.path` and `uploads/` logic in `app.py` and `gis_processors.py` with `StorageBackend` calls executing via `boto3`.

### 3.3 Tenant Data Segregation in OBS (租户数据隔离)
*   **Bucket Structure**: Enforce strict path prefixes for multi-tenancy.
    *   `obs://{bucket_name}/tenant_{user_id}/session_{session_id}/{filename}`
*   **Security**: Ensure users can only access files within their assigned `tenant_{user_id}` prefix. Combine this with temporary Presigned URLs (预签名URL) for secure frontend downloading/rendering.

### 3.4 Data Pipeline Integration (数据流水线对接)
*   **Ingestion**: User uploads file (e.g., SHP, GeoJSON) -> Backend buffers and uploads to OBS -> Trigger PostGIS data loading from OBS via temp files.
*   **Egress**: Output maps (`.png`), reports (`.docx`), or processed SHP files generated by the Agent are directly uploaded to OBS, returning an OBS URL to the Chainlit frontend.

---

## 📅 Implementation Phases

### Phase 1: Security & Storage Foundation (v4.0-alpha)
1.  Implement User Table & Chainlit Login.
2.  Implement `StorageBackend` interface and Huawei Cloud OBS integration.
3.  Migrate local `uploads/` file system to OBS (`obs://{bucket}/tenant_{user_id}/`).
4.  Refactor `database_tools` to accept `user_context`.

### Phase 2: Database Isolation & Pipeline (v4.0-beta)
1.  Migrate DB Schema (Add `owner_id`).
2.  Enable RLS on PostgreSQL.
3.  Connect OBS data ingestion pipeline with PostgreSQL (OBS -> Temp -> PostGIS).
4.  Test isolation: Ensure User A cannot query User B's spatial features or access User B's OBS objects.

### Phase 3: The Planner & Skills (v4.1)
1.  Build `PlannerAgent`.
2.  Migrate monolithic prompts and tools to ADK Skills and implement `SkillToolset`.
3.  Transition from `SequentialAgent` to dynamic graph execution (e.g., LangGraph style).

---

## 📝 Success Criteria (Acceptance Tests)

1.  **Security**:
    *   User A logs in -> Uploads `secret.shp`.
    *   User B logs in -> Asks "List my files" -> Does NOT see `secret.shp`.
    *   User B tries "Analyze secret.shp" -> Access Denied.
2.  **Autonomy**:
    *   User asks: "Find a location for a new hospital > 2000m from factories." (No predefined tool for "hospital siting").
    *   Agent autonomously plans: `Query(factories)` -> `Buffer(2000m)` -> `Difference(All_Land, Buffer)` -> `Result`.
