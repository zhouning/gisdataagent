# Abu Dhabi Origen Hotspots and GWM Validation Runbook

## Purpose and evidence boundary

This workflow converts the three private Origen Batch 1 stormwater workbooks
into an authenticated serving bundle and uses the locations for static spatial
diagnostics. The source workbooks and generated private artifacts must remain
outside Git.

The hotspot inventory may be used as an auxiliary static feature, a spatial
prior, or an external diagnostic. It must not be used as event water-depth or
flood-extent ground truth. Narrative intervention fields must not be converted
directly into hydraulic benefits without approved engineering parameters.

## Build the private hotspot bundle

Set local paths before running the importer:

```bash
export ORIGEN_SOURCE_ROOT="/path/to/Flood Management Data - Origen - Batch1"
export HOTSPOT_BUNDLE_ROOT="$HOME/.local/share/gisdataagent/private/abu_dhabi_stormwater/origen_hotspots_batch1"
export SWMM_NODE_PATH="/path/to/abu_dhabi_customer_stormwater_topology_nodes_full.fgb"
export RP005_DEPTH_PATH="/path/to/rp005/maximum_depth_wgs84.geojson"
export RP100_DEPTH_PATH="/path/to/rp100/maximum_depth_wgs84.geojson"

python scripts/import_abu_dhabi_origen_hotspots.py \
  --source-root "$ORIGEN_SOURCE_ROOT" \
  --output-root "$HOTSPOT_BUNDLE_ROOT" \
  --swmm-nodes "$SWMM_NODE_PATH" \
  --depth-result "5=$RP005_DEPTH_PATH" \
  --depth-result "100=$RP100_DEPTH_PATH"
```

The importer ignores Excel lock files, preserves source hashes and formulas for
audit, normalizes coordinates, keeps the ADM historical inventory separate,
and records workbook-wide formulas, cached Excel errors, and external-link
relationships. The repository receives code only; it does not receive the
workbooks or generated bundle.

The API reads the default bundle location above. Override it with
`ABU_DHABI_HOTSPOT_BUNDLE_ROOT` when necessary. These authenticated endpoints
serve normalized data only:

- `/api/abu-dhabi/flood/hotspots/catalog`
- `/api/abu-dhabi/flood/hotspots/map?inventory=current`
- `/api/abu-dhabi/flood/hotspots/map?inventory=history`
- `/api/abu-dhabi/flood/gwm/external-validation`
- `/api/abu-dhabi/flood/validation/report`

## Batch 1 acceptance snapshot

The 2026-09-18 import produced 590 current hotspots and 255 separate ADM
historical records. Current counts are ADM 251, AAM 184, and DRM 155. There are
99 Very High, 143 High, 298 Medium, and 50 Low records; 439 report a drainage
network and 151 report no network. All coordinates are usable after 16
auditable normalizations.

The workbook audit found 32,203 formula cells, 2,606 cached Excel errors, and
one ADM external-link relationship. The `#` hotspot-ID header is intentionally
not counted as an Excel error. Of the current ADM hotspots, 220 have a SWMM
node candidate within 500 m. Those links are candidates, not confirmed asset
identities.

Within the available model domain, 187 of 224 hotspots intersect at least 1 cm
in the 5-year result and 215 of 224 do so in the 100-year result. These are
static location concordance figures only. They are shown beside, but never
substituted for, the event-level external-validation cohorts described below.

## External-validation serving contract

The authenticated external-validation endpoint reads the frozen confirmatory
and supplementary receipts from private local storage. It verifies each
receipt's declared canonical hash, computes a file hash, checks within- and
cross-cohort event duplication, and publishes a path-free aggregate ledger.
Raw event IDs, source paths, and prediction arrays are not returned.

The 2026-09-18 ledger contains four strict Sentinel-2 confirmatory events out
of the preregistered target of five and two source-specific supplementary
events out of five. The event sets do not overlap, so six independent events
have been evaluated, but performance metrics are not pooled across the
Sentinel-2, Landsat, and Sentinel-1 observation contracts. The resulting
engineering-admission flag remains `false`.

Use `ABU_DHABI_GWM_CONFIRMATORY_RECEIPT` and
`ABU_DHABI_GWM_SUPPLEMENTARY_RECEIPT` to override the two default private
receipt locations. These environment values and their resolved paths are
never returned by the API.

## Reproduce supplementary GWM evaluation

The supplementary cohort is evaluation-only. Keep its events out of training,
and keep optical and SAR results source-specific.

```bash
python scripts/prepare_abu_dhabi_gwm_supplementary_physics_batch.py \
  --cohort /path/to/frozen_supplementary_final_cohort_v1.json \
  --era5 /path/to/era5_hourly_event_grid.parquet \
  --output /path/to/observations_final_v1

python scripts/run_abu_dhabi_gwm_confirmatory_physics_batch.py \
  --observation-root /path/to/observations_final_v1 \
  --output /path/to/physics_final_v1 \
  --minimum-events 2 \
  --confirmatory-target-events 5 \
  --batch-schema gwm.abu_dhabi_flood.supplementary_physics_batch.v1 \
  --selection-rule "pixel-qualified supplementary events frozen before model outputs"

python scripts/evaluate_abu_dhabi_gwm_supplementary_external_validation.py \
  --cohort /path/to/frozen_supplementary_final_cohort_v1.json \
  --observation-root /path/to/observations_final_v1 \
  --physics-root /path/to/physics_final_v1 \
  --output /path/to/evaluation_final_v1
```

The 2026-09-18 run completed both admitted events and passed both physics
quality gates, but the frozen five-event target was not reached. Its correct
status is `completed_exploratory_supplementary_underpowered`. Raw-depth overlap
with the source-specific satellite masks is weak, so the result is diagnostic
and must not be presented as confirmatory validation.

## Verification

Run the focused backend suite, the frontend localization suite, and a
production build before delivery. In English mode, verify the Phase 4 action
reads `Run rule-based scenario screening`, the Phase 5 report opens in English,
and no `model metadata` placeholder remains.
