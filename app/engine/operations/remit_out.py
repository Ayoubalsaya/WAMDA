"""REMIT_OUT — إرسال لمستفيد نهائي عبر شركة مراسلة. §٤ رقم ٩ · مثال §١-٣-ب.

ربط إلزامي بمستفيد مسجَّل + لقطة الوجهة لحظة الترحيل (§٣-٣) — لا رمبي يُقيَّد
في دفاترنا هنا؛ الشركة المراسلة تصرف وترسل من عندها، فالعملية بأكملها تبقى
بعملة الدولار فقط (لا حاجة لمقاصة 1900، ولا دفعة رمبي — تلك حصراً لمسار
بنك الصين المباشر، §٢-٨).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clock, fx, posting, profit
from app.engine.profit import NegativeMarginReasonRequiredError
from app.engine.rounding import RoundingKind, round_amount
from app.models import Beneficiary, Client, RemitOutDestination
from app.models.enums import OperationType


class BeneficiaryRequiredError(Exception):
    """§٥ / اختبار القبول ٣١: REMIT_OUT بلا مستفيد مسجّل → رفض تام."""


def execute(
    db: Session,
    *,
    client: Client,
    from_location_code: str,
    partner_account_code: str,
    beneficiary: Beneficiary,
    beneficiary_amount: Decimal,  # بعملة المستفيد (beneficiary.currency_code)
    cost_rate: Decimal,
    client_rate: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    idempotency_key: str,
    purpose: Optional[str] = None,
    description: Optional[str] = None,
    negative_margin_reason: Optional[str] = None,
):
    if beneficiary is None:
        raise BeneficiaryRequiredError("REMIT_OUT يتطلب مستفيداً مسجّلاً — لا وجهة غير مسجّلة")
    entry_date = clock.local_entry_date(now, work_timezone)

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        beneficiary_ccy = beneficiary.currency_code

        # المبلغ يُحصَّل من العميل — ROUND_UP (§٢-٥)
        client_amt_usd = round_amount(
            fx.convert(
                beneficiary_amount, client_rate, from_currency=beneficiary_ccy, to_currency=pivot.code, pivot_code=pivot.code
            ),
            pivot.decimals,
            RoundingKind.COLLECTED_FROM_CLIENT,
        )
        cost_amt_usd = round_amount(
            fx.convert(
                beneficiary_amount, cost_rate, from_currency=beneficiary_ccy, to_currency=pivot.code, pivot_code=pivot.code
            ),
            pivot.decimals,
            RoundingKind.INTERNAL,
        )
        diff = client_amt_usd - cost_amt_usd  # موجب = ربح (العميل دفع أكثر من التكلفة)
        if diff < 0 and not negative_margin_reason:
            raise NegativeMarginReasonRequiredError("هامش سالب — سبب مكتوب إلزامي قبل الترحيل")

        client_account = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=pivot.code, location_code=from_location_code
        )
        partner_account = accounts_repo.get_account_by_code(db, partner_account_code)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.REMIT_OUT,
            entry_date=entry_date,
            created_by=created_by,
            client_id=client.id,
            beneficiary_id=beneficiary.id,
            from_currency=pivot.code,
            cost_rate=cost_rate,
            client_rate=client_rate,
            description=description or f"إرسال لمستفيد {beneficiary.name}",
            negative_margin_reason=negative_margin_reason,
        )
        draft.add(account_id=client_account.id, currency_code=pivot.code, debit=client_amt_usd)
        draft.add(account_id=partner_account.id, currency_code=pivot.code, credit=cost_amt_usd)
        pl_account, pl_amounts = profit.account_and_side(db, diff=diff, currency_code=pivot.code)
        if pl_account is not None:
            draft.add(account_id=pl_account.id, currency_code=pivot.code, **pl_amounts)

        draft.entry.profit_amount = diff
        draft.entry.profit_currency = pivot.code
        entry = posting.post_entry(db, draft, posted_by=created_by, now=now)

        db.add(
            RemitOutDestination(
                entry_id=entry.id,
                beneficiary_id=beneficiary.id,
                beneficiary_name_snapshot=beneficiary.name,
                account_number_snapshot=beneficiary.account_number,
                bank_name_snapshot=beneficiary.bank_name,
                currency_code=beneficiary_ccy,
            )
        )
        db.flush()
        return entry

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "REMIT_OUT",
            "client_id": client.id,
            "beneficiary_id": beneficiary.id,
            "beneficiary_amount": beneficiary_amount,
            "cost_rate": cost_rate,
            "client_rate": client_rate,
        },
        create_fn=_create,
    )
