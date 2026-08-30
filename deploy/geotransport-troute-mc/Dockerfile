ARG BASE_IMAGE=gis-data-agent:dev@sha256:358b9f13cd0752702032fe0c6951ee675a3d2d3ee574337cc20e8437a1b67d92
FROM ${BASE_IMAGE}

USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y gfortran \
    && rm -rf /var/lib/apt/lists/*
# h5py is provided by the base image's pinned requirements/scientific profile.
# Keep this image focused on its native Fortran runtime dependency.
USER agent
