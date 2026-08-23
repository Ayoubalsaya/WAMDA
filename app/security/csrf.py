"""CSRF — نمط الكوكي المزدوج (double-submit cookie): رمز يُخزَّن في كوكي
غير HttpOnly ويجب تكراره في ترويسة الطلب لكل كتابة (§٩)."""

from __future__ import annotations

from app.security.tokens import constant_time_equal, generate_raw_token

CSRF_COOKIE_NAME = "wamda_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return generate_raw_token()


def verify_csrf_token(cookie_value: str | None, header_value: str | None) -> bool:
    return constant_time_equal(cookie_value, header_value)
