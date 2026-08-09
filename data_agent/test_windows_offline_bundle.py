"""Regression tests for Windows standalone deployment artifacts."""

import json
from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace

import pytest

DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy" / "windows-standalone"


_BUILDER_SPEC = importlib.util.spec_from_file_location(
    "gda_windows_bundle_builder", DEPLOY_DIR / "build_offline_bundle.py"
)
assert _BUILDER_SPEC and _BUILDER_SPEC.loader
_BUILDER = importlib.util.module_from_spec(_BUILDER_SPEC)
_BUILDER_SPEC.loader.exec_module(_BUILDER)

_VERIFIER_SPEC = importlib.util.spec_from_file_location(
    "gda_windows_bundle_verifier", DEPLOY_DIR.parent.parent / "scripts" / "verify_windows_offline_bundle.py"
)
assert _VERIFIER_SPEC and _VERIFIER_SPEC.loader
_VERIFIER = importlib.util.module_from_spec(_VERIFIER_SPEC)
_VERIFIER_SPEC.loader.exec_module(_VERIFIER)


def test_powershell_scripts_with_utf8_text_have_a_bom_for_windows_ps5():
    """Windows PowerShell 5.1 must decode UTF-8 deployment scripts correctly."""

    expected_bom = b"\xef\xbb\xbf"
    scripts = (
        "install_offline_bundle.ps1",
        "start_gda.ps1",
        "stop_gda.ps1",
    )
    for name in scripts:
        assert (DEPLOY_DIR / name).read_bytes().startswith(expected_bom), name


def test_windows_wheel_validator_accepts_abi3_wheels_for_python_311():
    wheels = [
        Path("argon2_cffi_bindings-25.1.0-cp39-abi3-win_amd64.whl"),
        Path("protobuf-6.33.6-cp310-abi3-win_amd64.whl"),
        Path("psutil-7.1.3-cp37-abi3-win_amd64.whl"),
    ]

    _BUILDER._validate_windows_wheels("test", wheels)


def test_windows_wheel_validator_rejects_old_non_abi3_cpython_wheels():
    wheels = [Path("example-1.0-cp310-none-win_amd64.whl")]

    with pytest.raises(ValueError, match="incompatible"):
        _BUILDER._validate_windows_wheels("test", wheels)


def test_builder_accepts_native_lite_profile(tmp_path):
    """native-lite must pass profile validation before artifact validation."""

    vendor_root = tmp_path / "vendor"
    vendor_root.mkdir()
    with pytest.raises(FileNotFoundError, match="python_runtime"):
        _BUILDER.build("native-lite", vendor_root, tmp_path / "bundle.zip")


def test_manifest_native_lite_matches_enhanced_single_host_stack():
    manifest = json.loads((DEPLOY_DIR / "bundle-manifest.json").read_text(encoding="utf-8"))

    assert "native-lite" in manifest["profiles"]
    assert set(manifest["profiles"]["native-lite"]["required_artifacts"]) == set(
        manifest["profiles"]["production"]["required_artifacts"]
    )
    assert "PostGIS" in manifest["profiles"]["native-lite"]["description"]
    assert "分布式" in manifest["profiles"]["native-lite"]["description"]


def test_native_lite_uses_external_lm_studio_instead_of_bundled_models():
    manifest = json.loads((DEPLOY_DIR / "bundle-manifest.json").read_text(encoding="utf-8"))
    required = set(manifest["profiles"]["native-lite"]["required_artifacts"])
    installer = (DEPLOY_DIR / "install_offline_bundle.ps1").read_text(encoding="utf-8-sig")
    starter = (DEPLOY_DIR / "start_gda.ps1").read_text(encoding="utf-8-sig")
    env_template = (DEPLOY_DIR / "templates" / "gda.env").read_text(encoding="utf-8")

    assert required.isdisjoint({"ollama_installer", "ollama_llm_model", "embedding_model"})
    assert "Install-Ollama" not in installer
    assert "OLLAMA_" not in env_template
    assert "ollama" not in starter.lower()
    assert "LM_STUDIO_BASE_URL=__LM_STUDIO_BASE_URL__" in env_template
    assert "LM_STUDIO_MODEL=__LM_STUDIO_CHAT_MODEL__" in env_template
    assert "LM_STUDIO_EMBEDDING_MODEL=__LM_STUDIO_EMBEDDING_MODEL__" in env_template
    assert "LM_STUDIO_EMBEDDING_DIMENSION=__LM_STUDIO_EMBEDDING_DIMENSION__" in env_template


def test_native_lite_is_wired_through_all_windows_scripts():
    installer = (DEPLOY_DIR / "install_offline_bundle.ps1").read_text(encoding="utf-8-sig")
    starter = (DEPLOY_DIR / "start_gda.ps1").read_text(encoding="utf-8-sig")
    verifier = (DEPLOY_DIR.parent.parent / "scripts" / "verify_windows_offline_bundle.py").read_text(
        encoding="utf-8"
    )

    assert "ValidateSet('core', 'native-lite', 'production')" in installer
    assert "$script:IsNativeStack" in installer
    assert "$Profile -eq 'production'" not in installer
    assert "$state.profile -eq 'production'" not in starter
    assert "choices=(\"core\", \"native-lite\", \"production\")" in verifier


def test_native_lite_docs_match_manifest_and_runtime_paths():
    manifest = json.loads((DEPLOY_DIR / "bundle-manifest.json").read_text(encoding="utf-8"))
    postgis_source = next(
        item["source"] for item in manifest["artifacts"] if item["id"] == "postgis_installer"
    )
    readme = (DEPLOY_DIR / "README.md").read_text(encoding="utf-8")
    vendor_readme = (DEPLOY_DIR / "vendor" / "README.md").read_text(encoding="utf-8")
    diagnostics = (DEPLOY_DIR / "collect_diagnostics.ps1").read_text(encoding="utf-8-sig")

    assert postgis_source in readme
    assert postgis_source.removeprefix("vendor/") in vendor_readme
    assert "D:\\GDA_DATA\\file_lake" in readme
    assert "D:\\GDA_FILE_LAKE" not in readme
    assert "DSN|URI" in diagnostics


def test_postgis_default_installer_arguments_use_nsis_silent_switch():
    installer = (DEPLOY_DIR / "install_offline_bundle.ps1").read_text(encoding="utf-8-sig")

    assert "else { '/S' }" in installer
    assert "/SILENT" not in installer


def test_native_service_verifier_checks_lm_studio_models_and_embedding_dimension(
    tmp_path, monkeypatch
):
    model_root = tmp_path / "payload" / "models" / "paper9"
    model_root.mkdir(parents=True)
    (model_root / "model.onnx").write_bytes(b"model")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.8:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "qwen-instruct")
    monkeypatch.setenv("LM_STUDIO_EMBEDDING_MODEL", "text-embedding-qwen")
    monkeypatch.setenv("LM_STUDIO_EMBEDDING_DIMENSION", "768")

    def fake_request(path, payload=None):
        if path == "models":
            return {"data": [{"id": "qwen-instruct"}, {"id": "text-embedding-qwen"}]}
        assert path == "embeddings"
        assert payload == {"model": "text-embedding-qwen", "input": ["GIS"]}
        return {"data": [{"index": 0, "embedding": [0.0] * 768}]}

    monkeypatch.setattr(_VERIFIER, "_request_lm_studio", fake_request)
    checks = []

    _VERIFIER.verify_native_services(tmp_path, "install", False, checks)

    by_name = {item["name"]: item for item in checks}
    assert by_name["lm_studio_models"]["status"] == "pass"
    assert by_name["lm_studio_embedding"]["status"] == "pass"
    assert all("ollama" not in item["name"] for item in checks)


def test_native_service_verifier_rejects_non_768_lm_studio_configuration(
    tmp_path, monkeypatch
):
    model_root = tmp_path / "payload" / "models" / "paper9"
    model_root.mkdir(parents=True)
    (model_root / "model.onnx").write_bytes(b"model")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.8:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "qwen-instruct")
    monkeypatch.setenv("LM_STUDIO_EMBEDDING_MODEL", "text-embedding-qwen")
    monkeypatch.setenv("LM_STUDIO_EMBEDDING_DIMENSION", "1024")

    checks = []
    _VERIFIER.verify_native_services(tmp_path, "install", False, checks)

    by_name = {item["name"]: item for item in checks}
    assert by_name["lm_studio_configuration"]["status"] == "fail"


def test_intent_router_uses_lm_studio_base_and_openai_provider(monkeypatch):
    from data_agent import intent_router
    from data_agent.model_gateway import ModelRegistry

    monkeypatch.setenv("LM_STUDIO_MODEL", "qwen/qwen3-32b")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://10.0.0.8:1234/v1")
    ModelRegistry.reset()

    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="GENERAL|ok|TOOLS:none"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=fake_completion))
    result = intent_router._route_via_litellm("请查询地类", "qwen/qwen3-32b")

    assert result == ("GENERAL|ok|TOOLS:none", 1, 2)
    assert calls[0]["model"] == "openai/qwen/qwen3-32b"
    assert calls[0]["api_base"] == "http://10.0.0.8:1234/v1"
