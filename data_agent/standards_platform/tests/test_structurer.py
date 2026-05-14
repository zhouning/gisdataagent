import uuid, pytest
from sqlalchemy import text
from data_agent.db_engine import get_engine
from data_agent.standards_platform import repository as repo
from data_agent.standards_platform.analysis.structurer import structure_extracted
from data_agent.user_context import current_user_id


@pytest.fixture
def doc_and_version():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    current_user_id.set("u_test")
    code = f"TEST-{uuid.uuid4().hex[:6]}"
    doc_id = repo.create_document(doc_code=code, title="t",
        source_type="enterprise", owner_user_id="u_test", raw_file_path="/tmp/x")
    ver_id = repo.create_version(document_id=doc_id, version_label="v1.0",
                                  created_by="u_test")
    repo.set_current_version(doc_id, ver_id)
    yield doc_id, ver_id
    with eng.connect() as c:
        c.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id}); c.commit()


def test_extractor_dict_to_clause_tree(doc_and_version):
    doc_id, ver_id = doc_and_version
    payload = {
        "FieldTable": [
            {"clause_no": "5.2", "heading": "建设用地", "kind": "section",
             "body_md": "建设用地分类与代码", "page": 12, "char_span": [0, 120]},
            {"clause_no": "5.2.1", "heading": "城市建设用地", "kind": "clause",
             "body_md": "城市建设用地的定义……", "page": 12, "char_span": [121, 320],
             "data_elements": [
                {"code": "URB_LAND_CODE", "name_zh": "城市用地代码",
                 "datatype": "varchar(8)", "obligation": "mandatory"}
             ],
             "terms": [{"term_code": "URB_LAND", "name_zh": "城市建设用地",
                        "definition": "..."}]
            },
        ],
        "LayerTable": [],
    }
    out = structure_extracted(doc_id=doc_id, version_id=ver_id, payload=payload)
    assert out["clauses_inserted"] >= 2
    assert out["data_elements_inserted"] >= 1
    assert out["terms_inserted"] >= 1
