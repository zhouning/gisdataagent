"""
Feishu (飞书) / Lark Bot Integration for GIS Data Agent.

Follows the same graceful-degradation pattern as wecom_bot.py:
  - Feature activates only when all FEISHU_* env vars are set.
  - Without them, prints "[Feishu] Not configured. Bot disabled." at startup.

Env vars (all required):
  FEISHU_APP_ID, FEISHU_APP_SECRET
Optional:
  FEISHU_VERIFICATION_TOKEN — for URL verification challenge
  FEISHU_ENCRYPT_KEY — for message encryption (AES-256-CBC)
  FEISHU_SHARE_BASE_URL — base URL for share links
"""
import base64
import hashlib
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
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
]

_API_BASE = "https://open.feishu.cn/open-apis"


def is_feishu_configured() -> bool:
    """Check if all required Feishu env vars are set."""
    return all(os.environ.get(k) for k in _REQUIRED_ENV)


def _get_config() -> dict:
    keys = _REQUIRED_ENV + ["FEISHU_VERIFICATION_TOKEN", "FEISHU_ENCRYPT_KEY"]
    return {k: os.environ.get(k, "") for k in keys}


# ---------------------------------------------------------------------------
# Message Decryption (AES-256-CBC, optional)
# ---------------------------------------------------------------------------

def _decrypt_feishu_message(encrypt_key: str, encrypted: str) -> str:
    """Decrypt Feishu encrypted event body using AES-256-CBC."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        key = hashlib.sha256(encrypt_key.encode()).digest()
        data = base64.b64decode(encrypted)
        iv = data[:16]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(data[16:]) + decryptor.finalize()
        # Remove PKCS7 padding
        pad_len = decrypted[-1]
        decrypted = decrypted[:-pad_len]
        return decrypted.decode("utf-8")
    except ImportError:
        # cryptography not installed — can't decrypt
        raise RuntimeError(
            "cryptography package required for Feishu message decryption. "
            "Install with: pip install cryptography"
        )


# ---------------------------------------------------------------------------
# Feishu Bot Implementation
# ---------------------------------------------------------------------------

class FeishuBot(BotBase):
    """Feishu / Lark bot using the Bot Open API."""

    def __init__(self):
        super().__init__(max_msg_per_minute=50)  # Feishu is more generous

    @property
    def platform_name(self) -> str:
        return "Feishu"

    async def refresh_token(self) -> str:
        """Acquire tenant_access_token from Feishu Internal App API."""
        cfg = _get_config()
        url = f"{_API_BASE}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": cfg["FEISHU_APP_ID"],
            "app_secret": cfg["FEISHU_APP_SECRET"],
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()

        if data.get("code", 0) != 0:
            raise RuntimeError(
                f"Feishu gettoken failed: {data.get('msg', 'unknown')}"
            )

        token = data["tenant_access_token"]
        expires_in = data.get("expire", 7200)
        self.token_cache.set(token, expires_in)
        return token

    async def send_text(self, user_id: str, text: str) -> None:
        """Send plain text message via Feishu Bot API."""
        token = await self.get_token()
        url = f"{_API_BASE}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        params = {"receive_id_type": "open_id"}
        payload = {
            "receive_id": user_id,
            "msg_type": "text",
            "content": json.dumps({"text": text[:4096]}),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            data = resp.json()
            if data.get("code", 0) != 0:
                print(f"[Feishu] send_text failed: {data.get('msg', resp.text[:200])}")

    async def send_markdown(self, user_id: str, markdown: str) -> None:
        """Send an interactive card with markdown content."""
        token = await self.get_token()
        md = simplify_markdown(markdown, max_length=4096)

        url = f"{_API_BASE}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        params = {"receive_id_type": "open_id"}

        # Feishu interactive card with markdown
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "GIS分析结果"},
                "template": "blue",
            },
            "elements": [{
                "tag": "markdown",
                "content": md,
            }],
        }

        payload = {
            "receive_id": user_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            data = resp.json()
            if data.get("code", 0) != 0:
                print(f"[Feishu] send_markdown failed: {data.get('msg', resp.text[:200])}")

    async def send_file(self, user_id: str, file_path: str) -> None:
        """Upload file to Feishu, then send as file message."""
        token = await self.get_token()
        filename = os.path.basename(file_path)

        # 1. Upload file
        upload_url = f"{_API_BASE}/im/v1/files"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                data = {"file_type": "stream", "file_name": filename}
                resp = await client.post(upload_url, headers=headers, files=files, data=data)

            result = resp.json()
            if result.get("code", 0) != 0:
                print(f"[Feishu] file upload failed: {result.get('msg', resp.text[:200])}")
                return

            file_key = result.get("data", {}).get("file_key")
            if not file_key:
                print(f"[Feishu] No file_key in upload response: {result}")
                return

            # 2. Send file message
            send_url = f"{_API_BASE}/im/v1/messages"
            send_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            params = {"receive_id_type": "open_id"}
            payload = {
                "receive_id": user_id,
                "msg_type": "file",
                "content": json.dumps({"file_key": file_key}),
            }
            resp = await client.post(send_url, headers=send_headers, params=params, json=payload)
            data = resp.json()
            if data.get("code", 0) != 0:
                print(f"[Feishu] send_file failed: {data.get('msg', resp.text[:200])}")

    async def send_card(self, user_id: str, title: str, description: str, url: str) -> None:
        """Send an interactive card with a clickable URL button."""
        token = await self.get_token()

        api_url = f"{_API_BASE}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        params = {"receive_id_type": "open_id"}

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": description[:500],
                },
                {
                    "tag": "action",
                    "actions": [{
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看完整结果"},
                        "url": url,
                        "type": "primary",
                    }],
                },
            ],
        }

        payload = {
            "receive_id": user_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(api_url, headers=headers, params=params, json=payload)
            data = resp.json()
            if data.get("code", 0) != 0:
                print(f"[Feishu] send_card failed: {data.get('msg', resp.text[:200])}")

    def mount_routes(self, app) -> bool:
        """Register Feishu callback routes."""
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        bot = self
        cfg = _get_config()

        async def feishu_callback(request: Request):
            """Handle Feishu event callback."""
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"error": "invalid JSON"}, status_code=400)

            # Handle URL verification challenge
            if body.get("type") == "url_verification":
                challenge = body.get("challenge", "")
                return JSONResponse({"challenge": challenge})

            # Decrypt if encrypted
            if "encrypt" in body:
                encrypt_key = cfg.get("FEISHU_ENCRYPT_KEY", "")
                if not encrypt_key:
                    return JSONResponse({"error": "encryption key not configured"}, status_code=500)
                try:
                    decrypted = _decrypt_feishu_message(encrypt_key, body["encrypt"])
                    body = json.loads(decrypted)
                except Exception as e:
                    print(f"[Feishu] Decryption failed: {e}")
                    return JSONResponse({"error": "decryption failed"}, status_code=400)

            # Handle event callback (v2.0 format)
            header = body.get("header", {})
            event = body.get("event", {})
            event_type = header.get("event_type", "")

            if event_type == "im.message.receive_v1":
                message = event.get("message", {})
                msg_type = message.get("message_type", "")
                msg_id = message.get("message_id", str(time.time()))

                if msg_type != "text":
                    return JSONResponse({"status": "ignored", "reason": "only text supported"})

                try:
                    content_obj = json.loads(message.get("content", "{}"))
                    text_content = content_obj.get("text", "").strip()
                except (json.JSONDecodeError, AttributeError):
                    text_content = ""

                sender = event.get("sender", {})
                sender_id = sender.get("sender_id", {}).get("open_id", "")

                if not sender_id or not text_content:
                    return JSONResponse({"status": "ignored"})

                # Handle message
                import asyncio
                asyncio.create_task(bot.handle_message(sender_id, msg_id, text_content))

            return JSONResponse({"status": "ok"})

        route = Route("/feishu/callback", endpoint=feishu_callback, methods=["POST"])

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

_bot_instance: Optional[FeishuBot] = None


def get_feishu_bot() -> Optional[FeishuBot]:
    """Get the singleton FeishuBot instance."""
    return _bot_instance


def ensure_feishu_connection(app=None) -> bool:
    """Initialize Feishu bot if configured. Called at startup.

    Args:
        app: Starlette/FastAPI app to mount routes on.

    Returns:
        True if bot was initialized successfully.
    """
    global _bot_instance

    if not is_feishu_configured():
        missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
        print(f"[Feishu] Not configured. Bot disabled. Missing: {', '.join(missing)}")
        return False

    _bot_instance = FeishuBot()

    if app:
        _bot_instance.mount_routes(app)

    cfg = _get_config()
    print(
        f"[Feishu] Bot configured (AppID={cfg['FEISHU_APP_ID'][:8]}...). "
        f"Callback URL: /feishu/callback"
    )
    return True
