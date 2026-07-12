from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES = ("overview.json", "source_assets.json", "state_channels.json", "data_contracts.json", "state_gate.json", "map.json")
FORBIDDEN = {"land_use_distribution", "parcel_area_by_class", "planning_conflict_count", "legal_parcel_status", "observed_transition", "future_land_use"}


def verify(root: Path):
    payloads = {name: json.loads((root / name).read_text()) for name in FILES}; bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("bundle_mismatch")
    overview = payloads["overview.json"]; assets = payloads["source_assets.json"]["source_assets"]; channels = payloads["state_channels.json"]["state_channels"]; gate = payloads["state_gate.json"]["state_gate"]
    if overview.get("fabricated_value_count") != 0 or FORBIDDEN & set(overview): raise ValueError("fabricated_state_output")
    primary = [asset for asset in assets if asset.get("asset_role") == "primary_land_use_state_source"]
    if len(primary) != 1 or primary[0].get("required_state_fields_present") is not True or primary[0].get("source_rows_materialized") is not False: raise ValueError("invalid_primary_state_audit")
    if any(asset.get("version_status") != "unresolved" or asset.get("state_status") != "schema_audit_only" for asset in assets): raise ValueError("false_observed_state")
    if any(channel.get("status") != "unavailable" or channel.get("value") is not None or channel.get("record_count") is not None for channel in channels.values()): raise ValueError("fabricated_state_channel")
    if gate.get("status") != "closed" or gate.get("traditional_gis_state_status") != "closed" or gate.get("uwm_transition_status") != "closed" or any(value != "closed" for value in gate["mechanisms"].values()): raise ValueError("false_state_gate")
    digest = hashlib.sha256("".join((root / name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id": next(iter(bundle_ids)), "summary": overview["summary"], "asset_ids": [asset["asset_id"] for asset in assets], "fabricated_value_count": 0, "digest": "sha256:" + digest}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("root", type=Path); args = parser.parse_args(); print(json.dumps(verify(args.root), ensure_ascii=False))


if __name__ == "__main__": main()
