# syntax=docker/dockerfile:1.7
FROM apache/dolphinscheduler-standalone-server:3.4.2

USER root

# DolphinScheduler's shell-task cancellation walks the process tree with pstree.
RUN apt-get update \
    && apt-get install -y --no-install-recommends psmisc \
    && rm -rf /var/lib/apt/lists/*
