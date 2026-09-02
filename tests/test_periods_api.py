"""اختبارات إقفال الفترات الشهرية وفتحها + الفترة التأسيسية
(`app/engine/periods.py`، `app/routers/periods.py`، §٩ المرحلة ١١).

يتحقق أن `close_period` عبر HTTP فعلياً تُنشئ صف `Period` الذي تقرأه بوابة
الأثر الرجعي القائمة في `posting._check_backdate_gate` (اختبار القبول ٢٦،
مبنية منذ مرحلة سابقة) — لا إعادة اختبار تلك البوابة نفسها، فقط أن هذه
المرحلة تُفعِّلها فعلياً بدل إنشاء صف `Period` يدوياً كما كانت الاختبارات
القديمة تفعل.
"""

from __future__ import annotations

from datetime import date
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
    return {"X-CSRF-Token": token}


def test_accountant_cannot_close_or_reopen_period(db, client, now):
    _login(db, client, role="ACCOUNTANT")
    resp = client.post("/periods/close", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert resp.status_code == 403
    resp2 = client.post("/periods/reopen", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert resp2.status_code == 403


def test_close_period_then_reopen_full_cycle(db, client, now):
    admin = _login(db, client, role="ADMIN")
    resp = client.post("/periods/close", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_closed"] is True
    assert body["closed_by_username"] == admin.username

    listing = client.get("/periods")
    assert listing.status_code == 200
    row = next(r for r in listing.json() if r["year"] == now.year and r["month"] == now.month)
    assert row["is_closed"] is True

    # إقفال ثانٍ لنفس الفترة → تضارب صريح، لا نجاح صامت
    dup = client.post("/periods/close", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert dup.status_code == 409

    reopened = client.post("/periods/reopen", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert reopened.status_code == 200
    assert reopened.json()["is_closed"] is False

    # فتح فترة غير مُقفلة أصلاً → تضارب صريح
    reopen_again = client.post("/periods/reopen", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert reopen_again.status_code == 409


def test_close_period_actually_activates_backdate_gate(db, client, now):
    """التكامل الحقيقي: `close_period` عبر HTTP تُنشئ صف Period، والبوابة
    القائمة في `posting.py` (اختبار القبول ٢٦) تقرؤه فعلاً وتُفعَّل — لا
    حاجة لإنشاء الصف يدوياً كما كانت الاختبارات القديمة تفعل."""
    admin = _login(db, client, role="ADMIN")
    from app.models import FoundingPeriod

    founding = db.get(FoundingPeriod, 1)
    founding.is_open = False
    db.flush()

    resp = client.post("/periods/close", json={"year": now.year, "month": now.month}, headers=_headers(client))
    assert resp.status_code == 200

    from app.engine import posting
    from app.engine.posting import BackdatedEntryRequiresAdminError

    accountant = f.make_user(db, role="ACCOUNTANT")
    client_row = f.make_client(db)
    with pytest.raises(BackdatedEntryRequiresAdminError):
        f.fund_client(
            db, client=client_row, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
            receiving_account_code="1101", user=accountant, now=now, idempotency_key=f.uid(),
        )


def test_founding_period_status_and_close_requires_acknowledgment(db, client, now):
    admin = _login(db, client, role="ADMIN")
    status_resp = client.get("/periods/founding")
    assert status_resp.status_code == 200
    assert status_resp.json()["is_open"] is True

    # فروق تأسيسية حقيقية غير صفرية (٣٩٠٠) عبر رصيد افتتاحي بثقة منخفضة
    from app.engine.operations import opening_balance as opening_op
    from app.models.enums import ConfidenceLevel, OpeningSourceType

    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    opening_op.execute(
        db, account_code=box.code, currency_code="LYD", amount=Decimal("777.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.LOW,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )

    status_resp2 = client.get("/periods/founding")
    assert status_resp2.json()["suspense_balance_by_currency"].get("LYD") == "777.000"

    without_ack = client.post("/periods/founding/close", json={}, headers=_headers(client))
    assert without_ack.status_code == 422

    with_ack = client.post(
        "/periods/founding/close", json={"acknowledged_remaining_suspense": True}, headers=_headers(client)
    )
    assert with_ack.status_code == 200
    assert with_ack.json()["is_open"] is False

    already_closed = client.post(
        "/periods/founding/close", json={"acknowledged_remaining_suspense": True}, headers=_headers(client)
    )
    assert already_closed.status_code == 409


def test_period_close_and_founding_close_write_audit_log(db, client, now):
    admin = _login(db, client, role="ADMIN")
    client.post("/periods/close", json={"year": now.year, "month": now.month}, headers=_headers(client))

    from sqlalchemy import select

    from app.models import AuditLog

    row = db.execute(
        select(AuditLog).where(AuditLog.action == "PERIOD_CLOSED", AuditLog.actor_id == admin.id)
    ).scalar_one_or_none()
    assert row is not None
    assert row.after_json == {"year": now.year, "month": now.month}
