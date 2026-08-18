from data_agent.intent_router import _LANG_HINTS, detect_language


def test_detects_arabic_text():
    assert detect_language("حلل استخدامات الأراضي في أبوظبي") == "ar"


def test_detects_mixed_arabic_with_gis_identifier():
    assert detect_language("حلل CRS و GeoJSON لهذه القطعة") == "ar"


def test_arabic_response_hint_is_available():
    assert "العربية" in _LANG_HINTS["ar"]
