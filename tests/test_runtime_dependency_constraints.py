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


def profile_requirements(relative_path: str) -> dict[str, Requirement]:
    """Parse a Windows offline profile, resolving local ``-r`` includes."""

    requirements: dict[str, Requirement] = {}
    visited: set[Path] = set()

    def read(path: Path) -> None:
        path = path.resolve()
        if path in visited:
            return
        visited.add(path)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("-r "):
                read(path.parent / line[3:].strip())
                continue
            try:
                requirement = Requirement(line)
            except InvalidRequirement:
                continue
            requirements[requirement.name.lower().replace("_", "-")] = requirement

    read(REPO_ROOT / relative_path)
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


def test_windows_production_profile_matches_runtime_dependency_floor() -> None:
    requirements = profile_requirements(
        "deploy/windows-standalone/requirements-windows-production.txt"
    )

    assert Version("1.84.0") in requirements["litellm"].specifier
    assert Version("1.82.8") not in requirements["litellm"].specifier
    assert str(requirements["h5py"].specifier) == "==3.16.0"
    assert str(requirements["pymupdf"].specifier) == "==1.27.2.2"


def test_windows_core_profile_keeps_optional_readers_out() -> None:
    requirements = profile_requirements(
        "deploy/windows-standalone/requirements-windows-core.txt"
    )

    assert "h5py" not in requirements
    assert "pymupdf" not in requirements
