# Abu Dhabi hydrodynamics delivery profiles

This package deliberately separates three things that are often confused:

1. the Git source and Dockerfiles, which provide an auditable build recipe;
2. the solver image, which provides the compiled SWMM/ANUGA runtime; and
3. the authorized customer data bundle, which provides the Abu Dhabi model
   inputs and is never copied into the image.

The image is not required when the recipient can build from source. It is
strongly recommended when the recipient needs an immediately runnable,
offline, or controlled-environment delivery.

## Profile A: source-rebuild delivery

Use this profile when the recipient has network access and wants to reproduce
the build from the pinned solver commits.

```bash
git clone --branch feat/abu-dhabi-hydrodynamics-reproducible-runtime \
  https://github.com/zhouning/gisdataagent.git
cd gisdataagent

docker build \
  -f deploy/abu-dhabi-hydrodynamics/Dockerfile \
  -t abu-dhabi-hydrodynamics:runtime-v1 .

docker run --rm \
  --read-only \
  --tmpfs /tmp:size=512m,mode=1777 \
  --tmpfs /data/runs:size=1g,mode=1777 \
  abu-dhabi-hydrodynamics:runtime-v1 --check --smoke
```

This build fetches the pinned EPA SWMM and ANUGA sources, Python wheels and
Debian build dependencies. It does not fetch or contain customer data.

## Profile B: registry delivery (recommended)

Build and publish architecture-specific or multi-architecture images to an
approved registry. Replace the registry and repository names with the
customer's actual location.

```bash
IMAGE_REPOSITORY=ghcr.io/ORG/abu-dhabi-hydrodynamics

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f deploy/abu-dhabi-hydrodynamics/Dockerfile \
  -t "${IMAGE_REPOSITORY}:runtime-v1" \
  --push .

docker pull "${IMAGE_REPOSITORY}:runtime-v1"
docker image inspect "${IMAGE_REPOSITORY}:runtime-v1" \
  --format '{{index .RepoDigests 0}}'
```

Publish the optional LISFLOOD-FP image separately:

```bash
LISFLOOD_REPOSITORY=ghcr.io/ORG/abu-dhabi-lisflood-fp

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f deploy/abu-dhabi-hydrodynamics/Dockerfile.lisflood \
  -t "${LISFLOOD_REPOSITORY}:5.9-bmi" \
  --push .
```

To use the registry image through Compose without rebuilding locally:

```bash
export ABU_DHABI_HYDRO_IMAGE="${IMAGE_REPOSITORY}:runtime-v1"
docker compose \
  -f deploy/abu-dhabi-hydrodynamics/compose.yml \
  pull hydrodynamics
```

The LISFLOOD-FP image remains separate because the pinned runtime is GPL-3.0.
Any redistribution must preserve the applicable license and source-offer
obligations.

## Profile C: offline image bundle

Use this profile when the recipient cannot reach a registry or the public
source package indexes. A Docker image tar is architecture-specific unless a
registry manifest is used.

```bash
TARGET_PLATFORM=linux/arm64
TARGET_SUFFIX=linux-arm64
IMAGE_NAME="abu-dhabi-hydrodynamics:runtime-v1-${TARGET_SUFFIX}"

docker buildx build \
  --platform "${TARGET_PLATFORM}" \
  -f deploy/abu-dhabi-hydrodynamics/Dockerfile \
  -t "${IMAGE_NAME}" \
  --load .

docker save --output \
  "abu-dhabi-hydrodynamics-runtime-v1-${TARGET_SUFFIX}.tar" \
  "${IMAGE_NAME}"

shasum -a 256 \
  "abu-dhabi-hydrodynamics-runtime-v1-${TARGET_SUFFIX}.tar"
```

On the receiving machine:

```bash
docker load --input abu-dhabi-hydrodynamics-runtime-v1-linux-arm64.tar
docker image inspect abu-dhabi-hydrodynamics:runtime-v1-linux-arm64
docker run --rm \
  --platform linux/arm64 \
  --read-only \
  --tmpfs /tmp:size=512m,mode=1777 \
  --tmpfs /data/runs:size=1g,mode=1777 \
  abu-dhabi-hydrodynamics:runtime-v1-linux-arm64 --check --smoke
```

Create a separate tar and checksum for `abu-dhabi-lisflood-fp:5.9-bmi` if
LISFLOOD-FP is part of the approved delivery.

### Validated 2026-09-23 offline bundle

The following architecture-specific archives were built and smoke-tested. Use
`linux-amd64` for Intel/AMD x86-64 servers and workstations. Use `linux-arm64`
for AWS Graviton, Ampere, Apple Silicon Docker Desktop and other AArch64 hosts.

| Archive | Loaded image tag | Platform | Bytes | SHA-256 |
|---|---|---|---:|---|
| `abu-dhabi-hydrodynamics-runtime-v1-linux-amd64.tar` | `abu-dhabi-hydrodynamics:runtime-v1-linux-amd64` | `linux/amd64` | 258,993,152 | `9af4c2be07609121400df8dd8c01b50669dadd4dfe1f77faddfbdaa115354086` |
| `abu-dhabi-hydrodynamics-runtime-v1-linux-arm64.tar` | `abu-dhabi-hydrodynamics:runtime-v1-linux-arm64` | `linux/arm64` | 255,635,456 | `2dae19fe71a8989233d009e8d5fb84257e91940aaf470de8c9778a6b88ccb174` |
| `abu-dhabi-lisflood-fp-5.9-bmi-linux-amd64.tar` | `abu-dhabi-lisflood-fp:5.9-bmi-linux-amd64` | `linux/amd64` | 31,154,688 | `f70f948b517835550a6970bf404fe082a754d661bd15fd07543f72974d6ba5f3` |
| `abu-dhabi-lisflood-fp-5.9-bmi-linux-arm64.tar` | `abu-dhabi-lisflood-fp:5.9-bmi-linux-arm64` | `linux/arm64` | 29,020,672 | `afe2b3d856053025348c98b8779f235df648c29ed88563b1bd7452ac9b1f3d9b` |

Load and test only the pair matching the deployment host. For an x86-64
deployment, replace `arm64` with `amd64` and `linux/arm64` with `linux/amd64`
in the following commands:

```bash
docker load --input abu-dhabi-hydrodynamics-runtime-v1-linux-arm64.tar
docker load --input abu-dhabi-lisflood-fp-5.9-bmi-linux-arm64.tar

docker run --rm --platform linux/arm64 \
  --read-only \
  --tmpfs /tmp:size=512m,mode=1777 \
  --tmpfs /data/runs:size=1g,mode=1777 \
  abu-dhabi-hydrodynamics:runtime-v1-linux-arm64 --check --smoke

docker run --rm --platform linux/arm64 \
  --read-only \
  --tmpfs /tmp:size=256m,mode=1777 \
  abu-dhabi-lisflood-fp:5.9-bmi-linux-arm64
```

The amd64 archive was also executed under Docker's `linux/amd64` emulation on
an ARM64 build host. Native x86-64 deployment does not require emulation.

## Customer data is a separate delivery

The image alone cannot run the real Abu Dhabi city model. The authorized data
bundle must be mounted read-only at `/data/input`, and the writable run
directory must be mounted at `/data/runs`. The expected relative paths,
required files, sizes and SHA-256 values are defined in
`manifests/customer-data.example.json`.

```bash
export ABU_DHABI_HYDRO_INPUT_DIR=/srv/abu-dhabi-hydro/input
export ABU_DHABI_HYDRO_RUN_DIR=/srv/abu-dhabi-hydro/runs
export ABU_DHABI_HYDRO_IMAGE=ghcr.io/ORG/abu-dhabi-hydrodynamics:runtime-v1
mkdir -p "${ABU_DHABI_HYDRO_RUN_DIR}"

docker compose \
  -f deploy/abu-dhabi-hydrodynamics/compose.yml \
  run --rm hydrodynamics --check
```

The data bundle is customer-restricted and must not be committed to Git or
baked into a public image. An image checksum does not replace the data-manifest
checksums.

## Standalone runtime versus Web application

The images in this directory are solver/runtime images. They run the SWMM,
ANUGA and coupling processes and provide smoke/preflight commands. They are not
the complete GISDataAgent Web application container.

For the phase-3 Web UI, the recipient additionally needs:

- the application source from this branch;
- the application Python and frontend dependencies;
- the environment variables in `.env.example` and `data_agent/.env.example`;
- the authorized customer data bundle; and
- either a locally provisioned solver environment or an integration that
  invokes the published runtime image.

For a command-line hydrodynamics validation, the runtime image plus the
authorized data bundle is sufficient. The direct runner must receive a
scenario-ready SWMM INP. A phase-3 API job creates
`coupled_scenario.inp` and records its provenance in
`delivery_summary.json` and `surface_manifest.json`.

## Handoff checklist

Every recipient handoff should include:

- Git commit and branch;
- image tag, platform and immutable digest, or offline tar and SHA-256;
- the customer data manifest and its delivery checksum;
- the exact `docker compose` or `docker run` command;
- the smoke receipt showing SWMM, ANUGA and coupling completion; and
- the LISFLOOD-FP license/source notice if that optional image is delivered.
