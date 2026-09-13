from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


FILES = ("overview.json", "version_assets.json", "version_channels.json", "data_contracts.json", "temporal_gate.json", "map.json")


def verify(root: Path):
    payloads = {name: json.loads((root / name).read_text()) for name in FILES}; bundle_ids = {payload.get("bundle_id") for payload in payloads.values()}
    if len(bundle_ids) != 1 or None in bundle_ids: raise ValueError("bundle_mismatch")
    overview = payloads["overview.json"]; assets = payloads["version_assets.json"]["version_assets"]; channels = payloads["version_channels.json"]["version_channels"]; gate = payloads["temporal_gate.json"]["temporal_gate"]
    if overview.get("fabricated_value_count") != 0: raise ValueError("fabricated_value")
    if any(asset.get("approval_status") != "unverified" or asset.get("version_status") == "current" or asset.get("effective_start") is not None for asset in assets): raise ValueError("false_version_claim")
    if any(channel.get("status") != "unavailable" or channel.get("value") is not None for channel in channels.values()): raise ValueError("fabricated_version_channel")
    if gate.get("status") != "closed" or gate.get("uwm_temporal_baseline_status") != "closed" or any(value != "closed" for value in gate["mechanisms"].values()): raise ValueError("false_temporal_baseline")
    digest = hashlib.sha256("".join((root / name).read_text() for name in FILES).encode()).hexdigest()
    return {"bundle_id": next(iter(bundle_ids)), "summary": overview["summary"], "asset_ids": [asset["asset_id"] for asset in assets], "fabricated_value_count": 0, "digest": "sha256:" + digest}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("root", type=Path); args = parser.parse_args(); print(json.dumps(verify(args.root), ensure_ascii=False))


if __name__ == "__main__": main()
