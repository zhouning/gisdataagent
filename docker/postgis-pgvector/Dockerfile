# Derived image: imresamu/postgis:16-3.4 (multi-arch incl. arm64) + pgvector.
# Why this exists:
#   - The official postgis/postgis:16-3.4 ships PostGIS but no pgvector binary
#     and has no arm64 build (blocker on Apple Silicon Mac).
#   - imresamu/postgis:16-3.4 is multi-arch and has the apt source for
#     postgresql-16-pgvector ready to install — but apt install at runtime
#     (via docker-entrypoint-initdb.d) runs as the unprivileged postgres user
#     and fails with "Permission denied".
#   - Baking pgvector into the image at build time avoids both problems.
FROM imresamu/postgis:16-3.4

USER root
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Sanity check at build time — fail loudly here rather than at first apply.
RUN test -f /usr/share/postgresql/16/extension/vector.control

USER postgres
