#!/usr/bin/env bash
set -euo pipefail

database_dir="/fuseki/databases/ontology"
bootstrap_path="/opt/fuseki/bootstrap/ontology.ttl.gz"
digest_path="/fuseki/databases/.ontology-bootstrap.sha256"
bootstrap_digest="$(sha256sum "${bootstrap_path}" | awk '{print $1}')"
installed_digest="$(test -f "${digest_path}" && head -n 1 "${digest_path}" || true)"

if [[ "${bootstrap_digest}" != "${installed_digest}" ]]; then
    mkdir -p "${database_dir}"
    find "${database_dir}" -mindepth 1 -delete
    "${JENA_HOME}/bin/tdb2.tdbloader" --loc="${database_dir}" "${bootstrap_path}"
    printf '%s\n' "${bootstrap_digest}" > "${digest_path}"
fi

exec "${FUSEKI_HOME}/fuseki-server" \
    --config="${FUSEKI_HOME}/config.ttl" \
    --port=3030
