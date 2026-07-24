"""外部身份证明的密码学验证。"""

from __future__ import annotations

import base64
import binascii
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class IdentityProofError(ValueError):
    """身份证明格式无效或签名验证失败。"""


def decode_ed25519_public_key(value: str) -> bytes:
    """解析 Base64 编码的 32 字节 Ed25519 公钥。"""
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise IdentityProofError("public_key 不是有效 Base64") from exc
    if len(raw) != 32:
        raise IdentityProofError("Ed25519 public_key 必须是 32 字节")
    return raw


def public_key_subject(public_key: str) -> str:
    """从公钥稳定推导外部身份 subject。"""
    return hashlib.sha256(decode_ed25519_public_key(public_key)).hexdigest()


def verify_ed25519_signature(
    public_key: str,
    message: str,
    signature: str,
) -> None:
    """验证客户端对服务器 challenge 原文的 Ed25519 签名。"""
    key_bytes = decode_ed25519_public_key(public_key)
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise IdentityProofError("signature 不是有效 Base64") from exc
    if len(signature_bytes) != 64:
        raise IdentityProofError("Ed25519 signature 必须是 64 字节")
    try:
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(
            signature_bytes,
            message.encode("utf-8"),
        )
    except InvalidSignature as exc:
        raise IdentityProofError("身份签名验证失败") from exc
