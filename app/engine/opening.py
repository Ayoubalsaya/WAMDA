"""§٢-١٠ — اشتقاق الطرف المقابل للرصيد الافتتاحي من درجة الثقة، وإقفال
الفترة التأسيسية.

confidence = HIGH            → الطرف المقابل 3100 رأس المال (فرعي العملة)
confidence = MEDIUM أو LOW    → الطرف المقابل 3900 فروق تأسيسية (فرعي العملة)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.accounts_repo import get_account_by_code, get_currency_subaccount
from app.engine.posting import OverrideReasonRequiredError
from app.models import Account, AccountBalance, FoundingPeriod
from app.models.enums import ConfidenceLevel


def derive_contra_account(db: Session, *, confidence: ConfidenceLevel, currency_code: str) -> Account:
    parent_code = "3100" if confidence == ConfidenceLevel.HIGH else "3900"
    return get_currency_subaccount(db, parent_code, currency_code)


class FoundingPeriodAlreadyClosedError(Exception):
    pass


class SuspenseBalanceAcknowledgmentRequiredError(Exception):
    """§٥ قاعدة ٤ / §٢-١٠: إقفال الفترة التأسيسية ورصيد 3900 غير صفري
    بلا إقرار المدير بالمتبقي → مرفوض."""


def total_suspense_balance(db: Session) -> dict[str, object]:
    """مجموع أرصدة كل حسابات 3900.x الفرعية — لا يفترض عدد عملات ثابتاً."""
    parent = get_account_by_code(db, "3900")
    children = db.execute(select(Account).where(Account.parent_id == parent.id)).scalars().all()
    balances: dict[str, object] = {}
    for child in children:
        row = db.get(AccountBalance, child.id)
        if row is not None and row.balance != 0:
            balances[child.currency_code] = row.balance
    return balances


def close_founding_period(
    db: Session, *, closed_by: int, now: datetime, acknowledged_remaining_suspense: bool = False
) -> FoundingPeriod:
    founding = db.get(FoundingPeriod, 1)
    if founding is None:
        raise ValueError("لا صف founding_period — بيانات التهيئة غير مكتملة")
    if not founding.is_open:
        raise FoundingPeriodAlreadyClosedError("الفترة التأسيسية مُقفلة أصلاً")

    remaining = total_suspense_balance(db)
    if remaining and not acknowledged_remaining_suspense:
        raise SuspenseBalanceAcknowledgmentRequiredError(
            f"رصيد 3900 غير صفري ({remaining}) — يتطلب إقرار المدير قبل الإقفال"
        )

    founding.is_open = False
    founding.closed_at = now
    founding.closed_by = closed_by
    db.flush()
    return founding
