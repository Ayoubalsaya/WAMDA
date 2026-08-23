"""رموز الجلسات وCSRF — عشوائية تشفيرياً؛ لا يُخزَّن الرمز الخام أبداً في
القاعدة، تُخزَّن بصمته (SHA-256) فقط في `sessions.token_hash`.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_raw_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_session_token() -> tuple[str, str]:
    """يُعيد (الرمز الخام للعميل مرة واحدة، بصمته للتخزين)."""
    raw = generate_raw_token()
    return raw, hash_token(raw)


def constant_time_equal(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return secrets.compare_digest(a, b)
