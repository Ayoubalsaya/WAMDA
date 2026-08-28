"""اختبارات HTTP لبيانات المرجع القابلة للقراءة فقط — `app/routers/reference.py`."""

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


def test_reference_endpoints_require_authentication(client):
    for path in ["/reference/currencies", "/reference/locations", "/reference/accounts",
                 "/reference/client-currency-locations", "/clients/search?q=a", "/journal/entries"]:
        resp = client.get(path)
        assert resp.status_code == 401, path


def test_list_currencies(db, client):
    _login(db, client)
    resp = client.get("/reference/currencies")
    assert resp.status_code == 200
    codes = {c["code"] for c in resp.json()}
    assert {"LYD", "USD", "CNY"} <= codes


def test_list_locations(db, client):
    _login(db, client)
    resp = client.get("/reference/locations")
    assert resp.status_code == 200
    codes = {l["code"] for l in resp.json()}
    assert {"TRIPOLI", "BENGHAZI", "LIBYA_BANK", "TURKEY", "CHINA"} <= codes


def test_client_currency_locations_matches_whitelist(db, client):
    _login(db, client)
    resp = client.get("/reference/client-currency-locations")
    assert resp.status_code == 200
    pairs = {(r["currency_code"], r["location_code"]) for r in resp.json()}
    assert ("CNY", "CHINA") in pairs
    assert ("LYD", "TURKEY") not in pairs  # ليست ضمن التركيبات المسموحة (§٢-٢)


def test_list_accounts_excludes_client_accounts_and_rollups(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.get("/reference/accounts")
    assert resp.status_code == 200
    codes = {a["code"] for a in resp.json()}
    assert "1101" in codes  # ورقة قابلة للترحيل
    assert "1000" not in codes  # رأس تجميع (له أبناء)
    assert not any(a["code"].startswith(f"2100-{c.code}-") for a in resp.json())  # حساب عميل مُشتق


def test_client_search_by_name_and_code(db, client):
    _login(db, client)
    c = f.make_client(db, name="أحمد التجاري")
    resp = client.get(f"/clients/search?q={c.code}")
    assert resp.status_code == 200
    assert any(row["id"] == c.id for row in resp.json())

    resp2 = client.get("/clients/search?q=أحمد")
    assert any(row["id"] == c.id for row in resp2.json())


def test_client_balances_by_location(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="BENGHAZI", amount=Decimal("200.000"),
        receiving_account_code="1102", user=f.make_user(db), now=now,
    )
    resp = client.get(f"/clients/{c.id}/balances")
    assert resp.status_code == 200
    by_location = {row["location_code"]: Decimal(row["balance"]) for row in resp.json()}
    assert by_location["TRIPOLI"] == Decimal("500.000")
    assert by_location["BENGHAZI"] == Decimal("200.000")


def test_client_balances_unknown_client_404(db, client):
    _login(db, client)
    resp = client.get("/clients/999999999/balances")
    assert resp.status_code == 404


def test_client_beneficiaries(db, client):
    _login(db, client)
    c = f.make_client(db)
    b = f.make_beneficiary(db, c, currency_code="CNY")
    resp = client.get(f"/clients/{c.id}/beneficiaries")
    assert resp.status_code == 200
    assert any(row["id"] == b.id for row in resp.json())


def test_pending_swift_movements_lists_sent_excludes_received(db, client, now):
    from app.engine.operations import swift_in as swift_in_op, swift_out as swift_out_op

    _login(db, client)
    user = f.make_user(db)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    out1 = swift_out_op.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("1000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), external_ref="REF-PENDING",
    )
    out2 = swift_out_op.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("500.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    from sqlalchemy import select as _select
    from app.models import SwiftMovement

    movement2 = db.execute(_select(SwiftMovement).where(SwiftMovement.out_entry_id == out2.id)).scalar_one()
    bank = f.make_bank_account(db, currency_code="USD")
    swift_in_op.execute(
        db, swift_movement_id=movement2.id, total_amount=Decimal("500.00"), fee_amount=Decimal("0.00"),
        receiving_account_code=bank.code, work_timezone=WORK_TZ, created_by=user.id, now=now,
        idempotency_key=f.uid(),
    )

    resp = client.get("/reference/swift-movements/pending")
    assert resp.status_code == 200
    rows = resp.json()
    ids = {r["id"] for r in rows}
    assert movement2.id not in ids  # استُقبلت بالفعل — لا تظهر كمعلَّقة
    pending = next(r for r in rows if r["external_ref"] == "REF-PENDING")
    assert pending["amount"] == "1000.000000"
    assert pending["out_entry_no"] == out1.entry_no
    assert pending["partner_name_ar"] is not None


def test_journal_entries_lists_todays_posted_entries_with_lines(db, client, now):
    _login(db, client)
    c = f.make_client(db)
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("321.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    resp = client.get(f"/journal/entries?date={entry.entry_date.isoformat()}")
    assert resp.status_code == 200
    rows = resp.json()
    matching = next(r for r in rows if r["id"] == entry.id)
    assert matching["operation_type"] == "RECEIPT"
    assert matching["client_name_ar"] == c.name_ar
    assert len(matching["lines"]) == 2
    assert {Decimal(l["debit"]) for l in matching["lines"]} | {Decimal(l["credit"]) for l in matching["lines"]} >= {
        Decimal("321.000")
    }
