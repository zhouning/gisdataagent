from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

FILES=("overview.json","source_products.json","lifecycle_channels.json","data_contracts.json","lifecycle_gate.json","map.json")
FORBIDDEN={"asset_condition","maintenance_status","failure_probability","replacement_cost","remaining_life","recovery_time"}
def verify(root:Path):
    payloads={name:json.loads((root/name).read_text()) for name in FILES};bundle_ids={payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids)!=1 or None in bundle_ids:raise ValueError("bundle_mismatch")
    overview=payloads["overview.json"];products=payloads["source_products.json"]["source_products"];channels=payloads["lifecycle_channels.json"]["lifecycle_channels"];gate=payloads["lifecycle_gate.json"]["lifecycle_gate"]
    if overview.get("fabricated_value_count")!=0 or FORBIDDEN&set(overview):raise ValueError("fabricated_lifecycle_output")
    if overview["summary"].get("unique_asset_count") is not None or overview["summary"].get("source_record_count_total") is not None:raise ValueError("overlap_unsafe_asset_total")
    if any(product.get("asset_status")!="catalog_evidence_only" or product.get("identity_evidence") is not None for product in products):raise ValueError("false_authoritative_asset_claim")
    if any(channel.get("status")!="unavailable" or channel.get("value") is not None or channel.get("record_count") is not None for channel in channels.values()):raise ValueError("fabricated_lifecycle_channel")
    if gate.get("status")!="closed" or gate.get("uwm_lifecycle_kernel_status")!="closed" or any(value!="closed" for value in gate["mechanisms"].values()):raise ValueError("false_lifecycle_gate")
    digest=hashlib.sha256("".join((root/name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id":next(iter(bundle_ids)),"summary":overview["summary"],"source_product_ids":[product["product_id"] for product in products],"fabricated_value_count":0,"digest":"sha256:"+digest}
def main():
    parser=argparse.ArgumentParser();parser.add_argument("root",type=Path);args=parser.parse_args();print(json.dumps(verify(args.root),ensure_ascii=False))
if __name__=="__main__":main()
