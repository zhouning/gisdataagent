from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES = ("overview.json", "rule_assets.json", "dcr_channels.json", "data_contracts.json", "execution_gate.json", "map.json")
FORBIDDEN = {"legal_floor_area_ratio", "legal_building_density", "legal_building_height", "legal_green_space_ratio", "legal_setback", "buildable_area", "development_scale", "construction_permission", "project_approval", "compliance_decision"}


def verify(root: Path):
    payloads = {name: json.loads((root / name).read_text()) for name in FILES}
    bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids) != 1 or None in bundle_ids:
        raise ValueError("bundle_mismatch")
    overview = payloads["overview.json"]
    assets = payloads["rule_assets.json"]["rule_assets"]
    channels = payloads["dcr_channels.json"]["dcr_channels"]
    gate = payloads["execution_gate.json"]["execution_gate"]
    if overview.get("fabricated_value_count") != 0 or FORBIDDEN & set(overview):
        raise ValueError("invalid_overview")
    if any(not asset.get("source_path") or asset.get("execution_status") == "executable" for asset in assets):
        raise ValueError("invalid_rule_asset")
    if any(channel.get("status") != "unavailable" or channel.get("value") is not None for channel in channels.values()):
        raise ValueError("fabricated_dcr_parameter")
    if gate.get("status") != "closed" or any(value != "closed" for value in gate["mechanisms"].values()):
        raise ValueError("false_dcr_execution")
    digest = hashlib.sha256("".join((root / name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id": next(iter(bundle_ids)), "summary": overview["summary"], "fabricated_value_count": 0, "digest": "sha256:" + digest}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=False))


if __name__ == "__main__":
    main()
