"""تحديد معدل على مسارات الدخول فقط — §٩ المرحلة ١٢.

طبقة ثانية فوق قفل الحساب (`lockout.py`/`portal_lockout.py`): القفل يحمي
حساباً بعينه من تخمين كلمته، وتحديد المعدل يحمي من **رشّ** أسماء مستخدمين
كثيرة من مصدر واحد (كل اسم يبقى تحت حدّ القفل الفردي فلا يُقفَل أيّ منها).

يُطبَّق على `POST /auth/login` و`POST /portal/login` **فقط** — لا يمسّ أي
طلب قراءة. حدّان منفصلان: الموظف من عنوان ثابت غالباً (حدّ أضيق)، العميل
من هاتف بشبكة متغيّرة (حدّ أوسع — حدّ صارم يزعجه بلا فائدة أمنية تُذكر).

**عدّاد في الذاكرة داخل العملية** (لا Redis): يكفي لنشر بعامل uvicorn
واحد خلف nginx (النشر المخطَّط، المرحلة ١٥). نشر متعدد العمّال يحتاج مخزناً
مشتركاً — موثَّق كقيد، لا مشكلة قائمة. `now` يُحقن (نفس قاعدة المحرك)،
فالاختبار يتحكم بالزمن بلا انتظار فعلي.
"""

from __future__ import annotations

import threading
import math
from collections import defaultdict

from app.security.login_messages import format_wait_ar


class RateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"طلبات كثيرة — حاول بعد {format_wait_ar(retry_after_seconds)}")


class RateLimiter:
    """نافذة منزلقة بسيطة: يحتفظ بطوابع زمنية للمحاولات داخل النافذة فقط."""

    def __init__(self, *, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def hit(self, key: str, *, now: float) -> None:
        """يسجّل محاولة ويرفع `RateLimitedError` إن بلغ المفتاح الحدّ.

        المحاولة المرفوضة **لا تُسجَّل**: وإلا مدّد الضغطُ المتكرر أثناء الإيقاف مدّتَه، ولم يعد العدّ التنازلي
        المعروض للمستخدم صحيحاً (ينتهي عند خروج أقدم محاولة مسجَّلة من النافذة)."""
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [t for t in self._hits[key] if t > cutoff]
            if len(recent) >= self.max_hits:
                self._hits[key] = recent
                raise RateLimitedError(retry_after_seconds=max(1, math.ceil(recent[0] + self.window_seconds - now)))
            recent.append(now)
            self._hits[key] = recent

    def remaining(self, key: str, *, now: float) -> int:
        """المحاولات المتبقية للمفتاح داخل النافذة الحالية (بعد احتساب آخر `hit`)."""
        cutoff = now - self.window_seconds
        with self._lock:
            used = sum(1 for t in self._hits.get(key, ()) if t > cutoff)
        return max(0, self.max_hits - used)

    def reset(self) -> None:
        """يُستدعى بين الاختبارات (تجهيزة conftest) — الحالة على مستوى الوحدة."""
        with self._lock:
            self._hits.clear()
