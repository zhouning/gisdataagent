"""
DingTalk (钉钉) Bot Integration for GIS Data Agent.

Follows the same graceful-degradation pattern as wecom_bot.py:
  - Feature activates only when all DINGTALK_* env vars are set.
  - Without them, prints "[DingTalk] Not configured. Bot disabled." at startup.

Env vars (all required):
  DINGTALK_APP_KEY, DINGTALK_APP_SECRET, DINGTALK_ROBOT_CODE
Optional:
  DINGTALK_SHARE_BASE_URL — base URL for share links
"""
import hashlib
import hmac
import base64
import json
import os
import time
from typing import Optional

import httpx

from .bot_base import BotBase, simplify_markdown

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_REQUIRED_ENV = [
    "DINGTALK_APP_KEY",
    "DINGTALK_APP_SECRET",
    "DINGTALK_ROBOT_CODE",
]

_API_BASE = "https://api.dingtalk.com"


def is_dingtalk_configured() -> bool:
    """Check if all required DingTalk env vars are set."""
    return all(os.environ.get(k) for k in _REQUIRED_ENV)


def _get_config() -> dict:
    return {k: os.environ.get(k, "") for k in _REQUIRED_ENV}


# ---------------------------------------------------------------------------
# DingTalk Bot Implementation
# ---------------------------------------------------------------------------

class DingTalkBot(BotBase):
    """DingTalk bot using the Robot API (v1.0)."""

    def __init__(self):
        super().__init__(max_msg_per_minute=20)

    @property
    def platform_name(self) -> str:
        return "DingTalk"

    async def refresh_token(self) -> str:
        """Acquire access token from DingTalk OAuth2 endpoint."""
        cfg = _get_config()
        url = f"{_API_BASE}/v1.0/oauth2/accessToken"
        payload = {
            "appKey": cfg["DINGTALK_APP_KEY"],
            "appSecret": cfg["DINGTALK_APP_SECRET"],
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()

        if "accessToken" not in data:
            raise RuntimeError(
                f"DingTalk gettoken failed: {data.get('message', data.get('errmsg', 'unknown'))}"
            )

        token = data["accessToken"]
        expires_in = data.get("expireIn", 7200)
        self.token_cache.set(token, expires_in)
        return token

    async def send_text(self, user_id: str, text: str) -> None:
        """Send plain text message via DingTalk Robot API."""
        token = await self.get_token()
        cfg = _get_config()

        url = f"{_API_BASE}/v1.0/robot/oToMessages/batchSend"
        headers = {"x-acs-dingtalk-access-token": token}
        payload = {
            "robotCode": cfg["DINGTALK_ROBOT_CODE"],
            "userIds": [user_id],
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": text[:2048]}),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code not in (200, 201):
                print(f"[DingTalk] send_text failed: {resp.status_code} {resp.text[:200]}")

    async def send_markdown(self, user_id: str, markdown: str) -> None:
        """Send markdown message via DingTalk Robot API."""
        token = await self.get_token()
        cfg = _get_config()

        # DingTalk markdown subset is similar to WeChat Enterprise
        md = simplify_markdown(markdown, max_length=2048)

        url = f"{_API_BASE}/v1.0/robot/oToMessages/batchSend"
        headers = {"x-acs-dingtalk-access-token": token}
        payload = {
            "robotCode": cfg["DINGTALK_ROBOT_CODE"],
            "userIds": [user_id],
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({
                "title": "GIS分析结果",
                "text": md,
            }),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code not in (200, 201):
                print(f"[DingTalk] send_markdown failed: {resp.status_code} {resp.text[:200]}")

    async def send_file(self, user_id: str, file_path: str) -> None:
        """Upload file to DingTalk media store, then send as file message."""
        token = await self.get_token()
        cfg = _get_config()

        # 1. Upload to media
        filename = os.path.basename(file_path)
        upload_url = f"{_API_BASE}/v1.0/robot/messageFiles/upload"
        headers = {"x-acs-dingtalk-access-token": token}

        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                data = {"robotCode": cfg["DINGTALK_ROBOT_CODE"]}
                resp = await client.post(upload_url, headers=headers, files=files, data=data)

            if resp.status_code not in (200, 201):
                print(f"[DingTalk] file upload failed: {resp.status_code} {resp.text[:200]}")
                return

            result = resp.json()
            media_id = result.get("mediaId")
            if not media_id:
                print(f"[DingTalk] No mediaId in upload response: {result}")
                return

            # 2. Send file message
            send_url = f"{_API_BASE}/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": cfg["DINGTALK_ROBOT_CODE"],
                "userIds": [user_id],
                "msgKey": "sampleFile",
                "msgParam": json.dumps({
                    "mediaId": media_id,
                    "fileName": filename,
                    "fileType": os.path.splitext(filename)[1].lstrip("."),
                }),
            }
            resp = await client.post(send_url, headers=headers, json=payload)
            if resp.status_code not in (200, 201):
                print(f"[DingTalk] send_file failed: {resp.status_code} {resp.text[:200]}")

    async def send_card(self, user_id: str, title: str, description: str, url: str) -> None:
        """Send an action card with a clickable URL."""
        token = await self.get_token()
        cfg = _get_config()

        api_url = f"{_API_BASE}/v1.0/robot/oToMessages/batchSend"
        headers = {"x-acs-dingtalk-access-token": token}
        payload = {
            "robotCode": cfg["DINGTALK_ROBOT_CODE"],
            "userIds": [user_id],
            "msgKey": "sampleActionCard",
            "msgParam": json.dumps({
                "title": title,
                "text": description[:500],
                "singleTitle": "查看结果",
                "singleURL": url,
            }),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(api_url, headers=headers, json=payload)
            if resp.status_code not in (200, 201):
                print(f"[DingTalk] send_card failed: {resp.status_code} {resp.text[:200]}")

    def mount_routes(self, app) -> bool:
        """Register DingTalk callback routes."""
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse, JSONResponse
        from starlette.routing import Route

        bot = self

        async def dingtalk_callback(request: Request):
            """Handle DingTalk bot callback messages."""
            if request.method == "GET":
                return PlainTextResponse("ok")

            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"error": "invalid JSON"}, status_code=400)

            # Extract message
            msg_type = body.get("msgtype", "")
            if msg_type != "text":
                return JSONResponse({"status": "ignored", "reason": "only text supported"})

            text_content = body.get("text", {}).get("content", "").strip()
            sender_id = body.get("senderStaffId", "")
            msg_id = body.get("msgId", body.get("chatbotCorpId", str(time.time())))

            if not sender_id or not text_content:
                return JSONResponse({"status": "ignored"})

            # Handle message
            import asyncio
            asyncio.create_task(bot.handle_message(sender_id, msg_id, text_content))

            return JSONResponse({"status": "ok"})

        route = Route("/dingtalk/callback", endpoint=dingtalk_callback, methods=["GET", "POST"])

        # Insert before Chainlit catch-all
        for i, r in enumerate(app.router.routes):
            if hasattr(r, "path") and r.path == "/{full_path:path}":
                app.router.routes.insert(i, route)
                return True

        app.router.routes.append(route)
        return True


# ---------------------------------------------------------------------------
# Singleton & Startup
# ---------------------------------------------------------------------------

_bot_instance: Optional[DingTalkBot] = None


def get_dingtalk_bot() -> Optional[DingTalkBot]:
    """Get the singleton DingTalkBot instance."""
    return _bot_instance


def ensure_dingtalk_connection(app=None) -> bool:
    """Initialize DingTalk bot if configured. Called at startup.

    Args:
        app: Starlette/FastAPI app to mount routes on.

    Returns:
        True if bot was initialized successfully.
    """
    global _bot_instance

    if not is_dingtalk_configured():
        missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
        print(f"[DingTalk] Not configured. Bot disabled. Missing: {', '.join(missing)}")
        return False

    _bot_instance = DingTalkBot()

    if app:
        _bot_instance.mount_routes(app)

    cfg = _get_config()
    print(
        f"[DingTalk] Bot configured (RobotCode={cfg['DINGTALK_ROBOT_CODE'][:8]}...). "
        f"Callback URL: /dingtalk/callback"
    )
    return True
