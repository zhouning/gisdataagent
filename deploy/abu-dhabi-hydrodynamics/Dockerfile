# syntax=docker/dockerfile:1.7
# Portable Linux runtime for the Abu Dhabi 1D/2D hydrodynamics adapters.
# Customer data is never copied into this image; mount it read-only at runtime.

FROM python:3.12-slim-bookworm AS builder

ARG SWMM_REPOSITORY=https://github.com/USEPA/Stormwater-Management-Model.git
ARG SWMM_COMMIT=7952ca837988b1c32f791812eccc9fd64547e093
ARG ANUGA_REPOSITORY=https://github.com/GeoscienceAustralia/anuga_core.git
ARG ANUGA_COMMIT=9a7ef669872540a215bbb58972d12262a0209668
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      cmake \
      g++ \
      gcc \
      gfortran \
      git \
      make \
      ninja-build \
      libopenmpi-dev \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/build

COPY deploy/abu-dhabi-hydrodynamics/requirements.txt /opt/build/requirements.txt
RUN python -m pip install --upgrade pip \
    --timeout 120 \
    --retries 8 \
    --index-url "${PIP_INDEX_URL}" \
    && python -m pip install --requirement /opt/build/requirements.txt \
    --timeout 120 \
    --retries 8 \
    --index-url "${PIP_INDEX_URL}"

RUN git clone --filter=blob:none "${SWMM_REPOSITORY}" swmm \
    && git -C swmm checkout --detach "${SWMM_COMMIT}" \
    && cmake -S swmm -B swmm-build \
       -DCMAKE_BUILD_TYPE=Release \
       -DCMAKE_INSTALL_PREFIX=/opt/swmm \
       -DBUILD_TESTS=OFF \
       -DBUILD_DEF=OFF \
    && cmake --build swmm-build --parallel \
    && cmake --install swmm-build \
    && install -d /opt/swmm/lib \
    && ln -s /opt/swmm/bin/libswmm5.so /opt/swmm/lib/libswmm5.so \
    && ln -s /opt/swmm/bin/libswmm-output.so /opt/swmm/lib/libswmm-output.so

RUN git clone --filter=blob:none "${ANUGA_REPOSITORY}" anuga \
    && git -C anuga checkout --detach "${ANUGA_COMMIT}" \
    && python -m pip install --no-build-isolation ./anuga \
    --timeout 120 \
    --retries 8 \
    --index-url "${PIP_INDEX_URL}" \
    && python -c "import anuga; print('ANUGA', getattr(anuga, '__version__', 'unknown'))"


FROM python:3.12-slim-bookworm AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ABU_DHABI_HYDRO_DATA_ROOT=/data/input \
    ABU_DHABI_HYDRO_RUN_ROOT=/data/runs \
    ABU_DHABI_SWMM_EXECUTABLE=/opt/swmm/bin/runswmm \
    ABU_DHABI_SWMM_LIBRARY=/opt/swmm/lib/libswmm5.so \
    ABU_DHABI_ANUGA_PYTHON=/usr/local/bin/python \
    LD_LIBRARY_PATH=/opt/swmm/lib:/opt/swmm/bin \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/cache \
    HOME=/tmp/hydro-home \
    PATH=/opt/swmm/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      libgomp1 \
      && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /opt/swmm/ /opt/swmm/

WORKDIR /app
COPY data_agent/uwm/abu_dhabi_flood/ /app/data_agent/uwm/abu_dhabi_flood/
COPY scripts/run_abu_dhabi_public_citywide_2d.py /app/scripts/run_abu_dhabi_public_citywide_2d.py
COPY scripts/run_abu_dhabi_swmm_anuga_bidirectional_pilot.py /app/scripts/run_abu_dhabi_swmm_anuga_bidirectional_pilot.py
COPY deploy/abu-dhabi-hydrodynamics/fixtures/ /app/fixtures/
COPY deploy/abu-dhabi-hydrodynamics/manifests/ /app/manifests/
COPY deploy/abu-dhabi-hydrodynamics/scripts/ /app/scripts/

RUN groupadd --gid 10001 hydro \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin hydro \
    && mkdir -p /data/input /data/runs \
    && chown -R hydro:hydro /app /data \
    && chmod -R u=rwX,g=rX,o= /app

USER 10001:10001
WORKDIR /app

ENTRYPOINT ["python", "/app/scripts/preflight.py"]
CMD ["--help"]
