"""
File Management API — upload, browse, delete, preview, local-dir mount.

Endpoints:
  POST   /api/user/files/upload          — multipart file upload (batch)
  GET    /api/user/files/browse           — list files/folders with path navigation
  DELETE /api/user/files/delete           — delete file or folder
  POST   /api/user/files/mkdir            — create subfolder
  GET    /api/user/files/preview/{path}   — spatial/tabular preview metadata
  POST   /api/user/files/download-url     — download file from URL to workspace
  GET    /api/local-data/browse           — browse LOCAL_DATA_DIRS (read-only)
  POST   /api/local-data/import           — copy from local dir into user workspace
"""
import os
import re
import shutil
import uuid
import asyncio
import mimetypes
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

import logging
logger = logging.getLogger("data_agent.api.file_routes")

_UPLOADS_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")

# Shapefile sidecar extensions
_SHP_SIDECARS = {".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml",
                 ".qpj", ".qmd", ".fix"}

# Max upload size per file (200 MB)
_MAX_UPLOAD_SIZE = 200 * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_dir(user) -> str:
    uid = user.identifier if hasattr(user, "identifier") else str(user)
    d = os.path.join(_UPLOADS_BASE, uid)
    os.makedirs(d, exist_ok=True)
    return d


def _safe_join(base: str, subpath: str) -> str | None:
    """Join base + subpath and verify it stays within base. Returns None if escape."""
    joined = os.path.normpath(os.path.join(base, subpath))
    if not joined.startswith(os.path.normpath(base)):
        return None
    return joined


def _scan_dir(dirpath: str, rel_prefix: str = "") -> list[dict]:
    """Scan a directory and return file/folder entries."""
    entries = []
    try:
        for name in sorted(os.listdir(dirpath)):
            full = os.path.join(dirpath, name)
            rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if os.path.isdir(full):
                entries.append({
                    "name": name, "path": rel, "type": "folder",
                    "size": 0, "modified": os.path.getmtime(full),
                })
            elif os.path.isfile(full):
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                # Skip shapefile sidecars (show .shp only)
                if f".{ext}" in _SHP_SIDECARS:
                    continue
                stat = os.stat(full)
                entries.append({
                    "name": name, "path": rel, "type": ext or "file",
                    "size": stat.st_size, "modified": stat.st_mtime,
                })
    except OSError:
        pass
    # Sort: folders first, then by modified time descending (newest first)
    entries.sort(key=lambda e: (0 if e["type"] == "folder" else 1, -e["modified"]))
    return entries


def _group_shapefiles(files: list) -> list:
    """For uploaded files, group .shp/.dbf/.shx/.prj by basename."""
    shp_bases = {}  # basename (no ext) → list of file tuples (filename, content)
    others = []
    for fname, content in files:
        stem, ext = os.path.splitext(fname)
        ext_lower = ext.lower()
        if ext_lower == ".shp" or ext_lower in _SHP_SIDECARS:
            base = stem
            shp_bases.setdefault(base, []).append((fname, content))
        else:
            others.append((fname, content))
    return shp_bases, others


# ---------------------------------------------------------------------------
# POST /api/user/files/upload — multipart batch upload
# ---------------------------------------------------------------------------

async def _api_upload_files(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    base = _user_dir(user)

    form = await request.form()
    # Target subfolder (optional)
    subfolder = form.get("subfolder", "")
    if subfolder:
        target = _safe_join(base, subfolder)
        if not target:
            return JSONResponse({"error": "Invalid subfolder path"}, status_code=400)
        os.makedirs(target, exist_ok=True)
    else:
        target = base

    uploaded = []
    errors = []

    # Collect all files from form
    raw_files = []
    for key in form:
        item = form[key]
        if hasattr(item, "read"):  # UploadFile
            content = await item.read()
            raw_files.append((item.filename or key, content))

    # Group shapefile components
    shp_groups, other_files = _group_shapefiles(raw_files)

    # Save shapefile groups
    for base_name, components in shp_groups.items():
        for fname, content in components:
            if len(content) > _MAX_UPLOAD_SIZE:
                errors.append({"file": fname, "error": f"Exceeds {_MAX_UPLOAD_SIZE // 1024 // 1024}MB limit"})
                continue
            out_path = os.path.join(target, fname)
            with open(out_path, "wb") as f:
                f.write(content)
        # Find the .shp in the group
        shp_name = next((fn for fn, _ in components if fn.lower().endswith(".shp")), None)
        if shp_name:
            uploaded.append({
                "name": shp_name,
                "path": os.path.relpath(os.path.join(target, shp_name), base),
                "size": sum(len(c) for _, c in components),
                "components": len(components),
            })

    # Save other files
    for fname, content in other_files:
        if len(content) > _MAX_UPLOAD_SIZE:
            errors.append({"file": fname, "error": f"Exceeds {_MAX_UPLOAD_SIZE // 1024 // 1024}MB limit"})
            continue
        out_path = os.path.join(target, fname)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(content)
        uploaded.append({
            "name": fname,
            "path": os.path.relpath(out_path, base),
            "size": len(content),
        })

    # Async OBS sync (non-blocking)
    try:
        from ..cloud_storage import get_cloud_adapter
        adapter = get_cloud_adapter()
        if adapter:
            uid = user.identifier if hasattr(user, "identifier") else str(user)
            for item in uploaded:
                full_path = os.path.join(base, item["path"])
                if os.path.isfile(full_path):
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda p=full_path, u=uid: _sync_one(p, u))
    except Exception:
        pass

    return JSONResponse({
        "status": "success",
        "uploaded": uploaded,
        "errors": errors,
        "count": len(uploaded),
    })


def _sync_one(local_path: str, uid: str):
    """Sync a single file to OBS (runs in thread pool)."""
    try:
        from ..gis_processors import sync_to_obs
        sync_to_obs(local_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GET /api/user/files/browse?path=subfolder
# ---------------------------------------------------------------------------

async def _api_browse_files(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    base = _user_dir(user)
    subpath = request.query_params.get("path", "")

    if subpath:
        target = _safe_join(base, subpath)
        if not target or not os.path.isdir(target):
            return JSONResponse({"error": "Directory not found"}, status_code=404)
    else:
        target = base

    entries = _scan_dir(target, subpath)
    return JSONResponse({
        "path": subpath,
        "entries": entries,
        "parent": os.path.dirname(subpath) if subpath else None,
    })


# ---------------------------------------------------------------------------
# DELETE /api/user/files/delete
# ---------------------------------------------------------------------------

async def _api_delete_file(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    filepath = body.get("path", "")
    if not filepath:
        return JSONResponse({"error": "path required"}, status_code=400)

    base = _user_dir(user)
    target = _safe_join(base, filepath)
    if not target:
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    if not os.path.exists(target):
        return JSONResponse({"error": "Not found"}, status_code=404)

    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
        return JSONResponse({"status": "success", "deleted": filepath, "type": "folder"})

    # Delete file + shapefile sidecars if .shp
    deleted = [filepath]
    os.remove(target)
    if target.lower().endswith(".shp"):
        stem = target[:-4]
        for ext in _SHP_SIDECARS:
            sidecar = stem + ext
            if os.path.isfile(sidecar):
                os.remove(sidecar)
                deleted.append(os.path.relpath(sidecar, base))

    return JSONResponse({"status": "success", "deleted": deleted})


# ---------------------------------------------------------------------------
# POST /api/user/files/mkdir
# ---------------------------------------------------------------------------

async def _api_mkdir(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    folder = body.get("path", "").strip()
    if not folder or ".." in folder:
        return JSONResponse({"error": "Invalid folder name"}, status_code=400)

    base = _user_dir(user)
    target = _safe_join(base, folder)
    if not target:
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    os.makedirs(target, exist_ok=True)
    return JSONResponse({"status": "success", "path": folder})


# ---------------------------------------------------------------------------
# GET /api/user/files/preview/{path:path} — spatial/tabular metadata preview
# ---------------------------------------------------------------------------

async def _api_preview_file(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    filepath = request.path_params.get("path", "")
    base = _user_dir(user)
    target = _safe_join(base, filepath)
    if not target or not os.path.isfile(target):
        return JSONResponse({"error": "Not found"}, status_code=404)

    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    info: dict = {
        "name": os.path.basename(filepath),
        "path": filepath,
        "size": os.path.getsize(target),
        "type": ext,
    }

    # Spatial preview
    if ext in ("shp", "geojson", "gpkg", "kml"):
        try:
            import geopandas as gpd
            gdf = gpd.read_file(target, rows=5)
            info["crs"] = str(gdf.crs) if gdf.crs else None
            info["feature_count"] = len(gpd.read_file(target, rows=0).index) if ext != "shp" else "unknown"
            # For shp, count via fiona
            try:
                import fiona
                with fiona.open(target) as src:
                    info["feature_count"] = len(src)
                    info["geometry_type"] = src.schema["geometry"]
                    info["fields"] = [{"name": k, "type": v} for k, v in src.schema["properties"].items()]
            except Exception:
                info["geometry_type"] = str(gdf.geom_type.unique().tolist()) if "geometry" in gdf.columns else None
                info["fields"] = [{"name": c, "type": str(gdf[c].dtype)} for c in gdf.columns if c != "geometry"]
            if gdf.crs and not gdf.is_empty.all():
                bounds = gdf.total_bounds.tolist()
                info["bounds"] = bounds
            info["sample"] = gdf.drop(columns=["geometry"], errors="ignore").head(5).to_dict(orient="records")
        except Exception as e:
            info["preview_error"] = str(e)

    # Raster preview
    elif ext in ("tif", "tiff"):
        try:
            import rasterio
            with rasterio.open(target) as src:
                info["crs"] = str(src.crs) if src.crs else None
                info["bounds"] = list(src.bounds)
                info["shape"] = [src.height, src.width]
                info["bands"] = src.count
                info["dtype"] = str(src.dtypes[0])
                info["nodata"] = src.nodata
                info["resolution"] = [src.res[0], src.res[1]]
        except Exception as e:
            info["preview_error"] = str(e)

    # Tabular preview (CSV/Excel)
    elif ext in ("csv", "xlsx", "xls"):
        try:
            import pandas as pd
            if ext == "csv":
                df = pd.read_csv(target, nrows=10, encoding_errors="replace")
            else:
                df = pd.read_excel(target, nrows=10)
            info["columns"] = [{"name": c, "type": str(df[c].dtype)} for c in df.columns]
            info["row_count_preview"] = len(df)
            info["sample"] = df.head(5).fillna("").to_dict(orient="records")
        except Exception as e:
            info["preview_error"] = str(e)

    return JSONResponse(info)


# ---------------------------------------------------------------------------
# POST /api/user/files/download-url — download from URL
# ---------------------------------------------------------------------------

async def _api_download_url(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    url = body.get("url", "").strip()
    subfolder = body.get("subfolder", "")

    if not url or not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "Valid HTTP(S) URL required"}, status_code=400)

    base = _user_dir(user)
    target_dir = _safe_join(base, subfolder) if subfolder else base
    if not target_dir:
        return JSONResponse({"error": "Invalid subfolder"}, status_code=400)
    os.makedirs(target_dir, exist_ok=True)

    # Extract filename from URL
    from urllib.parse import urlparse, unquote
    parsed = urlparse(url)
    filename = unquote(os.path.basename(parsed.path)) or f"download_{uuid.uuid4().hex[:8]}"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            out_path = os.path.join(target_dir, filename)
            with open(out_path, "wb") as f:
                f.write(resp.content)

            return JSONResponse({
                "status": "success",
                "name": filename,
                "path": os.path.relpath(out_path, base),
                "size": len(resp.content),
            })
    except Exception as e:
        return JSONResponse({"error": f"Download failed: {e}"}, status_code=500)


# ---------------------------------------------------------------------------
# LOCAL_DATA_DIRS — read-only browse of admin-configured local directories
# ---------------------------------------------------------------------------

def _get_local_data_dirs() -> list[dict]:
    """Parse LOCAL_DATA_DIRS env var. Format: 'label1:path1,label2:path2' or just 'path1,path2'."""
    raw = os.environ.get("LOCAL_DATA_DIRS", "")
    if not raw.strip():
        return []
    dirs = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry and not entry[1] == ":":
            # label:path format (but not Windows drive letter like C:)
            label, path = entry.split(":", 1)
        elif len(entry) > 2 and entry[1] == ":" and ":" in entry[2:]:
            # Windows: D:\path:label
            # Find the last colon that's not a drive letter
            parts = entry.rsplit(":", 1)
            if len(parts) == 2 and not parts[1].startswith(("\\", "/")):
                path, label = parts
            else:
                path, label = entry, os.path.basename(entry.rstrip("/\\"))
        else:
            path = entry
            label = os.path.basename(entry.rstrip("/\\")) or entry
        path = path.strip()
        label = label.strip()
        if os.path.isdir(path):
            dirs.append({"label": label, "path": path})
    return dirs


async def _api_browse_local_data(request: Request):
    """GET /api/local-data/browse?root=index&path=subfolder"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    dirs = _get_local_data_dirs()
    if not dirs:
        return JSONResponse({
            "configured": False,
            "message": "No LOCAL_DATA_DIRS configured. Set environment variable to enable.",
            "roots": [],
        })

    root_idx = request.query_params.get("root", "")
    subpath = request.query_params.get("path", "")

    # No root selected → return list of configured roots
    if root_idx == "":
        return JSONResponse({
            "configured": True,
            "roots": [{"index": i, "label": d["label"], "path": d["path"]} for i, d in enumerate(dirs)],
        })

    try:
        idx = int(root_idx)
        root = dirs[idx]
    except (ValueError, IndexError):
        return JSONResponse({"error": "Invalid root index"}, status_code=400)

    base = root["path"]
    if subpath:
        target = _safe_join(base, subpath)
        if not target or not os.path.isdir(target):
            return JSONResponse({"error": "Directory not found"}, status_code=404)
    else:
        target = base

    entries = _scan_dir(target, subpath)
    return JSONResponse({
        "configured": True,
        "root": {"index": idx, "label": root["label"]},
        "path": subpath,
        "parent": os.path.dirname(subpath) if subpath else None,
        "entries": entries,
    })


# ---------------------------------------------------------------------------
# POST /api/local-data/import — copy from local dir into user workspace
# ---------------------------------------------------------------------------

async def _api_import_local_data(request: Request):
    """Copy file(s) from LOCAL_DATA_DIRS into user's upload directory."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    root_idx = body.get("root", 0)
    source_path = body.get("path", "")
    dest_subfolder = body.get("subfolder", "")

    dirs = _get_local_data_dirs()
    try:
        root = dirs[int(root_idx)]
    except (ValueError, IndexError):
        return JSONResponse({"error": "Invalid root index"}, status_code=400)

    src_full = _safe_join(root["path"], source_path)
    if not src_full or not os.path.exists(src_full):
        return JSONResponse({"error": "Source not found"}, status_code=404)

    base = _user_dir(user)
    dest_dir = _safe_join(base, dest_subfolder) if dest_subfolder else base
    if not dest_dir:
        return JSONResponse({"error": "Invalid destination"}, status_code=400)
    os.makedirs(dest_dir, exist_ok=True)

    imported = []
    if os.path.isfile(src_full):
        # Single file — also copy shapefile sidecars
        fname = os.path.basename(src_full)
        shutil.copy2(src_full, os.path.join(dest_dir, fname))
        imported.append(fname)
        # Copy sidecars if shapefile
        if fname.lower().endswith(".shp"):
            stem = os.path.splitext(src_full)[0]
            for ext in _SHP_SIDECARS:
                sidecar = stem + ext
                if os.path.isfile(sidecar):
                    shutil.copy2(sidecar, os.path.join(dest_dir, os.path.basename(sidecar)))
                    imported.append(os.path.basename(sidecar))
    elif os.path.isdir(src_full):
        # Copy entire directory
        dest_target = os.path.join(dest_dir, os.path.basename(src_full))
        if os.path.exists(dest_target):
            shutil.rmtree(dest_target)
        shutil.copytree(src_full, dest_target)
        imported.append(os.path.basename(src_full) + "/")

    return JSONResponse({
        "status": "success",
        "imported": imported,
        "count": len(imported),
    })


# ---------------------------------------------------------------------------
# POST /api/data/import-postgis — import spatial file into PostGIS
# ---------------------------------------------------------------------------

async def _api_import_postgis(request: Request):
    """Import a spatial file from user workspace into PostGIS."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    filepath = body.get("path", "")
    table_name = body.get("table_name", "")
    target_crs = body.get("crs", "")  # e.g., "EPSG:4326"

    if not filepath:
        return JSONResponse({"error": "path required"}, status_code=400)

    base = _user_dir(user)
    target = _safe_join(base, filepath)
    if not target or not os.path.isfile(target):
        return JSONResponse({"error": "File not found"}, status_code=404)

    ext = filepath.rsplit(".", 1)[-1].lower() if "." in filepath else ""
    if ext not in ("shp", "geojson", "gpkg", "kml", "csv", "xlsx"):
        return JSONResponse({"error": f"Unsupported format: {ext}"}, status_code=400)

    try:
        import geopandas as gpd
        import pandas as pd
        from sqlalchemy import text

        # Load data
        if ext in ("csv", "xlsx"):
            df = pd.read_csv(target) if ext == "csv" else pd.read_excel(target)
            # Try to detect coordinate columns
            lon_col = next((c for c in df.columns if c.lower() in ("lon", "lng", "longitude", "x", "经度")), None)
            lat_col = next((c for c in df.columns if c.lower() in ("lat", "latitude", "y", "纬度")), None)
            if lon_col and lat_col:
                from shapely.geometry import Point
                geometry = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
                gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
            else:
                # No geometry — import as regular table
                from ..db_engine import get_engine
                engine = get_engine()
                if not engine:
                    return JSONResponse({"error": "Database not available"}, status_code=500)
                tname = table_name or f"import_{uuid.uuid4().hex[:8]}"
                df.to_sql(tname, engine, if_exists="replace", index=False)
                return JSONResponse({
                    "status": "success",
                    "table_name": tname,
                    "row_count": len(df),
                    "has_geometry": False,
                })
        else:
            gdf = gpd.read_file(target)

        # Reproject if requested
        if target_crs and gdf.crs and str(gdf.crs) != target_crs:
            gdf = gdf.to_crs(target_crs)

        # Generate table name
        tname = table_name or f"import_{uuid.uuid4().hex[:8]}"

        # Import to PostGIS
        from ..db_engine import get_engine
        engine = get_engine()
        if not engine:
            return JSONResponse({"error": "Database not available"}, status_code=500)

        gdf.to_postgis(tname, engine, if_exists="replace", index=False)

        # Register in data catalog
        try:
            from ..data_catalog import auto_register_from_path
            auto_register_from_path(
                target, creation_tool="import_postgis",
                storage_backend="postgis", postgis_table=tname,
            )
        except Exception:
            pass

        return JSONResponse({
            "status": "success",
            "table_name": tname,
            "row_count": len(gdf),
            "crs": str(gdf.crs) if gdf.crs else None,
            "has_geometry": True,
        })
    except Exception as e:
        logger.warning("PostGIS import failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Route Registration
# ---------------------------------------------------------------------------

def get_file_routes() -> list[Route]:
    return [
        Route("/api/user/files/upload", endpoint=_api_upload_files, methods=["POST"]),
        Route("/api/user/files/browse", endpoint=_api_browse_files, methods=["GET"]),
        Route("/api/user/files/delete", endpoint=_api_delete_file, methods=["DELETE"]),
        Route("/api/user/files/mkdir", endpoint=_api_mkdir, methods=["POST"]),
        Route("/api/user/files/preview/{path:path}", endpoint=_api_preview_file, methods=["GET"]),
        Route("/api/user/files/download-url", endpoint=_api_download_url, methods=["POST"]),
        Route("/api/local-data/browse", endpoint=_api_browse_local_data, methods=["GET"]),
        Route("/api/local-data/import", endpoint=_api_import_local_data, methods=["POST"]),
        Route("/api/data/import-postgis", endpoint=_api_import_postgis, methods=["POST"]),
    ]
