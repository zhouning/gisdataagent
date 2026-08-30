from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "docker-compose.yml"
K8S_FUSEKI = ROOT / "k8s/overlays/ontology-fuseki/fuseki-statefulset.yaml"
K8S_PROJECTION = ROOT / "k8s/overlays/ontology-fuseki/ontology-projection-job.yaml"
FUSEKI_ENTRYPOINT = ROOT / "docker/ontology-fuseki/entrypoint.sh"


def test_dockerignore_excludes_heavy_local_build_and_runtime_artifacts():
    text = DOCKERIGNORE.read_text(encoding="utf-8")

    for required in [
        "frontend/node_modules/",
        "frontend/dist/",
        "frontend/tsconfig.tsbuildinfo",
        "data_agent/test_data/",
        "data_agent/uploads/",
        "data_agent/__pycache__/",
        "outputs/",
        "notebooks/",
        "gis_data_agent.egg-info/",
    ]:
        assert required in text


def test_dockerfile_uses_buildkit_pip_cache_for_dependency_layer():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert text.startswith("# syntax=docker/dockerfile:")
    assert "--mount=type=cache,target=/root/.cache/pip" in text
    assert "pip install --no-cache-dir" not in text
    assert "PIP_DISABLE_PIP_VERSION_CHECK=1" in text


def test_ontology_packages_are_runtime_readable_but_not_runtime_writable():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "chown -R root:agent /app/data_agent/ontology/packages" in text
    assert "chmod -R u=rwX,g=rX,o= /app/data_agent/ontology/packages" in text


def test_ontology_projection_follows_active_pointer_instead_of_a_version_literal():
    text = COMPOSE.read_text(encoding="utf-8")
    projection = text.split("  ontology-projection:", 1)[1].split(
        "\n  # ---------------------------------------------------------------------------", 1
    )[0]

    assert "--package-dir" not in projection
    assert "natural_resource_one_map/1.0.2" not in projection


def test_fuseki_upgrade_replaces_nested_tdb_projection_contents():
    entrypoint = FUSEKI_ENTRYPOINT.read_text(encoding="utf-8")

    assert 'find "${database_dir}" -mindepth 1 -delete' in entrypoint
    assert "-maxdepth 1" not in entrypoint


def test_kubernetes_ontology_projection_uses_governed_2_3_0_read_image():
    statefulset = K8S_FUSEKI.read_text(encoding="utf-8")
    projection = K8S_PROJECTION.read_text(encoding="utf-8")

    assert "gisdataagent-ontology-fuseki:5.5.0-nr-2.3.0" in statefulset
    assert "stain/jena-fuseki" not in statefulset
    assert "ontology-projection-2-3-0" in projection
    assert "537245" in projection
    assert "natural_resource_one_map/1.0.2" not in projection
    assert "graph-store-endpoint" not in projection
