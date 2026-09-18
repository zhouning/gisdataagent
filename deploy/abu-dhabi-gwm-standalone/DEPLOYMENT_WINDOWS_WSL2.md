# Windows Docker Desktop + WSL2 Deployment

## Prerequisites

1. Windows x86-64.
2. Docker Desktop configured to use WSL2 and Linux containers.
3. At least 2 CPU, 2 GB memory, and 50 GB available on the result drive.
4. The offline image tar and its SHA-256 checksum.

## Verify the delivery checksum

```powershell
Get-FileHash .\abu-dhabi-gwm-api_1.0.0-model-r1-linux-amd64.tar -Algorithm SHA256
```

Compare it with the delivered `.sha256` file before loading the image.

## Load the image

```powershell
docker load -i .\abu-dhabi-gwm-api_1.0.0-model-r1-linux-amd64.tar
```

## Start the service

```powershell
.\scripts\run-windows.ps1 `
  -ApiToken "replace-with-a-random-token-of-at-least-32-characters" `
  -RunsDirectory "D:\AbuDhabiGWM\runs"
```

The startup script binds to `127.0.0.1` by default. This is the recommended
setting when the calling application runs on the same Windows machine. For a
cross-machine client, use `-BindAddress "0.0.0.0"` only behind a TLS reverse
proxy and a firewall rule restricted to the approved caller; bearer tokens
must not cross an untrusted plain-HTTP network.

The script does not remove or replace an existing container. If a container
named `abu-dhabi-gwm` already exists, it stops and asks the operator to inspect
it manually.

## Validate readiness

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health/live
Invoke-RestMethod http://127.0.0.1:8080/health/ready
```

Run the API examples:

```powershell
.\scripts\api-examples.ps1 -ApiToken "the-same-token"
```

For a release-level check of authentication, model identity, persistent
results, time slices, and the known `100 mm / 24 h` output, run:

```powershell
.\scripts\smoke-test.ps1 -ApiToken "the-same-token"
```

The smoke test uses a fixed idempotency key. Re-running it reads back the same
acceptance result instead of creating duplicate result directories.

## Result storage

Every successful call creates an immutable directory under:

```text
D:\AbuDhabiGWM\runs\trained-gwm-<UTC>-<id>\
├── run.json
└── surface_depth_labels_250m.npz
```

No automatic cleanup or deletion API is included. Operators must monitor free
disk capacity. When remaining free space falls below `GWM_MIN_FREE_DISK_GB`,
the service rejects new rollouts with HTTP 507 but keeps all existing results.

## Upgrade and rollback

1. Keep the previous image and its model release tag.
2. Stop the current container.
3. Start the new image with the same result-directory bind mount.
4. Call `/health/ready` and run a known `100 mm / 24 h` acceptance request.
5. If validation fails, stop the new container and restart the previous tag.

Existing run directories are versioned records and remain readable from the
host even if a later image cannot interpret them.
