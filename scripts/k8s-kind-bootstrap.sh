#!/usr/bin/env bash
# =============================================================================
# k8s-kind-bootstrap.sh — bring up GIS Data Agent on a local kind cluster
#
# Usage:
#   ./scripts/k8s-kind-bootstrap.sh up        # build images + create cluster + deploy
#   ./scripts/k8s-kind-bootstrap.sh build     # rebuild images + load into kind
#   ./scripts/k8s-kind-bootstrap.sh deploy    # apply k8s manifests only
#   ./scripts/k8s-kind-bootstrap.sh forward   # start kubectl port-forwards
#   ./scripts/k8s-kind-bootstrap.sh status    # show pod / service health
#   ./scripts/k8s-kind-bootstrap.sh down      # delete the kind cluster
#   ./scripts/k8s-kind-bootstrap.sh reset     # delete cluster + recreate
#
# Requires: docker, kind, kubectl. Tested on macOS Docker Desktop 4.30+.
# =============================================================================
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-gis-agent}"
NAMESPACE="${NAMESPACE:-gis-agent}"
OVERLAY="${OVERLAY:-k8s/overlays/local-kind}"
IMAGE_TAG="${IMAGE_TAG:-dev}"
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
# Ollama precheck — verify the host Ollama is reachable from the kind network
# ----------------------------------------------------------------------------
ollama_check() {
    log "checking host Ollama availability"
    local node_container
    node_container=$(docker ps --filter "name=${CLUSTER_NAME}-control-plane" --format '{{.Names}}' | head -1)
    if [ -z "$node_container" ]; then
        warn "kind control-plane container not found, skipping ollama check"
        return 0
    fi
    if docker exec "$node_container" sh -c \
            "wget -qO- --timeout=5 http://host.docker.internal:11434/api/tags 2>/dev/null" >/dev/null 2>&1; then
        ok "host Ollama reachable at host.docker.internal:11434"
        local tags_json
        tags_json=$(docker exec "$node_container" sh -c \
            "wget -qO- --timeout=5 http://host.docker.internal:11434/api/tags" 2>/dev/null || true)
        if [ -n "$tags_json" ]; then
            local models
            models=$(echo "$tags_json" | python3 -c \
                "import sys, json; d=json.load(sys.stdin); print(','.join(m['name'] for m in d.get('models', [])))" \
                2>/dev/null || echo "")
            if [ -n "$models" ]; then
                log "  available models: $models"
            else
                warn "  no models pulled — run: docker exec ollama ollama pull gemma3:27b"
            fi
        fi
    else
        warn "host Ollama NOT reachable at host.docker.internal:11434"
        warn "  Docker Desktop maps host.docker.internal automatically; ensure:"
        warn "    1. Ollama container is running:    docker ps | grep ollama"
        warn "    2. Ollama listens on 0.0.0.0:      docker logs ollama | grep '0.0.0.0:11434'"
        warn "    3. Models are pulled:              docker exec ollama ollama list"
        warn "  Deployment will continue; app pods will fall back to GOOGLE_API_KEY if set."
    fi
}

# ----------------------------------------------------------------------------
# Cluster lifecycle
# ----------------------------------------------------------------------------
cluster_exists() {
    kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"
}

cluster_up() {
    if cluster_exists; then
        log "kind cluster '$CLUSTER_NAME' already exists, skipping create"
        return 0
    fi
    log "creating kind cluster '$CLUSTER_NAME'"
    cat <<EOF | kind create cluster --name "$CLUSTER_NAME" --config -
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    # Surface the app port on localhost via a kind extraPortMappings entry.
    # We forward to the kubectl port-forward pattern instead, but if you'd
    # rather expose Ingress directly, install an ingress controller and let
    # this take over.
    extraPortMappings: []
EOF
    ok "kind cluster up"
    kubectl cluster-info --context "kind-$CLUSTER_NAME"
}

cluster_down() {
    if cluster_exists; then
        log "deleting kind cluster '$CLUSTER_NAME'"
        kind delete cluster --name "$CLUSTER_NAME"
        ok "cluster deleted"
    else
        warn "no cluster named '$CLUSTER_NAME' found"
    fi
}

# ----------------------------------------------------------------------------
# Image build + load
# ----------------------------------------------------------------------------
build_image() {
    local context="$1"
    local image="$2"
    log "building $image:$IMAGE_TAG from $context"
    docker build -t "${image}:${IMAGE_TAG}" "$context"
    log "loading $image:$IMAGE_TAG into kind cluster"
    kind load docker-image "${image}:${IMAGE_TAG}" --name "$CLUSTER_NAME"
}

build_all() {
    cluster_exists || fail "cluster '$CLUSTER_NAME' not running; run '$0 up' first"
    build_image "$ROOT" gis-data-agent
    build_image "$ROOT/subsystems/cv-service" gis-cv-service
    build_image "$ROOT/subsystems/cad-parser" gis-cad-parser
    build_image "$ROOT/subsystems/reference-data" gis-reference-data
    ok "all images built and loaded"
}

# ----------------------------------------------------------------------------
# Deploy
# ----------------------------------------------------------------------------
deploy() {
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
# Port-forward (kind has no ingress controller by default)
# ----------------------------------------------------------------------------
forward() {
    cluster_exists || fail "cluster not running"
    log "starting port-forwards (Ctrl-C to stop)"
    log "  app:           http://localhost:8080"
    log "  martin tiles:  http://localhost:3000"
    log "  minio console: http://localhost:9001  (login with minio_admin / local_dev_minio_secret)"
    log "  postgres:      localhost:5432"
    # Run in background then wait so a single Ctrl-C stops them all.
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
    cluster_exists || fail "cluster not running"
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
# Reset = down + up + ollama check + build + deploy
# ----------------------------------------------------------------------------
reset() {
    cluster_down
    cluster_up
    ollama_check
    build_all
    deploy
}

# ----------------------------------------------------------------------------
# Main dispatch
# ----------------------------------------------------------------------------
require_cmd docker
require_cmd kind
require_cmd kubectl

cmd="${1:-up}"
case "$cmd" in
    up)        cluster_up && ollama_check && build_all && deploy ;;
    build)     build_all ;;
    deploy)    deploy ;;
    forward)   forward ;;
    status)    status ;;
    ollama)    ollama_check ;;
    down)      cluster_down ;;
    reset)     reset ;;
    *)
        echo "Unknown command: $cmd"
        echo "Usage: $0 {up|build|deploy|forward|status|ollama|down|reset}"
        exit 1
        ;;
esac
