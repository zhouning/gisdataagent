# EA Repository Multi-Architecture Offline Image Design

## Objective

Package the restored `ea_repository` PostgreSQL database as two offline Docker
image archives. A recipient must be able to load the archive matching the
machine architecture, start one container with a new volume, and obtain the
same database content without installing PostgreSQL client tools or separately
copying a backup file.

The deliverables are:

- `ea-repository-pg17-amd64.tar` for `linux/amd64` hosts;
- `ea-repository-pg17-arm64.tar` for `linux/arm64` hosts;
- a SHA-256 checksum file;
- concise load, run, readiness, connection, backup, and upgrade instructions.

## Constraints

- PostgreSQL stays at version 17.5 to match the source and current local target.
- The image must not contain the database password.
- The source cloud RDS is not queried again during image construction.
- The current running local database is not modified or stopped.
- PostgreSQL physical data files are not shared across CPU architectures.
- Database writes after first startup must persist in a Docker volume.
- Startup must be idempotent: restarting a populated volume must not import the
  seed data again.
- The image is a seed image, not a mechanism for distributing later runtime
  changes. A new snapshot requires rebuilding and versioning the image.

## Selected Architecture

Both images extend the official `postgres:17.5-bookworm` image for their target
platform. They embed a portable, compressed SQL seed under
`/docker-entrypoint-initdb.d/`. The official PostgreSQL entrypoint executes that
seed only while initializing an empty `PGDATA` volume.

The existing custom archive remains the authoritative backup artifact, but it
is not suitable for direct execution by the official entrypoint. The build
process therefore renders a portable plain SQL seed from the verified archive
and `restore.list`. Rendering uses these policies:

- preserve the 99 tables, 321,574 rows, 785 columns, 98 constraints, 247
  indexes, and 19 sequence states;
- retain object creation order from the archive;
- exclude the 17 Huawei Cloud RDS `rdsAdmin` control functions and their ACLs,
  exactly as defined in `restore.list`;
- omit source ownership, privileges, and tablespace assignments;
- let objects be owned by the initialization user selected at container start.

The seed SQL is architecture-neutral. Only the PostgreSQL executable layers
differ between the AMD64 and ARM64 images.

## Image Contract

The image repository is `ea-repository-pg17`. Architecture-specific local tags
are:

- `ea-repository-pg17:17.5-seed-amd64`
- `ea-repository-pg17:17.5-seed-arm64`

The image declares:

- PostgreSQL port `5432`;
- the official `/var/lib/postgresql/data` volume;
- a health check against the configured initialization user and database;
- OCI labels describing PostgreSQL version, snapshot date, row-count signature,
  target architecture, and seed purpose.

The image does not hard-code `POSTGRES_PASSWORD`. At runtime the operator must
provide:

- `POSTGRES_USER=ea_user`
- `POSTGRES_DB=ea_repository`
- `POSTGRES_PASSWORD` or `POSTGRES_PASSWORD_FILE`

The documented default run command binds `127.0.0.1:5432:5432`. Operators who
need remote clients must make an explicit network exposure and firewall
decision.

## Startup Data Flow

1. Docker loads the architecture-specific image archive.
2. The operator creates a container with a new named volume and supplies the
   database password at runtime.
3. The official entrypoint initializes PostgreSQL 17.5 with `UTF8`,
   `LC_COLLATE=C`, and `LC_CTYPE=en_US.UTF-8`.
4. The entrypoint executes the embedded SQL seed in the target database.
5. PostgreSQL starts normally and the health check becomes healthy.
6. Subsequent restarts detect populated `PGDATA` and skip the seed import.

Initialization may take longer than a normal restart. Readiness is determined
from Docker health status, never from a fixed sleep interval.

## Build Flow

The build directory is isolated beneath the ignored migration artifact
directory so that the database seed cannot be accidentally committed. It
contains only a Dockerfile, generated seed SQL, and metadata needed for the
image build.

The build process performs these steps:

1. Revalidate the custom archive SHA-256.
2. Render plain SQL from the archive using the verified TOC selection.
3. Scan the SQL to confirm that all `rdsAdmin` control functions are absent and
   representative tables, constraints, indexes, data, and sequence sets are
   present.
4. Build AMD64 and ARM64 images from the same Dockerfile and seed.
5. Export each platform image to a separate Docker archive.
6. Calculate SHA-256 checksums for both archives.

The build must fail on any archive, SQL-generation, build, or export error.

## Verification

AMD64 verification runs in a new isolated container and new volume on this
machine. It must prove:

- image platform is `linux/amd64`;
- container reaches healthy state;
- PostgreSQL reports version 17.5 and expected locale/time-zone settings;
- database/user are `ea_repository` and `ea_user`;
- there are 99 tables and exactly 321,574 rows;
- the per-table row-count signature matches
  `7e0eb7eef88d9a3d7d5e89e4c2cdc5a546aeac517b332ad7f3f4820b40dcbba6`;
- there are 785 columns, 98 constraints, 247 indexes, and 19 sequences;
- no `rdsAdmin` control functions exist;
- restarting the same container does not rerun initialization and preserves a
  test write made after initialization.

ARM64 verification must use an ARM64 runtime, either native or Docker emulation
registered through BuildKit. It must repeat the database checks above. A
successful cross-platform build alone is not accepted as runtime verification.
If this Docker installation cannot execute ARM64 images, the ARM64 archive may
still be produced, but it must be clearly marked `built, runtime verification
pending` rather than claimed as verified.

After testing, disposable verification containers and volumes may be removed.
The original `ea-repository-pg17` container and
`ea_repository_pg17_data` volume remain untouched.

## Error Handling

- Archive checksum mismatch stops the build.
- Seed rendering errors stop the build before Docker is invoked.
- An initialization SQL error causes the test container to fail and preserves
  its logs for diagnosis.
- A health timeout is reported with container state and PostgreSQL logs.
- A row or object-count mismatch rejects the artifact.
- A platform mismatch rejects the corresponding artifact.
- Existing image tags or output archives are not overwritten silently. New
  builds use a versioned output directory or require explicit replacement.

## Security and Operations

The image contains application data. Anyone who receives either archive can
inspect that data regardless of the runtime database password. The archive must
therefore be transferred and stored as sensitive data.

Runtime passwords belong in environment injection or Docker secrets and not in
the Dockerfile, image labels, tar filename, README, or shell history. The
recipient should choose a new password rather than reuse the cloud RDS password.

The image tag represents an immutable seed snapshot. Routine backups on the
recipient machine must use `pg_dump` against the running container or a tested
volume-backup procedure. Pulling or loading a newer seed image does not migrate
an existing populated volume.

## Acceptance Criteria

The work is complete when:

- both architecture-specific Docker archive files exist and have SHA-256
  checksums;
- both archives load into Docker with the documented tags and correct platform
  metadata;
- AMD64 runtime verification passes all database and idempotency checks;
- ARM64 runtime verification passes, or the exact emulation/runtime blocker is
  documented without overstating verification;
- recipient instructions contain complete `docker load`, `docker run`, health,
  connection, stop/start, and backup examples;
- no password is embedded in either image or generated documentation;
- the existing local PostgreSQL container and its volume remain healthy and
  unchanged.
