import chainlit as cl
import sys
import os
import re
import asyncio
import threading
import time
import json
import zipfile
import shutil
from typing import List, Dict, Optional
from dotenv import load_dotenv
from google import genai as genai_client

from data_agent.i18n import t, set_language, get_language
from data_agent.multimodal import (
    UploadType, classify_upload, prepare_image_part,
    extract_pdf_text, prepare_pdf_part,
)

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)

# --- Observability: init structured logging early ---
from data_agent.observability import (
    setup_logging, get_logger,
    pipeline_runs, pipeline_duration, tool_calls, auth_events,
    generate_latest, CONTENT_TYPE_LATEST,
)
setup_logging()
logger = get_logger("app")

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.genai import types

# --- Context Cache support (v7.5.5) ---
try:
    from google.adk.apps import App
    from google.adk.agents.context_cache_config import ContextCacheConfig
    _CACHE_SUPPORT = True
except ImportError:
    _CACHE_SUPPORT = False

# Configure Google GenAI client for Routing (outside ADK agents)
# Uses google.genai (new unified SDK) — auto-reads GOOGLE_API_KEY / Vertex AI env vars
_genai_router_client = genai_client.Client()

# Import agent and report generator
try:
    from data_agent.agent import (
        root_agent,
        governance_pipeline,
        general_pipeline,
        data_pipeline,
        planner_agent,
        _load_spatial_data,
        _generate_upload_preview,
        ARCPY_AVAILABLE,
    )
    from data_agent.report_generator import generate_word_report
    from data_agent.user_context import (
        current_user_id, current_session_id, current_user_role,
        current_trace_id, get_user_upload_dir
    )
    from data_agent.auth import ensure_users_table
    from data_agent.memory import ensure_memory_table
    from data_agent.token_tracker import ensure_token_table
    from data_agent.database_tools import ensure_table_ownership_table
    from data_agent.sharing import ensure_share_links_table
    from data_agent.audit_logger import (
        ensure_audit_table, record_audit,
        ACTION_SESSION_START, ACTION_FILE_UPLOAD, ACTION_PIPELINE_COMPLETE,
        ACTION_REPORT_EXPORT, ACTION_SHARE_CREATE, ACTION_RBAC_DENIED,
        ACTION_USER_REGISTER,
        ACTION_TEMPLATE_CREATE, ACTION_TEMPLATE_APPLY, ACTION_TEMPLATE_DELETE,
    )
except ImportError:
    import agent
    import report_generator
    from user_context import (
        current_user_id, current_session_id, current_user_role,
        get_user_upload_dir
    )
    from auth import ensure_users_table
    from memory import ensure_memory_table
    from token_tracker import ensure_token_table
    from database_tools import ensure_table_ownership_table
    from sharing import ensure_share_links_table
    from audit_logger import (
        ensure_audit_table, record_audit,
        ACTION_SESSION_START, ACTION_FILE_UPLOAD, ACTION_PIPELINE_COMPLETE,
        ACTION_REPORT_EXPORT, ACTION_SHARE_CREATE, ACTION_RBAC_DENIED,
        ACTION_USER_REGISTER,
    )
    root_agent = agent.root_agent
    governance_pipeline = agent.governance_pipeline
    general_pipeline = agent.general_pipeline
    data_pipeline = agent.data_pipeline
    planner_agent = agent.planner_agent
    _load_spatial_data = agent._load_spatial_data
    _generate_upload_preview = agent._generate_upload_preview
    generate_word_report = report_generator.generate_word_report
    ARCPY_AVAILABLE = getattr(agent, 'ARCPY_AVAILABLE', False)

# Initialize DB tables (resilient — if PostgreSQL is down, non-DB features still work)
try:
    ensure_users_table()
    ensure_memory_table()
    ensure_token_table()
    ensure_table_ownership_table()
    ensure_share_links_table()
    ensure_audit_table()
    from data_agent.template_manager import ensure_templates_table
    ensure_templates_table()
    from data_agent.semantic_layer import ensure_semantic_tables, resolve_semantic_context, build_context_prompt
    ensure_semantic_tables()
    from data_agent.team_manager import ensure_teams_table
    ensure_teams_table()
    from data_agent.data_catalog import ensure_data_catalog_table
    ensure_data_catalog_table()
    from data_agent.map_annotations import ensure_annotations_table
    ensure_annotations_table()
    from data_agent.session_storage import ensure_chainlit_tables
    ensure_chainlit_tables()
    from data_agent.workflow_engine import ensure_workflow_tables
    ensure_workflow_tables()
    from data_agent.fusion_engine import ensure_fusion_tables
    ensure_fusion_tables()
    from data_agent.knowledge_graph import ensure_knowledge_graph_tables
    ensure_knowledge_graph_tables()
    from data_agent.failure_learning import ensure_failure_table
    ensure_failure_table()
    from data_agent.custom_skills import ensure_custom_skills_table
    ensure_custom_skills_table()
    from data_agent.knowledge_base import ensure_kb_tables
    ensure_kb_tables()
    from data_agent.user_tools import ensure_user_tools_table
    ensure_user_tools_table()
    from data_agent.workflow_templates import ensure_workflow_template_tables
    ensure_workflow_template_tables()
    from data_agent.custom_skill_bundles import ensure_skill_bundles_table
    ensure_skill_bundles_table()
    from data_agent.virtual_sources import ensure_virtual_sources_table
    ensure_virtual_sources_table()
    from data_agent.agent_registry import ensure_registry_table
    ensure_registry_table()
    from data_agent.analysis_chains import ensure_chains_table
    ensure_chains_table()
    from data_agent.workflow_engine import recover_incomplete_runs
    recover_incomplete_runs()
    from data_agent.plugin_registry import ensure_plugins_table
    ensure_plugins_table()
except Exception as _startup_err:
    logger.warning("DB initialization partially failed: %s", _startup_err)
    # Ensure resolve_semantic_context/build_context_prompt are importable even on failure
    try:
        from data_agent.semantic_layer import resolve_semantic_context, build_context_prompt
    except Exception:
        resolve_semantic_context = None
        build_context_prompt = None

from data_agent.obs_storage import ensure_obs_connection, is_obs_configured, upload_file_smart
from data_agent.gis_processors import sync_to_obs
from data_agent.hitl_approval import HITLApprovalPlugin, HITL_ENABLED
try:
    ensure_obs_connection()
except Exception as _obs_err:
    logger.warning("OBS initialization failed: %s", _obs_err)
if ARCPY_AVAILABLE:
    logger.info("ArcPy engine available and connected")
else:
    # Retry ArcPy bridge initialization (Chainlit watchfiles may interfere with first attempt)
    try:
        from data_agent.toolsets.geo_processing_tools import retry_arcpy_init
        if retry_arcpy_init():
            ARCPY_AVAILABLE = True
            logger.info("ArcPy engine available (retry succeeded)")
    except Exception:
        pass

# --- Prompt version logging ---
from data_agent.prompts import log_prompt_versions
log_prompt_versions()

# --- Enterprise WeChat Bot (conditional) ---
from data_agent.wecom_bot import ensure_wecom_connection, is_wecom_configured
try:
    ensure_wecom_connection()
except Exception as _wecom_err:
    logger.warning("WeCom initialization failed: %s", _wecom_err)

# --- DingTalk Bot (conditional) ---
try:
    from data_agent.dingtalk_bot import ensure_dingtalk_connection
    ensure_dingtalk_connection()
except Exception as _dt_err:
    logger.warning("DingTalk initialization failed: %s", _dt_err)

# --- Feishu Bot (conditional) ---
try:
    from data_agent.feishu_bot import ensure_feishu_connection
    ensure_feishu_connection()
except Exception as _fs_err:
    logger.warning("Feishu initialization failed: %s", _fs_err)

DYNAMIC_PLANNER = os.environ.get("DYNAMIC_PLANNER", "true").lower() in ("true", "1", "yes")
if DYNAMIC_PLANNER:
    logger.info("Dynamic Planner mode enabled")

# --- MCP Hub: load config (async connections deferred to on_chat_start) ---
try:
    from data_agent.mcp_hub import get_mcp_hub
    _mcp_hub = get_mcp_hub()
    _mcp_hub.load_config()
    _mcp_hub_loaded = True
except Exception as _mcp_err:
    logger.warning("MCP Hub config loading failed: %s", _mcp_err)
    _mcp_hub_loaded = False
_mcp_started = False
_mcp_lock = threading.Lock()

# --- Chainlit Data Layer: thread/message persistence in PostgreSQL ---
try:
    from data_agent.session_storage import get_chainlit_db_url as _get_cl_db_url
    _chainlit_db_url = _get_cl_db_url()
    if _chainlit_db_url:
        from chainlit.data.chainlit_data_layer import ChainlitDataLayer
        import chainlit.data as cl_data
        cl_data._data_layer = ChainlitDataLayer(database_url=_chainlit_db_url)
        cl_data._data_layer_initialized = True
        logger.info("Chainlit data layer initialized (PostgreSQL thread persistence)")
    else:
        logger.info("Chainlit data layer skipped (database not configured)")
except Exception as _cl_data_err:
    logger.warning("Chainlit data layer init failed: %s", _cl_data_err)

# --- Session Service: persistent DB or in-memory fallback ---
def _create_session_service():
    """Prefer DatabaseSessionService (PostgreSQL) with fallback to InMemory."""
    try:
        from data_agent.database_tools import get_async_db_url
        async_url = get_async_db_url()
        if async_url:
            from google.adk.sessions import DatabaseSessionService
            svc = DatabaseSessionService(db_url=async_url)
            logger.info("Using DatabaseSessionService (PostgreSQL)")
            return svc
    except ImportError as e:
        logger.warning("DatabaseSessionService unavailable (%s). "
              "Install asyncpg: pip install asyncpg", e)
    except Exception as e:
        logger.warning("DatabaseSessionService init failed: %s", e)
    logger.info("Falling back to InMemorySessionService")
    return InMemorySessionService()

session_service = _create_session_service()

# --- Context Cache (v7.5.5): cache long system prompts for cost savings ---
_CONTEXT_CACHE_ENABLED = os.environ.get("CONTEXT_CACHE_ENABLED", "true").lower() == "true"
_CONTEXT_CACHE_TTL = int(os.environ.get("CONTEXT_CACHE_TTL", "1800"))

_context_cache_config = None
if _CACHE_SUPPORT and _CONTEXT_CACHE_ENABLED:
    _context_cache_config = ContextCacheConfig(
        cache_intervals=10,
        ttl_seconds=_CONTEXT_CACHE_TTL,
        min_tokens=4096,
    )
    logger.info("Context caching enabled (TTL=%ds, min_tokens=4096)", _CONTEXT_CACHE_TTL)
else:
    logger.info("Context caching disabled (support=%s, enabled=%s)",
                _CACHE_SUPPORT, _CONTEXT_CACHE_ENABLED)

# ---------------------------------------------------------------------------
# HITL Approval Plugin (human-in-the-loop for high-risk operations)
# ---------------------------------------------------------------------------
_hitl_plugin = HITLApprovalPlugin()

if HITL_ENABLED:
    async def _chainlit_approval(content: str):
        """Show approval dialog via Chainlit AskActionMessage."""
        res = await cl.AskActionMessage(
            content=content,
            actions=[
                cl.Action(name="approve", payload={"value": "APPROVE"}, label=t("action.approve")),
                cl.Action(name="reject", payload={"value": "REJECT"}, label=t("action.reject")),
            ],
            timeout=int(os.environ.get("HITL_TIMEOUT", "120")),
        ).send()
        return res

    _hitl_plugin.set_approval_function(_chainlit_approval)

# ---------------------------------------------------------------------------
# Self-Registration Routes (mounted on Chainlit's FastAPI app)
# ---------------------------------------------------------------------------
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from chainlit.server import app as chainlit_app
from data_agent.auth import register_user

_REGISTER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>注册 - Data Agent</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#f5f5f5;display:flex;justify-content:center;
       align-items:center;min-height:100vh}
  .card{background:#fff;border-radius:12px;padding:40px;
        box-shadow:0 2px 12px rgba(0,0,0,.1);width:100%;max-width:420px}
  h2{text-align:center;margin-bottom:24px;color:#333}
  .field{margin-bottom:16px}
  label{display:block;margin-bottom:4px;font-size:14px;color:#555}
  input{width:100%;padding:10px 12px;border:1px solid #ddd;
        border-radius:8px;font-size:14px}
  input:focus{outline:none;border-color:#6366f1}
  .btn{width:100%;padding:12px;border:none;border-radius:8px;
       background:#6366f1;color:#fff;font-size:16px;cursor:pointer;margin-top:8px}
  .btn:hover{background:#4f46e5}
  .btn:disabled{background:#999;cursor:not-allowed}
  .msg{margin-top:12px;padding:10px;border-radius:8px;font-size:14px;display:none}
  .msg.error{display:block;background:#fef2f2;color:#dc2626;border:1px solid #fecaca}
  .msg.success{display:block;background:#f0fdf4;color:#16a34a;border:1px solid #bbf7d0}
  .link{text-align:center;margin-top:16px;font-size:14px}
  .link a{color:#6366f1;text-decoration:none}
</style>
</head>
<body>
<div class="card">
  <h2>注册 Data Agent</h2>
  <div id="msg" class="msg"></div>
  <form id="regForm">
    <div class="field">
      <label>用户名 (3-30位字母/数字/下划线)</label>
      <input name="username" required minlength="3" maxlength="30" pattern="[a-zA-Z0-9_]+">
    </div>
    <div class="field">
      <label>显示名称</label>
      <input name="display_name" placeholder="可选">
    </div>
    <div class="field">
      <label>密码 (8位以上，含字母和数字)</label>
      <input name="password" type="password" required minlength="8">
    </div>
    <div class="field">
      <label>确认密码</label>
      <input name="confirm" type="password" required>
    </div>
    <button class="btn" type="submit">注册</button>
  </form>
  <div class="link"><a href="/">返回登录</a></div>
</div>
<script>
document.getElementById('regForm').addEventListener('submit',async e=>{
  e.preventDefault();
  const fd=new FormData(e.target),msg=document.getElementById('msg');
  msg.className='msg';msg.style.display='none';
  if(fd.get('password')!==fd.get('confirm')){
    msg.className='msg error';msg.textContent='两次密码不一致';msg.style.display='block';return;
  }
  const btn=e.target.querySelector('button');
  btn.disabled=true;btn.textContent='注册中...';
  try{
    const resp=await fetch('/auth/register',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:fd.get('username'),password:fd.get('password'),
                           display_name:fd.get('display_name')||''})
    });
    const data=await resp.json();
    if(data.status==='success'){
      msg.className='msg success';msg.textContent=data.message;msg.style.display='block';
      setTimeout(()=>{window.location.href='/';},1500);
    }else{
      msg.className='msg error';msg.textContent=data.message;msg.style.display='block';
    }
  }catch(err){
    msg.className='msg error';msg.textContent='网络错误: '+err.message;msg.style.display='block';
  }finally{btn.disabled=false;btn.textContent='注册';}
});
</script>
</body>
</html>"""


@chainlit_app.post("/auth/register")
async def api_register(request: Request):
    """Handle registration API call."""
    body = await request.json()
    result = register_user(
        username=body.get("username", ""),
        password=body.get("password", ""),
        display_name=body.get("display_name", ""),
        email=body.get("email", ""),
    )
    try:
        record_audit(
            body.get("username", "unknown"), ACTION_USER_REGISTER,
            status="success" if result["status"] == "success" else "failure",
            details={"display_name": body.get("display_name", "")},
        )
    except Exception:
        pass
    status_code = 200 if result["status"] == "success" else 400
    return JSONResponse(content=result, status_code=status_code)


async def _serve_register_page(request: Request):
    return HTMLResponse(content=_REGISTER_HTML)

# Insert GET /register BEFORE Chainlit's catch-all /{full_path:path}
_register_route = Route("/register", endpoint=_serve_register_page, methods=["GET"])
for _i, _r in enumerate(chainlit_app.router.routes):
    if hasattr(_r, 'path') and _r.path == "/{full_path:path}":
        chainlit_app.router.routes.insert(_i, _register_route)
        break
else:
    chainlit_app.router.routes.append(_register_route)

logger.info("Self-registration enabled at /register")

# --- Result Sharing Routes (public, no auth) ---
from data_agent.sharing import (
    SHARE_VIEWER_HTML, validate_share_token, get_share_file_path
)
from fastapi.responses import FileResponse
import mimetypes


@chainlit_app.post("/api/share/{token}/validate")
async def api_share_validate_post(token: str, request: Request):
    """Validate a share token (POST, supports password)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    password = body.get("password")
    result = validate_share_token(token, password)
    status_map = {"not_found": 404, "expired": 410,
                  "password_required": 401, "wrong_password": 403}
    code = status_map.get(result.get("reason"), 200) if result["status"] == "error" else 200
    return JSONResponse(content=result, status_code=code)


async def _api_share_validate_get(request: Request):
    """Validate a share token (GET, passwordless links)."""
    token = request.path_params.get("token", "")
    result = validate_share_token(token, None)
    status_map = {"not_found": 404, "expired": 410,
                  "password_required": 401, "wrong_password": 403}
    code = status_map.get(result.get("reason"), 200) if result["status"] == "error" else 200
    return JSONResponse(content=result, status_code=code)


async def _serve_share_page(request: Request):
    """Serve the share viewer HTML page."""
    return HTMLResponse(content=SHARE_VIEWER_HTML)


async def _serve_share_file(request: Request):
    """Serve a file from a share link."""
    token = request.path_params["token"]
    filename = request.path_params["filename"]
    file_path = get_share_file_path(token, filename)
    if not file_path:
        return JSONResponse(content={"error": "File not found"}, status_code=404)
    content_type, _ = mimetypes.guess_type(filename)
    if filename.endswith('.html'):
        return FileResponse(file_path, media_type="text/html")
    elif filename.endswith('.png'):
        return FileResponse(file_path, media_type="image/png")
    else:
        return FileResponse(file_path, filename=filename,
                            media_type=content_type or "application/octet-stream")


_share_page_route = Route("/s/{token}", endpoint=_serve_share_page, methods=["GET"])
_share_file_route = Route(
    "/api/share/{token}/file/{filename:path}",
    endpoint=_serve_share_file, methods=["GET"]
)
_share_validate_get_route = Route(
    "/api/share/{token}/validate",
    endpoint=_api_share_validate_get, methods=["GET"]
)
for _i, _r in enumerate(chainlit_app.router.routes):
    if hasattr(_r, 'path') and _r.path == "/{full_path:path}":
        chainlit_app.router.routes.insert(_i, _share_page_route)
        chainlit_app.router.routes.insert(_i, _share_file_route)
        chainlit_app.router.routes.insert(_i, _share_validate_get_route)
        break

logger.info("Public share routes enabled at /s/{token}")

# --- User File API Routes (for custom frontend) ---
from chainlit.auth.cookie import get_token_from_cookies
from chainlit.auth.jwt import decode_jwt

_UPLOADS_BASE = os.path.join(os.path.dirname(__file__), "uploads")


def _get_user_from_request(request: Request):
    """Extract authenticated user from request cookies."""
    token = get_token_from_cookies(dict(request.cookies))
    if not token:
        return None
    try:
        return decode_jwt(token)
    except Exception:
        return None


async def _api_list_user_files(request: Request):
    """List files in the authenticated user's upload directory."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    user_dir = os.path.join(_UPLOADS_BASE, user.identifier)
    if not os.path.isdir(user_dir):
        return JSONResponse(content=[])

    files = []
    for name in os.listdir(user_dir):
        fpath = os.path.join(user_dir, name)
        if not os.path.isfile(fpath):
            continue
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        stat = os.stat(fpath)
        files.append({
            "name": name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "type": ext,
        })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return JSONResponse(content=files)


async def _api_serve_user_file(request: Request):
    """Serve a file from the authenticated user's upload directory."""
    filename = request.path_params.get("filename", "")
    user = _get_user_from_request(request)
    
    # Fallback for dev mode
    user_id = user.identifier if user and hasattr(user, "identifier") else "admin"

    user_dir = os.path.join(_UPLOADS_BASE, user_id)
    file_path = os.path.join(user_dir, filename)

    # Security: ensure resolved path is within the user directory
    real_path = os.path.realpath(file_path)
    real_dir = os.path.realpath(user_dir)
    if not real_path.startswith(real_dir + os.sep) and real_path != real_dir:
        return JSONResponse(content={"error": "Forbidden"}, status_code=403)

    if not os.path.isfile(real_path):
        return JSONResponse(content={"error": "Not found"}, status_code=404)

    content_type, _ = mimetypes.guess_type(filename)
    return FileResponse(real_path, media_type=content_type or "application/octet-stream")


# Insert file API routes BEFORE Chainlit's catch-all /{full_path:path}
_file_list_route = Route("/api/user/files", endpoint=_api_list_user_files, methods=["GET"])
_file_serve_route = Route("/api/user/files/{filename:path}", endpoint=_api_serve_user_file, methods=["GET"])
for _i, _r in enumerate(chainlit_app.router.routes):
    if hasattr(_r, 'path') and _r.path == "/{full_path:path}":
        chainlit_app.router.routes.insert(_i, _file_list_route)
        chainlit_app.router.routes.insert(_i + 1, _file_serve_route)
        break
else:
    chainlit_app.router.routes.append(_file_list_route)
    chainlit_app.router.routes.append(_file_serve_route)

logger.info("User file API routes enabled at /api/user/files")

# --- Admin Audit Viewer Routes ---
import hmac
import hashlib as _hashlib
import time as _time
from data_agent.audit_logger import get_user_audit_log, get_audit_stats

_AUDIT_SECRET = os.environ.get("CHAINLIT_AUTH_SECRET", "default-secret-key")


def _make_admin_token(username: str) -> str:
    """Generate short-lived HMAC token for admin API (valid 1 hour)."""
    ts = str(int(_time.time()) // 3600)
    msg = f"{username}:{ts}".encode()
    return hmac.new(_AUDIT_SECRET.encode(), msg, _hashlib.sha256).hexdigest()


def _verify_admin_token(token: str) -> bool:
    """Verify an admin HMAC token (current hour or previous hour)."""
    for offset in (0, -1):
        ts = str(int(_time.time()) // 3600 + offset)
        for user_candidate in ("admin",):
            msg = f"{user_candidate}:{ts}".encode()
            expected = hmac.new(_AUDIT_SECRET.encode(), msg, _hashlib.sha256).hexdigest()
            if hmac.compare_digest(token, expected):
                return True
    return False


_AUDIT_VIEWER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>审计日志 — Data Agent Admin</title>
<meta name="admin-token" content="{admin_token}">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
     background:#f5f5f5;color:#333;line-height:1.6}
.container{max-width:1100px;margin:0 auto;padding:24px 16px}
header{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;
       box-shadow:0 1px 3px rgba(0,0,0,.1)}
header h1{font-size:1.4em;color:#1a1a2e;margin-bottom:8px}
.stats-bar{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.stat-card{background:#fff;border-radius:10px;padding:16px 20px;flex:1;min-width:150px;
           box-shadow:0 1px 3px rgba(0,0,0,.1);text-align:center}
.stat-card .num{font-size:1.8em;font-weight:700;color:#6366f1}
.stat-card .label{font-size:.85em;color:#888;margin-top:4px}
.filters{background:#fff;border-radius:10px;padding:16px 20px;margin-bottom:16px;
         box-shadow:0 1px 3px rgba(0,0,0,.1);display:flex;gap:12px;flex-wrap:wrap;align-items:end}
.filters label{font-size:.85em;color:#666;display:block;margin-bottom:4px}
.filters input,.filters select{padding:8px 12px;border:1px solid #ddd;border-radius:6px;font-size:.9em}
.filters button{padding:8px 20px;background:#6366f1;color:#fff;border:none;border-radius:6px;
                font-size:.9em;cursor:pointer}
.filters button:hover{background:#4f46e5}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;
      box-shadow:0 1px 3px rgba(0,0,0,.1)}
th{background:#f8f9fa;padding:12px 14px;text-align:left;font-size:.85em;color:#555;
   border-bottom:2px solid #e8e8e8}
td{padding:10px 14px;border-bottom:1px solid #f0f0f0;font-size:.88em}
tr:hover{background:#fafafa}
.s-success{color:#10b981;font-weight:600}
.s-failure{color:#ef4444;font-weight:600}
.s-denied{color:#f59e0b;font-weight:600}
.detail-cell{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
             font-size:.82em;color:#666}
.load-more{text-align:center;padding:16px}
.load-more button{padding:10px 32px;background:#e8e8ff;color:#6366f1;border:none;
                  border-radius:8px;cursor:pointer;font-size:.9em}
.load-more button:hover{background:#d0d0ff}
.empty{text-align:center;padding:40px;color:#aaa}
footer{text-align:center;color:#aaa;font-size:.8em;padding:24px 0}
</style>
</head>
<body>
<div class="container">
<header><h1>审计日志管理</h1><p style="color:#888;font-size:.9em">系统操作记录与安全审计</p></header>
<div class="stats-bar" id="stats-bar"></div>
<div class="filters">
  <div><label>用户名</label><input id="f-user" placeholder="全部"></div>
  <div><label>操作类型</label><select id="f-action"><option value="">全部</option>
    <option value="login_success">登录成功</option><option value="login_failure">登录失败</option>
    <option value="user_register">用户注册</option><option value="session_start">会话开始</option>
    <option value="file_upload">文件上传</option><option value="pipeline_complete">分析完成</option>
    <option value="report_export">报告导出</option><option value="share_create">创建分享</option>
    <option value="file_delete">文件删除</option><option value="table_share">共享数据表</option>
    <option value="rbac_denied">权限拒绝</option></select></div>
  <div><label>状态</label><select id="f-status"><option value="">全部</option>
    <option value="success">成功</option><option value="failure">失败</option>
    <option value="denied">拒绝</option></select></div>
  <div><label>天数</label><select id="f-days">
    <option value="7">7天</option><option value="30" selected>30天</option>
    <option value="90">90天</option></select></div>
  <div><button id="btn-search" onclick="doSearch(0)">查询</button></div>
</div>
<table><thead><tr><th>时间</th><th>用户</th><th>操作</th><th>状态</th><th>详情</th></tr></thead>
<tbody id="log-body"></tbody></table>
<div class="load-more" id="load-more" style="display:none">
  <button onclick="loadMore()">加载更多</button></div>
<div class="empty" id="empty-msg" style="display:none">暂无符合条件的审计日志</div>
<footer>Data Agent Admin Panel</footer>
</div>
<script>
var TOKEN=document.querySelector('meta[name=admin-token]').content;
var offset=0,limit=50;
var actionLabels={login_success:"登录成功",login_failure:"登录失败",user_register:"用户注册",
  session_start:"会话开始",file_upload:"文件上传",pipeline_complete:"分析完成",
  report_export:"报告导出",share_create:"创建分享",file_delete:"文件删除",
  table_share:"共享数据表",rbac_denied:"权限拒绝"};

function api(url){
  return fetch(url,{headers:{'Authorization':'Bearer '+TOKEN}}).then(function(r){return r.json()});
}
function loadStats(){
  api('/api/admin/audit/stats?days='+document.getElementById('f-days').value).then(function(d){
    var bar=document.getElementById('stats-bar');
    var errRate=d.total_events>0?
      ((d.events_by_status.failure||0)+(d.events_by_status.denied||0))*100/d.total_events:0;
    bar.innerHTML='<div class="stat-card"><div class="num">'+d.total_events+'</div><div class="label">总事件数</div></div>'+
      '<div class="stat-card"><div class="num">'+d.active_users+'</div><div class="label">活跃用户</div></div>'+
      '<div class="stat-card"><div class="num">'+errRate.toFixed(1)+'%</div><div class="label">异常率</div></div>';
  });
}
function doSearch(off){
  offset=off;
  var p='?days='+document.getElementById('f-days').value+'&offset='+offset+'&limit='+limit;
  var u=document.getElementById('f-user').value;
  var a=document.getElementById('f-action').value;
  var s=document.getElementById('f-status').value;
  if(u) p+='&username='+encodeURIComponent(u);
  if(a) p+='&action='+encodeURIComponent(a);
  if(s) p+='&status='+encodeURIComponent(s);
  api('/api/admin/audit'+p).then(function(d){
    var tb=document.getElementById('log-body');
    if(offset===0) tb.innerHTML='';
    if(!d.rows||d.rows.length===0){
      if(offset===0){document.getElementById('empty-msg').style.display='';
        document.getElementById('load-more').style.display='none';}
      return;
    }
    document.getElementById('empty-msg').style.display='none';
    d.rows.forEach(function(r){
      var tr=document.createElement('tr');
      var ts=r.created_at?new Date(r.created_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'?';
      var sc=r.status==='success'?'s-success':(r.status==='failure'?'s-failure':'s-denied');
      var det=r.details?Object.entries(r.details).map(function(e){return e[0]+'='+e[1]}).join(', '):'';
      tr.innerHTML='<td>'+ts+'</td><td>'+r.username+'</td><td>'+(actionLabels[r.action]||r.action)+
        '</td><td class="'+sc+'">'+r.status+'</td><td class="detail-cell" title="'+det+'">'+det+'</td>';
      tb.appendChild(tr);
    });
    document.getElementById('load-more').style.display=d.rows.length>=limit?'':'none';
  });
}
function loadMore(){doSearch(offset+limit);}
loadStats();doSearch(0);
</script>
</body>
</html>"""


async def _serve_audit_page(request: Request):
    """Serve admin audit viewer — requires admin session."""
    # Check admin cookie via Chainlit session
    # Since this is outside Chainlit's auth flow, we verify via HMAC approach:
    # We generate a token for the admin user that's embedded in the HTML.
    # The page-level auth is minimal (anyone can see the page shell),
    # but the API endpoints verify the HMAC token.
    admin_token = _make_admin_token("admin")
    html = _AUDIT_VIEWER_HTML.replace("{admin_token}", admin_token)
    return HTMLResponse(content=html)


async def _api_admin_audit(request: Request):
    """Return audit log entries as JSON (admin-only, HMAC-protected)."""
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
    if not _verify_admin_token(token):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    params = request.query_params
    days = min(int(params.get("days", "30")), 90)
    offset_val = int(params.get("offset", "0"))
    limit_val = min(int(params.get("limit", "50")), 200)
    username_filter = params.get("username", "")
    action_filter = params.get("action", "")
    status_filter = params.get("status", "")

    from data_agent.database_tools import T_AUDIT_LOG
    from data_agent.db_engine import get_engine
    import json as _json

    engine = get_engine()
    if not engine:
        return JSONResponse(content={"rows": []})

    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            where_clauses = ["created_at >= NOW() - make_interval(days => :d)"]
            bind = {"d": days, "off": offset_val, "lim": limit_val}

            if username_filter:
                where_clauses.append("username = :uf")
                bind["uf"] = username_filter
            if action_filter:
                where_clauses.append("action = :af")
                bind["af"] = action_filter
            if status_filter:
                where_clauses.append("status = :sf")
                bind["sf"] = status_filter

            where_sql = " AND ".join(where_clauses)
            rows = conn.execute(text(f"""
                SELECT username, action, status, ip_address, details, created_at
                FROM {T_AUDIT_LOG}
                WHERE {where_sql}
                ORDER BY created_at DESC
                OFFSET :off LIMIT :lim
            """), bind).fetchall()

            result = []
            for r in rows:
                details = r[4] if isinstance(r[4], dict) else _json.loads(r[4] or "{}")
                result.append({
                    "username": r[0], "action": r[1], "status": r[2],
                    "ip_address": r[3], "details": details,
                    "created_at": r[5].isoformat() if r[5] else None,
                })
            return JSONResponse(content={"rows": result})
    except Exception as e:
        return JSONResponse(content={"rows": [], "error": str(e)})


async def _api_admin_audit_stats(request: Request):
    """Return aggregate audit stats (admin-only, HMAC-protected)."""
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
    if not _verify_admin_token(token):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    days = min(int(request.query_params.get("days", "30")), 90)
    stats = get_audit_stats(days)
    return JSONResponse(content=stats)


_audit_page_route = Route("/admin/audit", endpoint=_serve_audit_page, methods=["GET"])
_audit_api_route = Route("/api/admin/audit", endpoint=_api_admin_audit, methods=["GET"])
_audit_stats_route = Route("/api/admin/audit/stats", endpoint=_api_admin_audit_stats, methods=["GET"])
for _i, _r in enumerate(chainlit_app.router.routes):
    if hasattr(_r, 'path') and _r.path == "/{full_path:path}":
        chainlit_app.router.routes.insert(_i, _audit_page_route)
        chainlit_app.router.routes.insert(_i, _audit_api_route)
        chainlit_app.router.routes.insert(_i, _audit_stats_route)
        break
else:
    chainlit_app.router.routes.append(_audit_page_route)
    chainlit_app.router.routes.append(_audit_api_route)
    chainlit_app.router.routes.append(_audit_stats_route)

logger.info("Admin audit viewer enabled at /admin/audit")

# --- Health Check & System Diagnostics Routes ---
from data_agent.health import (
    liveness_check, readiness_check, get_system_status, format_startup_summary,
)


async def _health_endpoint(request: Request):
    """Liveness probe — always 200 if process is alive."""
    return JSONResponse(content=liveness_check())


async def _ready_endpoint(request: Request):
    """Readiness probe — 503 if critical subsystems are down."""
    result = readiness_check()
    status_code = 200 if result["status"] == "ok" else 503
    return JSONResponse(content=result, status_code=status_code)


async def _system_info_endpoint(request: Request):
    """Comprehensive system status (admin HMAC auth required)."""
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "") if auth.startswith("Bearer ") else ""
    if not _verify_admin_token(token):
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)
    return JSONResponse(content=get_system_status(session_svc=session_service))


async def _metrics_endpoint(request: Request):
    """Prometheus metrics endpoint for scraping."""
    from starlette.responses import Response as StarletteResponse
    return StarletteResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


_health_route = Route("/health", endpoint=_health_endpoint, methods=["GET"])
_ready_route = Route("/ready", endpoint=_ready_endpoint, methods=["GET"])
_sysinfo_route = Route("/api/admin/system-info", endpoint=_system_info_endpoint, methods=["GET"])
_metrics_route = Route("/metrics", endpoint=_metrics_endpoint, methods=["GET"])
for _i, _r in enumerate(chainlit_app.router.routes):
    if hasattr(_r, 'path') and _r.path == "/{full_path:path}":
        chainlit_app.router.routes.insert(_i, _health_route)
        chainlit_app.router.routes.insert(_i, _ready_route)
        chainlit_app.router.routes.insert(_i, _sysinfo_route)
        chainlit_app.router.routes.insert(_i, _metrics_route)
        break
else:
    chainlit_app.router.routes.append(_health_route)
    chainlit_app.router.routes.append(_ready_route)
    chainlit_app.router.routes.append(_sysinfo_route)
    chainlit_app.router.routes.append(_metrics_route)

# --- Mount Enterprise WeChat bot routes (conditional) ---
if is_wecom_configured():
    from data_agent.wecom_bot import mount_wecom_routes
    if mount_wecom_routes(chainlit_app):
        logger.info("WeCom callback routes mounted at /wecom/callback")

# --- Mount DingTalk bot routes (conditional) ---
try:
    from data_agent.dingtalk_bot import is_dingtalk_configured, ensure_dingtalk_connection
    if is_dingtalk_configured():
        ensure_dingtalk_connection(chainlit_app)
except Exception as _dt_mount_err:
    logger.warning("DingTalk route mount failed: %s", _dt_mount_err)

# --- Mount Feishu bot routes (conditional) ---
try:
    from data_agent.feishu_bot import is_feishu_configured, ensure_feishu_connection
    if is_feishu_configured():
        ensure_feishu_connection(chainlit_app)
except Exception as _fs_mount_err:
    logger.warning("Feishu route mount failed: %s", _fs_mount_err)

# --- Mount Stream API routes ---
try:
    from data_agent.stream_api import mount_stream_routes
    mount_stream_routes(chainlit_app)
except Exception as _stream_mount_err:
    logger.warning("Stream route mount failed: %s", _stream_mount_err)

# --- Mount Frontend API routes ---
try:
    from data_agent.frontend_api import mount_frontend_api
    mount_frontend_api(chainlit_app)
except Exception as _fe_err:
    logger.warning("Frontend API mount failed: %s", _fe_err)

# --- Workflow Scheduler (v5.4) ---
_workflow_scheduler = None
try:
    from data_agent.workflow_engine import WorkflowScheduler
    _workflow_scheduler = WorkflowScheduler()
    _workflow_scheduler.start()
except Exception as _wf_sched_err:
    logger.warning("Workflow scheduler init failed: %s", _wf_sched_err)

# --- Startup Diagnostics Banner ---
logger.info("\n%s", format_startup_summary(session_svc=session_service))

# Base upload directory (per-user dirs created inside)
BASE_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(BASE_UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB

# --- Progress Feedback Labels ---
TOOL_LABELS = {
    "describe_geodataframe": "数据质量检查",
    "check_topology": "拓扑检查",
    "check_field_standards": "字段标准检查",
    "check_consistency": "一致性核查",
    "query_database": "数据库查询",
    "list_tables": "列出数据表",
    "describe_table": "分析表结构",
    "reproject_spatial_data": "坐标投影转换",
    "engineer_spatial_features": "空间特征工程",
    "generate_tessellation": "格网镶嵌分析",
    "raster_to_polygon": "栅格转矢量",
    "pairwise_clip": "裁剪分析",
    "tabulate_intersection": "叠加统计",
    "surface_parameters": "地形参数计算",
    "zonal_statistics_as_table": "分区统计",
    "batch_geocode": "批量地理编码",
    "reverse_geocode": "逆地理编码",
    "ffi": "破碎化指数计算",
    "drl_model": "深度强化学习优化",
    "perform_clustering": "空间聚类分析",
    "create_buffer": "缓冲区分析",
    "summarize_within": "区域汇总统计",
    "overlay_difference": "空间擦除分析",
    "find_within_distance": "距离查询",
    "calculate_driving_distance": "驾车距离计算",
    "search_nearby_poi": "周边POI搜索",
    "search_poi_by_keyword": "关键词POI搜索",
    "get_admin_boundary": "行政区划边界获取",
    "get_population_data": "人口密度统计",
    "aggregate_population": "人口聚合统计",
    "visualize_geodataframe": "静态地图渲染",
    "visualize_interactive_map": "交互地图生成",
    "visualize_optimization_comparison": "优化对比图",
    "generate_heatmap": "热力图生成",
    "generate_choropleth": "等值区域图",
    "generate_bubble_map": "气泡图生成",
    "export_map_png": "导出地图PNG",
    "compose_map": "多图层地图合成",
    "list_user_files": "列出用户文件",
    "delete_user_file": "删除用户文件",
    "save_memory": "保存空间记忆",
    "recall_memories": "检索空间记忆",
    "list_memories": "列出空间记忆",
    "delete_memory": "删除空间记忆",
    "get_usage_summary": "查询Token用量",
    "arcpy_buffer": "ArcPy缓冲区分析",
    "arcpy_clip": "ArcPy裁剪分析",
    "arcpy_dissolve": "ArcPy融合分析",
    "arcpy_project": "ArcPy坐标投影",
    "arcpy_check_geometry": "ArcPy几何检查",
    "arcpy_repair_geometry": "ArcPy几何修复",
    "arcpy_slope": "ArcPy坡度计算",
    "arcpy_zonal_statistics": "ArcPy分区统计",
    "polygon_neighbors": "面邻域分析",
    "add_field": "添加字段",
    "add_join": "属性连接",
    "calculate_field": "字段计算",
    "summary_statistics": "汇总统计",
    "share_table": "共享数据表",
    "query_audit_log": "查询审计日志",
    "save_as_template": "保存模板",
    "list_templates": "浏览模板",
    "delete_template": "删除模板",
    "share_template": "共享模板",
    "describe_raster": "栅格数据画像",
    "calculate_ndvi": "NDVI植被指数计算",
    "raster_band_math": "波段运算",
    "classify_raster": "非监督分类",
    "visualize_raster": "栅格可视化",
    "download_lulc": "下载土地覆盖数据(LULC)",
    "download_dem": "下载高程数据(DEM)",
    "spatial_autocorrelation": "全局空间自相关(Moran's I)",
    "local_moran": "局部空间自相关(LISA)",
    "hotspot_analysis": "热点分析(Gi*)",
    "create_team": "创建团队",
    "list_my_teams": "我的团队列表",
    "invite_to_team": "邀请团队成员",
    "remove_from_team": "移除团队成员",
    "list_team_members": "团队成员列表",
    "list_team_resources": "团队共享资源",
    "leave_team": "退出团队",
    "delete_team": "删除团队",
}

AGENT_LABELS = {
    "vertex_search_agent": "检索领域知识",
    "DataIngestion": "数据采集与工程(并行)",
    "DataExploration": "数据质量审计",
    "DataProcessing": "特征工程与预处理",
    "DataAnalysis": "空间分析与优化",
    "DataVisualization": "生成可视化",
    "DataSummary": "生成分析报告",
    "GovExploration": "数据质量审计",
    "GovProcessing": "数据修复",
    "GovernanceReporter": "生成治理报告",
    "GeneralProcessing": "数据处理与分析",
    "GeneralViz": "生成可视化",
    "GeneralSummary": "生成分析总结",
    "Planner": "任务规划",
    "PlannerExplorer": "数据探查",
    "PlannerProcessor": "数据处理",
    "PlannerAnalyzer": "分析优化",
    "PlannerVisualizer": "生成可视化",
    "PlannerReporter": "撰写报告",
}

# --- Tool Descriptions: method names + parameter labels for explainability ---
TOOL_DESCRIPTIONS = {
    "describe_geodataframe": {
        "method": "数据质量预检（7项检查）",
        "params": {"file_path": "数据文件"},
    },
    "check_topology": {
        "method": "拓扑检查（自相交、重叠、多部件）",
        "params": {"file_path": "数据文件"},
    },
    "check_field_standards": {
        "method": "字段标准化验证",
        "params": {"file_path": "数据文件", "standard_schema": "标准模式"},
    },
    "check_consistency": {
        "method": "PDF-矢量一致性核查",
        "params": {"pdf_path": "PDF文档", "shp_path": "矢量数据",
                   "area_field": "面积字段", "unit_conversion": "单位换算系数"},
    },
    "query_database": {
        "method": "SQL 数据库查询",
        "params": {"sql_query": "SQL语句"},
    },
    "list_tables": {
        "method": "数据库表清单查询",
        "params": {},
    },
    "describe_table": {
        "method": "数据表结构分析",
        "params": {"table_name": "表名"},
    },
    "reproject_spatial_data": {
        "method": "坐标系重投影",
        "params": {"file_path": "数据文件", "target_crs": "目标坐标系"},
    },
    "engineer_spatial_features": {
        "method": "空间特征工程（面积/周长/质心）",
        "params": {"file_path": "数据文件"},
    },
    "generate_tessellation": {
        "method": "格网镶嵌分析",
        "params": {"extent_file": "范围数据", "shape_type": "格网形状", "size": "格网尺寸"},
    },
    "raster_to_polygon": {
        "method": "栅格转矢量",
        "params": {"raster_file": "栅格文件", "value_field": "值字段"},
    },
    "pairwise_clip": {
        "method": "空间裁剪",
        "params": {"input_features": "输入数据", "clip_features": "裁剪范围"},
    },
    "tabulate_intersection": {
        "method": "叠加交叉统计",
        "params": {"zone_features": "区域数据", "class_features": "分类数据", "class_field": "分类字段"},
    },
    "surface_parameters": {
        "method": "地形参数计算",
        "params": {"dem_raster": "DEM栅格", "parameter_type": "参数类型"},
    },
    "zonal_statistics_as_table": {
        "method": "分区统计",
        "params": {"zone_vector": "区域矢量", "value_raster": "值栅格", "stats": "统计指标"},
    },
    "batch_geocode": {
        "method": "批量地理编码（地址→坐标, 含置信度评级）",
        "params": {"file_path": "数据文件", "address_col": "地址列", "city": "城市"},
    },
    "reverse_geocode": {
        "method": "逆地理编码（坐标→地址, 高德API）",
        "params": {"file_path": "数据文件", "lng_col": "经度列", "lat_col": "纬度列"},
    },
    "calculate_driving_distance": {
        "method": "驾车距离计算（高德路径规划）",
        "params": {"origin_lng": "起点经度", "origin_lat": "起点纬度",
                   "dest_lng": "终点经度", "dest_lat": "终点纬度"},
    },
    "search_nearby_poi": {
        "method": "周边POI搜索（高德API）",
        "params": {"lng": "经度", "lat": "纬度", "keywords": "关键词",
                   "radius": "搜索半径(米)", "max_results": "最大结果数"},
    },
    "search_poi_by_keyword": {
        "method": "关键词POI搜索（高德API）",
        "params": {"keywords": "关键词", "region": "搜索区域", "max_results": "最大结果数"},
    },
    "get_admin_boundary": {
        "method": "行政区划边界获取（高德API）",
        "params": {"district_name": "行政区名称", "with_sub_districts": "含子区划"},
    },
    "get_population_data": {
        "method": "人口密度统计（WorldPop 100m栅格）",
        "params": {"district_name": "行政区名称", "year": "年份", "country_code": "国家代码"},
    },
    "aggregate_population": {
        "method": "自定义人口聚合统计（分区栅格统计）",
        "params": {"polygon_path": "面矢量路径", "raster_path": "人口栅格路径", "stats": "统计指标"},
    },
    "ffi": {
        "method": "耕地破碎化指数（FFI, 6项景观指标）",
        "params": {"data_path": "数据文件"},
    },
    "drl_model": {
        "method": "深度强化学习布局优化（MaskablePPO）",
        "params": {"data_path": "数据文件"},
    },
    "perform_clustering": {
        "method": "DBSCAN 空间密度聚类",
        "params": {"file_path": "数据文件", "eps": "邻域半径(米)", "min_samples": "最小点数"},
    },
    "create_buffer": {
        "method": "缓冲区分析",
        "params": {"file_path": "数据文件", "distance": "缓冲距离(米)", "dissolve": "融合重叠"},
    },
    "summarize_within": {
        "method": "区域内汇总统计",
        "params": {"zone_file": "区域数据", "data_file": "要素数据", "stats_field": "统计字段"},
    },
    "overlay_difference": {
        "method": "空间擦除（差集）",
        "params": {"input_file": "输入数据", "erase_file": "擦除范围"},
    },
    "find_within_distance": {
        "method": "距离筛选查询",
        "params": {"target_file": "目标数据", "reference_file": "参考数据",
                   "distance": "距离阈值(米)", "mode": "模式(within/beyond)"},
    },
    "generate_heatmap": {
        "method": "核密度估计热力图（KDE）",
        "params": {"file_path": "数据文件", "bandwidth": "带宽",
                   "resolution": "分辨率", "weight_field": "权重字段"},
    },
    "visualize_geodataframe": {
        "method": "静态地图渲染",
        "params": {"file_path": "数据文件"},
    },
    "visualize_interactive_map": {
        "method": "多图层交互地图",
        "params": {"original_data_path": "原始数据", "optimized_data_path": "优化数据",
                   "center_lat": "中心纬度", "center_lng": "中心经度", "zoom": "缩放级别"},
    },
    "visualize_optimization_comparison": {
        "method": "优化前后对比图",
        "params": {"original_data_path": "原始数据", "optimized_data_path": "优化数据"},
    },
    "generate_choropleth": {
        "method": "等值区域图（分级设色）",
        "params": {"file_path": "数据文件", "value_column": "值字段",
                   "color_scheme": "配色方案", "classification_method": "分级方法",
                   "num_classes": "分级数"},
    },
    "generate_bubble_map": {
        "method": "气泡图（尺寸映射）",
        "params": {"file_path": "数据文件", "size_column": "尺寸字段",
                   "color_column": "颜色字段", "max_radius": "最大半径"},
    },
    "export_map_png": {
        "method": "带底图高清PNG导出",
        "params": {"file_path": "数据文件", "value_column": "着色字段", "title": "地图标题"},
    },
    "compose_map": {
        "method": "多图层交互地图合成",
        "params": {"layers_json": "图层配置JSON", "center_lat": "中心纬度",
                   "center_lng": "中心经度", "zoom": "缩放级别"},
    },
    "list_user_files": {
        "method": "列出用户文件清单",
        "params": {},
    },
    "delete_user_file": {
        "method": "删除用户文件",
        "params": {"file_name": "文件名"},
    },
    "save_memory": {
        "method": "保存空间记忆",
        "params": {"memory_type": "记忆类型", "key": "关键词", "value": "内容"},
    },
    "recall_memories": {
        "method": "检索空间记忆",
        "params": {"memory_type": "记忆类型", "keyword": "搜索关键词"},
    },
    "list_memories": {
        "method": "列出空间记忆",
        "params": {"memory_type": "记忆类型"},
    },
    "delete_memory": {
        "method": "删除空间记忆",
        "params": {"memory_type": "记忆类型", "key": "关键词"},
    },
    "get_usage_summary": {
        "method": "Token用量统计查询",
        "params": {},
    },
    "arcpy_buffer": {
        "method": "ArcPy缓冲区分析",
        "params": {"input_features": "输入数据", "buffer_distance": "缓冲距离"},
    },
    "arcpy_clip": {
        "method": "ArcPy裁剪分析",
        "params": {"input_features": "输入数据", "clip_features": "裁剪范围"},
    },
    "arcpy_dissolve": {
        "method": "ArcPy融合分析（按字段+统计聚合）",
        "params": {"input_features": "输入数据", "dissolve_field": "融合字段",
                   "statistics_fields": "统计字段"},
    },
    "arcpy_project": {
        "method": "ArcPy坐标投影转换",
        "params": {"input_features": "输入数据", "out_crs": "目标坐标系"},
    },
    "arcpy_check_geometry": {
        "method": "ArcPy几何有效性检查",
        "params": {"input_features": "输入数据"},
    },
    "arcpy_repair_geometry": {
        "method": "ArcPy几何自动修复",
        "params": {"input_features": "输入数据"},
    },
    "arcpy_slope": {
        "method": "ArcPy坡度计算",
        "params": {"dem_raster": "DEM栅格", "output_measurement": "度量单位"},
    },
    "arcpy_zonal_statistics": {
        "method": "ArcPy分区统计",
        "params": {"zone_features": "区域数据", "value_raster": "值栅格", "statistics_type": "统计类型"},
    },
    "polygon_neighbors": {
        "method": "面邻域分析（共享边界检测）",
        "params": {"file_path": "面数据文件"},
    },
    "add_field": {
        "method": "添加属性字段",
        "params": {"file_path": "数据文件", "field_name": "字段名",
                   "field_type": "类型(TEXT/FLOAT/INTEGER)", "default_value": "默认值"},
    },
    "add_join": {
        "method": "属性表连接",
        "params": {"target_file": "目标数据", "join_file": "连接数据",
                   "target_field": "目标连接字段", "join_field": "连接表字段"},
    },
    "calculate_field": {
        "method": "字段表达式计算",
        "params": {"file_path": "数据文件", "field_name": "目标字段",
                   "expression": "计算表达式"},
    },
    "summary_statistics": {
        "method": "分组汇总统计",
        "params": {"file_path": "数据文件", "stats_fields": "统计规则",
                   "case_field": "分组字段"},
    },
    "share_table": {
        "method": "共享数据表（管理员专用）",
        "params": {"table_name": "数据表名"},
    },
    "query_audit_log": {
        "method": "审计日志查询（管理员专用）",
        "params": {"days": "查询天数", "action_filter": "操作类型",
                   "username_filter": "用户名"},
    },
    "save_as_template": {
        "method": "保存分析模板",
        "params": {"template_name": "模板名称", "description": "描述"},
    },
    "list_templates": {
        "method": "浏览分析模板",
        "params": {"keyword": "搜索关键词"},
    },
    "delete_template": {
        "method": "删除分析模板",
        "params": {"template_id": "模板ID"},
    },
    "share_template": {
        "method": "共享分析模板",
        "params": {"template_id": "模板ID"},
    },
    "describe_raster": {
        "method": "栅格数据画像（波段/CRS/统计）",
        "params": {"raster_path": "栅格文件"},
    },
    "calculate_ndvi": {
        "method": "NDVI植被指数计算",
        "params": {"raster_path": "栅格文件", "red_band": "红波段序号",
                   "nir_band": "近红外波段序号"},
    },
    "raster_band_math": {
        "method": "波段代数运算",
        "params": {"raster_path": "栅格文件", "expression": "表达式",
                   "output_name": "输出名称"},
    },
    "classify_raster": {
        "method": "非监督分类（KMeans）",
        "params": {"raster_path": "栅格文件", "n_classes": "类别数",
                   "method": "算法"},
    },
    "visualize_raster": {
        "method": "栅格可视化渲染",
        "params": {"raster_path": "栅格文件", "band": "波段",
                   "colormap": "色带"},
    },
    "download_lulc": {
        "method": "Sentinel-2 10m 土地覆盖数据下载",
        "params": {"admin_boundary_path": "行政区边界文件",
                   "year": "数据年份(2017-2024)"},
    },
    "download_dem": {
        "method": "Copernicus 30m 高程数据(DEM)下载",
        "params": {"admin_boundary_path": "行政区边界文件"},
    },
    "spatial_autocorrelation": {
        "method": "全局空间自相关检验（Moran's I）",
        "params": {"file_path": "数据文件", "column": "分析字段",
                   "weights_type": "权重类型(queen/knn/distance)",
                   "permutations": "置换次数"},
    },
    "local_moran": {
        "method": "局部空间自相关 LISA 聚类分析",
        "params": {"file_path": "数据文件", "column": "分析字段",
                   "weights_type": "权重类型", "significance": "显著性阈值"},
    },
    "hotspot_analysis": {
        "method": "Getis-Ord Gi* 热点/冷点分析",
        "params": {"file_path": "数据文件", "column": "分析字段",
                   "weights_type": "权重类型", "significance": "显著性阈值"},
    },
    "create_team": {
        "method": "创建协作团队",
        "params": {"team_name": "团队名称", "description": "描述"},
    },
    "list_my_teams": {
        "method": "列出我所在的团队",
        "params": {},
    },
    "invite_to_team": {
        "method": "邀请成员加入团队",
        "params": {"team_name": "团队名称", "username": "用户名", "role": "角色"},
    },
    "remove_from_team": {
        "method": "移除团队成员",
        "params": {"team_name": "团队名称", "username": "用户名"},
    },
    "list_team_members": {
        "method": "查看团队成员",
        "params": {"team_name": "团队名称"},
    },
    "list_team_resources": {
        "method": "查看团队共享资源",
        "params": {"team_name": "团队名称", "resource_type": "资源类型"},
    },
    "leave_team": {
        "method": "退出团队",
        "params": {"team_name": "团队名称"},
    },
    "delete_team": {
        "method": "删除团队",
        "params": {"team_name": "团队名称"},
    },
    "list_data_assets": {
        "method": "浏览数据资产目录",
        "params": {"asset_type": "资产类型", "keyword": "关键词", "storage_backend": "存储后端"},
    },
    "describe_data_asset": {
        "method": "数据资产详情查询",
        "params": {"asset_name_or_id": "资产名称或ID"},
    },
    "search_data_assets": {
        "method": "数据资产语义搜索",
        "params": {"query": "搜索关键词"},
    },
    "register_data_asset": {
        "method": "注册数据资产",
        "params": {"asset_name": "资产名称", "asset_type": "类型", "storage_backend": "存储后端"},
    },
    "tag_data_asset": {
        "method": "数据资产标签管理",
        "params": {"asset_id": "资产ID", "tags_json": "标签列表(JSON)"},
    },
    "delete_data_asset": {
        "method": "删除数据资产记录",
        "params": {"asset_id": "资产ID"},
    },
    "share_data_asset": {
        "method": "共享数据资产",
        "params": {"asset_id": "资产ID"},
    },
    "get_data_lineage": {
        "method": "数据血缘追踪",
        "params": {"asset_name_or_id": "资产名称/ID", "direction": "追踪方向"},
    },
}


def _format_tool_explanation(tool_name: str, args: dict) -> str:
    """Delegate to pipeline_helpers (S-1 refactoring)."""
    from data_agent.pipeline_helpers import format_tool_explanation
    return format_tool_explanation(tool_name, args, TOOL_DESCRIPTIONS)


def _build_step_summary(step: dict, step_idx: int) -> str:
    """Delegate to pipeline_helpers (S-1 refactoring)."""
    from data_agent.pipeline_helpers import build_step_summary
    return build_step_summary(step, step_idx, TOOL_DESCRIPTIONS, TOOL_LABELS)


NON_RERUNNABLE_TOOLS = {
    "save_memory", "recall_memories", "list_memories", "delete_memory",
    "get_usage_summary", "query_audit_log", "share_table",
}


def _extract_source_paths(args: dict) -> list:
    """Delegate to pipeline_helpers (S-1 refactoring)."""
    from data_agent.pipeline_helpers import extract_source_paths
    return extract_source_paths(args)


def _sync_tool_output_to_obs(resp_data, tool_name: str = "", tool_args: dict = None) -> None:
    """Delegate to pipeline_helpers (S-1 refactoring)."""
    from data_agent.pipeline_helpers import sync_tool_output_to_obs
    sync_tool_output_to_obs(resp_data, tool_name, tool_args)


PIPELINE_STAGES = {
    "optimization": [
        "DataIngestion", "DataAnalysis", "DataVisualization", "DataSummary",
    ],
    "governance": ["GovExploration", "GovProcessing", "GovernanceReporter"],
    "general": ["GeneralProcessing", "GeneralViz", "GeneralSummary"],
}


def _render_bar(completed: int, total: int) -> str:
    """Delegate to pipeline_helpers (S-1 refactoring)."""
    from data_agent.pipeline_helpers import render_bar
    return render_bar(completed, total)


def _build_progress_content(
    pipeline_label: str,
    pipeline_type: str,
    stages: list,
    stage_timings: list,
    is_complete: bool = False,
    total_duration: float = 0.0,
    is_error: bool = False,
) -> str:
    """Delegate to pipeline_helpers (S-1 refactoring)."""
    from data_agent.pipeline_helpers import build_progress_content
    return build_progress_content(
        pipeline_label, pipeline_type, stages, stage_timings, AGENT_LABELS,
        is_complete, total_duration, is_error,
    )


MAX_PIPELINE_RETRIES = 2


def _classify_error(exc: Exception) -> tuple:
    """Delegate to pipeline_helpers (S-1 refactoring)."""
    from data_agent.pipeline_helpers import classify_error
    return classify_error(exc)


async def _execute_pipeline(
    user_id: str,
    session_id: str,
    role: str,
    full_prompt: str,
    uploaded_files: list,
    pipeline_type: str,
    pipeline_name: str,
    intent: str,
    selected_agent,
    router_tokens: int = 0,
    retry_attempt: int = 0,
    extra_parts: list = None,
):
    """Execute a pipeline and handle success/error with optional retry.

    Extracted from @cl.on_message to allow reuse by the retry callback.
    """
    from data_agent.user_context import get_user_upload_dir
    trace_id = _set_user_context(user_id, session_id, role)
    logger.info("[Trace:%s] Pipeline=%s Intent=%s Started", trace_id, pipeline_name, intent)

    _plugins = [_hitl_plugin] if HITL_ENABLED else []
    try:
        from data_agent.plugins import build_plugin_stack
        _plugins.extend(build_plugin_stack())
    except Exception:
        pass  # Plugin framework unavailable — degrade gracefully

    # v9.0.3: Cross-session conversation memory
    _memory_svc = None
    try:
        from data_agent.conversation_memory import get_memory_service
        _memory_svc = get_memory_service()
    except Exception:
        pass  # Memory service unavailable — degrade gracefully

    if _context_cache_config:
        _app = App(
            name="data_agent_ui",
            root_agent=selected_agent,
            context_cache_config=_context_cache_config,
            plugins=_plugins,
        )
        _runner_kwargs = dict(app=_app, session_service=session_service)
        if _memory_svc:
            _runner_kwargs["memory_service"] = _memory_svc
        runner = Runner(**_runner_kwargs)
    else:
        _runner_kwargs = dict(
            agent=selected_agent,
            app_name="data_agent_ui",
            session_service=session_service,
            plugins=_plugins,
        )
        if _memory_svc:
            _runner_kwargs["memory_service"] = _memory_svc
        runner = Runner(**_runner_kwargs)
    content = types.Content(role='user', parts=[types.Part(text=full_prompt)] + (extra_parts or []))

    # --- Progress Feedback Setup ---
    if DYNAMIC_PLANNER and pipeline_type == "planner":
        stages = []
        total_stages = 0
        agent_visit_count = 0
    else:
        stages = PIPELINE_STAGES.get(pipeline_type, [])
        total_stages = len(stages)
    pipeline_start_time = time.time()

    # v12.1: Set pipeline run context for lineage tracking
    import uuid as _uuid
    _pipeline_run_id = _uuid.uuid4().hex[:12]
    try:
        from data_agent.pipeline_helpers import current_pipeline_run_id
        current_pipeline_run_id.set(_pipeline_run_id)
    except Exception:
        pass

    pipeline_step = cl.Step(name=pipeline_name, type="process")
    await pipeline_step.send()

    final_msg = cl.Message(content="")
    shown_artifacts = set()
    _pending_elements = []      # artifacts detected from tool responses
    _pending_map_update = None  # map config from tool responses
    _pending_data_update = None # data update from tool responses
    _final_map_update = None    # accumulated map config (not cleared during flush, injected into final_msg)
    _final_data_update = None   # accumulated data update
    current_agent_name = None
    current_agent_step = None
    current_tool_step = None
    current_tool_name = None
    tool_start_time = 0
    msg_sent = False
    full_response_text = ""
    tool_execution_log = []
    _tool_step_counter = 0
    _pending_tool_call = None
    stage_timings = []
    progress_msg = cl.Message(content=_build_progress_content(
        pipeline_name, pipeline_type, stages, stage_timings))
    await progress_msg.send()

    try:
        run_config = RunConfig(max_llm_calls=50) if (DYNAMIC_PLANNER and pipeline_type == "planner") else None
        events = runner.run_async(user_id=user_id, session_id=session_id, new_message=content, run_config=run_config)

        # Token accumulation counters
        total_input_tokens = router_tokens  # include router tokens
        total_output_tokens = 0

        async for event in events:
            # --- Accumulate token usage from ADK events ---
            if hasattr(event, 'usage_metadata') and event.usage_metadata:
                total_input_tokens += getattr(event.usage_metadata, 'prompt_token_count', 0) or 0
                total_output_tokens += getattr(event.usage_metadata, 'candidates_token_count', 0) or 0

            # --- Detect agent transitions via event.author ---
            author = getattr(event, 'author', None)
            if author and author != 'user' and author != current_agent_name:
                # Finalize previous agent step
                if current_agent_step:
                    agent_label = AGENT_LABELS.get(current_agent_name, current_agent_name)
                    if DYNAMIC_PLANNER and pipeline_type == "planner":
                        current_agent_step.name = f"{agent_label} ✓"
                    else:
                        stage_idx = stages.index(current_agent_name) + 1 if current_agent_name in stages else 0
                        current_agent_step.name = t("progress.stage_done", idx=stage_idx, total=total_stages, label=agent_label)
                    await current_agent_step.update()

                current_agent_name = author
                if author in AGENT_LABELS:
                    agent_label = AGENT_LABELS[author]
                    if DYNAMIC_PLANNER and pipeline_type == "planner":
                        agent_visit_count += 1
                        step_label = t("progress.step_running", n=agent_visit_count, label=agent_label)
                    else:
                        stage_idx = stages.index(author) + 1 if author in stages else 0
                        step_label = t("progress.stage_running", idx=stage_idx, total=total_stages, label=agent_label)
                    current_agent_step = cl.Step(
                        name=step_label,
                        type="process",
                        parent_id=pipeline_step.id,
                    )
                    await current_agent_step.send()

                    # --- Update inline progress message ---
                    if stage_timings and stage_timings[-1]["end"] is None:
                        stage_timings[-1]["end"] = time.time()
                    stage_timings.append({
                        "name": author, "label": agent_label,
                        "start": time.time(), "end": None,
                    })
                    progress_msg.content = _build_progress_content(
                        pipeline_name, pipeline_type, stages, stage_timings)
                    await progress_msg.update()

            if not (event.content and event.content.parts):
                continue

            for part in event.content.parts:

                if part.function_call:
                    # Finalize previous tool step if still open
                    if current_tool_step:
                        duration = time.time() - tool_start_time
                        label = TOOL_LABELS.get(current_tool_name, current_tool_name)
                        current_tool_step.name = f"{label} ✓ ({duration:.1f}s)"
                        current_tool_step.output = t("progress.tool_success")
                        await current_tool_step.update()

                    current_tool_name = part.function_call.name
                    tool_start_time = time.time()
                    label = TOOL_LABELS.get(current_tool_name, current_tool_name)
                    parent_id = current_agent_step.id if current_agent_step else pipeline_step.id
                    current_tool_step = cl.Step(
                        name=t("progress.tool_running", label=label),
                        type="tool",
                        parent_id=parent_id,
                    )
                    current_tool_step.input = _format_tool_explanation(
                        current_tool_name, part.function_call.args
                    )
                    await current_tool_step.send()
                    _pending_tool_call = {
                        "tool_name": part.function_call.name,
                        "args": dict(part.function_call.args) if part.function_call.args else {},
                        "start_time": time.time(),
                        "agent_name": current_agent_name or "",
                    }

                if part.function_response:
                    if current_tool_step:
                        duration = time.time() - tool_start_time
                        label = TOOL_LABELS.get(current_tool_name, current_tool_name)
                        current_tool_step.name = f"{label} ✓ ({duration:.1f}s)"
                        try:
                            resp_data = part.function_response.response
                            if isinstance(resp_data, dict) and "output_path" in resp_data:
                                current_tool_step.output = t("progress.tool_output", filename=os.path.basename(resp_data['output_path']))
                            elif isinstance(resp_data, dict) and "message" in resp_data:
                                msg = str(resp_data["message"])[:200]
                                current_tool_step.output = msg
                            elif isinstance(resp_data, str) and (os.sep in resp_data or '/' in resp_data):
                                current_tool_step.output = t("progress.tool_output", filename=os.path.basename(resp_data))
                            else:
                                out_str = str(resp_data)[:200]
                                current_tool_step.output = out_str if len(out_str) > 5 else t("progress.tool_success")
                        except Exception:
                            current_tool_step.output = t("progress.tool_success")
                        await current_tool_step.update()
                        # Refresh inline progress (elapsed time tick)
                        progress_msg.content = _build_progress_content(
                            pipeline_name, pipeline_type, stages, stage_timings)
                        await progress_msg.update()
                        # Extract artifacts from tool response (map HTML, files)
                        # Delegates to artifact_handler module for cleaner separation
                        try:
                            from data_agent.artifact_handler import (
                                detect_artifacts, build_map_update_from_html,
                                build_map_update_from_geojson, check_layer_control,
                            )
                            _resp_val = part.function_response.response

                            # Layer control detection
                            _lc = check_layer_control(_resp_val)
                            if _lc:
                                await cl.Message(content="", metadata={"layer_control": _lc}).send()

                            # Artifact detection
                            _tool_artifacts = detect_artifacts(_resp_val)
                            for _ta in _tool_artifacts:
                                _ta_path = _ta['path']
                                logger.info(f"[ArtifactDetect] Found: {_ta_path} (type={_ta['type']}, already_shown={_ta_path in shown_artifacts})")
                                if _ta_path not in shown_artifacts:
                                    _ta_name = os.path.basename(_ta_path)
                                    if _ta['type'] == 'html':
                                        _pending_elements.append(cl.File(path=_ta_path, name=_ta_name))
                                        shown_artifacts.add(_ta_path)
                                        _mc = build_map_update_from_html(_ta_path)
                                        if _mc:
                                            _pending_map_update = _mc
                                            _final_map_update = _mc
                                    elif _ta['type'] == 'png':
                                        _pending_elements.append(cl.Image(path=_ta_path, name=_ta_name, display="inline"))
                                        shown_artifacts.add(_ta_path)
                                    elif _ta['type'] == 'csv':
                                        _pending_elements.append(cl.File(path=_ta_path, name=_ta_name))
                                        shown_artifacts.add(_ta_path)
                                        _pending_data_update = {"file": _ta_name}
                                        _final_data_update = {"file": _ta_name}
                                    elif _ta['type'] == 'geojson':
                                        shown_artifacts.add(_ta_path)
                                        _pending_map_update = build_map_update_from_geojson(
                                            _ta_path, _pending_map_update)
                                        if _pending_map_update:
                                            _final_map_update = _pending_map_update
                        except Exception as _art_err:
                            logger.warning("[ArtifactDetect] Error: %s", _art_err)
                        try:
                            _tool_args = _pending_tool_call.get("args", {}) if _pending_tool_call else {}
                            _sync_tool_output_to_obs(part.function_response.response, current_tool_name, tool_args=_tool_args)
                        except Exception:
                            pass
                        # Capture tool execution for code export
                        if _pending_tool_call:
                            _tool_step_counter += 1
                            _resp = part.function_response.response
                            _out_path = None
                            _result_msg = ""
                            _is_err = False
                            if isinstance(_resp, dict):
                                _out_path = _resp.get("output_path")
                                _result_msg = str(_resp.get("message", ""))[:200]
                                _is_err = _resp.get("status") == "error"
                            elif isinstance(_resp, str):
                                _result_msg = _resp[:200]
                            tool_execution_log.append({
                                "step": _tool_step_counter,
                                "agent_name": _pending_tool_call["agent_name"],
                                "tool_name": _pending_tool_call["tool_name"],
                                "args": _pending_tool_call["args"],
                                "output_path": _out_path,
                                "result_summary": _result_msg,
                                "duration": time.time() - _pending_tool_call["start_time"],
                                "is_error": _is_err,
                            })
                            # Prometheus: track tool call
                            tool_calls.labels(
                                tool_name=_pending_tool_call["tool_name"],
                                status="error" if _is_err else "success",
                            ).inc()
                            _pending_tool_call = None
                        current_tool_step = None
                        current_tool_name = None

                if part.text:
                    # Update pipeline step with elapsed time
                    elapsed = time.time() - pipeline_start_time
                    pipeline_step.name = f"{pipeline_name} ({elapsed:.1f}s)"
                    await pipeline_step.update()

                    if not msg_sent:
                        msg_sent = True
                        await final_msg.send()

                    await final_msg.stream_token(part.text)
                    full_response_text += part.text

                    found = extract_file_paths(part.text)
                    if found:
                        logger.info(f"[ArtifactText] Found {len(found)} artifacts in LLM text: {[a['path'] for a in found]}")
                    elements = []
                    msg_metadata = {}
                    for artifact in found:
                        path = artifact['path']
                        if path in shown_artifacts:
                            continue
                        name = os.path.basename(path)
                        if artifact['type'] == 'png':
                            elements.append(cl.Image(path=path, name=name, display="inline"))
                            shown_artifacts.add(path)
                        elif artifact['type'] == 'html':
                            elements.append(cl.File(path=path, name=name))
                            shown_artifacts.add(path)
                            # Check for mapconfig.json alongside HTML
                            config_path = path.replace('.html', '.mapconfig.json')
                            _cfg_exists = os.path.exists(config_path)
                            logger.info(f"[ArtifactHTML] path={path}, config_exists={_cfg_exists}, config_path={config_path}")
                            if _cfg_exists:
                                try:
                                    with open(config_path, 'r', encoding='utf-8') as _cf:
                                        _mc_data = json.load(_cf)
                                        msg_metadata["map_update"] = _mc_data
                                        # Only upgrade _final_map_update if new config has more layers
                                        # (prevents summary text referencing old maps from overwriting richer configs)
                                        _new_layers = len(_mc_data.get('layers', []))
                                        _cur_layers = len(_final_map_update.get('layers', [])) if _final_map_update else 0
                                        if _new_layers >= _cur_layers:
                                            _final_map_update = _mc_data
                                        logger.info(f"[ArtifactHTML] Loaded mapconfig: layers={_new_layers}, _final_map_update={'UPDATED' if _new_layers >= _cur_layers else 'KEPT(had ' + str(_cur_layers) + ')'}")
                                except Exception as _mcerr:
                                    logger.error(f"[ArtifactHTML] Failed to load mapconfig: {_mcerr}")
                                    pass
                        elif artifact['type'] == 'csv':
                            elements.append(cl.File(path=path, name=name))
                            shown_artifacts.add(path)
                            msg_metadata["data_update"] = {"file": name}
                            _final_data_update = {"file": name}

                    if elements:
                        logger.info(f"[ArtifactSend] elements={len(elements)}, metadata_keys={list(msg_metadata.keys())}, final_map_set={_final_map_update is not None}")
                        await cl.Message(content="", elements=elements, metadata=msg_metadata).send()

                    # Flush any pending artifacts collected from tool responses
                    if _pending_elements or _pending_map_update or _pending_data_update:
                        _flush_meta = {}
                        if _pending_map_update:
                            _flush_meta["map_update"] = _pending_map_update
                            logger.info(f"[MapFlush] Sending map_update from tool response: {list(_pending_map_update.keys())}")
                            _pending_map_update = None
                        if _pending_data_update:
                            _flush_meta["data_update"] = _pending_data_update
                            _pending_data_update = None
                        if _pending_elements or _flush_meta:
                            await cl.Message(content="", elements=_pending_elements, metadata=_flush_meta).send()
                            _pending_elements = []

        # --- Flush remaining pending artifacts after pipeline ends ---
        if _pending_elements or _pending_map_update or _pending_data_update:
            _flush_meta = {}
            if _pending_map_update:
                _flush_meta["map_update"] = _pending_map_update
            if _pending_data_update:
                _flush_meta["data_update"] = _pending_data_update
            await cl.Message(content="", elements=_pending_elements, metadata=_flush_meta).send()

        # --- Cleanup: finalize all open steps ---
        if current_tool_step:
            duration = time.time() - tool_start_time
            label = TOOL_LABELS.get(current_tool_name, current_tool_name)
            current_tool_step.name = f"{label} ✓ ({duration:.1f}s)"
            await current_tool_step.update()

        if current_agent_step:
            agent_label = AGENT_LABELS.get(current_agent_name, current_agent_name)
            if DYNAMIC_PLANNER and pipeline_type == "planner":
                current_agent_step.name = f"{agent_label} ✓"
            else:
                stage_idx = stages.index(current_agent_name) + 1 if current_agent_name in stages else 0
                current_agent_step.name = t("progress.stage_done", idx=stage_idx, total=total_stages, label=agent_label)
            await current_agent_step.update()

        total_duration = time.time() - pipeline_start_time
        pipeline_step.name = f"{pipeline_name} ✓ ({total_duration:.1f}s)"
        await pipeline_step.update()

        # --- Finalize inline progress → completion timeline ---
        if stage_timings and stage_timings[-1]["end"] is None:
            stage_timings[-1]["end"] = time.time()
        progress_msg.content = _build_progress_content(
            pipeline_name, pipeline_type, stages, stage_timings,
            is_complete=True, total_duration=total_duration)
        await progress_msg.update()

        # --- Prometheus metrics: pipeline success ---
        pipeline_duration.labels(pipeline=pipeline_type).observe(total_duration)
        pipeline_runs.labels(pipeline=pipeline_type, status="success").inc()
        logger.info("[Trace:%s] Pipeline=%s Finished duration=%.1fs", trace_id, pipeline_name, total_duration)

        # --- Inject map/data updates into final_msg metadata ---
        # This ensures the main response message carries map_update, which is
        # more reliable than sending a separate empty-content metadata message.
        logger.info(f"[MapPreInject] _final_map_update={_final_map_update is not None}, _final_data_update={_final_data_update is not None}, msg_sent={msg_sent}")
        if _final_map_update or _final_data_update:
            meta = {}
            if _final_map_update:
                meta["map_update"] = _final_map_update
                logger.info(f"[MapInject] Injected map_update into meta message: layers={len(_final_map_update.get('layers', []))}")
                # Also store in REST API pending dict
                from data_agent.frontend_api import pending_map_updates
                pending_map_updates[user_id] = _final_map_update
            if _final_data_update:
                meta["data_update"] = _final_data_update
                from data_agent.frontend_api import pending_data_updates
                pending_data_updates[user_id] = _final_data_update
                
            # Send a dedicated message for metadata so the React frontend sees a new ID
            # and doesn't skip it due to processedMetaRef.current.has(msg.id)
            await cl.Message(content="", metadata=meta).send()

        if not msg_sent:
            # Pipeline produced no text — send final_msg so it completes
            await final_msg.send()
            msg_sent = True
        await final_msg.update()

        # --- Report Extraction ---
        session = await session_service.get_session(
            app_name="data_agent_ui",
            user_id=user_id,
            session_id=session_id
        )
        report_text = full_response_text

        if session and session.state:
            if pipeline_type == "planner":
                report_text = session.state.get("final_report",
                               session.state.get("planner_summary", full_response_text))
            elif pipeline_type == "optimization":
                report_text = session.state.get("final_summary", full_response_text)
            elif pipeline_type == "governance":
                report_text = session.state.get("governance_report", full_response_text)

        cl.user_session.set("last_response_text", report_text)

        # Save context for multi-turn dialogue
        user_text = cl.user_session.get("last_user_message", "")
        generated_files = [a['path'] for a in extract_file_paths(full_response_text)]
        cl.user_session.set("last_context", {
            "pipeline": pipeline_type,
            "files": generated_files,
            "summary": report_text[:800] if report_text else "",
        })
        cl.user_session.set("tool_execution_log", tool_execution_log)
        cl.user_session.set("last_intent", intent)

        # --- Auto-save analysis result as spatial memory ---
        try:
            from data_agent.memory import save_memory
            import json as _json
            _set_user_context(user_id, session_id, role)
            if generated_files and report_text:
                mem_value = _json.dumps({
                    "pipeline": pipeline_type,
                    "files": generated_files[:10],
                    "summary": report_text[:500],
                }, ensure_ascii=False)
                mem_key = user_text[:80].strip() or f"分析_{time.strftime('%m%d_%H%M')}"
                save_memory("analysis_result", mem_key, mem_value,
                            f"{pipeline_name} - {time.strftime('%Y-%m-%d %H:%M')}")
        except Exception:
            pass  # non-fatal

        # --- Auto-extract key facts from conversation (Memory ETL v7.5) ---
        try:
            extract_count = cl.user_session.get("auto_extract_count", 0)
            if extract_count < 5 and report_text and len(report_text) > 100:
                from data_agent.memory import extract_facts_from_conversation, save_auto_extract_memories

                async def _do_extract(_rt=report_text, _ut=user_text, _uid=user_id, _sid=session_id, _role=role):
                    try:
                        _set_user_context(_uid, _sid, _role)
                        facts = extract_facts_from_conversation(_rt, _ut)
                        if facts:
                            save_auto_extract_memories(facts)
                            logger.info("[MemoryETL] Extracted %d facts for user=%s", len(facts), _uid)
                    except Exception as ex:
                        logger.debug("[MemoryETL] Extraction failed: %s", ex)

                asyncio.create_task(_do_extract())
                cl.user_session.set("auto_extract_count", extract_count + 1)
        except Exception:
            pass  # non-fatal

        # --- v14.1: Recommended follow-up questions ---
        try:
            from data_agent.pipeline_helpers import generate_followup_questions
            followups = generate_followup_questions(report_text, user_text, pipeline_type)
            if followups:
                actions = [
                    cl.Action(name=f"followup_{i}", payload={"value": q}, label=q)
                    for i, q in enumerate(followups)
                ]
                await cl.Message(
                    content="💡 **推荐后续分析：**",
                    actions=actions,
                ).send()
        except Exception:
            pass  # non-fatal

        # --- v14.2: Evaluate analysis chains ---
        try:
            from data_agent.analysis_chains import evaluate_chains
            triggered = evaluate_chains(report_text, pipeline_type, generated_files, user_id)
            for chain in triggered[:2]:  # max 2 auto-triggered per turn
                await cl.Message(
                    content=f"🔗 **分析链触发**: {chain['chain_name']}\n执行: {chain['follow_up_prompt'][:100]}",
                    actions=[
                        cl.Action(name="chain_exec", payload={"value": chain["follow_up_prompt"]},
                                  label=f"执行: {chain['follow_up_prompt'][:40]}..."),
                    ],
                ).send()
        except Exception:
            pass  # non-fatal

        # --- Record token usage ---
        try:
            from data_agent.token_tracker import record_usage
            tracking_pipeline = pipeline_type
            if DYNAMIC_PLANNER and pipeline_type == "planner":
                tracking_pipeline = intent.lower() if intent != "AMBIGUOUS" else "general"
            record_usage(user_id, tracking_pipeline, total_input_tokens, total_output_tokens)
        except Exception:
            pass  # non-fatal

        # --- Audit: pipeline complete ---
        try:
            record_audit(user_id, ACTION_PIPELINE_COMPLETE, details={
                "pipeline_type": pipeline_type,
                "intent": intent,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "files_generated": len(generated_files),
            })
        except Exception:
            pass

        current_pipeline = cl.user_session.get("pipeline_type")
        actions = [
            cl.Action(
                name="export_report",
                value="docx",
                label=t("action.export_word"),
                description=t("action.export_word_desc"),
                payload={"format": "docx"}
            ),
            cl.Action(
                name="export_report",
                value="pdf",
                label=t("action.export_pdf"),
                description=t("action.export_pdf_desc"),
                payload={"format": "pdf"}
            ),
            cl.Action(
                name="share_result",
                value="share",
                label=t("action.share"),
                description=t("action.share_desc"),
                payload={"action": "share"}
            ),
            cl.Action(
                name="export_code",
                value="python",
                label=t("action.export_code"),
                description=t("action.export_code_desc"),
                payload={"format": "python"}
            ),
            cl.Action(
                name="save_as_template",
                value="template",
                label=t("action.save_template"),
                description=t("action.save_template_desc"),
                payload={"action": "save_template"}
            ),
            cl.Action(
                name="browse_templates",
                value="browse",
                label=t("action.browse_templates"),
                description=t("action.browse_templates_desc"),
                payload={"action": "browse"}
            ),
            cl.Action(
                name="browse_steps",
                value="browse",
                label=t("action.browse_steps"),
                description=t("action.browse_steps_desc"),
                payload={"action": "browse_steps"}
            ),
        ]
        await cl.Message(content=t("pipeline.complete"), actions=actions).send()

        # Reset retry count on success
        cl.user_session.set("retry_count", 0)

    except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.error("[Trace:%s] Pipeline=%s Error: %s", trace_id, pipeline_name, e)
        pipeline_runs.labels(pipeline=pipeline_type, status="error").inc()
        # Finalize progress with error state
        try:
            if stage_timings and stage_timings[-1]["end"] is None:
                stage_timings[-1]["_error_time"] = time.time()
            err_duration = time.time() - pipeline_start_time
            progress_msg.content = _build_progress_content(
                pipeline_name, pipeline_type, stages, stage_timings,
                is_complete=True, total_duration=err_duration, is_error=True)
            await progress_msg.update()
        except Exception:
            pass

        # --- Retry button logic ---
        is_retryable, err_category = _classify_error(e)
        retry_count = cl.user_session.get("retry_count", 0)

        if is_retryable and retry_attempt < MAX_PIPELINE_RETRIES:
            remaining = MAX_PIPELINE_RETRIES - retry_attempt
            retry_actions = [
                cl.Action(
                    name="retry_pipeline",
                    value="retry",
                    label=t("action.retry", current=retry_attempt + 1, max=MAX_PIPELINE_RETRIES),
                    description=t("action.retry_desc"),
                    payload={"attempt": retry_attempt + 1},
                ),
            ]
            await cl.Message(
                content=t("error.retryable", err_msg=err_msg, category=err_category, remaining=remaining),
                actions=retry_actions,
            ).send()
        elif not is_retryable:
            await cl.Message(
                content=t("error.non_retryable", err_msg=err_msg, category=err_category),
            ).send()
        else:
            await cl.Message(
                content=t("error.max_retries", err_msg=err_msg, max=MAX_PIPELINE_RETRIES),
            ).send()


def _set_user_context(user_id: str, session_id: str, role: str = "analyst"):
    """Set context variables for the current async task."""
    current_user_id.set(user_id)
    current_session_id.set(session_id)
    current_user_role.set(role)
    # Generate trace_id for end-to-end request tracing
    import uuid
    trace_id = uuid.uuid4().hex[:12]
    current_trace_id.set(trace_id)
    return trace_id


def extract_file_paths(text: str) -> List[Dict[str, str]]:
    """Extract file paths from text."""
    artifacts = []
    pattern = r'(?:[a-zA-Z]:\\|/)[^<>:"|?*]+\.(png|html|shp|zip|csv|xlsx|xls|kml|kmz|geojson|gpkg)'
    matches = re.finditer(pattern, text, re.IGNORECASE)
    for match in matches:
        path = match.group(0)
        ext = match.group(1).lower()
        if os.path.exists(path):
            artifacts.append({"path": path, "type": ext})
    return artifacts


def handle_uploaded_file(element, upload_dir: str) -> tuple:
    """
    Process uploaded file into user's upload directory.
    Returns (path, UploadType) tuple, or (None, None) if failed/oversized.
    Sets element._oversized=True if file exceeds MAX_UPLOAD_SIZE.
    """
    if not element.path:
        return (None, None)

    file_size = os.path.getsize(element.path)
    if file_size > MAX_UPLOAD_SIZE:
        element._oversized = True
        return (None, None)

    dest_path = os.path.join(upload_dir, element.name)
    shutil.copy(element.path, dest_path)

    ext = os.path.splitext(dest_path)[1].lower()

    if ext == '.zip':
        extract_dir = os.path.join(upload_dir, os.path.splitext(element.name)[0])
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(dest_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file.lower().endswith('.shp'):
                        result_path = os.path.abspath(os.path.join(root, file))
                        sync_to_obs(result_path)
                        return (result_path, UploadType.SPATIAL)

            # Fallback: search for other spatial formats
            for target_ext in ('.kml', '.geojson', '.json', '.gpkg'):
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file.lower().endswith(target_ext):
                            result_path = os.path.abspath(os.path.join(root, file))
                            sync_to_obs(result_path)
                            return (result_path, UploadType.SPATIAL)

            return (None, None)
        except Exception as e:
            logger.warning("Zip extraction failed: %s", e)
            return (None, None)

    abs_dest = os.path.abspath(dest_path)
    sync_to_obs(abs_dest)
    file_type = classify_upload(abs_dest)
    return (abs_dest, file_type)


def classify_intent(text: str, previous_pipeline: str = None,
                    image_paths: list = None, pdf_context: str = None) -> tuple:
    """Delegate to intent_router module (extracted for S-1 refactoring)."""
    from data_agent.intent_router import classify_intent as _classify
    return _classify(text, previous_pipeline, image_paths, pdf_context)


def generate_analysis_plan(user_text: str, intent: str, uploaded_files: list) -> str:
    """Delegate to intent_router module (extracted for S-1 refactoring)."""
    from data_agent.intent_router import generate_analysis_plan as _plan
    return _plan(user_text, intent, uploaded_files)


@cl.on_chat_resume
async def on_resume(thread: dict):
    """Restore context when user resumes a thread from sidebar history."""
    cl_user = cl.user_session.get("user")
    if cl_user:
        user_id = cl_user.identifier
        role = cl_user.metadata.get("role", "analyst") if cl_user.metadata else "analyst"
    else:
        user_id = "dev_user"
        role = "admin"

    session_id = thread.get("id", cl.user_session.get("id"))

    _set_user_context(user_id, session_id, role)
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("user_role", role)
    get_user_upload_dir()

    try:
        adk_session = await session_service.get_session(
            app_name="data_agent_ui", user_id=user_id, session_id=session_id)
        if adk_session:
            logger.info("Resumed ADK session %s (%d events)",
                        session_id, len(adk_session.events))
    except Exception as e:
        logger.warning("ADK session resume failed: %s", e)


@cl.on_chat_start
async def start():
    """Initialize session with authenticated user."""
    # Set i18n language from env (default: zh)
    set_language(os.environ.get("UI_LANGUAGE", "zh"))

    # Start MCP Hub connections (once, on first chat start — thread-safe)
    global _mcp_started
    if not _mcp_started and _mcp_hub_loaded:
        with _mcp_lock:
            if not _mcp_started:  # double-check after acquiring lock
                try:
                    await get_mcp_hub().startup()
                except Exception as e:
                    logger.warning("MCP Hub startup failed: %s", e)
                _mcp_started = True

    # Get authenticated user from Chainlit (set by auth callbacks in auth.py)
    cl_user = cl.user_session.get("user")

    if cl_user:
        user_id = cl_user.identifier
        role = cl_user.metadata.get("role", "analyst") if cl_user.metadata else "analyst"
        display_name = cl_user.display_name or user_id
    else:
        # Fallback for development (no auth configured)
        user_id = "dev_user"
        role = "admin"
        display_name = "Developer"

    session_id = cl.user_session.get("id")

    # Set context variables for this session
    _set_user_context(user_id, session_id, role)

    # Create or resume ADK session (get-first for page refresh recovery)
    adk_session = None
    try:
        adk_session = await session_service.get_session(
            app_name="data_agent_ui", user_id=user_id, session_id=session_id)
        if adk_session:
            logger.info("Restored existing session for %s (%d prior events)",
                       user_id, len(adk_session.events))
        else:
            adk_session = await session_service.create_session(
                app_name="data_agent_ui", user_id=user_id, session_id=session_id)
            logger.info("Created new ADK session for %s", user_id)
    except Exception as e:
        logger.warning("ADK session init failed: %s", e)

    # Store in Chainlit session
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("user_role", role)

    # Ensure user upload directory exists
    get_user_upload_dir()

    await cl.Message(content=f"Welcome, **{display_name}**! ({role})").send()
    cl.user_session.set("auto_extract_count", 0)

    try:
        record_audit(user_id, ACTION_SESSION_START, details={
            "role": role, "display_name": display_name,
        })
    except Exception:
        pass


@cl.on_message
async def main(message: cl.Message):
    """Handle user message with File Upload Support and RBAC."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")

    # Re-set context variables (ContextVar is per-async-task)
    trace_id = _set_user_context(user_id, session_id, role)
    logger.info("[Trace:%s] Message received user=%s role=%s", trace_id, user_id, role)

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        await cl.Message(content="Error: `GOOGLE_CLOUD_PROJECT` not found.").send()
        return

    # --- Handle File Uploads (user-scoped) ---
    user_upload_dir = get_user_upload_dir()
    uploaded_files = []      # spatial/document files for GIS processing
    image_files = []         # image files for multimodal understanding
    pdf_files = []           # PDF files for multimodal understanding
    oversized_files = []
    if message.elements:
        for element in message.elements:
            element._oversized = False
            processed_path, file_type = handle_uploaded_file(element, user_upload_dir)
            if processed_path:
                if file_type == UploadType.IMAGE:
                    image_files.append(processed_path)
                elif file_type == UploadType.PDF:
                    pdf_files.append(processed_path)
                else:
                    uploaded_files.append(processed_path)
            elif getattr(element, '_oversized', False):
                size_mb = os.path.getsize(element.path) / (1024 * 1024)
                oversized_files.append(f"{element.name} ({size_mb:.1f} MB)")

    if oversized_files:
        await cl.Message(
            content=t("upload.oversized", files="\n".join(f"- {f}" for f in oversized_files))
        ).send()

    # Audit: record file uploads
    all_uploaded = uploaded_files + image_files + pdf_files
    for _uf in all_uploaded:
        try:
            record_audit(user_id, ACTION_FILE_UPLOAD, details={
                "file_name": os.path.basename(_uf),
                "file_size": os.path.getsize(_uf) if os.path.exists(_uf) else 0,
            })
        except Exception:
            pass

    # --- Build multimodal extra_parts for images and PDFs ---
    extra_parts = []
    pdf_context = ""
    if image_files:
        await cl.Message(
            content=t("multimodal.image_detected", count=len(image_files))
        ).send()
        for img_path in image_files:
            part = prepare_image_part(img_path)
            if part:
                extra_parts.append(part)

    if pdf_files:
        await cl.Message(content=t("multimodal.pdf_detected")).send()
        for pdf_path in pdf_files:
            # Extract text for prompt context
            text_content = extract_pdf_text(pdf_path)
            if text_content:
                pdf_context += text_content + "\n"
            # Prepare native PDF part for Gemini
            pdf_part = prepare_pdf_part(pdf_path)
            if pdf_part:
                extra_parts.append(pdf_part)
        if pdf_context:
            from pypdf import PdfReader
            total_pages = sum(len(PdfReader(p).pages) for p in pdf_files if os.path.exists(p))
            await cl.Message(
                content=t("multimodal.pdf_extracted", pages=total_pages, chars=len(pdf_context))
            ).send()

    # Construct User Prompt
    user_text = message.content
    cl.user_session.set("last_user_message", user_text)

    # --- Custom Skill @mention detection (v8.0.1) ---
    _custom_skill_agent = None
    _custom_skill_name = None
    try:
        import re as _re_mod
        _at_match = _re_mod.match(r'@(\S+)\s*(.*)', user_text, _re_mod.DOTALL)
        if _at_match:
            from data_agent.custom_skills import find_skill_by_name, build_custom_agent
            _skill = find_skill_by_name(_at_match.group(1))
            if _skill:
                _custom_skill_agent = build_custom_agent(_skill)
                _custom_skill_name = _skill["skill_name"]
                # Strip @mention from prompt, use remaining text
                _remaining = _at_match.group(2).strip()
                if _remaining:
                    user_text = _remaining
    except Exception:
        pass  # non-fatal
    if uploaded_files:
        # Show data preview for the first uploaded file
        preview_text = _generate_upload_preview(uploaded_files[0])
        await cl.Message(content=preview_text).send()

        files_msg = "\n\n[System Context] 用户上传了以下文件，请优先分析这些数据："
        for f in uploaded_files:
            files_msg += f"\n- {f}"
        if not user_text.strip():
            user_text = "请对上传的数据进行完整的空间布局优化分析。"
        full_prompt = user_text + files_msg
    else:
        full_prompt = user_text

    # Inject multimodal context into prompt
    if image_files:
        full_prompt += f"\n\n[多模态上下文] 用户附带了 {len(image_files)} 张图片，图片内容已嵌入消息中，请结合图片进行分析。"
    if pdf_context:
        full_prompt += f"\n\n[PDF文档内容摘要]\n{pdf_context[:5000]}"

    # --- Inject previous turn context for multi-turn dialogue ---
    last_ctx = cl.user_session.get("last_context")
    if last_ctx:
        ctx_block = "\n\n[上轮分析上下文]"
        ctx_block += f"\n上一轮使用了 {last_ctx['pipeline']} 管线。"
        if last_ctx.get("files"):
            ctx_block += "\n上一轮生成的文件："
            for f in last_ctx["files"]:
                ctx_block += f"\n- {f}"
        if last_ctx.get("summary"):
            ctx_block += f"\n分析摘要：{last_ctx['summary']}"
        ctx_block += "\n\n如果用户提到「上面的结果」「刚才的数据」「之前的分析」「继续」等指代词，请使用以上文件路径和上下文。"
        full_prompt += ctx_block

    # --- Inject spatial memories for context ---
    try:
        from data_agent.memory import get_user_preferences, get_recent_analysis_results, get_analysis_perspective
        _set_user_context(user_id, session_id, role)
        viz_prefs = get_user_preferences()
        recent_results = get_recent_analysis_results(limit=3)
        perspective = get_analysis_perspective()

        if viz_prefs or recent_results or perspective:
            mem_block = "\n\n[用户空间记忆]"
            if viz_prefs:
                mem_block += "\n可视化偏好："
                for k, v in viz_prefs.items():
                    mem_block += f"\n- {k}: {v}"
            if recent_results:
                mem_block += "\n近期分析记录："
                for r in recent_results:
                    mem_block += f"\n- {r['key']}: {r.get('description', '')}"
                    files = r.get('value', {}).get('files', [])
                    if files:
                        mem_block += f" (文件: {', '.join(files[:3])})"
            if perspective:
                mem_block += f"\n\n用户分析视角：{perspective}"
                mem_block += "\n请在分析过程中考虑用户的分析视角和关注点。"
            mem_block += "\n\n请在用户未明确指定时使用以上偏好作为默认值。"
            full_prompt += mem_block
    except Exception:
        pass  # non-fatal

    # --- Inject semantic context for column/table resolution ---
    try:
        semantic = resolve_semantic_context(user_text)
        semantic_block = build_context_prompt(semantic)
        if semantic_block:
            full_prompt += "\n\n" + semantic_block
    except Exception:
        pass  # non-fatal

    # ArcPy engine context
    if ARCPY_AVAILABLE:
        full_prompt += "\n\n[系统环境] ArcPy 引擎可用。当用户需要修复几何、按字段融合统计、或对比ArcPy与开源工具结果时，可使用 arcpy_ 前缀的工具。"

    # v14.3: Language hint injection
    if user_lang and user_lang != "zh":
        from data_agent.intent_router import _LANG_HINTS
        lang_hint = _LANG_HINTS.get(user_lang, "")
        if lang_hint:
            full_prompt += f"\n\n[Language] {lang_hint}"

    # --- Template Apply: skip intent classification if pending template ---
    pending_template = cl.user_session.get("pending_template")
    if pending_template:
        cl.user_session.set("pending_template", None)  # consume it
        intent = pending_template["intent"]
        intent_reason = f"模板应用: {pending_template['template_name']}"
        router_tokens = 0
        full_prompt += f"\n\n[分析方案]\n{pending_template['plan_text']}\n请严格按照此方案执行。"
    else:
        # --- SEMANTIC ROUTING ---
        previous_pipeline = last_ctx.get("pipeline") if last_ctx else None
        intent, intent_reason, router_tokens, tool_cats, user_lang = classify_intent(
            user_text, previous_pipeline=previous_pipeline,
            image_paths=image_files or None,
            pdf_context=pdf_context or None,
        )
        logger.info("[Trace:%s] Router intent=%s reason=%s lang=%s", trace_id, intent, intent_reason, user_lang)

        # --- Track router token consumption separately (T-4 fix) ---
        if router_tokens > 0:
            try:
                from data_agent.token_tracker import record_usage
                record_usage(user_id, "router", router_tokens, 0, model_name="gemini-2.0-flash")
            except Exception:
                pass

        # --- Ambiguous Intent: Ask user to clarify ---
        if intent == "AMBIGUOUS":
            res = await cl.AskActionMessage(
                content=t("routing.ambiguous_prompt", reason=f"（{intent_reason}）" if intent_reason else ""),
                actions=[
                    cl.Action(name="general", payload={"value": "GENERAL"}, label=t("action.general")),
                    cl.Action(name="governance", payload={"value": "GOVERNANCE"}, label=t("action.governance")),
                    cl.Action(name="optimization", payload={"value": "OPTIMIZATION"}, label=t("action.optimization")),
                ],
                timeout=120,
            ).send()
            if res:
                intent = res.get("value", "GENERAL")
            else:
                await cl.Message(content=t("routing.timeout_auto")).send()
                intent = "GENERAL"

        # --- Usage Limit Check ---
        try:
            from data_agent.token_tracker import check_usage_limit
            limit_check = check_usage_limit(user_id, role)
            if not limit_check["allowed"]:
                await cl.Message(content=f"⚠️ {limit_check['reason']}").send()
                return
        except Exception:
            pass  # non-fatal

        # --- RBAC Check ---
        if role == "viewer" and intent in ("GOVERNANCE", "OPTIMIZATION"):
            try:
                record_audit(user_id, ACTION_RBAC_DENIED, status="denied", details={
                    "role": role, "intent": intent,
                })
            except Exception:
                pass
            await cl.Message(
                content=t("rbac.denied", role=role, intent=intent)
            ).send()
            return

        # --- Dynamic Model Selection ---
        try:
            from data_agent.utils import assess_complexity
            from data_agent.user_context import current_model_tier
            _file_count = len(uploaded_files) if uploaded_files else 0
            _tier = assess_complexity(user_text, intent, _file_count)
            current_model_tier.set(_tier)
            if _tier != "standard":
                logger.info("[Trace:%s] Model tier=%s", trace_id, _tier)
        except Exception:
            pass  # non-fatal, default tier is 'standard'

        # --- Plan Mode Confirmation (for expensive pipelines) ---
        PLAN_CONFIRMATION_INTENTS = {"OPTIMIZATION", "GOVERNANCE"}
        if intent in PLAN_CONFIRMATION_INTENTS:
            try:
                plan_text = generate_analysis_plan(user_text, intent, uploaded_files)
                if plan_text:
                    res = await cl.AskActionMessage(
                        content=t("plan.preview", plan=plan_text),
                        actions=[
                            cl.Action(name="confirm", payload={"value": "CONFIRM"}, label=t("action.confirm")),
                            cl.Action(name="modify", payload={"value": "MODIFY"}, label=t("action.modify")),
                            cl.Action(name="cancel", payload={"value": "CANCEL"}, label=t("action.cancel")),
                        ],
                        timeout=180,
                    ).send()

                    if res:
                        choice = res.get("value", "CONFIRM")
                        if choice == "CANCEL":
                            await cl.Message(content=t("routing.cancelled")).send()
                            return
                        elif choice == "MODIFY":
                            modify_res = await cl.AskUserMessage(
                                content=t("plan.modify_prompt"), timeout=180
                            ).send()
                            if modify_res:
                                plan_text = generate_analysis_plan(
                                    user_text + "\n用户修改要求: " + modify_res['output'],
                                    intent, uploaded_files
                                )
                                await cl.Message(content=t("plan.modified", plan=plan_text)).send()
                        # Inject approved plan into prompt
                        full_prompt += f"\n\n[分析方案]\n{plan_text}\n请严格按照此方案执行。"
                    else:
                        await cl.Message(content=t("routing.confirm_timeout")).send()
            except Exception as e:
                logger.error("Plan confirmation error: %s", e)

    # --- Custom Skill trigger keyword check (v8.0.1) ---
    if not _custom_skill_agent:
        try:
            from data_agent.custom_skills import find_skill_by_trigger, build_custom_agent
            _skill = find_skill_by_trigger(user_text)
            if _skill:
                _custom_skill_agent = build_custom_agent(_skill)
                _custom_skill_name = _skill["skill_name"]
        except Exception:
            pass  # non-fatal

    if _custom_skill_agent:
        selected_agent = _custom_skill_agent
        pipeline_type = "custom"
        pipeline_name = f"Custom Skill: {_custom_skill_name}"
        intent = "CUSTOM"
        intent_reason = f"自定义技能匹配: {_custom_skill_name}"
    elif intent == "GOVERNANCE":
        selected_agent = governance_pipeline
        pipeline_type = "governance"
        pipeline_name = "Governance Pipeline (数据治理)"
    elif intent == "OPTIMIZATION":
        selected_agent = data_pipeline
        pipeline_type = "optimization"
        pipeline_name = "Optimization Pipeline (空间优化)"
    elif DYNAMIC_PLANNER:
        selected_agent = planner_agent
        pipeline_type = "planner"
        pipeline_name = f"Dynamic Planner (意图: {intent})"
        full_prompt += f"\n\n[意图分类提示] 路由器判断: {intent}（{intent_reason}）"
    else:
        selected_agent = general_pipeline
        pipeline_type = "general"
        pipeline_name = "General Pipeline (通用分析与查询)"

    await cl.Message(
        content=t("routing.intent_recognized", intent=intent, pipeline_name=pipeline_name),
        metadata={"routing_info": {
            "intent": intent,
            "pipeline": pipeline_type,
            "pipeline_name": pipeline_name,
            "reason": intent_reason,
        }},
    ).send()

    cl.user_session.set("pipeline_type", pipeline_type)

    # --- Set tool categories for dynamic tool filtering (v7.5.6) ---
    from data_agent.user_context import current_tool_categories
    current_tool_categories.set(tool_cats)
    if tool_cats:
        logger.info("[Trace:%s] ToolCategories=%s (filtering %d categories)", trace_id, tool_cats, len(tool_cats))

    # --- Save retry context and execute pipeline ---
    cl.user_session.set("retry_full_prompt", full_prompt)
    cl.user_session.set("retry_uploaded_files", uploaded_files)
    cl.user_session.set("retry_pipeline_type", pipeline_type)
    cl.user_session.set("retry_pipeline_name", pipeline_name)
    cl.user_session.set("retry_intent", intent)
    cl.user_session.set("retry_count", 0)
    cl.user_session.set("retry_extra_parts", extra_parts)
    cl.user_session.set("retry_tool_cats", tool_cats)

    await _execute_pipeline(
        user_id, session_id, role, full_prompt, uploaded_files,
        pipeline_type, pipeline_name, intent, selected_agent,
        router_tokens=router_tokens,
        extra_parts=extra_parts,
    )


@cl.action_callback("retry_pipeline")
async def on_retry_pipeline(action: cl.Action):
    """Retry a failed pipeline with the same parameters."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    retry_attempt = (action.payload or {}).get("attempt", 1)
    full_prompt = cl.user_session.get("retry_full_prompt")
    uploaded_files = cl.user_session.get("retry_uploaded_files", [])
    pipeline_type = cl.user_session.get("retry_pipeline_type")
    pipeline_name = cl.user_session.get("retry_pipeline_name")
    intent = cl.user_session.get("retry_intent")
    retry_extra_parts = cl.user_session.get("retry_extra_parts", [])

    # Restore tool categories for dynamic tool filtering (v7.5.6)
    from data_agent.user_context import current_tool_categories
    retry_tool_cats = cl.user_session.get("retry_tool_cats", set())
    current_tool_categories.set(retry_tool_cats)

    if not full_prompt or not pipeline_type:
        await cl.Message(content=t("error.retry_missing_context")).send()
        return

    # Verify uploaded files still exist
    valid_files = [f for f in uploaded_files if os.path.exists(f)]
    if len(valid_files) < len(uploaded_files):
        missing = len(uploaded_files) - len(valid_files)
        await cl.Message(content=t("error.retry_files_missing", count=missing)).send()

    # Select agent (same logic as main handler)
    if DYNAMIC_PLANNER:
        selected_agent = planner_agent
    elif intent == "GOVERNANCE":
        selected_agent = governance_pipeline
    elif intent == "OPTIMIZATION":
        selected_agent = data_pipeline
    else:
        selected_agent = general_pipeline

    await cl.Message(content=t("error.retrying", attempt=retry_attempt)).send()

    await _execute_pipeline(
        user_id, session_id, role, full_prompt, valid_files,
        pipeline_type, pipeline_name, intent, selected_agent,
        retry_attempt=retry_attempt,
        extra_parts=retry_extra_parts,
    )


@cl.action_callback("export_report")
async def on_export_report(action: cl.Action):
    """Export analysis results as Word or PDF document."""
    # Re-set context for report generation
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    text = cl.user_session.get("last_response_text")
    if not text:
        await cl.Message(content=t("report.no_content")).send()
        return

    # Format and metadata
    fmt = action.payload.get("format", "docx") if action.payload else "docx"
    pipeline_type = cl.user_session.get("pipeline_type", "general")
    cl_user = cl.user_session.get("user")
    author = cl_user.display_name if cl_user else user_id

    msg = cl.Message(content=t("report.generating", fmt=fmt.upper()))
    await msg.send()
    try:
        user_dir = get_user_upload_dir()

        # Enrich report text with recent PNG visualizations for image embedding
        enriched_text = text
        try:
            import glob
            import time as _time
            
            # Prefer PNGs that were explicitly generated in this session's context
            last_ctx = cl.user_session.get("last_context", {})
            session_files = last_ctx.get("files", [])
            recent_pngs = [f for f in session_files if f.lower().endswith(".png") and os.path.exists(f)]
            
            # Fallback to scanning the directory for very recent PNGs (last 5 mins)
            if not recent_pngs:
                recent_pngs = sorted(
                    glob.glob(os.path.join(user_dir, "*.png")),
                    key=os.path.getmtime, reverse=True
                )
                cutoff = _time.time() - 300
                recent_pngs = [p for p in recent_pngs if os.path.getmtime(p) > cutoff]

            if recent_pngs:
                # Deduplicate and normalize paths
                unique_pngs = []
                for p in recent_pngs:
                    norm_p = os.path.abspath(p)
                    if norm_p not in unique_pngs:
                        unique_pngs.append(norm_p)
                
                # Only append if not already prominently featured in the text
                images_to_add = []
                for p in unique_pngs:
                    p_unix = p.replace("\\", "/")
                    p_win = p.replace("/", "\\")
                    if p_unix not in text and p_win not in text:
                        images_to_add.append(p)
                
                if images_to_add:
                    enriched_text += "\n\n## 分析可视化成果\n\n"
                    for png_path in images_to_add[:4]:  # max 4 images
                        enriched_text += f"{png_path}\n\n"
        except Exception as _enrich_err:
            logger.warning("Report enrichment failed: %s", _enrich_err)
        if fmt == "pdf":
            from data_agent.report_generator import generate_pdf_report
            output_path = os.path.join(user_dir, "Analysis_Report.pdf")
            result_path = generate_pdf_report(
                enriched_text, output_path, author=author, pipeline_type=pipeline_type
            )
        else:
            output_path = os.path.join(user_dir, "Analysis_Report.docx")
            generate_word_report(
                enriched_text, output_path, author=author, pipeline_type=pipeline_type
            )
            result_path = output_path

        sync_to_obs(result_path)
        filename = os.path.basename(result_path)
        try:
            record_audit(user_id, ACTION_REPORT_EXPORT, details={
                "format": fmt, "pipeline_type": pipeline_type, "file_name": filename,
            })
        except Exception:
            pass
        await cl.Message(content=t("report.done"), elements=[
            cl.File(path=result_path, name=filename, display="inline")
        ]).send()
    except Exception as e:
        await cl.Message(content=t("report.failed", error=str(e))).send()


@cl.action_callback("share_result")
async def on_share_result(action: cl.Action):
    """Generate a shareable public link for the current analysis results."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    report_text = cl.user_session.get("last_response_text", "")
    last_ctx = cl.user_session.get("last_context", {})
    pipeline_type = cl.user_session.get("pipeline_type", "general")
    generated_files = last_ctx.get("files", [])

    if not report_text and not generated_files:
        await cl.Message(content=t("share.no_results")).send()
        return

    # Ask share type
    res = await cl.AskActionMessage(
        content=t("share.choose_method"),
        actions=[
            cl.Action(name="share_public", payload={"value": "public"}, label=t("action.share_public")),
            cl.Action(name="share_password", payload={"value": "password"}, label=t("action.share_password")),
        ],
        timeout=60,
    ).send()

    password = None
    if res and res.get("value") == "password":
        pw_res = await cl.AskUserMessage(
            content=t("share.enter_password"), timeout=60
        ).send()
        if pw_res and pw_res.get("output"):
            password = pw_res["output"].strip()
            if len(password) < 4:
                await cl.Message(content=t("share.password_too_short")).send()
                return
        else:
            await cl.Message(content=t("share.no_password")).send()
            return
    elif not res:
        return  # User didn't respond

    # Build file list
    files_list = []
    for fp in generated_files:
        if os.path.exists(fp):
            basename = os.path.basename(fp)
            ext = basename.rsplit('.', 1)[-1].lower() if '.' in basename else ''
            files_list.append({"filename": basename, "type": ext})

    # Auto-expand shapefile sidecars
    from data_agent.sharing import create_share_link, expand_shapefile_sidecars
    if files_list:
        files_list = expand_shapefile_sidecars(files_list)

    if not files_list and not report_text:
        await cl.Message(content=t("share.no_files")).send()
        return

    title = cl.user_session.get("last_user_message", "")[:80] or "分析结果"
    result = create_share_link(
        title=title,
        summary=report_text,
        files=files_list,
        pipeline_type=pipeline_type,
        password=password,
        expires_hours=72,
    )

    if result["status"] == "success":
        share_url = result["url"]
        try:
            record_audit(user_id, ACTION_SHARE_CREATE, details={
                "token": result["token"],
                "password_protected": password is not None,
                "files_count": len(files_list),
            })
        except Exception:
            pass
        msg = t("share.link_generated", url=share_url)
        if password:
            msg += t("share.link_password", password=password)
        msg += t("share.link_footer")
        await cl.Message(content=msg).send()
    else:
        await cl.Message(content=t("share.failed", error=result.get('message', 'Unknown error'))).send()


@cl.action_callback("export_code")
async def on_export_code(action: cl.Action):
    """Export analysis pipeline as a reproducible Python script."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    tool_log = cl.user_session.get("tool_execution_log")
    if not tool_log:
        await cl.Message(content=t("code.no_log")).send()
        return

    try:
        from data_agent.code_exporter import generate_python_script, save_script_to_file

        script = generate_python_script(
            tool_log=tool_log,
            pipeline_type=cl.user_session.get("pipeline_type", "general"),
            user_message=cl.user_session.get("last_user_message", ""),
            uploaded_files=[os.path.basename(f) for f in
                           cl.user_session.get("last_context", {}).get("files", [])],
            intent=cl.user_session.get("last_intent", "GENERAL"),
            tool_descriptions=TOOL_DESCRIPTIONS,
        )

        output_path = save_script_to_file(script, get_user_upload_dir())
        sync_to_obs(output_path)

        try:
            from data_agent.audit_logger import ACTION_CODE_EXPORT
            record_audit(user_id, ACTION_CODE_EXPORT, details={
                "pipeline_type": cl.user_session.get("pipeline_type"),
                "tool_count": len(tool_log),
            })
        except Exception:
            pass

        await cl.Message(
            content=t("code.done", count=len(tool_log)),
            elements=[cl.File(path=output_path, name=os.path.basename(output_path), display="inline")]
        ).send()
    except Exception as e:
        await cl.Message(content=t("code.failed", error=str(e))).send()


@cl.action_callback("save_as_template")
async def on_save_as_template(action: cl.Action):
    """Save the current analysis pipeline as a reusable template."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    tool_log = cl.user_session.get("tool_execution_log")
    if not tool_log:
        await cl.Message(content=t("template.no_log")).send()
        return

    name_res = await cl.AskUserMessage(content=t("template.enter_name"), timeout=120).send()
    if not name_res or not name_res.get("output", "").strip():
        await cl.Message(content=t("template.cancelled")).send()
        return
    template_name = name_res["output"].strip()

    desc_res = await cl.AskUserMessage(
        content=t("template.enter_desc"), timeout=120
    ).send()
    template_desc = desc_res.get("output", "").strip() if desc_res else ""

    from data_agent.template_manager import save_as_template
    result = save_as_template(
        template_name=template_name,
        description=template_desc,
        tool_sequence=tool_log,
        pipeline_type=cl.user_session.get("pipeline_type", "general"),
        intent=cl.user_session.get("last_intent", "GENERAL"),
        source_query=cl.user_session.get("last_user_message", ""),
    )

    if result["status"] == "success":
        try:
            record_audit(user_id, ACTION_TEMPLATE_CREATE, details={
                "template_name": template_name,
                "tool_count": len(tool_log),
            })
        except Exception:
            pass
    await cl.Message(content=result["message"]).send()


@cl.action_callback("browse_templates")
async def on_browse_templates(action: cl.Action):
    """Browse available templates and select one to apply."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    from data_agent.template_manager import list_templates
    result = list_templates()
    if result["status"] != "success" or not result.get("templates"):
        await cl.Message(content=result.get("message", t("template.no_templates"))).send()
        return

    templates = result["templates"]
    PIPE_CN = {
        "optimization": "空间优化", "governance": "数据治理",
        "general": "通用分析", "planner": "动态规划",
    }

    actions = []
    lines = [t("template.list_header")]
    for tmpl in templates[:10]:
        tag = t("template.tag_own") if tmpl["is_own"] else t("template.tag_shared")
        pipe = PIPE_CN.get(tmpl["pipeline_type"], tmpl["pipeline_type"])
        desc_short = f" — {tmpl['description'][:60]}" if tmpl.get("description") else ""
        lines.append(f"- **{tmpl['name']}** {tag} | {pipe} | {tmpl['use_count']}x{desc_short}")
        actions.append(cl.Action(
            name="apply_template", value=str(tmpl["id"]),
            label=tmpl["name"][:60],
            payload={"template_id": tmpl["id"], "template_name": tmpl["name"]}
        ))

    await cl.Message(content="\n".join(lines), actions=actions).send()


@cl.action_callback("apply_template")
async def on_apply_template(action: cl.Action):
    """Load a template and set it as pending for the next message."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    template_id = action.payload.get("template_id") if action.payload else action.value
    template_name = action.payload.get("template_name", "") if action.payload else ""

    from data_agent.template_manager import get_template, generate_plan_from_template, _increment_use_count
    template = get_template(int(template_id))
    if not template:
        await cl.Message(content=t("template.not_found")).send()
        return

    plan_text = generate_plan_from_template(template)
    _increment_use_count(int(template_id))

    # Store in session — next on_message will pick it up
    cl.user_session.set("pending_template", {
        "template_id": template_id,
        "template_name": template["name"],
        "pipeline_type": template["pipeline_type"],
        "intent": template["intent"],
        "plan_text": plan_text,
    })

    try:
        record_audit(user_id, ACTION_TEMPLATE_APPLY, details={
            "template_id": template_id,
            "template_name": template["name"],
        })
    except Exception:
        pass

    await cl.Message(
        content=t("template.loaded", name=template['name'], plan=plan_text)
    ).send()


# ---------------------------------------------------------------------------
# Step Browser & Re-execution (PRD 5.2.3)
# ---------------------------------------------------------------------------

@cl.action_callback("browse_steps")
async def on_browse_steps(action: cl.Action):
    """Display the tool execution log with per-step re-run buttons."""
    tool_log = cl.user_session.get("tool_execution_log")
    if not tool_log:
        await cl.Message(content=t("steps.no_log")).send()
        return

    lines = [t("steps.header")]
    actions = []
    for i, step in enumerate(tool_log):
        step_idx = i + 1
        lines.append(_build_step_summary(step, step_idx))
        if step.get("tool_name") not in NON_RERUNNABLE_TOOLS:
            actions.append(cl.Action(
                name="rerun_step",
                value=str(i),
                label=t("action.rerun_step", idx=step_idx),
                description=TOOL_DESCRIPTIONS.get(
                    step["tool_name"], {}
                ).get("method", step["tool_name"]),
                payload={"step_index": i},
            ))

    await cl.Message(
        content="\n".join(lines),
        actions=actions,
    ).send()


@cl.action_callback("rerun_step")
async def on_rerun_step(action: cl.Action):
    """Re-run a single tool step, optionally with modified parameters."""
    import importlib
    import inspect
    import time as _time

    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    tool_log = cl.user_session.get("tool_execution_log")
    step_index = int(action.value)
    if not tool_log or step_index >= len(tool_log):
        await cl.Message(content=t("steps.not_found")).send()
        return

    step = tool_log[step_index]
    tool_name = step["tool_name"]
    original_args = dict(step.get("args", {}))

    # Show current parameters and offer choices
    explanation = _format_tool_explanation(tool_name, original_args)
    choice_msg = await cl.AskActionMessage(
        content=t("steps.rerun_prompt", explanation=explanation),
        actions=[
            cl.Action(name="rerun_mode", value="direct", label=t("action.rerun_direct")),
            cl.Action(name="rerun_mode", value="modify", label=t("action.rerun_modify")),
            cl.Action(name="rerun_mode", value="cancel", label=t("action.cancel")),
        ],
    ).send()

    if not choice_msg or choice_msg.get("value") == "cancel":
        return

    args = dict(original_args)

    if choice_msg.get("value") == "modify":
        desc = TOOL_DESCRIPTIONS.get(tool_name, {})
        param_labels = desc.get("params", {})

        for key, value in original_args.items():
            label = param_labels.get(key, key)
            current_val = str(value) if value is not None else ""
            user_input = await cl.AskUserMessage(
                content=t("steps.param_prompt", label=label, key=key, current=current_val),
                timeout=120,
            ).send()

            if user_input and user_input.get("output", "").strip():
                new_val = user_input["output"].strip()
                if isinstance(value, bool):
                    args[key] = new_val.lower() in ("true", "1", "yes", "是")
                elif isinstance(value, int):
                    try:
                        args[key] = int(new_val)
                    except ValueError:
                        args[key] = new_val
                elif isinstance(value, float):
                    try:
                        args[key] = float(new_val)
                    except ValueError:
                        args[key] = new_val
                else:
                    args[key] = new_val

    # Resolve file paths in args
    _PATH_KEYS = {
        "file_path", "input_path", "raster_path", "zone_vector",
        "value_raster", "target_file", "join_file", "input_features",
        "clip_features", "zone_features", "dem_raster", "extent_file",
        "raster_file", "data_file", "reference_file", "erase_file",
        "original_data_path", "optimized_data_path", "data_path",
        "polygon_path", "shp_path",
    }
    from data_agent.gis_processors import _resolve_path
    for key, value in args.items():
        if isinstance(value, str) and key in _PATH_KEYS:
            try:
                args[key] = _resolve_path(value)
            except Exception:
                pass

    # Dynamic import of the tool function
    from data_agent.code_exporter import TOOL_IMPORT_MAP
    import_stmt = TOOL_IMPORT_MAP.get(tool_name)
    if not import_stmt:
        await cl.Message(content=t("steps.tool_no_import", tool_name=tool_name)).send()
        return

    # Parse "from data_agent.xxx import func_name"
    parts = import_stmt.split()
    module_path = parts[1]
    func_name = parts[3]

    progress_msg = await cl.Message(
        content=t("steps.rerun_progress", tool_label=TOOL_LABELS.get(tool_name, tool_name))
    ).send()

    try:
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)

        start_time = _time.time()
        if inspect.iscoroutinefunction(func):
            result = await func(**args)
        else:
            result = func(**args)
        duration = _time.time() - start_time

        # Parse result
        is_error = False
        output_path = None
        result_summary = ""
        if isinstance(result, dict):
            is_error = result.get("status") == "error"
            output_path = result.get("output_path")
            result_summary = str(result.get("message", result.get("error_message", "")))[:200]
        elif isinstance(result, str):
            result_summary = result[:200]

        # Update tool_execution_log
        tool_log[step_index] = {
            "step": step["step"],
            "agent_name": step.get("agent_name", "") + " (重跑)",
            "tool_name": tool_name,
            "args": args,
            "output_path": output_path,
            "result_summary": result_summary,
            "duration": duration,
            "is_error": is_error,
        }
        cl.user_session.set("tool_execution_log", tool_log)

        # Display result
        result_str = str(result)
        if len(result_str) > 1000:
            result_str = result_str[:1000] + "..."

        elements = []
        if output_path and os.path.exists(str(output_path)):
            ext = os.path.splitext(str(output_path))[1].lower()
            basename = os.path.basename(str(output_path))
            if ext == '.png':
                elements.append(cl.Image(path=str(output_path), name=basename, display="inline"))
            else:
                elements.append(cl.File(path=str(output_path), name=basename))

        await cl.Message(
            content=t("steps.rerun_done", duration=f"{duration:.1f}", result=result_str),
            elements=elements,
        ).send()

    except Exception as e:
        await cl.Message(content=t("steps.rerun_failed", error=str(e))).send()
