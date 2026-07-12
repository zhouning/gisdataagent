from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
FILES=('overview.json','platform_capabilities.json','infrastructure_channels.json','data_contracts.json','uwm_gate.json','map.json');FORBIDDEN={'smart_city_score','digital_maturity_score','iot_coverage_rate','camera_coverage_rate','wifi_coverage_rate','five_g_coverage_rate','device_online_rate','digital_service_usage_rate','smart_district_rank','digital_investment_return','smart_policy_effect'}
def verify(root:Path):
 p={n:json.loads((root/n).read_text()) for n in FILES};ids={x.get('bundle_id') for x in p.values()}
 if len(ids)!=1 or None in ids:raise ValueError('bundle_mismatch')
 o=p['overview.json'];caps=p['platform_capabilities.json']['platform_capabilities'];channels=p['infrastructure_channels.json']['infrastructure_channels'];gate=p['uwm_gate.json']['uwm_gate']
 if o.get('fabricated_value_count')!=0 or FORBIDDEN & set(o):raise ValueError('invalid_overview')
 if any(x['status']=='verified' and not x.get('evidence_artifacts') for x in caps):raise ValueError('unverified_capability')
 if any(x['status']=='unavailable' and x.get('value') is not None for x in channels.values()):raise ValueError('fabricated_coverage')
 if any(v!='closed' for v in gate['mechanisms'].values()):raise ValueError('false_dynamic_mechanism')
 digest=hashlib.sha256(''.join((root/n).read_text() for n in FILES).encode()).hexdigest();return {'bundle_id':next(iter(ids)),'summary':o['summary'],'fabricated_value_count':0,'digest':'sha256:'+digest}
def main():
 q=argparse.ArgumentParser();q.add_argument('root',type=Path);a=q.parse_args();print(json.dumps(verify(a.root),ensure_ascii=False))
if __name__=='__main__':main()
