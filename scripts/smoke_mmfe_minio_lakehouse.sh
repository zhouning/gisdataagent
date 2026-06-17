#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BUCKET="${MMFE_LAKEHOUSE_BUCKET:-gis-agent-lakehouse}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minio_admin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-local_dev_minio_secret}"
SOURCE_FILE="${1:-data_agent/test_data/twm_bishan_demo/parcel_current.semantic.json}"
OBJECT_KEY="${2:-raw/twm/parcel_current.semantic.json}"

if [ ! -f "$ROOT_DIR/$SOURCE_FILE" ]; then
  echo "[minio-smoke] missing source file: $SOURCE_FILE" >&2
  exit 1
fi

docker-compose -f "$ROOT_DIR/docker-compose.yml" up -d minio minio-bucket-init >/dev/null
docker run --rm \
  --network gisdataagent_agent-net \
  --entrypoint sh \
  -e MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  -e MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  -v "$ROOT_DIR/$SOURCE_FILE:/tmp/source-object:ro" \
  minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -c "
    set -e
    mc alias set local http://minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
    mc mb --ignore-existing local/$BUCKET >/dev/null
    mc cp /tmp/source-object local/$BUCKET/$OBJECT_KEY >/dev/null
    mc ls local/$BUCKET/$OBJECT_KEY
  "

echo "[minio-smoke] uploaded s3://$BUCKET/$OBJECT_KEY"
