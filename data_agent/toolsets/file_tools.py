"""File management toolset: list, delete, and convert user files."""
import asyncio
import json
import os
import traceback

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

def list_user_files() -> str:
    """
    列出当前用户上传和生成的所有文件（本地 + 云端）。
    Returns:
        文件列表，包含文件名、大小和存储位置标签。
    """
    try:
        from ..user_context import get_user_upload_dir, current_user_id
        user_dir = get_user_upload_dir()

        local_files = {}
        if os.path.exists(user_dir):
            for f in sorted(os.listdir(user_dir)):
                fp = os.path.join(user_dir, f)
                if os.path.isfile(fp):
                    local_files[f] = os.path.getsize(fp) / 1024

        cloud_files = {}
        try:
            from ..obs_storage import is_obs_configured, list_user_objects
            if is_obs_configured():
                uid = current_user_id.get()
                for obj in list_user_objects(uid):
                    cloud_files[obj["filename"]] = obj["size"] / 1024
        except Exception:
            pass

        all_filenames = sorted(set(list(local_files.keys()) + list(cloud_files.keys())))
        if not all_filenames:
            return "您的文件目录为空。"

        lines = []
        for fname in all_filenames:
            in_local = fname in local_files
            in_cloud = fname in cloud_files
            size_kb = local_files.get(fname) or cloud_files.get(fname, 0)
            size_str = f"{size_kb/1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"

            if in_local and in_cloud:
                tag = ""
            elif in_cloud and not in_local:
                tag = " [云端]"
            else:
                tag = " [仅本地]"

            lines.append(f"- {fname} ({size_str}){tag}")

        return f"共 {len(lines)} 个文件：\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {str(e)}"


def delete_user_file(file_name: str) -> str:
    """
    删除当前用户目录中的指定文件（本地 + 云端）。仅允许删除用户自己的文件。

    Args:
        file_name: 要删除的文件名（不含路径），如 'query_result_abc123.csv'。
    Returns:
        删除结果消息。
    """
    try:
        from ..user_context import get_user_upload_dir, current_user_id
        user_dir = get_user_upload_dir()
        target = os.path.join(user_dir, file_name)
        
        # Security: prevent path traversal (e.g. "../other_user/file")
        real_user_dir = os.path.realpath(user_dir)
        real_target = os.path.realpath(target)
        if not real_target.startswith(real_user_dir + os.sep) and real_target != real_user_dir:
            return "安全限制：不允许访问用户目录以外的文件。"

        deleted_local = False
        if os.path.exists(target):
            os.remove(target)
            deleted_local = True
            base, ext = os.path.splitext(file_name)
            if ext.lower() == '.shp':
                for sidecar_ext in ['.cpg', '.dbf', '.prj', '.shx', '.sbn', '.sbx', '.shp.xml']:
                    sidecar = os.path.join(user_dir, base + sidecar_ext)
                    if os.path.exists(sidecar):
                        os.remove(sidecar)

        deleted_cloud = False
        try:
            from ..obs_storage import is_obs_configured, delete_from_obs, delete_shapefile_bundle_from_obs
            if is_obs_configured():
                uid = current_user_id.get()
                s3_key = f"{uid}/{file_name}"
                _, ext = os.path.splitext(file_name)
                if ext.lower() == '.shp':
                    count = delete_shapefile_bundle_from_obs(s3_key)
                    deleted_cloud = count > 0
                else:
                    deleted_cloud = delete_from_obs(s3_key)
        except Exception:
            pass

        try:
            from ..audit_logger import record_audit, ACTION_FILE_DELETE
            record_audit(
                current_user_id.get(), ACTION_FILE_DELETE,
                status="success" if (deleted_local or deleted_cloud) else "failure",
                details={"file_name": file_name},
            )
        except Exception:
            pass

        if deleted_local and deleted_cloud:
            return f"文件 '{file_name}' 已从本地和云端删除。"
        elif deleted_local:
            return f"文件 '{file_name}' 已从本地删除。"
        elif deleted_cloud:
            return f"文件 '{file_name}' 已从云端删除。"
        else:
            return f"文件 '{file_name}' 不存在。"
    except Exception as e:
        return f"Error deleting file: {str(e)}"


# ---------------------------------------------------------------------------
# Format conversion tools
# ---------------------------------------------------------------------------

async def convert_format(
    file_path: str,
    output_format: str = "geojson",
    layer_name: str = "",
) -> str:
    """将空间数据格式转换为 GeoJSON、Shapefile 或 GeoPackage。支持 GDB 多图层导出。

    Args:
        file_path: 输入文件路径。支持 .gdb（Esri File Geodatabase）、.shp、.geojson、.gpkg、.kml 等。
        output_format: 输出格式 (geojson/shp/gpkg)，默认 geojson。
        layer_name: GDB 指定图层名称。留空则导出所有图层（多图层时每层一个文件）。
                   非 GDB 格式忽略此参数。

    Returns:
        转换结果 JSON，含输出路径、记录数和字段列表。多图层时返回文件列表。
    """
    def _run():
        import geopandas as gpd
        from ..gis_processors import _resolve_path, _generate_output_path

        resolved = _resolve_path(file_path)
        ext = os.path.splitext(resolved)[1].lower()
        is_gdb = ext == ".gdb" or (
            os.path.isdir(resolved)
            and any(f.endswith(".gdbtable") for f in os.listdir(resolved) if os.path.isfile(os.path.join(resolved, f)))
        )

        driver_map = {"geojson": "GeoJSON", "shp": "ESRI Shapefile", "gpkg": "GPKG"}
        driver = driver_map.get(output_format.lower(), "GeoJSON")
        out_ext = {"geojson": "geojson", "shp": "shp", "gpkg": "gpkg"}.get(
            output_format.lower(), "geojson"
        )

        if is_gdb:
            import fiona
            all_layers = fiona.listlayers(resolved)
            if not all_layers:
                return {"status": "error", "message": f"GDB 为空: {resolved}"}

            if layer_name:
                if layer_name not in all_layers:
                    return {
                        "status": "error",
                        "message": f"图层 '{layer_name}' 不存在。可用图层: {all_layers}",
                    }
                layers_to_export = [layer_name]
            else:
                layers_to_export = all_layers

            outputs = []
            for lyr in layers_to_export:
                gdf = gpd.read_file(resolved, layer=lyr)
                safe_name = lyr.replace(" ", "_").replace("/", "_")[:50]
                out_path = _generate_output_path(f"gdb_{safe_name}", out_ext)
                gdf.to_file(out_path, driver=driver)
                outputs.append({
                    "layer": lyr,
                    "output_path": out_path,
                    "rows": len(gdf),
                    "columns": [c for c in gdf.columns if c != "geometry"],
                    "geometry_type": gdf.geom_type.iloc[0] if len(gdf) > 0 else None,
                    "crs": str(gdf.crs) if gdf.crs else None,
                })

            return {
                "status": "ok",
                "source": os.path.basename(resolved),
                "total_layers": len(all_layers),
                "exported_layers": len(outputs),
                "outputs": outputs,
            }
        else:
            # Non-GDB: simple format conversion
            gdf = gpd.read_file(resolved)
            out_path = _generate_output_path("converted", out_ext)
            gdf.to_file(out_path, driver=driver)
            return {
                "status": "ok",
                "source": os.path.basename(resolved),
                "output_path": out_path,
                "rows": len(gdf),
                "columns": [c for c in gdf.columns if c != "geometry"],
                "geometry_type": gdf.geom_type.iloc[0] if len(gdf) > 0 else None,
                "crs": str(gdf.crs) if gdf.crs else None,
                "format": output_format,
            }

    try:
        result = await asyncio.to_thread(_run)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        traceback.print_exc()
        return json.dumps({"status": "error", "message": str(e)})


# ---------------------------------------------------------------------------
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [list_user_files, delete_user_file, convert_format]


class FileToolset(BaseToolset):
    """User file listing and deletion tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
