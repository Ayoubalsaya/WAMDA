"""حقن الوقت — القاعدة اللانقضية: لا استدعاء مباشر لـ datetime.now داخل المنطق.

كل دوال المحرك تستقبل `now: datetime` (UTC، واعية بالمنطقة) كوسيط صريح من
المستدعي. `system_clock()` هي نقطة الاستدعاء الوحيدة المسموحة لـ
datetime.now — تُستخدم فقط في السكربتات/الطبقة الطرفية لاحقاً، لا هنا.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def system_clock() -> datetime:
    """نقطة الاستدعاء الوحيدة لـ datetime.now في كامل المشروع."""
    return datetime.now(timezone.utc)


def local_entry_date(now: datetime, work_timezone: str) -> date:
    """§5 قاعدة ١٠: entry_date بمنطقة العمل لا UTC — التخزين UTC والعرض محلي."""
    if now.tzinfo is None:
        raise ValueError("now يجب أن يكون واعياً بالمنطقة الزمنية (UTC)")
    return now.astimezone(ZoneInfo(work_timezone)).date()
