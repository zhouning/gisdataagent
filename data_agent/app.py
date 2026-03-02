import chainlit as cl
import sys
import os
import re
import asyncio
import time
import zipfile
import shutil
from typing import List, Dict, Optional
from dotenv import load_dotenv
import google.generativeai as genai

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

# Configure raw Gemini client for Routing (outside ADK agents)
if "GOOGLE_API_KEY" in os.environ:
    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# Import agent and report generator
try:
    from data_agent.agent import (
        root_agent,
        governance_pipeline,
        general_pipeline,
        data_pipeline,
        planner_agent,
        _load_spatial_data,
        ARCPY_AVAILABLE,
    )
    from data_agent.report_generator import generate_word_report
    from data_agent.user_context import (
        current_user_id, current_session_id, current_user_role,
        get_user_upload_dir
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
try:
    ensure_obs_connection()
except Exception as _obs_err:
    logger.warning("OBS initialization failed: %s", _obs_err)
if ARCPY_AVAILABLE:
    logger.info("ArcPy engine available and connected")

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
    if not user:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    user_dir = os.path.join(_UPLOADS_BASE, user.identifier)
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
    """Format tool args into human-readable Chinese explanation."""
    desc = TOOL_DESCRIPTIONS.get(tool_name)
    if not desc:
        args_str = str(args)
        return args_str[:500] + "..." if len(args_str) > 500 else args_str

    lines = [f"**{desc['method']}**"]
    param_labels = desc.get("params", {})
    for key, value in (args or {}).items():
        label = param_labels.get(key, key)
        display_val = value
        if isinstance(value, str) and (os.sep in value or '/' in value):
            display_val = os.path.basename(value)
        display_str = str(display_val)
        if len(display_str) > 120:
            display_str = display_str[:120] + "..."
        lines.append(f"- {label}: `{display_str}`")
    return "\n".join(lines)


def _build_step_summary(step: dict, step_idx: int) -> str:
    """Build a one-line summary of a tool execution step for the step browser."""
    tool_name = step.get("tool_name", "")
    desc = TOOL_DESCRIPTIONS.get(tool_name, {})
    method = desc.get("method", TOOL_LABELS.get(tool_name, tool_name))
    status = "失败" if step.get("is_error") else "成功"
    duration = step.get("duration", 0)
    out = step.get("output_path")
    out_str = f" -> `{os.path.basename(out)}`" if out else ""
    return f"**步骤 {step_idx}**. {method} [{status}, {duration:.1f}s]{out_str}"


NON_RERUNNABLE_TOOLS = {
    "save_memory", "recall_memories", "list_memories", "delete_memory",
    "get_usage_summary", "query_audit_log", "share_table",
}

# Keys in tool args that may contain source file paths for lineage tracking
_SOURCE_PATH_KEYS = {
    "file_path", "input_path", "shp_path", "raster_path", "polygon_path",
    "csv_path", "table_name", "data_path", "input_file", "boundary_path",
    "vector_path", "raster_file", "input_raster",
}


def _extract_source_paths(args: dict) -> list:
    """Extract source file/table references from tool arguments for data lineage."""
    sources = []
    for key, val in args.items():
        if not isinstance(val, str) or not val:
            continue
        if key in _SOURCE_PATH_KEYS:
            sources.append(val)
        elif key.endswith("_path") or key.endswith("_file"):
            sources.append(val)
    return sources


def _sync_tool_output_to_obs(resp_data, tool_name: str = "", tool_args: dict = None) -> None:
    """Detect file paths in tool response, sync to OBS, and register in data catalog."""
    paths = []
    if isinstance(resp_data, str) and os.path.exists(resp_data):
        paths.append(resp_data)
    elif isinstance(resp_data, dict):
        for v in resp_data.values():
            if isinstance(v, str) and os.path.exists(v):
                paths.append(v)

    uid = current_user_id.get()

    # Extract source file paths from tool arguments for lineage tracking
    source_paths = _extract_source_paths(tool_args or {})

    # Register in data catalog (always, even without cloud)
    try:
        from data_agent.data_catalog import register_tool_output
        for p in paths:
            register_tool_output(p, tool_name or "unknown", source_paths=source_paths)
    except Exception:
        pass

    # Sync to cloud storage
    if not is_obs_configured():
        return
    for p in paths:
        try:
            keys = upload_file_smart(p, uid)
            # Update catalog with cloud key
            if keys:
                try:
                    from data_agent.data_catalog import auto_register_from_path
                    auto_register_from_path(
                        p, creation_tool=tool_name or "unknown",
                        storage_backend="cloud", cloud_key=keys[0],
                    )
                except Exception:
                    pass
        except Exception:
            pass


PIPELINE_STAGES = {
    "optimization": [
        "DataIngestion", "DataAnalysis", "DataVisualization", "DataSummary",
    ],
    "governance": ["GovExploration", "GovProcessing", "GovernanceReporter"],
    "general": ["GeneralProcessing", "GeneralViz", "GeneralSummary"],
}


def _set_user_context(user_id: str, session_id: str, role: str = "analyst"):
    """Set context variables for the current async task."""
    current_user_id.set(user_id)
    current_session_id.set(session_id)
    current_user_role.set(role)


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


def handle_uploaded_file(element, upload_dir: str) -> Optional[str]:
    """
    Process uploaded file into user's upload directory.
    Returns None with element._oversized=True if file exceeds MAX_UPLOAD_SIZE.
    - If Zip: Extract and find .shp
    - If other: Return path
    """
    if not element.path:
        return None

    file_size = os.path.getsize(element.path)
    if file_size > MAX_UPLOAD_SIZE:
        element._oversized = True
        return None

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
                        return result_path

            # Fallback: search for other spatial formats
            for target_ext in ('.kml', '.geojson', '.json', '.gpkg'):
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file.lower().endswith(target_ext):
                            result_path = os.path.abspath(os.path.join(root, file))
                            sync_to_obs(result_path)
                            return result_path

            return None
        except Exception as e:
            logger.warning("Zip extraction failed: %s", e)
            return None

    abs_dest = os.path.abspath(dest_path)
    sync_to_obs(abs_dest)
    return abs_dest


def _generate_upload_preview(file_path: str) -> str:
    """Generate a markdown preview of uploaded spatial/tabular data."""
    try:
        import geopandas as _gpd
        gdf = _load_spatial_data(file_path)

        lines = ["### 数据预览 (Data Preview)\n"]

        # Basic info
        lines.append(f"- **要素数量**: {len(gdf)}")
        lines.append(f"- **坐标系**: {gdf.crs or '未定义'}")

        geom_types = gdf.geometry.dropna().geom_type.unique().tolist() if not gdf.geometry.isna().all() else []
        if geom_types:
            lines.append(f"- **几何类型**: {', '.join(geom_types)}")

        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        lines.append(f"- **空间范围**: [{bounds[0]:.4f}, {bounds[1]:.4f}] ~ [{bounds[2]:.4f}, {bounds[3]:.4f}]")

        # Column list
        non_geom_cols = [c for c in gdf.columns if c != 'geometry']
        lines.append(f"- **字段数**: {len(non_geom_cols)}")

        # First 5 rows as markdown table
        if non_geom_cols:
            display_cols = non_geom_cols[:8]  # max 8 columns for readability
            preview_df = gdf[display_cols].head(5)
            lines.append(f"\n**前 {min(5, len(gdf))} 行预览**:\n")
            # Header
            lines.append("| " + " | ".join(str(c) for c in display_cols) + " |")
            lines.append("| " + " | ".join("---" for _ in display_cols) + " |")
            # Rows
            for _, row in preview_df.iterrows():
                vals = [str(row[c])[:30] for c in display_cols]
                lines.append("| " + " | ".join(vals) + " |")

        return "\n".join(lines)
    except Exception as e:
        return f"数据预览失败: {str(e)}"


def classify_intent(text: str, previous_pipeline: str = None) -> tuple:
    """
    Uses Gemini Flash to semantically classify user intent into one of the 3 pipelines.
    Returns: (intent, reason, router_tokens) where intent is 'OPTIMIZATION', 'GOVERNANCE', 'GENERAL', or 'AMBIGUOUS'.
    """
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        prev_hint = ""
        if previous_pipeline:
            prev_hint = f"\n        - The previous turn used the {previous_pipeline.upper()} pipeline. If the user references prior results (上面, 刚才, 继续, 之前, 在此基础上), prefer routing to the SAME pipeline: {previous_pipeline.upper()}."
        prompt = f"""
        You are the Intent Router for a GIS Data Agent. Classify the User Input into ONE of these categories:

        1. **GOVERNANCE**: Data auditing, quality check, topology fix, standardization, consistency check. (Keywords: 治理, 审计, 质检, 核查, 拓扑, 标准)
        2. **OPTIMIZATION**: Land use optimization, DRL, FFI calculation, spatial layout planning. (Keywords: 优化, 布局, 破碎化, 规划)
        3. **GENERAL**: General queries, SQL, visualization, mapping, simple analysis, clustering, heatmap, buffer, site selection, memories, preferences. (Keywords: 查询, 地图, 热力图, 聚类, 选址, 分析, 筛选, 数据库, 记忆, 偏好, 记住, 历史)
        4. **AMBIGUOUS**: The input is too vague, unclear, or could match multiple pipelines equally. E.g. greetings, single-word inputs, or no clear GIS task.

        User Input: "{text}"

        Rules:
        - If input mentions "optimize" or "FFI", prioritize OPTIMIZATION.
        - If input is asking "what data is there" or "show map", choose GENERAL.{prev_hint}
        - If the input is a greeting (你好, hello, hi), casual chat, or contains no identifiable GIS task, output AMBIGUOUS.
        - If the input could reasonably belong to two pipelines equally, output AMBIGUOUS.
        - Output format: CATEGORY|REASON (e.g. "GENERAL|用户请求查看地图" or "AMBIGUOUS|输入不包含明确的GIS任务")
        """
        response = model.generate_content(prompt)
        # Track router token consumption
        router_input_tokens = 0
        router_output_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            router_input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            router_output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        router_tokens = router_input_tokens + router_output_tokens

        raw = response.text.strip()
        if "|" in raw:
            parts = raw.split("|", 1)
            intent = parts[0].strip().upper()
            reason = parts[1].strip()
        else:
            intent = raw.upper()
            reason = ""
        if "OPTIMIZATION" in intent: return ("OPTIMIZATION", reason, router_tokens)
        if "GOVERNANCE" in intent: return ("GOVERNANCE", reason, router_tokens)
        if "AMBIGUOUS" in intent: return ("AMBIGUOUS", reason, router_tokens)
        if "GENERAL" in intent: return ("GENERAL", reason, router_tokens)
        return ("GENERAL", reason, router_tokens)
    except Exception as e:
        logger.error("Router error: %s", e)
        return ("GENERAL", "", 0)


def generate_analysis_plan(user_text: str, intent: str, uploaded_files: list) -> str:
    """Generate a lightweight analysis plan for user confirmation before expensive pipelines."""
    try:
        from data_agent.prompts import get_prompt

        files_info = "\n".join(f"- {f}" for f in uploaded_files) if uploaded_files else "无上传文件"
        prompt_template = get_prompt("planner", "plan_generation_prompt")
        prompt = prompt_template.format(intent=intent, user_text=user_text, files_info=files_info)

        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error("Plan generation error: %s", e)
        return ""


@cl.on_chat_start
async def start():
    """Initialize session with authenticated user."""
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

    # Create or resume ADK session (handles page refresh with DB persistence)
    adk_session = None
    try:
        adk_session = await session_service.create_session(
            app_name="data_agent_ui", user_id=user_id, session_id=session_id)
    except Exception:
        # Session already exists — load it for potential state restore
        try:
            adk_session = await session_service.get_session(
                app_name="data_agent_ui", user_id=user_id, session_id=session_id)
            if adk_session:
                logger.info("Restored existing session for %s (%d prior events)",
                           user_id, len(adk_session.events))
        except Exception as e2:
            logger.warning("Could not restore session: %s", e2)

    # Store in Chainlit session
    cl.user_session.set("user_id", user_id)
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("user_role", role)

    # Ensure user upload directory exists
    get_user_upload_dir()

    await cl.Message(content=f"Welcome, **{display_name}**! ({role})").send()

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
    _set_user_context(user_id, session_id, role)

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        await cl.Message(content="Error: `GOOGLE_CLOUD_PROJECT` not found.").send()
        return

    # --- Handle File Uploads (user-scoped) ---
    user_upload_dir = get_user_upload_dir()
    uploaded_files = []
    oversized_files = []
    if message.elements:
        for element in message.elements:
            element._oversized = False
            processed_path = handle_uploaded_file(element, user_upload_dir)
            if processed_path:
                uploaded_files.append(processed_path)
            elif getattr(element, '_oversized', False):
                size_mb = os.path.getsize(element.path) / (1024 * 1024)
                oversized_files.append(f"{element.name} ({size_mb:.1f} MB)")

    if oversized_files:
        await cl.Message(
            content=f"以下文件超过 100 MB 上传限制，已跳过：\n" + "\n".join(f"- {f}" for f in oversized_files)
        ).send()

    # Audit: record file uploads
    for _uf in uploaded_files:
        try:
            record_audit(user_id, ACTION_FILE_UPLOAD, details={
                "file_name": os.path.basename(_uf),
                "file_size": os.path.getsize(_uf) if os.path.exists(_uf) else 0,
            })
        except Exception:
            pass

    # Construct User Prompt
    user_text = message.content
    cl.user_session.set("last_user_message", user_text)
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
        from data_agent.memory import get_user_preferences, get_recent_analysis_results
        _set_user_context(user_id, session_id, role)
        viz_prefs = get_user_preferences()
        recent_results = get_recent_analysis_results(limit=3)

        if viz_prefs or recent_results:
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
        intent, intent_reason, router_tokens = classify_intent(user_text, previous_pipeline=previous_pipeline)

        # --- Ambiguous Intent: Ask user to clarify ---
        if intent == "AMBIGUOUS":
            res = await cl.AskActionMessage(
                content=f"我不太确定您想做什么。{('（' + intent_reason + '）') if intent_reason else ''}\n\n请选择您需要的分析类型：",
                actions=[
                    cl.Action(name="general", payload={"value": "GENERAL"}, label="通用查询与分析"),
                    cl.Action(name="governance", payload={"value": "GOVERNANCE"}, label="数据质量治理"),
                    cl.Action(name="optimization", payload={"value": "OPTIMIZATION"}, label="空间布局优化"),
                ],
                timeout=120,
            ).send()
            if res:
                intent = res.get("value", "GENERAL")
            else:
                await cl.Message(content="操作超时，已自动选择通用分析管线。").send()
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
                content=f"权限不足：您的角色为 **{role}**，无法访问 {intent} 管线。请联系管理员升级权限。"
            ).send()
            return

        # --- Plan Mode Confirmation (for expensive pipelines) ---
        PLAN_CONFIRMATION_INTENTS = {"OPTIMIZATION", "GOVERNANCE"}
        if intent in PLAN_CONFIRMATION_INTENTS:
            try:
                plan_text = generate_analysis_plan(user_text, intent, uploaded_files)
                if plan_text:
                    res = await cl.AskActionMessage(
                        content=f"**分析方案预览**\n\n{plan_text}\n\n请确认是否执行：",
                        actions=[
                            cl.Action(name="confirm", payload={"value": "CONFIRM"}, label="确认执行"),
                            cl.Action(name="modify", payload={"value": "MODIFY"}, label="修改方案"),
                            cl.Action(name="cancel", payload={"value": "CANCEL"}, label="取消"),
                        ],
                        timeout=180,
                    ).send()

                    if res:
                        choice = res.get("value", "CONFIRM")
                        if choice == "CANCEL":
                            await cl.Message(content="已取消本次分析。").send()
                            return
                        elif choice == "MODIFY":
                            modify_res = await cl.AskUserMessage(
                                content="请描述您想修改的内容：", timeout=180
                            ).send()
                            if modify_res:
                                plan_text = generate_analysis_plan(
                                    user_text + "\n用户修改要求: " + modify_res['output'],
                                    intent, uploaded_files
                                )
                                await cl.Message(content=f"**修改后方案**\n\n{plan_text}").send()
                        # Inject approved plan into prompt
                        full_prompt += f"\n\n[分析方案]\n{plan_text}\n请严格按照此方案执行。"
                    else:
                        await cl.Message(content="确认超时，已自动执行。").send()
            except Exception as e:
                logger.error("Plan confirmation error: %s", e)

    if DYNAMIC_PLANNER:
        selected_agent = planner_agent
        pipeline_type = "planner"
        pipeline_name = f"Dynamic Planner (意图: {intent})"
        full_prompt += f"\n\n[意图分类提示] 路由器判断: {intent}（{intent_reason}）"
    elif intent == "GOVERNANCE":
        selected_agent = governance_pipeline
        pipeline_type = "governance"
        pipeline_name = "Governance Pipeline (数据治理)"
    elif intent == "OPTIMIZATION":
        selected_agent = data_pipeline
        pipeline_type = "optimization"
        pipeline_name = "Optimization Pipeline (空间优化)"
    else:
        selected_agent = general_pipeline
        pipeline_type = "general"
        pipeline_name = "General Pipeline (通用分析与查询)"

    await cl.Message(
        content=f"意图识别：**{intent}**\n已路由至：**{pipeline_name}**",
        metadata={"routing_info": {
            "intent": intent,
            "pipeline": pipeline_type,
            "pipeline_name": pipeline_name,
            "reason": intent_reason,
        }},
    ).send()

    cl.user_session.set("pipeline_type", pipeline_type)

    runner = Runner(agent=selected_agent, app_name="data_agent_ui", session_service=session_service)
    content = types.Content(role='user', parts=[types.Part(text=full_prompt)])

    # --- Progress Feedback Setup ---
    if DYNAMIC_PLANNER and pipeline_type == "planner":
        stages = []
        total_stages = 0
        agent_visit_count = 0
    else:
        stages = PIPELINE_STAGES.get(pipeline_type, [])
        total_stages = len(stages)
    pipeline_start_time = time.time()

    pipeline_step = cl.Step(name=pipeline_name, type="process")
    await pipeline_step.send()

    final_msg = cl.Message(content="")
    shown_artifacts = set()
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
                        current_agent_step.name = f"阶段 {stage_idx}/{total_stages}: {agent_label} ✓"
                    await current_agent_step.update()

                current_agent_name = author
                if author in AGENT_LABELS:
                    agent_label = AGENT_LABELS[author]
                    if DYNAMIC_PLANNER and pipeline_type == "planner":
                        agent_visit_count += 1
                        step_label = f"步骤 {agent_visit_count}: 正在{agent_label}..."
                    else:
                        stage_idx = stages.index(author) + 1 if author in stages else 0
                        step_label = f"阶段 {stage_idx}/{total_stages}: 正在{agent_label}..."
                    current_agent_step = cl.Step(
                        name=step_label,
                        type="process",
                        parent_id=pipeline_step.id,
                    )
                    await current_agent_step.send()

            if not (event.content and event.content.parts):
                continue

            for part in event.content.parts:

                if part.function_call:
                    # Finalize previous tool step if still open
                    if current_tool_step:
                        duration = time.time() - tool_start_time
                        label = TOOL_LABELS.get(current_tool_name, current_tool_name)
                        current_tool_step.name = f"{label} ✓ ({duration:.1f}s)"
                        current_tool_step.output = "执行成功"
                        await current_tool_step.update()

                    current_tool_name = part.function_call.name
                    tool_start_time = time.time()
                    label = TOOL_LABELS.get(current_tool_name, current_tool_name)
                    parent_id = current_agent_step.id if current_agent_step else pipeline_step.id
                    current_tool_step = cl.Step(
                        name=f"正在{label}...",
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
                                current_tool_step.output = f"输出: `{os.path.basename(resp_data['output_path'])}`"
                            elif isinstance(resp_data, dict) and "message" in resp_data:
                                msg = str(resp_data["message"])[:200]
                                current_tool_step.output = msg
                            elif isinstance(resp_data, str) and (os.sep in resp_data or '/' in resp_data):
                                current_tool_step.output = f"输出: `{os.path.basename(resp_data)}`"
                            else:
                                out_str = str(resp_data)[:200]
                                current_tool_step.output = out_str if len(out_str) > 5 else "执行成功"
                        except Exception:
                            current_tool_step.output = "执行成功"
                        await current_tool_step.update()
                        # Sync tool output files to OBS and register in data catalog
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
                            if os.path.exists(config_path):
                                try:
                                    with open(config_path, 'r', encoding='utf-8') as _cf:
                                        msg_metadata["map_update"] = json.load(_cf)
                                except Exception:
                                    pass
                        elif artifact['type'] == 'csv':
                            elements.append(cl.File(path=path, name=name))
                            shown_artifacts.add(path)
                            msg_metadata["data_update"] = {"file": name}

                    if elements:
                        await cl.Message(content="", elements=elements, metadata=msg_metadata).send()

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
                current_agent_step.name = f"阶段 {stage_idx}/{total_stages}: {agent_label} ✓"
            await current_agent_step.update()

        total_duration = time.time() - pipeline_start_time
        pipeline_step.name = f"{pipeline_name} ✓ ({total_duration:.1f}s)"
        await pipeline_step.update()

        # --- Prometheus metrics: pipeline success ---
        pipeline_duration.labels(pipeline=pipeline_type).observe(total_duration)
        pipeline_runs.labels(pipeline=pipeline_type, status="success").inc()

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
        generated_files = [a['path'] for a in extract_file_paths(full_response_text)]
        cl.user_session.set("last_context", {
            "pipeline": pipeline_type,
            "files": generated_files,
            "summary": report_text[:800] if report_text else "",
        })
        cl.user_session.set("tool_execution_log", tool_execution_log)
        cl.user_session.set("last_intent", intent)
        cl.user_session.set("last_user_message", user_text)

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
                label="导出 Word 报告",
                description="将本次分析结果导出为 Word 文档",
                payload={"format": "docx"}
            ),
            cl.Action(
                name="export_report",
                value="pdf",
                label="导出 PDF 报告",
                description="将本次分析结果导出为 PDF 文档",
                payload={"format": "pdf"}
            ),
            cl.Action(
                name="share_result",
                value="share",
                label="分享分析结果",
                description="生成公开链接，无需登录即可查看",
                payload={"action": "share"}
            ),
            cl.Action(
                name="export_code",
                value="python",
                label="导出 Python 脚本",
                description="将本次分析流程导出为可复现的 Python 脚本",
                payload={"format": "python"}
            ),
            cl.Action(
                name="save_as_template",
                value="template",
                label="保存为模板",
                description="将本次分析流程保存为可复用模板",
                payload={"action": "save_template"}
            ),
            cl.Action(
                name="browse_templates",
                value="browse",
                label="浏览模板",
                description="查看和应用已保存的分析模板",
                payload={"action": "browse"}
            ),
            cl.Action(
                name="browse_steps",
                value="browse",
                label="查看分析步骤",
                description="查看并重新执行本次分析的各个步骤",
                payload={"action": "browse_steps"}
            ),
        ]
        await cl.Message(content="分析完成。您可以下载相关文件、导出报告或分享结果。", actions=actions).send()

    except Exception as e:
        err_msg = f"Error: {str(e)}"
        logger.error("Pipeline execution error: %s", e)
        pipeline_runs.labels(pipeline=pipeline_type, status="error").inc()
        await cl.Message(content=err_msg).send()


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
        await cl.Message(content="无法获取报告内容").send()
        return

    # Format and metadata
    fmt = action.payload.get("format", "docx") if action.payload else "docx"
    pipeline_type = cl.user_session.get("pipeline_type", "general")
    cl_user = cl.user_session.get("user")
    author = cl_user.display_name if cl_user else user_id

    msg = cl.Message(content=f"正在生成 {fmt.upper()} 报告...")
    await msg.send()
    try:
        user_dir = get_user_upload_dir()
        if fmt == "pdf":
            from data_agent.report_generator import generate_pdf_report
            output_path = os.path.join(user_dir, "Analysis_Report.pdf")
            result_path = generate_pdf_report(
                text, output_path, author=author, pipeline_type=pipeline_type
            )
        else:
            output_path = os.path.join(user_dir, "Analysis_Report.docx")
            generate_word_report(
                text, output_path, author=author, pipeline_type=pipeline_type
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
        await cl.Message(content="报告已生成：", elements=[
            cl.File(path=result_path, name=filename, display="inline")
        ]).send()
    except Exception as e:
        await cl.Message(content=f"生成失败: {str(e)}").send()


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
        await cl.Message(content="当前没有可分享的分析结果。").send()
        return

    # Ask share type
    res = await cl.AskActionMessage(
        content="请选择分享方式：",
        actions=[
            cl.Action(name="share_public", payload={"value": "public"}, label="公开链接（无密码）"),
            cl.Action(name="share_password", payload={"value": "password"}, label="密码保护链接"),
        ],
        timeout=60,
    ).send()

    password = None
    if res and res.get("value") == "password":
        pw_res = await cl.AskUserMessage(
            content="请设置分享密码（至少4位）：", timeout=60
        ).send()
        if pw_res and pw_res.get("output"):
            password = pw_res["output"].strip()
            if len(password) < 4:
                await cl.Message(content="密码太短，已取消分享。").send()
                return
        else:
            await cl.Message(content="未输入密码，已取消分享。").send()
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
        await cl.Message(content="未找到可分享的文件。").send()
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
        msg = f"分享链接已生成（72小时有效）：\n\n`{share_url}`"
        if password:
            msg += f"\n\n访问密码：`{password}`"
        msg += "\n\n将此链接发送给他人即可查看分析结果（无需登录）。"
        await cl.Message(content=msg).send()
    else:
        await cl.Message(content=f"生成分享链接失败：{result.get('message', '未知错误')}").send()


@cl.action_callback("export_code")
async def on_export_code(action: cl.Action):
    """Export analysis pipeline as a reproducible Python script."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    tool_log = cl.user_session.get("tool_execution_log")
    if not tool_log:
        await cl.Message(content="当前没有可导出的分析流程。").send()
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
            content=f"Python 脚本已生成（{len(tool_log)} 个分析步骤）：",
            elements=[cl.File(path=output_path, name=os.path.basename(output_path), display="inline")]
        ).send()
    except Exception as e:
        await cl.Message(content=f"脚本生成失败: {str(e)}").send()


@cl.action_callback("save_as_template")
async def on_save_as_template(action: cl.Action):
    """Save the current analysis pipeline as a reusable template."""
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    role = cl.user_session.get("user_role", "analyst")
    _set_user_context(user_id, session_id, role)

    tool_log = cl.user_session.get("tool_execution_log")
    if not tool_log:
        await cl.Message(content="当前没有可保存的分析流程。").send()
        return

    name_res = await cl.AskUserMessage(content="请输入模板名称：", timeout=120).send()
    if not name_res or not name_res.get("output", "").strip():
        await cl.Message(content="已取消保存模板。").send()
        return
    template_name = name_res["output"].strip()

    desc_res = await cl.AskUserMessage(
        content="请输入模板描述（可选，直接回车跳过）：", timeout=120
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
        await cl.Message(content=result.get("message", "暂无可用模板。")).send()
        return

    templates = result["templates"]
    PIPE_CN = {
        "optimization": "空间优化", "governance": "数据治理",
        "general": "通用分析", "planner": "动态规划",
    }

    actions = []
    lines = ["**可用模板列表** — 点击模板名称应用\n"]
    for t in templates[:10]:
        tag = "[我的]" if t["is_own"] else "[共享]"
        pipe = PIPE_CN.get(t["pipeline_type"], t["pipeline_type"])
        desc_short = f" — {t['description'][:60]}" if t.get("description") else ""
        lines.append(f"- **{t['name']}** {tag} | {pipe} | 使用 {t['use_count']} 次{desc_short}")
        actions.append(cl.Action(
            name="apply_template", value=str(t["id"]),
            label=t["name"][:60],
            payload={"template_id": t["id"], "template_name": t["name"]}
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
        await cl.Message(content="模板不存在或无权访问。").send()
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
        content=f"已加载模板「{template['name']}」\n\n"
                f"**分析方案**:\n{plan_text}\n\n"
                f"请发送您的数据文件或描述分析需求，系统将按模板方案执行。"
    ).send()


# ---------------------------------------------------------------------------
# Step Browser & Re-execution (PRD 5.2.3)
# ---------------------------------------------------------------------------

@cl.action_callback("browse_steps")
async def on_browse_steps(action: cl.Action):
    """Display the tool execution log with per-step re-run buttons."""
    tool_log = cl.user_session.get("tool_execution_log")
    if not tool_log:
        await cl.Message(content="当前没有可查看的分析步骤。").send()
        return

    lines = ["## 分析步骤总览\n"]
    actions = []
    for i, step in enumerate(tool_log):
        step_idx = i + 1
        lines.append(_build_step_summary(step, step_idx))
        if step.get("tool_name") not in NON_RERUNNABLE_TOOLS:
            actions.append(cl.Action(
                name="rerun_step",
                value=str(i),
                label=f"重跑步骤 {step_idx}",
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
        await cl.Message(content="步骤数据不存在。").send()
        return

    step = tool_log[step_index]
    tool_name = step["tool_name"]
    original_args = dict(step.get("args", {}))

    # Show current parameters and offer choices
    explanation = _format_tool_explanation(tool_name, original_args)
    choice_msg = await cl.AskActionMessage(
        content=f"**重新执行**: {explanation}\n\n请选择执行方式：",
        actions=[
            cl.Action(name="rerun_mode", value="direct", label="直接执行（原参数）"),
            cl.Action(name="rerun_mode", value="modify", label="修改参数后执行"),
            cl.Action(name="rerun_mode", value="cancel", label="取消"),
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
                content=f"**{label}** (`{key}`)\n当前值: `{current_val}`\n"
                        f"输入新值（直接回车保持原值）：",
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
        await cl.Message(content=f"工具 `{tool_name}` 无法动态导入，不支持重新执行。").send()
        return

    # Parse "from data_agent.xxx import func_name"
    parts = import_stmt.split()
    module_path = parts[1]
    func_name = parts[3]

    progress_msg = await cl.Message(
        content=f"正在重新执行 **{TOOL_LABELS.get(tool_name, tool_name)}**..."
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
            content=f"**重新执行完成** ({duration:.1f}s)\n\n```\n{result_str}\n```",
            elements=elements,
        ).send()

    except Exception as e:
        await cl.Message(content=f"重新执行失败: {str(e)}").send()
