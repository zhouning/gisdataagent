#!/usr/bin/env python3
"""Diagnostic phase-1 entry point for the DLTB semantic demo.

The implementation remains in ``run_dltb_vertical_demo.py`` for backwards
compatibility with existing Windows runbooks. This alias makes the two-stage
demo boundary explicit: this command stops before Paper9. The customer-facing
entry point is the GIS Data Agent page's browser ZIP upload; this command is
for repeatable diagnostics and offline acceptance evidence. PostGIS is the
default semantic execution engine. Use ``--semantic-execution-engine lake``
on a host without PostgreSQL; use ``geopandas`` only for diagnostics.
"""

from __future__ import annotations

try:  # Running from the repository root or directly from scripts/.
    from scripts.run_dltb_vertical_demo import main
except ModuleNotFoundError:  # pragma: no cover - direct Windows invocation
    from run_dltb_vertical_demo import main


if __name__ == "__main__":
    raise SystemExit(main())
