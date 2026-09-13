from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJ_DATA_DIR = "/app/.venv/lib/python3.12/site-packages/pyproj/proj_dir/share/proj"


def test_dockerfile_exports_pyproj_data_dir_for_threaded_state_builds() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert f"PROJ_DATA={PYPROJ_DATA_DIR}" in dockerfile
    assert f"PROJ_LIB={PYPROJ_DATA_DIR}" in dockerfile
