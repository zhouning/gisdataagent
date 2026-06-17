#!/usr/bin/env python3
"""Build preview artifacts for the TWM Bishan demo dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

try:
    import rasterio
except ImportError:  # pragma: no cover - preview can still render vector layers.
    rasterio = None


DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
PREVIEW_DIR = DATA_DIR / "preview"
PROJECT_CRS = "EPSG:32648"


LAYERS = {
    "parcel_current": "parcel_current.geojson",
    "synthetic_pbf": "synthetic_pbf.geojson",
    "synthetic_eco_redline": "synthetic_eco_redline.geojson",
    "admin_units": "admin_units.geojson",
    "synthetic_annual_change": "synthetic_annual_change.geojson",
    "synthetic_projects": "synthetic_projects.geojson",
    "synthetic_planning_zones": "synthetic_planning_zones.geojson",
    "synthetic_urban_boundary": "synthetic_urban_boundary.geojson",
    "synthetic_remote_sensing_tiles": "synthetic_remote_sensing_tiles.geojson",
}


def _configure_cjk_font() -> None:
    candidates = [
        "PingFang SC",
        "Heiti SC",
        "Songti SC",
        "Arial Unicode MS",
        "Noto Sans CJK SC",
    ]
    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in available:
            plt.rcParams["font.sans-serif"] = [candidate, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return


def _load_layers() -> dict[str, gpd.GeoDataFrame]:
    out = {}
    for role, filename in LAYERS.items():
        path = DATA_DIR / filename
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise ValueError(f"{path} has no CRS")
        out[role] = gdf
    return out


def _load_dictionary() -> dict:
    path = DATA_DIR / "data_dictionary.zh.json"
    if not path.exists():
        return {"layers": {}, "fields": {}, "roles": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_quality_report() -> dict:
    path = DATA_DIR / "data_quality_report.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_relation_summary() -> list[dict]:
    relation_dir = DATA_DIR / "relations"
    if not relation_dir.exists():
        return []
    rows = []
    for path in sorted(relation_dir.glob("*.csv")):
        df = pd.read_csv(path)
        rows.append(
            {
                "relation": path.stem,
                "rows": len(df),
                "unique_projects": int(df["project_id"].nunique()) if "project_id" in df.columns and len(df) else 0,
                "columns": ", ".join(df.columns[:8]),
            }
        )
    return rows


def _load_table_summary() -> list[dict]:
    tables_dir = DATA_DIR / "tables"
    if not tables_dir.exists():
        return []
    rows = []
    for path in sorted(tables_dir.glob("*.csv")):
        df = pd.read_csv(path)
        rows.append(
            {
                "table": path.stem,
                "rows": len(df),
                "unique_projects": int(df["project_id"].nunique()) if "project_id" in df.columns and len(df) else 0,
                "columns": ", ".join(df.columns[:8]),
            }
        )
    return rows


def _load_manifest() -> dict:
    path = DATA_DIR / "dataset_manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_raster_summary() -> list[dict]:
    path = DATA_DIR / "raster_manifest.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for name, product in payload.get("products", {}).items():
        stats = product.get("stats", {})
        rows.append(
            {
                "raster": name,
                "中文名": product.get("alias_zh", ""),
                "path": product.get("relative_path", product.get("path", "")),
                "size": f"{product.get('width', 0)}x{product.get('height', 0)}",
                "crs": product.get("crs", ""),
                "valid_pixels": stats.get("valid_pixels", 0),
                "mean": stats.get("mean", ""),
                "synthetic": product.get("synthetic", ""),
            }
        )
    return rows


def _load_real_imagery_summary() -> list[dict]:
    path = DATA_DIR / "real_imagery_manifest.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    stac = payload.get("stac", {})
    for name, product in payload.get("products", {}).items():
        rows.append(
            {
                "product": name,
                "path": product.get("relative_path", product.get("path", "")),
                "type": product.get("type", ""),
                "selected_date": stac.get("selected_date", ""),
                "avg_cloud_cover": stac.get("avg_cloud_cover", ""),
                "synthetic": payload.get("synthetic", ""),
            }
        )
    return rows


def _layer_summary(gdf: gpd.GeoDataFrame) -> dict:
    projected = gdf.to_crs(PROJECT_CRS)
    bounds_projected = projected.total_bounds if len(projected) else None
    sum_area = float(projected.geometry.area.sum()) if len(projected) else 0.0
    bbox_area = 0.0
    if bounds_projected is not None:
        bbox_area = float(
            (bounds_projected[2] - bounds_projected[0])
            * (bounds_projected[3] - bounds_projected[1])
        )
    return {
        "rows": len(gdf),
        "crs": str(gdf.crs),
        "geometry_types": sorted(map(str, gdf.geom_type.dropna().unique().tolist())),
        "columns": [c for c in gdf.columns if c != "geometry"],
        "bounds": [round(float(x), 6) for x in gdf.total_bounds] if len(gdf) else None,
        "area_m2": round(sum_area, 2),
        "bbox_area_m2": round(bbox_area, 2),
        "bbox_coverage_ratio": round(sum_area / bbox_area, 4) if bbox_area else 0.0,
        "synthetic": (
            gdf["synthetic"].astype(str).value_counts().to_dict()
            if "synthetic" in gdf.columns
            else {}
        ),
        "not_for_production": (
            gdf["not_for_production"].astype(str).value_counts().to_dict()
            if "not_for_production" in gdf.columns
            else {}
        ),
        "qa_use_for_rules": (
            gdf["qa_use_for_rules"].astype(str).value_counts().to_dict()
            if "qa_use_for_rules" in gdf.columns
            else {}
        ),
    }


def _intersections(layers: dict[str, gpd.GeoDataFrame]) -> dict:
    projects = layers["synthetic_projects"].to_crs(PROJECT_CRS)
    pbf = layers["synthetic_pbf"].to_crs(PROJECT_CRS)
    eco = layers["synthetic_eco_redline"].to_crs(PROJECT_CRS)
    changes = layers["synthetic_annual_change"].to_crs(PROJECT_CRS)
    planning = layers["synthetic_planning_zones"].to_crs(PROJECT_CRS)
    rs_tiles = layers["synthetic_remote_sensing_tiles"].to_crs(PROJECT_CRS)

    project_pbf = gpd.sjoin(
        projects[["project_id", "geometry"]],
        pbf[["control_id", "geometry"]],
        predicate="intersects",
        how="inner",
    )
    project_eco = gpd.sjoin(
        projects[["project_id", "geometry"]],
        eco[["redline_id", "geometry"]],
        predicate="intersects",
        how="inner",
    )
    change_pbf = gpd.sjoin(
        changes[["change_id", "geometry"]],
        pbf[["control_id", "geometry"]],
        predicate="intersects",
        how="inner",
    )
    project_planning = gpd.sjoin(
        projects[["project_id", "geometry"]],
        planning[["plan_zone_id", "geometry"]],
        predicate="intersects",
        how="inner",
    )
    project_rs = gpd.sjoin(
        projects[["project_id", "geometry"]],
        rs_tiles[["tile_id", "geometry"]],
        predicate="intersects",
        how="inner",
    )

    return {
        "project_pbf_intersections": len(project_pbf),
        "project_pbf_unique_projects": int(project_pbf["project_id"].nunique()) if len(project_pbf) else 0,
        "project_eco_intersections": len(project_eco),
        "project_eco_unique_projects": int(project_eco["project_id"].nunique()) if len(project_eco) else 0,
        "annual_change_pbf_intersections": len(change_pbf),
        "annual_change_pbf_unique_changes": int(change_pbf["change_id"].nunique()) if len(change_pbf) else 0,
        "project_planning_intersections": len(project_planning),
        "project_planning_unique_projects": int(project_planning["project_id"].nunique()) if len(project_planning) else 0,
        "project_rs_tile_intersections": len(project_rs),
        "project_rs_tile_unique_projects": int(project_rs["project_id"].nunique()) if len(project_rs) else 0,
        "project_pbf_sample": project_pbf[["project_id", "control_id"]].head(20).to_dict("records"),
        "project_eco_sample": project_eco[["project_id", "redline_id"]].head(20).to_dict("records"),
        "project_planning_sample": project_planning[["project_id", "plan_zone_id"]].head(20).to_dict("records"),
    }


def _connected_components(gdf: gpd.GeoDataFrame) -> dict:
    projected = gdf.to_crs(PROJECT_CRS).reset_index(drop=True)
    if projected.empty:
        return {"connected_components": 0, "largest_component_features": 0, "largest_component_ratio": 0.0}
    parents = list(range(len(projected)))

    def find(x: int) -> int:
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parents[rb] = ra

    sidx = projected.sindex
    for i, geom in enumerate(projected.geometry):
        for j in sidx.query(geom, predicate="intersects"):
            if j > i:
                union(i, int(j))

    counts: dict[int, int] = {}
    for i in range(len(projected)):
        root = find(i)
        counts[root] = counts.get(root, 0) + 1
    largest = max(counts.values()) if counts else 0
    return {
        "connected_components": len(counts),
        "largest_component_features": int(largest),
        "largest_component_ratio": round(largest / len(projected), 4) if len(projected) else 0.0,
    }


def _write_geopackage(layers: dict[str, gpd.GeoDataFrame]) -> Path:
    dataset_id = _load_manifest().get("dataset_id", DATA_DIR.name)
    gpkg = PREVIEW_DIR / f"{dataset_id}_layers.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    for role, gdf in layers.items():
        gdf.to_file(gpkg, layer=role, driver="GPKG")
    return gpkg


def _plot_overview(layers: dict[str, gpd.GeoDataFrame]) -> Path:
    fig, ax = plt.subplots(figsize=(10, 10))
    layers["parcel_current"].to_crs(PROJECT_CRS).plot(
        ax=ax, color="#e8e8e8", edgecolor="#cfcfcf", linewidth=0.08
    )
    layers["admin_units"].to_crs(PROJECT_CRS).boundary.plot(
        ax=ax, color="#555555", linewidth=0.7
    )
    layers["synthetic_pbf"].to_crs(PROJECT_CRS).plot(
        ax=ax, color="#2ca25f", alpha=0.5, edgecolor="#006d2c", linewidth=0.2
    )
    layers["synthetic_eco_redline"].to_crs(PROJECT_CRS).plot(
        ax=ax, color="#dd1c77", alpha=0.45, edgecolor="#980043", linewidth=0.2
    )
    layers["synthetic_projects"].to_crs(PROJECT_CRS).plot(
        ax=ax, facecolor="none", edgecolor="#f16913", linewidth=1.0
    )
    layers["synthetic_urban_boundary"].to_crs(PROJECT_CRS).boundary.plot(
        ax=ax, color="#54278f", linewidth=1.1
    )
    ax.set_title("TWM Bishan Demo - Parcels, Control Zones, Urban Boundary, Projects")
    ax.set_axis_off()
    out = PREVIEW_DIR / "overview_layers.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def _plot_changes(layers: dict[str, gpd.GeoDataFrame]) -> Path:
    changes = layers["synthetic_annual_change"].to_crs(PROJECT_CRS)
    pbf = layers["synthetic_pbf"].to_crs(PROJECT_CRS)
    fig, ax = plt.subplots(figsize=(10, 10))
    layers["parcel_current"].to_crs(PROJECT_CRS).plot(
        ax=ax, color="#f2f2f2", edgecolor="#dddddd", linewidth=0.05
    )
    pbf.plot(ax=ax, color="#74c476", alpha=0.35, edgecolor="none")
    changes.plot(
        ax=ax,
        column="change_type",
        categorical=True,
        legend=True,
        cmap="Set1",
        markersize=2,
        edgecolor="#333333",
        linewidth=0.2,
    )
    ax.set_title("TWM Bishan Demo - Synthetic Annual Changes over PBF")
    ax.set_axis_off()
    out = PREVIEW_DIR / "annual_change_over_pbf.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def _plot_layer_grid(layers: dict[str, gpd.GeoDataFrame]) -> Path:
    order = [
        "parcel_current",
        "synthetic_pbf",
        "synthetic_eco_redline",
        "admin_units",
        "synthetic_annual_change",
        "synthetic_projects",
        "synthetic_planning_zones",
        "synthetic_urban_boundary",
        "synthetic_remote_sensing_tiles",
    ]
    colors = {
        "parcel_current": "#c7c7c7",
        "synthetic_pbf": "#2ca25f",
        "synthetic_eco_redline": "#dd1c77",
        "admin_units": "#756bb1",
        "synthetic_annual_change": "#fb6a4a",
        "synthetic_projects": "#f16913",
        "synthetic_planning_zones": "#9ecae1",
        "synthetic_urban_boundary": "#54278f",
        "synthetic_remote_sensing_tiles": "#08519c",
    }
    fig, axes = plt.subplots(3, 3, figsize=(15, 14))
    for ax, role in zip(axes.flat, order):
        gdf = layers[role].to_crs(PROJECT_CRS)
        if role in {"admin_units", "synthetic_urban_boundary", "synthetic_remote_sensing_tiles"}:
            gdf.boundary.plot(ax=ax, color=colors[role], linewidth=0.8)
        elif role == "synthetic_projects":
            gdf.plot(ax=ax, facecolor="none", edgecolor=colors[role], linewidth=0.9)
        else:
            gdf.plot(ax=ax, color=colors[role], alpha=0.65, edgecolor="#555555", linewidth=0.1)
        ax.set_title(f"{role} ({len(gdf)})")
        ax.set_axis_off()
    out = PREVIEW_DIR / "layer_grid.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def _plot_planning_multimodal(layers: dict[str, gpd.GeoDataFrame]) -> Path:
    fig, ax = plt.subplots(figsize=(10, 10))
    layers["synthetic_planning_zones"].to_crs(PROJECT_CRS).plot(
        ax=ax,
        column="plan_zone_type",
        categorical=True,
        legend=True,
        alpha=0.45,
        edgecolor="#666666",
        linewidth=0.2,
    )
    layers["synthetic_remote_sensing_tiles"].to_crs(PROJECT_CRS).boundary.plot(
        ax=ax, color="#08519c", linewidth=0.8, linestyle="--"
    )
    layers["synthetic_projects"].to_crs(PROJECT_CRS).plot(
        ax=ax, facecolor="none", edgecolor="#f16913", linewidth=1.0
    )
    ax.set_title("TWM Bishan Demo - Planning Zones, RS Tiles, Projects")
    ax.set_axis_off()
    out = PREVIEW_DIR / "planning_multimodal_context.png"
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def _plot_real_imagery_thumbnails() -> list[Path]:
    if rasterio is None:
        return []
    manifest_path = DATA_DIR / "real_imagery_manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    products = manifest.get("products", {})
    outputs: list[Path] = []

    rgb_info = products.get("sentinel2_l2a_rgb", {})
    rgb_path = DATA_DIR / rgb_info.get("relative_path", rgb_info.get("path", ""))
    if not rgb_path.exists() and rgb_info.get("path"):
        rgb_path = Path(rgb_info["path"])
    if rgb_path.exists():
        with rasterio.open(rgb_path) as src:
            if src.count >= 3:
                rgb = src.read([1, 2, 3], masked=True)
                image = np.moveaxis(np.ma.filled(rgb, 0), 0, -1).astype("uint8")
                fig, ax = plt.subplots(figsize=(9, 9))
                ax.imshow(image)
                ax.set_title("Real Sentinel-2 RGB")
                ax.set_axis_off()
                out = PREVIEW_DIR / "real_sentinel2_rgb.png"
                fig.tight_layout()
                fig.savefig(out, dpi=180)
                plt.close(fig)
                outputs.append(out)

    ndvi_info = products.get("sentinel2_l2a_ndvi", {})
    ndvi_path = DATA_DIR / ndvi_info.get("relative_path", ndvi_info.get("path", ""))
    if not ndvi_path.exists() and ndvi_info.get("path"):
        ndvi_path = Path(ndvi_info["path"])
    if ndvi_path.exists():
        with rasterio.open(ndvi_path) as src:
            ndvi = src.read(1, masked=True)
            fig, ax = plt.subplots(figsize=(9, 9))
            im = ax.imshow(ndvi, cmap="RdYlGn", vmin=-1.0, vmax=1.0)
            fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
            ax.set_title("Real Sentinel-2 NDVI")
            ax.set_axis_off()
            out = PREVIEW_DIR / "real_sentinel2_ndvi.png"
            fig.tight_layout()
            fig.savefig(out, dpi=180)
            plt.close(fig)
            outputs.append(out)
    return outputs


def _html_table(rows: list[dict]) -> str:
    if not rows:
        return "<p>No rows.</p>"
    keys = list(rows[0].keys())
    head = "".join(f"<th>{k}</th>" for k in keys)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{row.get(k, '')}</td>" for k in keys) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _field_tables(summaries: dict[str, dict], dictionary: dict) -> str:
    layers_meta = dictionary.get("layers", {})
    fields_meta = dictionary.get("fields", {})
    sections = []
    for role, summary in summaries.items():
        layer_alias = layers_meta.get(role, {}).get("alias_zh", role)
        rows = []
        for field in summary["columns"]:
            meta = fields_meta.get(field, {})
            rows.append({
                "field": field,
                "中文别名": meta.get("alias_zh", field),
                "说明": meta.get("description_zh", ""),
            })
        sections.append(f"<h3>{role} / {layer_alias}</h3>{_html_table(rows)}")
    return "\n".join(sections)


def _write_report(
    summaries: dict[str, dict],
    intersections: dict,
    gpkg: Path,
    images: list[Path],
    dictionary: dict,
    manifest: dict,
    quality_report: dict,
    relation_rows: list[dict],
    table_rows: list[dict],
    raster_rows: list[dict],
    real_imagery_rows: list[dict],
) -> Path:
    layers_meta = dictionary.get("layers", {})
    layer_rows = [
        {
            "role": role,
            "中文名": layers_meta.get(role, {}).get("alias_zh", role),
            "业务角色": layers_meta.get(role, {}).get("business_role_zh", ""),
            "rows": summary["rows"],
            "crs": summary["crs"],
            "geometry": ", ".join(summary["geometry_types"]),
            "synthetic": json.dumps(summary["synthetic"], ensure_ascii=False),
            "not_for_production": json.dumps(summary["not_for_production"], ensure_ascii=False),
            "qa_use_for_rules": json.dumps(summary["qa_use_for_rules"], ensure_ascii=False),
            "说明": layers_meta.get(role, {}).get("description_zh", ""),
        }
        for role, summary in summaries.items()
    ]
    gate = quality_report.get("quality_gate", {})
    gate_rows = [
        {"item": "status", "value": gate.get("status", "not_run")},
        {"item": "blockers", "value": len(gate.get("blockers", []))},
        {"item": "warnings", "value": len(gate.get("warnings", []))},
    ]
    warning_rows = [{"warning": item} for item in gate.get("warnings", [])]
    overlay_rows = [
        {"overlay": k, **v}
        for k, v in quality_report.get("overlays", {}).items()
    ]
    metric_rows = [
        {"metric": k, "value": v}
        for k, v in intersections.items()
        if not k.endswith("_sample")
    ]
    continuity = _connected_components(gpd.read_file(DATA_DIR / "parcel_current.geojson"))
    continuity_rows = [
        {"metric": "parcel_bbox_coverage_ratio", "value": summaries["parcel_current"]["bbox_coverage_ratio"]},
        {"metric": "parcel_connected_components", "value": continuity["connected_components"]},
        {"metric": "parcel_largest_component_features", "value": continuity["largest_component_features"]},
        {"metric": "parcel_largest_component_ratio", "value": continuity["largest_component_ratio"]},
    ]
    title = manifest.get("dataset_alias_zh") or manifest.get("dataset_id") or "TWM Demo Data Preview"
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; color: #222; }}
    h1, h2 {{ margin: 0 0 12px; }}
    section {{ margin: 28px 0; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #ddd; padding: 7px 8px; vertical-align: top; }}
    th {{ background: #f4f4f4; text-align: left; }}
    img {{ max-width: 100%; border: 1px solid #ddd; margin: 8px 0 18px; }}
    code {{ background: #f5f5f5; padding: 2px 4px; }}
    .warning {{ background: #fff5e6; border: 1px solid #ffd28a; padding: 12px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="warning">这些数据用于工程测试和演示。合成图层均带有 <code>synthetic=true</code> 和 <code>not_for_production=true</code>，不能用于生产级自然资源治理结论。</p>

  <section>
    <h2>How to Inspect</h2>
    <p>QGIS/ArcGIS: open <code>{gpkg}</code> to inspect all layers together.</p>
    <p>Manifest: open <code>{DATA_DIR / "dataset_manifest.json"}</code>.</p>
    <p>QA: open <code>{DATA_DIR / "data_quality_report.md"}</code>.</p>
  </section>

  <section>
    <h2>QA Gate</h2>
    {_html_table(gate_rows)}
    {_html_table(warning_rows)}
  </section>

  <section>
    <h2>Layer Summary</h2>
    {_html_table(layer_rows)}
  </section>

  <section>
    <h2>Field Dictionary</h2>
    {_field_tables(summaries, dictionary)}
  </section>

  <section>
    <h2>Rule-Hit Potential</h2>
    {_html_table(metric_rows)}
  </section>

  <section>
    <h2>Overlay QA</h2>
    {_html_table(overlay_rows)}
  </section>

  <section>
    <h2>Relation Tables</h2>
    {_html_table(relation_rows)}
  </section>

  <section>
    <h2>Governance Tables</h2>
    {_html_table(table_rows)}
  </section>

  <section>
    <h2>Raster Fixtures</h2>
    {_html_table(raster_rows)}
  </section>

  <section>
    <h2>Real Imagery</h2>
    {_html_table(real_imagery_rows)}
  </section>

  <section>
    <h2>Spatial Continuity</h2>
    {_html_table(continuity_rows)}
  </section>

  <section>
    <h2>Images</h2>
    {''.join(f'<h3>{img.name}</h3><img src="{img.name}" />' for img in images)}
  </section>

  <section>
    <h2>Sample Project/PBF Hits</h2>
    {_html_table(intersections.get("project_pbf_sample", []))}
  </section>

  <section>
    <h2>Sample Project/Eco-Redline Hits</h2>
    {_html_table(intersections.get("project_eco_sample", []))}
  </section>

  <section>
    <h2>Sample Project/Planning Hits</h2>
    {_html_table(intersections.get("project_planning_sample", []))}
  </section>
</body>
</html>
"""
    out = PREVIEW_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--project-crs", default=PROJECT_CRS)
    return parser.parse_args()


def main() -> None:
    global DATA_DIR, PREVIEW_DIR, PROJECT_CRS
    args = parse_args()
    _configure_cjk_font()
    DATA_DIR = Path(args.data_dir)
    PREVIEW_DIR = DATA_DIR / "preview"
    PROJECT_CRS = args.project_crs
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    layers = _load_layers()
    dictionary = _load_dictionary()
    manifest = _load_manifest()
    quality_report = _load_quality_report()
    relation_rows = _load_relation_summary()
    table_rows = _load_table_summary()
    raster_rows = _load_raster_summary()
    real_imagery_rows = _load_real_imagery_summary()
    summaries = {role: _layer_summary(gdf) for role, gdf in layers.items()}
    intersections = _intersections(layers)
    gpkg = _write_geopackage(layers)
    images = [
        _plot_layer_grid(layers),
        _plot_overview(layers),
        _plot_changes(layers),
        _plot_planning_multimodal(layers),
    ]
    images.extend(_plot_real_imagery_thumbnails())
    report = _write_report(
        summaries,
        intersections,
        gpkg,
        images,
        dictionary,
        manifest,
        quality_report,
        relation_rows,
        table_rows,
        raster_rows,
        real_imagery_rows,
    )
    print(json.dumps({
        "report": str(report),
        "geopackage": str(gpkg),
        "images": [str(p) for p in images],
        "intersections": {
            k: v for k, v in intersections.items() if not k.endswith("_sample")
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
