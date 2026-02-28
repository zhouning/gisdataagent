"""
Abstract base class for messaging platform bot integrations.

Provides shared infrastructure for all bot implementations:
- Access token management (TTL-based, thread-safe)
- Sliding window rate limiting
- Message deduplication (MsgId + TTL)
- Headless pipeline execution (classify_intent → run → push results)
- Result delivery with file priority ordering

Subclasses implement platform-specific message sending and route mounting.
"""
import asyncio
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Optional, List


# ---------------------------------------------------------------------------
# Access Token Cache (thread-safe, TTL-based)
# ---------------------------------------------------------------------------

class TokenCache:
    """Thread-safe access token with TTL and early refresh."""

    def __init__(self, buffer_seconds: int = 300):
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._expires_at: float = 0
        self._buffer = buffer_seconds

    @property
    def valid(self) -> bool:
        return self._token is not None and time.time() < self._expires_at

    def get(self) -> Optional[str]:
        if self.valid:
            return self._token
        return None

    def set(self, token: str, expires_in: int = 7200):
        with self._lock:
            self._token = token
            self._expires_at = time.time() + expires_in - self._buffer

    def invalidate(self):
        with self._lock:
            self._token = None
            self._expires_at = 0


# ---------------------------------------------------------------------------
# Sliding Window Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Async-safe sliding window rate limiter."""

    def __init__(self, max_per_minute: int = 18):
        self._max = max_per_minute
        self._window: List[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.time()
            cutoff = now - 60
            self._window = [t for t in self._window if t > cutoff]
            if len(self._window) >= self._max:
                return False
            self._window.append(now)
            return True


# ---------------------------------------------------------------------------
# Message Deduplication
# ---------------------------------------------------------------------------

class MessageDedup:
    """MsgId-based dedup with configurable TTL window."""

    def __init__(self, ttl_seconds: int = 15, max_size: int = 200):
        self._seen: OrderedDict = OrderedDict()
        self._ttl = ttl_seconds
        self._max = max_size

    def is_duplicate(self, msg_id: str) -> bool:
        now = time.time()
        # Cleanup expired entries
        while self._seen and len(self._seen) > self._max:
            self._seen.popitem(last=False)

        cutoff = now - self._ttl
        expired_keys = [k for k, t in self._seen.items() if t < cutoff]
        for k in expired_keys:
            del self._seen[k]

        if msg_id in self._seen:
            return True

        self._seen[msg_id] = now
        return False


# ---------------------------------------------------------------------------
# Markdown Conversion (platform-agnostic simplification)
# ---------------------------------------------------------------------------

def simplify_markdown(text: str, max_length: int = 2048) -> str:
    """Strip unsupported markdown for messaging platforms.

    Removes LaTeX, images, complex tables. Keeps headers, bold, links.
    """
    if not text:
        return ""

    # Remove LaTeX
    text = re.sub(r'\$\$.*?\$\$', '', text, flags=re.DOTALL)
    text = re.sub(r'\$[^$]+\$', '', text)

    # Remove images
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)

    # Simplify tables to plain text
    text = re.sub(r'\|[-:]+\|', '', text)

    # Collapse multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    text = text.strip()
    if len(text) > max_length:
        text = text[:max_length - 10] + "\n...(已截断)"

    return text


# ---------------------------------------------------------------------------
# File Priority
# ---------------------------------------------------------------------------

_EXT_PRIORITY = {
    "png": 0, "pdf": 1, "docx": 2, "html": 3, "csv": 4,
    "xlsx": 5, "shp": 6, "geojson": 7, "tif": 8,
}


def prioritize_files(file_paths: List[str], max_files: int = 3) -> List[str]:
    """Sort and limit files by extension priority (most useful first)."""
    return sorted(
        file_paths,
        key=lambda p: _EXT_PRIORITY.get(
            os.path.splitext(p)[1].lstrip(".").lower(), 99
        ),
    )[:max_files]


# ---------------------------------------------------------------------------
# Abstract Bot Base
# ---------------------------------------------------------------------------

class BotBase(ABC):
    """Abstract base class for messaging platform bot integrations.

    Subclasses must implement:
    - send_text: Send plain text message
    - send_markdown: Send markdown-formatted message
    - send_file: Send a file attachment
    - send_card: Send a clickable card/link
    - mount_routes: Register HTTP callback routes with the app
    - refresh_token: Platform-specific token acquisition
    - platform_name: Human-readable platform name
    """

    def __init__(self, max_msg_per_minute: int = 18, max_file_size: int = 20 * 1024 * 1024):
        self.token_cache = TokenCache()
        self.rate_limiter = RateLimiter(max_per_minute=max_msg_per_minute)
        self.dedup = MessageDedup()
        self.max_file_size = max_file_size

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name (e.g., 'DingTalk', 'Feishu')."""
        ...

    @abstractmethod
    async def refresh_token(self) -> str:
        """Acquire a new access token from the platform API.

        Returns:
            The access token string.
        Raises:
            RuntimeError on failure.
        """
        ...

    @abstractmethod
    async def send_text(self, user_id: str, text: str) -> None:
        """Send a plain text message to a user."""
        ...

    @abstractmethod
    async def send_markdown(self, user_id: str, markdown: str) -> None:
        """Send a markdown-formatted message to a user."""
        ...

    @abstractmethod
    async def send_file(self, user_id: str, file_path: str) -> None:
        """Send a file to a user."""
        ...

    @abstractmethod
    async def send_card(self, user_id: str, title: str, description: str, url: str) -> None:
        """Send a clickable card/link to a user."""
        ...

    @abstractmethod
    def mount_routes(self, app) -> bool:
        """Register HTTP callback routes with the Starlette/FastAPI app.

        Returns:
            True if routes were mounted successfully.
        """
        ...

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        token = self.token_cache.get()
        if token:
            return token
        token = await self.refresh_token()
        return token

    async def handle_message(self, user_id: str, msg_id: str, content: str) -> None:
        """Common message handler: dedup → ack → pipeline → push results.

        Args:
            user_id: Platform-specific user identifier.
            msg_id: Unique message ID for deduplication.
            content: User message text.
        """
        if self.dedup.is_duplicate(msg_id):
            return

        if not content or not content.strip():
            return

        content = content.strip()
        tag = f"[{self.platform_name}]"

        # Rate limit check
        if not await self.rate_limiter.acquire():
            print(f"{tag} Rate limited for {user_id}")
            return

        # ACK receipt
        try:
            await self.send_text(user_id, "正在分析中，请稍候...")
        except Exception as e:
            print(f"{tag} Failed to send ACK: {e}")

        # Run pipeline in background
        asyncio.create_task(self._run_pipeline(user_id, content))

    async def _run_pipeline(self, user_id: str, user_text: str) -> None:
        """Background: run analysis pipeline → push results."""
        tag = f"[{self.platform_name}]"
        try:
            from .auth import ensure_bot_user
            from .user_context import current_user_id, current_session_id, current_user_role
            from .pipeline_runner import run_pipeline_headless

            # Auto-provision user
            user_info = ensure_bot_user(user_id, self.platform_name.lower())
            username = user_info["username"]
            role = user_info["role"]

            # Set context vars
            current_user_id.set(username)
            session_id = f"{self.platform_name.lower()}_{user_id}_{int(time.time())}"
            current_session_id.set(session_id)
            current_user_role.set(role)

            # Import app-level functions (late to avoid circular imports)
            import importlib
            app_mod = importlib.import_module("data_agent.app")
            classify_intent = app_mod.classify_intent
            session_service = app_mod.session_service
            dynamic_planner = getattr(app_mod, "DYNAMIC_PLANNER", False)

            # Classify intent
            intent, reason, router_tokens = classify_intent(user_text)

            # RBAC check
            if role == "viewer" and intent in ("OPTIMIZATION", "GOVERNANCE"):
                await self.send_text(
                    user_id,
                    f"权限不足：您的角色({role})不允许使用{intent}分析管道。"
                )
                try:
                    from .audit_logger import record_audit, ACTION_RBAC_DENIED
                    record_audit(username, ACTION_RBAC_DENIED, status="denied",
                                 details={"intent": intent, "channel": self.platform_name.lower()})
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
                await self.send_text(user_id, f"分析出现错误: {result.error[:500]}")
                return

            # Push markdown report
            if result.report_text:
                md = simplify_markdown(result.report_text)
                if md:
                    try:
                        await self.send_markdown(user_id, md)
                    except Exception:
                        await self.send_text(user_id, md)

            # Push files (priority sorted, max 3)
            files_to_send = prioritize_files(result.generated_files)
            for fpath in files_to_send:
                if os.path.exists(fpath) and os.path.getsize(fpath) < self.max_file_size:
                    try:
                        await self.send_file(user_id, fpath)
                    except Exception as e:
                        print(f"{tag} Failed to send file {fpath}: {e}")

            # Create share link
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
                    base_url = os.environ.get(
                        f"{self.platform_name.upper()}_SHARE_BASE_URL",
                        os.environ.get("WECOM_SHARE_BASE_URL", "")
                    )
                    if base_url and share_url.startswith("/"):
                        share_url = base_url.rstrip("/") + share_url
                    if share_url:
                        await self.send_card(
                            user_id,
                            "查看完整分析结果",
                            result.report_text[:200] if result.report_text else "分析完成",
                            share_url,
                        )
            except Exception as e:
                print(f"{tag} Failed to create share link: {e}")

            # Record audit + token usage
            try:
                from .audit_logger import record_audit
                record_audit(username, "BOT_PIPELINE_COMPLETE", details={
                    "platform": self.platform_name,
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
            print(f"{tag} Pipeline error for {user_id}: {e}")
            try:
                await self.send_text(
                    user_id,
                    f"分析过程中出现异常: {str(e)[:300]}\n请稍后重试或在Web端进行分析。"
                )
            except Exception:
                pass
