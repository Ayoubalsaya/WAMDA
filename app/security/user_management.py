"""إنشاء مستخدمين من **داخل** النظام — بمدير مسجَّل الدخول، لا CLI (§٩).

هذا هو المسار الصحيح للمدير الاحتياطي: `app/cli/create_admin.py` أداة
الإقلاع الأولى فقط وترفض العمل إن وُجد مدير بالفعل — أي مدير إضافي بعده
يُنشأ هنا، ويُسجَّل في `audit_log` بهوية المُنشئ الحقيقية.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.enums import SessionSubjectType
from app.security import audit, passwords

VALID_ROLES = ("ADMIN", "ACCOUNTANT")
MIN_PASSWORD_LENGTH = 10


class UsernameTakenError(Exception):
    pass


class InvalidRoleError(Exception):
    pass


def create_user(
    db: Session,
    *,
    created_by: User,
    username: str,
    full_name: str,
    role: str,
    initial_password: str,
    now: datetime,
    security_question: str | None = None,
    security_answer: str | None = None,
) -> User:
    if role not in VALID_ROLES:
        raise InvalidRoleError(f"دور غير صالح: {role}")
    if db.execute(select(User).where(User.username == username)).first() is not None:
        raise UsernameTakenError(f"اسم المستخدم {username} مُستخدَم بالفعل")

    user = User(
        username=username,
        full_name=full_name,
        password_hash=passwords.hash_password(initial_password),
        role=role,
        security_question=security_question,
        security_answer_hash=passwords.hash_security_answer(security_answer) if security_answer else None,
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.flush()

    audit.log_write(
        db,
        actor_type=SessionSubjectType.USER,
        actor_id=created_by.id,
        action="USER_CREATED",
        entity="users",
        entity_id=user.id,
        after={"username": username, "role": role, "created_by_username": created_by.username},
    )
    return user
