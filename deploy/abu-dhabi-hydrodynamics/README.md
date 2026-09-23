# Abu Dhabi hydrodynamics reproducible runtime

This directory is the independent runtime package for the Abu Dhabi urban
stormwater model. It makes the numerical execution path reproducible without
putting customer data or platform-specific binaries into the Git repository.

The package has two deliberate delivery levels:

1. The public image builds the pinned EPA SWMM and ANUGA runtimes and runs
   synthetic smoke fixtures. Anyone can use it to verify that 1D, 2D and the
   adapter layer execute.
2. An authorized customer data bundle is mounted read-only at `/data/input`.
   The same image then runs the city-scale SWMM and ANUGA workflows using the
   files listed in `manifests/customer-data.example.json`.

LISFLOOD-FP is a separate optional image because the pinned BMI runtime is
GPL-3.0. Do not combine its binary into a product image without completing the
license review and source-offer obligations.

For the difference between source-rebuild, registry, offline-image and
customer-data delivery, see [DELIVERY.md](DELIVERY.md). The short version is:
the Dockerfile is sufficient for a reproducible rebuild, but a pre-built image
is recommended when another party must run without compiling or accessing
public package sources. The image still does not contain the customer model
data.

## Build and run the public smoke test

From the repository root:

```bash
docker build \
  -f deploy/abu-dhabi-hydrodynamics/Dockerfile \
  -t abu-dhabi-hydrodynamics:runtime-v1 .

docker run --rm \
  --read-only \
  --tmpfs /tmp:size=512m,mode=1777 \
  --tmpfs /data/runs:size=1g,mode=1777 \
  abu-dhabi-hydrodynamics:runtime-v1 --check --smoke
```

The smoke receipt must report `status=completed` for `epa_swmm`, `anuga_2d`,
and `epa_swmm_anuga_synchronous_coupling`. The coupled smoke exercises both
one-way overflow transfer and two-way exchange, advancing the native solvers
through two 300-second windows in each mode. It verifies that the receipt,
native SWW, maximum-depth GeoJSON and time-series manifest were created. It
uses only small synthetic fixtures; it is not a claim that the customer model
is calibrated or engineering-admitted.

## Build the optional LISFLOOD-FP image

```bash
docker build \
  -f deploy/abu-dhabi-hydrodynamics/Dockerfile.lisflood \
  -t abu-dhabi-lisflood-fp:5.9-bmi .

docker run --rm \
  --read-only \
  --tmpfs /tmp:size=256m,mode=1777 \
  abu-dhabi-lisflood-fp:5.9-bmi
```

The default command copies the immutable fixture into `/tmp/lisflood-smoke`,
runs the solver there, and verifies that non-empty `.mass` and `.max` outputs
were created. This keeps the image and mounted customer inputs read-only.

The image is pinned to LISFLOOD-FP BMI commit
`11f2a9214f80e1194bfaea23bc52a8247b9924ad`.

## Mount an authorized customer data bundle

Create a directory that follows the relative paths in
`manifests/customer-data.example.json`, then run:

```bash
export ABU_DHABI_HYDRO_INPUT_DIR=/srv/abu-dhabi-hydro/input
export ABU_DHABI_HYDRO_RUN_DIR=/srv/abu-dhabi-hydro/runs
mkdir -p "$ABU_DHABI_HYDRO_RUN_DIR"

docker compose -f deploy/abu-dhabi-hydrodynamics/compose.yml run --rm hydrodynamics --check
```

The customer input volume is read-only. Only `/data/runs` is writable. The
manifest is a delivery contract: before a city-scale run, the preflight must
check every required file, SHA-256, CRS/spatial extent and available disk.

## Run a mounted SWMM--ANUGA job

The same runner supports one-way overflow transfer and synchronous two-way
head exchange. The low-level runner consumes the rainfall forcing already
present in the file passed to `--swmm-inp`; its `--return-period-years` option
labels the receipt and does not rewrite the input. When a run is submitted
through the phase-3 API, the service first creates a run-local
`coupled_scenario.inp` with the selected official Zone B return period, peak
position, duration, tail and report interval, then passes that generated file
to this runner. Both the base and generated INP SHA-256 values and the applied
rainfall statistics are recorded in `delivery_summary.json` and
`surface_manifest.json`.

For a direct short two-way validation run, pass either a scenario-ready INP or
the `coupled_scenario.inp` produced by a phase-3 job:

```bash
export ABU_DHABI_SURFACE_RUN_ID=abu-surface-YYYYMMDDHHMMSS-xxxxxxxx

docker run --rm --read-only \
  --tmpfs /tmp:size=512m,mode=1777 \
  -v "$ABU_DHABI_HYDRO_INPUT_DIR:/data/input:ro" \
  -v "$ABU_DHABI_HYDRO_RUN_DIR:/data/runs" \
  --entrypoint python \
  abu-dhabi-hydrodynamics:runtime-v1 \
  /app/scripts/run_abu_dhabi_swmm_anuga_bidirectional_pilot.py \
  --swmm-inp "/data/runs/surface/${ABU_DHABI_SURFACE_RUN_ID}/coupled_scenario.inp" \
  --swmm-library /opt/swmm/lib/libswmm5.so \
  --grid /data/input/surface/terrain_grid_250m.npz \
  --bindings /data/input/coupling/interface_bindings.jsonl.gz \
  --output /data/runs/two-way-validation \
  --duration-seconds 600 \
  --window-seconds 300 \
  --coupling-mode two_way_swmm_anuga \
  --binding-limit 100 \
  --interface-detail-limit 100 \
  --run-id mounted-two-way-validation \
  --quiet
```

Remove `--binding-limit` for the complete mounted interface set. Select
`--coupling-mode one_way_swmm_to_anuga` to apply only SWMM node overflow to
ANUGA; the runner then suppresses signed head exchange and reverse flow.

## Solver pins

| Solver | Pin | License | Delivery |
|---|---|---|---|
| EPA SWMM | `7952ca837988b1c32f791812eccc9fd64547e093` (5.2.4) | Public Domain | core image |
| ANUGA | `9a7ef669872540a215bbb58972d12262a0209668` | Apache-2.0 | core image |
| LISFLOOD-FP BMI | `11f2a9214f80e1194bfaea23bc52a8247b9924ad` (5.9) | GPL-3.0 | optional image |

The fixed pins are recorded in `manifests/solvers.json`. The image builds from
source instead of copying the current developer's macOS ARM64 binaries, so the
same build can target Linux amd64 or arm64.

## Stage-3 integration

The phase-3 service is routed through the portable paths and exposes these
explicit modes:

- `surface_rainfall_only`
- `one_way_swmm_to_anuga`
- `two_way_swmm_anuga`
- optional `lisflood_fp_2d`

The first three modes are available through the phase-3 API. LISFLOOD-FP is
kept as a separate optional image because of its GPL-3.0 distribution terms;
it is runnable through the image command line but is not mixed into the Web
API process. The existing five-stage branch remains unchanged while this
independent runtime branch is being validated.
