from tools import validate_geometry_cmd, topology_checker_cmd, raster_calculator_cmd


def test_validate_geometry_cmd_structure():
    cmd = validate_geometry_cmd("/data/parcels.shp")
    assert cmd["algorithm"] == "qgis:checkvalidity"
    assert cmd["parameters"]["INPUT_LAYER"] == "/data/parcels.shp"
    assert cmd["parameters"]["METHOD"] == 2


def test_topology_checker_cmd_includes_rules():
    rules = ["must not overlap", "must not have gaps"]
    cmd = topology_checker_cmd("/data/parcels.shp", rules)
    assert cmd["algorithm"] == "qgis:topologychecker"
    assert cmd["parameters"]["RULES"] == rules


def test_raster_calculator_cmd_has_expression():
    cmd = raster_calculator_cmd('"band1@1" * 2', "/tmp/out.tif", ["/data/dem.tif"])
    assert cmd["algorithm"] == "qgis:rastercalculator"
    assert '"band1@1" * 2' in cmd["parameters"]["EXPRESSION"]
    assert len(cmd["parameters"]["LAYERS"]) == 1
