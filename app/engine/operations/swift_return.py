"""SWIFT_RETURN — مرتجع: يُقفل `1501` · يُعيد المبلغ لموقعه · الرسوم على
العميل · يربط بالقيد الأصلي. §٤ رقم ٨.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.models import Client, SwiftMovement
from app.models.enums import OperationType, SwiftStatus


def execute(
    db: Session,
    *,
    swift_movement_id: int,
    partner_account_code: str,
    total_amount: Decimal,
    client: Client,
    client_location_code: str,
    return_fee_amount: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    description: Optional[str] = None,
):
    entry_date = clock.local_entry_date(now, work_timezone)

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        movement = db.get(SwiftMovement, swift_movement_id)
        in_transit = accounts_repo.get_account_by_code(db, "1501")
        partner_account = accounts_repo.get_account_by_code(db, partner_account_code)
        client_account = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=pivot.code, location_code=client_location_code
        )
        amount_returned = total_amount - return_fee_amount

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.SWIFT_RETURN,
            entry_date=entry_date,
            created_by=created_by,
            client_id=client.id,
            from_currency=pivot.code,
            description=description or "سويفت مرتجع",
        )
        draft.add(account_id=in_transit.id, currency_code=pivot.code, credit=total_amount)
        draft.add(account_id=partner_account.id, currency_code=pivot.code, debit=amount_returned)
        if return_fee_amount > 0:
            draft.add(account_id=client_account.id, currency_code=pivot.code, debit=return_fee_amount)
        entry = posting.post_entry(db, draft, posted_by=created_by, now=now)

        movement.return_entry_id = entry.id
        movement.status = SwiftStatus.RETURNED
        db.flush()
        return entry

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "SWIFT_RETURN",
            "swift_movement_id": swift_movement_id,
            "total_amount": total_amount,
            "return_fee_amount": return_fee_amount,
        },
        create_fn=_create,
    )
