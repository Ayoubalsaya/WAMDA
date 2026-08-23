"""§٥ قاعدة ١١: كل كتابة تُسجَّل في `audit_log` (Append-only) مع `request_id`.

الجدول نفسه Append-only بمشغّل قاعدة (`trg_audit_log_append_only`، المرحلة
١) — هذا مجرد مُنشئ صف مريح، لا منطق إضافي.
"""

from __future__ import annotations

from typing import Optional

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
