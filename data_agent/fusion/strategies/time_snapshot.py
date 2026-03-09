"""Time snapshot strategy — join stream/temporal data to vector features."""
import geopandas as gpd
import pandas as pd


def _strategy_time_snapshot(aligned: list, params: dict) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Join stream/temporal data to vector features via spatial+temporal filtering.

    Loads stream data (CSV/JSON with timestamp, lat, lng, value columns),
    filters by time window, spatially joins to vector features, and aggregates.

    Params:
        window_minutes (int): Time window in minutes (default: 60).
        value_column (str): Column name for values to aggregate (default: "value").
        agg_stats (list[str]): Aggregation stats — count, mean, latest (default: all).
        timestamp_column (str): Timestamp column name (default: "timestamp").
    """
    log = []

    gdf = None
    stream_path = None
    for dtype, data in aligned:
        if dtype == "vector" and isinstance(data, gpd.GeoDataFrame):
            gdf = data
        elif dtype in ("stream", "tabular") and isinstance(data, (str, pd.DataFrame)):
            if isinstance(data, str):
                stream_path = data
            else:
                stream_path = data  # already loaded DataFrame

    if gdf is None:
        raise ValueError("time_snapshot requires at least one vector source.")

    result = gdf.copy()
    result["_fusion_timestamp"] = pd.Timestamp.now().isoformat()

    # Load and process stream data if available
    stream_df = None
    if stream_path is not None:
        try:
            if isinstance(stream_path, pd.DataFrame):
                stream_df = stream_path
            elif stream_path.endswith(".json"):
                stream_df = pd.read_json(stream_path)
            else:
                stream_df = pd.read_csv(stream_path, encoding="utf-8")
        except Exception as e:
            log.append(f"Stream data load failed: {e} — timestamp-only fallback")

    if stream_df is not None and len(stream_df) > 0:
        ts_col = params.get("timestamp_column", "timestamp")
        val_col = params.get("value_column", "value")
        window_min = params.get("window_minutes", 60)
        agg_stats = params.get("agg_stats", ["count", "mean", "latest"])

        # Time window filtering
        if ts_col in stream_df.columns:
            try:
                stream_df[ts_col] = pd.to_datetime(stream_df[ts_col])
                cutoff = pd.Timestamp.now() - pd.Timedelta(minutes=window_min)
                before_filter = len(stream_df)
                stream_df = stream_df[stream_df[ts_col] >= cutoff]
                log.append(f"Time window filter: {before_filter} → {len(stream_df)} "
                           f"events (last {window_min} min)")
            except Exception:
                log.append("Time parsing failed — using all stream records")

        # Spatial join: stream points to vector polygons
        lat_col = None
        lng_col = None
        for c in stream_df.columns:
            cl = c.lower()
            if cl in ("lat", "latitude", "y"):
                lat_col = c
            elif cl in ("lng", "lon", "longitude", "x"):
                lng_col = c

        if lat_col and lng_col:
            try:
                stream_gdf = gpd.GeoDataFrame(
                    stream_df,
                    geometry=gpd.points_from_xy(stream_df[lng_col], stream_df[lat_col]),
                    crs=gdf.crs or "EPSG:4326",
                )
                joined = gpd.sjoin(stream_gdf, gdf, how="inner", predicate="within")

                # Aggregate per target polygon
                if val_col in joined.columns and len(joined) > 0:
                    agg_dict = {}
                    if "count" in agg_stats:
                        agg_dict["stream_count"] = (val_col, "count")
                    if "mean" in agg_stats:
                        agg_dict["stream_mean"] = (val_col, "mean")

                    if agg_dict:
                        grouped = joined.groupby("index_right").agg(**agg_dict)
                        for col_name in grouped.columns:
                            result[col_name] = result.index.map(
                                grouped[col_name]
                            ).fillna(0)

                    if "latest" in agg_stats and ts_col in joined.columns:
                        latest = joined.groupby("index_right")[ts_col].max()
                        result["stream_latest"] = result.index.map(latest)

                log.append(f"Stream fusion: {len(joined)} events joined to "
                           f"{len(result)} features")
            except Exception as e:
                log.append(f"Stream spatial join failed: {e} — timestamp-only fallback")
        else:
            log.append("No coordinate columns found in stream data — timestamp-only")
    else:
        log.append(f"Time snapshot: annotated {len(result)} features with timestamp")

    return result, log
