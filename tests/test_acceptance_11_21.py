"""اختبارات القبول ١١–٢١."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.engine import accounts_repo, chain as chain_mod, clock, lots_fifo
from app.engine.operations import exchange, swift_in, swift_out, swift_return
from app.models import AccountBalance, CurrencyLot, JournalEntry, JournalLine, SwiftMovement
from app.models.enums import LotStatus, SwiftStatus
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.mark.acceptance(11)
def test_chain_ref_excluded_from_any_sum(db, now):
    """`chain_ref` نصّي للعرض والتتبع فقط — لا يدخل أي مجموع في أي تقرير (§٢-٩).

    لا توجد شاشة تقارير بعد (مرحلة لاحقة) — يُختبَر هنا على مستوى محرك
    القيود: recompute-balances يحسب الأرصدة من debit/credit فقط، ولا شيء
    في السلسلة يُستخدم رقمياً في أي مجموع مالي.
    """
    client = f.make_client(db)
    user = f.make_user(db)
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("20000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry_date = clock.local_entry_date(now, WORK_TZ)

    def step1(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD",
            to_location_code="TRIPOLI", amount=Decimal("10000.000"), cost_rate=Decimal("5.15"),
            client_rate=Decimal("5.10"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
            chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    def step2(chain_ref, seq, total):
        return exchange.execute_via_rates(
            db, client=client, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY",
            to_location_code="CHINA", amount=Decimal("1941.75"), cost_rate=Decimal("6.95"),
            client_rate=Decimal("6.90"), work_timezone=WORK_TZ, created_by=user.id, now=now,
            idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=seq, chain_total=total,
        )

    result = chain_mod.execute_two_step_chain(db, entry_date=entry_date, step1=step1, step2=step2)

    # chain_ref نص (CHN-2026-000001) — لا معنى رقمياً له إطلاقاً، والقيدان
    # مستقلان تماماً في journal_lines: recompute-balances لا يستعلم
    # chain_ref في حساب أي رصيد (تحقُّق بنيوي مباشر من الاستعلام نفسه).
    import inspect

    from app.engine import recompute

    source = inspect.getsource(recompute.compute_true_balances)
    assert "chain_ref" not in source

    report = recompute.verify(db)
    assert report.ok
    assert isinstance(result.chain_ref, str) and result.chain_ref.startswith("CHN-")


def _open_test_lot(db, user, now, *, original_qty=Decimal("69500.00"), cost_rate=Decimal("6.95")):
    """يفتح دفعة عبر مسار سويفت خروج/وصول حقيقي كامل — لا اختصار مباشر."""
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=f.make_client(db), currency_code="USD", location_code="TURKEY",
        amount=Decimal("100000.00"), receiving_account_code=partner_acct.code, user=user, now=now,
    )
    out_entry = swift_out.execute(
        db, partner_account_code=partner_acct.code, amount=original_qty / cost_rate,
        work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out_entry.id)).scalar_one()
    bank = f.make_bank_account(db, currency_code="CNY")
    swift_in.execute(
        db, swift_movement_id=movement.id, total_amount=original_qty / cost_rate, fee_amount=Decimal("0.00"),
        receiving_account_code=bank.code, bank_conversion_rate=cost_rate, work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    lot = db.execute(select(CurrencyLot).where(CurrencyLot.source_entry_id.in_(
        select(JournalLine.entry_id).where(JournalLine.account_id == bank.id)
    ))).scalars().first()
    return lot, movement, partner_acct, bank


@pytest.mark.acceptance(12)
def test_swift_in_converted_opens_lot_with_correct_qty_and_rate(db, now):
    user = f.make_user(db)
    lot, movement, _, bank = _open_test_lot(db, user, now, original_qty=Decimal("69500.00"), cost_rate=Decimal("6.95"))
    assert lot is not None
    assert lot.currency_code == "CNY"
    assert lot.original_qty == Decimal("69500.00")
    assert lot.remaining_qty == Decimal("69500.00")
    assert lot.cost_rate == Decimal("6.95")
    assert lot.cost_total == Decimal("10000.00")
    assert lot.status == LotStatus.OPEN
    assert lot.account_id == bank.id
    assert movement.exchange_rate == Decimal("6.95")


@pytest.mark.acceptance(13)
def test_sell_from_single_lot_profit_matches_document_example(db, now):
    """بيع ٣٤٬٠٠٠ ¥ من دفعة ٦٫٩٥ بسعر ٦٫٨٠ → ربح ١٠٧٫٩١$، يزيد أصول موقع دفع العميل."""
    user = f.make_user(db)
    lot, *_ = _open_test_lot(db, user, now)
    client = f.make_client(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("20000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    entry = exchange.execute_via_lot(
        db, client=client, from_location_code="TURKEY", to_location_code="CHINA", amount=Decimal("5000.00"),
        client_rate=Decimal("6.80"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    assert entry.profit_amount == Decimal("107.910000")
    assert entry.profit_currency == "USD"

    clearing_usd = accounts_repo.get_currency_subaccount(db, "1900", "USD")
    profit_acct = accounts_repo.get_currency_subaccount(db, "4120", "USD")
    # الربح يزيد رصيد حساب الربح — أصل الشركة (المقاصة عند التكلفة) لم يُمسّ إيجاباً بالربح نفسه
    assert db.get(AccountBalance, profit_acct.id).balance == Decimal("107.910000")

    db.refresh(lot)
    assert lot.remaining_qty == Decimal("69500.00") - Decimal("34000.00")


@pytest.mark.acceptance(14)
def test_sell_across_three_lots_cost_share_sums_exactly_no_5900(db, now):
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("100000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    bank = f.make_bank_account(db, currency_code="CNY")

    def _open(qty, rate):
        out_entry = swift_out.execute(
            db, partner_account_code=partner_acct.code, amount=qty / rate, work_timezone=WORK_TZ,
            created_by=user.id, now=now, idempotency_key=f.uid(),
        )
        movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out_entry.id)).scalar_one()
        swift_in.execute(
            db, swift_movement_id=movement.id, total_amount=qty / rate, fee_amount=Decimal("0.00"),
            receiving_account_code=bank.code, bank_conversion_rate=rate, work_timezone=WORK_TZ,
            created_by=user.id, now=now, idempotency_key=f.uid(),
        )

    _open(Decimal("1000.00"), Decimal("6.90"))
    _open(Decimal("1000.00"), Decimal("6.95"))
    _open(Decimal("1000.00"), Decimal("7.00"))

    client = f.make_client(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("10000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    consumption = lots_fifo.consume(db, currency_code="CNY", qty_needed=Decimal("2500.00"), cost_decimals=2)
    assert len(consumption.parts) == 3  # يستهلك من الدفعات الثلاث بالترتيب (FIFO)
    assert sum(p.cost_share for p in consumption.parts) == consumption.total_cost

    entry_5900_before = accounts_repo.get_account_by_code(db, "5900")
    balance_before = db.get(AccountBalance, entry_5900_before.id)
    assert balance_before is None or balance_before.balance == Decimal("0")


@pytest.mark.acceptance(15)
def test_cost_rate_frozen_after_first_consumption(db, now):
    user = f.make_user(db)
    lot, *_ = _open_test_lot(db, user, now)
    client = f.make_client(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    exchange.execute_via_lot(
        db, client=client, from_location_code="TURKEY", to_location_code="CHINA", amount=Decimal("100.00"),
        client_rate=Decimal("6.80"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    db.refresh(lot)
    with pytest.raises(lots_fifo.LotFrozenError):
        lots_fifo.assert_lot_editable(lot)


@pytest.mark.acceptance(16)
def test_lot_exhausted_closes_and_rejects_new_sale(db, now):
    user = f.make_user(db)
    lot, *_ = _open_test_lot(db, user, now, original_qty=Decimal("680.00"), cost_rate=Decimal("6.80"))
    client = f.make_client(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    # استهلاك الدفعة بالكامل (680/6.80 = 100$ → 680¥)
    exchange.execute_via_lot(
        db, client=client, from_location_code="TURKEY", to_location_code="CHINA", amount=Decimal("100.00"),
        client_rate=Decimal("6.80"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    db.refresh(lot)
    assert lot.remaining_qty == Decimal("0")
    assert lot.status == LotStatus.CLOSED

    with pytest.raises(lots_fifo.LotStockExhaustedError):
        exchange.execute_via_lot(
            db, client=client, from_location_code="TURKEY", to_location_code="CHINA", amount=Decimal("10.00"),
            client_rate=Decimal("6.80"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
        )


@pytest.mark.acceptance(18)
def test_swift_out_in_return_closes_1501_correctly(db, now):
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    in_transit = accounts_repo.get_account_by_code(db, "1501")

    out_entry = swift_out.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("10000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    assert db.get(AccountBalance, in_transit.id).balance == Decimal("10000.00")
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out_entry.id)).scalar_one()
    assert movement.status == SwiftStatus.SENT

    bank_usd = f.make_bank_account(db, currency_code="USD")
    swift_in.execute(
        db, swift_movement_id=movement.id, total_amount=Decimal("10000.00"), fee_amount=Decimal("25.00"),
        receiving_account_code=bank_usd.code, work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(),
    )
    assert db.get(AccountBalance, in_transit.id).balance == Decimal("0.00")  # أُقفل تماماً
    db.refresh(movement)
    assert movement.status == SwiftStatus.RECEIVED

    # سويفت آخر مستقل ينتهي بمرتجع — العميل يحتاج رصيداً كافياً ليُحمَّل رسوم المرتجع
    client = f.make_client(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TURKEY", amount=Decimal("1000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    out_entry2 = swift_out.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("5000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    movement2 = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out_entry2.id)).scalar_one()
    swift_return.execute(
        db, swift_movement_id=movement2.id, partner_account_code=partner_acct.code, total_amount=Decimal("5000.00"),
        client=client, client_location_code="TURKEY", return_fee_amount=Decimal("50.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    assert db.get(AccountBalance, in_transit.id).balance == Decimal("0.00")  # أُقفل مرة أخرى
    db.refresh(movement2)
    assert movement2.status == SwiftStatus.RETURNED


@pytest.mark.acceptance(19)
def test_reverse_swift_in_resets_movement_status_same_transaction(db, now):
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    out_entry = swift_out.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("10000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out_entry.id)).scalar_one()
    bank_usd = f.make_bank_account(db, currency_code="USD")
    in_entry = swift_in.execute(
        db, swift_movement_id=movement.id, total_amount=Decimal("10000.00"), fee_amount=Decimal("0.00"),
        receiving_account_code=bank_usd.code, work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(),
    )

    swift_in.reverse(db, entry=in_entry, reason="فحص عكس SWIFT_IN", created_by=user.id, now=now)
    db.refresh(movement)
    assert movement.status == SwiftStatus.SENT
    assert movement.in_entry_id is None
    assert movement.received_confirmed is False

    from app.engine import recompute

    report = recompute.verify(db)
    assert report.swift_problems == []


@pytest.mark.acceptance(20)
def test_external_ref_has_no_financial_effect(db, now):
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=f.make_client(db), currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    out_entry = swift_out.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("10000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), external_ref="REF-ORIGINAL",
    )
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out_entry.id)).scalar_one()
    balance_before = db.get(AccountBalance, accounts_repo.get_account_by_code(db, "1501").id).balance

    movement.external_ref = "REF-CHANGED-LATER"
    db.flush()

    balance_after = db.get(AccountBalance, accounts_repo.get_account_by_code(db, "1501").id).balance
    assert balance_before == balance_after
    from app.engine import recompute

    assert recompute.verify(db).ok


@pytest.mark.acceptance(21)
def test_two_step_operation_leaves_nothing_pending(db, now):
    """CASH_TRANSFER/EXCHANGE تنتهي فوراً بذاتها — لا صف swift_movements ولا دفعة تُفتح."""
    from app.engine.operations import cash_transfer

    user = f.make_user(db)
    client = f.make_client(db)
    f.fund_client(
        db, client=client, currency_code="USD", location_code="TRIPOLI", amount=Decimal("20000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    exec_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    cost_acct = f.make_correspondent_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1310")
    f.fund_client(
        db, client=client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("2000.000"),
        receiving_account_code=cost_acct.code, user=user, now=now,
    )
    entry = cash_transfer.execute(
        db, client=client, currency_code="USD", from_location_code="TRIPOLI", to_location_code="TURKEY",
        amount=Decimal("5000.00"), source_account_code="1104", execution_account_code=exec_acct.code,
        collection_account_code="1101", commission_currency="LYD", client_commission_amount=Decimal("400.000"),
        cost_commission_amount=Decimal("250.000"), cost_correspondent_account_code=cost_acct.code,
        work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    from app.models.enums import EntryStatus

    assert entry.status == EntryStatus.POSTED
    swift_rows = db.execute(select(SwiftMovement)).scalars().all()
    assert all(row.out_entry_id != entry.id and row.in_entry_id != entry.id for row in swift_rows)
    lots = db.execute(select(CurrencyLot).where(CurrencyLot.source_entry_id == entry.id)).scalars().all()
    assert lots == []
