"""CSRF — نمط الكوكي المزدوج (double-submit cookie): رمز يُخزَّن في كوكي
غير HttpOnly ويجب تكراره في ترويسة الطلب لكل كتابة (§٩)."""

from __future__ import annotations

from app.security.tokens import constant_time_equal, generate_raw_token

from app.config import settings

# أسماء الكوكيز تتبع البيئة (٢٠٢٦-١٠-١٢): الكوكيز لا تفصل المنافذ، فنفق الإنتاج (127.0.0.1:18000) وخادم التطوير
# (127.0.0.1:8000) يتشاركان خزنة الكوكيز — اسم مختلف في الإنتاج يمنع كتابة جلسة بيئة فوق جلسة الأخرى.
COOKIE_PREFIX = "wamda_prod" if settings.app_env == "production" else "wamda"
CSRF_COOKIE_NAME = f"{COOKIE_PREFIX}_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return generate_raw_token()


def verify_csrf_token(cookie_value: str | None, header_value: str | None) -> bool:
    return constant_time_equal(cookie_value, header_value)
