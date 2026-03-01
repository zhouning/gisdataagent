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
import os
import re
from typing import Optional

import httpx

from .bot_base import BotBase, simplify_markdown
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
# WeCom-specific Markdown (strips all table rows unlike simplify_markdown)
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
# WeComBot — inherits shared infrastructure from BotBase
# ---------------------------------------------------------------------------

class WeComBot(BotBase):
    """Enterprise WeChat bot built on shared BotBase infrastructure."""

    def __init__(self):
        super().__init__(max_msg_per_minute=18)

    @property
    def platform_name(self) -> str:
        return "WeCom"

    async def refresh_token(self) -> str:
        """Acquire WeCom access token via gettoken API."""
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

        token = data["access_token"]
        expires_in = data.get("expires_in", 7200)
        self.token_cache.set(token, expires_in)
        return token

    def _agent_id(self) -> int:
        return int(os.environ.get("WECOM_AGENT_ID", 0))

    async def _post_message(self, payload: dict) -> dict:
        """Send a message via WeCom message API. Handles token invalidation on 40014."""
        token = await self.get_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
        if data.get("errcode") == 40014:
            self.token_cache.invalidate()
        return data

    async def send_text(self, user_id: str, text: str) -> None:
        await self._post_message({
            "touser": user_id,
            "msgtype": "text",
            "agentid": self._agent_id(),
            "text": {"content": text[:2048]},
        })

    async def send_markdown(self, user_id: str, markdown: str) -> None:
        md = convert_to_wecom_markdown(markdown)
        if not md:
            return
        await self._post_message({
            "touser": user_id,
            "msgtype": "markdown",
            "agentid": self._agent_id(),
            "markdown": {"content": md},
        })

    async def send_file(self, user_id: str, file_path: str) -> None:
        token = await self.get_token()
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
            print(f"[WeCom] Media upload failed: {upload_data.get('errmsg', '')}")
            return

        await self._post_message({
            "touser": user_id,
            "msgtype": "file",
            "agentid": self._agent_id(),
            "file": {"media_id": upload_data["media_id"]},
        })

    async def send_card(self, user_id: str, title: str, description: str, url: str) -> None:
        await self._post_message({
            "touser": user_id,
            "msgtype": "textcard",
            "agentid": self._agent_id(),
            "textcard": {
                "title": title[:128],
                "description": description[:512],
                "url": url,
                "btntxt": "查看详情",
            },
        })

    def mount_routes(self, app) -> bool:
        """Mount WeCom callback routes on the Starlette/FastAPI app."""
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
        bot = self  # Capture for closures

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
            msg_type = msg.get("MsgType", "")
            from_user = msg.get("FromUserName", "")
            msg_id = msg.get("MsgId", "")
            content = msg.get("Content", "").strip()

            # Non-text messages
            if msg_type != "text":
                asyncio.create_task(
                    bot.send_text(from_user, "暂仅支持文本消息，请发送文字进行GIS分析。")
                )
                return PlainTextResponse("")

            # Strip @bot mention (group chat)
            content = re.sub(r'@\S+\s*', '', content).strip()

            # Empty message — send help
            if not content:
                asyncio.create_task(
                    bot.send_text(
                        from_user,
                        "欢迎使用GIS数据分析助手！\n"
                        "您可以发送如下指令：\n"
                        "• 查询数据库中有哪些表\n"
                        "• 分析北京市人口密度\n"
                        "• 对XX图层做缓冲区分析\n"
                        "更多功能请访问Web端。",
                    )
                )
                return PlainTextResponse("")

            # Delegate to shared handle_message (dedup + ACK + pipeline)
            asyncio.create_task(bot.handle_message(from_user, msg_id, content))
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
# Module-level Singleton & Backward-compat Functions
# ---------------------------------------------------------------------------

_bot: Optional[WeComBot] = None


def mount_wecom_routes(app) -> bool:
    """Mount WeCom callback routes. Creates bot singleton if needed."""
    global _bot
    if _bot is None:
        _bot = WeComBot()
    return _bot.mount_routes(app)


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
