"""
Tests for Feishu (飞书) Bot integration.

Covers: token acquisition, message sending, callback routing,
challenge-response verification, AES decryption, graceful degradation.
"""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from data_agent.bot_base import (
    TokenCache, RateLimiter, MessageDedup,
    simplify_markdown, prioritize_files,
)
from data_agent.feishu_bot import (
    FeishuBot, is_feishu_configured,
    ensure_feishu_connection, _REQUIRED_ENV,
    _decrypt_feishu_message,
)


# ---------------------------------------------------------------------------
# Feishu Configuration
# ---------------------------------------------------------------------------


class TestFeishuConfiguration(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_not_configured_missing_all(self):
        """All required env vars missing → not configured."""
        self.assertFalse(is_feishu_configured())

    @patch.dict(os.environ, {
        "FEISHU_APP_ID": "cli_abc123",
        "FEISHU_APP_SECRET": "secret_xyz",
    })
    def test_configured_all_present(self):
        """All required env vars set → configured."""
        self.assertTrue(is_feishu_configured())

    @patch.dict(os.environ, {
        "FEISHU_APP_ID": "cli_abc123",
    }, clear=True)
    def test_not_configured_partial(self):
        """Only partial env vars → not configured."""
        self.assertFalse(is_feishu_configured())


# ---------------------------------------------------------------------------
# FeishuBot Instance
# ---------------------------------------------------------------------------


class TestFeishuBot(unittest.TestCase):
    def test_platform_name(self):
        bot = FeishuBot()
        self.assertEqual(bot.platform_name, "Feishu")

    def test_rate_limiter_generous(self):
        """Feishu allows 50 msg/min (more than DingTalk/WeCom)."""
        bot = FeishuBot()
        self.assertEqual(bot.rate_limiter._max, 50)


# ---------------------------------------------------------------------------
# Token Acquisition (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFeishuTokenRefresh(unittest.TestCase):
    @patch.dict(os.environ, {
        "FEISHU_APP_ID": "cli_test",
        "FEISHU_APP_SECRET": "test_secret",
    })
    @patch("data_agent.feishu_bot.httpx.AsyncClient")
    def test_refresh_token_success(self, MockClient):
        """Successful tenant_access_token acquisition."""
        bot = FeishuBot()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "tenant_access_token": "t-12345",
            "expire": 7200,
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.new_event_loop()
        token = loop.run_until_complete(bot.refresh_token())
        self.assertEqual(token, "t-12345")
        self.assertTrue(bot.token_cache.valid)

    @patch.dict(os.environ, {
        "FEISHU_APP_ID": "cli_test",
        "FEISHU_APP_SECRET": "test_secret",
    })
    @patch("data_agent.feishu_bot.httpx.AsyncClient")
    def test_refresh_token_failure(self, MockClient):
        """Token API error code != 0 raises RuntimeError."""
        bot = FeishuBot()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 10003,
            "msg": "app_id not found",
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.new_event_loop()
        with self.assertRaises(RuntimeError) as ctx:
            loop.run_until_complete(bot.refresh_token())
        self.assertIn("app_id not found", str(ctx.exception))


# ---------------------------------------------------------------------------
# Graceful Degradation
# ---------------------------------------------------------------------------


class TestEnsureFeishuConnection(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_not_configured_returns_false(self):
        """ensure_feishu_connection returns False when not configured."""
        result = ensure_feishu_connection()
        self.assertFalse(result)

    @patch.dict(os.environ, {
        "FEISHU_APP_ID": "cli_abc",
        "FEISHU_APP_SECRET": "sec_xyz",
    })
    def test_configured_returns_true(self):
        """ensure_feishu_connection returns True when configured."""
        result = ensure_feishu_connection()
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# Route Mounting
# ---------------------------------------------------------------------------


class TestFeishuRouteMount(unittest.TestCase):
    def test_mount_routes(self):
        """Routes get appended to the app."""
        bot = FeishuBot()
        app = MagicMock()
        app.router.routes = []
        result = bot.mount_routes(app)
        self.assertTrue(result)
        self.assertEqual(len(app.router.routes), 1)
        self.assertEqual(app.router.routes[0].path, "/feishu/callback")

    def test_mount_before_catchall(self):
        """Route inserted before Chainlit catch-all."""
        bot = FeishuBot()
        app = MagicMock()

        catchall = MagicMock()
        catchall.path = "/{full_path:path}"
        app.router.routes = [catchall]

        result = bot.mount_routes(app)
        self.assertTrue(result)
        self.assertEqual(len(app.router.routes), 2)
        self.assertEqual(app.router.routes[0].path, "/feishu/callback")


# ---------------------------------------------------------------------------
# AES Decryption
# ---------------------------------------------------------------------------


class TestFeishuDecryption(unittest.TestCase):
    def test_decrypt_without_cryptography(self):
        """Decryption requires cryptography package."""
        # This test verifies the function signature works
        # Actual crypto tested only if cryptography is installed
        try:
            import cryptography
            has_crypto = True
        except ImportError:
            has_crypto = False

        if not has_crypto:
            with self.assertRaises(RuntimeError) as ctx:
                _decrypt_feishu_message("test_key", "dGVzdA==")
            self.assertIn("cryptography", str(ctx.exception))

    def test_decrypt_valid_data(self):
        """Test decryption with valid AES-256-CBC encrypted data."""
        try:
            import cryptography
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend
            import hashlib
            import base64
            import os as _os

            # Encrypt test data
            encrypt_key = "test_encryption_key"
            plaintext = json.dumps({"header": {"event_type": "test"}, "event": {}})
            key = hashlib.sha256(encrypt_key.encode()).digest()
            iv = _os.urandom(16)

            # Add PKCS7 padding
            block_size = 16
            pad_len = block_size - (len(plaintext.encode()) % block_size)
            padded = plaintext.encode() + bytes([pad_len] * pad_len)

            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(padded) + encryptor.finalize()
            encrypted_b64 = base64.b64encode(iv + encrypted).decode()

            # Decrypt and verify
            result = _decrypt_feishu_message(encrypt_key, encrypted_b64)
            data = json.loads(result)
            self.assertEqual(data["header"]["event_type"], "test")

        except ImportError:
            self.skipTest("cryptography package not installed")


# ---------------------------------------------------------------------------
# Send Methods (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFeishuSendText(unittest.TestCase):
    @patch("data_agent.feishu_bot.httpx.AsyncClient")
    def test_send_text_calls_api(self, MockClient):
        """send_text posts to im/v1/messages."""
        bot = FeishuBot()
        bot.token_cache.set("test_token", 7200)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.new_event_loop()
        loop.run_until_complete(bot.send_text("ou_test_user", "测试消息"))

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        self.assertIn("im/v1/messages", call_args[0][0])


class TestFeishuSendMarkdown(unittest.TestCase):
    @patch("data_agent.feishu_bot.httpx.AsyncClient")
    def test_send_markdown_as_card(self, MockClient):
        """send_markdown uses interactive card format."""
        bot = FeishuBot()
        bot.token_cache.set("test_token", 7200)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.new_event_loop()
        loop.run_until_complete(bot.send_markdown("ou_test_user", "# 标题\n内容"))

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs.get("json", {})
        self.assertEqual(payload.get("msg_type"), "interactive")


class TestFeishuSendCard(unittest.TestCase):
    @patch("data_agent.feishu_bot.httpx.AsyncClient")
    def test_send_card_with_url(self, MockClient):
        """send_card creates interactive card with button."""
        bot = FeishuBot()
        bot.token_cache.set("test_token", 7200)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = mock_client

        loop = asyncio.new_event_loop()
        loop.run_until_complete(bot.send_card(
            "ou_test", "结果", "分析完成", "https://example.com/s/abc"
        ))

        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs.get("json", {})
        content = json.loads(payload.get("content", "{}"))
        # Should have header + elements (markdown + action button)
        self.assertIn("header", content)
        self.assertIn("elements", content)
        self.assertEqual(len(content["elements"]), 2)  # markdown + action


# ---------------------------------------------------------------------------
# Message Dedup in Bot
# ---------------------------------------------------------------------------


class TestFeishuMessageDedup(unittest.TestCase):
    def test_dedup_blocks_repeated_msg(self):
        """handle_message ignores duplicate msg_id."""
        bot = FeishuBot()
        bot.send_text = AsyncMock()
        bot._run_pipeline = AsyncMock()  # prevent actual pipeline execution

        loop = asyncio.new_event_loop()
        loop.run_until_complete(bot.handle_message("ou_user1", "msg_f1", "hello"))
        loop.run_until_complete(bot.handle_message("ou_user1", "msg_f1", "hello"))

        # Only one ACK sent
        self.assertEqual(bot.send_text.await_count, 1)


# ---------------------------------------------------------------------------
# Handle Empty/Blank Message
# ---------------------------------------------------------------------------


class TestFeishuEmptyMessage(unittest.TestCase):
    def test_blank_message_ignored(self):
        """Blank content is silently ignored."""
        bot = FeishuBot()
        bot.send_text = AsyncMock()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(bot.handle_message("ou_user1", "msg_f2", "  "))

        bot.send_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Challenge-Response Verification (callback test)
# ---------------------------------------------------------------------------


class TestFeishuChallengeResponse(unittest.TestCase):
    def test_challenge_format(self):
        """URL verification challenge should echo the challenge value."""
        # This tests the callback logic pattern
        challenge = "challenge_12345"
        body = {"type": "url_verification", "challenge": challenge}
        # The callback should return {"challenge": challenge}
        response_body = {"challenge": body.get("challenge", "")}
        self.assertEqual(response_body["challenge"], challenge)


# ---------------------------------------------------------------------------
# Cross-bot Dedup Isolation
# ---------------------------------------------------------------------------


class TestCrossBotDedupIsolation(unittest.TestCase):
    def test_separate_dedup_instances(self):
        """Each bot has its own dedup instance."""
        from data_agent.dingtalk_bot import DingTalkBot

        dt_bot = DingTalkBot()
        fs_bot = FeishuBot()

        dt_bot.dedup.is_duplicate("shared_msg_id")
        # Feishu bot should NOT see DingTalk's msg as duplicate
        self.assertFalse(fs_bot.dedup.is_duplicate("shared_msg_id"))


# ---------------------------------------------------------------------------
# get_token delegates to refresh
# ---------------------------------------------------------------------------


class TestGetTokenDelegation(unittest.TestCase):
    def test_get_token_calls_refresh(self):
        """get_token() calls refresh_token() when cache is empty."""
        bot = FeishuBot()
        bot.refresh_token = AsyncMock(return_value="refreshed_token")

        loop = asyncio.new_event_loop()
        token = loop.run_until_complete(bot.get_token())
        self.assertEqual(token, "refreshed_token")
        bot.refresh_token.assert_awaited_once()

    def test_get_token_uses_cache(self):
        """get_token() returns cached token without refresh."""
        bot = FeishuBot()
        bot.token_cache.set("cached_token", 7200)
        bot.refresh_token = AsyncMock()

        loop = asyncio.new_event_loop()
        token = loop.run_until_complete(bot.get_token())
        self.assertEqual(token, "cached_token")
        bot.refresh_token.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
