"""REMIT_OUT — إرسال خارجي: نقل مبلغ من رصيد العميل إلى تاجر/مورد خارجي **بالعملة نفسها**. لا ربح للشركة.

قرار مالك ٢٠٢٦-١٠-٠٤: الإرسال ليس صرافة — التحويل بين العملات يتم قبله بعملية EXCHANGE منفصلة. القيد سطران متوازنان فقط
بعملة واحدة: مدين حساب العميل (عملة × موقع) · دائن حساب الشركة المُرسِل (بنك/مراسل/صندوق **بالعملة نفسها**).
لا سعر عميل، لا سعر تكلفة، لا صندوق ربح، ولا دولار وسيطاً (كان القديم: ٣ أسطر بالدولار + ٤١٢٠، انظر PROGRESS).

سجل المستفيدين أُلغي (٢٠٢٦-٠٩-٢٢): اسم التاجر ورقم الحساب يُدوَّنان في الملاحظة.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, posting
from app.models import Client
from app.models.enums import AccountForm, AccountType, OperationType

_SENDING_FORMS = frozenset({AccountForm.CASH, AccountForm.BANK, AccountForm.CORRESPONDENT})


class InvalidSendingAccountError(Exception):
    """حساب الإرسال ليس حساب شركة (بنك/مراسل/صندوق) بعملة العملية نفسها."""


def execute(
    db: Session,
    *,
    client: Client,
    from_location_code: str,
    sending_account_code: str,
    currency_code: str,
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
):
    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        sending_account = accounts_repo.get_account_by_code(db, sending_account_code)
        if sending_account.client_id is not None or sending_account.type != AccountType.ASSET or sending_account.form not in _SENDING_FORMS:
            raise InvalidSendingAccountError(f"الحساب {sending_account_code} ليس حساب شركة (بنك أو مراسل أو صندوق) للإرسال منه")
        if sending_account.currency_code != currency_code:
            raise InvalidSendingAccountError(
                f"حساب الإرسال {sending_account_code} بعملة {sending_account.currency_code} لا {currency_code} — الإرسال بالعملة نفسها فقط"
            )
        client_account = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=currency_code, location_code=from_location_code
        )
        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.REMIT_OUT,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            client_id=client.id,
            description=description or "إرسال خارجي",
        )
        draft.add(account_id=client_account.id, currency_code=currency_code, debit=amount)
        draft.add(account_id=sending_account.id, currency_code=currency_code, credit=amount)
        return posting.post_entry(
            db, draft, posted_by=created_by, now=now,
            allow_negative=allow_negative, override_reason=override_reason,
        )

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "REMIT_OUT",
            "client_id": client.id,
            "currency_code": currency_code,
            "location_code": from_location_code,
            "amount": amount,
            "sending_account_code": sending_account_code,
        },
        create_fn=_create,
    )
