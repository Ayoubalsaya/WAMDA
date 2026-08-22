"""فحص سريع لمسارات لم يغطها عرض الأمثلة الثلاثة: العكس · رفض LYD⇄CNY ·
معالج الخطوتين الذرّي. تشغيل يدوي فقط — ليس جزءاً من اختبارات المرحلة ٣.
"""

from __future__ import annotations

import sys
import uuid
from decimal import Decimal

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.engine import chain, clock, fx, posting
from app.engine.operations import cash_transfer, exchange, receipt
from app.models import Client, JournalEntry, SwiftMovement, User

WORK_TZ = settings.work_timezone


def _uuid():
    return str(uuid.uuid4())


def main():
    db = SessionLocal()
    now = clock.system_clock()
    user = db.execute(select(User).where(User.username == "demo_stage2")).scalar_one()
    client = db.execute(select(Client).where(Client.code == "DEMO-C0001")).scalar_one()

    print("── ١) رفض LYD⇄CNY مباشرة ──")
    try:
        fx.assert_pivot_pair("LYD", "CNY", "USD")
        print("  فشل: كان يجب أن يُرفض!")
    except fx.InvalidCurrencyPairError as e:
        print(f"  رُفض كما هو متوقع: {e}")

    print("\n── ٢) عكس قيد CASH_TRANSFER (المثال أ) ──")
    entry_a = db.execute(
        select(JournalEntry).where(JournalEntry.operation_type == "CASH_TRANSFER").order_by(JournalEntry.id)
    ).scalars().first()
    reversal = posting.reverse_entry(db, entry_a, reason="فحص سريع للعكس", created_by=user.id, now=now)
    db.commit()
    print(f"  الأصلي {entry_a.entry_no} → status={entry_a.status.value}")
    print(f"  العكسي {reversal.entry_no} → status={reversal.status.value}, reverses={reversal.reverses_entry_id}")

    print("\n── ٣) عكس SWIFT_IN بعد استهلاك جزء من دفعته → يجب أن يُرفض ──")
    from app.engine.operations import swift_in

    movement = db.execute(select(SwiftMovement)).scalars().first()
    swift_in_entry = db.get(JournalEntry, movement.in_entry_id)
    try:
        swift_in.reverse(db, entry=swift_in_entry, reason="فحص", created_by=user.id, now=now)
        print("  فشل: كان يجب أن يُرفض (الدفعة استُهلك منها جزء في المثال ج)!")
    except swift_in.SwiftInAlreadyConsumedError as e:
        db.rollback()
        print(f"  رُفض كما هو متوقع: {e}")

    print("\n── ٤) معالج الخطوتين الذرّي: LYD → USD → CNY ──")
    receipt.execute(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=_uuid(), description="تمويل تجريبي إضافي — سلسلة الخطوتين",
    )
    db.commit()
    entry_date = clock.local_entry_date(now, WORK_TZ)

    def step1(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI",
            to_currency="USD", to_location_code="TRIPOLI", amount=Decimal("10000.000"),
            cost_rate=Decimal("5.15"), client_rate=Decimal("5.10"), work_timezone=WORK_TZ,
            created_by=user.id, now=now, idempotency_key=_uuid(),
            negative_margin_reason="سعر السوق لحظة العملية", chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    def step2(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="USD", from_location_code="TRIPOLI",
            to_currency="CNY", to_location_code="CHINA", amount=Decimal("1941.75"),
            cost_rate=Decimal("6.95"), client_rate=Decimal("6.90"), work_timezone=WORK_TZ,
            created_by=user.id, now=now, idempotency_key=_uuid(),
            chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    result = chain.execute_two_step_chain(db, entry_date=entry_date, step1=step1, step2=step2)
    db.commit()
    print(f"  chain_ref={result.chain_ref}")
    print(f"  خطوة ١: {result.step1_entry.entry_no} ربح={result.step1_entry.profit_amount} {result.step1_entry.profit_currency}")
    print(f"  خطوة ٢: {result.step2_entry.entry_no} ربح={result.step2_entry.profit_amount} {result.step2_entry.profit_currency}")

    db.close()


if __name__ == "__main__":
    main()
