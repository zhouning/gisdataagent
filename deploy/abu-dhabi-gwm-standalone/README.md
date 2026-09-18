# Abu Dhabi Urban Flood GWM Standalone API

This directory packages Phase 4 of the Abu Dhabi urban-flood world model as a
database-free, offline `linux/amd64` container for Docker Desktop + WSL2.

The service contains no frontend, Chainlit runtime, LLM, PostgreSQL dependency,
or automatic result deletion. The frozen model is read-only inside the image;
each rollout is persisted below `/data/runs`.

## Runtime contract

- Image platform: `linux/amd64`
- Port: `8080`
- Host bind address: `127.0.0.1` by default
- Authentication: `Authorization: Bearer <token>`
- Model directory: `/opt/gwm/model` (read-only)
- Result directory: `/data/runs` (persistent bind mount)
- GPU: not required
- Recommended minimum: 2 CPU, 2 GB RAM, 50 GB result disk
- Automatic cleanup: disabled by design

Keep the default loopback bind when the calling application is on the same
Windows host. If the API must be called from another machine, explicitly bind
to a trusted interface and put TLS termination plus firewall access control in
front of the container; do not send the bearer token over an untrusted plain
HTTP network.

## Build the compact model bundle

The private model bundle is deliberately ignored by Git. Build it from the
validated local assets before building the image:

```bash
python scripts/build_model_bundle.py \
  --model-root /path/to/customer_five_year_event_gwm_20260914_r1 \
  --label-root /path/to/customer_city_swmm_2d_coupled_labels_20260914_r1 \
  --observation-root /path/to/customer_sentinel2_observed_flood_202404_r1 \
  --output-dir model_bundle
```

The builder validates the frozen-model split, external-holdout policy,
coefficient/grid compatibility, forcing duration, and source checksums. It
extracts only inference assets; raw five-year training labels are not copied.

## Build and test the image

```bash
./scripts/build-image.sh
```

The produced tag is:

```text
abu-dhabi-gwm-api:1.0.0-model-r1-linux-amd64
```

Create the offline Windows delivery files after the image passes validation:

```bash
./scripts/package-release.sh
```

The generated `dist/` directory contains the image tar, SHA-256 checksum,
deployment guide, Compose template, OpenAPI contract, model manifest, startup
script, and smoke test. The directory is ignored by Git.

## API

Primary endpoint:

```http
POST /v1/rollouts
Authorization: Bearer <token>
Idempotency-Key: optional-unique-key
Content-Type: application/json

{
  "totalRainfallMm": 100,
  "durationHours": 24
}
```

See `openapi.yaml` for the complete contract. Swagger and ReDoc pages are
disabled; `/openapi.json` remains available as machine-readable JSON.

The `/api/abu-dhabi/flood/gwm/trained/...` compatibility routes in the same
contract preserve the response shape currently consumed by GIS Data Agent.

## Safety boundary

This is a frozen research emulator of 250 m physical-model labels. A changed
rainfall amount or duration is a sensitivity scenario, not a calibrated
arbitrary design hyetograph, historical replay, external validation result, or
engineering replacement for SWMM/ANUGA.
