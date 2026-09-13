import json
import pytest
from data_agent.uwm.population_demographic_readiness_service import PopulationDemographicReadinessService

FILES=("overview","evidence_products","demographic_channels","data_contracts","population_gate","map")
def test_service_loads_closed_bundle(tmp_path):
    for name in FILES:
        payload={"bundle_id":"p"}
        if name=="population_gate":payload["population_gate"]={"status":"closed"}
        (tmp_path/f"{name}.json").write_text(json.dumps(payload))
    assert PopulationDemographicReadinessService(tmp_path).population_gate()["population_gate"]["status"]=="closed"
def test_service_rejects_mixed_bundle(tmp_path):
    for i,name in enumerate(FILES):(tmp_path/f"{name}.json").write_text(json.dumps({"bundle_id":str(i)}))
    with pytest.raises(ValueError,match="population_demographic_bundle_mismatch"):PopulationDemographicReadinessService(tmp_path)
