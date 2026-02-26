import pandas as pd
import geopandas as gpd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
import requests
import time
import os
from .gis_processors import _generate_output_path


def _geocode_amap(address: str, city: str = None) -> tuple:
    """
    Geocode a single address using Amap (高德) API.

    Returns:
        (longitude, latitude) tuple on success, None on failure.
    """
    api_key = os.environ.get("GAODE_API_KEY")
    if not api_key:
        return None

    params = {
        "key": api_key,
        "address": address,
    }
    if city:
        params["city"] = city

    try:
        resp = requests.get(
            "https://restapi.amap.com/v3/geocode/geo",
            params=params,
            timeout=10
        )
        data = resp.json()

        if data.get("status") == "1" and data.get("geocodes"):
            location_str = data["geocodes"][0]["location"]  # "116.397128,39.916527"
            lng, lat = location_str.split(",")
            return (float(lng), float(lat))
        return None
    except Exception:
        return None


def _reverse_geocode_amap(lng: float, lat: float) -> dict:
    """
    Reverse geocode using Amap (高德) API.

    Returns:
        Dict with address/province/city/district on success, None on failure.
    """
    api_key = os.environ.get("GAODE_API_KEY")
    if not api_key:
        return None

    params = {
        "key": api_key,
        "location": f"{lng},{lat}",
        "extensions": "base",
    }

    try:
        resp = requests.get(
            "https://restapi.amap.com/v3/geocode/regeocode",
            params=params,
            timeout=10,
        )
        data = resp.json()

        if data.get("status") == "1" and data.get("regeocode"):
            rc = data["regeocode"]
            ac = rc.get("addressComponent", {})
            return {
                "address": rc.get("formatted_address", ""),
                "province": ac.get("province", ""),
                "city": ac.get("city", "") if isinstance(ac.get("city"), str) else "",
                "district": ac.get("district", ""),
            }
        return None
    except Exception:
        return None


def batch_geocode(file_path: str, address_col: str, city: str = None) -> dict:
    """
    [Data Processing Tool] Converts addresses in a table (Excel/CSV) to coordinates.
    Uses Amap (高德) API when GAODE_API_KEY is configured, otherwise falls back to Nominatim.

    Args:
        file_path: Path to .xlsx or .csv file.
        address_col: Name of the column containing addresses.
        city: Optional city context to improve accuracy (e.g., "北京").

    Returns:
        Dict with status and path to the generated Shapefile.
    """
    try:
        # 1. Load Data
        if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)

        if address_col not in df.columns:
            return {"status": "error", "message": f"Column '{address_col}' not found. Available: {list(df.columns)}"}

        # 2. Select Geocoding Provider
        use_amap = bool(os.environ.get("GAODE_API_KEY"))
        provider_name = "Amap (高德)" if use_amap else "Nominatim (OSM)"
        print(f"Geocoding provider: {provider_name}")

        # Init Nominatim as fallback
        nominatim_geocode = None
        if not use_amap:
            geolocator = Nominatim(user_agent="data_agent_v3")
            nominatim_geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1)

        results = []
        success_count = 0

        print(f"Starting geocoding for {len(df)} records using address column: '{address_col}'...")

        # 3. Batch Process
        for idx, row in df.iterrows():
            addr = str(row[address_col])
            if city and city not in addr:
                query = f"{city} {addr}"
            else:
                query = addr

            try:
                lng, lat = None, None

                if use_amap:
                    result = _geocode_amap(addr, city=city)
                    if result:
                        lng, lat = result
                else:
                    location = nominatim_geocode(query)
                    if location:
                        lng, lat = location.longitude, location.latitude

                if lng is not None and lat is not None:
                    results.append({
                        "geometry": gpd.points_from_xy([lng], [lat])[0],
                        **row.to_dict(),
                        "geocode_match": "High",
                        "geocode_provider": provider_name
                    })
                    success_count += 1
                else:
                    print(f"  [Warn] Failed to geocode: {query}")
            except Exception as e:
                print(f"  [Error] Geocoding error for {query}: {e}")

        if success_count == 0:
            return {"status": "error", "message": "No addresses could be geocoded."}

        # 4. Create GeoDataFrame
        gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")

        # 5. Save as SHP (Standardize)
        out_path = _generate_output_path("geocoded", "shp")
        gdf.to_file(out_path, encoding='utf-8')

        return {
            "status": "success",
            "output_path": out_path,
            "total": len(df),
            "success": success_count,
            "provider": provider_name,
            "message": f"Geocoded {success_count}/{len(df)} addresses via {provider_name}."
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def reverse_geocode(file_path: str, lng_col: str = None, lat_col: str = None) -> dict:
    """
    [Data Processing Tool] 逆地理编码：将坐标转换为地址信息。
    支持 SHP/GeoJSON（从 Point 几何提取坐标）或 CSV/Excel（需指定经纬度列）。
    使用高德 API（需 GAODE_API_KEY），否则回退到 Nominatim。

    Args:
        file_path: 数据文件路径 (.shp/.geojson/.csv/.xlsx)。
        lng_col: 经度列名 (仅 CSV/Excel 需要，SHP 自动提取)。
        lat_col: 纬度列名 (仅 CSV/Excel 需要，SHP 自动提取)。

    Returns:
        Dict with status and path to output file with address columns added.
    """
    try:
        ext = os.path.splitext(file_path)[1].lower()

        # Load data
        if ext in ('.csv', '.xlsx', '.xls'):
            df = pd.read_csv(file_path) if ext == '.csv' else pd.read_excel(file_path)
            gdf = None

            # Detect coordinate columns
            if not lng_col or not lat_col:
                cols_lower = {c.lower(): c for c in df.columns}
                if 'lng' in cols_lower and 'lat' in cols_lower:
                    lng_col, lat_col = cols_lower['lng'], cols_lower['lat']
                elif 'lon' in cols_lower and 'lat' in cols_lower:
                    lng_col, lat_col = cols_lower['lon'], cols_lower['lat']
                elif 'longitude' in cols_lower and 'latitude' in cols_lower:
                    lng_col, lat_col = cols_lower['longitude'], cols_lower['latitude']
                elif 'x' in cols_lower and 'y' in cols_lower:
                    lng_col, lat_col = cols_lower['x'], cols_lower['y']
                else:
                    return {"status": "error", "message": f"无法自动检测经纬度列。可用列: {list(df.columns)}。请指定 lng_col 和 lat_col。"}

            coords = list(zip(df[lng_col].astype(float), df[lat_col].astype(float)))
        else:
            gdf = gpd.read_file(file_path)
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            # Extract coords from point geometry
            if not all(gdf.geom_type.isin(['Point', 'MultiPoint'])):
                # For polygon/line: use centroid
                coords = [(g.centroid.x, g.centroid.y) for g in gdf.geometry]
            else:
                coords = [(g.x, g.y) for g in gdf.geometry]
            df = pd.DataFrame(gdf.drop(columns='geometry'))

        # Reverse geocode each coordinate
        use_amap = bool(os.environ.get("GAODE_API_KEY"))
        provider_name = "Amap (高德)" if use_amap else "Nominatim (OSM)"

        nominatim_reverse = None
        if not use_amap:
            geolocator = Nominatim(user_agent="data_agent_v3")
            nominatim_reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1.1)

        addresses, provinces, cities, districts = [], [], [], []
        success_count = 0

        print(f"Starting reverse geocoding for {len(coords)} records via {provider_name}...")

        for lng, lat in coords:
            try:
                result = None
                if use_amap:
                    result = _reverse_geocode_amap(lng, lat)

                if result:
                    addresses.append(result["address"])
                    provinces.append(result["province"])
                    cities.append(result["city"])
                    districts.append(result["district"])
                    success_count += 1
                elif nominatim_reverse:
                    location = nominatim_reverse(f"{lat}, {lng}")
                    if location:
                        addresses.append(location.address)
                        provinces.append("")
                        cities.append("")
                        districts.append("")
                        success_count += 1
                    else:
                        addresses.append("")
                        provinces.append("")
                        cities.append("")
                        districts.append("")
                else:
                    addresses.append("")
                    provinces.append("")
                    cities.append("")
                    districts.append("")
            except Exception as e:
                print(f"  [Warn] Reverse geocode failed for ({lng},{lat}): {e}")
                addresses.append("")
                provinces.append("")
                cities.append("")
                districts.append("")

        # Add columns
        df["address"] = addresses
        df["province"] = provinces
        df["city"] = cities
        df["district"] = districts

        # Build output GeoDataFrame
        geom = gpd.points_from_xy([c[0] for c in coords], [c[1] for c in coords])
        result_gdf = gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")

        out_path = _generate_output_path("geocoded", "shp")
        result_gdf.to_file(out_path, encoding='utf-8')

        return {
            "status": "success",
            "output_path": out_path,
            "total": len(coords),
            "success": success_count,
            "provider": provider_name,
            "message": f"逆地理编码完成: {success_count}/{len(coords)} 条记录已转换为地址 (via {provider_name})。",
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def calculate_driving_distance(
    origin_lng: float, origin_lat: float,
    dest_lng: float, dest_lat: float
) -> str:
    """
    计算两点之间的驾车距离和预计时间（高德路径规划 API）。
    同时返回直线距离作为参考。

    Args:
        origin_lng: 起点经度。
        origin_lat: 起点纬度。
        dest_lng: 终点经度。
        dest_lat: 终点纬度。
    Returns:
        包含驾车距离、预计时间、直线距离的文字描述。
    """
    from math import radians, sin, cos, sqrt, atan2

    # 1. Haversine straight-line distance
    R = 6371000  # meters
    lat1, lat2 = radians(origin_lat), radians(dest_lat)
    dlat = radians(dest_lat - origin_lat)
    dlng = radians(dest_lng - origin_lng)
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    straight_dist = R * 2 * atan2(sqrt(a), sqrt(1-a))

    # 2. Amap driving route API
    api_key = os.environ.get("GAODE_API_KEY")
    if not api_key:
        return (
            f"直线距离: {straight_dist/1000:.2f} km\n"
            f"（驾车距离不可用：未配置 GAODE_API_KEY）"
        )

    try:
        params = {
            "key": api_key,
            "origin": f"{origin_lng},{origin_lat}",
            "destination": f"{dest_lng},{dest_lat}",
            "strategy": 0,  # fastest
        }
        resp = requests.get(
            "https://restapi.amap.com/v3/direction/driving",
            params=params,
            timeout=15,
        )
        data = resp.json()

        if data.get("status") == "1" and data.get("route", {}).get("paths"):
            path = data["route"]["paths"][0]
            drive_dist = float(path["distance"])  # meters
            drive_time = float(path["duration"])  # seconds
            if drive_time >= 3600:
                time_str = f"{int(drive_time//3600)}小时{int((drive_time%3600)//60)}分钟"
            else:
                time_str = f"{int(drive_time//60)}分钟"
            return (
                f"直线距离: {straight_dist/1000:.2f} km\n"
                f"驾车距离: {drive_dist/1000:.2f} km\n"
                f"预计驾车时间: {time_str}"
            )
        else:
            info = data.get("info", "unknown error")
            return (
                f"直线距离: {straight_dist/1000:.2f} km\n"
                f"（驾车距离查询失败: {info}）"
            )
    except Exception as e:
        return (
            f"直线距离: {straight_dist/1000:.2f} km\n"
            f"（驾车距离查询异常: {str(e)}）"
        )


def _parse_amap_polyline(polyline_str: str) -> list:
    """Parse Amap district polyline string into a list of Shapely Polygons.

    Amap format: polygons/rings separated by '|', coords by ';', lng/lat by ','.
    """
    from shapely.geometry import Polygon as _Polygon
    if not polyline_str:
        return []
    polygons = []
    for ring_str in polyline_str.split("|"):
        ring_str = ring_str.strip()
        if not ring_str:
            continue
        coords = []
        for pair in ring_str.split(";"):
            pair = pair.strip()
            if "," not in pair:
                continue
            try:
                lng_s, lat_s = pair.split(",", 1)
                coords.append((float(lng_s), float(lat_s)))
            except ValueError:
                continue
        if len(coords) >= 3:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            try:
                polygons.append(_Polygon(coords))
            except Exception:
                continue
    return polygons


def search_nearby_poi(
    lng: float,
    lat: float,
    keywords: str,
    radius: int = 3000,
    max_results: int = 50,
) -> dict:
    """
    周边POI搜索：搜索指定坐标点附近的兴趣点（银行、学校、医院等）。

    Args:
        lng: 中心点经度。
        lat: 中心点纬度。
        keywords: 搜索关键词 (如 "银行", "学校", "医院", "餐厅")。
        radius: 搜索半径 (米), 默认3000, 最大50000。
        max_results: 最大返回结果数, 默认50。

    Returns:
        Dict with status, output_path (Shapefile), total count, and message.
    """
    from shapely.geometry import Point
    import math

    api_key = os.environ.get("GAODE_API_KEY")
    if not api_key:
        return {"status": "error", "message": "未配置 GAODE_API_KEY，无法使用 POI 搜索。请在 .env 中设置高德 API Key。"}

    try:
        radius = min(int(radius), 50000)
        page_size = 25
        max_pages = math.ceil(max_results / page_size)
        all_pois = []

        for page_num in range(1, max_pages + 1):
            params = {
                "key": api_key,
                "location": f"{lng},{lat}",
                "keywords": keywords,
                "radius": radius,
                "page_size": page_size,
                "page_num": page_num,
                "show_fields": "business",
            }
            resp = requests.get(
                "https://restapi.amap.com/v5/place/around",
                params=params,
                timeout=15,
            )
            data = resp.json()

            if data.get("status") != "1":
                info = data.get("info", "unknown")
                if not all_pois:
                    return {"status": "error", "message": f"高德 POI 搜索失败: {info}"}
                break

            pois = data.get("pois", [])
            if not pois:
                break

            all_pois.extend(pois)
            if len(all_pois) >= max_results:
                all_pois = all_pois[:max_results]
                break

            time.sleep(0.1)

        if not all_pois:
            return {"status": "error", "message": f"在 ({lng},{lat}) 周围 {radius}m 内未找到 '{keywords}' 相关 POI。"}

        records = []
        for poi in all_pois:
            loc_str = poi.get("location", "")
            if not loc_str or "," not in loc_str:
                continue
            try:
                poi_lng, poi_lat = map(float, loc_str.split(","))
            except ValueError:
                continue
            records.append({
                "name": poi.get("name", ""),
                "type": poi.get("type", ""),
                "address": poi.get("address", ""),
                "pname": poi.get("pname", ""),
                "cityname": poi.get("cityname", ""),
                "adname": poi.get("adname", ""),
                "tel": str(poi.get("tel", ""))[:50],
                "distance_m": poi.get("distance", ""),
                "geometry": Point(poi_lng, poi_lat),
            })

        if not records:
            return {"status": "error", "message": "POI 搜索成功但无法解析坐标数据。"}

        gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
        out_path = _generate_output_path("poi_nearby", "shp")
        gdf.to_file(out_path, encoding='utf-8')

        return {
            "status": "success",
            "output_path": out_path,
            "total": len(gdf),
            "message": f"在 ({lng},{lat}) 周围 {radius}m 内找到 {len(gdf)} 个 '{keywords}' 相关 POI。",
        }
    except Exception as e:
        return {"status": "error", "message": f"POI 周边搜索异常: {str(e)}"}


def search_poi_by_keyword(
    keywords: str,
    region: str,
    max_results: int = 50,
) -> dict:
    """
    关键字POI搜索：在指定城市/区域内搜索兴趣点。

    Args:
        keywords: 搜索关键词 (如 "咖啡馆", "加油站", "星巴克")。
        region: 城市名或区划名 (如 "北京市", "朝阳区", "杭州")。
        max_results: 最大返回结果数, 默认50。

    Returns:
        Dict with status, output_path (Shapefile), total count, and message.
    """
    from shapely.geometry import Point
    import math

    api_key = os.environ.get("GAODE_API_KEY")
    if not api_key:
        return {"status": "error", "message": "未配置 GAODE_API_KEY，无法使用 POI 搜索。请在 .env 中设置高德 API Key。"}

    try:
        page_size = 25
        max_pages = math.ceil(max_results / page_size)
        all_pois = []

        for page_num in range(1, max_pages + 1):
            params = {
                "key": api_key,
                "keywords": keywords,
                "region": region,
                "city_limit": "true",
                "page_size": page_size,
                "page_num": page_num,
                "show_fields": "business",
            }
            resp = requests.get(
                "https://restapi.amap.com/v5/place/text",
                params=params,
                timeout=15,
            )
            data = resp.json()

            if data.get("status") != "1":
                info = data.get("info", "unknown")
                if not all_pois:
                    return {"status": "error", "message": f"高德 POI 搜索失败: {info}"}
                break

            pois = data.get("pois", [])
            if not pois:
                break

            all_pois.extend(pois)
            if len(all_pois) >= max_results:
                all_pois = all_pois[:max_results]
                break

            time.sleep(0.1)

        if not all_pois:
            return {"status": "error", "message": f"在 '{region}' 内未找到 '{keywords}' 相关 POI。"}

        records = []
        for poi in all_pois:
            loc_str = poi.get("location", "")
            if not loc_str or "," not in loc_str:
                continue
            try:
                poi_lng, poi_lat = map(float, loc_str.split(","))
            except ValueError:
                continue
            records.append({
                "name": poi.get("name", ""),
                "type": poi.get("type", ""),
                "address": poi.get("address", ""),
                "pname": poi.get("pname", ""),
                "cityname": poi.get("cityname", ""),
                "adname": poi.get("adname", ""),
                "tel": str(poi.get("tel", ""))[:50],
                "geometry": Point(poi_lng, poi_lat),
            })

        if not records:
            return {"status": "error", "message": "POI 搜索成功但无法解析坐标数据。"}

        gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
        out_path = _generate_output_path("poi_keyword", "shp")
        gdf.to_file(out_path, encoding='utf-8')

        return {
            "status": "success",
            "output_path": out_path,
            "total": len(gdf),
            "message": f"在 '{region}' 内找到 {len(gdf)} 个 '{keywords}' 相关 POI。",
        }
    except Exception as e:
        return {"status": "error", "message": f"POI 关键词搜索异常: {str(e)}"}


def get_admin_boundary(
    district_name: str,
    with_sub_districts: bool = False,
) -> dict:
    """
    获取行政区划边界：下载指定行政区的矢量边界数据（Shapefile）。

    Args:
        district_name: 行政区名称 (如 "北京市", "朝阳区", "浙江省")。
        with_sub_districts: 是否包含下级行政区边界, 默认 False。

    Returns:
        Dict with status, output_path (Shapefile), total count, and message.
    """
    from shapely.geometry import MultiPolygon

    api_key = os.environ.get("GAODE_API_KEY")
    if not api_key:
        return {"status": "error", "message": "未配置 GAODE_API_KEY，无法获取行政区划边界。请在 .env 中设置高德 API Key。"}

    try:
        # First call: get the target district (+ optional child list)
        # Use subdistrict=2 to handle municipalities (直辖市) where level 1 is a placeholder
        params = {
            "key": api_key,
            "keywords": district_name,
            "subdistrict": "2" if with_sub_districts else "0",
            "extensions": "all",
        }
        resp = requests.get(
            "https://restapi.amap.com/v3/config/district",
            params=params,
            timeout=15,
        )
        data = resp.json()

        if data.get("status") != "1" or not data.get("districts"):
            info = data.get("info", "unknown")
            return {"status": "error", "message": f"行政区划查询失败: {info}"}

        top_district = data["districts"][0]
        records = []

        # Parse the top-level district boundary
        polyline = top_district.get("polyline", "")
        polygons = _parse_amap_polyline(polyline)
        if polygons:
            geom = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
            records.append({
                "name": top_district.get("name", ""),
                "adcode": top_district.get("adcode", ""),
                "level": top_district.get("level", ""),
                "center": top_district.get("center", ""),
                "geometry": geom,
            })

        # If sub-districts requested, collect leaf-level children
        if with_sub_districts and top_district.get("districts"):
            # Flatten: for municipalities (直辖市), level-1 children are placeholders
            # that themselves contain the real districts at level-2
            children_to_fetch = []
            for child in top_district["districts"]:
                grandchildren = child.get("districts", [])
                if grandchildren:
                    # This child is an intermediate level (e.g., "市辖区"); use its children
                    children_to_fetch.extend(grandchildren)
                else:
                    children_to_fetch.append(child)

            for child in children_to_fetch:
                child_polyline = child.get("polyline", "")

                if child_polyline:
                    child_polygons = _parse_amap_polyline(child_polyline)
                else:
                    # Need a separate API call to get child boundary
                    time.sleep(0.1)
                    child_key = child.get("adcode") or child.get("name", "")
                    try:
                        child_resp = requests.get(
                            "https://restapi.amap.com/v3/config/district",
                            params={"key": api_key, "keywords": child_key,
                                    "subdistrict": "0", "extensions": "all"},
                            timeout=15,
                        )
                        child_data = child_resp.json()
                        if child_data.get("status") == "1" and child_data.get("districts"):
                            child_polyline = child_data["districts"][0].get("polyline", "")
                            child_polygons = _parse_amap_polyline(child_polyline)
                        else:
                            child_polygons = []
                    except Exception:
                        child_polygons = []

                if child_polygons:
                    geom = child_polygons[0] if len(child_polygons) == 1 else MultiPolygon(child_polygons)
                    records.append({
                        "name": child.get("name", ""),
                        "adcode": child.get("adcode", ""),
                        "level": child.get("level", ""),
                        "center": child.get("center", ""),
                        "geometry": geom,
                    })

        if not records:
            return {"status": "error", "message": f"未能解析 '{district_name}' 的行政区划边界数据。"}

        gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
        out_path = _generate_output_path("admin_boundary", "shp")
        gdf.to_file(out_path, encoding='utf-8')

        return {
            "status": "success",
            "output_path": out_path,
            "total": len(gdf),
            "message": f"获取到 '{district_name}' 的行政区划边界 ({len(gdf)} 个区划)。",
        }
    except Exception as e:
        return {"status": "error", "message": f"行政区划边界获取异常: {str(e)}"}
