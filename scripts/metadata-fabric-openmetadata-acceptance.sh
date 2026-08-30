#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
compose_file="${repository_root}/deploy/openmetadata-acceptance/compose.yml"
project_name="gda-om-acceptance-$$"
openmetadata_port="${GDA_OPENMETADATA_ACCEPTANCE_PORT:-18585}"
openmetadata_admin_port="${GDA_OPENMETADATA_ACCEPTANCE_ADMIN_PORT:-18586}"
control_port="${GDA_CONTROL_ACCEPTANCE_PORT:-15433}"
acceptance_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/gda-openmetadata-acceptance.XXXXXX")"
token_file="${acceptance_tmp_dir}/openmetadata-token"
lineage_evidence_file="${acceptance_tmp_dir}/lineage-evidence.json"
master_data_evidence_file="${acceptance_tmp_dir}/master-data-evidence.json"
provider_search_evidence_file="${acceptance_tmp_dir}/provider-search-evidence.json"
evidence_output_dir="${GDA_OPENMETADATA_ACCEPTANCE_EVIDENCE_DIR:-${repository_root}/.tmp/metadata-fabric}"
lineage_evidence_output_file="${evidence_output_dir}/openmetadata-lineage-acceptance-report.json"
master_data_evidence_output_file="${evidence_output_dir}/openmetadata-master-data-acceptance-report.json"
provider_search_evidence_output_file="${evidence_output_dir}/openmetadata-provider-search-acceptance-report.json"

export GDA_OPENMETADATA_ACCEPTANCE_PORT="${openmetadata_port}"
export GDA_OPENMETADATA_ACCEPTANCE_ADMIN_PORT="${openmetadata_admin_port}"
export GDA_CONTROL_ACCEPTANCE_PORT="${control_port}"

cleanup() {
  exit_code=$?
  trap - EXIT INT TERM
  if [[ ${exit_code} -ne 0 ]]; then
    docker compose -p "${project_name}" -f "${compose_file}" \
      logs --no-color --tail=200 || true
  fi
  if [[ "${GDA_OPENMETADATA_ACCEPTANCE_KEEP:-0}" != "1" ]]; then
    docker compose -p "${project_name}" -f "${compose_file}" \
      down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  if [[ -d "${acceptance_tmp_dir}" \
        && "$(basename "${acceptance_tmp_dir}")" == gda-openmetadata-acceptance.* ]]; then
    rm -rf -- "${acceptance_tmp_dir}"
  fi
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

docker compose -p "${project_name}" -f "${compose_file}" config --quiet
docker compose -p "${project_name}" -f "${compose_file}" pull --quiet
docker compose -p "${project_name}" -f "${compose_file}" up \
  --detach --wait --wait-timeout 600 openmetadata control-db

control_database_url="postgresql+psycopg://postgres:gda_acceptance_password@127.0.0.1:${control_port}/gda_control_acceptance"
uv run --with 'psycopg[binary]' \
  python "${repository_root}/scripts/accept_openmetadata_lineage_projection.py" \
  --openmetadata-url "http://127.0.0.1:${openmetadata_port}" \
  --control-database-url "${control_database_url}" \
  --token-file "${token_file}" \
  --evidence-file "${lineage_evidence_file}"

acceptance_python="${GDA_ACCEPTANCE_PYTHON:-${repository_root}/.venv/bin/python}"
if [[ ! -x "${acceptance_python}" ]]; then
  acceptance_python="python"
fi
  "${acceptance_python}" \
  "${repository_root}/scripts/accept_openmetadata_provider_search.py" \
  --openmetadata-url "http://127.0.0.1:${openmetadata_port}" \
  --token-file "${token_file}" \
  --source-only \
  --evidence-file "${provider_search_evidence_file}"

uv run --with 'psycopg[binary]' \
  python "${repository_root}/scripts/accept_openmetadata_master_data_projection.py" \
  --openmetadata-url "http://127.0.0.1:${openmetadata_port}" \
  --control-database-url "${control_database_url}" \
  --token-file "${token_file}" \
  --evidence-file "${master_data_evidence_file}"

install -d -m 700 "${evidence_output_dir}"
install -m 600 "${lineage_evidence_file}" "${lineage_evidence_output_file}"
install -m 600 "${master_data_evidence_file}" "${master_data_evidence_output_file}"
install -m 600 "${provider_search_evidence_file}" "${provider_search_evidence_output_file}"
echo "Lineage acceptance evidence: ${lineage_evidence_output_file}"
echo "Master-data acceptance evidence: ${master_data_evidence_output_file}"
echo "Provider-search acceptance evidence: ${provider_search_evidence_output_file}"
