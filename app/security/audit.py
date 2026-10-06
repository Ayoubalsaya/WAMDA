"""§٥ قاعدة ١١: كل كتابة تُسجَّل في `audit_log` (Append-only) مع `request_id`.

الجدول نفسه Append-only بمشغّل قاعدة (`trg_audit_log_append_only`، المرحلة
١) — هذا مجرد مُنشئ صف مريح، لا منطق إضافي.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.models.enums import SessionSubjectType


def log_write(
    db: Session,
    *,
    actor_type: SessionSubjectType,
    actor_id: int,
    action: str,
    entity: str,
    entity_id: Optional[int] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    ip: Optional[str] = None,
    request_id: Optional[str] = None,
) -> AuditLog:
    row = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before_json=before,
        after_json=after,
        ip=ip,
        request_id=request_id,
    )
    db.add(row)
    db.flush()
    return row


def log_user_write(
    db: Session, user, *, action: str, entity: str, entity_id: Optional[int] = None,
    before: Optional[dict] = None, after: Optional[dict] = None,
) -> AuditLog:
    """`log_write` لمنفِّذ موظف — اختصار لمسارات الإعدادات/الشركاء/المطابقة (§٥-١١)."""
    return log_write(
        db, actor_type=SessionSubjectType.USER, actor_id=user.id, action=action, entity=entity,
        entity_id=entity_id, before=before, after=after,
    )


def query_audit_log(
    db: Session,
    *,
    actor_id: Optional[int] = None,
    actor_type: Optional[SessionSubjectType] = None,
    entity: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """عرض عام مُصفَّى فوق `audit_log` — شاشة سجل التدقيق (§٩ المرحلة ١١).
    الأحدث أولاً دائماً."""
    query = select(AuditLog).order_by(AuditLog.at.desc())
    if actor_id is not None:
        query = query.where(AuditLog.actor_id == actor_id)
    if actor_type is not None:
        query = query.where(AuditLog.actor_type == actor_type)
    if entity is not None:
        query = query.where(AuditLog.entity == entity)
    if action is not None:
        query = query.where(AuditLog.action == action)
    if date_from is not None:
        query = query.where(AuditLog.at >= date_from)
    if date_to is not None:
        query = query.where(AuditLog.at < date_to + timedelta(days=1))  # نهاية اليوم شاملة
    query = query.limit(limit).offset(offset)
    return list(db.execute(query).scalars().all())
