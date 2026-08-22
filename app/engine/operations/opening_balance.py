"""OPENING — رصيد افتتاحي. §٤ رقم ١١ · §٢-١٠ / §٣-٧.

الطرف المقابل يُشتق تلقائياً من درجة الثقة (`app.engine.opening`) — لا
يُختار يدوياً أبداً. تاريخ الفترة التأسيسية حرّ (§٥ قاعدة ٤) — `as_of_date`
يُستخدم مباشرة كـ`entry_date` بلا تحويل منطقة عمل.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, opening, posting
from app.models import OpeningBalance
from app.models.enums import ConfidenceLevel, OperationType, OpeningSourceType


def execute(
    db: Session,
    *,
    account_code: str,
    currency_code: str,
    amount: Decimal,
    is_debit: bool,
    as_of_date: date,
    source_type: OpeningSourceType,
    confidence: ConfidenceLevel,
    approved_by: int,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    source_note: Optional[str] = None,
):
    def _create():
        account = accounts_repo.get_account_by_code(db, account_code)
        contra_account = opening.derive_contra_account(db, confidence=confidence, currency_code=currency_code)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.OPENING,
            entry_date=as_of_date,
            created_by=created_by,
            description=source_note or f"رصيد افتتاحي — {source_type.value}",
        )
        if is_debit:
            draft.add(account_id=account.id, currency_code=currency_code, debit=amount)
            draft.add(account_id=contra_account.id, currency_code=currency_code, credit=amount)
        else:
            draft.add(account_id=account.id, currency_code=currency_code, credit=amount)
            draft.add(account_id=contra_account.id, currency_code=currency_code, debit=amount)

        entry = posting.post_entry(db, draft, posted_by=created_by, now=now)

        db.add(
            OpeningBalance(
                account_id=account.id,
                amount=amount,
                currency_code=currency_code,
                as_of_date=as_of_date,
                source_type=source_type,
                source_note=source_note,
                confidence=confidence,
                contra_account_id=contra_account.id,
                approved_by=approved_by,
            )
        )
        db.flush()
        return entry

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "OPENING",
            "account_code": account_code,
            "currency_code": currency_code,
            "amount": amount,
            "is_debit": is_debit,
            "confidence": confidence.value,
        },
        create_fn=_create,
    )
