"""
Enterprise WeChat (企业微信) Bot Integration for GIS Data Agent.
Self-built application approach: receive messages via callback → run pipeline → push results.

Follows the obs_storage.py graceful-degradation pattern:
  - Feature activates only when all 5 WECOM_* env vars are set.
  - Without them, prints "[WeCom] Not configured. Bot disabled." at startup.

Env vars (all required):
  WECOM_CORP_ID, WECOM_APP_SECRET, WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_AGENT_ID
Optional:
  WECOM_SHARE_BASE_URL — base URL for share links (e.g., https://gis.example.com)
"""
import asyncio
import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Optional

import httpx

from .wecom_crypto import WXBizMsgCrypt, parse_message_xml

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REQUIRED_ENV = [
    "WECOM_CORP_ID",
    "WECOM_APP_SECRET",
    "WECOM_TOKEN",
    "WECOM_ENCODING_AES_KEY",
    "WECOM_AGENT_ID",
]


def is_wecom_configured() -> bool:
    """Check if all required WECOM env vars are set."""
    return all(os.environ.get(k) for k in _REQUIRED_ENV)


def _get_config() -> dict:
    return {k: os.environ.get(k, "") for k in _REQUIRED_ENV}


# ---------------------------------------------------------------------------
# Access Token Cache (2h TTL, thread-safe)
# ---------------------------------------------------------------------------

_token_lock = threading.Lock()
_cached_token: Optional[str] = None
_token_expires_at: float = 0


async def get_access_token() -> str:
    """
    Get WeCom access token, refreshing if needed.
    Token valid for 7200s; we refresh 300s early.
    """
    global _cached_token, _token_expires_at

    if _cached_token and time.time() < _token_expires_at:
        return _cached_token

    with _token_lock:
        # Double-check after acquiring lock
        if _cached_token and time.time() < _token_expires_at:
            return _cached_token

        cfg = _get_config()
        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={cfg['WECOM_CORP_ID']}"
            f"&corpsecret={cfg['WECOM_APP_SECRET']}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()

        if data.get("errcode", 0) != 0:
            raise RuntimeError(
                f"WeCom gettoken failed: {data.get('errmsg', 'unknown')}"
            )

        _cached_token = data["access_token"]
        _token_expires_at = time.time() + data.get("expires_in", 7200) - 300
        return _cached_token


def invalidate_token():
    """Force token refresh on next call (e.g., after 401)."""
    global _cached_token, _token_expires_at
    _cached_token = None
    _token_expires_at = 0


# ---------------------------------------------------------------------------
# Rate Limiter — sliding window (18 msgs/min, headroom below WeCom 20/min)
# ---------------------------------------------------------------------------

_rate_window: list = []  # timestamps
_RATE_LIMIT = 18
_RATE_PERIOD = 60  # seconds


async def _wait_for_rate_limit():
    """Block until we're under the rate limit."""
    while True:
        now = time.time()
        # Prune old entries
        while _rate_window and _rate_window[0] < now - _RATE_PERIOD:
            _rate_window.pop(0)
        if len(_rate_window) < _RATE_LIMIT:
            _rate_window.append(now)
            return
        # Wait for oldest entry to expire
        sleep_time = _rate_window[0] + _RATE_PERIOD - now + 0.1
        await asyncio.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Message Deduplication (MsgId → timestamp, 15s window)
# ---------------------------------------------------------------------------

_processing_messages: OrderedDict = OrderedDict()
_DEDUP_WINDOW = 15  # seconds


def _is_duplicate(msg_id: str) -> bool:
    """Check if MsgId was seen within dedup window. Returns True if duplicate."""
    if not msg_id:
        return False

    now = time.time()
    # Prune expired entries
    expired = [k for k, v in _processing_messages.items() if now - v > _DEDUP_WINDOW]
    for k in expired:
        _processing_messages.pop(k, None)

    if msg_id in _processing_messages:
        return True
    _processing_messages[msg_id] = now
    return False


# ---------------------------------------------------------------------------
# Send Functions (proactive push via WeCom API)
# ---------------------------------------------------------------------------

async def send_text_message(user_id: str, content: str) -> dict:
    """Send a plain text message to a WeCom user."""
    await _wait_for_rate_limit()
    token = await get_access_token()
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": user_id,
        "msgtype": "text",
        "agentid": int(os.environ.get("WECOM_AGENT_ID", 0)),
        "text": {"content": content[:2048]},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
    if data.get("errcode") == 40014:
        invalidate_token()
    return data


async def send_markdown_message(user_id: str, content: str) -> dict:
    """Send a WeCom-flavored markdown message."""
    await _wait_for_rate_limit()
    token = await get_access_token()
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": user_id,
        "msgtype": "markdown",
        "agentid": int(os.environ.get("WECOM_AGENT_ID", 0)),
        "markdown": {"content": content[:2048]},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
    if data.get("errcode") == 40014:
        invalidate_token()
    return data


async def send_file_message(user_id: str, file_path: str) -> dict:
    """Upload a file to WeCom media, then send as file message."""
    await _wait_for_rate_limit()
    token = await get_access_token()

    # Step 1: upload media
    upload_url = (
        f"https://qyapi.weixin.qq.com/cgi-bin/media/upload"
        f"?access_token={token}&type=file"
    )
    filename = os.path.basename(file_path)
    async with httpx.AsyncClient(timeout=60) as client:
        with open(file_path, "rb") as f:
            files = {"media": (filename, f, "application/octet-stream")}
            resp = await client.post(upload_url, files=files)
            upload_data = resp.json()

    if upload_data.get("errcode", 0) != 0:
        return upload_data

    media_id = upload_data["media_id"]

    # Step 2: send file message
    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": user_id,
        "msgtype": "file",
        "agentid": int(os.environ.get("WECOM_AGENT_ID", 0)),
        "file": {"media_id": media_id},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(send_url, json=payload)
        data = resp.json()
    if data.get("errcode") == 40014:
        invalidate_token()
    return data


async def send_text_card(
    user_id: str, title: str, description: str, url: str
) -> dict:
    """Send a clickable text card message (for share links)."""
    await _wait_for_rate_limit()
    token = await get_access_token()
    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": user_id,
        "msgtype": "textcard",
        "agentid": int(os.environ.get("WECOM_AGENT_ID", 0)),
        "textcard": {
            "title": title[:128],
            "description": description[:512],
            "url": url,
            "btntxt": "查看详情",
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(send_url, json=payload)
        data = resp.json()
    if data.get("errcode") == 40014:
        invalidate_token()
    return data


# ---------------------------------------------------------------------------
# Markdown Conversion (full markdown → WeCom subset)
# ---------------------------------------------------------------------------

def convert_to_wecom_markdown(text: str) -> str:
    """
    Convert full markdown/LaTeX report text to WeCom markdown subset.
    WeCom supports: bold, link, ordered/unordered list, heading (no tables, no images, no LaTeX).
    Truncates to 2048 chars.
    """
    if not text:
        return ""

    # Remove LaTeX
    result = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
    result = re.sub(r'\$[^$]+\$', '', result)

    # Remove images: ![alt](url)
    result = re.sub(r'!\[.*?\]\(.*?\)', '', result)

    # Remove table rows: | col | col |
    result = re.sub(r'^\|.*\|$', '', result, flags=re.MULTILINE)
    # Remove table separator: |---|---|
    result = re.sub(r'^\|[-:| ]+\|$', '', result, flags=re.MULTILINE)

    # Collapse multiple blank lines
    result = re.sub(r'\n{3,}', '\n\n', result)

    result = result.strip()

    # Truncate
    if len(result) > 2048:
        truncate_suffix = "\n...(已截断)"
        result = result[:2048 - len(truncate_suffix)] + truncate_suffix

    return result


# ---------------------------------------------------------------------------
# Message Handler (core logic)
# ---------------------------------------------------------------------------

async def handle_wecom_message(msg: dict) -> None:
    """
    Handle a decrypted WeCom message.
    Called from the POST /wecom/callback route after decryption.
    Runs pipeline in background, pushes results asynchronously.
    """
    msg_type = msg.get("MsgType", "")
    from_user = msg.get("FromUserName", "")
    msg_id = msg.get("MsgId", "")
    content = msg.get("Content", "").strip()

    # Dedup check
    if _is_duplicate(msg_id):
        return

    # Non-text messages
    if msg_type != "text":
        await send_text_message(from_user, "暂仅支持文本消息，请发送文字进行GIS分析。")
        return

    # Strip @bot mention (group chat)
    content = re.sub(r'@\S+\s*', '', content).strip()

    # Empty message
    if not content:
        await send_text_message(
            from_user,
            "欢迎使用GIS数据分析助手！\n"
            "您可以发送如下指令：\n"
            "• 查询数据库中有哪些表\n"
            "• 分析北京市人口密度\n"
            "• 对XX图层做缓冲区分析\n"
            "更多功能请访问Web端。",
        )
        return

    # Send immediate acknowledgment
    await send_text_message(from_user, f"收到，正在分析：「{content[:50]}」...")

    # Spawn background pipeline task
    asyncio.create_task(_run_pipeline_and_push(from_user, content))


async def _run_pipeline_and_push(wecom_userid: str, user_text: str) -> None:
    """Background task: run pipeline → push results to WeChat user."""
    try:
        # Lazy imports to avoid circular dependencies
        from .auth import ensure_wecom_user
        from .user_context import current_user_id, current_session_id, current_user_role
        from .pipeline_runner import run_pipeline_headless, extract_file_paths

        # Auto-provision user
        user_info = ensure_wecom_user(wecom_userid)
        username = user_info["username"]
        role = user_info["role"]

        # Set context vars
        current_user_id.set(username)
        session_id = f"wecom_{wecom_userid}_{int(time.time())}"
        current_session_id.set(session_id)
        current_user_role.set(role)

        # Import app-level classify_intent + agents + session_service
        # We import here to avoid circular imports at module level
        import importlib
        app_mod = importlib.import_module("data_agent.app")
        classify_intent = app_mod.classify_intent
        session_service = app_mod.session_service
        dynamic_planner = getattr(app_mod, "DYNAMIC_PLANNER", False)

        # Classify intent
        intent, reason, router_tokens = classify_intent(user_text)

        # RBAC check
        if role == "viewer" and intent in ("OPTIMIZATION", "GOVERNANCE"):
            await send_text_message(
                wecom_userid,
                f"权限不足：您的角色({role})不允许使用{intent}分析管道。"
            )
            try:
                from .audit_logger import record_audit, ACTION_RBAC_DENIED
                record_audit(username, ACTION_RBAC_DENIED, status="denied",
                             details={"intent": intent, "channel": "wecom"})
            except Exception:
                pass
            return

        # Select agent
        if dynamic_planner:
            selected_agent = app_mod.planner_agent
            pipeline_type = "planner"
        elif intent == "GOVERNANCE":
            selected_agent = app_mod.governance_pipeline
            pipeline_type = "governance"
        elif intent == "OPTIMIZATION":
            selected_agent = app_mod.data_pipeline
            pipeline_type = "optimization"
        else:
            selected_agent = app_mod.general_pipeline
            pipeline_type = "general"

        if dynamic_planner:
            full_prompt = user_text + f"\n\n[意图分类提示] 路由器判断: {intent}（{reason}）"
        else:
            full_prompt = user_text

        # Run headless pipeline
        result = await run_pipeline_headless(
            agent=selected_agent,
            session_service=session_service,
            user_id=username,
            session_id=session_id,
            prompt=full_prompt,
            pipeline_type=pipeline_type,
            intent=intent,
            router_tokens=router_tokens,
            use_dynamic_planner=dynamic_planner,
        )

        if result.error:
            await send_text_message(
                wecom_userid,
                f"分析出现错误: {result.error[:500]}"
            )
            return

        # Push markdown report
        if result.report_text:
            md = convert_to_wecom_markdown(result.report_text)
            if md:
                await send_markdown_message(wecom_userid, md)

        # Push up to 3 files (priority: PNG > PDF > DOCX > HTML > CSV)
        _EXT_PRIORITY = {
            "png": 0, "pdf": 1, "docx": 2, "html": 3, "csv": 4,
            "xlsx": 5, "shp": 6, "geojson": 7, "tif": 8,
        }
        files_to_send = sorted(
            result.generated_files,
            key=lambda p: _EXT_PRIORITY.get(
                os.path.splitext(p)[1].lstrip(".").lower(), 99
            ),
        )[:3]
        for fpath in files_to_send:
            if os.path.exists(fpath) and os.path.getsize(fpath) < 20 * 1024 * 1024:
                try:
                    await send_file_message(wecom_userid, fpath)
                except Exception as e:
                    print(f"[WeCom] Failed to send file {fpath}: {e}")

        # Create share link and push as text card
        try:
            from .sharing import create_share_link
            current_user_id.set(username)
            share_result = create_share_link(
                title=f"GIS分析: {user_text[:40]}",
                summary=result.report_text[:200] if result.report_text else "",
                files=result.generated_files[:10],
                pipeline_type=pipeline_type,
                expires_hours=72,
            )
            if share_result.get("status") == "success":
                share_url = share_result.get("url", "")
                base_url = os.environ.get("WECOM_SHARE_BASE_URL", "")
                if base_url and share_url.startswith("/"):
                    share_url = base_url.rstrip("/") + share_url

                if share_url:
                    await send_text_card(
                        wecom_userid,
                        "查看完整分析结果",
                        result.report_text[:200] if result.report_text else "分析完成",
                        share_url,
                    )
        except Exception as e:
            print(f"[WeCom] Failed to create share link: {e}")

        # Record audit + token usage
        try:
            from .audit_logger import record_audit, ACTION_WECOM_MESSAGE
            record_audit(username, ACTION_WECOM_MESSAGE, details={
                "intent": intent,
                "pipeline_type": pipeline_type,
                "input_tokens": result.total_input_tokens,
                "output_tokens": result.total_output_tokens,
                "files_generated": len(result.generated_files),
                "duration": round(result.duration_seconds, 1),
            })
        except Exception:
            pass

        try:
            from .token_tracker import record_usage
            tracking_pipeline = pipeline_type
            if dynamic_planner and pipeline_type == "planner":
                tracking_pipeline = intent.lower() if intent != "AMBIGUOUS" else "general"
            record_usage(username, tracking_pipeline,
                         result.total_input_tokens, result.total_output_tokens)
        except Exception:
            pass

    except Exception as e:
        print(f"[WeCom] Pipeline error for {wecom_userid}: {e}")
        try:
            await send_text_message(
                wecom_userid,
                f"分析过程中出现异常: {str(e)[:300]}\n请稍后重试或在Web端进行分析。"
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FastAPI/Starlette Routes
# ---------------------------------------------------------------------------

def mount_wecom_routes(app) -> bool:
    """
    Mount WeCom callback routes on the Chainlit/Starlette app.
    Called conditionally from app.py when WECOM vars are configured.
    Returns True if routes were mounted.
    """
    if not is_wecom_configured():
        return False

    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    cfg = _get_config()
    crypto = WXBizMsgCrypt(
        token=cfg["WECOM_TOKEN"],
        encoding_aes_key=cfg["WECOM_ENCODING_AES_KEY"],
        corp_id=cfg["WECOM_CORP_ID"],
    )

    async def wecom_callback_get(request: Request):
        """URL verification callback (GET)."""
        params = request.query_params
        msg_signature = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")
        echostr = params.get("echostr", "")

        ok, result = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
        if ok:
            return PlainTextResponse(result)
        return PlainTextResponse("Verification failed", status_code=403)

    async def wecom_callback_post(request: Request):
        """Message reception callback (POST). Must respond within 5s."""
        params = request.query_params
        msg_signature = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")

        body = (await request.body()).decode("utf-8")

        ok, xml_text = crypto.decrypt_message(
            msg_signature, timestamp, nonce, body
        )
        if not ok:
            return PlainTextResponse("Decrypt failed", status_code=403)

        msg = parse_message_xml(xml_text)

        # Fire-and-forget: handle in background, respond immediately
        asyncio.create_task(handle_wecom_message(msg))

        # Return empty 200 (WeChat requirement)
        return PlainTextResponse("")

    get_route = Route("/wecom/callback", endpoint=wecom_callback_get, methods=["GET"])
    post_route = Route("/wecom/callback", endpoint=wecom_callback_post, methods=["POST"])

    # Insert before Chainlit's catch-all route
    inserted = False
    for i, r in enumerate(app.router.routes):
        if hasattr(r, "path") and r.path == "/{full_path:path}":
            app.router.routes.insert(i, post_route)
            app.router.routes.insert(i, get_route)
            inserted = True
            break
    if not inserted:
        app.router.routes.append(get_route)
        app.router.routes.append(post_route)

    return True


# ---------------------------------------------------------------------------
# Startup health check
# ---------------------------------------------------------------------------

def ensure_wecom_connection() -> None:
    """Startup check: log whether WeCom bot is configured."""
    if is_wecom_configured():
        cfg = _get_config()
        agent_id = cfg.get("WECOM_AGENT_ID", "?")
        print(f"[WeCom] Bot configured (AgentID={agent_id}). "
              "Callback URL: /wecom/callback")
    else:
        missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
        print(f"[WeCom] Not configured. Bot disabled. "
              f"Missing: {', '.join(missing)}")
