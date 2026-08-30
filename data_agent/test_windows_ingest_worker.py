from __future__ import annotations

import json

from data_agent.offline_ingest import OfflineIngestStore
from scripts.windows_ingest_worker import process_once


def test_worker_waits_for_stable_signature_and_writes_atomic_state(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    gdb = inbox / "DLTB.gdb"
    gdb.mkdir()
    (gdb / "a.gdbtable").write_bytes(b"fixture")
    monkeypatch.setenv("GDA_LOCAL_INGEST_DIRS", str(inbox))
    store = OfflineIngestStore(tmp_path / "lake")
    state_path = store.root / "collector_state.json"

    assert process_once(inbox, store, state_path, settle_seconds=0) == 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert next(iter(state.values()))["status"] == "waiting_for_stability"

    assert process_once(inbox, store, state_path, settle_seconds=0) == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert next(iter(state.values()))["status"] == "blocked"
    assert not list(state_path.parent.glob(".collector_state.json.*"))
