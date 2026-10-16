"""Check every frozen dependency before model/data access and preservation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_runtime_freeze(root: Path) -> dict:
    root = root.resolve()
    dependencies = json.loads((root / "dependency_freeze.json").read_text())
    preparation = json.loads((root / "freeze_preparation.json").read_text())
    resources = preparation["nonpython_sha256"]
    if not dependencies or preparation["python_file_count"] != len(dependencies):
        raise ValueError("Frozen dependency count differs from preparation")
    # Never merge maps: an overlapping resource entry can mask a stale Python
    # digest (e.g. a renamed runner). Verify both declarations independently.
    conflicts = [name for name in dependencies.keys() & resources.keys()
                 if dependencies[name] != resources[name]]
    if conflicts:
        raise ValueError("Conflicting frozen declarations: " + ", ".join(sorted(conflicts)))
    for label, mapping in (("dependency", dependencies), ("resource", resources)):
        for name, digest in mapping.items():
            path = (root / name).resolve()
            if (Path(name).is_absolute() or not path.is_relative_to(root) or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise ValueError(f"Frozen {label} differs: {name}")
    return {"python_files_verified": len(dependencies), "resource_declarations_verified": len(resources),
            "overlapping_declarations_verified": len(dependencies.keys() & resources.keys()),
            "dependency_manifest_sha256": hashlib.sha256((root / "dependency_freeze.json").read_bytes()).hexdigest(),
            "preparation_sha256": hashlib.sha256((root / "freeze_preparation.json").read_bytes()).hexdigest(),
            "all_frozen_files_verified": True}
