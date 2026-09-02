"""مخطّطات شاشة سجل التدقيق العامة (§٩ المرحلة ١١) — عرض عام فوق
`audit_log` لكل الإجراءات، بخلاف `reports.balance_overrides` (عرض مفلتَر
مُخصَّص لتجاوزات الرصيد فقط)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AuditLogRow(BaseModel):
    id: int
    at: datetime
    actor_type: str
    actor_id: int
    actor_label: str
    action: str
    entity: str
    entity_id: Optional[int] = None
    before_json: Optional[dict] = None
    after_json: Optional[dict] = None
