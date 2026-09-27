# syntax=docker/dockerfile:1.7
# Multi-architecture source-data compiler for the Abu Dhabi flood model.
# This image never contains customer data. Mount input read-only and write
# derived artifacts to a separate private output volume.

FROM python:3.12-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG IMAGE_VERSION=v1

LABEL org.opencontainers.image.title="Abu Dhabi GIS preprocessing runtime" \
      org.opencontainers.image.description="Private source-data compiler for the Abu Dhabi flood world model" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.source="https://github.com/zhouning/gisdataagent" \
      io.gisdataagent.runtime="abu-dhabi-gis-preprocess"

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROJ_NETWORK=OFF \
    GIS_PREPROCESS_INPUT_ROOT=/input \
    GIS_PREPROCESS_OUTPUT_ROOT=/output \
    HOME=/tmp/gis-preprocess-home \
    XDG_CACHE_HOME=/tmp/cache

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      && rm -rf /var/lib/apt/lists/*

COPY deploy/abu-dhabi-gis-preprocess/requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
      --timeout 120 --retries 8 --index-url "${PIP_INDEX_URL}" \
    && python -m pip install --requirement /tmp/requirements.txt \
      --timeout 120 --retries 8 --index-url "${PIP_INDEX_URL}" \
    && rm -f /tmp/requirements.txt

WORKDIR /app

# Keep this image independent of the rest of the Agent's optional ML and
# solver package tree. The compiler imports only the Abu Dhabi source-data
# modules and the read-only ArcGIS connector contract used by their shared
# schema helpers.
COPY data_agent/uwm/abu_dhabi_flood/ /app/data_agent/uwm/abu_dhabi_flood/
COPY data_agent/connectors/arcgis_rest.py /app/data_agent/connectors/arcgis_rest.py
COPY deploy/abu-dhabi-gis-preprocess/minimal_data_agent_init.py /app/data_agent/__init__.py
COPY deploy/abu-dhabi-gis-preprocess/minimal_uwm_init.py /app/data_agent/uwm/__init__.py
COPY deploy/abu-dhabi-gis-preprocess/minimal_abu_dhabi_flood_init.py /app/data_agent/uwm/abu_dhabi_flood/__init__.py
COPY deploy/abu-dhabi-gis-preprocess/minimal_connectors_init.py /app/data_agent/connectors/__init__.py
COPY deploy/abu-dhabi-gis-preprocess/gis_preprocess.py /app/gis_preprocess.py
COPY deploy/abu-dhabi-gis-preprocess/source_adapters.py /app/source_adapters.py
COPY deploy/abu-dhabi-gis-preprocess/README.md /app/README.md

RUN groupadd --gid 10001 gisdata \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin gisdata \
    && mkdir -p /input /output /tmp/gis-preprocess-home /tmp/cache \
    && chown -R 10001:10001 /app /input /output /tmp/gis-preprocess-home /tmp/cache \
    && chmod -R u=rwX,g=rX,o= /app

USER 10001:10001
ENTRYPOINT ["python", "/app/gis_preprocess.py"]
CMD ["--help"]
