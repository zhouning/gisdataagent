"""Unit test for citation_rerank.rerank."""
from __future__ import annotations

from unittest.mock import patch
from data_agent.standards_platform.drafting.citation_rerank import rerank
from data_agent.standards_platform.drafting.citation_sources import Candidate


def test_rerank_assigns_confidence_and_sorts():
    candidates: list[Candidate] = [
        {"kind": "kb_chunk", "target_id": "c1", "target_url": None,
         "snippet": "图斑要素", "base_score": 0.8, "extra": {}},
        {"kind": "std_clause", "target_id": "abc", "target_url": None,
         "snippet": "行政区代码 XZQDM", "base_score": 0.6, "extra": {}},
        {"kind": "web_snapshot", "target_id": "w1", "target_url": "u",
         "snippet": "国土调查", "base_score": 0.5, "extra": {}},
    ]
    fake_llm_response = '''```json
[
  {"index": 1, "confidence": 0.95, "reason": "exact match"},
  {"index": 0, "confidence": 0.55, "reason": "loose"},
  {"index": 2, "confidence": 0.45, "reason": "weak"}
]
```'''
    with patch("data_agent.llm_client.generate_text",
               return_value=fake_llm_response):
        out = rerank("行政区代码", candidates, top_k=10)
    assert len(out) == 3
    # Sorted by confidence desc; original index 1 (std_clause) should be first
    assert out[0]["target_id"] == "abc"
    assert out[0]["extra"]["confidence"] == 0.95
    assert out[1]["target_id"] == "c1"


def test_rerank_sorts_by_confidence_descending():
    """LLM may return entries in any order; rerank must finalize sort by
    confidence descending (Fix #2)."""
    cands = [
        {"kind": "std_clause", "target_id": "a", "target_url": None,
         "snippet": "a", "base_score": 0.1, "extra": {}},
        {"kind": "std_clause", "target_id": "b", "target_url": None,
         "snippet": "b", "base_score": 0.1, "extra": {}},
        {"kind": "std_clause", "target_id": "c", "target_url": None,
         "snippet": "c", "base_score": 0.1, "extra": {}},
    ]
    # LLM returns entries deliberately out of order
    fake_llm_json = (
        '[{"index": 0, "confidence": 0.5, "reason": "ok"},'
        ' {"index": 1, "confidence": 0.9, "reason": "best"},'
        ' {"index": 2, "confidence": 0.7, "reason": "mid"}]'
    )
    with patch(
        "data_agent.llm_client.generate_text",
        return_value=fake_llm_json,
    ):
        out = rerank("query", cands)
    confidences = [c["extra"]["confidence"] for c in out]
    assert confidences == sorted(confidences, reverse=True), \
        f"output not sorted by confidence desc: {confidences}"
    # Specifically: index=1 (conf 0.9) should be first
    assert out[0]["target_id"] == "b"
