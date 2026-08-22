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


def assert_pivot_pair(from_currency: str, to_currency: str, pivot_code: str) -> None:
    if from_currency == to_currency:
        raise InvalidCurrencyPairError("العملتان متطابقتان — لا تحويل")
    if pivot_code not in (from_currency, to_currency):
        raise InvalidCurrencyPairError(_REJECTION_MESSAGE)


def convert(amount: Decimal, rate: Decimal, *, from_currency: str, to_currency: str, pivot_code: str) -> Decimal:
    """§١-٤: دولار → ثانوية = ضرب · ثانوية → دولار = قسمة."""
    assert_pivot_pair(from_currency, to_currency, pivot_code)
    if from_currency == pivot_code:
        return amount * rate
    return amount / rate
