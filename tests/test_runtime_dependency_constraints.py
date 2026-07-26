from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version


REPO_ROOT = Path(__file__).resolve().parents[1]


def runtime_requirements() -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}
    for raw_line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            continue
        requirements[requirement.name.lower().replace("_", "-")] = requirement
    return requirements


def test_google_adk_23_runtime_dependency_floor_is_explicit() -> None:
    requirements = runtime_requirements()
    google_adk = requirements["google-adk"].specifier
    fastapi = requirements["fastapi"].specifier
    starlette = requirements["starlette"].specifier

    assert Version("2.3.0") in google_adk
    assert Version("0.133.0") in fastapi
    assert Version("0.132.0") not in fastapi
    assert Version("1.3.1") in starlette
    assert Version("0.50.0") not in starlette
    assert Version("2.0.0") not in starlette


def test_google_adk_23_does_not_pin_incompatible_langchain_google_genai_adapter() -> None:
    requirements = runtime_requirements()
    google_adk = requirements["google-adk"].specifier
    google_genai = requirements["google-genai"].specifier

    assert Version("2.3.0") in google_adk
    assert Version("2.8.0") in google_genai
    assert "langchain-google-genai" not in requirements


def test_python_313_cloud_storage_floor_is_compatible_with_vertex_ai() -> None:
    requirements = runtime_requirements()
    cloud_storage = requirements["google-cloud-storage"].specifier

    assert Version("3.10.0") in cloud_storage
    assert Version("3.7.0") not in cloud_storage


def test_chap_netcdf_reader_dependency_is_pinned() -> None:
    requirements = runtime_requirements()
    h5py = requirements["h5py"].specifier

    assert Version("3.15.1") in h5py
