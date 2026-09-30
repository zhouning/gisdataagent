from scripts.compile_mussafah_formal_scenarios import execution_status, parse_external_inflow_report


REPORT = '''
EPA STORM WATER MANAGEMENT MODEL - VERSION 5.2 (Build 5.2.4)
Flow Units ............... LPS
Flow Routing Method ...... DYNWAVE
Ponding Allowed .......... YES
**************************        Volume        Volume
Flow Routing Continuity        hectare-m      10^6 ltr
**************************     ---------     ---------
External Inflow ..........         3.537        35.369
External Outflow .........         3.397        33.971
Flooding Loss ............         0.025         0.248
Initial Stored Volume ....         0.004         0.043
Final Stored Volume ......         0.123         1.229
Continuity Error (%) .....        -0.102
*********************
Node Flooding Summary
*********************
Node Flooded LPS days hr:min 10^6 ltr Meters
CB1   1.00 20.0 0 12:13 0.500 0.200
CB2   0.01 1.0 0 12:14 0.000 0.001
**********************
Storage Volume Summary
**********************
STO1 99.00 999.0 0 12:13 99.000 99.000
Analysis ended on: Sat Sep 26 17:20:52 2026
'''


def test_parse_dotted_metric_routing_and_bound_node_table():
    parsed = parse_external_inflow_report(REPORT)
    assert parsed['flow_routing_continuity']['external_inflow_million_litre'] == 35.369
    assert parsed['flow_routing_continuity']['final_storage_million_litre'] == 1.229
    assert parsed['node_flooding']['flooded_node_count'] == 2
    assert parsed['node_flooding']['total_flood_volume_m3'] == 500
    assert parsed['node_flooding']['maximum_ponded_depth_m'] == .2
    assert parsed['quality']['node_flood_volume_equals_routing_loss_required'] is False


def test_return_code_zero_does_not_hide_swmm_error():
    parsed = parse_external_inflow_report(REPORT + '\nERROR 217: control syntax\n')
    assert execution_status({'returncode': 0, 'parsed_report': parsed}) == 'failed_diagnostic'


def test_missing_table_is_unknown_not_zero():
    parsed = parse_external_inflow_report('ERROR 217: invalid control')
    assert parsed['node_flooding']['total_flood_volume_m3'] is None
    assert parsed['node_flooding']['flooded_node_count'] is None
    assert parsed['stability']['all_links_stable'] is None


def test_no_flooding_is_explicit_zero():
    text = REPORT.replace('CB1   1.00 20.0 0 12:13 0.500 0.200\nCB2   0.01 1.0 0 12:14 0.000 0.001', 'No nodes were flooded.')
    assert parse_external_inflow_report(text)['node_flooding']['total_flood_volume_m3'] == 0


def test_us_volumes_are_not_silently_labeled_metric():
    import pytest
    with pytest.raises(ValueError, match='unsupported_report_units'):
        parse_external_inflow_report(REPORT.replace('10^6 ltr', '10^6 gal'))
