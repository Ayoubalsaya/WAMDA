"""CASH_TRANSFER — نقل نفس العملة بين موقعين بعمولة فرق. §٤ رقم ٤ · مثال §١-٣-أ.

أربعة أسطر تُشكِّل زوجين متوازنين مستقلين (كل عملة تتوازن داخل نفسها،
§٢-٣ قاعدة ١): زوج حركة العملة المنقولة (بلا ربح فيه بذاته)، وزوج عمولة
الفرق (قد تكون بعملة مختلفة تماماً عن العملة المنقولة — كما في المثال،
تحويل دولار بعمولة تُحصَّل وتُكلَّف بالدينار). الربح = الفرق بينهما.
"""

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
    from_location_code: str,
    to_location_code: str,
    amount: Decimal,
    source_account_code: str,
    execution_account_code: str,
    collection_account_code: str,
    commission_currency: str,
    client_commission_amount: Decimal,
    cost_commission_amount: Decimal,
    cost_correspondent_account_code: str,
    work_timezone: str,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    description: Optional[str] = None,
):
    entry_date = clock.local_entry_date(now, work_timezone)

    def _create():
        client_from = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=currency_code, location_code=from_location_code
        )
        client_to = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=currency_code, location_code=to_location_code
        )
        source_account = accounts_repo.get_account_by_code(db, source_account_code)
        execution_account = accounts_repo.get_account_by_code(db, execution_account_code)
        collection_account = accounts_repo.get_account_by_code(db, collection_account_code)
        cost_correspondent = accounts_repo.get_account_by_code(db, cost_correspondent_account_code)
        revenue_account = accounts_repo.get_currency_subaccount(db, "4110", commission_currency)
        cost_account = accounts_repo.get_currency_subaccount(db, "5410", commission_currency)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.CASH_TRANSFER,
            entry_date=entry_date,
            created_by=created_by,
            client_id=client.id,
            description=description or f"تحويل بعمولة {currency_code} {from_location_code}→{to_location_code}",
        )
        # ١) التزام العميل ينتقل موقعياً — بلا ربح في هذا الزوج
        draft.add(account_id=client_from.id, currency_code=currency_code, debit=amount)
        draft.add(account_id=client_to.id, currency_code=currency_code, credit=amount)
        # ٢) الانتقال الأصلي الحقيقي لأموال الشركة
        draft.add(account_id=source_account.id, currency_code=currency_code, credit=amount)
        draft.add(account_id=execution_account.id, currency_code=currency_code, debit=amount)
        # ٣) تحصيل عمولة العميل (قد تكون بعملة مختلفة عن المنقولة)
        draft.add(account_id=collection_account.id, currency_code=commission_currency, debit=client_commission_amount)
        draft.add(account_id=revenue_account.id, currency_code=commission_currency, credit=client_commission_amount)
        # ٤) تكلفة العمولة الفعلية
        draft.add(account_id=cost_account.id, currency_code=commission_currency, debit=cost_commission_amount)
        draft.add(
            account_id=cost_correspondent.id, currency_code=commission_currency, credit=cost_commission_amount
        )

        draft.entry.profit_amount = client_commission_amount - cost_commission_amount
        draft.entry.profit_currency = commission_currency
        return posting.post_entry(db, draft, posted_by=created_by, now=now)

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "CASH_TRANSFER",
            "client_id": client.id,
            "currency_code": currency_code,
            "from_location_code": from_location_code,
            "to_location_code": to_location_code,
            "amount": amount,
            "client_commission_amount": client_commission_amount,
            "cost_commission_amount": cost_commission_amount,
        },
        create_fn=_create,
    )
