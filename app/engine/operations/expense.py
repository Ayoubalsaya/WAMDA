"""EXPENSE — مصروف تشغيلي أو رسوم. §٤ رقم ١٠."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.models.enums import OperationType


def execute(
    db: Session,
    *,
    expense_account_code: str,
    currency_code: str,
    paying_account_code: str,
    amount: Decimal,
    description: str,
    work_timezone: str,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    allow_negative: bool = False,
    override_reason: Optional[str] = None,
):
    entry_date = clock.local_entry_date(now, work_timezone)

    def _create():
        expense_account = accounts_repo.get_account_by_code(db, expense_account_code)
        paying_account = accounts_repo.get_account_by_code(db, paying_account_code)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.EXPENSE,
            entry_date=entry_date,
            created_by=created_by,
            description=description,
        )
        draft.add(account_id=expense_account.id, currency_code=currency_code, debit=amount)
        draft.add(account_id=paying_account.id, currency_code=currency_code, credit=amount)
        return posting.post_entry(
            db, draft, posted_by=created_by, now=now, allow_negative=allow_negative, override_reason=override_reason
        )

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "EXPENSE",
            "expense_account_code": expense_account_code,
            "currency_code": currency_code,
            "paying_account_code": paying_account_code,
            "amount": amount,
        },
        create_fn=_create,
    )
