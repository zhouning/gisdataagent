# Mussafah_00 map integration checkpoint

## Branch and integration baseline

This work belongs on `feat/abu-dhabi-mussafah00-gap-analysis`, based on
`feat/abu-dhabi-hydrodynamics-reproducible-runtime` at `847c467a`.
The original `bda879a1` checkpoint was incorrectly pushed to
`feat/abu-dhabi-nl2semantic2sql-productization`. This branch transfers its
Mussafah changes without importing the unrelated NL2SQL branch history.

Conflict resolution preserves the runtime baseline's synchronous coupling
exports, portable data-root configuration, rainfall-profile workflow,
Al Bateen routes, legacy partial-result entry, and other workspace styles.

## Verification on 2026-09-30

- Production frontend build succeeded, including the standalone map bundle.
- 86 targeted Python tests and 24 frontend tests passed.
- Existing-data smoke checks passed for all seven Mussafah scenarios:
  summaries, first playback frames and maximum-depth layers; catchment,
  terrain metadata and workspace bootstrap also returned HTTP 200.
  The unauthenticated scenario request returned HTTP 401.
- Additional route regressions: 11 passed and 4 failed. The same four
  failures were reproduced in a separate clean checkout of `847c467a`:
  two RD-F route tests, the latest-506 hotspot route test and a GWM route
  test whose mocked bootstrap signature omits rainfall selection arguments.
  These pre-existing failures are not reported as passing.
- These checks verify the branch transfer and access to existing artifacts;
  they do not rerun or recalibrate the hydraulic simulations.

## Entry point

The native GIS Data Agent workspace opens through `http://localhost:8000` after
authentication. The flood comparison publishes the formal catchment boundary,
scenario infrastructure, flood depth and scenario playback to the main map.
The catchment appears in the layer list and can be toggled independently.

## Included in Git

- Native flood comparison UI, map layers, timeline and 3D terrain integration.
- Authenticated Mussafah scenario, result, difference and terrain routes.
- Formal catchment polygon in source EPSG:32640 and display EPSG:4326.
- Compact 5 m terrain grid, encoded height image and metadata.
- SWMM/ANUGA adapters, scenario compilation and result-processing scripts.

## External runtime data

The approximately 11 GB of raw coupled results, source model packages and
customer delivery files remain on the workstation. This commit is a code and
map-asset checkpoint; cloning it does not download the hydraulic result archive.
Closing the application window does not delete those files.

The backend retains the current workstation paths as defaults. On another
machine, mount the corresponding packages and set these variables before startup:

| Variable | Package |
| --- | --- |
| `ABU_DHABI_MUSSAFAH_REAL_COUPLED_DIR` | `/Users/zhouning/.tmp/mussafah00_coupled/real_runs` |
| `ABU_DHABI_MUSSAFAH_DELIVERY_DIR` | `flood/解决方案_20260924/下一阶段推进_20260925/Mussafah00_Gap优化交付_20260926` |
| `ABU_DHABI_MUSSAFAH_FORMAL_DIR` | `flood/解决方案_20260924/下一阶段推进_20260925/正式场景编译_20260926` |
| `ABU_DHABI_MUSSAFAH_OLD_5M_DIR` | `flood/解决方案_20260924/局部试点_20260925/Mussafah_00_three_defense_lines_5m` |

The three `flood/` paths above are relative to
`/Users/zhouning/Downloads/阿布扎比/` on the current workstation.
Scenario readiness and engineering-admission flags continue to come from the
result packages; committing the integration does not change their validation status.
