# ArcPy MCP End-to-End Integration Design

**Date:** 2026-07-11

**Status:** Approved

## Objective

Connect GIS Data Agent to the private remote ArcPy MCP service on both macOS and Docker. The integration must let the `general`, `planner`, and `governance` pipelines complete the full workflow from a user-local GIS dataset to a verified local result: health and capability checks, upload, inspection, tool selection, job submission, polling, download, checksum verification, catalog lineage, and map loading.

The integration includes regular vector, raster, geometry, map export, and CPU deep-learning inference tools. Deep-learning submission requires explicit user confirmation because it can be long-running.

## Confirmed Existing Failures

The ArcPy service itself is healthy. A live health check reported ArcGIS Pro 3.7.1, an Advanced license, available Spatial Analyst and Image Analyst extensions, and CPU deep-learning tools.

The incomplete GIS Data Agent integration has multiple independent failures:

1. `data_agent/mcp_servers.yaml` configures `arcgis-pro-tools` as a Windows-local `stdio` process. A GIS Data Agent process running on macOS or in a Linux container cannot launch that Windows executable.
2. The active route module is `data_agent/api/mcp_routes.py`, but the frontend calls `POST /api/mcp/servers/test` while the active module registers `POST /api/mcp/test`.
3. The active create route imports the nonexistent `MCPServerConfig`; the actual class is `McpServerConfig`.
4. The active test route passes a raw dictionary to `McpHubManager.test_connection()`, which expects `McpServerConfig`.
5. Corrected versions of parts of this logic remain as dead code in `data_agent/frontend_api.py`, so tests aimed at the old functions did not protect the active routes after the route extraction.
6. The current HTTP MCP configuration can accept static headers but cannot resolve a bearer token from an environment variable or Docker secret file.
7. The current ADK HTTP client uses the default public trust store. A live Python probe failed with `CERTIFICATE_VERIFY_FAILED`; the same probe succeeded with status 200 when the ArcPy private CA was supplied explicitly.
8. Startup marks the MCP Hub as started even after timeout or failure, preventing an automatic retry in the same process.
9. Raw MCP tools expose artifact IDs, signed URLs, upload offsets, and job polling details directly to the model. That is insufficient for a reliable local-file-to-local-result workflow.

## Scope

### In Scope

- Repair the active MCP REST route contract and its tests.
- Add environment-backed bearer authentication and server-specific CA trust.
- Support macOS environment/Keychain injection and Docker secret-file injection.
- Add a system-managed remote ArcPy MCP server configuration.
- Add an ArcPy-specific client and high-level ADK toolset.
- Support artifact upload, resumability, inspection, job polling, download, safe extraction, and cleanup.
- Expose ArcPy tools to `general`, `planner`, and `governance` pipelines.
- Add explicit confirmation for CPU deep-learning inference.
- Return results in the existing GIS Data Agent output, lineage, and map-control conventions.
- Preserve graceful degradation when ArcPy is unavailable.

### Out of Scope

- ArcPy or deep-learning model training.
- Arbitrary Python, shell execution, arbitrary ArcPy callables, or non-allowlisted remote tool IDs.
- Sending Windows paths, UNC paths, parent traversal, or symlink targets to the ArcPy service.
- Making the ArcPy private CA a global Python trust store.
- Replacing the existing open-source GeoPandas, Rasterio, or QGIS tools.
- Refactoring unrelated frontend API route modules.

## Chosen Architecture

Use the existing MCP Hub for generic server lifecycle and visibility, with a dedicated ArcPy adapter for artifact and job orchestration.

### 1. Secure MCP Configuration

Extend `McpServerConfig` with secret and trust references rather than secret values:

- `bearer_token_env_var`
- `bearer_token_file_env_var`
- `ca_bundle_env_var`
- `system_managed`
- `expose_raw_tools`

Resolution precedence is token file, then token environment variable. Configuration persistence stores only reference names. API responses and logs never contain resolved values.

For Streamable HTTP, construct a server-specific `httpx.AsyncClient` through ADK's `httpx_client_factory`. Its `verify` value is the resolved private CA path. This avoids setting `SSL_CERT_FILE`, which could break unrelated public HTTPS clients.

### 2. System-Managed ArcPy Server

When `ARCPY_MCP_ENABLED` is true, register a runtime server named `arcpy-remote` from environment configuration. The environment-managed definition takes precedence over database and YAML rows of the same name.

The old Windows `arcgis-pro-tools` seed is removed from new installations. If an existing database contains that legacy `stdio` row, it remains visible as disabled legacy configuration and is never automatically connected when `arcpy-remote` is enabled.

The runtime ArcPy server is shared, system-managed, assigned to `general`, `planner`, and `governance`, and has `expose_raw_tools=false`. Agents receive the high-level ArcPy toolset rather than the protocol-level tools.

### 3. ArcPy MCP Client

Add `data_agent/arcpy_mcp_client.py` with one responsibility: implement the ArcPy MCP service contract without exposing transport details to agents.

The client provides:

- connection, retry, and close lifecycle;
- `health_check` and `get_capabilities` with short-lived caches;
- allowlisted MCP tool invocation;
- local file validation and user-sandbox enforcement;
- shapefile and file-geodatabase ZIP packaging;
- size and SHA-256 calculation;
- resumable artifact upload and completion verification;
- dataset inspection and artifact-relative path extraction;
- job polling and cancellation;
- sanitized failure-log retrieval;
- resumable result download and SHA-256 verification;
- safe ZIP extraction that rejects absolute and escaping paths;
- remote temporary artifact cleanup.

Bearer tokens, signed URLs, and server-side paths remain local variables inside this client and are never returned to the model.

### 4. ArcPy ADK Toolset

Add `data_agent/toolsets/arcpy_mcp_toolset.py`. It exposes high-level tools that accept user-local paths and domain parameters, then delegate the entire protocol workflow to `ArcPyMcpClient`.

The initial tool surface is:

- service status and dataset inspection;
- buffer, feature clip, raster clip, dissolve, intersect, and spatial join;
- feature and raster projection;
- geometry check and repair;
- slope and zonal statistics;
- ArcGIS Pro layout export;
- object detection, pixel classification, object classification, and change detection;
- allowlisted catalog-tool execution through `search_tools`, `describe_tool`, and `submit_job` when no dedicated wrapper exists.

Register independent `ArcPyMcpToolset` instances with all three pipelines to respect ADK ownership rules. Tool descriptions identify supported input types and required parameters. Deep-learning wrappers integrate with the existing human-in-the-loop approval mechanism before job submission.

### 5. MCP Hub and REST Repair

Keep `data_agent/api/mcp_routes.py` as the only active REST implementation. Repair it from the known-correct behavior that remains in `frontend_api.py`, then move route tests to the active module.

The canonical connection-test endpoint is `POST /api/mcp/servers/test`, matching the frontend. Server creation, update, delete, toggle, reconnect, status, and tool listing operate on `McpServerConfig` consistently.

System-managed servers cannot be deleted or have connection/security fields modified through the UI. They may expose a reconnect operation and sanitized status.

Startup reports success only after enabled servers complete their first connection attempt. Failed servers remain retryable with bounded exponential backoff. App shutdown closes Hub and ArcPy sessions.

## End-to-End Data Flow

1. The intent router selects an Agent pipeline. The LLM selects a high-level ArcPy tool based on its schema and description.
2. The ArcPy tool verifies service health. Spatial Analyst, Image Analyst, and deep-learning tasks also verify capabilities.
3. The requested local input is resolved through the existing user file sandbox. Absolute paths outside the sandbox, symlinks escaping it, and traversal are rejected.
4. Multi-file datasets are packaged as ZIP. Single raster, GeoPackage, PDF, project, DLPK, or EMD inputs remain single files.
5. The client computes exact byte size and lowercase SHA-256, calls `create_upload`, transfers bytes to the signed URL without the bearer token, and calls `complete_upload`.
6. Interrupted uploads use `get_upload_status`; expired signed URLs use `renew_upload`. The artifact is usable only after the server reports `ready` with the matching verified hash.
7. Every new GIS input is inspected through `inspect_dataset`. The inspection job is polled until a terminal state and supplies the approved artifact-relative path.
8. A dedicated operation is preferred. Otherwise the client searches the allowlist, describes the selected schema, validates parameters, and submits the catalog job.
9. Jobs are polled after 2, 5, 10, and then every 20 seconds or less. Terminal states are `succeeded`, `failed`, `timed_out`, `cancelled`, and `interrupted`.
10. Failed jobs retrieve the sanitized append-only job log and return a stable error code plus final ArcPy messages.
11. Successful jobs yield result artifact IDs. Each result receives a signed download URL, is downloaded resumably, and is verified against `actual_sha256`.
12. ZIP extraction remains inside the current user's workspace. Verified outputs are registered with the data catalog and lineage system and return optional `layer_control` metadata for map loading.
13. Temporary input artifacts are deleted after verified completion. Result artifacts are deleted only after their local copies pass checksum verification. Failure cleanup is best-effort and never hides the original error.

## Result Contract

Each high-level ArcPy tool returns a consistent JSON-serializable structure:

- `status`
- `operation`
- `message`
- `local_outputs`
- `dataset_summary`
- `arcgis_product`
- `arcgis_version`
- `duration_seconds`
- `lineage`
- `layer_control`, when the result is map-loadable
- `error_code` and sanitized `arcpy_messages`, on failure

Artifact IDs may appear in internal diagnostics but are not part of the normal LLM-facing result. Signed URLs and resolved credentials never appear.

## Security Model

- Never persist or print `ARCPY_MCP_TOKEN`.
- Never place the token value in a command argument.
- Prefer `ARCPY_MCP_TOKEN_FILE` in Docker; read it at runtime from a read-only secret mount.
- Validate that the CA bundle exists and does not contain a private key marker.
- Validate the ArcPy URL scheme and restrict system-managed configuration changes to deployment configuration.
- Allow only the remote MCP service's exposed and described tool IDs.
- Reject arbitrary Python, shell, ArcPy callable, drive, UNC, parent traversal, and escaping archive paths.
- Do not pass bearer authentication to signed upload or download URLs.
- Redact authorization headers, token values, signed URLs, and sensitive query parameters from exceptions and logs.
- Keep per-user local inputs and outputs inside the existing sandbox and propagate the current user context into tool execution.

## Configuration and Deployment

### Common Environment

```text
ARCPY_MCP_ENABLED=true
ARCPY_MCP_URL=https://192.168.25.228:8765/mcp
ARCPY_MCP_CA_BUNDLE=/run/secrets/arcpy_mcp_ca.crt
ARCPY_MCP_TOKEN_FILE=/run/secrets/arcpy_mcp_token
ARCPY_MCP_CONNECT_TIMEOUT=10
ARCPY_MCP_JOB_TIMEOUT=1800
ARCPY_MCP_DL_JOB_TIMEOUT=7200
ARCPY_MCP_UPLOAD_TIMEOUT=600
ARCPY_MCP_DOWNLOAD_TIMEOUT=600
```

Only one token source is required. If both are present, `ARCPY_MCP_TOKEN_FILE` wins.

### macOS

The existing Keychain/launch environment may inject `ARCPY_MCP_TOKEN`. The application receives an explicit CA path such as `/Users/zhouning/.config/gis-data-agent/arcpy-mcp-ca.crt` from its environment. The code does not depend on the Codex plugin cache path.

### Docker Compose

Mount the token as a Docker secret and the CA as a read-only file. Set the ArcPy URL and timeout values through environment configuration. Add the ArcPy host to `NO_PROXY` when the deployment network requires direct private-address routing.

The application remains startable when ArcPy configuration is absent or the endpoint is unavailable.

## Error Handling

Expose stable errors with sanitized detail:

- `ARCPY_MCP_DISABLED`
- `ARCPY_MCP_URL_MISSING`
- `ARCPY_MCP_TOKEN_MISSING`
- `ARCPY_MCP_CA_MISSING`
- `ARCPY_MCP_TLS_FAILED`
- `ARCPY_MCP_AUTH_FAILED`
- `ARCPY_MCP_UNREACHABLE`
- `ARCPY_WORKER_UNAVAILABLE`
- `ARCPY_EXTENSION_UNAVAILABLE`
- `ARCPY_UPLOAD_FAILED`
- `ARCPY_UPLOAD_CHECKSUM_MISMATCH`
- `ARCPY_DATASET_INSPECTION_FAILED`
- `ARCPY_TOOL_NOT_ALLOWED`
- `ARCPY_JOB_FAILED`
- `ARCPY_JOB_TIMED_OUT`
- `ARCPY_JOB_CANCELLED`
- `ARCPY_DOWNLOAD_FAILED`
- `ARCPY_DOWNLOAD_CHECKSUM_MISMATCH`
- `ARCPY_UNSAFE_ARCHIVE`

ArcPy failures do not stop the other GIS toolsets or Agent pipelines. When unavailable, ArcPy tools return a clear degraded status and existing open-source tools remain usable.

## Testing Strategy

Implementation follows test-driven development. Each behavior receives a failing test before production code changes.

### Unit and Contract Tests

- Active route registration and frontend path agreement.
- Correct `McpServerConfig` construction in test/create/update routes.
- Environment and secret-file resolution without secret serialization.
- Per-server CA client factory and missing/invalid CA behavior.
- System-managed config precedence over stale database/YAML rows.
- Retryable startup after connection failure.
- File sandbox validation and multi-file packaging.
- Upload offset resume, renewal, completion, and checksum mismatch.
- Inspection and artifact-relative path handling.
- Poll schedule and every terminal job state.
- Failure log sanitization.
- Download resume, checksum verification, and safe extraction.
- High-level result contract, lineage, and layer control.
- Tool visibility in `general`, `planner`, and `governance`.
- Mandatory confirmation for all four deep-learning tools.

### Integration Tests

Use a local fake Streamable HTTP MCP server to exercise initialization, bearer authentication, tool discovery, artifact calls, jobs, failures, and downloads without using secrets or the real service.

### Live macOS Smoke Test

Use the real ArcPy MCP service to:

1. perform health and capability checks;
2. discover the remote allowlisted tools;
3. upload and inspect a small deterministic GIS fixture;
4. execute a lightweight buffer operation;
5. poll to `succeeded`;
6. download and verify the result;
7. confirm the result is returned inside the current user's sandbox.

### Docker Smoke Test

Start the app with a Docker secret and read-only CA mount. Verify health and tool discovery, then run the same lightweight buffer operation when Docker and the private ArcPy host are reachable from the container.

### Deep-Learning Validation

Verify live capabilities and tool exposure. If a compatible ArcGIS Pro 3.7.1 DLPK or EMD is available, run a minimal inference after confirmation. If no model artifact exists, complete the invocation, confirmation, polling, and result-path contract against the fake MCP server and record the missing live model as an external acceptance dependency.

### Regression Verification

Run focused MCP Hub, active MCP route, ArcPy adapter, Agent registration, health, and frontend contract tests, followed by the relevant backend suite and frontend production build.

## Acceptance Criteria

1. The MCP management UI can test and show the system-managed ArcPy server without route or configuration errors.
2. The server connects on macOS and in Docker using the same application code and different secret injection methods.
3. All three requested Agent pipelines can discover the high-level ArcPy tools.
4. A user can request an ArcPy buffer analysis in chat and receive a verified local output without handling artifact IDs or signed URLs.
5. Map-loadable outputs can enter the existing data catalog and map display flow with lineage metadata.
6. ArcPy service or worker failure degrades cleanly without breaking non-ArcPy GIS tools.
7. Deep-learning submission requires explicit confirmation and uses the longer configured timeout.
8. No token, authorization header, signed URL, or unsafe server/local path appears in persistent storage, frontend responses, or logs.
9. Focused tests and frontend build pass, and live smoke verification reaches a terminal `succeeded` status before success is reported.
