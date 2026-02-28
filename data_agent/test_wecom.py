"""
Tests for Enterprise WeChat bot integration.
Covers: crypto roundtrip, config/degradation, markdown conversion, dedup, rate limit.
"""
import os
import struct
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# ---------------------------------------------------------------------------
# 1. Crypto Tests
# ---------------------------------------------------------------------------

class TestWXBizMsgCrypt(unittest.TestCase):
    """Test AES-256-CBC encrypt/decrypt roundtrip."""

    def setUp(self):
        from data_agent.wecom_crypto import WXBizMsgCrypt
        # 43-char Base64 key (decodes to 32 bytes)
        self.encoding_aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
        self.token = "test_token_123"
        self.corp_id = "wx1234567890abcdef"
        self.crypt = WXBizMsgCrypt(self.token, self.encoding_aes_key, self.corp_id)

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt then decrypt should return original message."""
        original = "Hello, 企业微信！这是一条测试消息。"
        encrypted = self.crypt._encrypt(original)
        decrypted = self.crypt._decrypt(encrypted)
        self.assertEqual(decrypted, original)

    def test_encrypt_decrypt_empty(self):
        """Empty string should roundtrip correctly."""
        encrypted = self.crypt._encrypt("")
        decrypted = self.crypt._decrypt(encrypted)
        self.assertEqual(decrypted, "")

    def test_encrypt_decrypt_long_message(self):
        """Long messages (>1000 chars) should roundtrip correctly."""
        original = "测试" * 600  # 1200 chars
        encrypted = self.crypt._encrypt(original)
        decrypted = self.crypt._decrypt(encrypted)
        self.assertEqual(decrypted, original)

    def test_corp_id_mismatch(self):
        """Decrypting with wrong corp_id should raise ValueError."""
        from data_agent.wecom_crypto import WXBizMsgCrypt
        crypt2 = WXBizMsgCrypt(self.token, self.encoding_aes_key, "wrong_corp_id")
        encrypted = self.crypt._encrypt("test")
        with self.assertRaises(ValueError) as ctx:
            crypt2._decrypt(encrypted)
        self.assertIn("CorpID mismatch", str(ctx.exception))

    def test_invalid_aes_key(self):
        """Short AES key should raise ValueError."""
        from data_agent.wecom_crypto import WXBizMsgCrypt
        with self.assertRaises(Exception):
            WXBizMsgCrypt(self.token, "tooshort", self.corp_id)

    def test_signature(self):
        """Signature should be deterministic SHA1."""
        sig = self.crypt._sign("1234567890", "nonce123", "encrypted_text")
        self.assertEqual(len(sig), 40)  # SHA1 hex
        # Same inputs → same output
        sig2 = self.crypt._sign("1234567890", "nonce123", "encrypted_text")
        self.assertEqual(sig, sig2)

    def test_verify_url_roundtrip(self):
        """Full verify_url flow: encrypt echostr → verify → get it back."""
        echostr_plain = "echo_test_string"
        echostr_encrypted = self.crypt._encrypt(echostr_plain)
        timestamp = "1234567890"
        nonce = "testnonce"
        signature = self.crypt._sign(timestamp, nonce, echostr_encrypted)

        ok, result = self.crypt.verify_url(signature, timestamp, nonce, echostr_encrypted)
        self.assertTrue(ok)
        self.assertEqual(result, echostr_plain)

    def test_verify_url_bad_signature(self):
        """Bad signature should fail verification."""
        echostr_encrypted = self.crypt._encrypt("test")
        ok, result = self.crypt.verify_url("bad_sig", "1234", "nonce", echostr_encrypted)
        self.assertFalse(ok)
        self.assertIn("Signature", result)

    def test_decrypt_message_roundtrip(self):
        """Full decrypt_message flow with XML envelope."""
        plain_xml = (
            "<xml>"
            "<ToUserName><![CDATA[bot]]></ToUserName>"
            "<FromUserName><![CDATA[user1]]></FromUserName>"
            "<Content><![CDATA[你好]]></Content>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<MsgId>123456</MsgId>"
            "</xml>"
        )
        nonce = "testnonce"
        timestamp = "1234567890"
        encrypted = self.crypt._encrypt(plain_xml)
        signature = self.crypt._sign(timestamp, nonce, encrypted)

        post_xml = (
            f"<xml>"
            f"<Encrypt><![CDATA[{encrypted}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
            f"<TimeStamp>{timestamp}</TimeStamp>"
            f"<Nonce><![CDATA[{nonce}]]></Nonce>"
            f"</xml>"
        )
        ok, result_xml = self.crypt.decrypt_message(signature, timestamp, nonce, post_xml)
        self.assertTrue(ok)
        self.assertIn("你好", result_xml)

    def test_encrypt_message(self):
        """encrypt_message should produce valid XML with all fields."""
        xml_out = self.crypt.encrypt_message("test reply", "nonce1", "1234567890")
        self.assertIn("<Encrypt>", xml_out)
        self.assertIn("<MsgSignature>", xml_out)
        self.assertIn("<TimeStamp>1234567890</TimeStamp>", xml_out)
        self.assertIn("<Nonce>", xml_out)


class TestParseMessageXml(unittest.TestCase):
    """Test XML message parsing."""

    def test_parse_text_message(self):
        from data_agent.wecom_crypto import parse_message_xml
        xml = (
            "<xml>"
            "<ToUserName><![CDATA[bot]]></ToUserName>"
            "<FromUserName><![CDATA[user1]]></FromUserName>"
            "<Content><![CDATA[查询表列表]]></Content>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<MsgId>123456789</MsgId>"
            "<AgentID>1000002</AgentID>"
            "</xml>"
        )
        result = parse_message_xml(xml)
        self.assertEqual(result["FromUserName"], "user1")
        self.assertEqual(result["Content"], "查询表列表")
        self.assertEqual(result["MsgType"], "text")
        self.assertEqual(result["MsgId"], "123456789")

    def test_parse_empty_xml(self):
        from data_agent.wecom_crypto import parse_message_xml
        result = parse_message_xml("<xml></xml>")
        self.assertEqual(result, {})

    def test_parse_invalid_xml(self):
        from data_agent.wecom_crypto import parse_message_xml
        result = parse_message_xml("not xml at all")
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# 2. PKCS7 Tests
# ---------------------------------------------------------------------------

class TestPKCS7(unittest.TestCase):
    """Test PKCS7 padding with 32-byte blocks."""

    def test_pad_unpad_roundtrip(self):
        from data_agent.wecom_crypto import PKCS7
        for size in [0, 1, 15, 16, 31, 32, 33, 100]:
            data = b"x" * size
            padded = PKCS7.pad(data)
            self.assertEqual(len(padded) % 32, 0)
            self.assertEqual(PKCS7.unpad(padded), data)

    def test_unpad_invalid(self):
        from data_agent.wecom_crypto import PKCS7
        with self.assertRaises(ValueError):
            PKCS7.unpad(b"\x00" * 32)  # pad byte 0 is invalid


# ---------------------------------------------------------------------------
# 3. Configuration & Degradation Tests
# ---------------------------------------------------------------------------

class TestWeComConfig(unittest.TestCase):
    """Test graceful degradation when env vars are missing."""

    def test_not_configured_by_default(self):
        """Without env vars, is_wecom_configured() returns False."""
        from data_agent.wecom_bot import is_wecom_configured
        env_keys = [
            "WECOM_CORP_ID", "WECOM_APP_SECRET", "WECOM_TOKEN",
            "WECOM_ENCODING_AES_KEY", "WECOM_AGENT_ID",
        ]
        with patch.dict(os.environ, {k: "" for k in env_keys}):
            self.assertFalse(is_wecom_configured())

    def test_configured_when_all_set(self):
        """With all env vars set, is_wecom_configured() returns True."""
        from data_agent.wecom_bot import is_wecom_configured
        env = {
            "WECOM_CORP_ID": "wxcorp123",
            "WECOM_APP_SECRET": "secret",
            "WECOM_TOKEN": "token",
            "WECOM_ENCODING_AES_KEY": "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
            "WECOM_AGENT_ID": "1000002",
        }
        with patch.dict(os.environ, env):
            self.assertTrue(is_wecom_configured())

    def test_partial_config(self):
        """Missing one key → not configured."""
        from data_agent.wecom_bot import is_wecom_configured
        env = {
            "WECOM_CORP_ID": "wxcorp123",
            "WECOM_APP_SECRET": "secret",
            "WECOM_TOKEN": "token",
            "WECOM_ENCODING_AES_KEY": "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
            # WECOM_AGENT_ID missing
        }
        with patch.dict(os.environ, env, clear=False):
            # Explicitly remove WECOM_AGENT_ID if it exists
            with patch.dict(os.environ, {"WECOM_AGENT_ID": ""}):
                self.assertFalse(is_wecom_configured())

    def test_ensure_wecom_connection_not_configured(self, ):
        """Startup check prints disabled message when not configured."""
        from data_agent.wecom_bot import ensure_wecom_connection
        with patch.dict(os.environ, {"WECOM_CORP_ID": ""}):
            ensure_wecom_connection()  # Should not raise


# ---------------------------------------------------------------------------
# 4. Markdown Conversion Tests
# ---------------------------------------------------------------------------

class TestMarkdownConversion(unittest.TestCase):
    """Test convert_to_wecom_markdown."""

    def test_strip_latex(self):
        from data_agent.wecom_bot import convert_to_wecom_markdown
        text = "结果为 $x^2$ 和 $$\\sum_{i=1}^n$$"
        result = convert_to_wecom_markdown(text)
        self.assertNotIn("$", result)
        self.assertIn("结果为", result)

    def test_strip_images(self):
        from data_agent.wecom_bot import convert_to_wecom_markdown
        text = "查看图片 ![alt](http://example.com/img.png) 结束"
        result = convert_to_wecom_markdown(text)
        self.assertNotIn("![", result)
        self.assertIn("查看图片", result)

    def test_strip_tables(self):
        from data_agent.wecom_bot import convert_to_wecom_markdown
        text = "前文\n| 列1 | 列2 |\n|---|---|\n| a | b |\n后文"
        result = convert_to_wecom_markdown(text)
        self.assertNotIn("|", result)
        self.assertIn("前文", result)
        self.assertIn("后文", result)

    def test_truncate_long(self):
        from data_agent.wecom_bot import convert_to_wecom_markdown
        text = "x" * 3000
        result = convert_to_wecom_markdown(text)
        self.assertLessEqual(len(result), 2048)
        self.assertIn("已截断", result)

    def test_empty_input(self):
        from data_agent.wecom_bot import convert_to_wecom_markdown
        self.assertEqual(convert_to_wecom_markdown(""), "")
        self.assertEqual(convert_to_wecom_markdown(None), "")

    def test_preserve_bold_and_links(self):
        from data_agent.wecom_bot import convert_to_wecom_markdown
        text = "**重要**: 请查看 [链接](http://example.com)"
        result = convert_to_wecom_markdown(text)
        self.assertIn("**重要**", result)
        self.assertIn("[链接]", result)


# ---------------------------------------------------------------------------
# 5. Dedup Tests
# ---------------------------------------------------------------------------

class TestDedup(unittest.TestCase):
    """Test message deduplication."""

    def setUp(self):
        from data_agent.wecom_bot import _processing_messages
        _processing_messages.clear()

    def test_first_message_not_duplicate(self):
        from data_agent.wecom_bot import _is_duplicate
        self.assertFalse(_is_duplicate("msg_001"))

    def test_same_id_is_duplicate(self):
        from data_agent.wecom_bot import _is_duplicate
        _is_duplicate("msg_002")  # first
        self.assertTrue(_is_duplicate("msg_002"))  # duplicate

    def test_different_id_not_duplicate(self):
        from data_agent.wecom_bot import _is_duplicate
        _is_duplicate("msg_003")
        self.assertFalse(_is_duplicate("msg_004"))

    def test_expired_entries_cleaned(self):
        from data_agent.wecom_bot import _is_duplicate, _processing_messages, _DEDUP_WINDOW
        _is_duplicate("msg_old")
        # Manually expire it
        _processing_messages["msg_old"] = time.time() - _DEDUP_WINDOW - 1
        self.assertFalse(_is_duplicate("msg_old"))  # Should not be duplicate after expiry

    def test_empty_msg_id_not_duplicate(self):
        from data_agent.wecom_bot import _is_duplicate
        self.assertFalse(_is_duplicate(""))
        self.assertFalse(_is_duplicate(""))


# ---------------------------------------------------------------------------
# 6. Pipeline Runner Tests
# ---------------------------------------------------------------------------

class TestPipelineRunner(unittest.TestCase):
    """Test extract_file_paths from pipeline_runner."""

    def test_extract_windows_paths(self):
        from data_agent.pipeline_runner import extract_file_paths
        # We can't test os.path.exists easily, so just test the regex logic
        # by temporarily patching os.path.exists
        with patch("data_agent.pipeline_runner.os.path.exists", return_value=True):
            text = r"输出文件: D:\adk\data_agent\uploads\admin\result_abc123.png"
            result = extract_file_paths(text)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["type"], "png")

    def test_extract_unix_paths(self):
        from data_agent.pipeline_runner import extract_file_paths
        with patch("data_agent.pipeline_runner.os.path.exists", return_value=True):
            text = "生成: /app/data_agent/uploads/user1/map_abc.html"
            result = extract_file_paths(text)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["type"], "html")

    def test_extract_multiple_types(self):
        from data_agent.pipeline_runner import extract_file_paths
        with patch("data_agent.pipeline_runner.os.path.exists", return_value=True):
            text = (
                r"结果: D:\uploads\a.png 和 D:\uploads\b.csv "
                r"以及 D:\uploads\c.shp"
            )
            result = extract_file_paths(text)
            types = {r["type"] for r in result}
            self.assertEqual(types, {"png", "csv", "shp"})

    def test_no_paths(self):
        from data_agent.pipeline_runner import extract_file_paths
        result = extract_file_paths("没有路径的文本")
        self.assertEqual(result, [])

    def test_docx_pdf_supported(self):
        from data_agent.pipeline_runner import extract_file_paths
        with patch("data_agent.pipeline_runner.os.path.exists", return_value=True):
            text = r"报告: D:\uploads\report.docx 和 D:\uploads\report.pdf"
            result = extract_file_paths(text)
            types = {r["type"] for r in result}
            self.assertIn("docx", types)
            self.assertIn("pdf", types)


class TestPipelineResult(unittest.TestCase):
    """Test PipelineResult dataclass."""

    def test_default_values(self):
        from data_agent.pipeline_runner import PipelineResult
        r = PipelineResult()
        self.assertEqual(r.report_text, "")
        self.assertEqual(r.generated_files, [])
        self.assertEqual(r.tool_execution_log, [])
        self.assertIsNone(r.error)
        self.assertEqual(r.total_input_tokens, 0)
        self.assertEqual(r.total_output_tokens, 0)

    def test_custom_values(self):
        from data_agent.pipeline_runner import PipelineResult
        r = PipelineResult(
            report_text="test report",
            pipeline_type="general",
            intent="GENERAL",
            total_input_tokens=100,
            total_output_tokens=50,
            duration_seconds=3.5,
        )
        self.assertEqual(r.report_text, "test report")
        self.assertEqual(r.total_input_tokens, 100)


# ---------------------------------------------------------------------------
# 7. Auth Integration Test
# ---------------------------------------------------------------------------

class TestWeComAuth(unittest.TestCase):
    """Test ensure_wecom_user in auth.py."""

    @patch("data_agent.auth.get_engine", return_value=None)
    def test_ensure_wecom_user_no_db(self, mock_engine):
        """Without DB, should return offline user dict."""
        from data_agent.auth import ensure_wecom_user
        result = ensure_wecom_user("zhangsan")
        self.assertEqual(result["username"], "wx_zhangsan")
        self.assertEqual(result["role"], "analyst")

    def test_username_prefix(self):
        """WeChat users should get wx_ prefix."""
        from data_agent.auth import ensure_wecom_user
        with patch("data_agent.auth.get_engine", return_value=None):
            result = ensure_wecom_user("lisi")
            self.assertTrue(result["username"].startswith("wx_"))


if __name__ == "__main__":
    unittest.main()
