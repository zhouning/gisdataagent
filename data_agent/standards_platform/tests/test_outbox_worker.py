from unittest.mock import patch
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform import outbox as ob
from data_agent.standards_platform.outbox_worker import run_once


@pytest.fixture
def clean_outbox():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    with eng.connect() as c:
        c.execute(text("DELETE FROM std_outbox")); c.commit()
    yield eng


def test_run_once_calls_dispatch_and_marks_done(clean_outbox):
    evt_id = ob.enqueue("embed_requested", {"version_id": "V"})
    with patch("data_agent.standards_platform.outbox_worker.dispatch") as fake:
        n = run_once(batch_size=5, max_attempts=5)
    assert n == 1
    fake.assert_called_once()
    with clean_outbox.connect() as c:
        status = c.execute(text("SELECT status FROM std_outbox WHERE id=:i"),
                           {"i": evt_id}).scalar()
    assert status == "done"


def test_run_once_marks_failed_after_max_attempts(clean_outbox):
    evt_id = ob.enqueue("embed_requested", {"version_id": "V"})
    with patch("data_agent.standards_platform.outbox_worker.dispatch",
               side_effect=RuntimeError("boom")):
        for _ in range(5):
            run_once(batch_size=5, max_attempts=5)
            # bump next_attempt_at back so the same event is picked again
            with clean_outbox.connect() as c:
                c.execute(text("UPDATE std_outbox SET next_attempt_at = now(), "
                               "status='pending' WHERE id=:i AND status='pending'"),
                          {"i": evt_id}); c.commit()
    with clean_outbox.connect() as c:
        status = c.execute(text("SELECT status FROM std_outbox WHERE id=:i"),
                           {"i": evt_id}).scalar()
    assert status == "failed"
