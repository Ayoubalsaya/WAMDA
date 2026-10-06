"""دخول بوابة العميل — §٧-٦: دخول بالكود (`Client.code`) وكلمة مرور، بلا
TOTP إطلاقاً (غير مذكور في §٧-٦ خلافاً لدخول الموظف §٧-١ الذي يفرضه دائماً)
— خطوة واحدة تنتهي بجلسة `SessionSubjectType.CLIENT` مباشرة.

كل دالة هنا تستقبل `now` صراحة — لا `datetime.now` مباشر (نفس قاعدة المحرك).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Client
from app.models import Session as SessionModel
from app.models.enums import SessionSubjectType
from app.security import audit, passwords, portal_lockout, sessions


class InvalidPortalCredentialsError(Exception):
    pass


@dataclass
class PortalLoginResult:
    session: SessionModel
    raw_token: str


def login(
    db: Session, *, code: str, password: str, now: datetime, ip: Optional[str] = None, ua: Optional[str] = None,
) -> PortalLoginResult:
    client = db.execute(select(Client).where(Client.code == code)).scalar_one_or_none()
    # رسالة عامة واحدة في كل حالات الرفض (عدم وجود/تعطيل عام/تعطيل بوابة
    # تحديداً) — لا تكشف أيّها فعلياً، نفس مبدأ auth.py.
    if client is None or not client.is_active or not client.portal_enabled:
        raise InvalidPortalCredentialsError("الكود أو كلمة المرور غير صحيحة")

    portal_lockout.check_not_locked(client, now)

    if not passwords.verify_password(password, client.portal_password_hash):
        portal_lockout.record_failed_attempt(db, client, now)
        raise InvalidPortalCredentialsError("الكود أو كلمة المرور غير صحيحة")

    portal_lockout.reset_failed_attempts(db, client)
    client.portal_last_login_at = now
    db.flush()
    session_row, raw_token = sessions.create_session(
        db, subject_type=SessionSubjectType.CLIENT, subject_id=client.id, now=now, ip=ip, ua=ua
    )
    audit.log_write(
        db, actor_type=SessionSubjectType.CLIENT, actor_id=client.id, action="PORTAL_LOGIN_SUCCESS",
        entity="clients", entity_id=client.id, ip=ip,
    )
    return PortalLoginResult(session=session_row, raw_token=raw_token)


def change_password(
    db: Session, *, client: Client, new_password: str, now: datetime, keep_session_id: Optional[str] = None,
) -> None:
    client.portal_password_hash = passwords.hash_password(new_password)
    db.flush()
    rows = db.execute(
        select(SessionModel).where(
            SessionModel.subject_type == SessionSubjectType.CLIENT, SessionModel.subject_id == client.id
        )
    ).scalars().all()
    for row in rows:
        if keep_session_id is not None and str(row.id) == str(keep_session_id):
            continue
        db.delete(row)
    db.flush()
    audit.log_write(
        db, actor_type=SessionSubjectType.CLIENT, actor_id=client.id, action="PORTAL_PASSWORD_CHANGED",
        entity="clients", entity_id=client.id,
    )
