"""§٢-٨ / §٣-٦ — دفعات الرمبي: فتح، استهلاك FIFO تلقائي، توزيع cost_share حتمي.

الدفعة تُعرض كمعلومة لا كحقل قابل للتعديل — المستهلك لا يختارها، يختارها
النظام (الأقدم `opened_at` أولاً) وحده.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine import numbering
from app.engine.rounding import RoundingKind, round_amount
from app.models import CurrencyLot, JournalEntry, LotConsumption
from app.models.enums import EntryStatus, LotStatus


class LotStockExhaustedError(Exception):
    """§٢-٨ قاعدة ٢: بيع بلا دفعة مفتوحة → يُرفض (المخزون نفد)."""


class LotFrozenError(Exception):
    """§٢-٨ قاعدة ١: cost_rate/original_qty لا يُعدَّلان بعد أول استهلاك."""


def open_lot(
    db: Session,
    *,
    source_entry_id: int,
    currency_code: str,
    account_id: int,
    original_qty: Decimal,
    cost_rate: Decimal,
    cost_currency: str,
    cost_decimals: int,
    now: datetime,
) -> CurrencyLot:
    """يفتح دفعة عند SWIFT_IN محوَّل لرمبي — التكلفة الكلية = original_qty ÷ cost_rate (§١-٤)."""
    if original_qty <= 0:
        raise ValueError("original_qty يجب أن تكون موجبة")
    lot_no = numbering.next_lot_no(db, now.year)
    cost_total = round_amount(original_qty / cost_rate, cost_decimals, RoundingKind.INTERNAL)
    lot = CurrencyLot(
        lot_no=lot_no,
        source_entry_id=source_entry_id,
        currency_code=currency_code,
        account_id=account_id,
        original_qty=original_qty,
        remaining_qty=original_qty,
        cost_rate=cost_rate,
        cost_total=cost_total,
        cost_currency=cost_currency,
        opened_at=now,
        status=LotStatus.OPEN,
    )
    db.add(lot)
    db.flush()
    return lot


def assert_lot_editable(lot: CurrencyLot) -> None:
    """§٢-٨ قاعدة ١ — يُستدعى قبل أي تعديل مستقبلي على cost_rate/original_qty."""
    if lot.remaining_qty != lot.original_qty:
        raise LotFrozenError(f"الدفعة {lot.lot_no} استُهلك منها جزء — cost_rate/original_qty مجمَّدان")


@dataclass
class ConsumptionPart:
    lot: CurrencyLot
    qty: Decimal
    cost_share: Decimal


@dataclass
class ConsumeResult:
    parts: list[ConsumptionPart]
    total_cost: Decimal
    cost_currency: str


def consume(db: Session, *, currency_code: str, qty_needed: Decimal, cost_decimals: int) -> ConsumeResult:
    """§٢-٨ — FIFO تلقائي بقفل صفّي؛ يوزّع cost_share بالخوارزمية الحتمية:

    ١. التكلفة الدقيقة لكل جزء قبل التقريب
    ٢. total_cost_exact من مجموع الأجزاء
    ٣. تقريب التكلفة النهائية (INTERNAL — حركة داخلية بين حسابات الشركة)
    ٤. تقريب الأجزاء بترتيب FIFO مع وضع الـ residual في آخر جزء
       حتى SUM(cost_share) = total_cost بالضبط — لا شيء في 5900 لهذا الفرق.
    """
    if qty_needed <= 0:
        raise ValueError("qty_needed يجب أن تكون موجبة")

    open_lots = db.execute(
        select(CurrencyLot)
        .where(CurrencyLot.currency_code == currency_code, CurrencyLot.status == LotStatus.OPEN)
        .order_by(CurrencyLot.opened_at)
        .with_for_update()
    ).scalars().all()

    remaining = qty_needed
    exact_parts: list[tuple[CurrencyLot, Decimal, Decimal]] = []
    cost_currency: str | None = None
    for lot in open_lots:
        if remaining <= 0:
            break
        take = min(lot.remaining_qty, remaining)
        if take <= 0:
            continue
        if cost_currency is None:
            cost_currency = lot.cost_currency
        elif cost_currency != lot.cost_currency:
            raise ValueError("دفعات مفتوحة بعملات تكلفة مختلفة لنفس currency_code — حالة غير متوقعة")
        exact_cost = take / lot.cost_rate
        exact_parts.append((lot, take, exact_cost))
        remaining -= take

    if remaining > 0:
        raise LotStockExhaustedError(
            f"مخزون {currency_code} غير كافٍ — لا دفعة مفتوحة تغطي المتبقي {remaining}"
        )

    total_cost_exact = sum((c for _, _, c in exact_parts), Decimal("0"))
    total_cost = round_amount(total_cost_exact, cost_decimals, RoundingKind.INTERNAL)

    parts: list[ConsumptionPart] = []
    running = Decimal("0")
    for i, (lot, qty, exact_cost) in enumerate(exact_parts):
        if i == len(exact_parts) - 1:
            share = total_cost - running
        else:
            share = round_amount(exact_cost, cost_decimals, RoundingKind.INTERNAL)
        running += share
        parts.append(ConsumptionPart(lot=lot, qty=qty, cost_share=share))

    return ConsumeResult(parts=parts, total_cost=total_cost, cost_currency=cost_currency)


def apply_consumption(
    db: Session,
    *,
    result: ConsumeResult,
    entry_id: int,
    client_rate: Decimal,
    cost_decimals: int,
    now: datetime,
) -> list[LotConsumption]:
    """يُستدعى بعد ترحيل القيد: ينقص remaining_qty، يُقفل الدفعات الفارغة،
    ويسجّل lot_consumptions (تحليلية فقط — §٢-٨ قاعدة ٤، لا تحرّك مالاً).
    """
    rows: list[LotConsumption] = []
    for part in result.parts:
        lot = part.lot
        lot.remaining_qty = lot.remaining_qty - part.qty
        if lot.remaining_qty == 0:
            lot.status = LotStatus.CLOSED
            lot.closed_at = now
        revenue_share = round_amount(part.qty / client_rate, cost_decimals, RoundingKind.INTERNAL)
        profit = revenue_share - part.cost_share
        row = LotConsumption(
            lot_id=lot.id,
            entry_id=entry_id,
            qty=part.qty,
            client_rate=client_rate,
            cost_share=part.cost_share,
            revenue=revenue_share,
            profit=profit,
            profit_currency=result.cost_currency,
            consumed_at=now,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


# ═══ العكس (٢٠٢٦-١٠-٠٢): إلغاء/تعديل قيد استهلك من دفعة يعيد الكمية ويضيف صفاً عكسياً ═══


def live_consumptions(db: Session, lot_id: int) -> list[LotConsumption]:
    """الاستهلاكات الحيّة: أصلية لم تُعكس (لا صف عكسي يشير إليها)، مرتّبة زمنياً."""
    reversed_ids = select(LotConsumption.reverses_consumption_id).where(
        LotConsumption.lot_id == lot_id, LotConsumption.reverses_consumption_id.isnot(None)
    )
    return list(db.execute(
        select(LotConsumption)
        .where(LotConsumption.lot_id == lot_id, LotConsumption.reverses_consumption_id.is_(None),
               LotConsumption.id.notin_(reversed_ids))
        .order_by(LotConsumption.consumed_at, LotConsumption.id)
    ).scalars())


def net_consumed_qty(db: Session, lot_id: int) -> Decimal:
    """صافي الاستهلاك = Σ الصفوف الأصلية − Σ الصفوف العكسية."""
    gross, reversed_ = db.execute(
        select(
            func.coalesce(func.sum(LotConsumption.qty).filter(LotConsumption.reverses_consumption_id.is_(None)), 0),
            func.coalesce(func.sum(LotConsumption.qty).filter(LotConsumption.reverses_consumption_id.isnot(None)), 0),
        ).where(LotConsumption.lot_id == lot_id)
    ).one()
    return Decimal(gross) - Decimal(reversed_)


def consuming_entry_nos(db: Session, lot_id: int) -> list[str]:
    """أرقام القيود التي ما زالت تستهلك من الدفعة (الحيّة فقط) — للرسائل العربية."""
    entry_ids = [c.entry_id for c in live_consumptions(db, lot_id)]
    if not entry_ids:
        return []
    rows = db.execute(select(JournalEntry.id, JournalEntry.entry_no).where(JournalEntry.id.in_(entry_ids))).all()
    by_id = dict(rows)
    return list(dict.fromkeys(by_id[i] for i in entry_ids if i in by_id))


def reverse_consumptions(db: Session, *, original: JournalEntry, reversal: JournalEntry, now: datetime) -> int:
    """يُستدعى من `posting.reverse_entry` لكل عكس (إلغاء · تعديل · سلسلة): كل استهلاك حيّ للقيد الأصلي
    يُعاد كميته لدفعته ويُضاف **صف عكسي** (append-only — الأصل لا يُحذف ولا يُعدَّل)، وتُعاد فتح الدفعة
    المقفلة لأن البيع استهلك آخرها (ما لم يكن قيد فتحها نفسه مُلغى). يُعيد عدد الصفوف المعكوسة."""
    reversed_ids = select(LotConsumption.reverses_consumption_id).where(LotConsumption.reverses_consumption_id.isnot(None))
    originals = db.execute(
        select(LotConsumption)
        .where(LotConsumption.entry_id == original.id, LotConsumption.reverses_consumption_id.is_(None),
               LotConsumption.id.notin_(reversed_ids))
        .order_by(LotConsumption.id)
    ).scalars().all()
    for c in originals:
        lot = db.execute(select(CurrencyLot).where(CurrencyLot.id == c.lot_id).with_for_update()).scalar_one()
        lot.remaining_qty = lot.remaining_qty + c.qty
        if lot.status == LotStatus.CLOSED:
            source = db.get(JournalEntry, lot.source_entry_id)
            if source is not None and source.status != EntryStatus.REVERSED:
                lot.status = LotStatus.OPEN
                lot.closed_at = None
        db.add(LotConsumption(
            lot_id=c.lot_id, entry_id=reversal.id, qty=c.qty, client_rate=c.client_rate,
            cost_share=-c.cost_share, revenue=-c.revenue, profit=-c.profit, profit_currency=c.profit_currency,
            consumed_at=now, reverses_consumption_id=c.id,
        ))
    db.flush()
    return len(originals)
