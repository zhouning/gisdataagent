from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from typing import Any
FILES=('overview.json','facilities.json','admin_units.json','channel_readiness.json','map.json')
def verify_product(product_dir: Path)->dict[str,Any]:
    payloads={name:json.loads((product_dir/name).read_text(encoding='utf-8')) for name in FILES}
    ids={p.get('bundle_id') for p in payloads.values()}
    if len(ids)!=1: raise ValueError('bundle_id_mismatch')
    facilities=payloads['facilities.json']['facilities']; seen=set()
    for row in facilities:
        if row['facility_id'] in seen: raise ValueError('duplicate_facility_id')
        seen.add(row['facility_id'])
        if not row.get('source_dataset') or not row.get('source_record_id'): raise ValueError('facility_source_trace_missing')
        for field in ('capacity','lifecycle_status','active_status','service_radius_m'):
            if row.get(field) is not None: raise ValueError('unavailable_numeric_or_status_value_present')
    readiness=payloads['channel_readiness.json']['channel_readiness']
    for view in readiness.values():
        for channel in view.values():
            if channel['status']=='unavailable' and channel.get('value') is not None: raise ValueError('unavailable_channel_value_present')
    overview=payloads['overview.json']
    if overview.get('fabricated_value_count')!=0: raise ValueError('fabricated_value_count_nonzero')
    digest=hashlib.sha256(''.join((product_dir/n).read_text(encoding='utf-8') for n in FILES).encode()).hexdigest()
    return {'verified':True,'bundle_id':ids.pop(),'facility_count':len(facilities),'admin_unit_count':len(payloads['admin_units.json']['admin_units']),'fabricated_value_count':0,'verification_digest':'sha256:'+digest}
def main():
 p=argparse.ArgumentParser();p.add_argument('--product-dir',type=Path,required=True);a=p.parse_args();print(json.dumps(verify_product(a.product_dir),ensure_ascii=False))
if __name__=='__main__':main()
