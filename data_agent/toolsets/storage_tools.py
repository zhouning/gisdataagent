"""
StorageToolset — Agent tools for data lake operations.

Exposes cloud/lake storage to the AI Agent so it can:
- Browse cloud storage contents
- Upload local files to the data lake
- Download cloud files to workspace
- Get storage system info
"""
import os
from google.adk.tools import FunctionTool

from ..gis_processors import _resolve_path
from ..user_context import get_user_upload_dir, current_user_id
from ..observability import get_logger
from google.adk.tools.base_toolset import BaseToolset

logger = get_logger("storage_tools")


def list_lake_assets(prefix: str = "", limit: int = 50) -> str:
    """
    [Storage Tool] List files in the data lake (cloud storage).

    Shows all files stored in the S3/OBS data lake, optionally filtered by prefix.
    Returns file names, sizes, and URIs for use in subsequent analysis.

    Args:
        prefix: Filter by key prefix (e.g., 'admin/' for admin's files).
        limit: Maximum number of results.

    Returns:
        Formatted list of lake assets with URIs.
    """
    from ..storage_manager import get_storage_manager
    sm = get_storage_manager()

    if not sm.cloud_available:
        return "数据湖 (S3/OBS) 未配置。当前仅使用本地存储。"

    uid = current_user_id.get()
    search_prefix = prefix or ""
    objects = sm.list_objects(search_prefix, user_id=uid if not prefix else None)

    if not objects:
        return f"数据湖中无匹配文件 (前缀: '{search_prefix}')"

    objects = objects[:limit]
    lines = [f"数据湖文件 ({len(objects)} 个):"]
    for obj in objects:
        size_kb = obj["size"] / 1024 if obj["size"] else 0
        size_str = f"{size_kb:.0f}KB" if size_kb < 1024 else f"{size_kb / 1024:.1f}MB"
        lines.append(f"  {obj['filename']}  ({size_str})  URI: {obj['uri']}")
    return "\n".join(lines)


def upload_to_lake(file_path: str) -> str:
    """
    [Storage Tool] Upload a local file to the data lake (S3/OBS).

    Copies a file from the user's workspace to cloud storage for persistent
    storage and sharing.

    Args:
        file_path: Local file path to upload.

    Returns:
        Cloud URI (s3://...) of the uploaded file, or error message.
    """
    from ..storage_manager import get_storage_manager
    sm = get_storage_manager()

    if not sm.cloud_available:
        return "数据湖 (S3/OBS) 未配置。"

    resolved = _resolve_path(file_path)
    if not os.path.isfile(resolved):
        return f"文件不存在: {file_path}"

    uid = current_user_id.get()
    uri = sm.store(resolved, user_id=uid)
    size_mb = os.path.getsize(resolved) / (1024 * 1024)
    return f"已上传到数据湖:\n  文件: {os.path.basename(resolved)} ({size_mb:.1f}MB)\n  URI: {uri}"


def download_from_lake(lake_uri: str) -> str:
    """
    [Storage Tool] Download a file from the data lake to the local workspace.

    Retrieves a file from S3/OBS cloud storage and saves it to the user's
    local workspace for analysis.

    Args:
        lake_uri: Cloud URI (s3://bucket/key) of the file to download.

    Returns:
        Local file path of the downloaded file.
    """
    from ..storage_manager import get_storage_manager
    sm = get_storage_manager()

    local_path = sm.resolve(lake_uri)
    if os.path.isfile(local_path):
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        return f"已下载到本地:\n  路径: {local_path}\n  大小: {size_mb:.1f}MB"
    return f"下载失败: {lake_uri}"


def get_storage_info() -> str:
    """
    [Storage Tool] Get storage system status and configuration.

    Shows the current storage backend configuration, cloud connectivity,
    cache status, and available space.

    Returns:
        Storage system status report.
    """
    from ..storage_manager import get_storage_manager
    sm = get_storage_manager()
    info = sm.get_info()

    lines = ["存储系统状态:"]
    lines.append(f"  默认后端: {info['default_backend']}")
    lines.append(f"  云存储: {'已连接' if info['cloud_available'] else '未配置'}")
    if info["cloud_bucket"]:
        lines.append(f"  Bucket: {info['cloud_bucket']}")
    lines.append(f"  本地缓存: {info['cache_dir']} ({info['cache_size_mb']}MB)")

    # Local workspace info
    user_dir = get_user_upload_dir()
    local_files = sum(1 for _, _, files in os.walk(user_dir) for _ in files)
    local_size = sum(
        os.path.getsize(os.path.join(r, f))
        for r, _, files in os.walk(user_dir) for f in files
    ) / (1024 * 1024)
    lines.append(f"  本地工作区: {local_files} 文件 ({local_size:.1f}MB)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Toolset Registration
# ---------------------------------------------------------------------------

class StorageToolset(BaseToolset):
    """Data lake storage tools for Agent."""

    name = "StorageToolset"
    description = "数据湖存储工具：浏览、上传、下载云存储文件"
    category = "data_management"

    def get_tools(self):
        return [
            FunctionTool(list_lake_assets),
            FunctionTool(upload_to_lake),
            FunctionTool(download_from_lake),
            FunctionTool(get_storage_info),
        ]
