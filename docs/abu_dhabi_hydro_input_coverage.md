# Abu Dhabi hydro workbench input coverage

The workbench now distinguishes inputs required to execute the current bounded diagnostic from inputs required before an engineering-admitted 1D/2D model can be claimed.

## Source catalog

| Source key | What it controls | Current admission |
| --- | --- | --- |
| `network` | SWMM nodes, links, cross-sections, storage and hydraulic structures | Runtime hard gate |
| `terrain` | DTM/DSM elevation and 2D surface geometry | Runtime hard gate |
| `rainfall` | Event hyetograph or spatial rainfall field | Runtime forcing; customer/design rainfall is required for engineering admission; April 2024 reconstruction is a diagnostic proxy |
| `catchments` | Authoritative runoff polygons, outlet nodes and subcatchment attributes | Engineering-required; not a solver-domain substitute |
| `land_sea_boundary` | Coastline/land-sea mask, sea-facing segments and boundary tags | Engineering-required for coastal 2D/coupled runs |
| `tide` | Time-dependent sea or downstream stage | Engineering-required where an open/coastal boundary exists |
| `outfalls` | Outfall geometry, downstream mapping and gate/backflow state | Engineering-required for boundary interpretation |
| `pumps` | Pump curves, controls and SCADA state | Engineering-required when pumps affect the event |
| `hydraulic_structures` | Gates, weirs, orifices, culverts, storage and operating rules | Engineering-required when present in the network |
| `external_inflows` | Upstream/channel/transfer hydrographs entering the modeled system | Conditional |
| `surface_cover` | Imperviousness, depression storage and Manning roughness zones | Engineering-required for runoff/surface routing |
| `surface_features` | Buildings, roads, kerbs, walls, levees, culverts and flow paths | Engineering-required for urban 2D routing |
| `inlet_coupling` | Inlet capture capacity and 1D node-to-2D grid exchange mapping | Engineering-required for true 1D–2D exchange |
| `soil_infiltration` | Soil classes and Horton/Green-Ampt/CN parameters | Engineering-required for infiltration-sensitive runs |
| `groundwater` | Groundwater level and infiltration/inflow leakage parameters | Conditional |
| `network_condition` | Blockage, sediment, closed links and event-time asset state | Engineering-required for actual operating capacity |
| `initial_state` | Event-start levels, flows, surface depth, moisture and controls | Engineering-required for hot start/initial-condition fidelity |
| `observations` | Water level, flow, inundation depth/extent and recession observations | Engineering-required for calibration and validation |
| `coastal_bathymetry` | Nearshore/port bathymetry when the 2D domain includes water cells | Conditional |

## Important interpretation

The current diagnostic pilot remains executable with `network` and `terrain` plus the registered April 2024 or numeric rainfall proxy because it uses explicit diagnostic defaults. This is a capability boundary, not evidence that the missing sources are unnecessary. The preflight now lists engineering gaps separately and keeps the result marked diagnostic-only.

The coastline geometry and tide series are separate inputs:

1. `land_sea_boundary` says where the sea-facing boundary is and how mesh edges are tagged.
2. `tide` says what water level is imposed on that boundary over time.
3. `outfalls` maps drainage nodes to downstream or coastal boundary conditions.

DTM elevation alone does not provide land/sea semantics, boundary tags or tide-station mapping. If the calculation domain enters tidal flats, ports or open water, `coastal_bathymetry` is also needed and must share horizontal and vertical datum conventions with the terrain data.

Every spatial or time-series source also carries common metadata requirements: CRS, horizontal and vertical datum, units, timezone, validity period, version, source lineage and QA/QC status. A URI without those declarations is not sufficient for engineering admission.

## Items reviewed but intentionally not split into extra source cards

- Open channels, wadis, canals, bridges and storage ponds are represented by the `network` and `hydraulic_structures` contracts when they participate in the 1D system; their cross-sections, bank/crest levels and control rules must still be supplied.
- Dry-weather/baseflow, lateral inflow and sewer infiltration/inflow are represented by `external_inflows`, `groundwater` and `initial_state` according to the scenario.
- Evaporation/interception and wave-resolved wind forcing are not active inputs for the current short-duration pluvial diagnostic. They become conditional inputs for long continuous simulations or a wave-resolving coastal model; a measured or design total-water-level series remains the accepted boundary forcing for the current workbench.
- The normalized SWMM model, conditioned terrain, 2D mesh, boundary-condition table and node-to-grid exchange table are ETL-derived model-native artifacts. They are not additional raw customer datasets, but preflight must verify that they exist before an engineering run is admitted.

## Runtime boundary

The current ANUGA adapter still uses a bounded diagnostic surface configuration. Registering a new source in the UI does not silently claim that the solver has consumed it; the source remains blocked by ETL/runtime-adapter status until the corresponding model-native transformation is enabled.
