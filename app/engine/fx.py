"""§١-٤ — قاعدة اتجاه الحساب و§٢-٩ — الدولار نقطة تحول إجبارية.

السعر دائماً «كم وحدة من العملة الثانوية مقابل دولار واحد». الأسعار **لا
تُقرَّب إطلاقاً** (§٢-٥) — هذه الدالة لا تُقرّب شيئاً، التقريب مسؤولية
المستدعي عبر `rounding.round_amount` بعد التحويل.
"""

from __future__ import annotations

from decimal import Decimal


class InvalidCurrencyPairError(Exception):
    """§٢-٩: `LYD ⇄ CNY` مرفوض في محرك القيود — يُفحص هنا لا في الواجهة وحدها."""


_REJECTION_MESSAGE = (
    "لا يمكن التحويل مباشرة بين الدينار والرمبي — يجب المرور بالدولار بسعرين منفصلين."
)


SAME_CURRENCY_MESSAGE = "الصرف بين عملتين مختلفتين فقط. لنقل المبلغ بين حساباتك استخدم التحويل"

# أقصى نسبة مسموحة يبتلعها التقريب من المبلغ الناتج (٥٪). سعر ينتج 0.01595 USD يُقرَّب إلى 0.01 (فقد ٣٧٪) ⇒ مرفوض؛
# 0.1428 يُقرَّب إلى 0.14 (فقد ١٫٩٪) ⇒ مقبول. المبلغ الصفري مرفوض دوماً.
MAX_ROUNDING_LOSS = Decimal("0.05")


class ImplausibleRateError(Exception):
    """السعر يُنتج مبلغاً يُقرَّب إلى صفر أو شبه صفر — غالباً سعر مقلوب أو خطأ أصفار."""


def assert_plausible_amount(raw: Decimal, rounded: Decimal, currency_code: str) -> None:
    if raw <= 0 or rounded <= 0 or abs(raw - rounded) / raw > MAX_ROUNDING_LOSS:
        raise ImplausibleRateError(
            f"السعر المُدخَل ينتج مبلغاً يقارب الصفر ({raw.normalize():f} {currency_code} يُقرَّب إلى {rounded}) — راجع السعر والاتجاه (قد يكون مقلوباً)"
        )


def assert_pivot_pair(from_currency: str, to_currency: str, pivot_code: str) -> None:
    if from_currency == to_currency:
        raise InvalidCurrencyPairError(SAME_CURRENCY_MESSAGE)
    if pivot_code not in (from_currency, to_currency):
        raise InvalidCurrencyPairError(_REJECTION_MESSAGE)


def convert(amount: Decimal, rate: Decimal, *, from_currency: str, to_currency: str, pivot_code: str) -> Decimal:
    """§١-٤: دولار → ثانوية = ضرب · ثانوية → دولار = قسمة."""
    assert_pivot_pair(from_currency, to_currency, pivot_code)
    if from_currency == pivot_code:
        return amount * rate
    return amount / rate
