"""إعادة ضبط المصادقة الثنائية (2FA) لمستخدم من السيرفر — فقدان جهاز المصادقة (٢٠٢٦-١٠-٠٢).

يمسح `totp_secret` **فقط** (كلمة المرور لا تُمسّ) فيُسجَّل جهاز جديد عند الدخول التالي (نفس مسار أول دخول:
QR ثم رمز تأكيد). يُنهي كل جلسات المستخدم القائمة فوراً ويصفّر عدّاد المحاولات/القفل، ويُسجَّل في `audit_log`
(`TOTP_RESET`، المنفِّذ = المستخدم نفسه لأن العملية من السيرفر بلا جلسة؛ `after.via = "cli"`).

يختلف عن `reset-admin-password` (يمسح كلمة المرور **و**2FA معاً): هذا للحالة الشائعة — الكلمة معروفة والجهاز ضاع.
أمر طوارئ على السيرفر فقط: يتطلب وصولاً للطرفية، ويطلب تأكيداً كتابياً."""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.models.enums import SessionSubjectType
from app.security import audit, backup_codes, sessions


def reset_totp(db, *, username: str) -> User:
    """المنطق (قابل للاختبار بلا تفاعل). يرفع ValueError إن لم يوجد المستخدم."""
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise ValueError(f"لا مستخدم باسم '{username}'")
    had_secret = user.totp_secret is not None
    user.totp_secret = None
    user.failed_attempts = 0
    user.locked_until = None
    revoked = sessions.revoke_all_for_subject(db, subject_type=SessionSubjectType.USER, subject_id=user.id)
    codes_invalidated = backup_codes.invalidate_all(db, user_id=user.id)  # مرتبطة بالجهاز الممسوح
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action="TOTP_RESET", entity="users", entity_id=user.id,
        before={"had_totp": had_secret}, after={"had_totp": False, "sessions_revoked": revoked, "backup_codes_invalidated": codes_invalidated, "via": "cli"},
    )
    db.flush()
    return user


def run() -> None:
    db = SessionLocal()
    try:
        username = input("اسم المستخدم المراد إعادة ضبط 2FA له: ").strip()
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user is None:
            print("لا مستخدم بهذا الاسم.")
            sys.exit(1)
        print(f"سيُمسح جهاز المصادقة لـ'{user.username}' ({user.full_name}) وتُنهى كل جلساته. كلمة المرور لا تتغيّر.")
        if input(f"اكتب اسم المستخدم '{user.username}' للتأكيد: ").strip() != user.username:
            print("لم يُؤكَّد — لا تغيير.")
            sys.exit(1)
        reset_totp(db, username=user.username)
        db.commit()
        print("تمت إعادة الضبط. عند الدخول التالي: كلمة المرور ثم مسح رمز QR جديد بتطبيق المصادقة.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
