from data_agent.finals_preflight import inspect_finals_host


def _build_resources(tmp_path, *, package_version="0.3.3", algorithm_version="2.2.3"):
    repo = tmp_path / "paper9"
    version_file = repo / "src" / "paper9_mnr" / "version.py"
    version_file.parent.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "paper9"\nversion = "{package_version}"\n',
        encoding="utf-8",
    )
    version_file.write_text(
        f'ALGORITHM_VERSION = "{algorithm_version}"\n', encoding="utf-8"
    )

    runs = tmp_path / "bishan"
    prepared = runs / "prepared"
    dltb = prepared / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"
    dltb.parent.mkdir(parents=True)
    dltb.write_bytes(b"shp")
    ensemble = prepared / "ensemble_seed0"
    ensemble.mkdir()
    (ensemble / "member_0.onnx").write_bytes(b"onnx")
    return repo, runs


def test_finals_host_preflight_passes_with_exact_versions_and_model(tmp_path):
    repo, runs = _build_resources(tmp_path)

    report = inspect_finals_host(
        paper9_repo=repo,
        bishan_runs=runs,
        model_tag="Gemma4:26b",
        ollama_tags=["Gemma4:26b", "Gemma4:12b"],
    )

    assert report["ready"] is True
    assert report["failed_checks"] == []
    ensemble = next(
        check for check in report["checks"] if check["name"] == "bishan_onnx_ensemble"
    )
    assert ensemble["actual"]["member_count"] == 1


def test_finals_host_preflight_fails_closed_on_version_or_model_mismatch(tmp_path):
    repo, runs = _build_resources(tmp_path, package_version="0.2.1")

    report = inspect_finals_host(
        paper9_repo=repo,
        bishan_runs=runs,
        model_tag="Gemma4:26b",
        ollama_tags=["Gemma4:12b"],
    )

    assert report["ready"] is False
    assert report["failed_checks"] == [
        "paper9_package_version",
        "ollama_model_tag",
    ]
