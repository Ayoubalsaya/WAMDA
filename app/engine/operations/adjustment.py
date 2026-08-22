"""ADJUSTMENT — تسوية، مدير فقط بسبب إلزامي. §٤ رقم ١٢.

فرق الجرد (زيادة/عجز الصندوق) يُسجَّل عبرها حصراً (تعديل معتمد) — الطرف
المقابل يُشتق تلقائياً: `4900.x` زيادة أو `5910.x` عجز، حسب `is_debit`.
فحص الدور (مدير فقط) مؤجَّل للمرحلة ٤ — هنا فقط يُفرض السبب إلزامياً.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.engine.posting import OverrideReasonRequiredError
from app.models.enums import OperationType


def execute(
    db: Session,
    *,
    account_code: str,
    currency_code: str,
    amount: Decimal,
    is_debit: bool,  # True = زيادة صندوق (4900.x دائن) · False = عجز (5910.x مدين)
    reason: str,
    work_timezone: str,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    allow_negative: bool = False,
):
    if not reason:
        raise OverrideReasonRequiredError("ADJUSTMENT يتطلب سبباً إلزامياً")
    entry_date = clock.local_entry_date(now, work_timezone)

    def _create():
        account = accounts_repo.get_account_by_code(db, account_code)
        contra_parent = "4900" if is_debit else "5910"
        contra_account = accounts_repo.get_currency_subaccount(db, contra_parent, currency_code)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.ADJUSTMENT,
            entry_date=entry_date,
            created_by=created_by,
            description=reason,
        )
        if is_debit:
            draft.add(account_id=account.id, currency_code=currency_code, debit=amount)
            draft.add(account_id=contra_account.id, currency_code=currency_code, credit=amount)
        else:
            draft.add(account_id=account.id, currency_code=currency_code, credit=amount)
            draft.add(account_id=contra_account.id, currency_code=currency_code, debit=amount)

        return posting.post_entry(
            db, draft, posted_by=created_by, now=now, allow_negative=allow_negative, override_reason=reason
        )

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "ADJUSTMENT",
            "account_code": account_code,
            "currency_code": currency_code,
            "amount": amount,
            "is_debit": is_debit,
            "reason": reason,
        },
        create_fn=_create,
    )
