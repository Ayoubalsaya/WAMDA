"""شاشة سجل التدقيق العامة (§٩ المرحلة ١١) — عرض/تصفية `audit_log` كاملاً
(القراءة فقط، append-only بمشغّل قاعدة أصلاً). مدير فقط (`VIEW_AUDIT_LOG`)
— بيانات حسّاسة (تجاوزات صلاحية، تغييرات بيانات اعتماد).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import get_db
from app.models import Client, User
from app.models.enums import SessionSubjectType
from app.schemas.audit import AuditLogRow
from app.security import audit
from app.security.deps import require_role
from app.security.permissions import Action

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=list[AuditLogRow])
def list_audit_log(
    actor_type: Optional[SessionSubjectType] = None,
    entity: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: OrmSession = Depends(get_db),
    current_user: User = Depends(require_role(Action.VIEW_AUDIT_LOG)),
) -> list[AuditLogRow]:
    rows = audit.query_audit_log(
        db, actor_type=actor_type, entity=entity, action=action, date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    if not rows:
        return []
    user_ids = {r.actor_id for r in rows if r.actor_type == SessionSubjectType.USER}
    client_ids = {r.actor_id for r in rows if r.actor_type == SessionSubjectType.CLIENT}
    users_by_id = {u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()} if user_ids else {}
    clients_by_id = {c.id: c for c in db.execute(select(Client).where(Client.id.in_(client_ids))).scalars().all()} if client_ids else {}

    def _label(r) -> str:
        if r.actor_type == SessionSubjectType.USER:
            u = users_by_id.get(r.actor_id)
            return u.username if u else f"مستخدم #{r.actor_id}"
        c = clients_by_id.get(r.actor_id)
        return c.code if c else f"عميل #{r.actor_id}"

    return [
        AuditLogRow(
            id=r.id, at=r.at, actor_type=r.actor_type.value, actor_id=r.actor_id, actor_label=_label(r),
            action=r.action, entity=r.entity, entity_id=r.entity_id, before_json=r.before_json, after_json=r.after_json,
        )
        for r in rows
    ]
