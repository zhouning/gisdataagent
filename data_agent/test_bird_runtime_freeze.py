"""A stale runner or conflicting freeze declaration must prevent evaluation."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/nl2sql_bench_bird/verify_runtime_freeze.py"
spec = importlib.util.spec_from_file_location("bird_freeze_verification", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
verify_runtime_freeze = module.verify_runtime_freeze


def write_fixture(root):
    (root / "run_frozen.py").write_text("print('original')\n")
    (root / "settings.json").write_text('{"model":"local"}')
    digest = lambda name: hashlib.sha256((root / name).read_bytes()).hexdigest()
    dependencies = {"run_frozen.py": digest("run_frozen.py")}
    preparation = {"python_file_count": 1, "nonpython_sha256": {
        "settings.json": digest("settings.json"), "run_frozen.py": digest("run_frozen.py")}}
    (root / "dependency_freeze.json").write_text(json.dumps(dependencies))
    (root / "freeze_preparation.json").write_text(json.dumps(preparation))
    return dependencies, preparation


def test_freeze_validates_identical_overlapping_runner_declarations(tmp_path):
    write_fixture(tmp_path)
    report = verify_runtime_freeze(tmp_path)
    assert report["all_frozen_files_verified"]
    assert report["overlapping_declarations_verified"] == 1


def test_freeze_rejects_resource_map_that_masks_stale_runner_digest(tmp_path):
    dependencies, preparation = write_fixture(tmp_path)
    (tmp_path / "run_frozen.py").write_text("print('new output path')\n")
    preparation["nonpython_sha256"]["run_frozen.py"] = hashlib.sha256((tmp_path / "run_frozen.py").read_bytes()).hexdigest()
    (tmp_path / "freeze_preparation.json").write_text(json.dumps(preparation))
    with pytest.raises(ValueError, match="Conflicting frozen declarations: run_frozen.py"):
        verify_runtime_freeze(tmp_path)


@pytest.mark.parametrize("changed", ["run_frozen.py", "settings.json"])
def test_freeze_rejects_changed_python_or_resource(tmp_path, changed):
    write_fixture(tmp_path)
    (tmp_path / changed).write_text("changed")
    with pytest.raises(ValueError, match="differs"):
        verify_runtime_freeze(tmp_path)


def test_freeze_rejects_path_outside_runtime_even_if_digest_matches(tmp_path):
    dependencies, preparation = write_fixture(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "_outside.py")
    outside.write_text("external")
    dependencies = {"../" + outside.name: hashlib.sha256(outside.read_bytes()).hexdigest()}
    (tmp_path / "dependency_freeze.json").write_text(json.dumps(dependencies))
    with pytest.raises(ValueError, match="Frozen dependency differs"):
        verify_runtime_freeze(tmp_path)


def test_freeze_rejects_incomplete_dependency_count(tmp_path):
    dependencies, preparation = write_fixture(tmp_path)
    preparation["python_file_count"] = 2
    (tmp_path / "freeze_preparation.json").write_text(json.dumps(preparation))
    with pytest.raises(ValueError, match="count differs"):
        verify_runtime_freeze(tmp_path)


def persistence_module(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    import persist_product_run
    return persist_product_run


def test_dependency_preservation_is_complete_and_excludes_undeclared_credentials(tmp_path, monkeypatch):
    runtime, destination = tmp_path / "runtime", tmp_path / "saved"
    runtime.mkdir()
    destination.mkdir()
    write_fixture(runtime)
    (runtime / ".bird.env").write_text("PASSWORD=do-not-copy")
    persistence = persistence_module(monkeypatch)
    report = persistence.preserve_dependencies(runtime, destination)
    assert report["all_frozen_files_verified"]
    assert report["copied_declared_files"] == 2
    assert not list(destination.rglob("*.env"))
    assert verify_runtime_freeze(destination / "frozen_dependencies")["python_files_verified"] == 1
    with pytest.raises(FileExistsError):
        persistence.preserve_dependencies(runtime, destination)


def test_dependency_preservation_rejects_files_changed_during_copy(tmp_path, monkeypatch):
    runtime, destination = tmp_path / "runtime", tmp_path / "saved"
    runtime.mkdir()
    destination.mkdir()
    write_fixture(runtime)
    persistence = persistence_module(monkeypatch)
    real_copy = persistence.shutil.copy2
    def changed_copy(source, target):
        result = real_copy(source, target)
        if Path(target).name == "run_frozen.py":
            Path(target).write_text("changed while copying")
        return result
    monkeypatch.setattr(persistence.shutil, "copy2", changed_copy)
    with pytest.raises(ValueError, match="differs"):
        persistence.preserve_dependencies(runtime, destination)
    assert not (destination / "dependency_preservation_verification.json").exists()


def test_dependency_preservation_rejects_declared_environment_credentials(tmp_path, monkeypatch):
    runtime, destination = tmp_path / "runtime", tmp_path / "saved"
    runtime.mkdir()
    destination.mkdir()
    _, preparation = write_fixture(runtime)
    (runtime / ".bird.env").write_text("PASSWORD=do-not-copy")
    preparation["nonpython_sha256"][".bird.env"] = hashlib.sha256((runtime / ".bird.env").read_bytes()).hexdigest()
    (runtime / "freeze_preparation.json").write_text(json.dumps(preparation))
    with pytest.raises(ValueError, match="credential"):
        persistence_module(monkeypatch).preserve_dependencies(runtime, destination)
    assert not (destination / "frozen_dependencies").exists()


def online_runner(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    import run_online_product
    return run_online_product


def runner_args(root, profile):
    return ["run_online_product", "--credentials-dir", str(root / "no-credentials"),
            "--out-dir", str(root / "results"), "--budget-policy", str(root / "no-budget"),
            "--budget-ledger", str(root / "no-ledger"), "--query-profile", profile, "--preflight-only"]


def write_online_fixture(root, settings):
    write_fixture(root)
    (root / "public_settings.json").write_text(json.dumps(settings))
    preparation = json.loads((root / "freeze_preparation.json").read_text())
    preparation["nonpython_sha256"]["public_settings.json"] = hashlib.sha256((root / "public_settings.json").read_bytes()).hexdigest()
    (root / "freeze_preparation.json").write_text(json.dumps(preparation))


def test_online_preflight_never_loads_credentials_or_dispatches_generation(tmp_path, monkeypatch, capsys):
    runner = online_runner(monkeypatch)
    write_online_fixture(tmp_path, {
        "GDA_LLM_PROVIDER": "gemini", "GDA_NL2SQL_QUERY_PROFILE": "registered_ir_strict"})
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", runner_args(tmp_path, "registered_ir_strict"))
    monkeypatch.setattr(runner, "load_dotenv", lambda *_a, **_k: pytest.fail("Credential access in offline preflight"))
    monkeypatch.setattr(runner.runpy, "run_path", lambda *_a, **_k: pytest.fail("Model evaluation in offline preflight"))
    runner.main()
    report = json.loads((tmp_path / "preflight_verification.json").read_text())
    assert report["query_policy"]["strict_contract"] is True
    assert '"model_calls": 0' in capsys.readouterr().out


def test_online_profile_mismatch_fails_before_credential_access(tmp_path, monkeypatch):
    from data_agent.nl2sql_route_policy import QueryPolicyError
    runner = online_runner(monkeypatch)
    write_online_fixture(tmp_path, {"GDA_LLM_PROVIDER": "gemini"})
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", runner_args(tmp_path, "registered_ir_strict"))
    monkeypatch.setattr(runner, "load_dotenv", lambda *_a, **_k: pytest.fail("Credential access before route validation"))
    with pytest.raises(QueryPolicyError, match="differs from frozen"):
        runner.main()


def test_online_runner_rejects_undeclared_public_settings(tmp_path, monkeypatch):
    runner = online_runner(monkeypatch)
    write_fixture(tmp_path)
    (tmp_path / "public_settings.json").write_text('{"GDA_LLM_PROVIDER":"gemini"}')
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "argv", runner_args(tmp_path, "configured"))
    with pytest.raises(RuntimeError, match="declared in the frozen resources"):
        runner.main()
