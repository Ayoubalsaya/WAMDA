"""عكس/تعديل قيد استهلك من دفعة رمبي يعيد الكمية ويضيف صفاً عكسياً (٢٠٢٦-١٠-٠٢).

الخلفية: إلغاء بيع رمبي من دفعة لم يكن يعيد الكمية ولا يعكس صف الاستهلاك — المخزون يضيع بصمت، والفحص
القديم (`remaining = original − Σ الاستهلاك`) لا يكشفه لأن الصف بقي مسجَّلاً. الآن:
  · كل مسار عكس (`posting.reverse_entry`: إلغاء · تعديل · سلسلة) يعيد الكمية ويضيف صفاً عكسياً (append-only)؛
  · تعديل بيع الرمبي = عكس + إنشاء في المعاملة نفسها؛ فشله يتراجع كلاهما؛
  · إلغاء SWIFT_IN بعد الاستهلاك يُرفض بـ٤٠٩ يسمّي القيود المستهلِكة، وينجح بعد إلغائها؛
  · `recompute.verify` يكشف هذا الصنف بنيوياً.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.engine import accounts_repo, lots_fifo, recompute
from app.engine.operations import exchange as exchange_op
from app.models import CurrencyLot, JournalEntry, LotConsumption
from app.models.enums import EntryStatus, LotStatus
from tests import factories as f
from tests.test_treasury_exchange_never_touches_lots import _csrf, _login, _open_cny_lot, client  # noqa: F401

WORK_TZ = "Africa/Tripoli"
RATE = Decimal("6.80")  # ١٠$ × ٦٫٨٠ = ٦٨ يوان لكل بيع بالضبط


def _client_with_usd(db, admin, now):
    c = f.make_client(db)
    f.fund_client(db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("500"),
                  receiving_account_code="1104", user=admin, now=now)
    return c


def _sell(db, admin, c, now, amount="10"):
    return exchange_op.execute_via_lot(
        db, client=c, from_location_code="TURKEY", to_location_code="CHINA", amount=Decimal(amount),
        client_rate=RATE, work_timezone=WORK_TZ, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )


def _small_lot(db, admin, now, qty: str, *, opened_offset_minutes: int = 0):
    """دفعة صغيرة مباشرة (بلا سويفت) — مصدرها قيد قبض حقيقي."""
    from datetime import timedelta

    src_client = f.make_client(db)
    source = f.fund_client(db, client=src_client, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("1"),
                           receiving_account_code="1101", user=admin, now=now)
    bank = f.make_bank_account(db, currency_code="CNY")
    return lots_fifo.open_lot(
        db, source_entry_id=source.id, currency_code="CNY", account_id=bank.id, original_qty=Decimal(qty),
        cost_rate=Decimal("6.80"), cost_currency="USD", cost_decimals=2, now=now + timedelta(minutes=opened_offset_minutes),
    )


def _rows(db, lot_id):
    return db.execute(select(LotConsumption).where(LotConsumption.lot_id == lot_id).order_by(LotConsumption.id)).scalars().all()


def _cancel(client, entry_id, reason="اختبار"):
    return client.post(f"/operations/{entry_id}/cancel", headers=_csrf(client), json={"reason": reason})


# ═══ ١) الإلغاء يعيد الكمية ويضيف صفاً عكسياً (append-only) ═══


def test_cancel_lot_sale_restores_quantity_and_appends_a_reversal_row(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)
    db.refresh(lot)
    assert lot.remaining_qty == lot.original_qty - Decimal("68")
    (orig,) = _rows(db, lot.id)
    snapshot = (orig.id, orig.qty, orig.cost_share, orig.revenue, orig.profit, orig.entry_id)

    resp = _cancel(client, sale.id)
    assert resp.status_code == 200, resp.text
    db.refresh(lot)
    assert lot.remaining_qty == lot.original_qty

    rows = _rows(db, lot.id)
    assert len(rows) == 2, "الصف الأصلي يبقى + صف عكسي جديد (لا حذف)"
    orig2, rev = rows
    assert (orig2.id, orig2.qty, orig2.cost_share, orig2.revenue, orig2.profit, orig2.entry_id) == snapshot  # الأصل لم يُمَس
    db.refresh(sale)
    assert rev.reverses_consumption_id == orig.id
    assert rev.entry_id == sale.reversed_by_entry_id
    assert rev.qty == orig.qty and rev.cost_share == -orig.cost_share and rev.revenue == -orig.revenue and rev.profit == -orig.profit
    assert lots_fifo.net_consumed_qty(db, lot.id) == Decimal("0")
    assert lots_fifo.live_consumptions(db, lot.id) == []
    assert recompute.verify(db).lot_problems == []


def test_cancelled_sale_no_longer_counts_in_lot_reports(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)
    row = next(r for r in client.get("/lots").json() if r["id"] == lot.id)
    assert row["num_sales"] == 1
    assert _cancel(client, sale.id).status_code == 200
    row = next(r for r in client.get("/lots").json() if r["id"] == lot.id)
    assert row["num_sales"] == 0 and Decimal(row["total_profit"]) == 0
    assert client.get(f"/lots/{lot.id}").json()["consumptions"] == []


# ═══ ٢) الدفعة التي أغلقها البيع (استهلك آخرها) يعيد الإلغاء فتحها ═══


def test_cancel_reopens_a_lot_the_sale_exhausted(db, client, now):
    admin = _login(db, client)
    lot = _small_lot(db, admin, now, "68.00")
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)
    db.refresh(lot)
    assert lot.remaining_qty == 0 and lot.status == LotStatus.CLOSED and lot.closed_at is not None

    assert _cancel(client, sale.id).status_code == 200
    db.refresh(lot)
    assert lot.remaining_qty == Decimal("68.00")
    assert lot.status == LotStatus.OPEN and lot.closed_at is None
    assert recompute.verify(db).lot_problems == []


# ═══ ٣) التعديل = عكس + إنشاء ذرّياً ═══


def test_edit_lot_sale_restores_old_quantity_then_consumes_the_new_one(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    c = _client_with_usd(db, admin, now)
    sale = _sell(db, admin, c, now)  # ٦٨
    resp = client.post(f"/operations/{sale.id}/edit", headers=_csrf(client), json={
        "reason": "تصحيح المبلغ",
        "operation": {"client_id": c.id, "from_location_code": "TURKEY", "to_location_code": "CHINA",
                      "amount": "20", "client_rate": "6.80"},
    })
    assert resp.status_code == 200, resp.text
    db.refresh(lot)
    assert lot.remaining_qty == lot.original_qty - Decimal("136"), "القديمة أُعيدت (٦٨) ثم استُهلكت الجديدة (١٣٦)"
    rows = _rows(db, lot.id)
    assert [(r.reverses_consumption_id is not None, r.qty) for r in rows] == [
        (False, Decimal("68")), (True, Decimal("68")), (False, Decimal("136"))]
    assert [c_.qty for c_ in lots_fifo.live_consumptions(db, lot.id)] == [Decimal("136")]
    assert recompute.verify(db).lot_problems == []


def test_failed_edit_rolls_back_both_the_reversal_and_the_restore(db, client, now):
    """مخزون غير كافٍ للمبلغ الجديد ← ٤٠٩ عربي، والمعاملة كلها تتراجع: البيع الأصلي والكمية كما كانا."""
    admin = _login(db, client)
    lot = _small_lot(db, admin, now, "68.00")
    c = _client_with_usd(db, admin, now)
    sale = _sell(db, admin, c, now)  # يستهلك الدفعة كلها
    savepoint = db.begin_nested()  # get_db الحقيقي يتراجع عند الاستثناء؛ هنا نحاكيه بنقطة حفظ صريحة
    resp = client.post(f"/operations/{sale.id}/edit", headers=_csrf(client), json={
        "reason": "زيادة المبلغ",
        "operation": {"client_id": c.id, "from_location_code": "TURKEY", "to_location_code": "CHINA",
                      "amount": "50", "client_rate": "6.80"},
    })
    assert resp.status_code == 409, resp.text
    assert "مخزون" in resp.json()["detail"]
    savepoint.rollback()
    db.expire_all()
    assert db.get(JournalEntry, sale.id).status == EntryStatus.POSTED
    lot = db.get(CurrencyLot, lot.id)
    assert lot.remaining_qty == 0 and lot.status == LotStatus.CLOSED
    assert len(_rows(db, lot.id)) == 1
    assert recompute.verify(db).lot_problems == []


# ═══ ٤) بيع يمتد على دفعتين (FIFO) ═══


def test_cancel_restores_every_lot_a_sale_spanned(db, client, now):
    admin = _login(db, client)
    first = _small_lot(db, admin, now, "40.00", opened_offset_minutes=0)
    second = _small_lot(db, admin, now, "100.00", opened_offset_minutes=5)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)  # ٦٨ = ٤٠ من الأولى + ٢٨ من الثانية
    db.refresh(first); db.refresh(second)
    assert (first.remaining_qty, first.status) == (Decimal("0.00"), LotStatus.CLOSED)
    assert second.remaining_qty == Decimal("72.00")

    assert _cancel(client, sale.id).status_code == 200
    db.refresh(first); db.refresh(second)
    assert (first.remaining_qty, first.status) == (Decimal("40.00"), LotStatus.OPEN)
    assert second.remaining_qty == Decimal("100.00")
    assert recompute.verify(db).lot_problems == []


# ═══ ٥) إلغاء القيد الذي فتح الدفعة ═══


def test_cancelling_the_swift_in_that_opened_a_consumed_lot_is_rejected_naming_the_consumers(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)

    resp = _cancel(client, lot.source_entry_id)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert lot.lot_no in detail and sale.entry_no in detail and "ألغِ هذه القيود أولاً" in detail

    # ألغِ البيع ثم أعد المحاولة: تنجح، وتُقفل الدفعة (قيدها المُنشئ مُلغى) وتبقى كاملة
    assert _cancel(client, sale.id).status_code == 200
    assert _cancel(client, lot.source_entry_id).status_code == 200
    db.refresh(lot)
    assert lot.status == LotStatus.CLOSED and lot.remaining_qty == lot.original_qty
    assert recompute.verify(db).lot_problems == []


# ═══ ٦) قيد عكسي لا يُلغى ولا يُعدَّل ═══


def test_a_reversal_entry_cannot_be_cancelled_or_edited(db, client, now):
    admin = _login(db, client)
    _open_cny_lot(db, admin, now)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)
    assert _cancel(client, sale.id).status_code == 200
    db.refresh(sale)
    resp = _cancel(client, sale.reversed_by_entry_id)
    assert resp.status_code == 409 and "عكسي" in resp.json()["detail"]
    resp = client.post(f"/operations/{sale.reversed_by_entry_id}/edit", headers=_csrf(client),
                       json={"reason": "x", "operation": {}})
    assert resp.status_code == 409 and "عكسي" in resp.json()["detail"]


# ═══ ٧) فحص الاتساق يكشف هذا الصنف ═══


def _simulate_legacy_silent_loss(db, lot, sale):
    """حالة ما قبل الإصلاح: القيد REVERSED، الاستهلاك بقي حيّاً بلا صف عكسي، والدفعة منقوصة."""
    db.execute(text("DELETE FROM lot_consumptions WHERE reverses_consumption_id IS NOT NULL"))
    db.execute(text("UPDATE currency_lots SET remaining_qty = original_qty - 68 WHERE id = :i"), {"i": lot.id})
    db.expire_all()


def test_verify_detects_the_silent_loss_the_old_check_missed(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)
    assert _cancel(client, sale.id).status_code == 200
    _simulate_legacy_silent_loss(db, lot, sale)

    # الفحص القديم (Σ كل الاستهلاكات) كان يرى: remaining = original − 68 ✓ فلا يشتكي — هنا يجب أن يشتكي
    problems = recompute.verify(db).lot_problems
    assert any("قيده" in p and "مُلغى" in p and "لا صف عكسي" in p for p in problems), problems


def test_verify_flags_remaining_mismatch_closed_with_stock_and_bad_reversal_rows(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)
    assert recompute.verify(db).lot_problems == []

    db.execute(text("UPDATE currency_lots SET remaining_qty = remaining_qty - 5 WHERE id = :i"), {"i": lot.id})
    db.expire_all()
    assert any("net_consumed" in p for p in recompute.verify(db).lot_problems)
    db.execute(text("UPDATE currency_lots SET remaining_qty = remaining_qty + 5 WHERE id = :i"), {"i": lot.id})

    db.execute(text("UPDATE currency_lots SET status = 'CLOSED' WHERE id = :i"), {"i": lot.id})
    db.expire_all()
    assert any("CLOSED" in p and "رصيد" in p for p in recompute.verify(db).lot_problems)
    db.execute(text("UPDATE currency_lots SET status = 'OPEN' WHERE id = :i"), {"i": lot.id})

    assert _cancel(client, sale.id).status_code == 200
    db.execute(text("UPDATE lot_consumptions SET qty = qty + 1 WHERE reverses_consumption_id IS NOT NULL"))
    db.expire_all()
    assert any("لا يطابق أصله" in p for p in recompute.verify(db).lot_problems)


# ═══ ٨) ترحيل البيانات التاريخية (الصف العكسي الناقص لقيود ملغاة قبل الإصلاح) ═══


def test_migration_backfills_historic_reversed_sales(db, client, now):
    admin = _login(db, client)
    lot = _open_cny_lot(db, admin, now)
    sale = _sell(db, admin, _client_with_usd(db, admin, now), now)
    assert _cancel(client, sale.id).status_code == 200
    _simulate_legacy_silent_loss(db, lot, sale)
    assert recompute.verify(db).lot_problems  # الحالة التالفة التاريخية

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "3f1a9c7d2e44_lot_consumption_reversal_rows.py"
    spec = importlib.util.spec_from_file_location("lot_reversal_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db.flush()
    assert migration.backfill_historic_reversals(db.connection()) == 1
    assert migration.backfill_historic_reversals(db.connection()) == 0  # idempotent
    db.expire_all()
    assert db.get(CurrencyLot, lot.id).remaining_qty == lot.original_qty
    assert recompute.verify(db).lot_problems == []


# ═══ ٩) لا مسار يُنشئ صفوف استهلاك خارج lots_fifo ═══


def test_only_lots_fifo_creates_lot_consumption_rows():
    """قائمة المسارات التي تُنشئ استهلاكاً: `execute_via_lot` (POST /operations/exchange/from-lot، وتعديل بيع
    الرمبي) عبر `lots_fifo.apply_consumption` — وحده. أي مسار جديد يستدعي `LotConsumption(` خارج
    `lots_fifo.py` يكسر هذا الاختبار فيُراجَع عكسه وتعديله (`reverse_consumptions` عام لكل عكس)."""
    root = Path(__file__).resolve().parent.parent / "app"
    offenders = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*.py")
        if "LotConsumption(" in p.read_text(encoding="utf-8") and p.name != "lots_fifo.py" and p.parent.name != "models"
    )
    assert offenders == [], f"مسارات جديدة تُنشئ استهلاكاً: {offenders}"
    callers = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*.py")
        if "apply_consumption(" in p.read_text(encoding="utf-8") and p.name != "lots_fifo.py"
    )
    assert callers == ["engine/operations/exchange.py"]
