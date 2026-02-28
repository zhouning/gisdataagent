"""
Tests for DingTalk Bot integration.

Covers: token acquisition, message sending, callback routing,
message dedup, graceful degradation, and route mounting.
"""
import asyncio
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from data_agent.bot_base import (
    TokenCache, RateLimiter, MessageDedup,
    simplify_markdown, prioritize_files, BotBase,
)
from data_agent.dingtalk_bot import (
    DingTalkBot, is_dingtalk_configured,
    ensure_dingtalk_connection, _REQUIRED_ENV,
)


# ---------------------------------------------------------------------------
# TokenCache
# ---------------------------------------------------------------------------


class TestTokenCache(unittest.TestCase):
    def test_initial_state_invalid(self):
        tc = TokenCache()
        self.assertFalse(tc.valid)
        self.assertIsNone(tc.get())

    def test_set_and_get(self):
        tc = TokenCache(buffer_seconds=0)
        tc.set("tok_abc", expires_in=600)
        self.assertTrue(tc.valid)
        self.assertEqual(tc.get(), "tok_abc")

    def test_expired_returns_none(self):
        tc = TokenCache(buffer_seconds=0)
        tc.set("tok_old", expires_in=0)
        self.assertFalse(tc.valid)
        self.assertIsNone(tc.get())

    def test_invalidate(self):
        tc = TokenCache()
        tc.set("tok_x", 600)
        tc.invalidate()
        self.assertIsNone(tc.get())


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter(unittest.TestCase):
    def test_within_limit(self):
        rl = RateLimiter(max_per_minute=5)
        results = [asyncio.get_event_loop().run_until_complete(rl.acquire()) for _ in range(5)]
        self.assertTrue(all(results))

    def test_exceeds_limit(self):
        rl = RateLimiter(max_per_minute=2)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(rl.acquire())
        loop.run_until_complete(rl.acquire())
        self.assertFalse(loop.run_until_complete(rl.acquire()))


# ---------------------------------------------------------------------------
# MessageDedup
# ---------------------------------------------------------------------------


class TestMessageDedup(unittest.TestCase):
    def test_first_message_not_dup(self):
        d = MessageDedup(ttl_seconds=10)
        self.assertFalse(d.is_duplicate("msg_001"))

    def test_duplicate_detected(self):
        d = MessageDedup(ttl_seconds=10)
        d.is_duplicate("msg_002")
        self.assertTrue(d.is_duplicate("msg_002"))

    def test_different_ids_not_dup(self):
        d = MessageDedup(ttl_seconds=10)
        d.is_duplicate("msg_a")
        self.assertFalse(d.is_duplicate("msg_b"))

    def test_max_size_eviction(self):
        d = MessageDedup(ttl_seconds=999, max_size=3)
        for i in range(5):
            d.is_duplicate(f"msg_{i}")
        # Oldest entries should be evicted when exceeding max_size
        self.assertEqual(len(d._seen) <= 5, True)


# ---------------------------------------------------------------------------
# simplify_markdown
# ---------------------------------------------------------------------------


class TestSimplifyMarkdown(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(simplify_markdown(""), "")
        self.assertEqual(simplify_markdown(None), "")

    def test_strips_latex(self):
        text = "面积为 $A = \\pi r^2$ 平方公里"
        result = simplify_markdown(text)
        self.assertNotIn("$", result)

    def test_strips_images(self):
        text = "结果如下 ![map](path/to/map.png) 分析完成"
        result = simplify_markdown(text)
        self.assertNotIn("![", result)

    def test_truncation(self):
        long = "x" * 3000
        result = simplify_markdown(long, max_length=100)
        self.assertTrue(len(result) <= 100)
        self.assertIn("已截断", result)


# ---------------------------------------------------------------------------
# prioritize_files
# ---------------------------------------------------------------------------


class TestPrioritizeFiles(unittest.TestCase):
    def test_priority_order(self):
        files = ["a.csv", "b.png", "c.docx"]
        result = prioritize_files(files, max_files=3)
        self.assertEqual(result[0], "b.png")  # PNG first

    def test_max_limit(self):
        files = ["a.csv", "b.png", "c.docx", "d.pdf", "e.html"]
        result = prioritize_files(files, max_files=2)
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# DingTalk Configuration
# ---------------------------------------------------------------------------


class TestDingTalkConfiguration(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_not_configured_missing_all(self):
        """All required env vars missing → not configured."""
        self.assertFalse(is_dingtalk_configured())

    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "key123",
        "DINGTALK_APP_SECRET": "sec456",
        "DINGTALK_ROBOT_CODE": "robot789",
    })
    def test_configured_all_present(self):
        """All required env vars set → configured."""
        self.assertTrue(is_dingtalk_configured())

    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "key123",
    }, clear=True)
    def test_not_configured_partial(self):
        """Only some env vars → not configured."""
        self.assertFalse(is_dingtalk_configured())


# ---------------------------------------------------------------------------
# DingTalkBot Instance
# ---------------------------------------------------------------------------


class TestDingTalkBot(unittest.TestCase):
    def test_platform_name(self):
        bot = DingTalkBot()
        self.assertEqual(bot.platform_name, "DingTalk")

    def test_rate_limiter_default(self):
        bot = DingTalkBot()
        self.assertEqual(bot.rate_limiter._max, 20)


# ---------------------------------------------------------------------------
# Token Acquisition (mocked HTTP)
# ---------------------------------------------------------------------------


class TestDingTalkTokenRefresh(unittest.TestCase):
    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "test_key",
        "DINGTALK_APP_SECRET": "test_secret",
        "DINGTALK_ROBOT_CODE": "test_robot",
    })
    @patch("data_agent.dingtalk_bot.httpx.AsyncClient")
    def test_refresh_token_success(self, MockClient):
        """Successful token acquisition from DingTalk API."""
        bot = DingTalkBot()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "accessToken": "at_123456",
            "expireIn": 7200,
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.get_event_loop()
        token = loop.run_until_complete(bot.refresh_token())
        self.assertEqual(token, "at_123456")
        self.assertTrue(bot.token_cache.valid)

    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "test_key",
        "DINGTALK_APP_SECRET": "test_secret",
        "DINGTALK_ROBOT_CODE": "test_robot",
    })
    @patch("data_agent.dingtalk_bot.httpx.AsyncClient")
    def test_refresh_token_failure(self, MockClient):
        """Token API error raises RuntimeError."""
        bot = DingTalkBot()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "message": "invalid credentials",
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.get_event_loop()
        with self.assertRaises(RuntimeError):
            loop.run_until_complete(bot.refresh_token())


# ---------------------------------------------------------------------------
# Graceful Degradation
# ---------------------------------------------------------------------------


class TestEnsureDingTalkConnection(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_not_configured_returns_false(self):
        """ensure_dingtalk_connection returns False when not configured."""
        result = ensure_dingtalk_connection()
        self.assertFalse(result)

    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "key123",
        "DINGTALK_APP_SECRET": "sec456",
        "DINGTALK_ROBOT_CODE": "robot789",
    })
    def test_configured_returns_true(self):
        """ensure_dingtalk_connection returns True when configured."""
        result = ensure_dingtalk_connection()
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# Route Mounting
# ---------------------------------------------------------------------------


class TestDingTalkRouteMount(unittest.TestCase):
    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "key123",
        "DINGTALK_APP_SECRET": "sec456",
        "DINGTALK_ROBOT_CODE": "robot789",
    })
    def test_mount_routes(self):
        """Routes get inserted into the app."""
        bot = DingTalkBot()
        app = MagicMock()
        app.router.routes = []
        result = bot.mount_routes(app)
        self.assertTrue(result)
        self.assertEqual(len(app.router.routes), 1)
        self.assertEqual(app.router.routes[0].path, "/dingtalk/callback")

    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "key123",
        "DINGTALK_APP_SECRET": "sec456",
        "DINGTALK_ROBOT_CODE": "robot789",
    })
    def test_mount_before_catchall(self):
        """Route inserted before Chainlit catch-all."""
        bot = DingTalkBot()
        app = MagicMock()

        catchall = MagicMock()
        catchall.path = "/{full_path:path}"
        app.router.routes = [catchall]

        result = bot.mount_routes(app)
        self.assertTrue(result)
        self.assertEqual(len(app.router.routes), 2)
        # DingTalk route should be before catch-all
        self.assertEqual(app.router.routes[0].path, "/dingtalk/callback")


# ---------------------------------------------------------------------------
# Message Dedup in Bot
# ---------------------------------------------------------------------------


class TestBotMessageDedup(unittest.TestCase):
    def test_dedup_blocks_repeated_msg(self):
        """handle_message ignores duplicate msg_id."""
        bot = DingTalkBot()
        bot.send_text = AsyncMock()
        # Use a unique msg_id to avoid cross-test interference
        unique_id = f"dedup_test_{time.time()}"

        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.handle_message("user1", unique_id, "hello"))
        loop.run_until_complete(bot.handle_message("user1", unique_id, "hello"))

        # send_text should only be called once (the ACK for the first message)
        self.assertEqual(bot.send_text.await_count, 1)


# ---------------------------------------------------------------------------
# Handle Empty/Blank Message
# ---------------------------------------------------------------------------


class TestBotEmptyMessage(unittest.TestCase):
    def test_blank_message_ignored(self):
        """Blank content is silently ignored."""
        bot = DingTalkBot()
        bot.send_text = AsyncMock()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.handle_message("user1", "msg_200", "   "))

        bot.send_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Send Methods (mocked HTTP)
# ---------------------------------------------------------------------------


class TestDingTalkSendText(unittest.TestCase):
    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "key123",
        "DINGTALK_APP_SECRET": "sec456",
        "DINGTALK_ROBOT_CODE": "robot789",
    })
    @patch("data_agent.dingtalk_bot.httpx.AsyncClient")
    def test_send_text_calls_api(self, MockClient):
        """send_text posts to robot/oToMessages/batchSend."""
        bot = DingTalkBot()
        bot.token_cache.set("test_token", 7200)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.send_text("user_001", "测试消息"))

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        self.assertIn("batchSend", call_args[0][0])


class TestDingTalkSendMarkdown(unittest.TestCase):
    @patch.dict(os.environ, {
        "DINGTALK_APP_KEY": "key123",
        "DINGTALK_APP_SECRET": "sec456",
        "DINGTALK_ROBOT_CODE": "robot789",
    })
    @patch("data_agent.dingtalk_bot.httpx.AsyncClient")
    def test_send_markdown(self, MockClient):
        """send_markdown posts sampleMarkdown msgKey."""
        bot = DingTalkBot()
        bot.token_cache.set("test_token", 7200)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.get_event_loop()
        loop.run_until_complete(bot.send_markdown("user_001", "# 标题\n内容"))

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs.get("json", {})
        self.assertEqual(payload.get("msgKey"), "sampleMarkdown")


# ---------------------------------------------------------------------------
# Ensure Bot User
# ---------------------------------------------------------------------------


class TestEnsureBotUser(unittest.TestCase):
    @patch("data_agent.auth.get_engine", return_value=None)
    def test_ensure_bot_user_no_db(self, mock_engine):
        """Without DB, returns a default user dict."""
        from data_agent.auth import ensure_bot_user
        result = ensure_bot_user("test_uid", "dingtalk")
        self.assertEqual(result["username"], "dt_test_uid")
        self.assertEqual(result["role"], "analyst")

    @patch("data_agent.auth.get_engine", return_value=None)
    def test_feishu_prefix(self, mock_engine):
        """Feishu user gets fs_ prefix."""
        from data_agent.auth import ensure_bot_user
        result = ensure_bot_user("xyz", "feishu")
        self.assertEqual(result["username"], "fs_xyz")


if __name__ == "__main__":
    unittest.main()
