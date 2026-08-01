"""Stage 38 public checkpoint for Center Hill CWMS catalog identities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from data_agent.uwm.geospatial_kernel_v2 import (
    cwms_component_discharge_catalog as catalog_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_hydraulic_boundary_falsification as stage37,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_hydraulic_boundary_response as stage36,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE38_ROOT = "data/geotransport_v0_1/stage38_center_hill_cwms_component_discharge_catalog"
DEFAULT_STAGE38_ROOT = REPO_ROOT / STAGE38_ROOT
RAW_CATALOG_PATH = f"{STAGE38_ROOT}/raw/center_hill_timeseries_catalog.json"
ACQUISITION_MANIFEST_PATH = f"{STAGE38_ROOT}/catalog_acquisition_manifest.json"
STAGE37_LEDGER_PATH = f"{stage37.STAGE37_ROOT}/hydraulic_boundary_falsification_ledger.json"
STAGE37_GATES_PATH = (
    "benchmarks/geotransport_v0_1/stage37_hydraulic_boundary_falsification_gates.json"
)
CATALOG_URL = (
    "https://cwms-data.usace.army.mil/cwms-data/catalog/TIMESERIES"
    "?office=LRN&page-size=500&like=%2ACENTER_HILL%2A"
    "&include-aliases=true"
)
EXPECTED_RAW_SHA256 = "845f357258d6c2729363df7eb0ba85735a35dbdfc82e8e455d34a1f1c66a2312"
EXPECTED_RAW_SIZE_BYTES = 62_337
EXPECTED_STAGE37_LEDGER_SHA256 = "2bad541ec95387ca57bdf63a916b72c95a50db346befa96de77f56f0d1a7a989"
EXPECTED_STAGE37_GATES_SHA256 = "f1326a8b2ae2e766b71556697849fe5ea84daa4b706337be1b2f08c0aa81e71d"
SCHEMA = "gwm.geotransport.public_cwms_component_discharge_catalog.v1"
STATUS = "stage38_cwms_component_discharge_catalog_checkpoint_admitted"


@dataclass(frozen=True)
class PublicCWMSComponentDischargeCatalogLedger:
    catalog_operator_artifact: dict[str, object]
    raw_catalog_artifact: dict[str, object]
    acquisition_manifest_artifact: dict[str, object]
    stage37_ledger_artifact: dict[str, object]
    stage37_gates_artifact: dict[str, object]
    catalog_evidence: catalog_operator.CWMSComponentDischargeCatalogEvidence
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            self.raw_catalog_artifact["sha256"] != EXPECTED_RAW_SHA256
            or self.raw_catalog_artifact["size_bytes"] != EXPECTED_RAW_SIZE_BYTES
            or self.stage37_ledger_artifact["sha256"] != EXPECTED_STAGE37_LEDGER_SHA256
            or self.stage37_gates_artifact["sha256"] != EXPECTED_STAGE37_GATES_SHA256
            or len(self.catalog_evidence.components) != 4
        ):
            raise ValueError("public_cwms_component_catalog_ledger_invalid")

    def require_historical_values(self) -> None:
        self.catalog_evidence.require_historical_values()

    def require_continuous_coverage(self) -> None:
        self.catalog_evidence.require_continuous_coverage()

    def require_gate_command(self) -> None:
        self.catalog_evidence.require_gate_command()

    def require_human_action(self) -> None:
        self.catalog_evidence.require_human_action()

    def require_causal_intervention(self) -> None:
        self.catalog_evidence.require_causal_intervention()

    def promote_to_runtime_operator(self) -> None:
        self.catalog_evidence.promote_to_runtime_operator()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "status": STATUS,
            "catalog_operator_artifact": self.catalog_operator_artifact,
            "raw_catalog_artifact": self.raw_catalog_artifact,
            "acquisition_manifest_artifact": (self.acquisition_manifest_artifact),
            "stage37_ledger_artifact": self.stage37_ledger_artifact,
            "stage37_gates_artifact": self.stage37_gates_artifact,
            "catalog_evidence": self.catalog_evidence.as_dict(),
            "provenance_id": self.provenance_id,
            "claim_boundary": {
                "stage37_negative_result_preserved": True,
                "catalog_metadata_only": True,
                "component_discharge_source_identities_admitted": True,
                "historical_values_acquired": False,
                "value_availability_or_continuity_admitted": False,
                "gate_commands_admitted": False,
                "human_actions_admitted": False,
                "causal_interventions_admitted": False,
                "runtime_operators_admitted": False,
            },
            "decision": {
                "stage37_negative_result_preserved": True,
                "catalog_checkpoint_admitted": True,
                "component_discharge_source_identity_count": 4,
                "component_discharge_source_identities_admitted": True,
                "component_values_acquisition_admitted": False,
                "coverage_continuity_admitted": False,
                "gate_commands_admitted": False,
                "human_actions_admitted": False,
                "causal_interventions_admitted": False,
                "runtime_operators_admitted": False,
                "separate_bounded_value_acquisition_plan_required": True,
            },
        }


def compile_public_cwms_component_discharge_catalog(
    source_root: Path = DEFAULT_STAGE38_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicCWMSComponentDischargeCatalogLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    raw_path = source / "raw/center_hill_timeseries_catalog.json"
    manifest_path = source / "catalog_acquisition_manifest.json"
    raw_artifact = _artifact(raw_path, root)
    manifest_artifact = _artifact(manifest_path, root)
    if (
        raw_artifact["sha256"] != EXPECTED_RAW_SHA256
        or raw_artifact["size_bytes"] != EXPECTED_RAW_SIZE_BYTES
    ):
        raise ValueError("public_cwms_component_catalog_raw_artifact_invalid")
    manifest = _read_json(manifest_path)
    _validate_manifest(manifest, raw_artifact)
    catalog = _read_json(raw_path)
    evidence = catalog_operator.compile_cwms_component_discharge_catalog(catalog)

    stage37_ledger_path = root / STAGE37_LEDGER_PATH
    stage37_gates_path = root / STAGE37_GATES_PATH
    stage37_ledger_artifact = _artifact(stage37_ledger_path, root)
    stage37_gates_artifact = _artifact(stage37_gates_path, root)
    if (
        stage37_ledger_artifact["sha256"] != EXPECTED_STAGE37_LEDGER_SHA256
        or stage37_gates_artifact["sha256"] != EXPECTED_STAGE37_GATES_SHA256
    ):
        raise ValueError("public_cwms_component_catalog_stage37_hash_invalid")
    stage37_compiled = stage37.compile_public_hydraulic_boundary_falsification(
        stage36_root=root / stage36.STAGE36_ROOT,
        repo_root=root,
    )
    if stage37_compiled.as_dict() != _read_json(stage37_ledger_path):
        raise ValueError("public_cwms_component_catalog_stage37_not_reproducible")
    stage37_gates = _read_json(stage37_gates_path)
    if (
        stage37_gates.get("all_gates_passed") is not True
        or stage37_gates.get("status") != "stage36_falsification_attributed_no_alternative_admitted"
        or sum(bool(value) for value in stage37_gates.get("gates", {}).values()) != 31
    ):
        raise ValueError("public_cwms_component_catalog_stage37_gates_invalid")

    operator_path = root / "data_agent/uwm/geospatial_kernel_v2/cwms_component_discharge_catalog.py"
    artifacts = (
        _artifact(operator_path, root),
        raw_artifact,
        manifest_artifact,
        stage37_ledger_artifact,
        stage37_gates_artifact,
    )
    digest = hashlib.sha256(
        "|".join(str(value["sha256"]) for value in artifacts).encode("ascii")
    ).hexdigest()
    return PublicCWMSComponentDischargeCatalogLedger(
        artifacts[0],
        artifacts[1],
        artifacts[2],
        artifacts[3],
        artifacts[4],
        evidence,
        f"center-hill-cwms-component-discharge-catalog:{digest}",
    )


def _validate_manifest(manifest: dict[str, object], raw_artifact: dict[str, object]) -> None:
    boundary = manifest.get("approved_request_boundary")
    artifact = manifest.get("artifact")
    claims = manifest.get("claim_boundary")
    if (
        manifest.get("schema") != "gwm.geotransport.stage38_cwms_catalog_acquisition.v1"
        or manifest.get("actual_request_count") != 1
        or manifest.get("actual_attempt_count") != 1
        or manifest.get("actual_download_bytes") != EXPECTED_RAW_SIZE_BYTES
        or not isinstance(boundary, dict)
        or boundary.get("exact_url") != CATALOG_URL
        or boundary.get("allowed_host") != "cwms-data.usace.army.mil"
        or boundary.get("maximum_request_count") != 1
        or boundary.get("maximum_attempts_per_request") != 3
        or boundary.get("maximum_bytes_per_request") != 1_000_000
        or boundary.get("maximum_total_download_bytes") != 1_000_000
        or boundary.get("workspace_or_private_data_sent") is not False
        or boundary.get("timeseries_values_requested") is not False
        or not isinstance(artifact, dict)
        or artifact.get("path") != raw_artifact["path"]
        or artifact.get("sha256") != raw_artifact["sha256"]
        or artifact.get("size_bytes") != raw_artifact["size_bytes"]
        or artifact.get("hash_verified") is not True
        or not isinstance(claims, dict)
        or claims.get("catalog_metadata_acquired") is not True
        or claims.get("timeseries_values_acquired") is not False
        or claims.get("gate_commands_admitted") is not False
        or claims.get("human_actions_admitted") is not False
        or claims.get("causal_interventions_admitted") is not False
        or claims.get("runtime_operators_admitted") is not False
    ):
        raise ValueError("public_cwms_component_catalog_manifest_invalid")


def _artifact(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("public_cwms_component_catalog_artifact_outside_repo") from exc
    body = resolved.read_bytes()
    return {
        "path": str(relative),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_cwms_component_catalog_json_object_required")
    return value
