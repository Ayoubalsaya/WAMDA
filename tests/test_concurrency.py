"""اختبارات تزامن حقيقية — اختبارات القبول ١٧ · ٤٣ · ٤٤ · ٤٥.

جلسات/اتصالات منفصلة فعلياً عبر `ThreadPoolExecutor`، لا محاكاة — تُطلَب
صراحة في توجيهات المرحلة ٣ لأن تنافس الأقفال الحقيقي (`SELECT…FOR UPDATE`،
`pg_advisory_xact_lock`) لا يظهر إلا بمعاملات منفصلة فعلاً تتنافس معاً.

**تحذير نطاق:** هذه الاختبارات وحدها من كامل مجموعة المرحلة ٣ تلتزم
(commit) بيانات حقيقية على قاعدة التطوير — عزل fixture `db` المعتاد
(معاملة واحدة تُلغى) لا يصلح هنا. أعِد ضبط القاعدة لحالة مرجعية نظيفة
بعد تشغيلها إن أردت:
    alembic downgrade base && alembic upgrade head && python -m app.cli seed
"""

from __future__ import annotations

import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.engine import accounts_repo, lots_fifo, recompute
from app.engine.operations import exchange, payment, receipt, swift_in, swift_out
from app.engine.posting import CreditLimitExceededError, InsufficientBalanceError
from app.models import AccountBalance, Client, Counter, CurrencyLot, IdempotencyKey, JournalEntry, SwiftMovement
from tests import factories as f

WORK_TZ = "Africa/Tripoli"
CONC_NOW = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)

pytestmark = pytest.mark.concurrency


@pytest.fixture(scope="module")
def conc_engine():
    eng = create_engine(settings.database_url, pool_size=50, max_overflow=10)
    yield eng
    eng.dispose()


def _session(engine):
    return sessionmaker(bind=engine)()


@pytest.mark.acceptance(17)
def test_20_concurrent_sales_same_lot_no_overconsumption(conc_engine):
    """٢٠ بيعاً متزامناً على نفس الدفعة — سعتها تكفي ١٩ بالضبط، فيجب أن
    ينجح ١٩ ويُرفض ١ بـ`LotStockExhaustedError`، ولا `remaining_qty` سالبة."""
    setup = _session(conc_engine)
    admin = f.make_user(setup)
    partner_acct = f.make_correspondent_account(
        setup, currency_code="USD", location_code="TURKEY", parent_code="1320"
    )
    funder = f.make_client(setup)
    f.fund_client(
        setup, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("100000.00"),
        receiving_account_code=partner_acct.code, user=admin, now=CONC_NOW,
    )
    bank = f.make_bank_account(setup, currency_code="CNY")
    rate = Decimal("6.80")
    per_sale_cny = Decimal("68.00")  # 68/6.80 = 10.00$ بالضبط لكل عملية
    lot_qty = per_sale_cny * 19  # سعة ١٩ عملية بالضبط من ٢٠ محاولة
    out_entry = swift_out.execute(
        setup, partner_account_code=partner_acct.code, amount=lot_qty / rate, work_timezone=WORK_TZ,
        created_by=admin.id, now=CONC_NOW, idempotency_key=f.uid(),
    )
    movement = setup.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out_entry.id)).scalar_one()
    swift_in.execute(
        setup, swift_movement_id=movement.id, total_amount=lot_qty / rate, fee_amount=Decimal("0.00"),
        receiving_account_code=bank.code, bank_conversion_rate=rate, work_timezone=WORK_TZ,
        created_by=admin.id, now=CONC_NOW, idempotency_key=f.uid(),
    )
    admin_id = admin.id
    bank_id = bank.id
    client_ids = []
    for _ in range(20):
        c = f.make_client(setup)
        f.fund_client(
            setup, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("1000.00"),
            receiving_account_code="1104", user=admin, now=CONC_NOW,
        )
        client_ids.append(c.id)
    setup.commit()
    setup.close()

    outcomes = {"ok": 0, "exhausted": 0}
    lock = threading.Lock()

    def worker(client_id):
        session = _session(conc_engine)
        try:
            client = session.get(Client, client_id)
            exchange.execute_via_lot(
                session, client=client, from_location_code="TURKEY", to_location_code="CHINA",
                amount=Decimal("10.00"), client_rate=rate, work_timezone=WORK_TZ, created_by=admin_id,
                now=CONC_NOW, idempotency_key=f.uid(),
            )
            session.commit()
            with lock:
                outcomes["ok"] += 1
        except lots_fifo.LotStockExhaustedError:
            session.rollback()
            with lock:
                outcomes["exhausted"] += 1
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(worker, client_ids))

    assert outcomes == {"ok": 19, "exhausted": 1}

    verify = _session(conc_engine)
    lot = verify.execute(select(CurrencyLot).where(CurrencyLot.account_id == bank_id)).scalars().first()
    assert lot.remaining_qty == Decimal("0.00")
    verify.close()


@pytest.mark.acceptance(43)
def test_50_concurrent_requests_same_idempotency_key_single_entry(conc_engine):
    setup = _session(conc_engine)
    admin = f.make_user(setup)
    client = f.make_client(setup)
    admin_id, client_id = admin.id, client.id
    setup.commit()
    setup.close()

    shared_key = f.uid()
    results: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(_i):
        session = _session(conc_engine)
        try:
            c = session.get(Client, client_id)
            entry = receipt.execute(
                session, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
                receiving_account_code="1101", work_timezone=WORK_TZ, created_by=admin_id, now=CONC_NOW,
                idempotency_key=shared_key,
            )
            session.commit()
            with lock:
                results.append(entry.id)
        except Exception as exc:  # noqa: BLE001 — نسجّل أي فشل غير متوقع للتشخيص
            session.rollback()
            with lock:
                errors.append(exc)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(worker, range(50)))

    assert not errors, errors
    assert len(results) == 50
    assert len(set(results)) == 1  # نفس معرّف القيد للجميع — قيد واحد فقط أُنشئ فعلياً

    verify = _session(conc_engine)
    matching_entries = verify.execute(select(JournalEntry).where(JournalEntry.id == results[0])).scalars().all()
    assert len(matching_entries) == 1
    idem_rows = verify.execute(select(IdempotencyKey).where(IdempotencyKey.key == shared_key)).scalars().all()
    assert len(idem_rows) == 1
    verify.close()


@pytest.mark.acceptance(44)
def test_50_parallel_entries_same_account_no_lost_updates(conc_engine):
    setup = _session(conc_engine)
    admin = f.make_user(setup)
    client = f.make_client(setup)
    admin_id, client_id = admin.id, client.id
    setup.commit()
    setup.close()

    def worker(_i):
        session = _session(conc_engine)
        try:
            c = session.get(Client, client_id)
            receipt.execute(
                session, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10.000"),
                receiving_account_code="1101", work_timezone=WORK_TZ, created_by=admin_id, now=CONC_NOW,
                idempotency_key=f.uid(),
            )
            session.commit()
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(worker, range(50)))

    verify = _session(conc_engine)
    client_account = accounts_repo.get_or_create_client_account(
        verify, client=verify.get(Client, client_id), currency_code="LYD", location_code="TRIPOLI"
    )
    balance = verify.get(AccountBalance, client_account.id).balance
    assert balance == Decimal("500.000")  # ٥٠ × ١٠.٠٠٠ بالضبط — لا تحديث مفقود

    report = recompute.verify(verify)
    assert report.ok, (report.balance_diffs, report.swift_problems)
    verify.close()


@pytest.mark.acceptance(45)
def test_100_concurrent_entries_10_failures_numbering_stays_contiguous(conc_engine):
    setup = _session(conc_engine)
    admin = f.make_user(setup)
    client = f.make_client(setup)
    empty_box = f.make_bank_account(setup, currency_code="LYD", location_code="TRIPOLI", parent_code="1400")
    admin_id, client_id, empty_box_code = admin.id, client.id, empty_box.code

    counter_row = setup.execute(
        select(Counter).where(Counter.name == "WMD", Counter.year == CONC_NOW.year)
    ).scalar_one_or_none()
    start_value = counter_row.last_value if counter_row else 0
    setup.commit()
    setup.close()

    tasks = ["ok"] * 90 + ["fail"] * 10
    random.Random(7).shuffle(tasks)
    created_ids: list[int] = []
    lock = threading.Lock()

    def worker(kind):
        session = _session(conc_engine)
        try:
            c = session.get(Client, client_id)
            if kind == "ok":
                entry = receipt.execute(
                    session, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5.000"),
                    receiving_account_code="1101", work_timezone=WORK_TZ, created_by=admin_id, now=CONC_NOW,
                    idempotency_key=f.uid(),
                )
                session.commit()
                with lock:
                    created_ids.append(entry.id)
            else:
                # صندوق بلا تمويل إطلاقاً — رفض مضمون بعد تخصيص entry_no
                # وقبل أي commit، فيرتد العدّاد مع كامل المعاملة (§٥ قاعدة ٩).
                payment.execute(
                    session, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5.000"),
                    paying_account_code=empty_box_code, work_timezone=WORK_TZ, created_by=admin_id,
                    now=CONC_NOW, idempotency_key=f.uid(),
                )
                session.commit()  # لا يُنفَّذ أبداً في المسار السليم
        except (InsufficientBalanceError, CreditLimitExceededError):
            session.rollback()
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=40) as pool:
        list(pool.map(worker, tasks))

    assert len(created_ids) == 90

    verify = _session(conc_engine)
    entries = verify.execute(select(JournalEntry).where(JournalEntry.id.in_(created_ids))).scalars().all()
    numbers = sorted(int(e.entry_no.rsplit("-", 1)[-1]) for e in entries)
    assert len(set(numbers)) == 90  # لا تكرار
    assert numbers == list(range(start_value + 1, start_value + 91))  # متصل بلا فجوة
    verify.close()
