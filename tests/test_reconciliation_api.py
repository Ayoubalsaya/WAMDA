"""اختبارات HTTP للمطابقة (`app/routers/reconciliation.py`، §٧-٩)."""

from __future__ import annotations

import uuid
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


def _login(db, client: TestClient, *, role: str = "ADMIN"):
    user = f.make_user(db, role=role)
    user.password_hash = hash_password("Sup3rSecret!1")
    user.must_change_password = False
    user.totp_secret = pyotp.random_base32()
    db.flush()
    code = pyotp.TOTP(user.totp_secret).now()
    resp = client.post("/auth/login", json={"username": user.username, "password": "Sup3rSecret!1", "totp_code": code})
    assert resp.status_code == 200
    return user


def _headers(client: TestClient) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    return {"X-CSRF-Token": token, "Idempotency-Key": uuid.uuid4().hex}


def test_accountant_cannot_reconcile(db, client):
    _login(db, client, role="ACCOUNTANT")
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    resp = client.post(
        "/reconciliation/statements",
        json={"partner_id": partner_acct.partner_id, "period_from": "2026-06-01", "period_to": "2026-06-30",
              "lines": [{"value_date": "2026-06-10", "description": "x", "amount": "100.00"}]},
        headers=_headers(client),
    )
    assert resp.status_code == 403


def test_create_statement_and_list(db, client):
    _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    resp = client.post(
        "/reconciliation/statements",
        json={"partner_id": partner_acct.partner_id, "period_from": "2026-06-01", "period_to": "2026-06-30",
              "lines": [
                  {"value_date": "2026-06-10", "description": "دفعة أولى", "amount": "1000.00"},
                  {"value_date": "2026-06-15", "description": "دفعة ثانية", "amount": "500.00"},
              ]},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["lines"]) == 2
    assert all(ln["status"] == "OPEN" for ln in body["lines"])

    listing = client.get("/reconciliation/statements")
    assert listing.status_code == 200
    row = next(r for r in listing.json() if r["id"] == body["id"])
    assert row["total_lines"] == 2
    assert row["open_lines"] == 2


def test_auto_match_finds_unambiguous_amount_within_date_tolerance(db, client, now):
    user = _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funder = f.make_client(db)
    entry = f.fund_client(
        db, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("1000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    stmt = client.post(
        "/reconciliation/statements",
        json={"partner_id": partner_acct.partner_id, "period_from": now.date().isoformat(), "period_to": now.date().isoformat(),
              "lines": [{"value_date": now.date().isoformat(), "description": "قيد مطابق", "amount": "1000.00"}]},
        headers=_headers(client),
    ).json()

    result = client.post(f"/reconciliation/statements/{stmt['id']}/auto-match", headers=_headers(client))
    assert result.status_code == 200
    body = result.json()
    assert body["matched_count"] == 1
    line = body["statement"]["lines"][0]
    assert line["status"] == "RESOLVED"
    assert line["matched_entry_id"] == entry.id
    assert line["matched_entry_no"] == entry.entry_no


def test_auto_match_leaves_unmatched_amount_open(db, client, now):
    _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    stmt = client.post(
        "/reconciliation/statements",
        json={"partner_id": partner_acct.partner_id, "period_from": now.date().isoformat(), "period_to": now.date().isoformat(),
              "lines": [{"value_date": now.date().isoformat(), "description": "لا مقابل له", "amount": "9999.99"}]},
        headers=_headers(client),
    ).json()

    result = client.post(f"/reconciliation/statements/{stmt['id']}/auto-match", headers=_headers(client))
    body = result.json()
    assert body["matched_count"] == 0
    assert body["statement"]["lines"][0]["status"] == "OPEN"


def test_manual_match_and_resolve(db, client, now):
    user = _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funder = f.make_client(db)
    entry = f.fund_client(
        db, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("250.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    stmt = client.post(
        "/reconciliation/statements",
        json={"partner_id": partner_acct.partner_id, "period_from": now.date().isoformat(), "period_to": now.date().isoformat(),
              "lines": [{"value_date": now.date().isoformat(), "description": "فرق يدوي", "amount": "300.00"}]},
        headers=_headers(client),
    ).json()
    line_id = stmt["lines"][0]["id"]

    matched = client.patch(
        f"/reconciliation/statements/{stmt['id']}/lines/{line_id}/match",
        json={"entry_id": entry.id}, headers=_headers(client),
    )
    assert matched.status_code == 200
    assert matched.json()["status"] == "RESOLVED"
    assert matched.json()["matched_entry_id"] == entry.id

    resolved = client.patch(
        f"/reconciliation/statements/{stmt['id']}/lines/{line_id}/resolve",
        json={}, headers=_headers(client),
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"


def test_unknown_statement_404(db, client):
    _login(db, client)
    resp = client.get("/reconciliation/statements/999999999")
    assert resp.status_code == 404
