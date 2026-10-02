"""رموز احتياطية للمصادقة الثنائية (٢٠٢٦-١٠-٠٣).

· عشرة رموز عشوائية (٥٠ بت لكل منها: ١٠ حروف/أرقام من أبجدية بلا التباس)، **كل منها لمرة واحدة**، تُعرض مرة واحدة فقط عند الإنشاء؛
· تُخزَّن **هاشاً** (SHA-256 مع بادئة نطاق) لا نصاً، ولا تُسجَّل في أي سجل (التدقيق يحمل العدد المتبقّي فقط)؛
· تحلّ محل رمز تطبيق المصادقة **فقط** — كلمة المرور مطلوبة دائماً قبلها (`login_step1`)، وتخضع لنفس القفل (٥ محاولات) وحدّ معدل الدخول؛
· إعادة الإنشاء (`generate`) تُبطل كل الرموز السابقة؛
· الاستهلاك ذرّي (`UPDATE … WHERE used_at IS NULL RETURNING`) فلا يُستعمل الرمز مرتين حتى تحت التزامن.
هاش بسيط بلا ملح لكل رمز مقبول لأن الرمز عالي الإنتروبيا وعشوائي (لا كلمة مرور يختارها بشر) ويلزمه قبله كلمة المرور."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import UserBackupCode

CODE_COUNT = 10
LOW_THRESHOLD = 3          # يبقى ٣ أو أقل ← تنبيه
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بلا I/O/0/1 (التباس)
_GROUP = 5
_DOMAIN = "wamda-backup-code:v1:"


def normalize(code: str) -> str:
    """يتجاهل الحالة والشرطة والمسافات: `abcde-23456` = `ABCDE23456`."""
    return re.sub(r"[^A-Za-z0-9]", "", code or "").upper()


def _hash(code: str) -> str:
    return hashlib.sha256((_DOMAIN + normalize(code)).encode("utf-8")).hexdigest()


def _new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(2 * _GROUP))
    return f"{raw[:_GROUP]}-{raw[_GROUP:]}"


def remaining(db: Session, *, user_id: int) -> int:
    return db.execute(
        select(func.count()).select_from(UserBackupCode).where(
            UserBackupCode.user_id == user_id, UserBackupCode.used_at.is_(None), UserBackupCode.invalidated_at.is_(None)
        )
    ).scalar_one()


def invalidate_all(db: Session, *, user_id: int, now: datetime | None = None) -> int:
    """يُبطل كل الرموز الحيّة (إعادة إنشاء · إعادة ضبط 2FA/كلمة المرور). يُعيد عددها."""
    result = db.execute(
        update(UserBackupCode)
        .where(UserBackupCode.user_id == user_id, UserBackupCode.used_at.is_(None), UserBackupCode.invalidated_at.is_(None))
        .values(invalidated_at=now or func.now())
    )
    db.flush()
    return result.rowcount or 0


def generate(db: Session, *, user_id: int, now: datetime) -> list[str]:
    """ينشئ عشرة رموز جديدة **ويُبطل كل السابقة**. الرموز النصية تُعاد هنا مرة واحدة ولا تُحفَظ نصاً في أي مكان."""
    invalidate_all(db, user_id=user_id, now=now)
    codes: list[str] = []
    seen: set[str] = set()
    while len(codes) < CODE_COUNT:
        c = _new_code()
        if normalize(c) in seen:
            continue
        seen.add(normalize(c))
        codes.append(c)
    for c in codes:
        db.add(UserBackupCode(user_id=user_id, code_hash=_hash(c), created_at=now))
    db.flush()
    return codes


def consume(db: Session, *, user_id: int, code: str, now: datetime) -> bool:
    """يستهلك الرمز إن كان حيّاً لهذا المستخدم. ذرّي: UPDATE واحد بشرط `used_at IS NULL`."""
    if len(normalize(code)) != 2 * _GROUP:
        return False
    row = db.execute(
        update(UserBackupCode)
        .where(
            UserBackupCode.user_id == user_id, UserBackupCode.code_hash == _hash(code),
            UserBackupCode.used_at.is_(None), UserBackupCode.invalidated_at.is_(None),
        )
        .values(used_at=now)
        .returning(UserBackupCode.id)
    ).first()
    db.flush()
    return row is not None
