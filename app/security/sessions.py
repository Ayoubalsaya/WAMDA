"""إدارة الجلسات — §٩: كوكي Secure+HttpOnly+SameSite=Strict، سقف مطلق ٨ ساعات + مهلة خمول (٣٠ د موظف / ١٥ د بوابة).

هذا الملف منطق قاعدة بيانات نقي (بلا كوكي/HTTP) — طبقة الكوكي في
`app/routers/auth.py`. `now` يُحقن دائماً، لا `datetime.now` هنا.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.config import settings
from app.models import Session as SessionModel
from app.models.enums import SessionSubjectType
from app.security import tokens

SESSION_TTL = timedelta(hours=8)
TOUCH_INTERVAL = timedelta(minutes=1)  # لا كتابة لكل طلب


def idle_timeout_for(subject_type: SessionSubjectType) -> timedelta:
    minutes = settings.staff_idle_timeout_minutes if subject_type == SessionSubjectType.USER else settings.portal_idle_timeout_minutes
    return timedelta(minutes=minutes)


def create_session(
    db: OrmSession,
    *,
    subject_type: SessionSubjectType,
    subject_id: int,
    now: datetime,
    ip: Optional[str] = None,
    ua: Optional[str] = None,
) -> tuple[SessionModel, str]:
    """يُعيد (صف الجلسة، الرمز الخام — يُرسَل للعميل مرة واحدة فقط)."""
    raw_token, token_hash = tokens.generate_session_token()
    row = SessionModel(
        subject_type=subject_type,
        subject_id=subject_id,
        token_hash=token_hash,
        created_at=now,
        last_seen_at=now,
        expires_at=now + SESSION_TTL,
        ip=ip,
        ua=ua,
    )
    db.add(row)
    db.flush()
    return row, raw_token


def get_valid_session(db: OrmSession, raw_token: str, now: datetime) -> Optional[SessionModel]:
    token_hash = tokens.hash_token(raw_token)
    row = db.execute(select(SessionModel).where(SessionModel.token_hash == token_hash)).scalar_one_or_none()
    if row is None or row.expires_at <= now:
        return None
    if now - row.last_seen_at >= idle_timeout_for(row.subject_type):  # خمول — تنتهي الجلسة (الصف يبقى حتى الخروج/الانتهاء المطلق)
        return None
    return row


def touch(db: OrmSession, row: SessionModel, now: datetime) -> bool:
    """يُسجّل نشاطاً فعلياً. يُرجع True إن كتب فعلاً (فعلى المستدعي أن يلتزم)؛ بحدّ أقصى مرة كل `TOUCH_INTERVAL`."""
    if now - row.last_seen_at < TOUCH_INTERVAL:
        return False
    row.last_seen_at = now
    db.flush()
    return True


def revoke_session(db: OrmSession, session_row: SessionModel) -> None:
    db.delete(session_row)
    db.flush()


def revoke_all_for_subject(db: OrmSession, *, subject_type: SessionSubjectType, subject_id: int) -> int:
    """يُستدعى عند تغيير كلمة المرور — يُبطل كل الجلسات الأخرى القائمة."""
    rows = db.execute(
        select(SessionModel).where(
            SessionModel.subject_type == subject_type, SessionModel.subject_id == subject_id
        )
    ).scalars().all()
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)
