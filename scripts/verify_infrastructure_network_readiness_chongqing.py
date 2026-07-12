from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES = ("overview.json", "infrastructure_assets.json", "utility_channels.json", "data_contracts.json", "kernel_gate.json", "map.json")
FORBIDDEN = {"utility_capacity", "network_condition", "outage_count", "failure_probability", "recovery_time", "cascade_risk", "service_reliability"}


def verify(root: Path):
    payloads = {name: json.loads((root / name).read_text()) for name in FILES}; bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("bundle_mismatch")
    overview = payloads["overview.json"]; assets = payloads["infrastructure_assets.json"]["infrastructure_assets"]; channels = payloads["utility_channels.json"]["utility_channels"]; gate = payloads["kernel_gate.json"]["kernel_gate"]
    if overview.get("fabricated_value_count") != 0 or FORBIDDEN & set(overview): raise ValueError("fabricated_infrastructure_output")
    commuting = [asset for asset in assets if asset.get("source_kind") == "commuting_od_proxy"]
    if any(asset.get("asset_role") == "telecom_network_observation" for asset in commuting): raise ValueError("proxy_misclassified")
    if any(asset.get("capacity_status") != "unavailable" or asset.get("ownership_status") != "unavailable" or asset.get("operations_status") != "unavailable" for asset in assets): raise ValueError("false_asset_state")
    if any(channel.get("status") != "unavailable" or channel.get("value") is not None or channel.get("record_count") is not None for channel in channels.values()): raise ValueError("fabricated_utility_channel")
    if gate.get("status") != "closed" or gate.get("utility_observation_status") != "closed" or gate.get("uwm_cascade_kernel_status") != "closed" or any(value != "closed" for value in gate["mechanisms"].values()): raise ValueError("false_kernel_gate")
    digest = hashlib.sha256("".join((root / name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id": next(iter(bundle_ids)), "summary": overview["summary"], "asset_ids": [asset["asset_id"] for asset in assets], "fabricated_value_count": 0, "digest": "sha256:" + digest}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("root", type=Path); args = parser.parse_args(); print(json.dumps(verify(args.root), ensure_ascii=False))


if __name__ == "__main__": main()
