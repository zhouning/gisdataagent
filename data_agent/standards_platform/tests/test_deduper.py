import uuid, pytest
from sqlalchemy import text
from data_agent.db_engine import get_engine
from data_agent.standards_platform.analysis.deduper import find_similar_clauses


def _seed(c, doc_id, ver_id, body, vec):
    c.execute(text("""
      INSERT INTO std_clause (id, document_id, document_version_id, ordinal_path,
        kind, body_md, embedding)
      VALUES (:i, :d, :v, '5.2'::ltree, 'clause', :b, CAST(:e AS vector))
    """), {"i": str(uuid.uuid4()), "d": doc_id, "v": ver_id,
            "b": body, "e": "[" + ",".join(str(x) for x in vec) + "]"})


def test_returns_nearest_neighbours_cross_version():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    doc_a, ver_a = str(uuid.uuid4()), str(uuid.uuid4())
    doc_b, ver_b = str(uuid.uuid4()), str(uuid.uuid4())
    vec_a = [0.0] * 768
    vec_b = [0.0] * 768
    for idx in (37, 199, 431, 702):
        vec_a[idx] = 1.0
        vec_b[idx] = 1.0
    vec_b[703] = 0.01
    try:
        with eng.begin() as c:
            for d,v in ((doc_a,ver_a),(doc_b,ver_b)):
                c.execute(text("INSERT INTO std_document (id, doc_code, title, source_type, "
                               "owner_user_id) VALUES (:i, :c, 't', 'draft', 'u')"),
                          {"i": d, "c": f"T-{uuid.uuid4().hex[:6]}"})
                c.execute(text("INSERT INTO std_document_version (id, document_id, version_label, "
                               "semver_major) VALUES (:i, :d, 'v1.0', 1)"), {"i": v, "d": d})
            _seed(c, doc_a, ver_a, "城市建设用地定义",
                  vec_a)
            _seed(c, doc_b, ver_b, "城市建设用地定义 2",
                  vec_b)
        hits = find_similar_clauses(version_id=ver_a, top_k=50, min_similarity=0.99)
        assert any(str(h["document_version_id"]) == ver_b for h in hits)
    finally:
        with eng.begin() as c:
            c.execute(text("DELETE FROM std_document WHERE id = ANY(CAST(:ids AS uuid[]))"),
                      {"ids": [doc_a, doc_b]})
