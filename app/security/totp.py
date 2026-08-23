"""٢FA بمعيار TOTP (RFC 6238) — إلزامي للمدير والمحاسب (§٧-١)."""

from __future__ import annotations

import pyotp

ISSUER = "ومضة"


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, *, username: str) -> str:
    """رابط QR لتطبيقات المصادقة (Google Authenticator وما شابه)."""
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def verify_totp_code(secret: str | None, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False
