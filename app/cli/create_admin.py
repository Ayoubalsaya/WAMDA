"""إنشاء **أول** مدير — لا حسابات افتراضية (§٩). تفاعلي، عبر CLI على
السيرفر فقط، ويعمل *قبل* وجود أي مصادقة في النظام.

يرفض إن وُجد مدير مسجَّل بالفعل — تصحيح معتمد: تركه مفتوحاً يعني أن أي
وصول لطرفية السيرفر ينشئ مديراً بلا تفويض ويتجاوز النظام كله. المدير
الاحتياطي (§٩) لا يُنشأ من هنا — يُنشأ من **داخل** النظام بمدير مسجَّل
الدخول عبر شاشة المستخدمين (`POST /users`، مرحلة ٩/١٠)، ويُسجَّل في
audit_log بهوية المُنشئ. هذا الأمر أداة الإقلاع الأولى فقط.
"""

from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import passwords

MIN_PASSWORD_LENGTH = 10


def _prompt_password(label: str) -> str:
    while True:
        p1 = getpass.getpass(f"{label}: ")
        if len(p1) < MIN_PASSWORD_LENGTH:
            print(f"قصيرة جداً — {MIN_PASSWORD_LENGTH} أحرف على الأقل.")
            continue
        p2 = getpass.getpass("تأكيد كلمة المرور: ")
        if p1 != p2:
            print("كلمتا المرور غير متطابقتين — أعد المحاولة.")
            continue
        return p1


def run() -> None:
    db = SessionLocal()
    try:
        if db.execute(select(User).where(User.role == "ADMIN")).first() is not None:
            print("يوجد مدير مسجَّل بالفعل — أنشئ المدير الاحتياطي من داخل النظام عبر شاشة المستخدمين.")
            sys.exit(1)

        print("=== إنشاء أول مدير للنظام ===")
        username = input("اسم المستخدم: ").strip()
        if not username:
            print("اسم المستخدم إلزامي.")
            sys.exit(1)
        if db.execute(select(User).where(User.username == username)).first() is not None:
            print("اسم المستخدم مُستخدَم بالفعل.")
            sys.exit(1)

        full_name = input("الاسم الكامل: ").strip() or username
        password = _prompt_password(f"كلمة المرور ({MIN_PASSWORD_LENGTH} أحرف على الأقل)")
        security_question = input("سؤال تحقق لاستعادة الحساب لاحقاً (اختياري لكن يُنصح به بشدة): ").strip()
        security_answer = getpass.getpass("إجابة سؤال التحقق: ") if security_question else ""

        user = User(
            username=username,
            full_name=full_name,
            password_hash=passwords.hash_password(password),
            role="ADMIN",
            security_question=security_question or None,
            security_answer_hash=passwords.hash_security_answer(security_answer) if security_answer else None,
            is_active=True,
            must_change_password=True,
        )
        db.add(user)
        db.commit()
        print(f"\nتم إنشاء المدير '{username}' بنجاح.")
        print("سيُطلب منه تغيير كلمة المرور وتسجيل تطبيق مصادقة (2FA) عند أول دخول.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
