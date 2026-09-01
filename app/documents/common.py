"""سياق Jinja2 مشترك لكل قوالب المستندات — ملف الشركة (اسم/شعار من
`Setting`، المرحلة ٩) + الخط المضمَّن + وقت التوليد. لا cost_rate هنا ولا
في أي دالة بناء سياق مستند يصل عميلاً — يُحجَب عند مصدر البيانات نفسه لا
في القالب (نفس مبدأ بوابة العميل، المرحلة ٩)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.documents.fonts import font_face_css
from app.models import Setting

_COMPANY_KEY = "company_profile"


def base_context(db: OrmSession, *, now: datetime, work_timezone: str) -> dict:
    row = db.execute(select(Setting).where(Setting.key == _COMPANY_KEY)).scalar_one_or_none()
    company_name = (row.value.get("name_ar") if row else None) or "ومضة"
    company_logo = row.value.get("logo_data_url") if row else None
    return {
        "font_css": font_face_css(),
        "company_name": company_name,
        "company_logo_data_uri": company_logo,
        "footer_text": "نظام إدارة تحويلات وصرافة — ليبيا · تركيا · الصين",
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "show_signatures": True,
    }
