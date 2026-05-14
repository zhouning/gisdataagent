from unittest.mock import patch, MagicMock
from data_agent.standards_platform.ingestion.classifier import classify


def _fake_llm(json_response: dict):
    fake = MagicMock()
    fake.generate.return_value = MagicMock(text=__import__("json").dumps(json_response))
    return fake


def test_recognises_national_gb():
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=_fake_llm({"source_type": "national",
                                       "doc_code": "GB/T 13923-2022", "confidence": 0.93})):
        out = classify(filename="GB-T-13923-2022.docx",
                       text_excerpt="基础地理信息要素分类与代码")
    assert out["source_type"] == "national"
    assert out["doc_code"].startswith("GB/T 13923")


def test_recognises_industry_ch():
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=_fake_llm({"source_type": "industry",
                                       "doc_code": "CH/T 9011-2018", "confidence": 0.9})):
        out = classify(filename="CH-T-9011-2018.docx", text_excerpt="基础地理信息数字成果...")
    assert out["source_type"] == "industry"


def test_falls_back_to_enterprise_when_unrecognised():
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=_fake_llm({"source_type": "enterprise",
                                       "doc_code": "SMP-DS-001", "confidence": 0.4})):
        out = classify(filename="internal-spec.docx", text_excerpt="本院数据规范...")
    assert out["source_type"] == "enterprise"


def test_handles_llm_failure_gracefully():
    fake = MagicMock(); fake.generate.side_effect = RuntimeError("upstream down")
    with patch("data_agent.standards_platform.ingestion.classifier.create_model",
               return_value=fake):
        out = classify(filename="x.docx", text_excerpt="...")
    assert out["source_type"] == "draft"  # safe fallback
    assert out["confidence"] == 0.0
