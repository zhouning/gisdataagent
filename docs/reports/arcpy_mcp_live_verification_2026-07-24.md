# ArcPy MCP Live Verification

Date: 2026-07-24

## Outcome

The ArcPy MCP integration is not yet accepted as a successful live
end-to-end smoke. Local contract, regression, build, and security checks pass,
but the remote service does not complete dataset inspection for the smoke
fixture.

## Sanitized Live Evidence

- Gateway status: `healthy`
- ArcGIS version: `3.7.1`
- ArcGIS product: `ArcInfo` (Advanced)
- Worker processor: `CPU`
- Spatial Analyst: `Available`
- Image Analyst: `Available`
- macOS smoke terminal stage: `inspect.dataset`
- macOS smoke terminal status: `failed`
- Stable remote error: `WORKER_EXECUTION_FAILED`
- Local public error: `ARCPY_INSPECTION_FAILED`
- Compatible DLPK/EMD present: no
- Deep-learning readiness status: `live_model_artifact_missing`
- Deep-learning inference submitted: no

The current run reached the remote inspection stage, proving that the
application-side URL, credential, CA, upload, and LAN path were usable. It did
not reach buffer execution or verified result download, so no success claim is
made. The sanitized artifact count was unchanged after the failed run, so the
run did not add a remote artifact leak.

Earlier diagnostics reproduced the same inspection failure for GeoJSON,
GeoPackage, and FlatGeobuf inputs. A valid shapefile ZIP transferred fully but
was rejected during upload completion with only a generic service error. One
non-model diagnostic artifact remains on the service because its exact delete
request was refused. No broad deletion was attempted.

## Docker Status

The Docker smoke remains blocked before application startup. Docker Desktop
cannot bind-mount a process-substitution descriptor as a Compose secret. The
failed containers and network were cleaned up while volumes were retained. No
credential was persisted or passed as a regular container environment
variable.

## Acceptance Boundary

Live acceptance remains blocked until the service can inspect the tracked
fixture, run the buffer job to `succeeded`, and return a downloaded artifact
whose size and SHA-256 pass client verification. Docker acceptance additionally
requires stable host files for the read-only token and CA secrets.

This report intentionally omits credentials, signed URLs, artifact and job
identifiers, endpoint details, and server filesystem paths.
