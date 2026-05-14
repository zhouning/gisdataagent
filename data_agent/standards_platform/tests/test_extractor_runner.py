from unittest.mock import patch, MagicMock
from data_agent.standards_platform.ingestion.extractor_runner import run_extractor


def test_dispatches_to_docx_extractor(tmp_path):
    f = tmp_path / "x.docx"; f.write_bytes(b"PK")
    with patch("data_agent.standards_platform.ingestion.extractor_runner.docx_extract",
               return_value={"FieldTable": [{"name": "n"}], "LayerTable": []}) as fake:
        out = run_extractor(str(f))
    fake.assert_called_once()
    assert "FieldTable" in out


def test_dispatches_to_xmi_parser(tmp_path):
    f = tmp_path / "m.xmi"; f.write_text("<XMI/>", encoding="utf-8")
    with patch("data_agent.standards_platform.ingestion.extractor_runner.parse_xmi_file",
               return_value=MagicMock(modules=[], classes=[])) as fake:
        out = run_extractor(str(f))
    fake.assert_called_once()
    assert "modules" in out


def test_unknown_ext_raises(tmp_path):
    f = tmp_path / "x.csv"; f.write_text("a,b")
    import pytest
    with pytest.raises(ValueError, match="unsupported"):
        run_extractor(str(f))
