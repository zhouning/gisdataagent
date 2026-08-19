from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.chongqing_customer_data_quality import (
    build_chongqing_customer_data_quality_report,
)
from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    ChongqingFederatedCompensationDeploymentError,
    ChongqingFederatedCompensationSourceCatalog,
    build_chongqing_federated_compensation_deployment_binding,
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)


def test_chongqing_customer_source_catalog_pins_artifacts_mappings_and_ontology() -> None:
    catalog = build_chongqing_federated_compensation_source_catalog()

    assert catalog.customer_bundle_id == "natural-resource-ontology-customer-demo-v1"
    assert catalog.customer_bundle_version == "1.0.0"
    assert catalog.ontology_package_id == "natural-resource-one-map:2.3.0:587915868b1221af"
    assert catalog.customer_data_quality_report_sha256 == (
        build_chongqing_customer_data_quality_report().report_sha256
    )
    assert len(catalog.artifacts) == 5
    assert len(catalog.sources) == 10
    assert len(catalog.field_mappings) == 6
    document = json.dumps(catalog.model_dump(mode="json"), sort_keys=True)
    assert "relative_path" not in document
    assert "heping_changed_parcels.geojson" in document


def test_source_catalog_fingerprint_drift_fails_closed() -> None:
    catalog = build_chongqing_federated_compensation_source_catalog()
    drifted = catalog.model_copy(update={"field_mapping_set_sha256": "f" * 64})

    with pytest.raises(ValidationError, match="field mapping set fingerprint"):
        ChongqingFederatedCompensationSourceCatalog.model_validate(
            drifted.model_dump(mode="python")
        )


def test_deployment_binding_joins_customer_catalog_to_sealed_run_without_execution() -> None:
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    catalog = build_chongqing_federated_compensation_source_catalog()

    binding = build_chongqing_federated_compensation_deployment_binding(
        intent,
        plan_set,
        materialization,
        catalog,
    )

    assert tuple(item.position for item in binding.items) == (0, 1, 2)
    assert binding.recovery_source_snapshot_sha256 == intent.source_snapshot_sha256
    assert binding.field_mapping_set_sha256 == catalog.field_mapping_set_sha256
    assert binding.customer_data_quality_report_sha256 == (
        catalog.customer_data_quality_report_sha256
    )
    assert binding.provider_dispatch_performed is False
    assert binding.checkpoint_authority_write_performed is False
    assert binding.compensation_completion_recorded is False

    drifted_materialization = materialization.model_copy(update={"plan_set_sha256": "f" * 64})
    with pytest.raises(
        ChongqingFederatedCompensationDeploymentError,
        match="sealed contract",
    ):
        build_chongqing_federated_compensation_deployment_binding(
            intent,
            plan_set,
            drifted_materialization,
            catalog,
        )


def test_source_catalog_rejects_bundle_when_quality_report_cannot_be_sealed(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "customer-bundle"
    from data_agent.chongqing_entity_link_baseline import CUSTOMER_BUNDLE_DIR

    shutil.copytree(CUSTOMER_BUNDLE_DIR, bundle_dir)
    artifact_name = "heping_changed_parcels.geojson"
    artifact_path = bundle_dir / artifact_name
    document = json.loads(artifact_path.read_text(encoding="utf-8"))
    document["features"][0]["properties"].pop("JQDLDM")
    artifact_path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["name"] == artifact_name)
    entry["size"] = artifact_path.stat().st_size
    entry["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ChongqingFederatedCompensationDeploymentError,
        match="aggregate quality",
    ):
        build_chongqing_federated_compensation_source_catalog(bundle_dir=bundle_dir)
