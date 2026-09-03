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
from app.security import audit, passwords, sessions

VALID_ROLES = ("ADMIN", "ACCOUNTANT")
MIN_PASSWORD_LENGTH = 10


class UsernameTakenError(Exception):
    pass


class InvalidRoleError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class SelfLockoutError(Exception):
    """مدير يحاول تعطيل نفسه أو خفض دوره — يُرفض (قد يُقفل النظام بلا مدير)."""


class LastAdminError(Exception):
    """آخر مدير نشط في النظام — لا يُعطَّل ولا يُخفَّض دوره من أي جهة."""


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


def _active_admin_count(db: Session, *, exclude_id: int | None = None) -> int:
    query = select(User).where(User.role == "ADMIN", User.is_active.is_(True))
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return len(db.execute(query).scalars().all())


def update_user(
    db: Session,
    *,
    actor: User,
    user_id: int,
    is_active: bool | None = None,
    role: str | None = None,
) -> User:
    """تعطيل/تفعيل مستخدم و/أو تغيير دوره — مدير فقط (يُفرَض في الموجّه).

    حواجز الأمان:
    - المدير لا يعطّل نفسه ولا يخفض دوره (`SelfLockoutError`).
    - آخر مدير نشط لا يُعطَّل/يُخفَّض من أي جهة (`LastAdminError`).
    عند التعطيل الفعلي: **كل جلسات المستخدم تُبطَل فوراً** (لا انتظار
    انتهاء الـ٨ ساعات). تغيير الدور يعتمد على إعادة فحص `role` الطازج في
    `get_current_user` كل طلب — لا حاجة لإبطال الجلسة، الصلاحية الجديدة/
    المسحوبة تسري من الطلب التالي مباشرةً.
    كل تغيير يُسجَّل في `audit_log` بهوية المُنفِّذ والقيمة قبل/بعد.
    """
    target = db.get(User, user_id)
    if target is None:
        raise UserNotFoundError(f"لا مستخدم بالمعرّف {user_id}")

    if role is not None and role not in VALID_ROLES:
        raise InvalidRoleError(f"دور غير صالح: {role}")

    deactivating = is_active is False and target.is_active
    demoting = role is not None and role != "ADMIN" and target.role == "ADMIN"

    if target.id == actor.id and (deactivating or demoting):
        raise SelfLockoutError("لا يمكنك تعطيل حسابك أو خفض دورك — اطلب ذلك من مدير آخر")

    # حاجز دفاعي: لا يُترَك النظام بلا مدير نشط واحد. حالياً غير قابل
    # للوصول عملياً (المُنفِّذ نفسه مدير نشط، وحاجز النفس أعلاه يمنع
    # استهدافه نفسه) — يبقى لأن `MANAGE_USERS` قد تُمنَح لدور آخر مستقبلاً.
    if (deactivating or demoting) and target.role == "ADMIN" and _active_admin_count(db, exclude_id=target.id) == 0:
        raise LastAdminError("هذا آخر مدير نشط — عيّن مديراً آخر قبل تعطيله أو خفض دوره")  # pragma: no cover

    before = {"is_active": target.is_active, "role": target.role}
    if is_active is not None:
        target.is_active = is_active
    if role is not None:
        target.role = role
    db.flush()

    revoked = 0
    if deactivating:
        revoked = sessions.revoke_all_for_subject(
            db, subject_type=SessionSubjectType.USER, subject_id=target.id
        )

    after = {"is_active": target.is_active, "role": target.role}
    if before != after:
        audit.log_write(
            db,
            actor_type=SessionSubjectType.USER,
            actor_id=actor.id,
            action="USER_UPDATED",
            entity="users",
            entity_id=target.id,
            before=before,
            after={**after, "actor_username": actor.username, "sessions_revoked": revoked},
        )
    return target
