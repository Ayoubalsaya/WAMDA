"""فك قفل حساب مستخدم من السيرفر (٢٠٢٦-١٠-١٢) — يصفّر عدّاد المحاولات الفاشلة و`locked_until` **فقط**.

لا يمسّ كلمة المرور ولا 2FA ولا الجلسات (على خلاف `reset-2fa` و`reset-admin-password`). القفل ينتهي وحده بعد ١٥ دقيقة؛
هذا للحالة المستعجلة. لا يفكّ **إيقاف العنوان** (حدّ المعدل في ذاكرة العملية): ذلك بـ`sudo systemctl restart wamda`.
يُسجَّل في `audit_log` (`ACCOUNT_UNLOCKED`، `via=cli`)."""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.models.enums import SessionSubjectType
from app.security import audit


def unlock_user(db, *, username: str) -> User:
    """المنطق (قابل للاختبار بلا تفاعل). يرفع ValueError إن لم يوجد المستخدم."""
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise ValueError(f"لا مستخدم باسم '{username}'")
    before = {"failed_attempts": user.failed_attempts, "locked": user.locked_until is not None}
    user.failed_attempts = 0
    user.locked_until = None
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action="ACCOUNT_UNLOCKED", entity="users",
        entity_id=user.id, before=before, after={"failed_attempts": 0, "locked": False, "via": "cli"},
    )
    db.flush()
    return user


def run() -> None:
    db = SessionLocal()
    try:
        username = input("اسم المستخدم المراد فك قفله: ").strip()
        try:
            user = unlock_user(db, username=username)
        except ValueError as exc:
            print(exc)
            sys.exit(1)
        db.commit()
        print(f"فُكّ قفل '{user.username}' (كلمة المرور و2FA لم يتغيّرا).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
