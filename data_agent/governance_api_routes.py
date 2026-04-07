"""
产品化 REST API — 治理场景专用端点

精简版 API，只包含 Phase 1 需要的端点。
复用原型的认证机制（JWT cookie auth）。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import geopandas as gpd
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logger = logging.getLogger(__name__)

UPLOADS_BASE = os.path.join(os.path.dirname(__file__), "uploads")

# 简易的 dataset 注册表（Phase 1 用内存，Phase 2 用 DB）
_datasets: dict[str, dict] = {}
_ds_counter = 0


def _get_user_from_request(request: Request):
    """复用原型的 JWT 认证。"""
    try:
        from data_agent.auth import get_user_from_request
        return get_user_from_request(request)
    except Exception:
        return None


def _get_user_id(request: Request) -> str:
    user = _get_user_from_request(request)
    if user and hasattr(user, "identifier"):
        return user.identifier
    return "admin"


# ---------------------------------------------------------------------------
# POST /api/v1/upload — 上传文件并注册为 dataset
# ---------------------------------------------------------------------------

async def api_upload(request: Request) -> JSONResponse:
    """上传数据文件，自动识别格式，注册为 dataset。"""
    global _ds_counter

    user_id = _get_user_id(request)
    user_dir = os.path.join(UPLOADS_BASE, user_id)
    os.makedirs(user_dir, exist_ok=True)

    form = await request.form()
    upload = form.get("file")
    if not upload:
        return JSONResponse({"error": "No file in form data"}, status_code=400)

    filename = getattr(upload, "filename", "upload")
    contents = await upload.read()

    dest_path = os.path.join(user_dir, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    # ZIP 解压（复用原型的逻辑）
    ext = os.path.splitext(filename)[1].lower()
    result_path = os.path.abspath(dest_path)
    if ext == ".zip":
        import zipfile
        extract_dir = os.path.join(user_dir, os.path.splitext(filename)[0])
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(dest_path, "r") as zr:
                zr.extractall(extract_dir)
            for target_ext in (".shp", ".geojson", ".json", ".gpkg"):
                for root, _, files in os.walk(extract_dir):
                    for fname in files:
                        if fname.lower().endswith(target_ext):
                            result_path = os.path.abspath(os.path.join(root, fname))
                            break
        except Exception as e:
            logger.warning("ZIP extraction failed: %s", e)

    # 读取空间数据基本信息
    try:
        gdf = gpd.read_file(result_path)
        info = {
            "record_count": len(gdf),
            "crs": str(gdf.crs) if gdf.crs else "未知",
            "geometry_type": list(gdf.geometry.geom_type.unique()) if not gdf.geometry.isna().all() else [],
            "columns": [c for c in gdf.columns if c != "geometry"],
            "column_count": len(gdf.columns) - 1,
            "bounds": list(gdf.total_bounds) if not gdf.geometry.isna().all() else None,
        }
    except Exception as e:
        info = {"error": f"读取空间数据失败: {e}"}

    # 注册 dataset
    _ds_counter += 1
    ds_id = f"ds-{_ds_counter:04d}"
    _datasets[ds_id] = {
        "id": ds_id,
        "filename": filename,
        "file_path": result_path,
        "user_id": user_id,
        "info": info,
    }

    return JSONResponse({
        "dataset_id": ds_id,
        "filename": filename,
        "file_path": result_path,
        **info,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/datasets/{id}/profile — 数据画像
# ---------------------------------------------------------------------------

async def api_dataset_profile(request: Request) -> JSONResponse:
    """获取数据集的基本信息和字段详情。"""
    ds_id = request.path_params["id"]
    ds = _datasets.get(ds_id)
    if not ds:
        return JSONResponse({"error": f"Dataset {ds_id} not found"}, status_code=404)

    try:
        gdf = gpd.read_file(ds["file_path"])
        fields = []
        for col in gdf.columns:
            if col == "geometry":
                continue
            non_null = int(gdf[col].notna().sum())
            sample = str(gdf[col].dropna().iloc[0])[:100] if non_null > 0 else ""
            fields.append({
                "name": col,
                "dtype": str(gdf[col].dtype),
                "non_null": non_null,
                "total": len(gdf),
                "null_rate": round(1 - non_null / len(gdf), 4) if len(gdf) > 0 else 0,
                "sample": sample,
            })

        return JSONResponse({
            "dataset_id": ds_id,
            "filename": ds["filename"],
            "record_count": len(gdf),
            "crs": str(gdf.crs) if gdf.crs else "未知",
            "geometry_type": list(gdf.geometry.geom_type.unique()),
            "bounds": list(gdf.total_bounds),
            "fields": fields,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/v1/datasets/{id}/geojson — 返回 GeoJSON 供地图渲染
# ---------------------------------------------------------------------------

async def api_dataset_geojson(request: Request) -> Response:
    """返回数据集的 GeoJSON，供前端地图渲染。"""
    ds_id = request.path_params["id"]
    ds = _datasets.get(ds_id)
    if not ds:
        return JSONResponse({"error": f"Dataset {ds_id} not found"}, status_code=404)

    try:
        gdf = gpd.read_file(ds["file_path"])
        # 转换为 WGS84 供 Leaflet 渲染
        if gdf.crs and not gdf.crs.is_geographic:
            gdf = gdf.to_crs(epsg=4326)
        elif not gdf.crs:
            gdf = gdf.set_crs(epsg=4326, allow_override=True)

        geojson_str = gdf.to_json(ensure_ascii=False)
        return Response(content=geojson_str, media_type="application/geo+json")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/v1/datasets/{id}/match — 标准对照分析
# ---------------------------------------------------------------------------

async def api_dataset_match(request: Request) -> JSONResponse:
    """执行标准对照分析，返回匹配结果和差距报告。"""
    ds_id = request.path_params["id"]
    ds = _datasets.get(ds_id)
    if not ds:
        return JSONResponse({"error": f"Dataset {ds_id} not found"}, status_code=404)

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    target_table = body.get("standard_table", "DLTB")

    try:
        from data_agent.intelligence.tools import check_compliance
        result = check_compliance(ds["file_path"], target_table)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# POST /api/v1/datasets/{id}/advise — 模型调整建议
# ---------------------------------------------------------------------------

async def api_dataset_advise(request: Request) -> JSONResponse:
    """生成模型调整建议。"""
    ds_id = request.path_params["id"]
    ds = _datasets.get(ds_id)
    if not ds:
        return JSONResponse({"error": f"Dataset {ds_id} not found"}, status_code=404)

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    target_table = body.get("standard_table", "DLTB")

    try:
        from data_agent.intelligence.tools import advise_model
        result = advise_model(ds["file_path"], target_table)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/v1/datasets/{id}/report — 生成并下载报告
# ---------------------------------------------------------------------------

async def api_dataset_report(request: Request) -> Response:
    """生成治理分析报告并返回下载。"""
    ds_id = request.path_params["id"]
    ds = _datasets.get(ds_id)
    if not ds:
        return JSONResponse({"error": f"Dataset {ds_id} not found"}, status_code=404)

    try:
        from data_agent.intelligence.tools import generate_report
        result = generate_report(ds["file_path"])
        report_path = result["report_path"]

        with open(report_path, "rb") as f:
            content = f.read()

        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{Path(report_path).name}"'},
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# GET /api/v1/datasets — 列出所有 dataset
# ---------------------------------------------------------------------------

async def api_list_datasets(request: Request) -> JSONResponse:
    """列出当前用户的所有数据集。"""
    user_id = _get_user_id(request)
    user_datasets = [
        {k: v for k, v in ds.items() if k != "file_path"}
        for ds in _datasets.values()
        if ds.get("user_id") == user_id
    ]
    return JSONResponse({"datasets": user_datasets})


# ---------------------------------------------------------------------------
# 路由注册
# ---------------------------------------------------------------------------

GOVERNANCE_ROUTES = [
    Route("/api/v1/upload", endpoint=api_upload, methods=["POST"]),
    Route("/api/v1/datasets", endpoint=api_list_datasets, methods=["GET"]),
    Route("/api/v1/datasets/{id}/profile", endpoint=api_dataset_profile, methods=["GET"]),
    Route("/api/v1/datasets/{id}/geojson", endpoint=api_dataset_geojson, methods=["GET"]),
    Route("/api/v1/datasets/{id}/match", endpoint=api_dataset_match, methods=["POST"]),
    Route("/api/v1/datasets/{id}/advise", endpoint=api_dataset_advise, methods=["POST"]),
    Route("/api/v1/datasets/{id}/report", endpoint=api_dataset_report, methods=["GET"]),
]


def mount_governance_api(app):
    """将治理 API 路由挂载到 Chainlit/Starlette app。

    复用原型的路由挂载模式：在 Chainlit catch-all 之前插入。
    """
    for i, route in enumerate(app.router.routes):
        path = getattr(route, "path", "")
        if path == "/{path:path}":
            for j, gov_route in enumerate(GOVERNANCE_ROUTES):
                app.router.routes.insert(i + j, gov_route)
            logger.info("Mounted %d governance API routes", len(GOVERNANCE_ROUTES))
            return

    app.router.routes.extend(GOVERNANCE_ROUTES)
    logger.info("Appended %d governance API routes", len(GOVERNANCE_ROUTES))
