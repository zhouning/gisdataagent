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


def test_non_root_runtime_precreates_writable_env_and_matplotlib_cache() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    copy_sources = dockerfile.index(
        "COPY --chown=agent:agent data_agent/ /app/data_agent/"
    )
    runtime_dirs = dockerfile.index(
        "install -o agent -g agent -m 0600 /dev/null /app/data_agent/.env"
    )

    assert runtime_dirs > copy_sources
    assert "install -d -o agent -g agent /app/.cache/matplotlib" in dockerfile
    assert "/app/.files" in dockerfile
    assert "ENV MPLCONFIGDIR=/app/.cache/matplotlib" in dockerfile


def test_non_root_runtime_precreates_chainlit_markdown_file() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "COPY --chown=agent:agent --chmod=0644 chainlit.md /app/chainlit.md"
        in dockerfile
    )
