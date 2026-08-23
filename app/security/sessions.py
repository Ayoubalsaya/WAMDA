"""إدارة الجلسات — §٩: كوكي Secure+HttpOnly+SameSite=Strict، انتهاء ٨ ساعات.

هذا الملف منطق قاعدة بيانات نقي (بلا كوكي/HTTP) — طبقة الكوكي في
`app/routers/auth.py`. `now` يُحقن دائماً، لا `datetime.now` هنا.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import Session as SessionModel
from app.models.enums import SessionSubjectType
from app.security import tokens

SESSION_TTL = timedelta(hours=8)


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
    return row


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
