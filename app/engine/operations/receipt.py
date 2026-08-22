"""RECEIPT — استلام من عميل. §٤ رقم ١ · لا سعر صرف (§٢-٦)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.models import Client
from app.models.enums import OperationType


def execute(
    db: Session,
    *,
    client: Client,
    currency_code: str,
    location_code: str,
    amount: Decimal,
    receiving_account_code: str,
    work_timezone: str,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    payment_method: Optional[str] = None,
    description: Optional[str] = None,
):
    entry_date = clock.local_entry_date(now, work_timezone)

    def _create():
        client_account = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=currency_code, location_code=location_code
        )
        receiving_account = accounts_repo.get_account_by_code(db, receiving_account_code)
        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.RECEIPT,
            entry_date=entry_date,
            created_by=created_by,
            client_id=client.id,
            description=description or (f"استلام — {payment_method}" if payment_method else "استلام"),
        )
        draft.add(account_id=receiving_account.id, currency_code=currency_code, debit=amount, memo=payment_method)
        draft.add(account_id=client_account.id, currency_code=currency_code, credit=amount)
        return posting.post_entry(db, draft, posted_by=created_by, now=now)

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "RECEIPT",
            "client_id": client.id,
            "currency_code": currency_code,
            "location_code": location_code,
            "amount": amount,
            "receiving_account_code": receiving_account_code,
        },
        create_fn=_create,
    )
