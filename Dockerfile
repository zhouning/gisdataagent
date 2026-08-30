# syntax=docker/dockerfile:1.7
# =============================================================================
# GIS Data Agent — Dockerfile
# Multi-stage: Node.js frontend build + GDAL/Python runtime
# =============================================================================

# ---- Stage 1: Build frontend ------------------------------------------------
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Runtime -------------------------------------------------------
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.9.3

LABEL maintainer="GIS Data Agent Team"
LABEL description="AI-powered geospatial analysis platform"

# Prevent interactive prompts during package install
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_INPUT=1

# ---- System packages --------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libspatialindex-dev \
    postgresql-client \
    fonts-wqy-microhei \
    fonts-noto-cjk \
    libreoffice-writer \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python virtual environment ---------------------------------------------
RUN python3 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# ---- Install Python dependencies -------------------------------------------
# PIP_INDEX_URL build-arg lets local builds (especially in mainland China)
# point at a faster mirror without modifying the file. Default keeps the
# upstream pypi.org behaviour for CI / overseas builds.
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
        --index-url "${PIP_INDEX_URL}" && \
    pip install -r requirements.txt \
        --index-url "${PIP_INDEX_URL}"

# Blueprint Spatial is an offline runtime capability, never a worker-time
# download. DuckDB verifies the official signed extension during image build;
# the provider binds the copied binary hash and extension version in receipts.
ENV GDA_BLUEPRINT_DUCKDB_SPATIAL_EXTENSION_PATH=/app/duckdb-extensions/spatial.duckdb_extension
RUN mkdir -p /app/duckdb-extensions && \
    python -c "import duckdb,pathlib,shutil; c=duckdb.connect(':memory:'); c.execute('INSTALL spatial'); p=pathlib.Path(c.execute(\"SELECT install_path FROM duckdb_extensions() WHERE extension_name='spatial'\").fetchone()[0]); c.close(); shutil.copyfile(p, pathlib.Path('/app/duckdb-extensions/spatial.duckdb_extension'))" && \
    chmod 0444 /app/duckdb-extensions/spatial.duckdb_extension && \
    rm -rf /root/.duckdb

# pyproj 3.7+ can lose the PROJ database context in worker threads unless the
# data directory is explicit. TWM state builds run through FastAPI's threadpool.
ENV PROJ_DATA=/app/.venv/lib/python3.12/site-packages/pyproj/proj_dir/share/proj
ENV PROJ_LIB=/app/.venv/lib/python3.12/site-packages/pyproj/proj_dir/share/proj

# ---- Rebuild matplotlib font cache (pick up CJK fonts) ---------------------
RUN python -c "import matplotlib.font_manager; matplotlib.font_manager._load_fontmanager(try_read_cache=False)"

# ---- Remove build tools to save space (~200MB) ------------------------------
RUN apt-get purge -y build-essential python3-dev && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# ---- Copy application code --------------------------------------------------
COPY data_agent/ /app/data_agent/
COPY config/deployment_profiles/ /app/config/deployment_profiles/
COPY config/recovery_sli_baselines/ /app/config/recovery_sli_baselines/
COPY data/uwm_public_proxy/ /app/data/uwm_public_proxy/
# Evidence-bounded TWM demo assets. The three test-data directories and the
# four-file Paper9 evidence bundle enter through data_agent; benchmark
# artifacts are copied file by file to avoid unrelated local outputs.
COPY data/benchmarks/dam_gk_2026-07-18/ /app/data/benchmarks/dam_gk_2026-07-18/
COPY docs/reports/twm_data_foundation_validation.json /app/docs/reports/twm_data_foundation_validation.json
COPY benchmarks/gwm_bench_v0_2/internal_dev/hydro_kernel_experiment/stability_report_10seed.json /app/benchmarks/gwm_bench_v0_2/internal_dev/hydro_kernel_experiment/stability_report_10seed.json
COPY benchmarks/gwm_bench_v0_3_candidate/certificate_refresh_report.json /app/benchmarks/gwm_bench_v0_3_candidate/certificate_refresh_report.json
COPY benchmarks/gwm_bench_v0_3_candidate/nwm_forcing_admission_certificate.json /app/benchmarks/gwm_bench_v0_3_candidate/nwm_forcing_admission_certificate.json
COPY benchmarks/gwm_bench_v0_3_candidate/nwm_spatial_topology_admission_certificate.json /app/benchmarks/gwm_bench_v0_3_candidate/nwm_spatial_topology_admission_certificate.json
COPY benchmarks/standard_mapping_chongqing_v0_1/acceptance_report.json /app/benchmarks/standard_mapping_chongqing_v0_1/acceptance_report.json
COPY benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_protocol.json /app/benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_protocol.json
COPY benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_report.json /app/benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_report.json
COPY geocausal/ /app/geocausal/
COPY --from=frontend-builder /build/dist/ /app/frontend/dist/
COPY .chainlit/ /app/.chainlit/
COPY public/ /app/public/
COPY scripts/ /app/scripts/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
# Build the evidence-bounded demand-11 environmental product from bundled
# local assets so a fresh container never depends on an ignored local output.
RUN python scripts/build_uwm_environmental_kernel_chongqing.py \
    --source-root /app \
    --output-dir /app/data/uwm_public_proxy/chongqing_central/uwm_environmental_kernel_chongqing

# ---- Create uploads directory and non-root user -----------------------------
RUN groupadd -r agent && useradd -r -g agent -d /app -s /bin/bash agent && \
    mkdir -p /app/data_agent/uploads /app/data_agent/data_lake/raw && \
    chown -R root:agent /app/data_agent/ontology/packages && \
    chmod -R u=rwX,g=rX,o= /app/data_agent/ontology/packages && \
    chown agent:agent /app /app/data_agent \
        /app/data_agent/uploads /app/data_agent/data_lake \
        /app/data_agent/data_lake/raw

USER agent

# ---- Runtime configuration --------------------------------------------------
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
