from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

import numpy as np
import pandas as pd


COUNTY_SHAPEFILE_FIELD_MAP = {
    "AveAgeDeat": "AveAgeDeath",
    "SocialAsso": "SocialAssoc",
    "UnemployRa": "UnemployRate",
    "pHHinPover": "pHHinPoverty",
    "pNoHealthI": "pNoHealthInsur",
    "MentalHeal": "MentalHealth",
    "pAdultSmok": "pAdultSmoking",
    "pAdultObes": "pAdultObesity",
    "pInsuffici": "pInsufficientSleep",
    "pSuicideDe": "pSuicideDeaths",
    "AirPolluti": "AirPollution",
    "Shape_Leng": "Shape_Length",
}

COUNTY_ANALYSIS_COLUMNS = (
    "FIPS",
    "SocialAssoc",
    "AveAgeDeath",
    "STATE_NAME",
    "UnemployRate",
    "pHHinPoverty",
    "pNoHealthInsur",
    "MentalHealth",
    "pAdultSmoking",
    "pAdultObesity",
    "FastFood",
    "pInsufficientSleep",
    "pAlcohol",
    "pSuicideDeaths",
    "AirPollution",
    "Shape_Length",
    "Shape_Area",
    "_gc_x",
    "_gc_y",
)


def _require_geopandas() -> Any:
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise RuntimeError(
            "GeoPandas is required for spatial output generation. "
            "Install the Docker notebook environment or geospatial Python dependencies."
        ) from exc
    return gpd


def _safe_field_token(value: object, *, max_length: int | None = None) -> str:
    token = re.sub(r"[^0-9A-Za-z_]+", "_", str(value).strip()).strip("_")
    if not token:
        token = "field"
    if token[0].isdigit():
        token = f"f_{token}"
    if max_length is not None:
        token = token[:max_length].rstrip("_") or "field"
    return token


def normalize_join_key(series: pd.Series, *, width: int | None = None) -> pd.Series:
    values = series.astype("string").fillna("").str.strip()
    values = values.str.replace(r"\.0$", "", regex=True)
    if width is not None:
        values = values.str.zfill(width)
    return values


def _infer_key_width(*series_items: pd.Series) -> int | None:
    widths: list[int] = []
    for series in series_items:
        values = normalize_join_key(series)
        digit_values = values[values.str.fullmatch(r"\d+", na=False)]
        if not digit_values.empty:
            widths.append(int(digit_values.str.len().max()))
    return max(widths) if widths else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def prepare_county_analysis_table_from_shapefile(
    *,
    county_path: str | Path,
    output_csv: str | Path,
    field_map: dict[str, str] | None = None,
) -> Path:
    """Export CountyData.shp attributes to the full field names expected by SCCA."""
    gpd = _require_geopandas()
    county_path = Path(county_path)
    output_csv = Path(output_csv)
    counties = gpd.read_file(county_path)
    rename_map = field_map or COUNTY_SHAPEFILE_FIELD_MAP
    table = pd.DataFrame(counties.drop(columns=getattr(counties, "geometry").name))
    table = table.rename(columns={key: value for key, value in rename_map.items() if key in table.columns})

    geometry = counties.geometry
    representative_points = geometry.representative_point()
    table["_gc_x"] = representative_points.x
    table["_gc_y"] = representative_points.y

    missing = [column for column in COUNTY_ANALYSIS_COLUMNS if column not in table.columns]
    if missing:
        raise ValueError(
            "County shapefile is missing required analysis fields after normalization: "
            + ", ".join(missing)
        )

    table = table.loc[:, list(COUNTY_ANALYSIS_COLUMNS)].copy()
    table["FIPS"] = normalize_join_key(table["FIPS"], width=5)
    for column in COUNTY_ANALYSIS_COLUMNS:
        if column not in {"FIPS", "STATE_NAME"}:
            table[column] = pd.to_numeric(table[column], errors="coerce")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return output_csv


def _load_joined_spatial_frame(
    *,
    boundary_path: Path,
    analysis_joined_csv: Path,
    boundary_key: str,
    analysis_key: str,
) -> Any:
    gpd = _require_geopandas()
    boundaries = gpd.read_file(boundary_path)
    analysis = pd.read_csv(
        analysis_joined_csv,
        encoding="utf-8-sig",
        dtype={analysis_key: "string"},
    )
    if boundary_key not in boundaries.columns:
        raise ValueError(f"Boundary key field is missing from spatial data: {boundary_key}")
    if analysis_key not in analysis.columns:
        raise ValueError(f"Analysis key field is missing from joined CSV: {analysis_key}")

    width = _infer_key_width(boundaries[boundary_key], analysis[analysis_key])
    boundaries = boundaries.copy()
    analysis = analysis.copy()
    boundaries["_gc_join_key"] = normalize_join_key(boundaries[boundary_key], width=width)
    analysis["_gc_join_key"] = normalize_join_key(analysis[analysis_key], width=width)

    duplicate_count = int(analysis["_gc_join_key"].duplicated().sum())
    if duplicate_count:
        analysis = analysis.drop_duplicates(subset=["_gc_join_key"], keep="first")

    merged = boundaries.merge(
        analysis.drop(columns=[analysis_key], errors="ignore"),
        on="_gc_join_key",
        how="left",
        suffixes=("", "_analysis"),
    )
    return merged.drop(columns=["_gc_join_key"])


def _merge_optional_unit_metrics(
    frame: Any,
    *,
    metrics_path: Path,
    boundary_key: str,
    unit_key_candidates: Iterable[str],
    rename_map: dict[str, str],
) -> tuple[Any, list[str]]:
    if not metrics_path.exists():
        return frame, []

    dtype_map = {candidate: "string" for candidate in unit_key_candidates}
    metrics = pd.read_csv(metrics_path, encoding="utf-8-sig", dtype=dtype_map)
    unit_key = next((candidate for candidate in unit_key_candidates if candidate in metrics.columns), None)
    if unit_key is None or boundary_key not in frame.columns:
        return frame, []

    width = _infer_key_width(frame[boundary_key], metrics[unit_key])
    prepared = metrics.copy()
    prepared["_gc_join_key"] = normalize_join_key(prepared[unit_key], width=width)
    prepared = prepared.drop_duplicates(subset=["_gc_join_key"], keep="first")

    keep_columns = ["_gc_join_key"]
    produced_columns: list[str] = []
    for source_column, output_column in rename_map.items():
        if source_column not in prepared.columns:
            continue
        prepared[output_column] = prepared[source_column]
        keep_columns.append(output_column)
        produced_columns.append(output_column)

    if len(keep_columns) == 1:
        return frame, []

    merged = frame.copy()
    merged["_gc_join_key"] = normalize_join_key(merged[boundary_key], width=width)
    merged = merged.merge(
        prepared[keep_columns],
        on="_gc_join_key",
        how="left",
    )
    return merged.drop(columns=["_gc_join_key"]), produced_columns


def _spatial_columns(frame: Any) -> list[str]:
    return [column for column in frame.columns if column != getattr(frame, "geometry").name]


def _coerce_file_frame(frame: Any) -> Any:
    result = frame.copy()
    for column in _spatial_columns(result):
        if pd.api.types.is_bool_dtype(result[column]):
            result[column] = result[column].astype(str)
        elif pd.api.types.is_object_dtype(result[column]):
            result[column] = result[column].map(
                lambda value: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list, tuple))
                else value
            )
    return result


def _shapefile_safe_frame(frame: Any) -> Any:
    result = _coerce_file_frame(frame)
    rename: dict[str, str] = {}
    used: set[str] = set()
    for column in _spatial_columns(result):
        safe = _safe_field_token(column, max_length=10)
        base = safe[:8] if len(safe) > 8 else safe
        candidate = safe
        counter = 1
        while candidate.lower() in used:
            suffix = str(counter)
            candidate = f"{base[: 10 - len(suffix)]}{suffix}"
            counter += 1
        used.add(candidate.lower())
        if candidate != column:
            rename[column] = candidate
    return result.rename(columns=rename)


def write_spatial_files(
    frame: Any,
    *,
    output_dir: Path,
    output_stem: str,
    formats: Iterable[str] = ("gpkg", "geojson", "shp"),
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    requested = {item.lower().lstrip(".") for item in formats}
    file_frame = _coerce_file_frame(frame)

    if "gpkg" in requested:
        gpkg_path = output_dir / f"{output_stem}.gpkg"
        file_frame.to_file(gpkg_path, layer="county_analysis", driver="GPKG")
        outputs["gpkg"] = str(gpkg_path)

    if "geojson" in requested:
        geojson_path = output_dir / f"{output_stem}.geojson"
        geojson_frame = file_frame.to_crs(epsg=4326) if file_frame.crs else file_frame
        geojson_frame.to_file(geojson_path, driver="GeoJSON")
        outputs["geojson"] = str(geojson_path)

    if "shp" in requested:
        shp_dir = output_dir / f"{output_stem}_shp"
        shp_dir.mkdir(parents=True, exist_ok=True)
        shp_path = shp_dir / f"{output_stem}.shp"
        _shapefile_safe_frame(file_frame).to_file(shp_path, driver="ESRI Shapefile", encoding="UTF-8")
        outputs["shp"] = str(shp_path)

    return outputs


def _load_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def _plot_erf_curve(erf_curve: pd.DataFrame, output_path: Path) -> str | None:
    if erf_curve.empty or not {"exposure", "response"}.issubset(erf_curve.columns):
        return None
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    curve_columns = ["exposure", "response"]
    if {"ci_lower", "ci_upper"}.issubset(erf_curve.columns):
        curve_columns.extend(["ci_lower", "ci_upper"])
    curve = erf_curve[curve_columns].apply(pd.to_numeric, errors="coerce").dropna(subset=["exposure", "response"])
    if curve.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(curve["exposure"], curve["response"], color="#1f6f8b", linewidth=2.2)
    if {"ci_lower", "ci_upper"}.issubset(curve.columns):
        band = curve[["exposure", "ci_lower", "ci_upper"]].dropna()
        if not band.empty:
            ax.fill_between(
                band["exposure"],
                band["ci_lower"],
                band["ci_upper"],
                color="#1f6f8b",
                alpha=0.18,
                linewidth=0,
            )
    ax.set_xlabel("Exposure")
    ax.set_ylabel("Estimated outcome response")
    ax.set_title("Exposure-response curve")
    ax.grid(True, color="#d9d9d9", linewidth=0.6)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return str(output_path)


def _plot_effect_estimates(effect_estimates: pd.DataFrame, output_path: Path) -> str | None:
    if effect_estimates.empty or "estimator" not in effect_estimates.columns:
        return None
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    estimates = effect_estimates.copy()
    estimates["coef"] = pd.to_numeric(estimates.get("coef"), errors="coerce")
    estimates["ci_lower"] = pd.to_numeric(estimates.get("ci_lower"), errors="coerce")
    estimates["ci_upper"] = pd.to_numeric(estimates.get("ci_upper"), errors="coerce")
    estimates = estimates.dropna(subset=["coef"]).reset_index(drop=True)
    if estimates.empty:
        return None
    y = list(range(len(estimates)))
    lower = (estimates["coef"] - estimates["ci_lower"]).clip(lower=0)
    upper = (estimates["ci_upper"] - estimates["coef"]).clip(lower=0)
    has_ci = lower.notna() & upper.notna()
    error_x = estimates.loc[has_ci, "coef"].to_numpy(dtype=float)
    error_y = [y[index] for index in estimates.index[has_ci]]
    error_lower = lower.loc[has_ci].to_numpy(dtype=float)
    error_upper = upper.loc[has_ci].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.6 * len(estimates) + 1.6)))
    ax.barh(y, estimates["coef"], color="#496a81")
    if has_ci.any():
        ax.errorbar(
            error_x,
            error_y,
            xerr=[error_lower, error_upper],
            fmt="none",
            ecolor="#1d2327",
            elinewidth=1,
            capsize=3,
        )
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(estimates["estimator"])
    ax.set_xlabel("Estimated coefficient")
    ax.set_title("Effect estimates")
    ax.grid(True, axis="x", color="#d9d9d9", linewidth=0.6)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return str(output_path)


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _plot_spatial_slx_effects(slx_summary: dict[str, Any], output_path: Path) -> str | None:
    if not slx_summary or slx_summary.get("status") != "ok":
        return None
    direct = pd.to_numeric(pd.Series([slx_summary.get("direct_effect")]), errors="coerce").iloc[0]
    indirect = pd.to_numeric(pd.Series([slx_summary.get("indirect_effect")]), errors="coerce").iloc[0]
    total = pd.to_numeric(pd.Series([slx_summary.get("total_effect")]), errors="coerce").iloc[0]
    if not all(math.isfinite(float(value)) for value in (direct, indirect, total)):
        return None

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    labels = ["Direct", "Indirect", "Total"]
    values = [float(direct), float(indirect), float(total)]
    ci_lower = [
        pd.to_numeric(pd.Series([slx_summary.get("direct_ci_lower")]), errors="coerce").iloc[0],
        pd.to_numeric(pd.Series([slx_summary.get("indirect_ci_lower")]), errors="coerce").iloc[0],
        pd.to_numeric(pd.Series([slx_summary.get("total_ci_lower")]), errors="coerce").iloc[0],
    ]
    ci_upper = [
        pd.to_numeric(pd.Series([slx_summary.get("direct_ci_upper")]), errors="coerce").iloc[0],
        pd.to_numeric(pd.Series([slx_summary.get("indirect_ci_upper")]), errors="coerce").iloc[0],
        pd.to_numeric(pd.Series([slx_summary.get("total_ci_upper")]), errors="coerce").iloc[0],
    ]
    lower_errors = [
        max(value - lower, 0.0) if math.isfinite(float(lower)) else 0.0
        for value, lower in zip(values, ci_lower)
    ]
    upper_errors = [
        max(upper - value, 0.0) if math.isfinite(float(upper)) else 0.0
        for value, upper in zip(values, ci_upper)
    ]

    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    colors = ["#496a81", "#7b9e87", "#c17c3a"]
    bars = ax.bar(labels, values, color=colors, width=0.62)
    for index, (value, bar) in enumerate(zip(values, bars)):
        if lower_errors[index] > 0 or upper_errors[index] > 0:
            ax.errorbar(
                bar.get_x() + bar.get_width() / 2.0,
                value,
                yerr=[[lower_errors[index]], [upper_errors[index]]],
                fmt="none",
                ecolor="#1d2327",
                elinewidth=1,
                capsize=3,
            )
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            value,
            f"{value:.3f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=9,
        )
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_ylabel("Estimated effect")
    ax.set_title("SLX direct, indirect, and total effects")
    ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.6)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return str(output_path)


def _plot_exposure_change_distribution(frame: Any, map_field: str, output_path: Path) -> str | None:
    if map_field not in frame.columns:
        return None
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    values = pd.to_numeric(frame[map_field], errors="coerce").dropna()
    if values.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(values, bins=32, color="#637f4f", edgecolor="white", linewidth=0.4)
    ax.axvline(0, color="#333333", linewidth=0.9)
    ax.set_xlabel(map_field)
    ax.set_ylabel("County count")
    ax.set_title("Target exposure-change distribution")
    ax.grid(True, axis="y", color="#d9d9d9", linewidth=0.6)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return str(output_path)


def _plot_static_map(
    frame: Any,
    *,
    map_field: str,
    output_path: Path,
    states_path: Path | None = None,
    title: str = "County target exposure change",
) -> str | None:
    if map_field not in frame.columns:
        return None
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    values = pd.to_numeric(frame[map_field], errors="coerce")
    if values.notna().sum() == 0:
        return None
    plot_frame = frame.copy()
    plot_frame[map_field] = values
    fig, ax = plt.subplots(figsize=(12, 8))
    plot_frame.plot(
        column=map_field,
        cmap="RdBu_r",
        legend=True,
        linewidth=0.08,
        edgecolor="#ffffff",
        missing_kwds={"color": "#efefef", "edgecolor": "#ffffff", "hatch": "///"},
        ax=ax,
    )
    if states_path and states_path.exists():
        try:
            states = _require_geopandas().read_file(states_path)
            if states.crs != plot_frame.crs and plot_frame.crs is not None:
                states = states.to_crs(plot_frame.crs)
            states.boundary.plot(ax=ax, color="#303030", linewidth=0.35)
        except Exception:
            pass
    ax.set_axis_off()
    ax.set_title(title, pad=12)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return str(output_path)


def _map_center(frame: Any) -> tuple[float, float]:
    bounds = frame.total_bounds
    if len(bounds) != 4 or any(not math.isfinite(float(value)) for value in bounds):
        return 39.5, -98.35
    minx, miny, maxx, maxy = (float(value) for value in bounds)
    return (miny + maxy) / 2.0, (minx + maxx) / 2.0


def _write_interactive_map(frame: Any, *, map_field: str, output_path: Path) -> str | None:
    if map_field not in frame.columns:
        return None
    values = pd.to_numeric(frame[map_field], errors="coerce")
    if values.notna().sum() == 0:
        return None

    import branca.colormap as cm
    import folium

    map_frame = frame.copy()
    map_frame[map_field] = values
    map_frame = map_frame.to_crs(epsg=4326) if map_frame.crs else map_frame
    map_frame = map_frame.loc[map_frame.geometry.notna()].copy()
    map_frame = map_frame.loc[~map_frame.geometry.is_empty].copy()
    if map_frame.empty:
        return None
    map_frame["geometry"] = map_frame.geometry.simplify(0.01, preserve_topology=True)

    valid = map_frame[map_field].dropna()
    min_value = float(valid.min())
    max_value = float(valid.max())
    if min_value == max_value:
        max_value = min_value + 1.0
    color_map = cm.LinearColormap(
        ["#2f5d8c", "#f7f7f2", "#b84a3a"],
        vmin=min_value,
        vmax=max_value,
    )
    color_map.caption = map_field
    fmap = folium.Map(location=_map_center(map_frame), zoom_start=4, tiles="cartodbpositron")

    def style_function(feature: dict[str, Any]) -> dict[str, Any]:
        value = feature.get("properties", {}).get(map_field)
        if value is None:
            return {"fillColor": "#d9d9d9", "color": "#ffffff", "weight": 0.2, "fillOpacity": 0.25}
        return {
            "fillColor": color_map(float(value)),
            "color": "#ffffff",
            "weight": 0.2,
            "fillOpacity": 0.72,
        }

    tooltip_fields = [
        column
        for column in ("STATE_NAME", "County", "FIPS", map_field)
        if column in map_frame.columns
    ]
    folium.GeoJson(
        map_frame.to_json(),
        name="County analysis",
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields) if tooltip_fields else None,
    ).add_to(fmap)
    color_map.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(output_path)
    return str(output_path)


def _format_qgis_number(value: float) -> str:
    if value != 0 and abs(value) < 0.001:
        return f"{value:.3e}"
    return f"{value:.6g}"


def _qgis_class_breaks(values: pd.Series, *, class_count: int = 5) -> list[tuple[float, float]]:
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return []
    unique = np.unique(numeric.to_numpy(dtype=float))
    if len(unique) == 1:
        value = float(unique[0])
        return [(value, value)]

    classes = max(2, min(int(class_count), int(len(unique))))
    quantiles = np.quantile(numeric.to_numpy(dtype=float), np.linspace(0.0, 1.0, classes + 1))
    breaks = sorted({float(value) for value in quantiles if np.isfinite(value)})
    if len(breaks) < 2:
        breaks = [float(unique.min()), float(unique.max())]
    return [(breaks[index], breaks[index + 1]) for index in range(len(breaks) - 1)]


def _qgis_fill_symbol(index: int, color: str) -> str:
    return f"""      <symbol alpha=\"1\" clip_to_extent=\"1\" force_rhr=\"0\" name=\"{index}\" type=\"fill\">
        <layer class=\"SimpleFill\" enabled=\"1\" locked=\"0\" pass=\"0\">
          <Option type=\"Map\">
            <Option name=\"color\" type=\"QString\" value=\"{color}\"/>
            <Option name=\"joinstyle\" type=\"QString\" value=\"bevel\"/>
            <Option name=\"outline_color\" type=\"QString\" value=\"255,255,255,255\"/>
            <Option name=\"outline_style\" type=\"QString\" value=\"solid\"/>
            <Option name=\"outline_width\" type=\"QString\" value=\"0.10\"/>
            <Option name=\"outline_width_unit\" type=\"QString\" value=\"MM\"/>
            <Option name=\"style\" type=\"QString\" value=\"solid\"/>
          </Option>
        </layer>
      </symbol>"""


def _write_qgis_graduated_style(
    frame: Any,
    *,
    field: str,
    output_path: Path,
    colors: list[str],
) -> str | None:
    if field not in frame.columns:
        return None
    values = pd.to_numeric(frame[field], errors="coerce")
    if values.notna().sum() == 0:
        return None

    ranges = _qgis_class_breaks(values)
    if not ranges:
        return None
    if len(colors) < len(ranges):
        colors = [*colors, *([colors[-1]] * (len(ranges) - len(colors)))]
    field_xml = escape(field)
    range_lines: list[str] = []
    symbol_lines: list[str] = []
    for index, (lower, upper) in enumerate(ranges):
        label = f"{_format_qgis_number(lower)} - {_format_qgis_number(upper)}"
        range_lines.append(
            "      "
            f"<range label=\"{escape(label)}\" lower=\"{_format_qgis_number(lower)}\" "
            f"render=\"true\" symbol=\"{index}\" upper=\"{_format_qgis_number(upper)}\"/>"
        )
        symbol_lines.append(_qgis_fill_symbol(index, colors[index]))

    qml = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version=\"3.34\" styleCategories=\"Symbology\">
  <renderer-v2 attr=\"{field_xml}\" enableorderby=\"0\" forceraster=\"0\" graduatedMethod=\"GraduatedColor\" symbollevels=\"0\" type=\"graduatedSymbol\">
    <ranges>
{chr(10).join(range_lines)}
    </ranges>
    <symbols>
{chr(10).join(symbol_lines)}
    </symbols>
    <classificationMethod id=\"Quantile\"/>
  </renderer-v2>
  <layerGeometryType>2</layerGeometryType>
</qgis>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(qml, encoding="utf-8")
    return str(output_path)


def write_qgis_styles(
    *,
    spatial_frame: Any,
    output_dir: str | Path,
    map_field: str = "gc_target_70_exposure_change",
) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    diverging = ["49,93,140,255", "104,151,170,255", "247,247,242,255", "205,139,80,255", "184,74,58,255"]
    sequential = ["247,247,242,255", "186,210,171,255", "123,158,135,255", "73,106,129,255", "43,72,89,255"]
    style_specs = {
        "target_exposure_change_qml": (map_field, output_dir / "target_exposure_change.qml", diverging),
        "spatial_indirect_effect_qml": (
            "gc_spatial_indirect_effect",
            output_dir / "spatial_indirect_effect.qml",
            sequential,
        ),
        "spatial_total_effect_qml": (
            "gc_spatial_total_effect",
            output_dir / "spatial_total_effect.qml",
            sequential,
        ),
    }
    outputs: dict[str, str] = {}
    for key, (field, path, colors) in style_specs.items():
        style_path = _write_qgis_graduated_style(
            spatial_frame,
            field=field,
            output_path=path,
            colors=colors,
        )
        if style_path:
            outputs[key] = style_path
    return outputs


def write_analysis_visualizations(
    *,
    analysis_dir: str | Path,
    spatial_frame: Any,
    output_dir: str | Path,
    map_field: str = "gc_target_70_exposure_change",
    states_path: str | Path | None = None,
) -> dict[str, str]:
    analysis_dir = Path(analysis_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    states = Path(states_path) if states_path else None
    outputs: dict[str, str] = {}

    erf = _plot_erf_curve(
        _load_csv_if_exists(analysis_dir / "erf_curve.csv"),
        output_dir / "erf_curve.png",
    )
    if erf:
        outputs["erf_curve_png"] = erf
    effects = _plot_effect_estimates(
        _load_csv_if_exists(analysis_dir / "effect_estimates.csv"),
        output_dir / "effect_estimates.png",
    )
    if effects:
        outputs["effect_estimates_png"] = effects
    slx_effects = _plot_spatial_slx_effects(
        _load_json_if_exists(analysis_dir / "spatial_slx_summary.json"),
        output_dir / "spatial_slx_effects.png",
    )
    if slx_effects:
        outputs["spatial_slx_effects_png"] = slx_effects
    histogram = _plot_exposure_change_distribution(
        spatial_frame,
        map_field,
        output_dir / "target_exposure_change_histogram.png",
    )
    if histogram:
        outputs["target_exposure_change_histogram_png"] = histogram
    static_map = _plot_static_map(
        spatial_frame,
        map_field=map_field,
        output_path=output_dir / "target_exposure_change_map.png",
        states_path=states,
        title="County target exposure change",
    )
    if static_map:
        outputs["target_exposure_change_map_png"] = static_map
    interactive_map = _write_interactive_map(
        spatial_frame,
        map_field=map_field,
        output_path=output_dir / "target_exposure_change_map.html",
    )
    if interactive_map:
        outputs["target_exposure_change_map_html"] = interactive_map

    if "gc_spatial_indirect_effect" in spatial_frame.columns:
        indirect_map = _plot_static_map(
            spatial_frame,
            map_field="gc_spatial_indirect_effect",
            output_path=output_dir / "spatial_indirect_effect_map.png",
            states_path=states,
            title="County spatial indirect effect",
        )
        if indirect_map:
            outputs["spatial_indirect_effect_map_png"] = indirect_map
        indirect_map_html = _write_interactive_map(
            spatial_frame,
            map_field="gc_spatial_indirect_effect",
            output_path=output_dir / "spatial_indirect_effect_map.html",
        )
        if indirect_map_html:
            outputs["spatial_indirect_effect_map_html"] = indirect_map_html
    return outputs


def build_spatial_analysis_outputs(
    *,
    boundary_path: str | Path,
    analysis_joined_csv: str | Path,
    output_dir: str | Path,
    analysis_dir: str | Path | None = None,
    boundary_key: str = "FIPS",
    analysis_key: str = "FIPS",
    output_stem: str = "county_social_capital_analysis",
    formats: Iterable[str] = ("gpkg", "geojson", "shp"),
    states_path: str | Path | None = None,
    map_field: str = "gc_target_70_exposure_change",
) -> dict[str, Any]:
    boundary_path = Path(boundary_path)
    analysis_joined_csv = Path(analysis_joined_csv)
    output_dir = Path(output_dir)
    analysis_dir_path = Path(analysis_dir) if analysis_dir else analysis_joined_csv.parent

    joined_frame = _load_joined_spatial_frame(
        boundary_path=boundary_path,
        analysis_joined_csv=analysis_joined_csv,
        boundary_key=boundary_key,
        analysis_key=analysis_key,
    )
    joined_frame, exposure_mapping_fields = _merge_optional_unit_metrics(
        joined_frame,
        metrics_path=analysis_dir_path / "spatial_exposure_mapping.csv",
        boundary_key=boundary_key,
        unit_key_candidates=(analysis_key, boundary_key, "unit_id"),
        rename_map={
            "direct_effect": "gc_spatial_direct_effect",
            "indirect_effect": "gc_spatial_indirect_effect",
            "total_effect": "gc_spatial_total_effect",
            "out_neighbor_count": "gc_spatial_out_neighbor_count",
            "incoming_weight_sum": "gc_spatial_incoming_weight_sum",
        },
    )
    spatial_files = write_spatial_files(
        joined_frame,
        output_dir=output_dir,
        output_stem=output_stem,
        formats=formats,
    )
    visualization_dir = output_dir / "visualizations"
    visualizations = write_analysis_visualizations(
        analysis_dir=analysis_dir_path,
        spatial_frame=joined_frame,
        output_dir=visualization_dir,
        map_field=map_field,
        states_path=states_path,
    )
    qgis_styles = write_qgis_styles(
        spatial_frame=joined_frame,
        output_dir=output_dir / "qgis_styles",
        map_field=map_field,
    )
    manifest = {
        "boundary_path": str(boundary_path),
        "analysis_joined_csv": str(analysis_joined_csv),
        "analysis_dir": str(analysis_dir_path),
        "row_count": int(len(joined_frame)),
        "matched_count": int(joined_frame[map_field].notna().sum()) if map_field in joined_frame.columns else None,
        "crs": str(joined_frame.crs) if joined_frame.crs is not None else None,
        "map_field": map_field,
        "enriched_effect_fields": exposure_mapping_fields,
        "spatial_files": spatial_files,
        "visualizations": visualizations,
        "qgis_styles": qgis_styles,
    }
    manifest_path = output_dir / "spatial_output_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest"] = str(manifest_path)
    return manifest
