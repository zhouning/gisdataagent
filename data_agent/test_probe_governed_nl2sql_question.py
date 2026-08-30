from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts import probe_governed_nl2sql_question as probe


def test_probe_direct_operator_environment_overrides_stale_shell_values(
    tmp_path: Path, monkeypatch
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GDA_LLM_PROVIDER=gemini\n"
        "GDA_LLM_MODEL=gemini-3.7-flash\n"
        "GDA_GEMINI_TRANSPORT=direct\n"
        "GEMINI_API_KEY=operator-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GDA_OPERATOR_ENV_FILE", str(env_path))
    monkeypatch.setenv("GDA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("GDA_LLM_MODEL", "stale-model")
    monkeypatch.setenv("GDA_GEMINI_TRANSPORT", "openai_compatible")
    monkeypatch.setenv("GEMINI_API_KEY", "stale-shell-key")

    probe._load_environment()

    assert os.environ["GDA_LLM_PROVIDER"] == "gemini"
    assert os.environ["GDA_LLM_MODEL"] == "gemini-3.7-flash"
    assert os.environ["GDA_GEMINI_TRANSPORT"] == "direct"
    assert os.environ["GEMINI_API_KEY"] == "operator-key"


def test_probe_can_persist_secret_free_report(tmp_path: Path, monkeypatch, capsys):
    output = tmp_path / "probe.json"
    report = {"schema": "test", "status": "ok", "source_rows_persisted": False}
    args = argparse.Namespace(
        semantic_layer=tmp_path / "semantic.json",
        source_id=13,
        owner="operator",
        question="question",
        model="gemini-3.7-flash",
        reasoning_effort="low",
        timeout_seconds=30,
        execution_profile="semantic_ir_experimental",
        output=output,
    )
    monkeypatch.setattr(probe.argparse.ArgumentParser, "parse_args", lambda self: args)

    with patch.object(probe, "_run", AsyncMock(return_value=report)):
        probe.main()

    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert json.loads(capsys.readouterr().out) == report
