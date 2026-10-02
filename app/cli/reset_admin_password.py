"""إعادة تعيين كلمة مرور مدير من السيرفر مباشرة — طوارئ فقدان الوصول (§٩).

يفترض فقدان جهاز 2FA أيضاً (سيناريو الطوارئ الواقعي) فيمسح `totp_secret`
معه — يُعاد تسجيله عند أول دخول تالٍ (نفس مسار `login_step2_setup`).

٢٠٢٦-١٠-٠٣: مساوٍ لـ`reset-2fa` في الضمانات — **يُنهي كل جلسات المدير** فوراً (كلمة المرور القديمة قد تكون مسرَّبة، فلا تبقى
جلسة قائمة بها)، **يُسجَّل في `audit_log`** (`ADMIN_PASSWORD_RESET`، `via: cli`، بلا كلمة المرور نفسها ولا هاشها)، و**يطلب تأكيداً
كتابياً** باسم المستخدم قبل التنفيذ. المنطق في `reset_password` (قابل للاختبار بلا تفاعل)."""

from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.models.enums import SessionSubjectType
from app.security import audit, passwords, sessions

MIN_PASSWORD_LENGTH = 10


def reset_password(db, *, username: str, new_password: str) -> User:
    """يرفع ValueError إن لم يوجد مدير بهذا الاسم أو قصرت الكلمة."""
    user = db.execute(select(User).where(User.username == username, User.role == "ADMIN")).scalar_one_or_none()
    if user is None:
        raise ValueError(f"لا مدير باسم '{username}'")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"كلمة المرور قصيرة — {MIN_PASSWORD_LENGTH} أحرف على الأقل")
    had_totp = user.totp_secret is not None
    user.password_hash = passwords.hash_password(new_password)
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    user.totp_secret = None
    revoked = sessions.revoke_all_for_subject(db, subject_type=SessionSubjectType.USER, subject_id=user.id)
    _clear_backup_codes(db, user.id)
    audit.log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action="ADMIN_PASSWORD_RESET", entity="users", entity_id=user.id,
        before={"had_totp": had_totp},
        after={"must_change_password": True, "totp_cleared": True, "sessions_revoked": revoked, "via": "cli"},
    )
    db.flush()
    return user


def _clear_backup_codes(db, user_id: int) -> None:
    """الرموز الاحتياطية مرتبطة بجهاز المصادقة الذي مُسح — تُبطَل معه (تُنشأ من جديد بعد إعداد الجهاز)."""
    from app.security import backup_codes

    backup_codes.invalidate_all(db, user_id=user_id)


def run() -> None:
    db = SessionLocal()
    try:
        username = input("اسم مستخدم المدير: ").strip()
        user = db.execute(
            select(User).where(User.username == username, User.role == "ADMIN")
        ).scalar_one_or_none()
        if user is None:
            print("لا مدير بهذا الاسم.")
            sys.exit(1)

        p1 = getpass.getpass(f"كلمة المرور الجديدة ({MIN_PASSWORD_LENGTH} أحرف على الأقل): ")
        if len(p1) < MIN_PASSWORD_LENGTH:
            print("قصيرة جداً.")
            sys.exit(1)
        p2 = getpass.getpass("تأكيد: ")
        if p1 != p2:
            print("غير متطابقتين.")
            sys.exit(1)

        print(f"\nسيُغيَّر كلمة مرور '{user.username}' ({user.full_name})، ويُمسح جهاز 2FA، وتُنهى كل جلساته.")
        if input(f"اكتب اسم المستخدم '{user.username}' للتأكيد: ").strip() != user.username:
            print("لم يُؤكَّد — لا تغيير.")
            sys.exit(1)

        reset_password(db, username=user.username, new_password=p1)
        db.commit()
        print(f"\nأُعيد تعيين كلمة مرور '{username}'.")
        print("سيُطلب منه تغييرها وإعادة تسجيل 2FA عند الدخول التالي.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
