# ArcPy Remote MCP Server and Codex Plugin Design

Date: 2026-07-10

## 1. Objective

Build two independent private Git repositories:

1. `zhouning/arcpy-mcp-server`: a Windows-only ArcPy MCP service that exposes a controlled ArcPy catalog over Streamable HTTP and provides secure artifact upload/download.
2. `zhouning/codex-arcpy-mcp-plugin`: an installable Codex marketplace repository for macOS that configures the remote MCP server and teaches Codex the required artifact and job workflow.

The primary client is Codex on macOS. It reaches the Windows machine over the existing LAN or VPN by direct IP.

## 2. Confirmed Deployment Values

| Item | Value |
|---|---|
| Windows service IP | `192.168.25.228` |
| LAN subnet | `192.168.25.0/24` |
| MCP HTTPS port | `8765` |
| MCP endpoint | `https://192.168.25.228:8765/mcp` |
| GitHub owner | `zhouning` |
| Server repository | `zhouning/arcpy-mcp-server` |
| Plugin repository | `zhouning/codex-arcpy-mcp-plugin` |
| Marketplace name | `zhouning-arcpy` |
| Plugin name | `arcpy-mcp` |
| ArcGIS Python | `D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe` |
| ArcGIS Pro | `3.7.1`, Advanced Named User |
| Artifact retention | 7 days by default |

The router must reserve `192.168.25.228` for the Windows machine before deployment. A changed IP requires a new TLS server certificate and a plugin endpoint update.

## 3. Existing Implementation Assessment

The unfinished reference implementation is in `subsystems/tool-mcp-servers/arcgis-mcp` in the current GIS Data Agent repository. It is useful as a capability inventory, but it is not a safe base for remote deployment because it:

- supports only local `stdio` transport;
- references obsolete ArcGIS Python environment paths;
- interpolates user values into generated Python source strings;
- has no authentication, TLS, artifact transfer, path isolation, persistent jobs, or recovery model;
- relies primarily on mocked subprocess tests rather than real ArcPy integration tests;
- calls an unavailable `arcpy.ia.SuperResolution` API;
- directly imports `arcgis.learn` model classes, which is slow and unnecessary for standard ArcGIS inference tools.

The two new repositories will be implemented independently. The old GIS Data Agent code remains unchanged and serves only as historical reference.

## 4. Scope

### 4.1 Included

- Streamable HTTP MCP over HTTPS.
- Static Bearer Token authentication for a single user.
- Short-lived signed artifact upload and download URLs.
- A persistent single-worker ArcPy execution queue.
- A discoverable, explicitly allowlisted ArcPy tool catalog.
- Common vector, raster, data inspection, map export, and deep-learning inference operations.
- Strict service workspace isolation.
- Login-triggered Windows Scheduled Task startup under the ArcGIS Named User account.
- A private GitHub Codex marketplace and plugin for macOS.
- macOS Keychain storage for the Bearer Token.
- Unit, protocol, security, ArcPy integration, failure-recovery, and plugin validation tests.

### 4.2 Excluded

- Arbitrary Python or ArcPy code execution.
- Arbitrary ArcPy module or function names supplied by clients.
- Access to arbitrary Windows paths, UNC paths, or symlinks.
- Public internet exposure.
- Multi-user tenancy, OAuth, roles, or per-user workspaces.
- Parallel ArcPy workers in the first release.
- CPU-based deep-learning model training.
- Automatic migration or modification of the existing GIS Data Agent implementation.

## 5. Repository Layout

Local independent checkouts will be created under `D:\adk\standalone\`. Each checkout has its own `.git` directory and remote private GitHub repository. The parent repository will ignore `standalone/` so the independent repositories are not accidentally staged into the GIS Data Agent repository.

### 5.1 Server Repository

```text
arcpy-mcp-server/
|- pyproject.toml
|- README.md
|- .env.example
|- src/arcpy_mcp_server/
|  |- app.py
|  |- config.py
|  |- auth.py
|  |- artifacts.py
|  |- jobs.py
|  |- catalog.py
|  |- worker_supervisor.py
|  |- worker_protocol.py
|  `- worker/
|     |- main.py
|     |- executor.py
|     |- validation.py
|     `- tools/
|- config/tool_catalog.yaml
|- scripts/
|  |- bootstrap.ps1
|  |- bootstrap_tls.ps1
|  |- install_scheduled_task.ps1
|  |- uninstall_scheduled_task.ps1
|  |- start.ps1
|  |- stop.ps1
|  `- status.ps1
`- tests/
```

### 5.2 Plugin Marketplace Repository

```text
codex-arcpy-mcp-plugin/
|- .agents/plugins/marketplace.json
|- plugins/arcpy-mcp/
|  |- .codex-plugin/plugin.json
|  |- .mcp.json
|  |- skills/arcpy-mcp/SKILL.md
|  |- scripts/configure-macos.sh
|  |- scripts/verify-connection.sh
|  `- assets/arcpy-mcp-ca.crt
`- README.md
```

The plugin contains the public CA certificate only. The CA private key, server private key, Bearer Token, and artifact signing key never enter either Git repository.

## 6. System Architecture

```text
macOS Codex
  |  MCP over HTTPS + Bearer Token
  v
Windows Gateway
  |- Streamable HTTP MCP endpoint
  |- Artifact HTTP endpoints
  |- Authentication and signed URLs
  |- SQLite job and artifact database
  |- Workspace manager
  `- Worker supervisor
          | JSON Lines over stdin/stdout
          v
     Persistent ArcPy Worker
     ArcGIS Pro default Python environment
```

### 6.1 Gateway Process

The gateway runs in a project-owned Python virtual environment. It owns all non-Esri dependencies, including FastMCP, HTTP serving, validation, SQLite access, TLS handling, and test tooling. No FastMCP or web-server packages are installed into the ArcGIS Pro Python environment.

The gateway:

- authenticates MCP requests;
- creates signed artifact transfer URLs;
- validates all client input before it reaches ArcPy;
- persists jobs and artifacts in SQLite WAL mode;
- serializes ArcPy execution through one worker;
- captures progress, warnings, errors, and audit events;
- restarts a worker after a crash, cancellation, or timeout.

### 6.2 ArcPy Worker

The worker is launched with the exact ArcGIS Pro default Python executable. It imports ArcPy once, reports environment capabilities to the supervisor, and processes one JSON Lines request at a time.

Worker stdout is reserved for protocol messages. Diagnostic logs use stderr. Requests contain a catalog tool ID, validated structured parameters, artifact-resolved workspace paths, job ID, and deadline. Responses contain status, ArcPy messages, structured result metadata, and output file declarations.

The worker never accepts Python source, import paths, arbitrary function names, absolute client paths, or shell commands.

Cancellation and hard timeout are implemented by terminating the worker process. The supervisor removes incomplete outputs, marks the job, launches a new worker, and waits for a successful capability handshake before accepting another task.

### 6.3 ArcPy Environment Decision

The service uses the ArcGIS Pro default environment because it contains the complete Esri deep-learning stack:

- PyTorch `2.9.1`;
- torchvision `0.25.0`;
- fastai `1.0.63`;
- Esri Deep Learning Essentials for ArcGIS Pro 3.7;
- CUDA 12.9-compatible packages.

The machine currently exposes no usable NVIDIA CUDA device, so deep-learning inference runs in CPU mode. The worker uses standard `arcpy.ia` geoprocessing tools rather than importing the complete `arcgis.learn` namespace.

## 7. MCP Surface

### 7.1 Stable Control Tools

Artifact tools:

- `create_upload`
- `get_upload_status`
- `renew_upload`
- `complete_upload`
- `list_artifacts`
- `create_download`
- `delete_artifact`

Job tools:

- `submit_job`
- `get_job`
- `list_jobs`
- `cancel_job`
- `get_job_log`

Catalog and health tools:

- `get_capabilities`
- `search_tools`
- `describe_tool`
- `health_check`

### 7.2 Dedicated Common Tools

Frequently used operations are also registered as dedicated MCP tools for better Codex ergonomics. Each dedicated tool validates a typed request and submits the same internal asynchronous job used by `submit_job`.

Initial dedicated tools cover:

- dataset inspection;
- buffer;
- clip;
- project;
- dissolve;
- intersect;
- spatial join;
- check geometry;
- repair geometry;
- raster clip;
- raster projection;
- slope;
- zonal statistics;
- map layout export;
- deep-learning object detection;
- deep-learning pixel classification;
- deep-learning object classification;
- deep-learning change detection.

### 7.3 Tool Catalog

`config/tool_catalog.yaml` is the only authority for executable operations. Each entry defines:

- stable tool ID and display name;
- ArcPy callable selected by server-owned code;
- category and description;
- JSON Schema for parameters;
- artifact input and output roles;
- required ArcGIS license and extensions;
- default and maximum timeout;
- risk classification;
- CPU/GPU eligibility;
- output collection rules.

The first catalog includes:

- data inspection: describe, fields, record count, extent, spatial reference, and data type;
- vector: Buffer, Clip, Dissolve, Intersect, Union, Spatial Join, Project, Merge, Check Geometry, and Repair Geometry;
- raster: Clip, Project Raster, Resample, Extract by Mask, Slope, Zonal Statistics, and Mosaic;
- map: APRX inspection and layout export to PDF or PNG;
- deep learning: Detect Objects, Classify Pixels, Classify Objects, Detect Change, Translate Pixels, and Export Training Data.

`TrainDeepLearningModel` is excluded while no GPU is available. It can enter the catalog only when startup detects a GPU and configuration explicitly enables training. The invalid legacy Super Resolution wrapper is not migrated.

## 8. Artifact Model

Clients reference artifacts by opaque ID, never by a Windows path.

The default service data root is `%LOCALAPPDATA%\ArcPyMCP\data`. Each job receives isolated `input`, `work`, `output`, and `logs` directories beneath that root.

### 8.1 Upload

1. Codex calls `create_upload` with logical name, expected size, SHA-256, and media type.
2. The server creates an incomplete artifact and returns an upload session ID, current byte offset, and short-lived signed HTTPS URL.
3. Codex uses `curl` to stream the macOS file. The HTTP endpoint accepts sequential ranged writes and returns the committed byte offset.
4. After a network interruption, Codex calls `get_upload_status`, resumes at the server-confirmed offset, and calls `renew_upload` if the signed URL has expired. Existing committed bytes remain available until incomplete-upload cleanup.
5. The server writes to a temporary file and enforces configured size limits while streaming.
6. Codex calls `complete_upload`; the server verifies total size and SHA-256 before making the artifact usable.

Single files upload directly. Shapefiles, FileGDB directories, APRX resource bundles, and other multi-file datasets upload as ZIP archives.

Default limits are 20 GiB per uploaded archive or file, 50 GiB expanded ZIP size, 100,000 ZIP entries, and 16 directory levels. These limits are configurable. Incomplete upload sessions expire after 24 hours.

ZIP extraction rejects path traversal, absolute paths, UNC paths, drive prefixes, symlinks, excessive file counts, excessive nesting, and excessive expanded size.

### 8.2 Download

The gateway registers successful worker outputs as artifacts. Single-file outputs download directly. Directories and multi-file formats are packaged as ZIP. `create_download` returns a signed URL that expires after 10 minutes. Downloads support HTTP Range so `curl -C -` can resume an interrupted transfer. If the URL expires, Codex requests a new URL without recreating the artifact.

The macOS workflow verifies the downloaded SHA-256 before extraction or use.

## 9. Job Model

```text
queued -> starting -> running -> succeeded
                            |-> failed
                            |-> timed_out
                            `-> cancelling -> cancelled
```

Additional terminal state `interrupted` is used when the Windows process or machine stops while a job is running.

SQLite stores jobs, artifacts, job-artifact links, and append-only job events. WAL mode is used so health checks and status polling do not block the worker transaction path.

After restart:

- queued jobs remain queued;
- running, starting, or cancelling jobs become interrupted;
- interrupted jobs are not automatically retried because ArcPy operations may have side effects inside their isolated job directory;
- completed artifacts remain available until retention cleanup.

The default retention period is seven days. Cleanup never removes an artifact referenced by an active job. Users may explicitly delete completed artifacts earlier.

## 10. Error Handling

The API returns stable machine-readable codes and a sanitized human-readable message. Initial codes include:

- `AUTH_FAILED`
- `INVALID_REQUEST`
- `INVALID_ARTIFACT`
- `ARTIFACT_HASH_MISMATCH`
- `PATH_REJECTED`
- `TOOL_NOT_ALLOWED`
- `LICENSE_UNAVAILABLE`
- `EXTENSION_UNAVAILABLE`
- `PARAMETER_VALIDATION_FAILED`
- `ARCPY_EXECUTION_FAILED`
- `JOB_TIMEOUT`
- `JOB_CANCELLED`
- `WORKER_CRASHED`
- `WORKER_UNAVAILABLE`

ArcPy messages are retained in structured job events. Responses omit secrets, signed URLs from prior events, server filesystem roots, and raw environment variables.

## 11. Network and Security

### 11.1 TLS

The server uses a private local certificate authority. The server certificate contains IP SAN `192.168.25.228`. The plugin repository distributes the CA public certificate for macOS trust installation.

TLS private material is stored outside Git under the current Windows user's protected application data directory.

### 11.2 Authentication

All MCP calls require a static Bearer Token. The server reads the token from its process environment and uses constant-time comparison. The token is not stored in SQLite or logs.

Artifact URLs use a separate HMAC signing key and include artifact ID, operation, and expiry. Their default lifetime is 10 minutes.

### 11.3 Firewall

The bootstrap script creates a Windows Firewall inbound rule for TCP port `8765`, Private network profile, and remote subnet `192.168.25.0/24`. Public-profile access remains blocked.

### 11.4 Workspace Isolation

The gateway resolves every artifact path itself. It rejects absolute paths, UNC paths, drive-prefixed paths, traversal segments, alternate data streams, and symlinks. ArcPy output parameters are rewritten into the current job output directory.

## 12. Windows Startup and Operations

The server runs as the current Windows user through Task Scheduler and starts at user login. This preserves access to the ArcGIS Named User license and user profile.

The startup sequence is:

1. load environment configuration and secrets;
2. validate TLS files and the workspace;
3. open and migrate SQLite;
4. launch the ArcPy worker;
5. validate ArcPy import, product license, extensions, and writable scratch workspace;
6. expose the HTTPS service;
7. mark stale jobs interrupted.

If ArcPy health checks fail, the HTTP service remains available for diagnostics and artifact administration, but new ArcPy jobs are rejected.

Operational scripts install, remove, start, stop, and inspect the scheduled task. Logs rotate by size and age.

## 13. Codex Plugin Design

The plugin manifest references `.mcp.json`. The MCP entry uses type `http`, URL `https://192.168.25.228:8765/mcp`, and Bearer Token environment variable `ARCPY_MCP_TOKEN`.

The plugin skill instructs Codex to:

1. check server and ArcPy health;
2. hash local input files;
3. create uploads and use `curl` for streaming transfer, offset-based resume, and URL renewal;
4. inspect uploaded datasets before selecting a processing tool;
5. search and describe the allowlisted tool catalog;
6. submit and poll asynchronous jobs;
7. download and verify result artifacts;
8. warn that CPU deep-learning inference can be slow;
9. avoid exposing tokens, signed URLs, or local CA private material.

`configure-macos.sh`:

- adds the private GitHub marketplace;
- installs `arcpy-mcp@zhouning-arcpy`;
- imports the CA public certificate into the user's macOS Keychain after confirmation;
- stores the Bearer Token as a generic Keychain password;
- loads `ARCPY_MCP_TOKEN` into the current Codex CLI/app user session;
- verifies TLS and MCP health.

The plugin never accepts or generates Windows absolute paths. It uses artifact IDs and logical output names exclusively.

## 14. Testing Strategy

### 14.1 Server Unit Tests

- Bearer Token validation and constant-time comparison behavior.
- Signed URL generation, expiry, operation binding, and tamper rejection.
- Path and ZIP traversal defenses.
- Upload size and SHA-256 enforcement.
- Tool catalog schema and allowlist enforcement.
- Job state transitions and retention logic.
- Worker protocol parsing and malformed-message handling.

### 14.2 Protocol and Integration Tests

- Full MCP flow with a fake worker.
- Streaming upload and download.
- Interrupted upload and download resume with signed URL renewal.
- Queue serialization.
- Cancellation, timeout, worker crash, and restart recovery.
- Gateway restart and interrupted-job reconciliation.

### 14.3 Real ArcPy Tests

Tests run with the ArcGIS Pro default Python and create disposable data inside the test workspace:

- FileGDB and feature-class creation;
- vector buffer and projection;
- geometry checking;
- a small raster analysis;
- APRX or layout export when a fixture is available;
- extension and license reporting.

Deep-learning tool discovery and parameter validation are mandatory. A real inference smoke test is mandatory only when a compatible ArcGIS Pro 3.7.1 `.dlpk` or `.emd` test model is available. Without a model, the test suite must report the inference test as skipped and must not claim deep-learning end-to-end success.

### 14.4 Plugin Tests

- plugin manifest validation;
- marketplace validation;
- MCP companion configuration validation;
- shell script syntax and secret redaction tests;
- Codex plugin installation from the private marketplace;
- macOS TLS, health, upload, job, and download smoke test.

## 15. Acceptance Criteria

The implementation is complete when:

1. Both private GitHub repositories exist and their default branches are pushed.
2. The Windows gateway starts through the user Scheduled Task and passes health checks.
3. No server dependency has been installed into the ArcGIS Pro Python environment.
4. The macOS Codex plugin installs from `zhouning/codex-arcpy-mcp-plugin`.
5. Codex connects to `https://192.168.25.228:8765/mcp` using `ARCPY_MCP_TOKEN`.
6. A macOS file can be uploaded, processed by a real ArcPy vector tool, downloaded, and hash-verified.
7. A real ArcPy raster job completes through the same workflow.
8. A running job can be cancelled and the worker returns to healthy state.
9. Path traversal, unauthorized tools, invalid signatures, and unauthenticated requests are rejected by automated tests.
10. Deep-learning tools are discoverable and CPU inference completes when a compatible test model is supplied; otherwise the missing runtime inference evidence is explicitly reported.

## 16. Key Risks and Mitigations

| Risk | Mitigation |
|---|---|
| ArcGIS Named User license unavailable | Run under the logged-in user and reject jobs while health is degraded. |
| Direct IP changes | Reserve `192.168.25.228`; regenerate TLS and update plugin if it changes. |
| ArcPy hangs | Per-tool hard deadlines; terminate and recreate the worker. |
| CPU DL inference is very slow | Long async deadlines, progress messages, explicit CPU warnings, no CPU training. |
| Malicious archives | Stream limits, hash verification, safe extraction, file-count and expanded-size limits. |
| Accidental host filesystem access | Artifact IDs, server-resolved paths, isolated job directories, absolute-path rejection. |
| Secret disclosure | Keychain/environment storage, redacted logs, separate signing key, no secrets in Git. |
| ArcGIS update changes the default environment | Startup capability handshake and pinned compatibility tests before accepting jobs. |

## 17. Implementation Order

1. Create the independent private repositories and local checkouts.
2. Implement gateway configuration, TLS, authentication, artifacts, and SQLite jobs.
3. Implement worker protocol, supervisor, health checks, and recovery.
4. Implement the catalog and core real ArcPy tools.
5. Add raster, map, and deep-learning tools.
6. Build the Codex marketplace, plugin, skill, and macOS scripts.
7. Run Windows tests and real ArcPy smoke tests.
8. Install on macOS and run the end-to-end acceptance workflow.
