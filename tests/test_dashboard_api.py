"""اختبارات HTTP للوحة التحكم · مركز السيولة · الحسابات · الدفعات
(`app/routers/dashboard.py`، §٧-٢·٧-٤·٧-٧·٧-٨)."""

from __future__ import annotations

from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.engine.operations import exchange as exchange_op, swift_in as swift_in_op, swift_out as swift_out_op
from app.main import app
from app.models import CurrencyLot, JournalEntry, SwiftMovement
from app.models.enums import EntryStatus, OperationType
from app.security.passwords import hash_password
from tests import factories as f

WORK_TZ = "Africa/Tripoli"


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(db, client: TestClient, *, role: str = "ACCOUNTANT"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200
    return user


def test_dashboard_summary_kpis_split_funds_from_liabilities(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    funds = {r["currency_code"]: Decimal(r["amount"]) for r in body["kpis"]["funds"]}
    liabilities = {r["currency_code"]: Decimal(r["amount"]) for r in body["kpis"]["client_liabilities"]}
    assert funds["LYD"] >= Decimal("500.000")  # حساب 1101 (صندوق) — أصل
    assert liabilities["LYD"] >= Decimal("500.000")  # حساب 2100-* العميل — التزام مقابل


def test_dashboard_profit_split_transfer_fee_vs_exchange_spread(db, client, now, monkeypatch):
    # "أرباح اليوم" في المسار يعتمد system_clock() الحقيقي، لا `now` الوهمي
    # المُحقَن هنا — يجب تثبيته لهذا الاختبار وحده كي يطابق تاريخ القيود
    # المُنشأة بـ`now` المزيَّف، بلا أي مساس بمصدر الوقت الحقيقي في الإنتاج.
    monkeypatch.setattr("app.routers.dashboard.system_clock", lambda: now)
    _login(db, client)
    user = f.make_user(db)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.15"), client_rate=Decimal("5.10"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
    )
    resp = client.get("/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()["today_profit"]
    exchange_currencies = {r["currency_code"] for r in body["exchange_spread"]}
    transfer_currencies = {r["currency_code"] for r in body["transfer_fee"]}
    assert "USD" in exchange_currencies
    assert "USD" not in transfer_currencies  # الصرافة لا تدخل فرق التحويل إطلاقاً


def test_dashboard_alert_negative_asset_balance(db, client, now):
    _login(db, client)
    user = f.make_user(db, role="ADMIN")
    # صندوق اختبار طازج بدل "1101" الحقيقي — رصيد "1101" الفعلي في قاعدة
    # التطوير المشتركة كبير موجب فعلاً، فخصم صغير نسبي لن يجعله سالباً؛
    # نحتاج بداية صفرية مضمونة لإثبات أن التنبيه يكتشف السالب فعلاً.
    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    c = f.make_client(db, credit_allowed=True)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code=box.code, user=user, now=now,
    )
    from app.engine.operations import payment as payment_op

    payment_op.execute(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("150.000"),
        paying_account_code=box.code, work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
        allow_negative=True, override_reason="اختبار تنبيه رصيد سالب",
    )
    resp = client.get("/dashboard/summary")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert any(a["code"] == "negative_balance" and box.code in a["message_ar"] for a in alerts)


def test_dashboard_alert_draft_pending_detects_stray_draft(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    stray = JournalEntry(
        entry_no=f"WMD-TEST-{f.uid()}", entry_date=now.date(), operation_type=OperationType.EXPENSE,
        status=EntryStatus.DRAFT, created_by=user.id,
    )
    db.add(stray)
    db.flush()
    resp = client.get("/dashboard/summary")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert any(a["code"] == "draft_pending" for a in alerts)


def test_liquidity_position_assets_vs_liabilities_per_location(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("8000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    resp = client.get("/position/liquidity")
    assert resp.status_code == 200
    rows = {(r["currency_code"], r["location_code"]): r for r in resp.json()}
    row = rows[("USD", "TURKEY")]
    assert Decimal(row["assets"]) >= Decimal("8000.00")
    assert Decimal(row["liabilities"]) >= Decimal("8000.00")
    assert Decimal(row["net"]) == Decimal(row["assets"]) - Decimal(row["liabilities"])


def test_accounts_boxes_lists_libya_cash_accounts(db, client):
    _login(db, client)
    resp = client.get("/accounts/boxes")
    assert resp.status_code == 200
    codes = {a["code"] for a in resp.json()["accounts"]}
    assert {"1101", "1102", "1103", "1104"} <= codes


def test_accounts_correspondents_grouped_by_partner_turkey_only(db, client):
    _login(db, client)
    turkey = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    china_wrong = f.make_correspondent_account(db, currency_code="USD", location_code="CHINA", parent_code="1320")
    resp = client.get("/accounts/correspondents")
    assert resp.status_code == 200
    body = resp.json()
    all_codes = {a["code"] for g in body["groups"] for a in g["accounts"]}
    assert turkey.code in all_codes
    assert china_wrong.code not in all_codes
    assert len(body["groups"]) >= 1
    assert any(len(g["accounts"]) == 1 and g["accounts"][0]["code"] == turkey.code for g in body["groups"])


def test_accounts_banks_china_only(db, client):
    _login(db, client)
    china_bank = f.make_bank_account(db, currency_code="CNY", location_code="CHINA")
    resp = client.get("/accounts/banks")
    assert resp.status_code == 200
    codes = {a["code"] for a in resp.json()["accounts"]}
    assert china_bank.code in codes


def test_lots_list_and_detail_profit_matches_consumptions(db, client, now):
    _login(db, client)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funder = f.make_client(db)
    f.fund_client(
        db, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    bank = f.make_bank_account(db, currency_code="CNY")
    out = swift_out_op.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("1000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), external_ref="REF-LOT-TEST",
    )
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out.id)).scalar_one()
    in_entry = swift_in_op.execute(
        db, swift_movement_id=movement.id, total_amount=Decimal("1000.00"), fee_amount=Decimal("0.00"),
        receiving_account_code=bank.code, bank_conversion_rate=Decimal("6.80"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    lot_row = db.execute(select(CurrencyLot).where(CurrencyLot.source_entry_id == in_entry.id)).scalar_one()

    buyer = f.make_client(db)
    f.fund_client(
        db, client=buyer, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    exchange_op.execute_via_lot(
        db, client=buyer, from_location_code="TRIPOLI", to_location_code="CHINA", amount=Decimal("500.00"),
        client_rate=Decimal("6.70"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )

    resp = client.get("/lots")
    assert resp.status_code == 200
    rows = resp.json()
    row = next(r for r in rows if r["id"] == lot_row.id)
    assert row["swift_external_ref"] == "REF-LOT-TEST"
    assert row["num_sales"] == 1
    assert Decimal(row["total_profit"]) > 0

    detail = client.get(f"/lots/{lot_row.id}")
    assert detail.status_code == 200
    dbody = detail.json()
    assert len(dbody["consumptions"]) == 1
    assert dbody["consumptions"][0]["client_name_ar"] == buyer.name_ar
    assert Decimal(dbody["lot"]["total_profit"]) == Decimal(dbody["consumptions"][0]["profit"])


def test_lot_detail_unknown_id_404(db, client):
    _login(db, client)
    resp = client.get("/lots/999999999")
    assert resp.status_code == 404
