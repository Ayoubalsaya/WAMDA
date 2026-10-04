"""LOCAL_MOVE — نقل نفس العملة بين أي حسابين للشركة بلا ربح. §٤ رقم ٥.

لا يمسّ أي حساب عميل. العمولة اختيارية (٢٠٢٦-١٠-٠٥، قرار مالك — حلّت محل حقل الرسوم
القديم المقيَّد في 5200): زوج أسطر متوازن بعملتها المستقلة، المنطق نفسه الذي في الصرافة
(`exchange.add_commission`، نطاق الخزينة: حساب شركة دائماً) — ندفعها (الحالة الغالبة):
مدين 5410 ← دائن الحساب المختار؛ نقبضها: مدين الحساب المختار ← دائن 4110.
هذه هي «تحويل بعمولة / خزينة» في الواجهة: لا مسار خادم ثانٍ.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.engine.operations.exchange import InvalidCommissionError, add_commission
from app.models.enums import OperationType

__all__ = ["InvalidCommissionError", "execute"]


def execute(
    db: Session,
    *,
    currency_code: str,
    from_account_code: str,
    to_account_code: str,
    amount: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
    backdate_reason: Optional[str] = None,
    idempotency_key: str,
    description: Optional[str] = None,
    allow_negative: bool = False,
    override_reason: Optional[str] = None,
    commission_direction: Optional[str] = None,
    commission_currency: Optional[str] = None,
    commission_amount: Optional[Decimal] = None,
    commission_account_code: Optional[str] = None,
):
    parts = (commission_direction, commission_currency, commission_amount)
    if any(p is not None for p in parts) and not all(p is not None for p in parts):
        raise InvalidCommissionError("العمولة تتطلب الاتجاه والعملة والمبلغ معاً")

    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        from_account = accounts_repo.get_account_by_code(db, from_account_code)
        to_account = accounts_repo.get_account_by_code(db, to_account_code)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.LOCAL_MOVE,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            description=description or f"نقل داخلي {currency_code}",
        )
        draft.add(account_id=to_account.id, currency_code=currency_code, debit=amount)
        draft.add(account_id=from_account.id, currency_code=currency_code, credit=amount)

        if commission_amount is not None:
            add_commission(
                db, draft, is_treasury=True, client=None, direction=commission_direction,
                currency_code=commission_currency, amount=commission_amount,
                account_code=commission_account_code, location_code=None,
            )

        return posting.post_entry(
            db, draft, posted_by=created_by, now=now,
            allow_negative=allow_negative, override_reason=override_reason,
        )

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "LOCAL_MOVE",
            "currency_code": currency_code,
            "from_account_code": from_account_code,
            "to_account_code": to_account_code,
            "amount": amount,
            "commission": [commission_direction, commission_currency, commission_amount, commission_account_code],
        },
        create_fn=_create,
    )
