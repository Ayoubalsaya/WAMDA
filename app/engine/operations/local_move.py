"""LOCAL_MOVE — نقل نفس العملة بين أي حسابين للشركة بلا ربح. §٤ رقم ٥.

لا يمسّ أي حساب عميل. تكلفته إن وُجدت (رسوم تحويل بنكي داخلي مثلاً) تُقيَّد
في `5200` (فرعي العملة) بطرف مقابل الحساب المصدر.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.models.enums import OperationType


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
    fee_amount: Decimal = Decimal("0"),
    description: Optional[str] = None,
    allow_negative: bool = False,
    override_reason: Optional[str] = None,
):
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

        if fee_amount > 0:
            fee_account = accounts_repo.get_currency_subaccount(db, "5200", currency_code)
            draft.add(account_id=fee_account.id, currency_code=currency_code, debit=fee_amount)
            draft.add(account_id=from_account.id, currency_code=currency_code, credit=fee_amount)

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
            "fee_amount": fee_amount,
        },
        create_fn=_create,
    )
