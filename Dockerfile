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
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---- Rebuild matplotlib font cache (pick up CJK fonts) ---------------------
RUN python -c "import matplotlib.font_manager; matplotlib.font_manager._load_fontmanager(try_read_cache=False)"

# ---- Remove build tools to save space (~200MB) ------------------------------
RUN apt-get purge -y build-essential python3-dev && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# ---- Copy application code --------------------------------------------------
COPY data_agent/ /app/data_agent/
COPY --from=frontend-builder /build/dist/ /app/frontend/dist/
COPY .chainlit/ /app/.chainlit/
COPY public/ /app/public/
COPY scripts/ /app/scripts/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# ---- Create uploads directory and non-root user -----------------------------
RUN groupadd -r agent && useradd -r -g agent -d /app -s /bin/bash agent && \
    mkdir -p /app/data_agent/uploads && \
    chown -R agent:agent /app

USER agent

# ---- Runtime configuration --------------------------------------------------
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/ || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
