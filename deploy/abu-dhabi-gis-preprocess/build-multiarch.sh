#!/usr/bin/env bash
set -euo pipefail

mode="${1:-local}"
image="${2:-abu-dhabi-gis-preprocess:v1}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd)"
dockerfile="${script_dir}/Dockerfile"

case "${mode}" in
  local)
    docker buildx build \
      --platform linux/arm64 \
      --load \
      --file "${dockerfile}" \
      --tag "${image}-arm64" \
      "${repository_root}"
    docker buildx build \
      --platform linux/amd64 \
      --load \
      --file "${dockerfile}" \
      --tag "${image}-amd64" \
      "${repository_root}"
    ;;
  publish)
    if [[ "${image}" != */* ]]; then
      echo "publish mode requires a registry-qualified image, for example ghcr.io/acme/abu-dhabi-gis-preprocess:v1" >&2
      exit 2
    fi
    docker buildx build \
      --platform linux/arm64,linux/amd64 \
      --push \
      --file "${dockerfile}" \
      --tag "${image}" \
      "${repository_root}"
    ;;
  *)
    echo "usage: $0 [local|publish] [image]" >&2
    exit 2
    ;;
esac
