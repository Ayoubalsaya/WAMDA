"""SWIFT_OUT — خروج دولار من تركيا إلى `1501`. §٤ رقم ٦."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.models import SwiftMovement
from app.models.enums import OperationType, SwiftStatus


def execute(
    db: Session,
    *,
    partner_account_code: str,
    amount: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    external_ref: Optional[str] = None,
    description: Optional[str] = None,
):
    entry_date = clock.local_entry_date(now, work_timezone)

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        partner_account = accounts_repo.get_account_by_code(db, partner_account_code)
        in_transit = accounts_repo.get_account_by_code(db, "1501")

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.SWIFT_OUT,
            entry_date=entry_date,
            created_by=created_by,
            partner_id=partner_account.partner_id,
            from_currency=pivot.code,
            description=description or "سويفت خروج",
        )
        draft.add(account_id=in_transit.id, currency_code=pivot.code, debit=amount)
        draft.add(account_id=partner_account.id, currency_code=pivot.code, credit=amount)
        entry = posting.post_entry(db, draft, posted_by=created_by, now=now)

        db.add(
            SwiftMovement(
                out_entry_id=entry.id,
                amount=amount,
                currency_code=pivot.code,
                transfer_date=entry_date,
                status=SwiftStatus.SENT,
                external_ref=external_ref,
            )
        )
        db.flush()
        return entry

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={"op": "SWIFT_OUT", "partner_account_code": partner_account_code, "amount": amount},
        create_fn=_create,
    )
