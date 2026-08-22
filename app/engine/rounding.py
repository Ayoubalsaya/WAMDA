"""§٢-٥ — سياسة التقريب: مصفوفة قاطعة، دالة مركزية واحدة، لا تقريب خارجها.

الشاشة والقيد والإيصال والتقرير يجب أن يستدعوا هذه الدالة بنفس الوسائط
لإنتاج نفس الرقم دائماً (اختبار القبول ٢٣). الأسعار **لا تُقرَّب إطلاقاً**.
"""

from __future__ import annotations

import enum
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal


class RoundingKind(str, enum.Enum):
    GIVEN_TO_CLIENT = "GIVEN_TO_CLIENT"              # ROUND_DOWN — مبلغ يُعطى للعميل
    COLLECTED_FROM_CLIENT = "COLLECTED_FROM_CLIENT"  # ROUND_UP   — مبلغ يُحصَّل من العميل
    INTERNAL = "INTERNAL"                             # ROUND_HALF_UP — حركة داخلية بين حسابات الشركة


_ROUNDING_MODE: dict[RoundingKind, str] = {
    RoundingKind.GIVEN_TO_CLIENT: ROUND_DOWN,
    RoundingKind.COLLECTED_FROM_CLIENT: ROUND_UP,
    RoundingKind.INTERNAL: ROUND_HALF_UP,
}


def round_amount(amount: Decimal, decimals: int, kind: RoundingKind) -> Decimal:
    """المصفوفة القاطعة §٢-٥ — الدقة `decimals` تأتي من `currencies.decimals`."""
    if not isinstance(amount, Decimal):
        raise TypeError("المبالغ Decimal حصراً — لا float في أي طبقة (§٦-٣)")
    quantum = Decimal(1).scaleb(-decimals)
    return amount.quantize(quantum, rounding=_ROUNDING_MODE[kind])


def rounding_difference(
    exact_amount: Decimal, rounded_amount: Decimal
) -> Decimal:
    """الفرق الناتج عن التقريب — يذهب حصراً إلى `5900` (§٢-٥)."""
    return rounded_amount - exact_amount
