import shutil
from pathlib import Path

import yaml

from data_agent.metadata_fabric_sandbox import (
    DEFAULT_MANIFEST_DIR,
    DEFAULT_OPENMETADATA_VALUES,
    GRAVITINO_LOCAL_IMAGE,
    NAMESPACE,
    build_sandbox_report,
)


def _copy_manifests(tmp_path: Path) -> Path:
    destination = tmp_path / "metadata-fabric-sandbox"
    shutil.copytree(DEFAULT_MANIFEST_DIR, destination)
    return destination


def test_foundation_sandbox_contract_is_valid_but_not_live_evidence():
    report = build_sandbox_report()

    assert report["status"] == "valid"
    assert report["namespace"] == NAMESPACE
    assert report["static_contract_verified"] is True
    assert report["persistence_configured"] is True
    assert report["live_deployment_verified"] is False
    assert report["production_provider_verified"] is False
    assert report["production_table_catalog_provider_verified"] is False
    assert report["oidc_verified"] is False
    assert report["backup_restore_verified"] is False
    assert report["upgrade_verified"] is False
    assert report["writes_to_gda_enabled"] is False
    assert report["providers"]["gravitino"]["image"] == GRAVITINO_LOCAL_IMAGE
    assert report["providers"]["gravitino"]["image_provenance"] == (
        "local_release_build"
    )
    assert len(set(report["database_pvcs"].values())) == 2
    assert report["errors"] == []


def test_validator_rejects_committed_secret_external_service_and_latest_image(
    tmp_path,
):
    manifest_dir = _copy_manifests(tmp_path)
    unsafe = manifest_dir / "unsafe.yaml"
    unsafe.write_text(
        yaml.safe_dump_all(
            [
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": "unsafe", "namespace": NAMESPACE},
                    "stringData": {"password": "leaked"},
                },
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "metadata": {"name": "unsafe", "namespace": NAMESPACE},
                    "spec": {"type": "LoadBalancer", "ports": [{"port": 80}]},
                },
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"name": "unsafe", "namespace": NAMESPACE},
                    "spec": {
                        "template": {
                            "spec": {
                                "serviceAccountName": "unsafe",
                                "automountServiceAccountToken": False,
                                "containers": [
                                    {"name": "unsafe", "image": "example/unsafe:latest"}
                                ],
                            }
                        }
                    },
                },
            ],
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    kustomization_path = manifest_dir / "kustomization.yaml"
    kustomization = yaml.safe_load(kustomization_path.read_text(encoding="utf-8"))
    kustomization["resources"].append("unsafe.yaml")
    kustomization_path.write_text(
        yaml.safe_dump(kustomization, sort_keys=False), encoding="utf-8"
    )

    report = build_sandbox_report(manifest_dir=manifest_dir)

    assert report["status"] == "invalid"
    assert "Secret objects and secret contents must not be committed" in report["errors"]
    assert "Service/unsafe must remain ClusterIP" in report["errors"]
    assert "Deployment/unsafe must not use a latest image" in report["errors"]


def test_validator_rejects_openmetadata_write_path_oidc_and_inline_fernet(tmp_path):
    values = yaml.safe_load(DEFAULT_OPENMETADATA_VALUES.read_text(encoding="utf-8"))
    config = values["openmetadata"]["config"]
    config["pipelineServiceClientConfig"]["enabled"] = True
    config["authentication"]["oidcConfiguration"]["enabled"] = True
    config["fernetkey"] = {"value": "unsafe-inline-value"}
    unsafe_values = tmp_path / "values.yaml"
    unsafe_values.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")

    report = build_sandbox_report(openmetadata_values_path=unsafe_values)

    assert report["status"] == "invalid"
    assert "OpenMetadata pipeline client must be disabled in M2" in report["errors"]
    assert "OpenMetadata OIDC must remain disabled until separately verified" in report[
        "errors"
    ]
    assert "OpenMetadata Fernet key must use the external runtime Secret" in report[
        "errors"
    ]


def test_validator_rejects_a_pullable_openmetadata_tag(tmp_path):
    values = yaml.safe_load(DEFAULT_OPENMETADATA_VALUES.read_text(encoding="utf-8"))
    values["image"]["pullPolicy"] = "IfNotPresent"
    unsafe_values = tmp_path / "values.yaml"
    unsafe_values.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")

    report = build_sandbox_report(openmetadata_values_path=unsafe_values)

    assert report["status"] == "invalid"
    assert "OpenMetadata pinned image must be preloaded with pullPolicy Never" in report[
        "errors"
    ]


def test_validator_rejects_quota_without_rolling_update_headroom(tmp_path):
    manifest_dir = _copy_manifests(tmp_path)
    namespace_path = manifest_dir / "namespace.yaml"
    documents = list(yaml.safe_load_all(namespace_path.read_text(encoding="utf-8")))
    quota = next(item for item in documents if item.get("kind") == "ResourceQuota")
    quota["spec"]["hard"]["limits.cpu"] = "12"
    namespace_path.write_text(
        yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8"
    )

    report = build_sandbox_report(manifest_dir=manifest_dir)

    assert report["status"] == "invalid"
    assert (
        "sandbox CPU quota must reserve bounded OpenMetadata rolling-update headroom"
        in report["errors"]
    )
