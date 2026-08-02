# Abu Dhabi Land-Use Benchmark V1

This directory is the single execution boundary for comparing GeoSOS-FLUS,
the GWM Geospatial Kernel and Paper58 on Abu Dhabi city land-cover simulation
and constrained planning optimization.

The comparison is valid only when every candidate consumes the same canonical
grid, origin state, action, hard constraints and driver versions, and writes a
prediction accepted by `contract.validate_prediction`.

## Frozen scope

- Boundary: OpenStreetMap relation `R4479763` (Abu Dhabi city).
- Grid: `EPSG:32640`, 100 m, aligned to the 100 m UTM lattice.
- Observations: annual 2017-2024 states.
- Historical fit: transitions ending no later than 2021.
- Validation: 2021 to 2022.
- Test: open-loop rollout from 2022 to 2023 and 2024.
- Scenario origin: 2024; conditional annual rollout through 2030.
- Semantics: six-class land cover, not cadastral residential/commercial use.

`protocol.json` is authoritative. It separates oracle-demand allocation skill,
end-to-end rollout and planning optimization so that demand error cannot be
mistaken for spatial allocation error.

## Materialize the boundary and grid

```bash
python benchmarks/abu_dhabi_land_use_v1/fetch_boundary.py \
  --proxy http://127.0.0.1:7897
python benchmarks/abu_dhabi_land_use_v1/prepare_grid.py
```

The generated `boundary_manifest.json` and `grid_profile.json` retain source
and artifact hashes. Large raster artifacts remain local; their hashes and
lineage records are the reproducibility interface.

## Execute the three candidates

Historical conditional allocation:

```bash
python benchmarks/abu_dhabi_land_use_v1/run_geosos_flus.py
python benchmarks/abu_dhabi_land_use_v1/run_geospatial_kernel.py
python ../paper58-geofm-world-model-rl/experiments/abu_dhabi/run_paper58_abu_dhabi.py
python benchmarks/abu_dhabi_land_use_v1/compile_comparison.py
```

Conditional 2025-2030 scenarios and multi-objective planning comparison:

```bash
python benchmarks/abu_dhabi_land_use_v1/run_planning_scenarios.py
python benchmarks/abu_dhabi_land_use_v1/compile_planning.py
python benchmarks/abu_dhabi_land_use_v1/audit_outputs.py
```

`run_planning_scenarios.py` invokes the real external FLUS console, trains the
explicit Geospatial Kernel and loads Paper58 LDN checkpoints. All candidates
start from the observed 2024 state and receive the same annual demand and hard
constraints. Future exogenous raster drivers are held at their known 2024
values; Paper58 recursively writes back its predicted latent state.

## Current result

- Historical test: Geospatial Kernel has the best 2023 one-step change FoM;
  Paper58 has the best 2024 two-step open-loop change FoM.
- Planning test: all three Geospatial Kernel scenario allocations are on the
  frozen 2030 Pareto frontier. Paper58 and GeoSOS-FLUS are dominated on the
  current public-data proxy objectives.
- FLUS retires roughly 2,900-3,650 existing built pixels while reallocating
  more built pixels elsewhere; the two proposed models show no built retirement
  under the same frozen scenario demands.
- Every one of the 240 published seed and ensemble rasters passes grid, class,
  nodata and hard-constraint checks in `output_audit.json`.

These findings are conditional on Dynamic World labels, public OSM proxy
constraints and planner-supplied scenario demand. They do not predict actual
Abu Dhabi policy or establish causal planning effects. Required negative
controls in `protocol.json` remain pending.
