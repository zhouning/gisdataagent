# EA Repository Multi-Architecture Offline Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce separately loadable AMD64 and ARM64 PostgreSQL 17.5 Docker image archives that initialize an empty volume with the verified `ea_repository` snapshot.

**Architecture:** Render an architecture-neutral gzip-compressed SQL seed from the verified custom archive and filtered TOC, then copy it into architecture-specific official PostgreSQL 17.5 images. Verify each image by starting it with a disposable volume, comparing database structure and exact row-count signatures, restarting it to prove idempotency, and finally exporting it with `docker save`.

**Tech Stack:** PostgreSQL 18.1 client tools, PostgreSQL 17.5 server image, Docker Buildx, PowerShell 7/Windows PowerShell, Docker Desktop QEMU/binfmt, SHA-256.

---

## File Structure

All implementation artifacts live below the already ignored migration directory
`dumps/ea_repository_20260720/offline-image-v1/`. The source custom archive and
`restore.list` remain unchanged.

- `offline-image-v1/build/Dockerfile`: one deterministic image definition for both platforms.
- `offline-image-v1/build/ea_repository_seed.sql.gz`: generated architecture-neutral seed.
- `offline-image-v1/build/seed-metadata.json`: snapshot identity and expected verification values.
- `offline-image-v1/scripts/New-Seed.ps1`: validates the source archive, renders SQL, compresses it, and validates the generated seed.
- `offline-image-v1/scripts/Test-SeedImage.ps1`: runs a platform image in an isolated container and verifies startup, database contents, and restart idempotency.
- `offline-image-v1/README.md`: recipient load/run/operate/backup instructions without a password.
- `offline-image-v1/SHA256SUMS`: hashes for the deliverable archives and seed.
- `offline-image-v1/ea-repository-pg17-amd64.tar`: AMD64 Docker image archive.
- `offline-image-v1/ea-repository-pg17-arm64.tar`: ARM64 Docker image archive.

## Fixed Inputs and Expected Values

```text
Source archive: dumps/ea_repository_20260720/ea_repository_pg17_20260720.dump
Restore TOC: dumps/ea_repository_20260720/restore.list
Source archive SHA-256: 17F3A3BFFF790F174880EF757876C929CA0178A5A1EABB91B1BF620C58BEBB9F
PostgreSQL image: postgres:17.5-bookworm
Database: ea_repository
User: ea_user
Tables: 99
Rows: 321574
Columns: 785
Constraints: 98
Indexes: 247
Sequences: 19
Row-count SHA-256: 7e0eb7eef88d9a3d7d5e89e4c2cdc5a546aeac517b332ad7f3f4820b40dcbba6
AMD64 tag: ea-repository-pg17:17.5-seed-amd64
ARM64 tag: ea-repository-pg17:17.5-seed-arm64
```

### Task 1: Preflight and Seed Generator

**Files:**
- Create: `dumps/ea_repository_20260720/offline-image-v1/scripts/New-Seed.ps1`
- Create: `dumps/ea_repository_20260720/offline-image-v1/build/seed-metadata.json`
- Generate: `dumps/ea_repository_20260720/offline-image-v1/build/ea_repository_seed.sql`
- Generate: `dumps/ea_repository_20260720/offline-image-v1/build/ea_repository_seed.sql.gz`

- [ ] **Step 1: Create isolated output directories and refuse an accidental overwrite**

Run:

```powershell
$root = 'D:\adk\dumps\ea_repository_20260720\offline-image-v1'
if (Test-Path -LiteralPath $root) { throw "Output already exists: $root" }
New-Item -ItemType Directory -Path "$root\build", "$root\scripts" -Force
```

Expected: two empty directories are created; an existing output root stops the run.

- [ ] **Step 2: Write the seed-generator preflight checks first**

The script must stop unless all assertions below pass before generating SQL:

```powershell
$ErrorActionPreference = 'Stop'
$expectedArchiveHash = '17F3A3BFFF790F174880EF757876C929CA0178A5A1EABB91B1BF620C58BEBB9F'
$actualArchiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash
if ($actualArchiveHash -ne $expectedArchiveHash) {
    throw "Archive checksum mismatch: $actualArchiveHash"
}

$activeRdsEntries = @(Select-String -LiteralPath $RestoreList `
    -Pattern '^[^;].*(rdsAdmin|FUNCTION public (control_|create_plugin_|drop_plugin_|select_control_version))')
if ($activeRdsEntries.Count -ne 0) {
    throw "Restore list still contains active RDS entries"
}

$disabledFunctions = @(Select-String -LiteralPath $RestoreList -Pattern '^;.* FUNCTION public ').Count
if ($disabledFunctions -ne 17) {
    throw "Expected 17 disabled RDS functions, found $disabledFunctions"
}
```

- [ ] **Step 3: Run the preflight against a deliberately wrong expected hash**

Temporarily invoke the check with `expectedArchiveHash=0000`.

Expected: FAIL before `pg_restore` runs, with `Archive checksum mismatch`.

- [ ] **Step 4: Implement SQL rendering and deterministic gzip compression**

The generator invokes:

```powershell
& $PgRestore `
  --file=$PlainSql `
  --use-list=$RestoreList `
  --no-owner --no-privileges --no-tablespaces `
  $Archive
if ($LASTEXITCODE -ne 0) { throw "pg_restore SQL rendering failed: $LASTEXITCODE" }
```

Then it uses `.NET` `System.IO.Compression.GZipStream` at optimal compression
to write `ea_repository_seed.sql.gz`, closes all streams in `finally`, and
removes the uncompressed SQL only after every validation passes.

- [ ] **Step 5: Validate the generated SQL before deleting the plain file**

The generator checks all of the following:

```powershell
$forbiddenPatterns = @(
  'control_extension', 'control_tablespace', 'create_plugin_',
  'drop_plugin_', 'select_control_version', 'rdsAdmin'
)
foreach ($pattern in $forbiddenPatterns) {
    if (Select-String -LiteralPath $PlainSql -SimpleMatch $pattern -Quiet) {
        throw "Forbidden seed content: $pattern"
    }
}
foreach ($literal in $SensitiveLiteral) {
    if ($literal -and (Select-String -LiteralPath $PlainSql -SimpleMatch $literal -Quiet)) {
        throw 'Sensitive literal found in seed content'
    }
}

$required = @(
  'CREATE TABLE public.t_object',
  'COPY public.t_object',
  'CREATE INDEX ix_object_name',
  'ADD CONSTRAINT pk_object',
  "SELECT pg_catalog.setval('public.object_id_seq'"
)
foreach ($pattern in $required) {
    if (-not (Select-String -LiteralPath $PlainSql -SimpleMatch $pattern -Quiet)) {
        throw "Required seed content missing: $pattern"
    }
}
```

Expected: forbidden match count is zero and every required representative object is present.

- [ ] **Step 6: Write immutable seed metadata**

Create `seed-metadata.json` with the fixed values above plus:

```json
{
  "snapshot_time": "2026-07-20T11:17:52.879456+08:00",
  "source_wal_lsn": "35/EF0031E8",
  "seed_purpose": "first-start initialization only",
  "password_embedded": false
}
```

- [ ] **Step 7: Run the complete generator and verify artifacts**

Run:

```powershell
& .\scripts\New-Seed.ps1
Get-FileHash -Algorithm SHA256 .\build\ea_repository_seed.sql.gz
```

Expected: exit 0, compressed seed and metadata exist, plain SQL is removed, and a seed SHA-256 is printed.

### Task 2: Multi-Architecture Image Definition

**Files:**
- Create: `dumps/ea_repository_20260720/offline-image-v1/build/Dockerfile`

- [ ] **Step 1: Write a failing Dockerfile contract check**

Run before creating the Dockerfile:

```powershell
$dockerfile = '.\build\Dockerfile'
if (-not (Test-Path -LiteralPath $dockerfile)) { throw 'Dockerfile missing' }
```

Expected: FAIL with `Dockerfile missing`.

- [ ] **Step 2: Create the platform-neutral Dockerfile**

Use exactly one Dockerfile:

```dockerfile
FROM postgres:17.5-bookworm

ARG TARGETARCH
ARG SEED_SHA256

LABEL org.opencontainers.image.title="EA Repository PostgreSQL Seed" \
      org.opencontainers.image.version="17.5-seed-20260720" \
      org.opencontainers.image.description="PostgreSQL 17.5 first-start seed for ea_repository" \
      io.ea.repository.snapshot="2026-07-20T11:17:52.879456+08:00" \
      io.ea.repository.row-count="321574" \
      io.ea.repository.row-count-sha256="7e0eb7eef88d9a3d7d5e89e4c2cdc5a546aeac517b332ad7f3f4820b40dcbba6" \
      io.ea.repository.seed-sha256="${SEED_SHA256}" \
      io.ea.repository.architecture="${TARGETARCH}"

ENV POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale-provider=libc --lc-collate=C --lc-ctype=en_US.UTF-8" \
    TZ="Asia/Shanghai"

COPY --chown=postgres:postgres ea_repository_seed.sql.gz \
    /docker-entrypoint-initdb.d/10-ea_repository_seed.sql.gz
COPY seed-metadata.json /usr/local/share/ea-repository/seed-metadata.json

HEALTHCHECK --interval=5s --timeout=5s --start-period=60s --retries=30 \
  CMD pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" || exit 1

CMD ["postgres", "-c", "timezone=Etc/GMT-8"]
```

- [ ] **Step 3: Validate the Dockerfile contract and secret absence**

Run:

```powershell
$required = @('postgres:17.5-bookworm', 'TARGETARCH', 'SEED_SHA256',
  'ea_repository_seed.sql.gz', 'HEALTHCHECK', 'timezone=Etc/GMT-8')
foreach ($item in $required) {
  if (-not (Select-String -LiteralPath .\build\Dockerfile -SimpleMatch $item -Quiet)) {
    throw "Dockerfile contract missing: $item"
  }
}
foreach ($literal in $SensitiveLiteral) {
  if ($literal -and (Select-String -Path .\build\* -SimpleMatch $literal -Quiet)) {
    throw 'Sensitive literal found in build context'
  }
}
```

Expected: exit 0 and zero secret matches.

### Task 3: AMD64 Build and Runtime Verification

**Files:**
- Create: `dumps/ea_repository_20260720/offline-image-v1/scripts/Test-SeedImage.ps1`

- [ ] **Step 1: Write verification assertions before building**

`Test-SeedImage.ps1` accepts `-Image`, `-Platform`, `-Container`, `-Volume`, and
`-HostPort`. It generates a random test password at runtime and never prints it.
It must:

1. create a new named volume and container;
2. poll `.State.Health.Status` until `healthy` or a 300-second deadline;
3. query exact table row counts and hash the canonical JSON map in PowerShell;
4. query column, constraint, index, sequence, and RDS-function counts;
5. insert a marker into a dedicated temporary verification table;
6. restart the container, wait for health, and confirm the marker remains;
7. assert logs contain one initialization completion and not a second import;
8. remove the disposable container and volume in `finally` only after saving logs.

The expected SQL assertions are:

```sql
SELECT count(*) FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema'); -- 99 before marker table

SELECT count(*) FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema'); -- 785 before marker table

SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema'); -- 98

SELECT count(*) FROM pg_indexes
WHERE schemaname NOT IN ('pg_catalog', 'information_schema'); -- 247

SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind='S' AND n.nspname NOT IN ('pg_catalog', 'information_schema'); -- 19

SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public'; -- 0
```

- [ ] **Step 2: Run verification against the unbuilt AMD64 tag**

Run:

```powershell
& .\scripts\Test-SeedImage.ps1 `
  -Image 'ea-repository-pg17:17.5-seed-amd64' `
  -Platform 'linux/amd64' -Container 'ea-seed-test-amd64' `
  -Volume 'ea_seed_test_amd64_data' -HostPort 55432
```

Expected: FAIL because the image tag does not exist locally.

- [ ] **Step 3: Build and load the AMD64 image**

Run:

```powershell
$seedHash = (Get-FileHash -Algorithm SHA256 .\build\ea_repository_seed.sql.gz).Hash
docker buildx build --platform linux/amd64 --load `
  --build-arg "SEED_SHA256=$seedHash" `
  --tag ea-repository-pg17:17.5-seed-amd64 .\build
if ($LASTEXITCODE -ne 0) { throw 'AMD64 image build failed' }
```

Expected: exit 0 and image platform reports `linux/amd64`.

- [ ] **Step 4: Run complete AMD64 verification**

Run the command from Step 2 again.

Expected: healthy startup, all fixed counts match, row-count signature matches,
test marker survives restart, no second seed import occurs, and cleanup succeeds.

### Task 4: ARM64 Build and Runtime Verification

**Files:**
- Reuse: `dumps/ea_repository_20260720/offline-image-v1/scripts/Test-SeedImage.ps1`

- [ ] **Step 1: Confirm ARM64 execution capability**

Run:

```powershell
docker run --rm --platform linux/arm64 alpine:3.20 uname -m
```

Expected: `aarch64`. Any other result stops ARM64 verification.

- [ ] **Step 2: Build and load the ARM64 image**

Run:

```powershell
$seedHash = (Get-FileHash -Algorithm SHA256 .\build\ea_repository_seed.sql.gz).Hash
docker buildx build --platform linux/arm64 --load `
  --build-arg "SEED_SHA256=$seedHash" `
  --tag ea-repository-pg17:17.5-seed-arm64 .\build
if ($LASTEXITCODE -ne 0) { throw 'ARM64 image build failed' }
```

Expected: exit 0 and image platform reports `linux/arm64`.

- [ ] **Step 3: Run complete ARM64 verification under QEMU**

Run:

```powershell
& .\scripts\Test-SeedImage.ps1 `
  -Image 'ea-repository-pg17:17.5-seed-arm64' `
  -Platform 'linux/arm64' -Container 'ea-seed-test-arm64' `
  -Volume 'ea_seed_test_arm64_data' -HostPort 55433
```

Expected: the same database and idempotency assertions as AMD64 pass. Allow the
full 300-second health deadline because seed import runs under emulation.

### Task 5: Export, Reload Test, and Recipient Documentation

**Files:**
- Create: `dumps/ea_repository_20260720/offline-image-v1/README.md`
- Create: `dumps/ea_repository_20260720/offline-image-v1/SHA256SUMS`
- Generate: `dumps/ea_repository_20260720/offline-image-v1/ea-repository-pg17-amd64.tar`
- Generate: `dumps/ea_repository_20260720/offline-image-v1/ea-repository-pg17-arm64.tar`

- [ ] **Step 1: Export each tag to a separate Docker archive without overwriting**

Run:

```powershell
$amdTar = '.\ea-repository-pg17-amd64.tar'
$armTar = '.\ea-repository-pg17-arm64.tar'
foreach ($path in @($amdTar, $armTar)) {
  if (Test-Path -LiteralPath $path) { throw "Refusing overwrite: $path" }
}
docker save --output $amdTar ea-repository-pg17:17.5-seed-amd64
if ($LASTEXITCODE -ne 0) { throw 'AMD64 docker save failed' }
docker save --output $armTar ea-repository-pg17:17.5-seed-arm64
if ($LASTEXITCODE -ne 0) { throw 'ARM64 docker save failed' }
```

- [ ] **Step 2: Generate checksums**

Write `SHA256SUMS` as lowercase hash, two spaces, filename for the two tar files
and `build/ea_repository_seed.sql.gz`.

Expected: recalculating each SHA-256 reproduces the file exactly.

- [ ] **Step 3: Write recipient instructions**

`README.md` must include these password-safe examples:

```powershell
docker load --input .\ea-repository-pg17-amd64.tar
$env:EA_REPOSITORY_PASSWORD = Read-Host 'Database password'
docker run -d --name ea-repository-pg17 --restart unless-stopped `
  --publish 127.0.0.1:5432:5432 `
  --env POSTGRES_USER=ea_user --env POSTGRES_DB=ea_repository `
  --env "POSTGRES_PASSWORD=$env:EA_REPOSITORY_PASSWORD" `
  --volume ea_repository_pg17_data:/var/lib/postgresql/data `
  ea-repository-pg17:17.5-seed-amd64
```

Include the ARM64 tag substitution, `docker inspect` health command, URI encoding
note for special password characters, stop/start commands, `pg_dump` backup
example, restore-to-new-volume guidance, and warning that loading a newer image
does not update an existing populated volume.

- [ ] **Step 4: Prove the archives load independently**

Record the current image IDs, remove only the two generated local tags, load
each tar, and verify the restored tags and platforms:

```powershell
docker image rm ea-repository-pg17:17.5-seed-amd64
docker load --input .\ea-repository-pg17-amd64.tar
docker image inspect ea-repository-pg17:17.5-seed-amd64 `
  --format '{{.Os}}/{{.Architecture}}'

docker image rm ea-repository-pg17:17.5-seed-arm64
docker load --input .\ea-repository-pg17-arm64.tar
docker image inspect ea-repository-pg17:17.5-seed-arm64 `
  --format '{{.Os}}/{{.Architecture}}'
```

Expected: `linux/amd64` and `linux/arm64`, with image IDs equal to the pre-export values.

- [ ] **Step 5: Re-run fresh runtime verification after tar reload**

Run `Test-SeedImage.ps1` once for each reloaded tag using new container names,
new volumes, and ports `55434` and `55435`.

Expected: both complete verification runs pass again.

- [ ] **Step 6: Verify original database remains untouched and healthy**

Run:

```powershell
docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' ea-repository-pg17
```

Then query the original `127.0.0.1:5432` database and recompute the exact
per-table row-count signature.

Expected: original container is `running healthy`, has 99 tables and 321,574
rows, and retains row-count signature
`7e0eb7eef88d9a3d7d5e89e4c2cdc5a546aeac517b332ad7f3f4820b40dcbba6`.

- [ ] **Step 7: Final sensitive-data and artifact audit**

Run a recursive text scan across Dockerfile, scripts, metadata, README, and
Docker image histories for the cloud host and known password. List archive
files with sizes and SHA-256 values.

Expected: zero sensitive matches; two non-empty tar files; checksum verification passes.

## Completion Evidence

Report:

- exact paths, sizes, and SHA-256 values for both `.tar` files;
- PostgreSQL version and platform for each loaded image;
- health, table/row/object counts, row-count signature, and idempotency result for each runtime test;
- seed SHA-256 and source archive SHA-256;
- original local database health and unchanged signature;
- any residual limitation of QEMU verification versus native ARM64 hardware.
