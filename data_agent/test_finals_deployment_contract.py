import subprocess
import sys
from pathlib import Path

from data_agent.model_gateway import ModelRegistry
from data_agent.paper9_agent_prompt import PAPER9_AGENT_INSTRUCTION
from scripts.check_gemma4_finals_preflight import (
    _default_bishan_runs,
    _default_repo,
)

ROOT = Path(__file__).resolve().parents[1]


def test_finals_compose_uses_configurable_paper9_033_mount():
    compose = (ROOT / "docker-compose.gemma4-demo.yml").read_text(encoding="utf-8")

    assert "${PAPER9_HOST_REPO:-./vendor/paper9-mnr-offline-package}" in compose
    assert "${PAPER9_BISHAN_RUNS_HOST:-./demo-data/bishan}" in compose
    assert "${PAPER9_DONGXING_RUNS_HOST:-./demo-data/dongxing}" in compose
    assert "/Users/" not in compose


def test_finals_env_template_declares_every_host_mount():
    template = (ROOT / ".env.finals.example").read_text(encoding="utf-8")

    assert "PAPER9_HOST_REPO=" in template
    assert "PAPER9_BISHAN_RUNS_HOST=" in template
    assert "PAPER9_DONGXING_RUNS_HOST=" in template


def test_gemma4_demo_model_disables_thinking_for_tool_loops():
    info = ModelRegistry.get_model_info("gemma4-26b-ollama")

    assert info["model_id"] == "ollama_chat/Gemma4:26b"
    assert info["extra_body"] == {"think": False}
    assert info["request_timeout"] == 600


def test_paper9_prompt_requires_complete_preflight_even_on_version_failure():
    assert "即使 status 已显示版本不兼容" in PAPER9_AGENT_INSTRUCTION
    assert "paper9_inspect_resources" in PAPER9_AGENT_INSTRUCTION
    assert "首次 pipeline 必须设置 cultivated_area_floor_delta_ha='0'" in PAPER9_AGENT_INSTRUCTION
    assert "严禁超过一次重规划" in PAPER9_AGENT_INSTRUCTION


def test_finals_preflight_script_imports_when_started_from_scripts_directory():
    result = subprocess.run(
        [sys.executable, "check_gemma4_finals_preflight.py", "--help"],
        cwd=ROOT / "scripts",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--paper9-repo" in result.stdout


def test_finals_preflight_defaults_to_runtime_mounts(monkeypatch):
    monkeypatch.delenv("PAPER9_HOST_REPO", raising=False)
    monkeypatch.delenv("PAPER9_BISHAN_RUNS_HOST", raising=False)
    monkeypatch.setenv("PAPER9_FARMLAND_MPC_REPO", "/app/paper9-demo")
    monkeypatch.setenv(
        "PAPER9_FARMLAND_MPC_DEFAULT_PREPARED_DIR",
        "/app/bishan-runs/prepared",
    )

    assert _default_repo() == Path("/app/paper9-demo")
    assert _default_bishan_runs() == Path("/app/bishan-runs")
