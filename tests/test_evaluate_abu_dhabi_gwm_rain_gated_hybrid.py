from scripts.evaluate_abu_dhabi_gwm_rain_gated_hybrid import _gate_name


def test_gate_names_cover_fallback_and_ungated_modes() -> None:
    assert _gate_name(0.0) == "linear_fallback"
    assert _gate_name(2.0) == "exp_cumulative_rain_scale_2mm"
    assert _gate_name(None) == "ungated"
