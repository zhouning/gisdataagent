# Standards Platform — Drafting Wave 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 3-source citation assistant (pgvector + KB + web) with LLM rerank to the 起草 sub-tab. User searches → gets ranked candidates → clicks insert → editor gets a `[[ref:UUID]]` chip; `std_reference` row is persisted.

**Architecture:** New `data_agent/standards_platform/drafting/` modules `citation_sources.py` (3 source impls), `citation_rerank.py` (model_gateway-based rerank via `llm_client.generate_text`), `citation_assistant.py` (orchestrator). Two new REST routes `POST /api/std/citation/{search,insert}`. Frontend adds `CitationPanel.tsx`, `citationMark.ts` (TipTap mark), and integrates into `ClauseEditor.tsx`. No DB migration — `std_reference` and `std_web_snapshot` already exist (migration 073).

**Tech Stack:** Python 3.13 + SQLAlchemy raw SQL + pgvector cosine + Starlette + pytest + React 18 + TipTap 2 (custom Mark) + TypeScript.

**Spec:** `docs/superpowers/specs/2026-05-15-std-platform-drafting-wave2-design.md`

---

## File Structure

**Backend (created)**
- `data_agent/standards_platform/drafting/citation_sources.py` — `Candidate` TypedDict, `search_pgvector`, `search_kb`, `search_web`
- `data_agent/standards_platform/drafting/citation_rerank.py` — `rerank` via `llm_client.generate_text`
- `data_agent/standards_platform/drafting/citation_assistant.py` — `search_citations` orchestrator
- `data_agent/standards_platform/tests/test_citation_sources.py` — 3 unit tests
- `data_agent/standards_platform/tests/test_citation_rerank.py` — 1 unit test
- `data_agent/standards_platform/tests/test_citation_assistant.py` — 1 unit test
- `data_agent/standards_platform/tests/test_api_citation.py` — 4 API tests

**Backend (modified)**
- `data_agent/api/standards_routes.py` — add 2 routes `citation/search` + `citation/insert`

**Frontend (created)**
- `frontend/src/components/datapanel/standards/draft/citationMark.ts` — TipTap mark for `[[ref:UUID]]`
- `frontend/src/components/datapanel/standards/draft/CitationPanel.tsx` — search UI

**Frontend (modified)**
- `frontend/src/components/datapanel/standards/standardsApi.ts` — `+citationSearch`, `+citationInsert`
- `frontend/src/components/datapanel/standards/draft/ClauseEditor.tsx` — register Citation mark, toolbar button, panel mount, body_md regex enhancer on load

---
## Task 1: `citation_sources.py` skeleton + `Candidate` TypedDict

**Files:**
- Create: `data_agent/standards_platform/drafting/citation_sources.py`
- Create: `data_agent/standards_platform/tests/test_citation_sources.py`

- [ ] **Step 1: Write failing test for the type contract**

```python
"""Unit tests for citation_sources."""
from __future__ import annotations

import pytest
from data_agent.standards_platform.drafting.citation_sources import (
    Candidate, search_pgvector, search_kb, search_web,
)


def test_candidate_typed_dict_shape():
    c: Candidate = {
        "kind": "std_clause", "target_id": "abc",
        "target_url": None, "snippet": "x", "base_score": 0.5, "extra": {}
    }
    assert c["kind"] == "std_clause"
```

- [ ] **Step 2: Run test, confirm import failure**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py -q
```

Expected: `ImportError`.

- [ ] **Step 3: Create the module**

```python
"""Citation candidate sources — pgvector / knowledge_base / web_snapshot.

All three functions return list[Candidate]. They are intended to be
called in parallel by citation_assistant.search_citations.
"""
from __future__ import annotations

import os
from typing import TypedDict

from sqlalchemy import text

from ...db_engine import get_engine
from ...observability import get_logger

logger = get_logger("standards_platform.drafting.citation_sources")


class Candidate(TypedDict):
    kind: str            # 'std_clause' | 'std_data_element' | 'std_term'
                         # | 'kb_chunk' | 'web_snapshot'
    target_id: str | None
    target_url: str | None
    snippet: str
    base_score: float
    extra: dict


def search_pgvector(query_embedding: list[float], *,
                    top_k_per_table: int = 10) -> list[Candidate]:
    """Cosine search over std_clause / std_data_element / std_term."""
    raise NotImplementedError


def search_kb(query: str, *, top_k: int = 10) -> list[Candidate]:
    """Wrap data_agent.knowledge_base.search_kb()."""
    raise NotImplementedError


def search_web(query: str, *, top_k: int = 5) -> list[Candidate]:
    """Search std_web_snapshot.body via ILIKE for the query terms."""
    raise NotImplementedError
```

- [ ] **Step 4: Run test, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/citation_sources.py data_agent/standards_platform/tests/test_citation_sources.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): citation_sources skeleton + Candidate TypedDict"
```

---

## Task 2: `search_pgvector` implementation

**Files:**
- Modify: `data_agent/standards_platform/drafting/citation_sources.py`
- Modify: `data_agent/standards_platform/tests/test_citation_sources.py`

- [ ] **Step 1: Write failing test**

Append to `test_citation_sources.py`:

```python
import uuid
from sqlalchemy import text as _sql
from data_agent.db_engine import get_engine
from dotenv import load_dotenv as _ld
import os as _os
_ld(_os.path.join(_os.path.dirname(__file__), "..", "..", ".env"))


@pytest.fixture
def db():
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


def test_search_pgvector_returns_clause_matches(db):
    """Insert a clause with a synthetic embedding, search with the same
    embedding, expect that clause as the top hit."""
    doc_id = str(uuid.uuid4()); ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    # Use a 768-dim embedding: all 0.1, except first dim = 1.0
    emb = "[" + ",".join(["1.0"] + ["0.1"] * 767) + "]"
    with db.begin() as c:
        c.execute(_sql(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'test')"
        ), {"i": doc_id, "c": f"T-PGV-{doc_id[:6]}"})
        c.execute(_sql(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
        c.execute(_sql(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md, embedding) "
            "VALUES (:i, :d, :v, CAST('1' AS ltree), '1', 'clause', "
            "'pgvector test', CAST(:e AS vector))"
        ), {"i": cid, "d": doc_id, "v": ver_id, "e": emb})

    try:
        # Same embedding → cosine 1.0
        results = search_pgvector([1.0] + [0.1] * 767, top_k_per_table=5)
        clause_hits = [r for r in results if r["target_id"] == cid]
        assert len(clause_hits) == 1
        assert clause_hits[0]["kind"] == "std_clause"
        assert clause_hits[0]["base_score"] > 0.99  # near-perfect cosine
        assert "pgvector test" in clause_hits[0]["snippet"]
    finally:
        with db.begin() as c:
            c.execute(_sql("DELETE FROM std_document WHERE id=:d"),
                      {"d": doc_id})
```

- [ ] **Step 2: Run, expect NotImplementedError**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py::test_search_pgvector_returns_clause_matches -q
```

Expected: `NotImplementedError`.

- [ ] **Step 3: Implement `search_pgvector`**

Replace the `raise NotImplementedError` body with:

```python
def search_pgvector(query_embedding: list[float], *,
                    top_k_per_table: int = 10) -> list[Candidate]:
    eng = get_engine()
    if eng is None:
        return []
    emb_lit = "[" + ",".join(f"{x:.6f}" for x in query_embedding) + "]"
    sql = """
        (SELECT 'std_clause' AS kind, id::text AS target_id,
                LEFT(COALESCE(heading,'') || ' ' || COALESCE(body_md,''), 500) AS snippet,
                1 - (embedding <=> CAST(:e AS vector)) AS base_score,
                jsonb_build_object(
                    'clause_no', clause_no,
                    'document_version_id', document_version_id::text,
                    'document_id', document_id::text
                ) AS extra
           FROM std_clause WHERE embedding IS NOT NULL
           ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k)
        UNION ALL
        (SELECT 'std_data_element' AS kind, id::text,
                LEFT(COALESCE(name_zh,'') || ' ' || COALESCE(definition,''), 500),
                1 - (embedding <=> CAST(:e AS vector)),
                jsonb_build_object('code', code,
                    'document_version_id', document_version_id::text)
           FROM std_data_element WHERE embedding IS NOT NULL
           ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k)
        UNION ALL
        (SELECT 'std_term' AS kind, id::text,
                LEFT(COALESCE(name_zh,'') || ' ' || COALESCE(definition,''), 500),
                1 - (embedding <=> CAST(:e AS vector)),
                jsonb_build_object('term_code', term_code,
                    'document_version_id', document_version_id::text)
           FROM std_term WHERE embedding IS NOT NULL
           ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k)
        ORDER BY base_score DESC
    """
    with eng.connect() as conn:
        rows = conn.execute(text(sql), {"e": emb_lit,
                                         "k": top_k_per_table}).mappings().all()
    return [{
        "kind": r["kind"],
        "target_id": r["target_id"],
        "target_url": None,
        "snippet": r["snippet"] or "",
        "base_score": float(r["base_score"]),
        "extra": dict(r["extra"]) if r["extra"] else {},
    } for r in rows]
```

- [ ] **Step 4: Run, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/citation_sources.py data_agent/standards_platform/tests/test_citation_sources.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): search_pgvector across clauses/elements/terms"
```

---
## Task 3: `search_kb` implementation (wraps existing knowledge_base.search_kb)

**Files:**
- Modify: `data_agent/standards_platform/drafting/citation_sources.py`
- Modify: `data_agent/standards_platform/tests/test_citation_sources.py`

- [ ] **Step 1: Write failing test (mock the underlying function)**

Append:

```python
from unittest.mock import patch


def test_search_kb_wraps_chunks(monkeypatch):
    """Mock data_agent.knowledge_base.search_kb to return 2 chunks."""
    fake_chunks = [
        {"chunk_id": "c1", "kb_id": 5, "title": "GB/T 13923",
         "content": "行政区代码定义……", "score": 0.92},
        {"chunk_id": "c2", "kb_id": 5, "title": "国土调查规程",
         "content": "图斑要素……", "score": 0.78},
    ]
    with patch("data_agent.knowledge_base.search_kb",
               return_value=fake_chunks):
        results = search_kb("行政区代码", top_k=5)
    assert len(results) == 2
    assert results[0]["kind"] == "kb_chunk"
    assert results[0]["target_id"] == "c1"
    assert results[0]["base_score"] == 0.92
    assert "行政区代码" in results[0]["snippet"]
```

- [ ] **Step 2: Run, expect NotImplementedError**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py::test_search_kb_wraps_chunks -q
```

- [ ] **Step 3: Implement `search_kb`**

```python
def search_kb(query: str, *, top_k: int = 10) -> list[Candidate]:
    try:
        from ...knowledge_base import search_kb as _kb_search
    except Exception as e:
        logger.warning("knowledge_base import failed: %s", e)
        return []
    kb_id_env = os.getenv("STANDARDS_KB_ID")
    kwargs: dict = {"top_k": top_k}
    if kb_id_env:
        try:
            kwargs["kb_id"] = int(kb_id_env)
        except ValueError:
            pass
    try:
        chunks = _kb_search(query, **kwargs)
    except Exception as e:
        logger.warning("knowledge_base.search_kb failed: %s", e)
        return []
    out: list[Candidate] = []
    for ch in chunks or []:
        out.append({
            "kind": "kb_chunk",
            "target_id": str(ch.get("chunk_id") or ""),
            "target_url": None,
            "snippet": (ch.get("content") or "")[:500],
            "base_score": float(ch.get("score") or 0.0),
            "extra": {"kb_id": ch.get("kb_id"),
                      "title": ch.get("title")},
        })
    return out
```

- [ ] **Step 4: Run, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/citation_sources.py data_agent/standards_platform/tests/test_citation_sources.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): search_kb wraps knowledge_base.search_kb"
```

---

## Task 4: `search_web` implementation (FTS over std_web_snapshot)

**Files:**
- Modify: `data_agent/standards_platform/drafting/citation_sources.py`
- Modify: `data_agent/standards_platform/tests/test_citation_sources.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_search_web_returns_snapshot_matches(db):
    """Insert a fake std_web_snapshot row and search by ILIKE."""
    snap_id = str(uuid.uuid4())
    with db.begin() as c:
        c.execute(_sql(
            "INSERT INTO std_web_snapshot (id, url, fetched_at, body, "
            "content_type, status_code, fetched_by) "
            "VALUES (:i, :u, now(), :b, 'text/plain', 200, 'test')"
        ), {"i": snap_id, "u": "https://std.samr.gov.cn/test",
            "b": "测试内容: 行政区代码 XZQDM 是字段定义"})
    try:
        results = search_web("行政区代码 XZQDM", top_k=5)
        hits = [r for r in results if r["target_id"] == snap_id]
        assert len(hits) == 1
        assert hits[0]["kind"] == "web_snapshot"
        assert hits[0]["target_url"] == "https://std.samr.gov.cn/test"
        assert "行政区代码" in hits[0]["snippet"]
    finally:
        with db.begin() as c:
            c.execute(_sql("DELETE FROM std_web_snapshot WHERE id=:i"),
                      {"i": snap_id})
```

- [ ] **Step 2: Run, expect NotImplementedError**

- [ ] **Step 3: Implement `search_web`**

```python
def search_web(query: str, *, top_k: int = 5) -> list[Candidate]:
    """Search std_web_snapshot.body via ILIKE for any token in the query.

    Simple substring matching; no FTS index dependency. The snippet is
    the first ~500 chars of the matched body (a window around the first
    match would be better but is deferred).
    """
    eng = get_engine()
    if eng is None:
        return []
    tokens = [t for t in query.split() if t.strip()]
    if not tokens:
        return []
    # Build OR-ed ILIKE conditions
    pattern_clauses = " OR ".join(
        f"body ILIKE :p{i}" for i in range(len(tokens))
    )
    params = {f"p{i}": f"%{tok}%" for i, tok in enumerate(tokens)}
    params["k"] = top_k
    sql = f"""
        SELECT id::text AS id, url, LEFT(body, 500) AS snippet
          FROM std_web_snapshot
         WHERE {pattern_clauses}
         ORDER BY fetched_at DESC
         LIMIT :k
    """
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [{
        "kind": "web_snapshot",
        "target_id": r["id"],
        "target_url": r["url"],
        "snippet": r["snippet"] or "",
        "base_score": 0.5,  # neutral; rerank will refine
        "extra": {},
    } for r in rows]
```

- [ ] **Step 4: Run, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_sources.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/citation_sources.py data_agent/standards_platform/tests/test_citation_sources.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): search_web ILIKE over std_web_snapshot"
```

---
## Task 5: `citation_rerank.py` (LLM rerank via llm_client.generate_text)

**Files:**
- Create: `data_agent/standards_platform/drafting/citation_rerank.py`
- Create: `data_agent/standards_platform/tests/test_citation_rerank.py`

- [ ] **Step 1: Write failing test (mock llm_client)**

```python
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
```

- [ ] **Step 2: Run, expect ImportError**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_rerank.py -q
```

- [ ] **Step 3: Implement the module**

```python
"""LLM rerank for citation candidates.

Uses the project's llm_client.generate_text wrapper (which routes through
model_gateway internally) to send a Chinese prompt asking the model to
score each candidate on relevance to the query, then re-sorts.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ...observability import get_logger
from .citation_sources import Candidate

logger = get_logger("standards_platform.drafting.citation_rerank")

_PROMPT_TEMPLATE = """你是一个数据标准检索助手。给定一段查询和一组候选片段，
为每个候选给出 0-1 之间的相关度分数。返回 JSON 数组
[{{"index": <int>, "confidence": <float>, "reason": <string>}}]，
按 confidence 降序。只输出 JSON。

查询: {query}

候选:
{cands}
"""


def _format_candidates(candidates: list[Candidate]) -> str:
    lines: list[str] = []
    for i, c in enumerate(candidates):
        snippet = (c["snippet"] or "")[:200].replace("\n", " ")
        lines.append(f"[{i}] kind={c['kind']} snippet=\"{snippet}\"")
    return "\n".join(lines)


def _parse_json_array(raw: str) -> list[dict[str, Any]] | None:
    """Strip code fences and parse the first JSON array in the string."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # Fallback: find the first [...] block
    m = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            return None
    return None


def rerank(query: str, candidates: list[Candidate], *,
           top_k: int = 20) -> list[Candidate]:
    """LLM rerank. On any failure, fall back to base_score sort."""
    if not candidates:
        return []
    try:
        from ...llm_client import generate_text
    except ImportError:
        logger.warning("llm_client unavailable; falling back to base_score")
        return sorted(candidates, key=lambda c: c["base_score"],
                      reverse=True)[:top_k]
    prompt = _PROMPT_TEMPLATE.format(
        query=query, cands=_format_candidates(candidates))
    try:
        raw = generate_text(prompt, tier="fast", timeout_ms=20_000)
    except Exception as e:
        logger.warning("llm rerank failed: %s; falling back", e)
        return sorted(candidates, key=lambda c: c["base_score"],
                      reverse=True)[:top_k]
    parsed = _parse_json_array(raw)
    if not parsed:
        logger.warning("llm rerank returned unparseable: %r", raw[:200])
        return sorted(candidates, key=lambda c: c["base_score"],
                      reverse=True)[:top_k]
    # Build output by index, attach confidence, drop indexes that don't
    # exist in the original list.
    seen_indexes: set[int] = set()
    out: list[Candidate] = []
    for entry in parsed:
        try:
            i = int(entry["index"])
            if i < 0 or i >= len(candidates) or i in seen_indexes:
                continue
            seen_indexes.add(i)
            conf = float(entry.get("confidence", candidates[i]["base_score"]))
        except (KeyError, ValueError, TypeError):
            continue
        cand = dict(candidates[i])  # shallow copy
        cand["extra"] = {**cand.get("extra", {}), "confidence": conf,
                         "rerank_reason": entry.get("reason", "")}
        out.append(cand)  # type: ignore[arg-type]
    # Append any candidates the LLM didn't score, ordered by base_score
    missing = [(i, c) for i, c in enumerate(candidates)
               if i not in seen_indexes]
    missing.sort(key=lambda t: t[1]["base_score"], reverse=True)
    for _, c in missing:
        copy = dict(c)
        copy["extra"] = {**copy.get("extra", {}),
                         "confidence": copy["base_score"]}
        out.append(copy)  # type: ignore[arg-type]
    return out[:top_k]
```

- [ ] **Step 4: Run, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_rerank.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/citation_rerank.py data_agent/standards_platform/tests/test_citation_rerank.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): citation_rerank — LLM rerank via llm_client.generate_text"
```

---

## Task 6: `citation_assistant.py` orchestrator

**Files:**
- Create: `data_agent/standards_platform/drafting/citation_assistant.py`
- Create: `data_agent/standards_platform/tests/test_citation_assistant.py`

- [ ] **Step 1: Write failing test (mock 3 sources + rerank)**

```python
"""Unit test for citation_assistant.search_citations."""
from __future__ import annotations

from unittest.mock import patch
from data_agent.standards_platform.drafting.citation_assistant import (
    search_citations,
)


def test_assistant_orchestrates_three_sources():
    fake_pgvec = [{"kind": "std_clause", "target_id": "p1",
                   "target_url": None, "snippet": "pg snippet",
                   "base_score": 0.9, "extra": {}}]
    fake_kb = [{"kind": "kb_chunk", "target_id": "k1",
                "target_url": None, "snippet": "kb snippet",
                "base_score": 0.7, "extra": {}}]
    fake_web = [{"kind": "web_snapshot", "target_id": "w1",
                 "target_url": "https://x", "snippet": "web snippet",
                 "base_score": 0.5, "extra": {}}]

    with patch("data_agent.standards_platform.drafting.citation_assistant"
               "._embed_query", return_value=[0.0] * 768), \
         patch("data_agent.standards_platform.drafting.citation_sources"
               ".search_pgvector", return_value=fake_pgvec), \
         patch("data_agent.standards_platform.drafting.citation_sources"
               ".search_kb", return_value=fake_kb), \
         patch("data_agent.standards_platform.drafting.citation_sources"
               ".search_web", return_value=fake_web), \
         patch("data_agent.standards_platform.drafting.citation_rerank"
               ".rerank", side_effect=lambda q, c, top_k=20: c):
        out = search_citations(clause_id="dummy", query="行政区",
                               sources={"pgvector", "kb", "web"})
    kinds = sorted(c["kind"] for c in out)
    assert kinds == ["kb_chunk", "std_clause", "web_snapshot"]
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement `citation_assistant.py`**

```python
"""Orchestrate the 3 citation sources and the LLM rerank."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from ...observability import get_logger
from . import citation_sources as _cs
from . import citation_rerank as _rr

logger = get_logger("standards_platform.drafting.citation_assistant")

_DEFAULT_SOURCES = frozenset({"pgvector", "kb", "web"})


def _embed_query(query: str) -> list[float]:
    """Embed the query via the project's embedding gateway."""
    try:
        from ...embedding_gateway import get_embeddings
        vecs = get_embeddings([query])
        if vecs and len(vecs) == 1 and len(vecs[0]) == 768:
            return list(vecs[0])
    except Exception as e:
        logger.warning("embed_query failed: %s", e)
    return [0.0] * 768


def search_citations(*, clause_id: str, query: str,
                     sources: set[str] | None = None,
                     top_k: int = 20) -> list[_cs.Candidate]:
    src = sources or _DEFAULT_SOURCES
    if not query or not query.strip():
        return []

    candidates: list[_cs.Candidate] = []
    futures: dict = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        if "pgvector" in src:
            emb = _embed_query(query)
            futures[pool.submit(_cs.search_pgvector, emb)] = "pgvector"
        if "kb" in src:
            futures[pool.submit(_cs.search_kb, query)] = "kb"
        if "web" in src:
            futures[pool.submit(_cs.search_web, query)] = "web"
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                got = fut.result() or []
                logger.info("source %s returned %d candidates", name, len(got))
                candidates.extend(got)
            except Exception as e:
                logger.warning("source %s failed: %s", name, e)

    if not candidates:
        return []
    return _rr.rerank(query, candidates, top_k=top_k)
```

- [ ] **Step 4: Run, verify pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_citation_assistant.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```
git add data_agent/standards_platform/drafting/citation_assistant.py data_agent/standards_platform/tests/test_citation_assistant.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): citation_assistant orchestrator (3 sources + rerank)"
```

---
## Task 7: 2 REST routes (`citation/search` + `citation/insert`)

**Files:**
- Modify: `data_agent/api/standards_routes.py`

- [ ] **Step 1: Smoke check current state**

```
.venv\Scripts\python.exe -c "from data_agent.api.standards_routes import standards_routes; print(len(standards_routes))"
```

Expected: `18` (after Wave 1.5).

- [ ] **Step 2: Add 2 handler functions**

Find the existing handlers in `standards_routes.py` (e.g., near `lock_clause`). Append the 2 new ones above the `standards_routes = [...]` list:

```python
async def citation_search(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    body = await request.json()
    clause_id = body.get("clause_id")
    query = (body.get("query") or "").strip()
    if not clause_id or not query:
        return JSONResponse({"error": "clause_id and query required"},
                            status_code=400)
    sources_list = body.get("sources")
    sources = set(sources_list) if sources_list else None
    from ..standards_platform.drafting.citation_assistant import (
        search_citations,
    )
    cands = search_citations(clause_id=clause_id, query=query,
                             sources=sources, top_k=20)
    return JSONResponse({"candidates": cands})


async def citation_insert(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    body = await request.json()
    clause_id = body.get("clause_id")
    cand = body.get("candidate") or {}
    if not clause_id or not cand:
        return JSONResponse({"error": "clause_id and candidate required"},
                            status_code=400)
    kind = cand.get("kind", "")
    target_kind_map = {
        "std_clause": "std_clause",
        "std_data_element": "std_clause",  # element belongs to a clause
        "std_term": "std_clause",
        "kb_chunk": "internet_search",
        "web_snapshot": "web_snapshot",
    }
    target_kind = target_kind_map.get(kind)
    if target_kind is None:
        return JSONResponse(
            {"error": f"unsupported candidate kind: {kind}"},
            status_code=400)
    target_clause_id = None
    target_url = cand.get("target_url")
    snapshot_id = None
    if kind in ("std_clause",):
        target_clause_id = cand.get("target_id")
    elif kind == "web_snapshot":
        snapshot_id = cand.get("target_id")
    citation_text = (cand.get("snippet") or "")[:500]
    confidence = cand.get("extra", {}).get("confidence")
    eng = get_engine()
    import uuid as _u
    ref_id = str(_u.uuid4())
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_reference (
                id, source_clause_id, target_kind, target_clause_id,
                target_url, snapshot_id, citation_text, confidence,
                verified_by, verified_at)
            VALUES (:i, :sc, :tk, :tc, :tu, :sn, :ct, :cf, :u, now())
        """), {
            "i": ref_id, "sc": clause_id, "tk": target_kind,
            "tc": target_clause_id, "tu": target_url,
            "sn": snapshot_id, "ct": citation_text,
            "cf": confidence, "u": username,
        })
    return JSONResponse({"ref_id": ref_id, "citation_text": citation_text})
```

- [ ] **Step 3: Append 2 routes to the `standards_routes = [...]` list**

```python
    Route("/api/std/citation/search",
          endpoint=citation_search, methods=["POST"]),
    Route("/api/std/citation/insert",
          endpoint=citation_insert, methods=["POST"]),
```

- [ ] **Step 4: Smoke check**

```
.venv\Scripts\python.exe -c "from data_agent.api.standards_routes import standards_routes; print(len(standards_routes))"
```

Expected: `20` (was 18).

- [ ] **Step 5: Commit**

```
git add data_agent/api/standards_routes.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): citation/search + citation/insert routes"
```

---

## Task 8: 4 API tests for citation endpoints

**Files:**
- Create: `data_agent/standards_platform/tests/test_api_citation.py`

- [ ] **Step 1: Write 4 failing tests**

```python
"""API smoke tests for citation endpoints."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from unittest.mock import patch

from data_agent.db_engine import get_engine
from data_agent.standards_platform.tests.test_api_standards import (
    _client, _auth_user,
)


def _seed_clause():
    eng = get_engine()
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-CIT-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
        conn.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', 'hello')"
        ), {"i": cid, "d": doc_id, "v": ver_id})
    return cid, doc_id


@pytest.fixture
def fresh_clause():
    cid, did = _seed_clause()
    yield cid
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM std_document WHERE id=:d"), {"d": did})


def test_search_citations_returns_200(monkeypatch, fresh_clause):
    fake_cands = [{"kind": "std_clause", "target_id": "c1",
                   "target_url": None, "snippet": "x", "base_score": 0.9,
                   "extra": {"confidence": 0.95}}]
    _auth_user(monkeypatch, username="admin", role="admin")
    with patch("data_agent.standards_platform.drafting.citation_assistant"
               ".search_citations", return_value=fake_cands):
        r = _client().post("/api/std/citation/search",
                           json={"clause_id": fresh_clause,
                                 "query": "行政区"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0]["kind"] == "std_clause"


def test_search_citations_validates_query_required(monkeypatch, fresh_clause):
    _auth_user(monkeypatch, username="admin", role="admin")
    r = _client().post("/api/std/citation/search",
                       json={"clause_id": fresh_clause, "query": ""})
    assert r.status_code == 400


def test_insert_citation_creates_std_reference(monkeypatch, fresh_clause):
    _auth_user(monkeypatch, username="admin", role="admin")
    cand = {"kind": "std_clause", "target_id": str(uuid.uuid4()),
            "target_url": None, "snippet": "test snippet",
            "base_score": 0.8, "extra": {"confidence": 0.85}}
    # The target_id must exist for the FK; insert a real one.
    eng = get_engine()
    target_doc = str(uuid.uuid4())
    target_ver = str(uuid.uuid4())
    target_clause = cand["target_id"]
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": target_doc, "c": f"T-TGT-{target_doc[:6]}"})
        c.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": target_ver, "d": target_doc})
        c.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', '')"
        ), {"i": target_clause, "d": target_doc, "v": target_ver})
    try:
        r = _client().post("/api/std/citation/insert",
                           json={"clause_id": fresh_clause,
                                 "candidate": cand})
        assert r.status_code == 200
        ref_id = r.json()["ref_id"]
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT source_clause_id, target_clause_id, citation_text, "
                "confidence, verified_by FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert str(row.source_clause_id) == fresh_clause
        assert str(row.target_clause_id) == target_clause
        assert row.citation_text == "test snippet"
        assert float(row.confidence) == 0.85
        assert row.verified_by == "admin"
    finally:
        with eng.begin() as c:
            c.execute(text("DELETE FROM std_document WHERE id=:d"),
                      {"d": target_doc})


def test_insert_citation_rejects_invalid_kind(monkeypatch, fresh_clause):
    _auth_user(monkeypatch, username="admin", role="admin")
    cand = {"kind": "totally_bogus", "target_id": "x",
            "target_url": None, "snippet": "...",
            "base_score": 0.5, "extra": {}}
    r = _client().post("/api/std/citation/insert",
                       json={"clause_id": fresh_clause, "candidate": cand})
    assert r.status_code == 400
```

- [ ] **Step 2: Run, verify all 4 pass**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/tests/test_api_citation.py -q
```

Expected: `4 passed`.

- [ ] **Step 3: Run full standards_platform regression**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ -q
```

Expected: previous count + new tests, no regressions.

- [ ] **Step 4: Commit**

```
git add data_agent/standards_platform/tests/test_api_citation.py
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "test(std-platform): 4 API tests for citation/search + citation/insert"
```

---
## Task 9: standardsApi.ts — 2 new fetch functions

**Files:**
- Modify: `frontend/src/components/datapanel/standards/standardsApi.ts`

- [ ] **Step 1: Append types + fetch functions**

At the end of the file:

```typescript
export interface CitationCandidate {
  kind: string;
  target_id: string | null;
  target_url: string | null;
  snippet: string;
  base_score: number;
  extra: Record<string, any>;
}

export const citationSearch = (clauseId: string, query: string,
                                sources?: string[]) =>
  fetch("/api/std/citation/search", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({clause_id: clauseId, query, sources}),
  }).then(j<{candidates: CitationCandidate[]}>);

export const citationInsert = (clauseId: string,
                                candidate: CitationCandidate) =>
  fetch("/api/std/citation/insert", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({clause_id: clauseId, candidate}),
  }).then(j<{ref_id: string; citation_text: string}>);
```

- [ ] **Step 2: TypeScript check**

```
cd D:\adk\frontend
npx tsc --noEmit -p .
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
cd D:\adk
git add frontend/src/components/datapanel/standards/standardsApi.ts
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): standardsApi citationSearch + citationInsert"
```

---

## Task 10: TipTap Citation mark

**Files:**
- Create: `frontend/src/components/datapanel/standards/draft/citationMark.ts`

- [ ] **Step 1: Write the mark**

```typescript
import { Mark, mergeAttributes } from "@tiptap/core";

export const Citation = Mark.create({
  name: "citation",

  addAttributes() {
    return {
      refId: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-citation"),
        renderHTML: (attrs) =>
          attrs.refId ? { "data-citation": attrs.refId } : {},
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-citation]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes({ class: "citation-chip" }, HTMLAttributes),
      0,
    ];
  },
});
```

- [ ] **Step 2: TypeScript check**

```
cd D:\adk\frontend
npx tsc --noEmit -p .
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
cd D:\adk
git add frontend/src/components/datapanel/standards/draft/citationMark.ts
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): TipTap Citation mark for [[ref:UUID]] chips"
```

---

## Task 11: CitationPanel.tsx — search UI

**Files:**
- Create: `frontend/src/components/datapanel/standards/draft/CitationPanel.tsx`

- [ ] **Step 1: Write the component**

```tsx
import React, { useState } from "react";
import {
  citationSearch, citationInsert, CitationCandidate,
} from "../standardsApi";

interface Props {
  clauseId: string;
  onClose: () => void;
  onInsert: (refId: string) => void;
}

const SOURCE_LABELS: Record<string, string> = {
  pgvector: "本库", kb: "知识库", web: "网页快照",
};

function confidenceBadge(c: number | undefined): string {
  if (c === undefined) return "⚪";
  if (c >= 0.8) return "🟢";
  if (c >= 0.6) return "🟡";
  return "🔴";
}

export default function CitationPanel({clauseId, onClose, onInsert}: Props) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState<Record<string, boolean>>({
    pgvector: true, kb: true, web: false,
  });
  const [results, setResults] = useState<CitationCandidate[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const onSearch = async () => {
    setErr(null); setBusy(true);
    try {
      const enabled = Object.keys(sources).filter(k => sources[k]);
      const r = await citationSearch(clauseId, query, enabled);
      setResults(r.candidates);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onPickInsert = async (c: CitationCandidate) => {
    try {
      const r = await citationInsert(clauseId, c);
      onInsert(r.ref_id);
    } catch (e) {
      setErr(String(e));
    }
  };

  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0, width: 360,
      background: "#fff", borderLeft: "1px solid #ccc", zIndex: 10,
      display: "flex", flexDirection: "column", color: "#222",
    }}>
      <div style={{padding: 8, borderBottom: "1px solid #ddd",
                   display: "flex", alignItems: "center", gap: 8}}>
        <strong style={{flex: 1}}>引用助手</strong>
        <button onClick={onClose}>×</button>
      </div>
      <div style={{padding: 8, borderBottom: "1px solid #eee"}}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") onSearch(); }}
          placeholder="搜索词、字段代码、标准号..."
          style={{width: "100%", padding: 4, marginBottom: 6,
                  border: "1px solid #ccc", borderRadius: 3}}
          disabled={busy}
          autoFocus
        />
        <div style={{display: "flex", gap: 8, fontSize: 12,
                     marginBottom: 6}}>
          {(["pgvector","kb","web"] as const).map(k => (
            <label key={k} style={{cursor: "pointer"}}>
              <input type="checkbox"
                     checked={sources[k]}
                     onChange={(e) => setSources({
                       ...sources, [k]: e.target.checked
                     })}/>
              {" "}{SOURCE_LABELS[k]}
            </label>
          ))}
        </div>
        <button onClick={onSearch} disabled={busy || !query.trim()}>
          {busy ? "搜索中..." : "搜索"}
        </button>
      </div>
      {err && <div style={{padding: 8, color: "red", fontSize: 12}}>{err}</div>}
      <div style={{flex: 1, overflow: "auto", padding: 8}}>
        {results.length === 0 && !busy && (
          <div style={{color: "#888", fontSize: 13}}>暂无结果</div>
        )}
        {results.map((c, i) => {
          const conf = c.extra?.confidence as number | undefined;
          return (
            <div key={i} style={{
              padding: 8, marginBottom: 8, border: "1px solid #eee",
              borderRadius: 4, fontSize: 13,
            }}>
              <div style={{fontSize: 11, color: "#666", marginBottom: 4}}>
                {confidenceBadge(conf)}{" "}
                {conf !== undefined ? conf.toFixed(2) : "?"}{" · "}
                <code>{c.kind}</code>
                {c.extra?.clause_no && ` · ${c.extra.clause_no}`}
                {c.extra?.code && ` · ${c.extra.code}`}
              </div>
              <div style={{whiteSpace: "pre-wrap"}}>
                {c.snippet.slice(0, 200)}{c.snippet.length > 200 ? "…" : ""}
              </div>
              <button onClick={() => onPickInsert(c)}
                      style={{marginTop: 6, fontSize: 12,
                              padding: "2px 8px"}}>
                插入
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: TypeScript check**

```
cd D:\adk\frontend
npx tsc --noEmit -p .
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```
cd D:\adk
git add frontend/src/components/datapanel/standards/draft/CitationPanel.tsx
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): CitationPanel — 3-source search + insert UI"
```

---

## Task 12: ClauseEditor integration — register mark, toolbar button, panel mount, body_md enhancer

**Files:**
- Modify: `frontend/src/components/datapanel/standards/draft/ClauseEditor.tsx`

- [ ] **Step 1: Add imports**

After existing TipTap imports (after `import TableCell from "@tiptap/extension-table-cell";`):

```tsx
import { Citation } from "./citationMark";
import CitationPanel from "./CitationPanel";
```

- [ ] **Step 2: Register Citation in the useEditor extensions array**

Find the existing `extensions: [...]` array in `useEditor`. Add `Citation` to the end:

```tsx
extensions: [
  StarterKit,
  Placeholder.configure({ placeholder: "开始编写条款内容…" }),
  Link,
  Table.configure({ resizable: false }),
  TableRow,
  TableHeader,
  TableCell,
  Citation,
],
```

- [ ] **Step 3: Add `citationOpen` state and the body_md enhancer**

Just below the existing `const [state, setState] = useState<EditorState>({ kind: "idle" });`:

```tsx
const [citationOpen, setCitationOpen] = useState(false);
```

In the acquire effect, find this line:

```tsx
const html = marked.parse(combined) as string;
editor.commands.setContent(html, false);
```

Replace with:

```tsx
const rawHtml = marked.parse(combined) as string;
// Enhance bare [[ref:UUID]] text into chip spans so the Citation mark renders it
const html = rawHtml.replace(
  /\[\[ref:([0-9a-fA-F-]+)\]\]/g,
  (_m, id) => `<span data-citation="${id}" class="citation-chip">[[ref:${id}]]</span>`
);
editor.commands.setContent(html, false);
```

- [ ] **Step 4: Add toolbar button + CitationPanel mount**

Find the toolbar section with `<button onClick={onSave}>保存</button>` and the row buttons. Add a new button after `− 行`:

```tsx
<button
  onClick={() => setCitationOpen(true)}
  disabled={state.kind !== "editing"}
  title="查找并插入引用 (Ctrl+Shift+R)"
>
  查找引用
</button>
```

Just before the closing `</div>` of the outermost container (after the toolbar div), add:

```tsx
{citationOpen && clause && (
  <CitationPanel
    clauseId={clause.id}
    onClose={() => setCitationOpen(false)}
    onInsert={(refId) => {
      editor?.chain().focus().insertContent(
        `<span data-citation="${refId}" class="citation-chip">[[ref:${refId}]]</span>`
      ).run();
      setCitationOpen(false);
    }}
  />
)}
```

Also make the outer container `position: "relative"` so the absolute panel overlays correctly. Find:

```tsx
<div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
```

Change to:

```tsx
<div style={{ display: "flex", flexDirection: "column", height: "100%", position: "relative" }}>
```

- [ ] **Step 5: Add citation-chip CSS**

Find the existing `<style>{`...`}</style>` block (inside the `.std-clause-editor` div). Append CSS rules inside the template literal, before the closing backtick:

```css
.std-clause-editor .citation-chip {
  display: inline-block;
  padding: 0 4px;
  margin: 0 2px;
  background: #eef6ff;
  border: 1px solid #99c2ee;
  border-radius: 3px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #0a4;
  white-space: nowrap;
}
```

- [ ] **Step 6: TypeScript check and build**

```
cd D:\adk\frontend
npm run build
```

Expected: exit 0.

- [ ] **Step 7: Commit**

```
cd D:\adk
git add frontend/src/components/datapanel/standards/draft/ClauseEditor.tsx
git -c user.name="Zhou Ning" -c user.email="zhouning1@supermap.com" commit -m "feat(std-platform): integrate Citation mark + CitationPanel into ClauseEditor"
```

---

## Task 13: Manual E2E verification + push

**Files:** none — runtime verification only.

- [ ] **Step 1: Restart Chainlit so it picks up the new routes**

```
Get-WmiObject Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*chainlit*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$env:PYTHONPATH = "D:\adk"
$env:NO_PROXY = "119.3.175.198,localhost,127.0.0.1"
cd D:\adk
Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-m","chainlit","run","data_agent/app.py","-w" -RedirectStandardOutput "D:\adk\chainlit_stdout.log" -RedirectStandardError "D:\adk\chainlit_stderr.log" -NoNewWindow
```

Wait until `Frontend API routes mounted` appears in the log.

- [ ] **Step 2: Probe new route exists**

```
try { Invoke-WebRequest "http://localhost:8000/api/std/citation/search" -Method POST -Body '{}' -ContentType "application/json" -UseBasicParsing -TimeoutSec 5 } catch { Write-Host "HTTP $($_.Exception.Response.StatusCode.value__)" }
```

Expected: HTTP 401 (auth required → route exists).

- [ ] **Step 3: Browser checklist (8 steps)**

1. F12 → Application → Service Workers → Unregister localhost. Then Ctrl+Shift+R.
2. Login admin/admin123 → DataPanel → 数据标准 → 分析 → 选 docx → 进入分析
3. 切到「起草」→ 点 FT.1 → 编辑器加载，表格可见
4. 工具栏点「查找引用」→ 右侧滑出 CitationPanel
5. 输入 "行政区代码" → 选 pgvector + kb → 点搜索 → 候选列表出现，每条带 confidence 徽标
6. 点最相关那条的 [插入] 按钮 → 编辑器光标处出现一个浅蓝色 `[[ref:xxx]]` chip
7. 点保存 → DevTools Network 看 PUT body_md 包含 `[[ref:UUID]]` 文本
8. 切到 FT.2 再切回 FT.1 → chip 重新渲染（保持 chip 样式而非裸文本）

- [ ] **Step 4: SQL verify**

```
.venv\Scripts\python.exe -c @"
import os, sys
sys.path.insert(0, '.')
os.chdir('data_agent')
from dotenv import load_dotenv
load_dotenv('.env')
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
pw = quote_plus(os.environ.get('POSTGRES_PASSWORD',''))
url = f'postgresql://{os.environ[\"POSTGRES_USER\"]}:{pw}@{os.environ[\"POSTGRES_HOST\"]}:{os.environ[\"POSTGRES_PORT\"]}/{os.environ[\"POSTGRES_DATABASE\"]}'
eng = create_engine(url)
with eng.connect() as c:
    rows = c.execute(text('SELECT id, source_clause_id, target_kind, citation_text, confidence FROM std_reference ORDER BY verified_at DESC LIMIT 3')).fetchall()
    for r in rows: print(r)
"@
```

Expected: 1+ rows showing the citation just inserted, with `source_clause_id` matching FT.1.

- [ ] **Step 5: Full pytest regression**

```
.venv\Scripts\python.exe -m pytest data_agent/standards_platform/ -q
```

Expected: green.

- [ ] **Step 6: Update memory**

Append to `C:\Users\zn198\.claude\projects\D--adk\memory\std_platform_drafting_wave1_implementation_20260515.md` a new "Wave 2" section listing the 13 commits and the manual-E2E outcome.

- [ ] **Step 7: Push**

```
cd D:\adk
git push origin feat/v12-extensible-platform
```

Expected: clean push, no conflicts.

---

## Done criteria recap

- [ ] 13 tasks committed in order
- [ ] `pytest data_agent/standards_platform/` green (5 new citation tests + 4 API tests)
- [ ] `npm run build` exit 0
- [ ] 8-step browser E2E passes
- [ ] At least one row in `std_reference` from manual test
- [ ] Branch pushed to GitHub

