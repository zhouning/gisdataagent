"""Small deterministic ANUGA execution used by the portable runtime smoke test."""

from __future__ import annotations

import json
from pathlib import Path

import anuga
import numpy as np


def main() -> None:
    output = Path.cwd()
    domain = anuga.rectangular_cross_domain(8, 4, len1=80.0, len2=40.0)
    domain.set_name("anuga_portable_smoke")
    domain.set_datadir(str(output))
    domain.set_quantity("elevation", lambda x, y: 0.001 * x)
    domain.set_quantity("friction", 0.03)
    domain.set_quantity("stage", 0.0)
    boundary = anuga.Dirichlet_boundary([0.0, 0.0, 0.0])
    domain.set_boundary(
        {"left": boundary, "right": boundary, "top": boundary, "bottom": boundary}
    )
    anuga.Rate_operator(domain, rate=2.0e-5, label="synthetic_uniform_rainfall")
    for _ in domain.evolve(yieldstep=10.0, finaltime=40.0):
        pass
    depth = np.asarray(domain.quantities["stage"].centroid_values) - np.asarray(
        domain.quantities["elevation"].centroid_values
    )
    summary = {
        "schema": "gwm.abu_dhabi_flood.anuga_portable_smoke.v1",
        "status": "completed",
        "anuga_version": str(getattr(anuga, "__version__", "unknown")),
        "triangle_count": int(len(depth)),
        "minimum_depth_m": float(np.min(depth)),
        "maximum_depth_m": float(np.max(depth)),
        "finite": bool(np.isfinite(depth).all()),
        "output": "anuga_portable_smoke.sww",
    }
    (output / "anuga_smoke_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
