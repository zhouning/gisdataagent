from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=("overview.json","evidence_products.json","demographic_channels.json","data_contracts.json","population_gate.json","map.json")
FORBIDDEN={"gender_ratio","nationality_ratio","citizen_ratio","household_size","population_growth_rate","forecast_population","service_demand_forecast"}
def verify(root:Path):
 payloads={name:json.loads((root/name).read_text()) for name in FILES};ids={p.get("bundle_id") for p in payloads.values()}
 if len(ids)!=1 or None in ids:raise ValueError("bundle_mismatch")
 overview=payloads["overview.json"];products=payloads["evidence_products.json"]["evidence_products"];channels=payloads["demographic_channels.json"]["demographic_channels"];gate=payloads["population_gate.json"]["population_gate"]
 if overview.get("fabricated_value_count")!=0 or FORBIDDEN&set(overview):raise ValueError("fabricated_population_output")
 if overview["summary"].get("authoritative_current_population") is not None or overview["summary"].get("forecast_population") is not None:raise ValueError("false_population_claim")
 if any(p.get("population_status")!="fragile_context_or_proxy" for p in products):raise ValueError("proxy_promoted")
 if any(c.get("status")!="unavailable" or c.get("value") is not None or c.get("record_count") is not None for c in channels.values()):raise ValueError("fabricated_demographic_channel")
 if gate.get("status")!="closed" or gate.get("uwm_population_kernel_status")!="closed" or any(v!="closed" for v in gate["mechanisms"].values()):raise ValueError("false_population_gate")
 digest=hashlib.sha256("".join((root/n).read_text() for n in FILES).encode()).hexdigest();return {"bundle_id":next(iter(ids)),"summary":overview["summary"],"evidence_product_ids":[p["product_id"] for p in products],"fabricated_value_count":0,"digest":"sha256:"+digest}
def main():
 parser=argparse.ArgumentParser();parser.add_argument("root",type=Path);args=parser.parse_args();print(json.dumps(verify(args.root),ensure_ascii=False))
if __name__=="__main__":main()
