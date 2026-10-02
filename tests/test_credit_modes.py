"""ائتمان بلا سقف (٢٠٢٦-١٠-٠٣): وضع لكل عميل × عملة — المحرك · الإيقاف مع دين قائم · عملة جديدة · رقابة بالرؤية."""

from __future__ import annotations

from decimal import Decimal

import uuid

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.engine import accounts_repo
from app.main import app
from app.models import AccountBalance
from app.security.passwords import hash_password
from tests import factories as f

PASSWORD = "Sup3rSecret!1"


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(db, client, *, role="ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password(PASSWORD)
    user.must_change_password = False
    user.totp_secret = "JBSWY3DPEHPK3PXP"
    db.flush()
    r = client.post("/auth/login", json={"username": user.username, "password": PASSWORD, "totp_code": pyotp.TOTP(user.totp_secret).now()})
    assert r.status_code == 200, r.text
    return user


def _h(client):
    return {"X-CSRF-Token": client.cookies.get("wamda_csrf")}


def _hi(client):
    return {**_h(client), "Idempotency-Key": uuid.uuid4().hex}


def _pay(client, c, amount, ccy="LYD", loc="TRIPOLI"):
    return client.post("/operations/payment", json={
        "client_id": c.id, "currency_code": ccy, "location_code": loc, "amount": amount, "paying_account_code": "1101"}, headers=_hi(client))


def _receipt(client, c, amount, ccy="LYD", loc="TRIPOLI"):
    return client.post("/operations/receipt", json={
        "client_id": c.id, "currency_code": ccy, "location_code": loc, "amount": amount, "receiving_account_code": "1101"}, headers=_hi(client))


def _balance(db, c, ccy="LYD", loc="TRIPOLI"):
    acc = accounts_repo.get_or_create_client_account(db, client=c, currency_code=ccy, location_code=loc)
    return db.get(AccountBalance, acc.id).balance


def _fund_box(db, now, amount="9000000000.000"):
    rich = f.make_client(db)
    f.fund_client(db, client=rich, currency_code="LYD", location_code="TRIPOLI", amount=Decimal(amount),
                  receiving_account_code="1101", user=f.make_user(db), now=now)


def test_unlimited_allows_a_huge_negative_balance_then_stop_rejects_only_new_debt(db, client, now):
    _login(db, client)
    _fund_box(db, now)
    c = f.make_client(db)
    assert _pay(client, c, "100.000").status_code == 409, "عميل جديد بلا ائتمان"
    assert client.put(f"/clients/{c.id}/credit-mode", json={"mode": "UNLIMITED"}, headers=_h(client)).json()["credit_status"] == "OPEN"
    big = _pay(client, c, "5000000000.000")
    assert big.status_code == 201, big.text
    assert _balance(db, c) == Decimal("-5000000000.000")

    stop = client.put(f"/clients/{c.id}/credit-mode", json={"mode": "NONE"}, headers=_h(client)).json()
    assert stop["credit_status"] == "STOPPED"
    debts = [(d["currency_code"], d["balance"]) for d in stop["outstanding_debts"]]
    assert ("LYD", "-5000000000.000000") in debts, "تحذير بالدين القائم لا رفض"
    more = _pay(client, c, "1.000")
    assert more.status_code == 409 and "بلا ائتمان" in more.json()["detail"], more.text
    # تخفيض الدين مسموح (سداد جزئي) ويبقى سالباً
    partial = _receipt(client, c, "1000.000")
    assert partial.status_code == 201, partial.text
    assert _balance(db, c) == Decimal("-4999999000.000")


def test_unlimited_in_one_currency_does_not_open_another(db, client, now):
    _login(db, client)
    _fund_box(db, now)
    c = f.make_client(db)
    client.put(f"/clients/{c.id}/credit-limits/LYD", json={"mode": "UNLIMITED"}, headers=_h(client))
    assert _pay(client, c, "10.000").status_code == 201
    assert client.get(f"/clients/{c.id}").json()["credit_status"] == "PARTIAL"
    # USD لم تُفعَّل: غياب الصف = بلا ائتمان
    rich = f.make_client(db)
    f.fund_client(db, client=rich, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"),
                  receiving_account_code="1104", user=f.make_user(db), now=now)
    usd_box = "1104"
    usd = client.post("/operations/payment", json={
        "client_id": c.id, "currency_code": "USD", "location_code": "TRIPOLI", "amount": "1.00", "paying_account_code": usd_box}, headers=_hi(client))
    assert usd.status_code == 409 and "بلا ائتمان" in usd.json()["detail"], usd.text


def test_limit_mode_still_enforces_and_override_path_remains(db, client, now):
    _login(db, client)
    _fund_box(db, now)
    c = f.make_client(db)
    f.set_credit_limit(db, c, "LYD", Decimal("100.000"))
    assert _pay(client, c, "80.000").status_code == 201
    over = _pay(client, c, "50.000")
    assert over.status_code == 409 and "تجاوز حد ائتمان" in over.json()["detail"]


def test_debtors_report_lists_every_negative_balance_biggest_first_with_last_activity(db, client, now):
    _login(db, client)
    _fund_box(db, now)
    small, large = f.make_client(db, name=f"مدين صغير {f.uid()}"), f.make_client(db, name=f"مدين كبير {f.uid()}")
    for c in (small, large):
        client.put(f"/clients/{c.id}/credit-mode", json={"mode": "UNLIMITED"}, headers=_h(client))
    assert _pay(client, small, "10.000").status_code == 201
    assert _pay(client, large, "7000.000").status_code == 201
    rows = client.get("/reports/debtors").json()
    mine = [r for r in rows if r["client_id"] in (small.id, large.id)]
    assert [r["client_id"] for r in mine] == [large.id, small.id], "الأكبر أولاً"
    assert mine[0]["debt"] == "7000.000000" and mine[0]["currency_code"] == "LYD" and mine[0]["location_code"] == "TRIPOLI"
    assert mine[0]["credit_mode"] == "UNLIMITED" and mine[0]["last_activity"]
    assert client.get("/documents/reports/debtors.xlsx").status_code == 200
    # الدين الذي سُدّد كلياً يخرج من التقرير
    assert _receipt(client, small, "10.000").status_code == 201
    assert small.id not in [r["client_id"] for r in client.get("/reports/debtors").json()]


def test_dashboard_total_client_debts_per_currency(db, client, now):
    _login(db, client)
    _fund_box(db, now)
    c = f.make_client(db)
    client.put(f"/clients/{c.id}/credit-mode", json={"mode": "UNLIMITED"}, headers=_h(client))
    before = {d["currency_code"]: Decimal(d["amount"]) for d in client.get("/dashboard/summary").json()["kpis"]["client_debts"]}
    r = _pay(client, c, "250.000")
    assert r.status_code == 201, r.text
    after = {d["currency_code"]: Decimal(d["amount"]) for d in client.get("/dashboard/summary").json()["kpis"]["client_debts"]}
    assert after["LYD"] - before.get("LYD", Decimal("0")) == Decimal("250.000")
    alerts = client.get("/dashboard/summary").json()["alerts"]
    assert not [a for a in alerts if a["code"] == "credit_exceeded" and c.code in a["message_ar"]], "بلا سقف: لا تنبيه تجاوز"


def test_migration_semantics_check_constraints(db):
    """الوضع صريح: LIMIT يلزمه مبلغ، وغيره بلا مبلغ — القيد في القاعدة لا في التطبيق وحده."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    c = f.make_client(db)
    for bad in ("'LIMIT', NULL", "'LIMIT', 0", "'LIMIT', -5", "'UNLIMITED', 5", "'NONE', 1", "'WHATEVER', NULL"):
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.execute(text(f"INSERT INTO client_credit_limits (client_id, currency_code, mode, limit_amount) VALUES ({c.id}, 'LYD', {bad})"))
    assert db.execute(select(AccountBalance).limit(0)).all() == []
