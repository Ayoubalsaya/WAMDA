"""أعمدة مُشفَّرة على مستوى التطبيق — يُستعمل لـ`users.totp_secret` (٢٠٢٦-١٠-٠٦).

Fernet بمفتاح **مستقل** `TOTP_ENCRYPTION_KEY` (لا يُستعمل مفتاح النسخ الاحتياطي): تسرّب نسخة قاعدة البيانات وحدها لا يكشف أسرار 2FA،
وتسرّب مفتاح النسخ لا يكشفها. القيمة المخزَّنة تبدأ بـ`enc1:` ليُميَّز المشفَّر من النص الصريح السابق (قبل الترحيل).

· الإنتاج (`APP_ENV=production`): المفتاح إلزامي (يرفض الإقلاع بدونه — `config.py`)، والقيمة بلا بادئة `enc1:` تُرفض عند القراءة (لا نص صريح صامت).
· محلياً بلا مفتاح: تمرير شفاف بلا تشفير (راحة تطوير فقط)؛ الاختبارات تضبط مفتاحاً فعلياً فيُختبر المسار الحقيقي.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import settings

PREFIX = "enc1:"


@lru_cache(maxsize=4)
def _fernet_for(key: str) -> Fernet:
    return Fernet(key.encode())


def current_fernet() -> Optional[Fernet]:
    key = settings.totp_encryption_key
    return _fernet_for(key) if key else None


def encrypt_value(plain: str, fernet: Fernet) -> str:
    return PREFIX + fernet.encrypt(plain.encode()).decode()


def decrypt_value(stored: str, fernet: Fernet) -> str:
    return fernet.decrypt(stored[len(PREFIX):].encode()).decode()


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        fernet = current_fernet()
        if fernet is None:
            if settings.app_env == "production":  # دفاع ثانٍ — الإقلاع يرفض أصلاً
                raise RuntimeError("TOTP_ENCRYPTION_KEY غير مضبوط — لا كتابة لسرّ 2FA بنص صريح في الإنتاج")
            return value
        return encrypt_value(value, fernet)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if not value.startswith(PREFIX):
            if settings.app_env == "production":
                raise RuntimeError("سرّ 2FA مخزَّن بنص صريح — شغّل «alembic upgrade head» بعد ضبط TOTP_ENCRYPTION_KEY")
            return value
        fernet = current_fernet()
        if fernet is None:
            raise RuntimeError("سرّ 2FA مشفَّر لكن TOTP_ENCRYPTION_KEY غير مضبوط")
        try:
            return decrypt_value(value, fernet)
        except InvalidToken as exc:
            raise RuntimeError("تعذّر فكّ سرّ 2FA — TOTP_ENCRYPTION_KEY لا يطابق المفتاح الذي شُفّر به") from exc
