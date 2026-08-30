from __future__ import annotations

from pathlib import Path

FRONTEND = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "src"
    / "components"
    / "datapanel"
    / "OfflineIngestTab.tsx"
)


def test_dltb_frontend_defaults_to_postgis_and_exposes_verified_alternatives():
    source = FRONTEND.read_text(encoding="utf-8")

    assert "useState<'postgis' | 'lake' | 'geopandas'>('postgis')" in source
    assert "execution_engine: semanticEngine" in source
    assert "publish_postgis: true" in source
    assert "['postgis', 'PostGIS'" in source
    assert "['lake', '数据湖 SQL'" in source
    assert "['geopandas', '诊断'" in source
    assert "fallback_used" in source
    assert "request_id" in source
