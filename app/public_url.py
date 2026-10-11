"""العنوان العام للنظام (`PUBLIC_BASE_URL`) كما يدخل في **رموز QR المطبوعة وروابط الدعوة** (٢٠٢٦-١٠-١٢، قرار مالك).

رمز QR المطبوع على إيصال أو بطاقة يبقى متداوَلاً للأبد، ورابط دعوة يُرسَل لعميل لا يُستردّ — فلا يُولَّد أيٌّ منهما بعنوان مؤقت
(`http://127.0.0.1:8000` أو عنوان IP أو HTTP). في الإنتاج (`APP_ENV=production`) يُشترط أن يكون `PUBLIC_BASE_URL` نطاقاً
بـ`https://` (لا IP ولا localhost)؛ وإلا **يُرفض التوليد برسالة عربية واضحة** (503) بدل مستند برمز مكسور.
محلياً/في الاختبار يبقى الافتراضي `http://127.0.0.1:8000` كما كان."""

from __future__ import annotations

import ipaddress
from typing import Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, status

from app.config import settings

LOCAL_DEFAULT = "http://127.0.0.1:8000"

NOT_CONFIGURED_MESSAGE = (
    "لا يمكن توليد هذا المستند/الرابط الآن: عنوان النظام العام (PUBLIC_BASE_URL) لم يُضبَط بعد على نطاق HTTPS. "
    "رمز QR المطبوع والروابط المُرسَلة تبقى للأبد، فلا تُولَّد بعنوان مؤقت. اضبط النطاق ثم أعد المحاولة."
)


class PublicBaseUrlNotConfiguredError(Exception):
    pass


def _is_ip_or_local(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def base_url() -> str:
    """العنوان بلا شرطة أخيرة. في الإنتاج يرفع `PublicBaseUrlNotConfiguredError` إن لم يكن نطاق HTTPS صالحاً."""
    raw = (settings.public_base_url or "").strip().rstrip("/")
    if settings.app_env != "production":
        return raw or LOCAL_DEFAULT
    parts = urlsplit(raw)
    if not raw or parts.scheme != "https" or not parts.hostname or _is_ip_or_local(parts.hostname) or parts.path not in ("", "/"):
        raise PublicBaseUrlNotConfiguredError(NOT_CONFIGURED_MESSAGE)
    return f"https://{parts.netloc}"


def base_url_or_none() -> Optional[str]:
    try:
        return base_url()
    except PublicBaseUrlNotConfiguredError:
        return None


def require_public_base_url() -> str:
    """FastAPI dependency: يُشغَّل **قبل** أي عمل في المسار (فلا دعوة تُنشأ ولا مستند يُولَّد ثم يُرفض)."""
    try:
        return base_url()
    except PublicBaseUrlNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
