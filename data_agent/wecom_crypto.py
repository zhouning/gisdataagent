"""
Enterprise WeChat (企业微信) Message Encryption/Decryption.
Implements WXBizMsgCrypt protocol: AES-256-CBC with PKCS7 (32-byte blocks).
Zero new dependencies — uses `cryptography` (already installed) + `xml.etree`.
"""
import base64
import hashlib
import socket
import struct
import time
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class PKCS7:
    """PKCS#7 padding with 32-byte block size (WeChat spec)."""
    BLOCK_SIZE = 32

    @staticmethod
    def pad(data: bytes) -> bytes:
        amount = PKCS7.BLOCK_SIZE - (len(data) % PKCS7.BLOCK_SIZE)
        return data + bytes([amount] * amount)

    @staticmethod
    def unpad(data: bytes) -> bytes:
        pad_len = data[-1]
        if pad_len < 1 or pad_len > PKCS7.BLOCK_SIZE:
            raise ValueError("Invalid PKCS7 padding")
        if data[-pad_len:] != bytes([pad_len] * pad_len):
            raise ValueError("Invalid PKCS7 padding")
        return data[:-pad_len]


class WXBizMsgCrypt:
    """
    WeChat Enterprise message encryption helper.

    Args:
        token:            Callback verification token (set in WeCom admin).
        encoding_aes_key: 43-char Base64-encoded AES key (set in WeCom admin).
        corp_id:          Enterprise CorpID.
    """

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        # AES key = Base64Decode(EncodingAESKey + "=")
        self.aes_key = base64.b64decode(encoding_aes_key + "=")
        if len(self.aes_key) != 32:
            raise ValueError(
                f"Invalid EncodingAESKey: decoded length {len(self.aes_key)}, expected 32"
            )

    # ------------------------------------------------------------------
    # Signature
    # ------------------------------------------------------------------
    def _sign(self, timestamp: str, nonce: str, encrypt: str) -> str:
        """SHA1(sort([token, timestamp, nonce, encrypt]))"""
        parts = sorted([self.token, timestamp, nonce, encrypt])
        return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Encrypt
    # ------------------------------------------------------------------
    def _encrypt(self, plaintext: str) -> str:
        """
        Encrypt message → Base64 string.
        Format: random(16) + msg_len(4, big-endian) + msg + corp_id
        """
        import os as _os
        msg_bytes = plaintext.encode("utf-8")
        corp_bytes = self.corp_id.encode("utf-8")
        # 16 random bytes + 4-byte network-order length + message + corpid
        raw = (
            _os.urandom(16)
            + struct.pack("!I", len(msg_bytes))
            + msg_bytes
            + corp_bytes
        )
        padded = PKCS7.pad(raw)
        iv = self.aes_key[:16]
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        return base64.b64encode(encrypted).decode("utf-8")

    # ------------------------------------------------------------------
    # Decrypt
    # ------------------------------------------------------------------
    def _decrypt(self, ciphertext_b64: str) -> str:
        """Decrypt Base64 ciphertext → plaintext string."""
        encrypted = base64.b64decode(ciphertext_b64)
        iv = self.aes_key[:16]
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        raw = PKCS7.unpad(padded)
        # Skip 16 random bytes, read 4-byte msg length
        msg_len = struct.unpack("!I", raw[16:20])[0]
        msg = raw[20: 20 + msg_len].decode("utf-8")
        from_corp_id = raw[20 + msg_len:].decode("utf-8")
        if from_corp_id != self.corp_id:
            raise ValueError(
                f"CorpID mismatch: expected '{self.corp_id}', got '{from_corp_id}'"
            )
        return msg

    # ------------------------------------------------------------------
    # Public API: URL verification (GET callback)
    # ------------------------------------------------------------------
    def verify_url(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> Tuple[bool, str]:
        """
        Verify callback URL (GET request from WeCom).

        Returns:
            (True, decrypted_echostr) on success, (False, error_msg) on failure.
        """
        try:
            computed = self._sign(timestamp, nonce, echostr)
            if computed != msg_signature:
                return False, "Signature verification failed"
            plaintext = self._decrypt(echostr)
            return True, plaintext
        except Exception as e:
            return False, f"URL verification error: {e}"

    # ------------------------------------------------------------------
    # Public API: decrypt incoming message (POST callback)
    # ------------------------------------------------------------------
    def decrypt_message(
        self, msg_signature: str, timestamp: str, nonce: str, post_data: str
    ) -> Tuple[bool, str]:
        """
        Decrypt an incoming encrypted XML message.

        Args:
            msg_signature: msg_signature query param.
            timestamp:     timestamp query param.
            nonce:         nonce query param.
            post_data:     Raw POST body (encrypted XML).

        Returns:
            (True, decrypted_xml_text) on success, (False, error_msg) on failure.
        """
        try:
            root = ET.fromstring(post_data)
            encrypt_node = root.find("Encrypt")
            if encrypt_node is None or not encrypt_node.text:
                return False, "Missing <Encrypt> element"
            ciphertext = encrypt_node.text

            computed = self._sign(timestamp, nonce, ciphertext)
            if computed != msg_signature:
                return False, "Signature verification failed"

            plaintext_xml = self._decrypt(ciphertext)
            return True, plaintext_xml
        except ET.ParseError as e:
            return False, f"XML parse error: {e}"
        except Exception as e:
            return False, f"Decrypt error: {e}"

    # ------------------------------------------------------------------
    # Public API: encrypt outgoing reply
    # ------------------------------------------------------------------
    def encrypt_message(
        self, reply_msg: str, nonce: str, timestamp: Optional[str] = None
    ) -> str:
        """
        Encrypt a reply message into WeChat XML format.

        Returns:
            Encrypted XML string ready to send as HTTP response body.
        """
        ts = timestamp or str(int(time.time()))
        encrypted = self._encrypt(reply_msg)
        signature = self._sign(ts, nonce, encrypted)
        return (
            f"<xml>"
            f"<Encrypt><![CDATA[{encrypted}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
            f"<TimeStamp>{ts}</TimeStamp>"
            f"<Nonce><![CDATA[{nonce}]]></Nonce>"
            f"</xml>"
        )


# ---------------------------------------------------------------------------
# XML message parsing helper
# ---------------------------------------------------------------------------

def parse_message_xml(xml_text: str) -> dict:
    """
    Parse decrypted WeCom XML into a dict.
    Common fields: MsgType, Content, FromUserName, ToUserName, AgentID, MsgId, CreateTime.
    """
    result = {}
    try:
        root = ET.fromstring(xml_text)
        for child in root:
            result[child.tag] = child.text or ""
    except ET.ParseError:
        pass
    return result
