# Legacy Test Compatibility Baseline (2026-07-26)

## Purpose

This document records the first complete Linux/Python 3.13 execution of the
legacy `data_agent/` test directory on the active platform lineage. It is a
compatibility inventory, not a release gate and not evidence that production
is ready.

## Frozen Evidence

- GitHub Actions run: [CI run 30198018519](https://github.com/zhouning/gisdataagent/actions/runs/30198018519)
- Revision: `77e2fd83f2629448adab1524505e1b1e79fca46a`
- Runtime: Ubuntu, Python 3.13, PostGIS 16/3.4
- Command: `python -m pytest data_agent/ --ignore=data_agent/test_knowledge_agent.py -q`
- Result: 6,424 passed, 853 failed, 38 skipped, 252 errors, 1,528 warnings
- Duration: 978.80 seconds

The run completed collection and executed the entire directory. Its failure is
therefore useful evidence about legacy compatibility debt; it must not be
silenced or represented as an AR-0/AR-1 platform regression.

## Failure Taxonomy

The dominant failure families are:

1. Legacy database prerequisites are absent. Standards-platform tests expect
   tables such as `std_document`, `std_outbox`, and semantic hint tables that
   are outside the AR-0/AR-1 control-ledger migration boundary.
2. External runtimes are not provisioned. Several tests expect a Gemini API
   key, ArcPy/MCP services, or other workstation-bound integrations.
3. GIS binary data is inconsistent. Raster tests see incompatible PROJ data
   layouts between installed wheels and system GDAL/PROJ packages.
4. Research fixtures are not repository-portable. UWM/TWM tests reference
   unversioned datasets or absolute `/Users/zhouning/gisdataagent` paths.
5. Assertions encode older behavior. A smaller residual group reaches the
   implementation but expects results from earlier model and routing contracts.

## CI Decision

The required PR gate is `Platform Required Tests`. It covers the AR-0/AR-1
configuration, migrations, contracts, gateway, DolphinScheduler adapter and
worker, staging evidence chain, authentication boundaries, and PostgreSQL
control-ledger behavior.

The complete legacy inventory is retained as the manually dispatched
`Diagnostic - Legacy Compatibility` workflow. That workflow is expected to
remain red until its prerequisites and assertions are migrated. A red legacy
inventory does not authorize bypassing a required platform check, publishing a
candidate, or deploying to Kubernetes.

## Remediation Order

1. Make database test families create and migrate isolated schemas.
2. Separate hermetic unit tests from credentialed integration tests.
3. Pin one compatible GDAL/PROJ/rasterio/pyproj runtime and verify it in a
   container image.
4. Replace absolute paths with repository fixtures or explicit data manifests.
5. Re-baseline behavioral assertions only after the owning contract is named.

Each family moves into the required gate only after it is deterministic on a
clean Linux runner. The frozen counts above remain unchanged for auditability.
