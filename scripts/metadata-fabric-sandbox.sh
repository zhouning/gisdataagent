#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-gda-metadata-sandbox}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_DIR="${GDA_METADATA_FABRIC_CACHE:-${TMPDIR:-/tmp}/gda-metadata-fabric-cache}"
PROXY_URL="${GDA_METADATA_FABRIC_PROXY:-}"

OPENMETADATA_CHART_VERSION="1.13.1"
OPENMETADATA_CHART_SHA256="63081a24174e7061686780ab3186fa4e8076a0533e68b053acbcd2ba2000cf9a"
OPENMETADATA_CHART_URL="https://github.com/open-metadata/openmetadata-helm-charts/releases/download/openmetadata-1.13.1/openmetadata-1.13.1.tgz"
OPENMETADATA_IMAGE="docker.getcollate.io/openmetadata/server:1.13.1"
OPENMETADATA_ARM64_MANIFEST="sha256:13df068569cd975fddea58ee53127c48423eb582912b9384524e483a937ef538"
OPENMETADATA_IMAGE_BY_DIGEST="docker.getcollate.io/openmetadata/server@${OPENMETADATA_ARM64_MANIFEST}"
GRAVITINO_VERSION="1.3.0"
GRAVITINO_BINARY_SHA256="bed7e51701628f651bc53a03307eed16ae04c15b083ee9be40af7fb776b625cd"
GRAVITINO_SCHEMA_SHA256="7a2d605a677a462ca619dba594ce7ebcf500358345560ad084c1b67a25c722df"
GRAVITINO_BINARY_URL="https://github.com/apache/gravitino/releases/download/v1.3.0/gravitino-1.3.0-bin.tar.gz"
POSTGRESQL_JDBC_VERSION="42.7.0"
POSTGRESQL_JDBC_SHA256="90c39c97ac309b5767882f9beef913244da029204af2d2982c2b45bcfcb42624"
POSTGRESQL_JDBC_URL="https://jdbc.postgresql.org/download/postgresql-42.7.0.jar"
GRAVITINO_IMAGE="gda/gravitino:1.3.0-local-arm64"
HELM_VERSION="3.18.6"
HELM_DARWIN_ARM64_SHA256="48e30d236a1f334c6acb78501be5a851eaa2a267fefeb1131b6484eb2f9f30d7"
HELM_DARWIN_ARM64_URL="https://get.helm.sh/helm-v3.18.6-darwin-arm64.tar.gz"
HELM_BIN="${HELM_BIN:-}"
NODES=()

log() { printf '[metadata-sandbox] %s\n' "$*"; }
fail() { printf '[metadata-sandbox] ERROR: %s\n' "$*" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 not found in PATH"
}

file_sha256() {
    shasum -a 256 "$1" | awk '{print $1}'
}

verify_file() {
    local path="$1" expected="$2" actual
    [ -f "$path" ] || return 1
    actual="$(file_sha256 "$path")"
    [ "$actual" = "$expected" ]
}

download_verified() {
    local url="$1" destination="$2" expected="$3" temporary
    if verify_file "$destination" "$expected"; then
        log "using verified cache: $destination"
        return 0
    fi
    mkdir -p "$(dirname "$destination")"
    temporary="$(mktemp "${destination}.download.XXXXXX")"
    if [ -n "$PROXY_URL" ]; then
        HTTPS_PROXY="$PROXY_URL" HTTP_PROXY="$PROXY_URL" \
            curl -fL --retry 3 --connect-timeout 15 -o "$temporary" "$url"
    else
        curl -fL --retry 3 --connect-timeout 15 -o "$temporary" "$url"
    fi
    if ! verify_file "$temporary" "$expected"; then
        rm -f "$temporary"
        fail "checksum mismatch for $url"
    fi
    mv "$temporary" "$destination"
}

discover_nodes() {
    local node
    NODES=()
    while IFS= read -r node; do
        [ -n "$node" ] && NODES+=("$node")
    done < <(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
    [ "${#NODES[@]}" -gt 0 ] || fail "Docker Desktop Kubernetes has no nodes"
}

cluster_preflight() {
    local context architectures server_version
    context="$(kubectl config current-context)"
    [ "$context" = "docker-desktop" ] || \
        fail "current context is '$context'; expected docker-desktop"
    discover_nodes
    architectures="$(kubectl get nodes -o jsonpath='{range .items[*]}{.status.nodeInfo.architecture}{"\n"}{end}' | sort -u)"
    [ "$architectures" = "arm64" ] || \
        fail "all sandbox nodes must be arm64; observed: $architectures"
    server_version="$(kubectl version -o json | sed -n 's/.*"gitVersion":[[:space:]]*"\([^"]*\)".*/\1/p' | tail -1)"
    log "cluster context=$context server=$server_version nodes=${NODES[*]} architecture=arm64"
}

prepare_helm() {
    local archive helm_dir
    if [ -n "$HELM_BIN" ]; then
        [ -x "$HELM_BIN" ] || fail "HELM_BIN is not executable: $HELM_BIN"
        return 0
    fi
    if command -v helm >/dev/null 2>&1; then
        HELM_BIN="$(command -v helm)"
        return 0
    fi
    [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] || \
        fail "set HELM_BIN on platforms other than macOS arm64"
    archive="$CACHE_DIR/helm-v${HELM_VERSION}-darwin-arm64.tar.gz"
    helm_dir="$CACHE_DIR/helm-v${HELM_VERSION}"
    download_verified "$HELM_DARWIN_ARM64_URL" "$archive" "$HELM_DARWIN_ARM64_SHA256"
    mkdir -p "$helm_dir"
    tar -xOzf "$archive" darwin-arm64/helm > "$helm_dir/helm"
    chmod 0755 "$helm_dir/helm"
    HELM_BIN="$helm_dir/helm"
}

download_openmetadata_chart() {
    OPENMETADATA_CHART="$CACHE_DIR/openmetadata-${OPENMETADATA_CHART_VERSION}.tgz"
    download_verified \
        "$OPENMETADATA_CHART_URL" \
        "$OPENMETADATA_CHART" \
        "$OPENMETADATA_CHART_SHA256"
}

download_gravitino_release() {
    GRAVITINO_BINARY="$CACHE_DIR/gravitino-${GRAVITINO_VERSION}-bin.tar.gz"
    POSTGRESQL_JDBC="$CACHE_DIR/postgresql-${POSTGRESQL_JDBC_VERSION}.jar"
    download_verified \
        "$GRAVITINO_BINARY_URL" \
        "$GRAVITINO_BINARY" \
        "$GRAVITINO_BINARY_SHA256"
    download_verified \
        "$POSTGRESQL_JDBC_URL" \
        "$POSTGRESQL_JDBC" \
        "$POSTGRESQL_JDBC_SHA256"
}

ensure_secret() {
    local name="$1" key="$2" format="$3" secret_dir secret_file
    if kubectl -n "$NAMESPACE" get secret "$name" >/dev/null 2>&1; then
        log "preserving existing Secret/$name"
        return 0
    fi
    secret_dir="$(mktemp -d "${TMPDIR:-/tmp}/gda-metadata-secret.XXXXXX")"
    secret_file="$secret_dir/value"
    umask 077
    case "$format" in
        hex) openssl rand -hex 32 > "$secret_file" ;;
        fernet) openssl rand -base64 32 | tr '+/' '-_' > "$secret_file" ;;
        *) fail "unknown secret format: $format" ;;
    esac
    kubectl -n "$NAMESPACE" create secret generic "$name" \
        "--from-file=${key}=${secret_file}" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    rm -f "$secret_file"
    rmdir "$secret_dir"
    log "created external Secret/$name"
}

prepare_gravitino_schema() {
    local member schema_dir schema_file
    download_gravitino_release
    member="$(tar -tzf "$GRAVITINO_BINARY" | awk '/\/scripts\/postgresql\/schema-1.3.0-postgresql.sql$/ {print; exit}')"
    [ -n "$member" ] || fail "Gravitino release does not contain the PostgreSQL 1.3.0 schema"
    schema_dir="$(mktemp -d "${TMPDIR:-/tmp}/gda-gravitino-schema.XXXXXX")"
    schema_file="$schema_dir/001-schema.sql"
    tar -xOzf "$GRAVITINO_BINARY" "$member" > "$schema_file"
    verify_file "$schema_file" "$GRAVITINO_SCHEMA_SHA256" || \
        fail "Gravitino PostgreSQL schema checksum mismatch"
    kubectl -n "$NAMESPACE" create configmap metadata-gravitino-schema-1-3-0 \
        "--from-file=001-schema.sql=${schema_file}" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    rm -f "$schema_file"
    rmdir "$schema_dir"
    log "applied verified Gravitino PostgreSQL schema ConfigMap"
}

prepare_runtime_inputs() {
    kubectl apply -f "$ROOT/k8s/metadata-fabric-sandbox/namespace.yaml" >/dev/null
    ensure_secret metadata-openmetadata-postgresql password hex
    ensure_secret metadata-gravitino-postgresql password hex
    ensure_secret metadata-openmetadata-runtime fernet-key fernet
    prepare_gravitino_schema
}

load_gravitino_image() {
    local image_archive node
    discover_nodes
    image_archive="$(mktemp "${TMPDIR:-/tmp}/gda-gravitino-image.XXXXXX.tar")"
    docker save "$GRAVITINO_IMAGE" -o "$image_archive"
    for node in "${NODES[@]}"; do
        log "loading $GRAVITINO_IMAGE into $node"
        docker exec -i "$node" ctr -n=k8s.io images import - < "$image_archive" >/dev/null
    done
    rm -f "$image_archive"
}

load_openmetadata_image() {
    local image_archive node
    discover_nodes
    image_archive="$(mktemp "${TMPDIR:-/tmp}/gda-openmetadata-image.XXXXXX.tar")"
    docker save "$OPENMETADATA_IMAGE" -o "$image_archive"
    for node in "${NODES[@]}"; do
        log "loading $OPENMETADATA_IMAGE into $node"
        docker exec -i "$node" ctr -n=k8s.io images import - < "$image_archive" >/dev/null
    done
    rm -f "$image_archive"
}

prepare_openmetadata_image() {
    local platform repo_digest
    docker pull --platform linux/arm64 "$OPENMETADATA_IMAGE_BY_DIGEST"
    platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$OPENMETADATA_IMAGE_BY_DIGEST")"
    [ "$platform" = "linux/arm64" ] || \
        fail "OpenMetadata image must be linux/arm64; observed: $platform"
    repo_digest="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' \
        "$OPENMETADATA_IMAGE_BY_DIGEST")"
    printf '%s\n' "$repo_digest" | grep -Fqx "$OPENMETADATA_IMAGE_BY_DIGEST" || \
        fail "OpenMetadata image does not match the pinned ARM64 manifest"
    docker tag "$OPENMETADATA_IMAGE_BY_DIGEST" "$OPENMETADATA_IMAGE"
    load_openmetadata_image
}

build_gravitino_image() {
    local build_context
    download_gravitino_release
    build_context="$(mktemp -d "${TMPDIR:-/tmp}/gda-gravitino-build.XXXXXX")"
    cp "$ROOT/docker/gravitino-release/Dockerfile" "$build_context/Dockerfile"
    cp "$GRAVITINO_BINARY" "$build_context/gravitino-1.3.0-bin.tar.gz"
    cp "$POSTGRESQL_JDBC" "$build_context/postgresql-42.7.0.jar"
    docker build --platform linux/arm64 -t "$GRAVITINO_IMAGE" "$build_context"
    rm -f \
        "$build_context/Dockerfile" \
        "$build_context/gravitino-1.3.0-bin.tar.gz" \
        "$build_context/postgresql-42.7.0.jar"
    rmdir "$build_context"
    load_gravitino_image
}

deploy_foundation() {
    kubectl apply --dry-run=server -k "$ROOT/k8s/metadata-fabric-sandbox" >/dev/null
    kubectl apply -k "$ROOT/k8s/metadata-fabric-sandbox"
    kubectl -n "$NAMESPACE" rollout status \
        statefulset/metadata-openmetadata-postgresql --timeout=10m
    kubectl -n "$NAMESPACE" rollout status \
        statefulset/metadata-gravitino-postgresql --timeout=10m
    kubectl -n "$NAMESPACE" rollout status \
        statefulset/metadata-opensearch --timeout=15m
    kubectl -n "$NAMESPACE" rollout status \
        statefulset/metadata-gravitino --timeout=15m
}

deploy_openmetadata() {
    prepare_helm
    download_openmetadata_chart
    "$HELM_BIN" upgrade --install openmetadata "$OPENMETADATA_CHART" \
        --namespace "$NAMESPACE" \
        --values "$ROOT/helm/metadata-fabric-sandbox/openmetadata-values.yaml" \
        --history-max 3 \
        --wait \
        --timeout 20m
}

render() {
    prepare_helm
    download_openmetadata_chart
    kubectl kustomize "$ROOT/k8s/metadata-fabric-sandbox" >/dev/null
    "$HELM_BIN" template openmetadata "$OPENMETADATA_CHART" \
        --namespace "$NAMESPACE" \
        --values "$ROOT/helm/metadata-fabric-sandbox/openmetadata-values.yaml" \
        --skip-tests \
        >/dev/null
    log "Kustomize and OpenMetadata Helm rendering passed"
}

status() {
    kubectl -n "$NAMESPACE" get pods -o wide
    kubectl -n "$NAMESPACE" get services
    kubectl -n "$NAMESPACE" get pvc
    kubectl -n "$NAMESPACE" exec statefulset/metadata-gravitino -- \
        curl -fsS --max-time 15 http://127.0.0.1:8090/api/version
    printf '\n'
    kubectl -n "$NAMESPACE" exec deployment/openmetadata -c openmetadata -- \
        wget -qO- -T 15 http://127.0.0.1:8585/api/v1/system/health
    printf '\n'
}

validate() {
    if [ -x "$ROOT/.venv/bin/python" ]; then
        "$ROOT/.venv/bin/python" -m data_agent.metadata_fabric_sandbox validate
    else
        python -m data_agent.metadata_fabric_sandbox validate
    fi
}

require_cmd curl
require_cmd kubectl
require_cmd shasum

command_name="${1:-up}"
case "$command_name" in
    validate)
        validate
        ;;
    preflight)
        require_cmd docker
        cluster_preflight
        validate >/dev/null
        render
        ;;
    prepare)
        require_cmd openssl
        cluster_preflight
        prepare_runtime_inputs
        ;;
    build)
        require_cmd docker
        cluster_preflight
        build_gravitino_image
        ;;
    deploy)
        require_cmd docker
        cluster_preflight
        prepare_runtime_inputs
        prepare_openmetadata_image
        deploy_foundation
        deploy_openmetadata
        ;;
    render)
        render
        ;;
    status)
        cluster_preflight
        status
        ;;
    up)
        require_cmd docker
        require_cmd openssl
        cluster_preflight
        validate >/dev/null
        render
        prepare_runtime_inputs
        build_gravitino_image
        prepare_openmetadata_image
        deploy_foundation
        deploy_openmetadata
        status
        ;;
    *)
        fail "usage: $0 {validate|preflight|prepare|build|deploy|render|status|up}"
        ;;
esac
