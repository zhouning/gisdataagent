#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
image_ref="${GDA_GRAVITINO_ACCEPTANCE_IMAGE:-gda/gravitino:1.3.0-local-arm64}"
expected_image_id="${GDA_GRAVITINO_ACCEPTANCE_IMAGE_ID:-sha256:d355dc7e92f9e3545d717f3eab2cbdf412115f2b82e1e544d7f6235c1eacd5a5}"
port="${GDA_GRAVITINO_ACCEPTANCE_PORT:-18090}"
run_id="${BASHPID:-$$}"
network_name="gda-gravitino-acceptance-${run_id}"
db_container="gda-gravitino-acceptance-db-${run_id}"
container_name="gda-gravitino-acceptance-${run_id}"
entity_volume="gda-gravitino-acceptance-entity-${run_id}"
db_volume="gda-gravitino-acceptance-db-${run_id}"
jdbc_password="${GDA_GRAVITINO_ACCEPTANCE_JDBC_PASSWORD:-gda_acceptance_password}"
evidence_file="${GDA_GRAVITINO_ACCEPTANCE_EVIDENCE_FILE:-${repository_root}/.tmp/metadata-fabric/gravitino-metadata-bridge-acceptance-report.json}"
state_file="${GDA_GRAVITINO_ACCEPTANCE_STATE_FILE:-${repository_root}/.tmp/metadata-fabric/gravitino-metadata-bridge-acceptance-state-${run_id}.json}"
python_bin="${repository_root}/.venv/bin/python"

actual_image_id="$(docker image inspect --format '{{.Id}}' "${image_ref}")"
if [[ "${actual_image_id}" != "${expected_image_id}" ]]; then
  printf 'Pinned Gravitino image mismatch: expected %s, got %s\n' \
    "${expected_image_id}" "${actual_image_id}" >&2
  exit 1
fi

cleanup() {
  exit_code=$?
  trap - EXIT INT TERM
  if [[ "${GDA_GRAVITINO_ACCEPTANCE_KEEP:-0}" != "1" ]]; then
    docker rm --force "${container_name}" "${db_container}" >/dev/null 2>&1 || true
    docker volume rm "${entity_volume}" "${db_volume}" >/dev/null 2>&1 || true
    docker network rm "${network_name}" >/dev/null 2>&1 || true
    rm -f "${state_file}"
  fi
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

docker network create "${network_name}" >/dev/null
docker volume create "${entity_volume}" >/dev/null
docker volume create "${db_volume}" >/dev/null

# The pinned image runs as UID 1000; named volumes start owned by root.
docker run --rm --user 0 --entrypoint /bin/sh \
  --volume "${entity_volume}:/var/lib/gda" "${image_ref}" \
  -c 'chown -R 1000:0 /var/lib/gda'

docker run --detach --name "${db_container}" \
  --network "${network_name}" --network-alias postgres \
  --volume "${db_volume}:/var/lib/postgresql/data" \
  --env "POSTGRES_PASSWORD=${jdbc_password}" \
  --env POSTGRES_DB=postgres \
  postgres:16-alpine >/dev/null

db_ready=0
for _ in $(seq 1 60); do
  if docker exec "${db_container}" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    db_ready=1
    break
  fi
  sleep 1
done
if [[ "${db_ready}" != "1" ]]; then
  docker logs --tail=120 "${db_container}" >&2 || true
  printf 'PostgreSQL did not become ready within the acceptance window\n' >&2
  exit 1
fi

start_gravitino() {
  docker run --detach --name "${container_name}" \
    --network "${network_name}" --network-alias gravitino \
    --publish "127.0.0.1:${port}:8090" \
    --volume "${entity_volume}:/var/lib/gda" \
    --env "GDA_GRAVITINO_JDBC_PASSWORD=${jdbc_password}" \
    "${image_ref}" sh -lc '
      cp -a /opt/gravitino/conf /tmp/gda-conf
      printf "%s\\n" \
        "gravitino.entity.store.relational.jdbcUrl = jdbc:h2:file:/var/lib/gda/entity-store" \
        "gravitino.iceberg-rest.catalog-backend = jdbc" \
        "gravitino.iceberg-rest.jdbc-driver = org.postgresql.Driver" \
        "gravitino.iceberg-rest.uri = jdbc:postgresql://postgres:5432/postgres" \
        "gravitino.iceberg-rest.jdbc-user = postgres" \
        "gravitino.iceberg-rest.jdbc-password = ${GDA_GRAVITINO_JDBC_PASSWORD}" \
        "gravitino.iceberg-rest.jdbc-initialize = true" \
        "gravitino.iceberg-rest.warehouse = /var/lib/gda/warehouse" \
        >> /tmp/gda-conf/gravitino.conf
      exec /opt/gravitino/bin/gravitino.sh --config /tmp/gda-conf run
    ' >/dev/null
}

wait_for_gravitino() {
  local ready=0
  for _ in $(seq 1 60); do
    if curl --silent --fail --max-time 5 "http://127.0.0.1:${port}/health" >/dev/null; then
      ready=1
      break
    fi
    sleep 2
  done
  if [[ "${ready}" != "1" ]]; then
    docker logs --tail=160 "${container_name}" >&2 || true
    printf 'Gravitino did not become healthy within the acceptance window\n' >&2
    exit 1
  fi
}

start_gravitino
wait_for_gravitino

"${python_bin}" \
  "${repository_root}/scripts/accept_gravitino_metadata_bridge.py" \
  --gravitino-url "http://127.0.0.1:${port}" \
  --evidence-file "${evidence_file}" \
  --image-ref "${image_ref}" \
  --image-id "${actual_image_id}" \
  --phase seed \
  --state-file "${state_file}" \
  --catalog-backend jdbc \
  --catalog-uri jdbc:postgresql://postgres:5432/postgres \
  --catalog-jdbc-driver org.postgresql.Driver \
  --catalog-jdbc-user postgres \
  --catalog-jdbc-password "${jdbc_password}" \
  --catalog-warehouse /var/lib/gda/warehouse

docker rm --force "${container_name}" >/dev/null
start_gravitino
wait_for_gravitino

runtime_metadata="$(printf '{"phase":"persistent-recovery","network":"%s","entity_store_volume":"%s","catalog_database_volume":"%s","postgres_image":"postgres:16-alpine"}' "${network_name}" "${entity_volume}" "${db_volume}")"
"${python_bin}" \
  "${repository_root}/scripts/accept_gravitino_metadata_bridge.py" \
  --gravitino-url "http://127.0.0.1:${port}" \
  --evidence-file "${evidence_file}" \
  --image-ref "${image_ref}" \
  --image-id "${actual_image_id}" \
  --phase recover \
  --state-file "${state_file}" \
  --catalog-backend jdbc \
  --catalog-uri jdbc:postgresql://postgres:5432/postgres \
  --catalog-jdbc-driver org.postgresql.Driver \
  --catalog-jdbc-user postgres \
  --catalog-jdbc-password "${jdbc_password}" \
  --catalog-warehouse /var/lib/gda/warehouse \
  --runtime-metadata "${runtime_metadata}"
