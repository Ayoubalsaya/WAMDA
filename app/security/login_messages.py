"""صياغة عربية لرسائل الدخول: المحاولات المتبقية قبل الإيقاف المؤقت، ومدة الانتظار بالدقائق والثواني.

نصوص فقط بلا أي حالة — يستخدمها الموجّه وحدّ المعدل. الأرقام غربية (3، 14) كبقية رسائل الواجهة.
"""

from __future__ import annotations


def _plural_ar(n: int, *, one: str, two: str, few: str, many: str) -> str:
    """الصيغة العربية للعدد: ١ مفرد · ٢ مثنّى · ٣–١٠ جمع قلّة · ١١+ تمييز مفرد."""
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n <= 10:
        return few.format(n=n)
    return many.format(n=n)


def format_wait_ar(total_seconds: int) -> str:
    """«14 دقيقة و5 ثوانٍ» — لا رقم ثوانٍ خام (787)."""
    total = max(1, int(total_seconds))
    minutes, seconds = divmod(total, 60)
    parts: list[str] = []
    if minutes:
        parts.append(_plural_ar(
            minutes, one="دقيقة واحدة", two="دقيقتان", few="{n} دقائق", many="{n} دقيقة"
        ))
    if seconds:
        parts.append(_plural_ar(
            seconds, one="ثانية واحدة", two="ثانيتان", few="{n} ثوانٍ", many="{n} ثانية"
        ))
    return " و".join(parts)


def format_attempts_left_ar(left: int) -> str:
    """«بقيت 3 محاولات قبل الإيقاف المؤقت»."""
    left = max(0, int(left))
    if left == 0:
        return "لا محاولات متبقية قبل الإيقاف المؤقت"
    if left == 1:
        return "بقيت محاولة واحدة قبل الإيقاف المؤقت"
    if left == 2:
        return "بقيت محاولتان قبل الإيقاف المؤقت"
    return _plural_ar(
        left, one="", two="", few="بقيت {n} محاولات قبل الإيقاف المؤقت", many="بقيت {n} محاولة قبل الإيقاف المؤقت"
    )
