# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

ARG SERVICE_VERSION=1.0.0
ARG MODEL_RELEASE=GWM-R1-20260914

LABEL org.opencontainers.image.title="Abu Dhabi Urban Flood GWM API" \
      org.opencontainers.image.version="${SERVICE_VERSION}" \
      org.opencontainers.image.description="Offline database-free frozen-GWM inference service" \
      com.gisdataagent.gwm.model-release="${MODEL_RELEASE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    GWM_MODEL_DIR=/opt/gwm/model \
    GWM_RUN_DIR=/data/runs \
    GWM_MIN_FREE_DISK_GB=5 \
    GWM_MAX_CONCURRENT_RUNS=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --requirement /app/requirements.txt

RUN groupadd --gid 10001 gwm \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin gwm \
    && mkdir -p /opt/gwm/model /data/runs \
    && chown -R root:gwm /opt/gwm \
    && chmod -R 0550 /opt/gwm \
    && chown -R gwm:gwm /data/runs \
    && chmod 0750 /data/runs

COPY --chown=root:gwm app/ /app/app/
COPY --chown=root:gwm model_bundle/ /opt/gwm/model/
RUN chown -R root:gwm /app /opt/gwm/model \
    && chmod -R u=rwX,g=rX,o= /app /opt/gwm/model

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=3).read()"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
