# Professional Tool MCP Servers

Three MCP (Model Context Protocol) servers that bridge professional GIS/3D tools with the Data Agent platform.

## Servers

### arcgis-mcp
ArcGIS Pro tools via subprocess. Calls the real arcpy Python environment at `ARCPY_PYTHON_EXE`.
- `arcgis_topology_check` — Topology validation
- `arcgis_spatial_join` — Spatial join
- `arcgis_buffer_analysis` — Buffer analysis
- `arcgis_export_map` — Map layout export to PDF

### qgis-mcp
QGIS processing tools.
- `qgis_validate_geometry` — Geometry validation
- `qgis_topology_checker` — Topology rule checking
- `qgis_raster_calculator` — Raster calculator
- `qgis_export_layout` — Print layout export

### blender-mcp
Blender 3D operations.
- `blender_import_model` — Import 3D models
- `blender_check_mesh` — Mesh quality check
- `blender_render_preview` — Render preview image
- `blender_export_screenshot` — Viewport screenshot

## Usage

Each server runs independently:

```bash
cd arcgis-mcp && pip install -r requirements.txt && python server.py
cd qgis-mcp && pip install -r requirements.txt && python server.py
cd blender-mcp && pip install -r requirements.txt && python server.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARCPY_PYTHON_EXE` | `D:/Users/zn198/.../python.exe` | Path to ArcGIS Pro conda Python |
