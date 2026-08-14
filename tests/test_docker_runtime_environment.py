from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJ_DATA_DIR = "/app/.venv/lib/python3.12/site-packages/pyproj/proj_dir/share/proj"


def test_dockerfile_exports_pyproj_data_dir_for_threaded_state_builds() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert f"PROJ_DATA={PYPROJ_DATA_DIR}" in dockerfile
    assert f"PROJ_LIB={PYPROJ_DATA_DIR}" in dockerfile


def test_runtime_home_does_not_redirect_the_pip_build_cache_into_app() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.index("ENV HOME=/app") > dockerfile.index(
        "pip install -r requirements.txt"
    )


def test_runtime_user_is_numeric_for_kubernetes_run_as_non_root() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "groupadd --gid 10001 agent" in dockerfile
    assert "useradd --uid 10001 --gid agent" in dockerfile
    assert "USER 10001:10001" in dockerfile
