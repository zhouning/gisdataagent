# Abu Dhabi SWMM–ANUGA coupling and grid profiles

## Current executable path

The current citywide result is a one-way offline coupling:

1. EPA SWMM runs the customer full-city network.
2. Node overflow_or_flooding_m3s is read from the native SWMM OUT.
3. SWMM node coordinates are mapped to the ANUGA grid.
4. The mapped overflow is injected into ANUGA as a surface source.
5. The 2D result is written as maximum-depth GeoJSON and an 11-frame timeline.

The 2D rainfall is reduced by the mapped SWMM subcatchment area fraction so
the same rainfall is not counted once in SWMM and again in ANUGA.

This is not yet a synchronous two-way solve: a completed native OUT file cannot
receive ANUGA feedback. The repository now contains the native SWMM dynamic
session adapter (swmm_dynamic_toolkit.py) and a signed head-difference
exchange kernel (compute_head_difference_exchange_rate) for the next stage.
That stage will advance SWMM and ANUGA in shared windows, calculate the
SWMM-node/ANUGA-cell head difference, and write the signed exchange flow back
through swmm_setValue(NODE_LATFLOW).

## Grid profiles

The runner accepts --cell-size-m from 25 m to 1000 m when the size tiles the
current city bounds.

| Profile | Cell size | Rectangular cells | Triangles | Use |
| --- | ---: | ---: | ---: | --- |
| Fast citywide | 250 m | 27,360 | 109,440 | interactive overview |
| Current fine citywide | 100 m | 171,000 | 684,000 | customer demonstration |
| Priority area | 50 m | 684,000 | 2,736,000 | selected districts |
| Microtopography | 5–10 m | local only | local only | roads, curbs, inlets |

## Current 100 m run

- Surface: customer AUH_DTM_5m_Z40, resampled from 5 m to 100 m.
- Network forcing: existing full-city SWMM native OUT, 100-year / 180-minute
  Zone B DDF scenario.
- Spatial mask: ESA WorldCover 2021 public land/water proxy; permanent-water
  cells are excluded from rainfall and published flood layers.
- Simulation: 300 minutes, 30-minute output interval, 11 frames.
- Maximum depth: 4.20 m.
- Area at depth >= 0.01 m: 773.0 km².
- Area at depth >= 0.05 m: 442.57 km².
- SWMM overflow volume injected into ANUGA: 3,071,496 m³ (runtime receipt).

Result directory:

/Users/zhouning/Downloads/阿布扎比/二维水动力诊断_客户DTM_z40_全市_SWMM二维单向耦合_100m_20260909

The page service now prefers this 100 m result when it exists and reports the
actual grid size from delivery_summary.json; it falls back to the 250 m result
only when the 100 m directory is absent.
