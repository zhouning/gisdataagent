#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SERVICE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
IMAGE_TAG=${IMAGE_TAG:-abu-dhabi-gwm-api:1.0.0-model-r1-linux-amd64}

if [ ! -f "${SERVICE_DIR}/model_bundle/manifest.json" ]; then
  echo "Missing model_bundle/manifest.json; run build_model_bundle.py first." >&2
  exit 1
fi

docker buildx build \
  --platform linux/amd64 \
  --load \
  --tag "${IMAGE_TAG}" \
  "${SERVICE_DIR}"

docker image inspect "${IMAGE_TAG}" --format '{{.Id}} {{.Architecture}} {{.Os}}'
