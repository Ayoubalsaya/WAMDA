"""إعادة تعيين كلمة مرور مدير من السيرفر مباشرة — طوارئ فقدان الوصول (§٩).

يفترض فقدان جهاز 2FA أيضاً (سيناريو الطوارئ الواقعي) فيمسح `totp_secret`
معه — يُعاد تسجيله عند أول دخول تالٍ (نفس مسار `login_step2_setup`).
"""

from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import passwords

MIN_PASSWORD_LENGTH = 10


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

        user.password_hash = passwords.hash_password(p1)
        user.must_change_password = True
        user.failed_attempts = 0
        user.locked_until = None
        user.totp_secret = None
        db.commit()
        print(f"\nأُعيد تعيين كلمة مرور '{username}'.")
        print("سيُطلب منه تغييرها وإعادة تسجيل 2FA عند الدخول التالي.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
