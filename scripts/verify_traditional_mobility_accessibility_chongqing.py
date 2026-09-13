from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES=("overview.json","admin_units.json","channel_readiness.json","map.json")


def verify_product(product_dir: Path) -> dict:
    root=Path(product_dir); payloads={name:json.loads((root/name).read_text(encoding="utf-8")) for name in FILES}
    bundle_ids={payload.get("bundle_id") for payload in payloads.values()}; channels=payloads["channel_readiness.json"]["channels"]
    violations=sum(1 for row in channels.values() if row.get("status")=="unavailable" and row.get("value") is not None)
    errors=[]
    if len(bundle_ids)!=1 or None in bundle_ids: errors.append("bundle_id_mismatch")
    if payloads["overview.json"].get("fabricated_value_count")!=0: errors.append("fabricated_values_present")
    if violations: errors.append("unavailable_channel_numeric_values_present")
    digest=hashlib.sha256("".join(json.dumps(payloads[name],sort_keys=True,ensure_ascii=False) for name in FILES).encode()).hexdigest()
    return {"valid":not errors,"errors":errors,"bundle_id":next(iter(bundle_ids)) if len(bundle_ids)==1 else None,"fabricated_value_count":payloads["overview.json"].get("fabricated_value_count"),"unavailable_channel_numeric_violation_count":violations,"admin_unit_count":len(payloads["admin_units.json"]["admin_units"]),"verification_digest":"sha256:"+digest}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("product_dir",type=Path); args=parser.parse_args(); result=verify_product(args.product_dir); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["valid"] else 2


if __name__ == "__main__": raise SystemExit(main())
