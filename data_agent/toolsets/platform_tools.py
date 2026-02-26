"""Platform toolset: memory, token tracking, file management."""
import os

from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..memory import save_memory, recall_memories, list_memories, delete_memory
from ..token_tracker import get_usage_summary
from ..audit_logger import query_audit_log
from ..template_manager import list_templates, delete_template, share_template


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
        target = os.path.normpath(target)
        if not target.startswith(os.path.normpath(user_dir)):
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
# Toolset class
# ---------------------------------------------------------------------------

_ALL_FUNCS = [
    list_user_files,
    delete_user_file,
    save_memory,
    recall_memories,
    list_memories,
    delete_memory,
    get_usage_summary,
    query_audit_log,
    list_templates,
    delete_template,
    share_template,
]


class PlatformToolset(BaseToolset):
    """Memory, token tracking, and file management tools."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _ALL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
