"""SWIFT_IN — وصول لبنك الصين · إقفال `1501` · رسوم. §٤ رقم ٧.

بلا `bank_conversion_rate`: إيداع دولار مباشر في `1410.x`.
بوجود `bank_conversion_rate`: تحويل داخلي عبر المقاصة (`1900.x`) — بلا
سعر عميل وبلا ربح عند هذه اللحظة (سعر واحد فقط) — ويفتح دفعة رمبي فوراً
(§٢-٨). الربح يتحقق لاحقاً مع كل بيع من الدفعة، لا هنا.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import accounts_repo, clearing, clock, lots_fifo, posting
from app.engine.rounding import RoundingKind, round_amount
from app.models import CurrencyLot, JournalEntry, SwiftMovement
from app.models.enums import LotStatus, OperationType, SwiftStatus


class SwiftInAlreadyConsumedError(Exception):
    """الدفعة المفتوحة بهذا السويفت استُهلك منها جزء — لا يمكن عكس القيد."""


def execute(
    db: Session,
    *,
    swift_movement_id: int,
    total_amount: Decimal,
    fee_amount: Decimal,
    receiving_account_code: str,
    work_timezone: str,
    created_by: int,
    now: datetime,
    entry_date: Optional[date] = None,
    backdate_reason: Optional[str] = None,
    idempotency_key: str,
    bank_conversion_rate: Optional[Decimal] = None,
    description: Optional[str] = None,
):
    _today = clock.local_entry_date(now, work_timezone)

    entry_date = entry_date or _today

    def _create():
        pivot = accounts_repo.get_pivot_currency(db)
        movement = db.get(SwiftMovement, swift_movement_id)
        in_transit = accounts_repo.get_account_by_code(db, "1501")
        fee_account = accounts_repo.get_currency_subaccount(db, "5300", pivot.code)
        net_received = total_amount - fee_amount

        draft = posting.create_draft_entry(
            db,
            operation_type=OperationType.SWIFT_IN,
            entry_date=entry_date,
            is_backdated=entry_date != _today,
            backdate_reason=backdate_reason,
            created_by=created_by,
            from_currency=pivot.code,
            to_currency="CNY" if bank_conversion_rate is not None else None,
            cost_rate=bank_conversion_rate,
            description=description or "سويفت وصول",
        )
        draft.add(account_id=in_transit.id, currency_code=pivot.code, credit=total_amount)
        draft.add(account_id=fee_account.id, currency_code=pivot.code, debit=fee_amount)

        cny_qty = None
        receiving_account = accounts_repo.get_account_by_code(db, receiving_account_code)
        if bank_conversion_rate is None:
            draft.add(account_id=receiving_account.id, currency_code=pivot.code, debit=net_received)
        else:
            clearing_usd = clearing.clearing_account(db, pivot.code)
            clearing_cny = clearing.clearing_account(db, "CNY")
            cny = accounts_repo.get_currency(db, "CNY")
            cny_qty = round_amount(net_received * bank_conversion_rate, cny.decimals, RoundingKind.INTERNAL)
            draft.add(account_id=clearing_usd.id, currency_code=pivot.code, debit=net_received)
            draft.add(account_id=receiving_account.id, currency_code="CNY", debit=cny_qty)
            draft.add(account_id=clearing_cny.id, currency_code="CNY", credit=cny_qty)

        entry = posting.post_entry(db, draft, posted_by=created_by, now=now)

        movement.in_entry_id = entry.id
        movement.received_confirmed = True
        movement.received_date = entry_date
        movement.status = SwiftStatus.RECEIVED
        movement.exchange_rate = bank_conversion_rate
        db.flush()

        if bank_conversion_rate is not None:
            lots_fifo.open_lot(
                db,
                source_entry_id=entry.id,
                currency_code="CNY",
                account_id=receiving_account.id,
                original_qty=cny_qty,
                cost_rate=bank_conversion_rate,
                cost_currency=pivot.code,
                cost_decimals=pivot.decimals,
                now=now,
            )
        return entry

    return posting.execute_idempotent(
        db,
        idempotency_key=idempotency_key,
        request_payload={
            "op": "SWIFT_IN",
            "swift_movement_id": swift_movement_id,
            "total_amount": total_amount,
            "fee_amount": fee_amount,
            "bank_conversion_rate": bank_conversion_rate,
        },
        create_fn=_create,
    )


def reverse(db: Session, *, entry: JournalEntry, reason: str, created_by: int, now: datetime) -> JournalEntry:
    """اختبار القبول ١٩: عكس قيد SWIFT_IN يُعيد swift_movements.status إلى SENT
    في نفس المعاملة — يُرفض إن استُهلك جزء من الدفعة التي فتحها بالفعل.
    """
    lot = db.execute(select(CurrencyLot).where(CurrencyLot.source_entry_id == entry.id)).scalar_one_or_none()
    if lot is not None and lot.remaining_qty != lot.original_qty:
        raise SwiftInAlreadyConsumedError(
            f"الدفعة {lot.lot_no} استُهلك منها جزء — لا يمكن عكس قيد SWIFT_IN الذي فتحها"
        )

    reversal = posting.reverse_entry(db, entry, reason=reason, created_by=created_by, now=now)

    movement = db.execute(select(SwiftMovement).where(SwiftMovement.in_entry_id == entry.id)).scalar_one()
    movement.status = SwiftStatus.SENT
    movement.received_confirmed = False
    movement.received_date = None
    movement.exchange_rate = None
    movement.in_entry_id = None

    if lot is not None:
        # §٢-٨ قاعدة ٣: لا تُحذف دفعة أبداً — تُقفل بدل ذلك، وremaining_qty
        # تبقى كما هي (كاملة، لم يُستهلك منها شيء) فتُقرأ لاحقاً كأثر صادق
        # لدفعة فُتحت ثم أُلغيت بعكس القيد الذي أنشأها قبل أي بيع منها.
        lot.status = LotStatus.CLOSED
        lot.closed_at = now

    db.flush()
    return reversal
