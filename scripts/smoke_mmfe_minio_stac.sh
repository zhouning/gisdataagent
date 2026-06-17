#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
BUCKET="${MMFE_LAKEHOUSE_BUCKET:-gis-agent-lakehouse}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minio_admin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-local_dev_minio_secret}"
COLLECTION="${MMFE_STAC_COLLECTION:-mmfe-fusion-products}"
ITEM_ID="${1:-twm-parcel-current}"
OBJECT_KEY="catalog/stac/$COLLECTION/$ITEM_ID.json"
TMP_FILE="$ROOT_DIR/.tmp/$ITEM_ID.stac.json"

mkdir -p "$ROOT_DIR/.tmp"
cat > "$TMP_FILE" <<EOF
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "$ITEM_ID",
  "collection": "$COLLECTION",
  "bbox": [],
  "geometry": null,
  "properties": {
    "datetime": "2026-06-16T00:00:00Z",
    "mmfe:product_type": "semantic_fusion_product",
    "mmfe:validation_scaffold": "twm"
  },
  "assets": {
    "semantic_manifest": {
      "href": "s3://$BUCKET/raw/twm/parcel_current.semantic.json",
      "type": "application/json",
      "roles": ["metadata"]
    }
  },
  "links": []
}
EOF

docker-compose -f "$ROOT_DIR/docker-compose.yml" up -d minio minio-bucket-init >/dev/null
docker run --rm \
  --network gisdataagent_agent-net \
  --entrypoint sh \
  -e MINIO_ROOT_USER="$MINIO_ROOT_USER" \
  -e MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  -v "$TMP_FILE:/tmp/stac-item.json:ro" \
  minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -c "
    set -e
    mc alias set local http://minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
    mc mb --ignore-existing local/$BUCKET >/dev/null
    mc cp /tmp/stac-item.json local/$BUCKET/$OBJECT_KEY >/dev/null
    mc ls local/$BUCKET/$OBJECT_KEY
  "

echo "[minio-stac-smoke] uploaded s3://$BUCKET/$OBJECT_KEY"
