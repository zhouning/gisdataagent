import uuid
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform import outbox as ob


@pytest.fixture
def clean_outbox():
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    with eng.connect() as conn:
        conn.execute(text("DELETE FROM std_outbox"))
        conn.commit()
    yield eng


def test_enqueue_creates_pending_row(clean_outbox):
    evt_id = ob.enqueue("extract_requested", {"doc_id": str(uuid.uuid4())})
    with clean_outbox.connect() as conn:
        row = conn.execute(text("SELECT status, attempts FROM std_outbox WHERE id = :i"),
                           {"i": evt_id}).first()
    assert row.status == "pending"
    assert row.attempts == 0


def test_claim_marks_in_flight(clean_outbox):
    evt_id = ob.enqueue("embed_requested", {"clause_id": "x"})
    claimed = ob.claim_batch(limit=1)
    assert len(claimed) == 1
    assert claimed[0]["id"] == evt_id
    with clean_outbox.connect() as conn:
        status = conn.execute(text("SELECT status FROM std_outbox WHERE id = :i"),
                              {"i": evt_id}).scalar()
    assert status == "in_flight"


def test_complete_marks_done(clean_outbox):
    evt_id = ob.enqueue("dedupe_requested", {"doc_id": "y"})
    ob.claim_batch(limit=1)
    ob.complete(evt_id)
    with clean_outbox.connect() as conn:
        status = conn.execute(text("SELECT status, processed_at FROM std_outbox WHERE id = :i"),
                              {"i": evt_id}).first()
    assert status.status == "done"
    assert status.processed_at is not None


def test_fail_increments_attempts_and_schedules_retry(clean_outbox):
    evt_id = ob.enqueue("structure_requested", {"doc_id": "z"})
    ob.claim_batch(limit=1)
    ob.fail(evt_id, "boom", max_attempts=5)
    with clean_outbox.connect() as conn:
        row = conn.execute(text(
            "SELECT status, attempts, last_error FROM std_outbox WHERE id = :i"
        ), {"i": evt_id}).first()
    assert row.status == "pending"
    assert row.attempts == 1
    assert row.last_error == "boom"


def test_fail_after_max_attempts_marks_failed(clean_outbox):
    evt_id = ob.enqueue("structure_requested", {"doc_id": "z"})
    for _ in range(5):
        # Reset next_attempt_at so claim_batch can always find the event
        with clean_outbox.connect() as conn:
            conn.execute(text(
                "UPDATE std_outbox SET next_attempt_at = now() WHERE id = :i"
            ), {"i": evt_id})
            conn.commit()
        ob.claim_batch(limit=1)
        ob.fail(evt_id, "persist", max_attempts=5)
    with clean_outbox.connect() as conn:
        row = conn.execute(text(
            "SELECT status, attempts FROM std_outbox WHERE id = :i"
        ), {"i": evt_id}).first()
    assert row.status == "failed"
    assert row.attempts == 5


def test_claim_skips_not_yet_due(clean_outbox):
    """next_attempt_at in the future must not be claimed."""
    evt_id = ob.enqueue("extract_requested", {"doc_id": "future"})
    with clean_outbox.connect() as conn:
        conn.execute(text(
            "UPDATE std_outbox SET next_attempt_at = now() + interval '1 hour' WHERE id = :i"
        ), {"i": evt_id})
        conn.commit()
    assert ob.claim_batch(limit=5) == []
