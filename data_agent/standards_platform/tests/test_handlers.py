from unittest.mock import patch, MagicMock
import pytest
from data_agent.standards_platform.handlers import dispatch


def test_extract_requested_routes_to_extract_then_enqueues_structure():
    with patch("data_agent.standards_platform.handlers.run_extractor",
               return_value={"FieldTable":[]}) as fake_ex, \
         patch("data_agent.standards_platform.handlers.outbox.enqueue") as fake_enq:
        dispatch({"id":"e1","event_type":"extract_requested",
                  "payload":{"document_id":"D","version_id":"V",
                             "file_path":"/tmp/x.docx","ext":".docx"},
                  "attempts":0})
    fake_ex.assert_called_once()
    fake_enq.assert_called_with("structure_requested",
        {"document_id":"D","version_id":"V","extracted":{"FieldTable":[]}})


def test_structure_requested_routes_to_structurer_then_enqueues_embed():
    with patch("data_agent.standards_platform.handlers.structure_extracted",
               return_value={"clauses_inserted":3}) as fake_s, \
         patch("data_agent.standards_platform.handlers.outbox.enqueue") as fake_enq:
        dispatch({"id":"e2","event_type":"structure_requested",
                  "payload":{"document_id":"D","version_id":"V",
                             "extracted":{"FieldTable":[]}}, "attempts":0})
    fake_s.assert_called_once()
    fake_enq.assert_called_with("embed_requested", {"version_id":"V"})


def test_embed_requested_then_enqueues_dedupe():
    with patch("data_agent.standards_platform.handlers.embed_version",
               return_value={"clauses_embedded":3}), \
         patch("data_agent.standards_platform.handlers.outbox.enqueue") as fake_enq:
        dispatch({"id":"e3","event_type":"embed_requested",
                  "payload":{"version_id":"V"}, "attempts":0})
    fake_enq.assert_called_with("dedupe_requested", {"version_id":"V"})


def test_unknown_event_raises():
    with pytest.raises(ValueError):
        dispatch({"id":"x","event_type":"nope","payload":{}, "attempts":0})
