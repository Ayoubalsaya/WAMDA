"""رفض الإقلاع في الإنتاج إن كان حدّ محاولات الدخول أضعف من الحدّ الصارم
(طلب مالك صريح، ٢٠٢٦-١٠-٠٢): APP_ENV=production يفرض حدّاً أقصى ٨ محاولات
لكلٍّ من LOGIN_RATE_LIMIT_MAX وPORTAL_LOGIN_RATE_LIMIT_MAX، ونافذة لا تقلّ
عن ٥ دقائق (٣٠٠ث) — عُدِّل ٢٠٢٦-١٠-١٢ من ٥ محاولات/١٥ دقيقة. محلياً (APP_ENV=local) القيم حرة بلا أي قيد — التصحيح
الصامت يخفي خطأ الإعداد، رفض الإقلاع يكشفه فوراً.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import (
    PRODUCTION_MAX_LOGIN_RATE_LIMIT,
    PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS,
    Settings,
)

_DB_URL = "postgresql+psycopg://wamda_app:x@localhost:5432/wamda_db"
_TOTP_KEY = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()


def test_production_with_weak_login_limit_refuses_to_boot():
    with pytest.raises(ValidationError) as exc:
        Settings(database_url=_DB_URL, app_env="production", totp_encryption_key=_TOTP_KEY, login_rate_limit_max=PRODUCTION_MAX_LOGIN_RATE_LIMIT + 1)
    message = str(exc.value)
    assert f"LOGIN_RATE_LIMIT_MAX={PRODUCTION_MAX_LOGIN_RATE_LIMIT + 1}" in message
    assert str(PRODUCTION_MAX_LOGIN_RATE_LIMIT) in message


def test_production_with_weak_portal_login_limit_refuses_to_boot():
    with pytest.raises(ValidationError) as exc:
        Settings(database_url=_DB_URL, app_env="production", totp_encryption_key=_TOTP_KEY, portal_login_rate_limit_max=PRODUCTION_MAX_LOGIN_RATE_LIMIT + 1)
    assert f"PORTAL_LOGIN_RATE_LIMIT_MAX={PRODUCTION_MAX_LOGIN_RATE_LIMIT + 1}" in str(exc.value)


def test_production_with_short_window_refuses_to_boot():
    with pytest.raises(ValidationError) as exc:
        Settings(database_url=_DB_URL, app_env="production", totp_encryption_key=_TOTP_KEY, login_rate_limit_window_seconds=PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS - 1)
    message = str(exc.value)
    assert f"LOGIN_RATE_LIMIT_WINDOW_SECONDS={PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS - 1}" in message
    assert str(PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS) in message


def test_production_with_strict_values_boots_fine():
    s = Settings(
        database_url=_DB_URL,
        app_env="production", totp_encryption_key=_TOTP_KEY,
        login_rate_limit_max=PRODUCTION_MAX_LOGIN_RATE_LIMIT,
        portal_login_rate_limit_max=PRODUCTION_MAX_LOGIN_RATE_LIMIT,
        login_rate_limit_window_seconds=PRODUCTION_MIN_RATE_LIMIT_WINDOW_SECONDS,
    )
    assert s.login_rate_limit_max == PRODUCTION_MAX_LOGIN_RATE_LIMIT


def test_local_with_weak_values_boots_fine():
    """محلياً لا قيد إطلاقاً — حتى قيم أوسع من الحدّ الصارم في الإنتاج."""
    s = Settings(
        database_url=_DB_URL,
        app_env="local",
        login_rate_limit_max=10,
        portal_login_rate_limit_max=30,
        login_rate_limit_window_seconds=300,
    )
    assert s.login_rate_limit_max == 10
    assert s.portal_login_rate_limit_max == 30
