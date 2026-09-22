"""EXCHANGE — تحويل بين عملتين بسعرين. §٤ رقم ٣ · الدولار إلزامي في أحد الطرفين.

نمطان بشكل قيد مختلف تماماً (كلاهما في §٢-٣ / §٢-٨ من الوثيقة):

  · `execute_via_rates`  — الحالة العامة (مثال §٢-٣: LYD⇄USD): سعرا التكلفة
    والعميل كلاهما يُطبَّقان على **نفس المبلغ الخام** (عملة "من")، فينتج
    رقمان مختلفان **بعملة "إلى"** — الفرق بينهما هو الربح/الخسارة، ويُقيَّد
    على ضلع "إلى". ضلع "من" مرور نظيف بلا فارق (نفس المبلغ مديناً ودائناً).

  · `execute_via_lot`  — رمبي من مخزون السويفت (مثال §٢-٨-ج، USD→CNY فقط):
    كمية الرمبي المُسلَّمة = تحويل العميل للمبلغ الخام (نظيفة، بلا فارق).
    التكلفة **لا تُدخَل يدوياً** — تُشتق من استهلاك FIFO لتلك الكمية بالذات
    من الدفعات المفتوحة، فيظهر الفارق على ضلع الدولار (عملة "من") بدلاً
    من "إلى"، لأن الدفعة تجمّد سعر تكلفتها لحظة الفتح لا لحظة البيع.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.engine import accounts_repo, clearing, clock, fx, lots_fifo, posting, profit
from app.engine.rounding import RoundingKind, round_amount
from app.models import Client, JournalEntry
from app.engine.profit import NegativeMarginReasonRequiredError
from app.models.enums import OperationType

__all__ = ["NegativeMarginReasonRequiredError", "execute_via_rates", "execute_via_lot"]


def execute_via_rates(
    db: Session,
    *,
    client: Client,
    from_currency: str,
    from_location_code: str,
    to_currency: str,
    to_location_code: str,
    amount: Decimal,
    cost_rate: Decimal,
    client_rate: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
    backdate_reason: Optional[str] = None,
    idempotency_key: str,
    description: Optional[str] = None,
    negative_margin_reason: Optional[str] = None,
    chain_ref: Optional[str] = None,
    chain_seq: Optional[int] = None,
    chain_total: Optional[int] = None,
) -> JournalEntry:
    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        fx.assert_pivot_pair(from_currency, to_currency, pivot.code)
        to_ccy_row = accounts_repo.get_currency(db, to_currency)

        to_amount_client = round_amount(
            fx.convert(amount, client_rate, from_currency=from_currency, to_currency=to_currency, pivot_code=pivot.code),
            to_ccy_row.decimals,
            RoundingKind.GIVEN_TO_CLIENT,
        )
        to_amount_cost = round_amount(
            fx.convert(amount, cost_rate, from_currency=from_currency, to_currency=to_currency, pivot_code=pivot.code),
            to_ccy_row.decimals,
            RoundingKind.INTERNAL,
        )
        diff = to_amount_cost - to_amount_client
        if diff < 0 and not negative_margin_reason:
            raise NegativeMarginReasonRequiredError("هامش سالب — سبب مكتوب إلزامي قبل الترحيل")

        client_from = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=from_currency, location_code=from_location_code
        )
        client_to = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=to_currency, location_code=to_location_code
        )
        clearing_from = clearing.clearing_account(db, from_currency)
        clearing_to = clearing.clearing_account(db, to_currency)

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.EXCHANGE,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            client_id=client.id,
            from_currency=from_currency,
            to_currency=to_currency,
            cost_rate=cost_rate,
            client_rate=client_rate,
            description=description or f"صرافة {from_currency} → {to_currency}",
            negative_margin_reason=negative_margin_reason,
            chain_ref=chain_ref,
            chain_seq=chain_seq,
            chain_total=chain_total,
        )
        draft.add(account_id=client_from.id, currency_code=from_currency, debit=amount)
        draft.add(account_id=clearing_from.id, currency_code=from_currency, credit=amount)
        draft.add(account_id=clearing_to.id, currency_code=to_currency, debit=to_amount_cost)
        draft.add(account_id=client_to.id, currency_code=to_currency, credit=to_amount_client)

        pl_account, pl_amounts = profit.account_and_side(db, diff=diff, currency_code=to_currency)
        if pl_account is not None:
            draft.add(account_id=pl_account.id, currency_code=to_currency, **pl_amounts)

        draft.entry.profit_amount = diff
        draft.entry.profit_currency = to_currency
        return posting.post_entry(db, draft, posted_by=created_by, now=now)

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "EXCHANGE_VIA_RATES",
            "client_id": client.id,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "amount": amount,
            "cost_rate": cost_rate,
            "client_rate": client_rate,
        },
        create_fn=_create,
    )


def execute_via_lot(
    db: Session,
    *,
    client: Client,
    from_location_code: str,
    to_location_code: str,
    amount: Decimal,  # بعملة الدولار (from_currency) — ما يدفعه العميل فعلياً
    client_rate: Decimal,
    work_timezone: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
    backdate_reason: Optional[str] = None,
    idempotency_key: str,
    description: Optional[str] = None,
) -> JournalEntry:
    """§٢-٨-ج: بيع رمبي من مخزون السويفت — FIFO تلقائي، بلا cost_rate يدوي."""
    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        cny = accounts_repo.get_currency(db, "CNY")
        to_amount_client = round_amount(amount * client_rate, cny.decimals, RoundingKind.GIVEN_TO_CLIENT)

        consumption = lots_fifo.consume(
            db, currency_code="CNY", qty_needed=to_amount_client, cost_decimals=pivot.decimals
        )
        cost_amt = consumption.total_cost
        diff = amount - cost_amt  # موجب = ربح بالدولار

        client_from = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code=pivot.code, location_code=from_location_code
        )
        client_to = accounts_repo.get_or_create_client_account(
            db, client=client, currency_code="CNY", location_code=to_location_code
        )
        clearing_from = clearing.clearing_account(db, pivot.code)
        clearing_to = clearing.clearing_account(db, "CNY")

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.EXCHANGE,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            client_id=client.id,
            from_currency=pivot.code,
            to_currency="CNY",
            cost_rate=None,  # مشتق من الدفعة لا يُدخَل يدوياً
            client_rate=client_rate,
            description=description or "صرافة رمبي من مخزون السويفت",
        )
        draft.add(account_id=client_from.id, currency_code=pivot.code, debit=amount)
        draft.add(account_id=clearing_from.id, currency_code=pivot.code, credit=cost_amt)

        pl_account, pl_amounts = profit.account_and_side(db, diff=diff, currency_code=pivot.code)
        if pl_account is not None:
            draft.add(account_id=pl_account.id, currency_code=pivot.code, **pl_amounts)

        draft.add(account_id=clearing_to.id, currency_code="CNY", debit=to_amount_client)
        draft.add(account_id=client_to.id, currency_code="CNY", credit=to_amount_client)

        draft.entry.profit_amount = diff
        draft.entry.profit_currency = pivot.code
        entry = posting.post_entry(db, draft, posted_by=created_by, now=now)

        lots_fifo.apply_consumption(
            db, result=consumption, entry_id=entry.id, client_rate=client_rate, cost_decimals=pivot.decimals, now=now
        )
        return entry

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "EXCHANGE_VIA_LOT",
            "client_id": client.id,
            "amount": amount,
            "client_rate": client_rate,
        },
        create_fn=_create,
    )
