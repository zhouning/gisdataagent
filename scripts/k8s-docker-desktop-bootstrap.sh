#!/usr/bin/env bash
# =============================================================================
# k8s-docker-desktop-bootstrap.sh — bring up GIS Data Agent on Docker Desktop's
# bundled kind cluster (context: docker-desktop). Node names are discovered
# from the active cluster so the script also supports custom worker counts.
#
# Usage:
#   ./scripts/k8s-docker-desktop-bootstrap.sh up        # build images + load + deploy
#   ./scripts/k8s-docker-desktop-bootstrap.sh build     # rebuild images + load to nodes
#   ./scripts/k8s-docker-desktop-bootstrap.sh deploy    # apply k8s manifests only
#   ./scripts/k8s-docker-desktop-bootstrap.sh forward   # start kubectl port-forwards
#   ./scripts/k8s-docker-desktop-bootstrap.sh status    # show pod / service health
#   ./scripts/k8s-docker-desktop-bootstrap.sh ollama    # probe host Ollama from cluster
#   ./scripts/k8s-docker-desktop-bootstrap.sh down      # delete the gis-agent namespace
#
# Differs from k8s-kind-bootstrap.sh:
#   - No `kind` CLI dependency. Docker Desktop's kind cluster is managed by
#     Docker Desktop itself and isn't visible to the standalone kind binary.
#   - Image distribution uses `docker save | docker exec ... ctr images import`
#     per node instead of `kind load`.
#   - Skips QC subsystems (cv-service / cad-parser / reference-data) — the
#     overlay strips them. Switch to overlays/local-kind for full deploy.
#   - Pulls the Tsinghua pip mirror by default (mainland China network).
#
# Requires: docker, kubectl. Tested on macOS Docker Desktop 4.30+ with kind
# cluster type enabled in Settings → Kubernetes.
# =============================================================================
set -euo pipefail

NAMESPACE="${NAMESPACE:-gis-agent}"
OVERLAY="${OVERLAY:-k8s/overlays/docker-desktop}"
IMAGE_TAG="${IMAGE_TAG:-dev}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
NODES=()
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Color helpers — only when stdout is a tty.
if [ -t 1 ]; then
    BOLD='\033[1m'; BLUE='\033[34m'; GREEN='\033[32m'
    YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
else
    BOLD=''; BLUE=''; GREEN=''; YELLOW=''; RED=''; RESET=''
fi
log()   { printf "${BLUE}[bootstrap]${RESET} %s\n" "$*"; }
ok()    { printf "${GREEN}[ok]${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn]${RESET} %s\n" "$*"; }
fail()  { printf "${RED}[fail]${RESET} %s\n" "$*" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 not found in PATH"
}

# ----------------------------------------------------------------------------
# Cluster precheck — verify Docker Desktop's kind cluster is up
# ----------------------------------------------------------------------------
discover_nodes() {
    local node_names node
    node_names=$(kubectl get nodes \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}') || \
        fail "could not list nodes in the Docker Desktop cluster"

    NODES=()
    while IFS= read -r node; do
        [ -n "$node" ] && NODES+=("$node")
    done <<< "$node_names"
    [ "${#NODES[@]}" -gt 0 ] || fail "Docker Desktop cluster has no nodes"
}

cluster_check() {
    log "checking Docker Desktop kind cluster"
    local context
    context=$(kubectl config current-context 2>/dev/null || echo "")
    if [ "$context" != "docker-desktop" ]; then
        fail "current kubectl context is '$context', expected 'docker-desktop'.\n       Switch with: kubectl config use-context docker-desktop"
    fi
    discover_nodes
    for node in "${NODES[@]}"; do
        if ! docker ps --format '{{.Names}}' | grep -qx "$node"; then
            fail "kind node '$node' not running. In Docker Desktop:\n       Settings → Kubernetes → enable kind cluster type → Apply & restart"
        fi
    done
    ok "cluster context=docker-desktop, nodes=${NODES[*]}"
}

# ----------------------------------------------------------------------------
# Ollama precheck — verify host Ollama reachable from inside the cluster
# ----------------------------------------------------------------------------
ollama_check() {
    log "checking host Ollama via in-cluster pod"
    # kindest/node images don't have curl/wget; spin a throwaway probe pod
    # that uses curlimages/curl. Quoting is awkward here — keep the curl
    # invocation simple.
    local out
    out=$(kubectl run ollama-probe-$$ --rm -i --restart=Never \
            --image=curlimages/curl:latest --quiet --timeout=60s -- \
            curl -sS --max-time 5 http://host.docker.internal:11434/api/tags \
            2>/dev/null || true)
    if [ -z "$out" ]; then
        warn "host Ollama NOT reachable at host.docker.internal:11434 from inside the cluster"
        warn "  - Check Ollama is running:    curl localhost:11434/api/tags"
        warn "  - Check models are pulled:    ollama list"
        warn "  Deployment will continue; app will hit Ollama errors at runtime."
        return 0
    fi
    ok "host Ollama reachable from cluster"
    if command -v python3 >/dev/null; then
        local models
        models=$(printf '%s' "$out" | python3 -c \
            "import sys, json; d=json.load(sys.stdin); print(', '.join(m['name'] for m in d.get('models', [])))" \
            2>/dev/null || echo "")
        [ -n "$models" ] && log "  available models: $models"
    fi
}

# ----------------------------------------------------------------------------
# Image build + load
# ----------------------------------------------------------------------------
load_to_nodes() {
    local image="$1"
    log "exporting ${image}:${IMAGE_TAG} and importing into kind nodes"
    local tarball
    tarball=$(mktemp -t gis-img.XXXXXX.tar)
    # Trap cleanup so a failed import doesn't leave the tar behind.
    trap "rm -f '$tarball'" RETURN
    docker save "${image}:${IMAGE_TAG}" -o "$tarball"
    for node in "${NODES[@]}"; do
        log "  importing into $node"
        docker exec -i "$node" ctr -n=k8s.io images import - < "$tarball"
    done
    rm -f "$tarball"
    trap - RETURN
}

build_image() {
    local context="$1"
    local image="$2"
    log "building ${image}:${IMAGE_TAG} from ${context}"
    docker build \
        --build-arg "PIP_INDEX_URL=${PIP_INDEX_URL}" \
        -t "${image}:${IMAGE_TAG}" \
        "$context"
    load_to_nodes "$image"
}

build_all() {
    cluster_check
    build_image "$ROOT" gis-data-agent
    # postgis-pgvector is a tiny derived layer on imresamu/postgis (~30s build
    # once the base is cached). Always rebuild it — no harm if unchanged, and
    # it lets us pin the exact pgvector version through the local Dockerfile.
    build_image_no_arg "$ROOT/docker/postgis-pgvector" gis-postgis-pgvector "16-3.4"
    ok "all images built and loaded"
}

# Variant of build_image that doesn't pass the PIP_INDEX_URL build-arg (the
# postgis-pgvector Dockerfile doesn't use it, and bookworm-slim's apt sources
# already work fine).
build_image_no_arg() {
    local context="$1"
    local image="$2"
    local tag="${3:-$IMAGE_TAG}"
    log "building ${image}:${tag} from ${context}"
    docker build -t "${image}:${tag}" "$context"
    log "exporting ${image}:${tag} and importing into kind nodes"
    local tarball
    tarball=$(mktemp -t gis-img.XXXXXX.tar)
    trap "rm -f '$tarball'" RETURN
    docker save "${image}:${tag}" -o "$tarball"
    for node in "${NODES[@]}"; do
        log "  importing into $node"
        docker exec -i "$node" ctr -n=k8s.io images import - < "$tarball"
    done
    rm -f "$tarball"
    trap - RETURN
}

# ----------------------------------------------------------------------------
# Deploy
# ----------------------------------------------------------------------------
deploy() {
    cluster_check
    log "applying $OVERLAY"
    kubectl apply -k "$OVERLAY"
    log "waiting for postgres rollout (up to 5min)"
    kubectl -n "$NAMESPACE" rollout status statefulset/postgres --timeout=300s || true
    log "waiting for redis rollout (up to 2min)"
    kubectl -n "$NAMESPACE" rollout status statefulset/redis --timeout=120s || true
    log "waiting for minio rollout (up to 2min)"
    kubectl -n "$NAMESPACE" rollout status statefulset/minio --timeout=120s || true
    log "waiting for migrations Job (up to 5min)"
    kubectl -n "$NAMESPACE" wait --for=condition=complete \
        --timeout=300s job/gis-agent-migrate || \
        warn "migrations Job not yet complete; check 'kubectl -n $NAMESPACE logs job/gis-agent-migrate'"
    log "waiting for app deployment (up to 5min)"
    kubectl -n "$NAMESPACE" rollout status deployment/gis-agent-app --timeout=300s || true
    ok "deploy step done — run '$0 status' to verify"
}

# ----------------------------------------------------------------------------
# Port-forward (no ingress controller in Docker Desktop kind)
# ----------------------------------------------------------------------------
forward() {
    cluster_check
    log "starting port-forwards (Ctrl-C to stop)"
    log "  app:           http://localhost:8080"
    log "  martin tiles:  http://localhost:3000"
    log "  minio console: http://localhost:9001  (login with minio_admin / local_dev_minio_secret)"
    log "  postgres:      localhost:5432"
    trap 'kill 0' EXIT
    kubectl -n "$NAMESPACE" port-forward svc/gis-agent-app 8080:80 &
    kubectl -n "$NAMESPACE" port-forward svc/martin 3000:3000 &
    kubectl -n "$NAMESPACE" port-forward svc/minio 9001:9001 &
    kubectl -n "$NAMESPACE" port-forward svc/postgres 5432:5432 &
    wait
}

# ----------------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------------
status() {
    cluster_check
    printf "${BOLD}=== Pods ===${RESET}\n"
    kubectl -n "$NAMESPACE" get pods -o wide
    printf "\n${BOLD}=== Services ===${RESET}\n"
    kubectl -n "$NAMESPACE" get svc
    printf "\n${BOLD}=== Recent Events ===${RESET}\n"
    kubectl -n "$NAMESPACE" get events --sort-by='.lastTimestamp' | tail -20 || true
    printf "\n${BOLD}=== Migration Job ===${RESET}\n"
    kubectl -n "$NAMESPACE" get job/gis-agent-migrate \
        -o custom-columns=NAME:.metadata.name,COMPLETIONS:.status.succeeded,DURATION:.status.completionTime \
        2>/dev/null || warn "migrations job not found yet"
}

# ----------------------------------------------------------------------------
# Down — drop the namespace (does NOT touch the cluster itself, since the
# user manages it via Docker Desktop, not us).
# ----------------------------------------------------------------------------
namespace_down() {
    if kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
        log "deleting namespace '$NAMESPACE' (this preserves the cluster)"
        kubectl delete ns "$NAMESPACE" --wait=false
        ok "namespace deletion in progress; check with 'kubectl get ns $NAMESPACE'"
    else
        warn "namespace '$NAMESPACE' not found, nothing to do"
    fi
}

# ----------------------------------------------------------------------------
# Main dispatch
# ----------------------------------------------------------------------------
require_cmd docker
require_cmd kubectl

cmd="${1:-up}"
case "$cmd" in
    up)        cluster_check && ollama_check && build_all && deploy ;;
    build)     build_all ;;
    deploy)    deploy ;;
    forward)   forward ;;
    status)    status ;;
    ollama)    ollama_check ;;
    down)      namespace_down ;;
    *)
        echo "Unknown command: $cmd"
        echo "Usage: $0 {up|build|deploy|forward|status|ollama|down}"
        exit 1
        ;;
esac
