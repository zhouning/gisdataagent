#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SERVICE_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
IMAGE_TAG=${IMAGE_TAG:-abu-dhabi-gwm-api:1.0.0-model-r1-linux-amd64}
DIST_DIR=${DIST_DIR:-${SERVICE_DIR}/dist}
ARCHIVE="${DIST_DIR}/abu-dhabi-gwm-api_1.0.0-model-r1-linux-amd64.tar"
ARCHIVE_NAME=$(basename "${ARCHIVE}")

mkdir -p "${DIST_DIR}/scripts"
rm -f \
  "${DIST_DIR}/run-windows.ps1" \
  "${DIST_DIR}/api-examples.ps1" \
  "${DIST_DIR}/smoke-test.ps1"
docker image inspect "${IMAGE_TAG}" >/dev/null
docker save --output "${ARCHIVE}" "${IMAGE_TAG}"
chmod 0644 "${ARCHIVE}"

pushd "${DIST_DIR}" >/dev/null
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${ARCHIVE_NAME}" > "${ARCHIVE_NAME}.sha256"
else
  shasum -a 256 "${ARCHIVE_NAME}" > "${ARCHIVE_NAME}.sha256"
fi
popd >/dev/null

cp "${SERVICE_DIR}/README.md" "${DIST_DIR}/README.md"
cp "${SERVICE_DIR}/openapi.yaml" "${DIST_DIR}/openapi.yaml"
cp "${SERVICE_DIR}/DEPLOYMENT_WINDOWS_WSL2.md" "${DIST_DIR}/DEPLOYMENT_WINDOWS_WSL2.md"
cp "${SERVICE_DIR}/docker-compose.windows.yml" "${DIST_DIR}/docker-compose.windows.yml"
cp "${SERVICE_DIR}/.env.windows.example" "${DIST_DIR}/.env.windows.example"
cp "${SERVICE_DIR}/model_bundle/manifest.json" "${DIST_DIR}/MODEL_MANIFEST.json"
cp "${SERVICE_DIR}/scripts/run-windows.ps1" "${DIST_DIR}/scripts/run-windows.ps1"
cp "${SERVICE_DIR}/scripts/api-examples.ps1" "${DIST_DIR}/scripts/api-examples.ps1"
cp "${SERVICE_DIR}/scripts/smoke-test.ps1" "${DIST_DIR}/scripts/smoke-test.ps1"

ls -lh "${ARCHIVE}" "${ARCHIVE}.sha256"
