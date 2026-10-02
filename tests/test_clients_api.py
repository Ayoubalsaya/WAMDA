"""اختبارات HTTP فعلية لشاشات العملاء (§٧-٥) — `app/routers/clients.py`."""

from __future__ import annotations

from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
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
    resp = client.post(
        "/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code}
    )
    assert resp.status_code == 200
    return user


def _headers(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token}


def test_list_clients_requires_auth(client):
    resp = client.get("/clients")
    assert resp.status_code == 401


def test_create_client_by_accountant_succeeds(db, client):
    _login(db, client, role="ACCOUNTANT")
    resp = client.post(
        "/clients", json={"code": f"C-{f.uid()}", "name_ar": "عميل اختبار API"}, headers=_headers(client)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["credit_status"] == "STOPPED"  # عميل جديد: بلا ائتمان في كل العملات
    assert body["balances"] == []


def test_create_client_duplicate_code_conflict(db, client):
    _login(db, client)
    code = f"C-{f.uid()}"
    resp1 = client.post("/clients", json={"code": code, "name_ar": "الأول"}, headers=_headers(client))
    assert resp1.status_code == 201
    resp2 = client.post("/clients", json={"code": code, "name_ar": "الثاني"}, headers=_headers(client))
    assert resp2.status_code == 409


def test_get_client_detail_includes_balances_and_limits(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("400.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    f.set_credit_limit(db, c, "USD", Decimal("1000.00"))
    resp = client.get(f"/clients/{c.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == c.code
    balances = {b["currency_code"]: b["balance"] for b in body["balances"]}
    assert balances["LYD"] == "400.000000"
    limits = {l["currency_code"]: l["limit_amount"] for l in body["credit_limits"]}
    assert limits["USD"] == "1000.000000" and limits["LYD"] is None


def test_get_client_unknown_404(db, client):
    _login(db, client)
    resp = client.get("/clients/999999999")
    assert resp.status_code == 404


def test_update_client_basic_info(db, client):
    _login(db, client)
    c = f.make_client(db)
    resp = client.patch(f"/clients/{c.id}", json={"phone": "0910000000"}, headers=_headers(client))
    assert resp.status_code == 200, resp.text
    assert resp.json()["phone"] == "0910000000"


def test_set_credit_mode_requires_admin(db, client):
    _login(db, client, role="ACCOUNTANT")
    c = f.make_client(db)
    resp = client.put(f"/clients/{c.id}/credit-mode", json={"mode": "UNLIMITED"}, headers=_headers(client))
    assert resp.status_code == 403


def test_credit_mode_unlimited_then_none_applies_to_every_currency_with_one_audit_row(db, client):
    from sqlalchemy import select

    from app.models import AuditLog

    _login(db, client, role="ADMIN")
    c = f.make_client(db)
    f.set_credit_limit(db, c, "USD", Decimal("10000"))  # حد مخصص سيُستبدل
    resp = client.put(f"/clients/{c.id}/credit-mode", json={"mode": "UNLIMITED"}, headers=_headers(client))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["credit_status"] == "OPEN" and body["outstanding_debts"] == []
    assert body["credit_limits"] and all(l["mode"] == "UNLIMITED" and l["limit_amount"] is None for l in body["credit_limits"])
    rows = db.execute(select(AuditLog).where(AuditLog.action == "CLIENT_CREDIT_MODE_CHANGED", AuditLog.entity_id == c.id)).scalars().all()
    assert len(rows) == 1, "إجراء تدقيق واحد لكل العملات"
    before = {x["currency_code"]: x for x in rows[0].before_json["currencies"]}
    after = {x["currency_code"]: x for x in rows[0].after_json["currencies"]}
    assert before["USD"] == {"currency_code": "USD", "mode": "LIMIT", "limit_amount": "10000.000000"}
    assert set(before) == set(after) and all(x["mode"] == "UNLIMITED" for x in after.values())
    assert rows[0].after_json["credit_status"] == "OPEN" and rows[0].before_json["credit_status"] == "PARTIAL"
    stop = client.put(f"/clients/{c.id}/credit-mode", json={"mode": "NONE"}, headers=_headers(client)).json()
    assert stop["credit_status"] == "STOPPED" and all(l["mode"] == "NONE" for l in stop["credit_limits"])


def test_status_is_partial_for_a_custom_limit_and_for_a_currency_added_later(db, client):
    from app.models import Currency

    _login(db, client, role="ADMIN")
    c = f.make_client(db)
    client.put(f"/clients/{c.id}/credit-mode", json={"mode": "UNLIMITED"}, headers=_headers(client))
    assert client.get(f"/clients/{c.id}").json()["credit_status"] == "OPEN"
    client.put(f"/clients/{c.id}/credit-limits/USD", json={"mode": "LIMIT", "limit_amount": "500"}, headers=_headers(client))
    assert client.get(f"/clients/{c.id}").json()["credit_status"] == "PARTIAL"
    client.put(f"/clients/{c.id}/credit-limits/USD", json={"mode": "UNLIMITED"}, headers=_headers(client))
    assert client.get(f"/clients/{c.id}").json()["credit_status"] == "OPEN"
    db.add(Currency(code="ZZT", name_ar="عملة لاحقة", symbol="Z", decimals=2, is_active=True, sort_order=99))
    db.flush()
    assert client.get(f"/clients/{c.id}").json()["credit_status"] == "PARTIAL", "عملة جديدة لا تُفعَّل تلقائياً"


def test_set_credit_limit_modes_and_validation(db, client):
    _login(db, client, role="ADMIN")
    c = f.make_client(db)
    resp = client.put(f"/clients/{c.id}/credit-limits/USD", json={"limit_amount": "2500.00"}, headers=_headers(client))
    assert resp.status_code == 204, resp.text
    limits = {l["currency_code"]: l for l in client.get(f"/clients/{c.id}").json()["credit_limits"]}
    assert limits["USD"]["mode"] == "LIMIT" and limits["USD"]["limit_amount"] == "2500.000000"
    assert limits["LYD"]["mode"] == "NONE" and limits["LYD"]["limit_amount"] is None  # غير مفعَّلة

    resp2 = client.put(f"/clients/{c.id}/credit-limits/USD", json={"limit_amount": "5000.00"}, headers=_headers(client))
    assert resp2.status_code == 204  # upsert
    assert client.put(f"/clients/{c.id}/credit-limits/USD", json={"mode": "LIMIT"}, headers=_headers(client)).status_code == 422
    assert client.put(f"/clients/{c.id}/credit-limits/USD", json={"mode": "UNLIMITED"}, headers=_headers(client)).status_code == 204
    limits = {l["currency_code"]: l for l in client.get(f"/clients/{c.id}").json()["credit_limits"]}
    assert limits["USD"]["mode"] == "UNLIMITED" and limits["USD"]["limit_amount"] is None


def test_list_clients_reflects_balance_and_last_activity(db, client, now):
    _login(db, client)
    c = f.make_client(db, name=f"عميل قائمة {f.uid()}")
    entry = f.fund_client(
        db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("250.00"),
        receiving_account_code="1104", user=f.make_user(db), now=now,
    )
    resp = client.get(f"/clients?q={c.code}")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == c.id)
    balances = {b["currency_code"]: b["balance"] for b in row["balances"]}
    assert balances["USD"] == "250.000000"
    assert row["last_activity"] == entry.entry_date.isoformat()


def test_client_statement_running_balance_and_no_cost_rate_leak(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.get(f"/clients/{c.id}/statement?currency=LYD&location=TRIPOLI")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["opening_balance"] == "0"
    assert len(body["rows"]) == 2
    assert body["rows"][0]["running_balance"] == "100.000000"
    assert body["rows"][1]["running_balance"] == "150.000000"
    assert body["closing_balance"] == "150.000000"
    assert "cost_rate" not in resp.text  # القاعدة الصارمة: لا سعر تكلفة في أي شيء يخص العميل


def test_client_statement_date_filter_and_opening_balance(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    first = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.get(
        f"/clients/{c.id}/statement?currency=LYD&location=TRIPOLI&from={first.entry_date.isoformat()}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["opening_balance"] == "0"
    assert len(body["rows"]) == 1


def test_client_statement_unknown_account_returns_empty(db, client):
    _login(db, client)
    c = f.make_client(db)
    resp = client.get(f"/clients/{c.id}/statement?currency=CNY&location=CHINA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == []
    assert body["opening_balance"] == "0"


