#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAMESPACE="${HYDRO_NAMESPACE:-gis-agent-hydro-dev}"
IMAGE="${HYDRO_IMAGE:-abu-dhabi-hydrodynamics:workbench-dev}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
HYDRO_RUNTIME_IMAGE="${HYDRO_RUNTIME_IMAGE:-abu-dhabi-hydrodynamics:runtime-v1}"
NODES=(desktop-control-plane desktop-worker)

cluster_check() {
  test "$(kubectl config current-context)" = "docker-desktop" || {
    echo "Expected kubectl context docker-desktop" >&2
    exit 1
  }
  for node in "${NODES[@]}"; do
    docker inspect "$node" >/dev/null
  done
}

build() {
  cluster_check
  docker build \
    --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL" \
    --build-arg "HYDRO_RUNTIME_IMAGE=$HYDRO_RUNTIME_IMAGE" \
    -f "$ROOT/docker/hydro-workbench/Dockerfile" -t "$IMAGE" "$ROOT"
  local archive
  archive="$(mktemp -t hydro-workbench.XXXXXX.tar)"
  trap 'rm -f "$archive"' RETURN
  docker save "$IMAGE" -o "$archive"
  for node in "${NODES[@]}"; do
    docker exec -i "$node" ctr -n=k8s.io images import - < "$archive"
  done
  rm -f "$archive"
  trap - RETURN
}

deploy() {
  cluster_check
  kubectl apply -k "$ROOT/k8s/hydro-workbench/overlays/docker-desktop"
  kubectl -n "$NAMESPACE" rollout status deployment/hydro-api --timeout=180s
}

status() {
  kubectl -n "$NAMESPACE" get pods,jobs,svc,pvc -o wide
}

forward() {
  echo "Hydro workbench: http://localhost:8091"
  exec kubectl -n "$NAMESPACE" port-forward service/hydro-api 8091:80
}

case "${1:-up}" in
  build) build ;;
  deploy) deploy ;;
  up) build; deploy ;;
  status) status ;;
  forward) forward ;;
  *) echo "Usage: $0 {up|build|deploy|status|forward}" >&2; exit 2 ;;
esac
