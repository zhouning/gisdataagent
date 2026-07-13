from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from data_agent.uwm.population_demographic_readiness import build_population_demographic_readiness_product

DEFAULT_SPECS=(
 ("district_population_2021","chongqing_district_population_2021/snapshot_manifest.json","district_population_context",2021,"district","district_count",None),
 ("ghsl_population_2020","ghsl/snapshot_manifest.json","population_spatial_proxy",2020,"raster_tile",None,None),
 ("ghsl_admin_alignment","ghsl_admin_alignment/ghsl_admin_alignment_manifest.json","population_spatial_proxy",2020,"township_admin_proxy",None,"ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv"),
 ("population_downscaling_2021","fitted_gap_filling_2026_07_05/population_downscaling_proxy.json","population_downscaling_proxy",2021,"admin_proxy",None,"fitted_gap_filling_2026_07_05/population_downscaling_admin_rows.csv"),
)
def _csv_rows(path):return max(sum(1 for _ in path.open())-1,0)
def _write(product,output_dir):
    output_dir.mkdir(parents=True,exist_ok=True);bid=product["bundle_id"]
    payloads={
     "overview.json":{k:v for k,v in product.items() if k not in {"evidence_products","demographic_channels","data_contracts","population_gate"}},
     "evidence_products.json":{"schema":"uwm.population_evidence_products.v1","bundle_id":bid,"evidence_products":product["evidence_products"]},
     "demographic_channels.json":{"schema":"uwm.demographic_channels.v1","bundle_id":bid,"demographic_channels":product["demographic_channels"]},
     "data_contracts.json":{"schema":"uwm.population_demographic_contracts.v1","bundle_id":bid,"data_contracts":product["data_contracts"]},
     "population_gate.json":{"schema":"uwm.population_dynamics_gate.v1","bundle_id":bid,"population_gate":product["population_gate"]},
     "map.json":{"schema":"uwm.population_demographic_map.v1","bundle_id":bid,"layers":[{"product_id":p["product_id"],"source_path":p["source_path"],"spatial_grain":p["spatial_grain"],"geometry_embedded":False} for p in product["evidence_products"]]},
    }
    for name,payload in payloads.items():
        temp=output_dir/f".{name}.tmp";temp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")));temp.replace(output_dir/name)
def build_product(*,evidence_specs,output_dir):
    products=[]
    for spec in evidence_specs:
        path=Path(spec["source_path"]);payload=json.loads(path.read_text());summary=payload.get("summary") or {};count=summary.get(spec.get("record_count_field")) if spec.get("record_count_field") else None
        if count is None and spec.get("row_path"):count=_csv_rows(Path(spec["row_path"]))
        products.append({"product_id":spec["product_id"],"source_path":str(path),"dataset_id":payload.get("dataset_id"),"evidence_role":spec["evidence_role"],"observation_year":spec.get("observation_year"),"spatial_grain":spec["spatial_grain"],"record_count":count,"population_status":"fragile_context_or_proxy","claim_level":(payload.get("claim_boundary") or {}).get("max_claim_level"),"limitations":["not_current_authoritative_population","no_customer_required_demographic_structure","not_longitudinal_growth_evidence"]})
    product=build_population_demographic_readiness_product(evidence_products=products,source_artifacts=[p["source_path"] for p in products]);_write(product,Path(output_dir));return product
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--source-root",type=Path,required=True);parser.add_argument("--output-dir",type=Path,required=True);args=parser.parse_args()
    specs=[{"product_id":i,"source_path":args.source_root/r,"evidence_role":role,"observation_year":year,"spatial_grain":grain,"record_count_field":field,"row_path":args.source_root/rows if rows else None} for i,r,role,year,grain,field,rows in DEFAULT_SPECS]
    product=build_product(evidence_specs=specs,output_dir=args.output_dir);print(json.dumps({"bundle_id":product["bundle_id"],"summary":product["summary"]},ensure_ascii=False))
if __name__=="__main__":main()
