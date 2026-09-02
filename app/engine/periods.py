"""إقفال الفترة الشهرية وفتحها (§٩) — إدارية بحتة: لا تُنشئ قيوداً ولا
تلمس أي رصيد، فقط تُسجِّل حالة `Period(year, month)` التي يقرأها بالفعل
`posting._check_backdate_gate` (المرحلة ٢، بلا تغيير هناك) لتفعيل قاعدة
"قيد بأثر رجعي بعد إقفال الفترة يحتاج مديراً + سبباً" تلقائياً بمجرد
الإقفال الحقيقي — لا حاجة لأي تعديل في محرك الترحيل نفسه.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Period


class PeriodAlreadyClosedError(Exception):
    pass


class PeriodNotClosedError(Exception):
    pass


def close_period(db: Session, *, year: int, month: int, closed_by: int, now: datetime) -> Period:
    period = db.get(Period, (year, month))
    if period is not None and period.is_closed:
        raise PeriodAlreadyClosedError(f"الفترة {year}-{month:02d} مُقفلة أصلاً")
    if period is None:
        period = Period(year=year, month=month, is_closed=True, closed_by=closed_by, closed_at=now)
        db.add(period)
    else:
        period.is_closed = True
        period.closed_by = closed_by
        period.closed_at = now
    db.flush()
    return period


def reopen_period(db: Session, *, year: int, month: int) -> Period:
    """صلاحية REOPEN_CLOSED_PERIOD (مدير فقط) تُفرَض في الراوتر لا هنا.
    `closed_by`/`closed_at` يبقيان كما كانا عند آخر إقفال حقيقي — سجلّ
    تاريخي لا يُمحى بإعادة الفتح؛ من فتح الفترة ومتى يُسجَّل في
    `audit_log` بدل عمودين إضافيين على `Period` لحالة عابرة."""
    period = db.get(Period, (year, month))
    if period is None or not period.is_closed:
        raise PeriodNotClosedError(f"الفترة {year}-{month:02d} ليست مُقفلة أصلاً")
    period.is_closed = False
    db.flush()
    return period
