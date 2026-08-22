"""ربح/خسارة العملية — دائماً `4120.x` (ربح، دائن) أو `5120.x` (خسارة، مدين).

كل وحدة عملية تحسب `diff` بالإشارة المناسبة لاتجاه قيدها هي (المدين/الدائن
ينعكسان بين حالة "تحصيل من عميل" وحالة "تسليم لعميل") ثم تستدعي هذه الدالة.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo
from app.models import Account


class NegativeMarginReasonRequiredError(Exception):
    """§٥ قاعدة ٧: هامش سالب يتطلب تأكيداً إجبارياً بسبب مكتوب قبل الترحيل."""


def account_and_side(
    db: Session, *, diff: Decimal, currency_code: str
) -> tuple[Optional[Account], Optional[dict]]:
    """diff > 0 ربح (دائن 4120.x) · diff < 0 خسارة (مدين 5120.x) · diff == 0 لا سطر."""
    if diff > 0:
        return accounts_repo.get_currency_subaccount(db, "4120", currency_code), {"credit": diff}
    if diff < 0:
        return accounts_repo.get_currency_subaccount(db, "5120", currency_code), {"debit": -diff}
    return None, None
