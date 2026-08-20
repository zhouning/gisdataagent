# Abu Dhabi Stormwater World Model Repository Handoff

## Scope

This handoff freezes the implementation that can proceed while the project is
waiting for customer-authoritative data. It covers the traditional-model
contracts, GWM boundary, data-request register, readiness checks, customer
delivery documents, and synthetic/diagnostic test adapters.

## Public repository boundary

The public GitHub branch contains code and small, non-authoritative metadata
only. It does not contain:

- customer database rows or database credentials;
- internal database hosts, connection strings, or local dictionary paths;
- engineering DTM/LiDAR, private drainage assets, SCADA logs, or inundation
  observations;
- bulk public/test raster, vector, Parquet, GeoPackage, SWMM, or ANUGA output.

The local dataset is intentionally excluded because it is large and because
public/test data must not be confused with customer-authoritative production
inputs.

## Current model boundary

EPA SWMM 5.2.4, ANUGA 2D, and LISFLOOD-FP remain traditional-model candidates
for physical constraints, calibration, validation, and fallback. GWM remains
an architecture and shadow-state layer for fast scenario rollout, uncertainty
and distribution-shift detection, and planner candidate screening. GWM does
not replace the physical authority before blind validation and governance
approval.

At this handoff, `k0_opened`, traditional-model admission, GWM training,
hybrid-planner admission, and city-scale prediction claims remain disabled.

## Resumption procedure

When the customer provides data, create a separate controlled data-ingestion
change. Register each file or database snapshot, verify source/version/time,
CRS and vertical datum, units, quality flags, licensing, topology/crosswalks,
and SHA-256, then update the K0 receipt. Do not place customer data in this
public repository.
