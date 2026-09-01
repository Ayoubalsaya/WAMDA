"""اختبارات إيصال العملية (`app/documents/receipt.py`، `app/routers/documents.py`، §٨).

يشغّل `TestClient(app)` محرك التوليد الحقيقي عبر lifespan (Playwright/
Chromium فعلي — لا محاكاة)، فكل اختبار هنا يفحص **بايتات PDF/PNG حقيقية**
لا مجرد نجاح الاستدعاء.
"""

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


def test_receipt_requires_auth(client):
    resp = client.get("/documents/receipt/1.pdf")
    assert resp.status_code == 401


def test_receipt_pdf_a4_is_real_pdf_with_embedded_font(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل إيصال فريد جداً")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("777.500"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/documents/receipt/{entry.id}.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 2000
    # الخط مضمَّن فعلاً — لا نص عادي، بايتات glyph حقيقية (FontFile)
    assert b"/FontFile" in resp.content
    assert b"IBMPlexSansArabic" in resp.content


def test_receipt_pdf_thermal_uses_80mm_page_size(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل حراري فريد جداً")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/documents/receipt/{entry.id}.pdf?size=thermal")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


def test_receipt_png_is_real_image(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل PNG فريد جداً")
    entry = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/documents/receipt/{entry.id}.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_receipt_shows_balance_before_and_after(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل رصيد قبل وبعد فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("1000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry2 = f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.documents.receipt import build_receipt_context

    ctx = build_receipt_context(db, entry_id=entry2.id, doc_size="a4", now=now, work_timezone=WORK_TZ)
    balance = next(b for b in ctx["balances"] if b["currency_code"] == "LYD")
    assert balance["before"] == Decimal("1000.000")
    assert balance["after"] == Decimal("1500.000")


def test_receipt_never_contains_cost_rate(db, client, now):
    """cost_rate لا يُقرأ أصلاً في `build_receipt_context` — يُفحَص هنا على
    مستوى الـHTML المولَّد فعلياً، لا على افتراض الكود (نفس مبدأ اختبار
    القبول ٤١ للبوابة، المرحلة ٩)."""
    user = _login(db, client)
    c = f.make_client(db, name="عميل صرافة فريد لفحص التكلفة")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    entry = exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.10"), client_rate=Decimal("5.15"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    from app.documents.common import base_context
    from app.documents.jinja import render_template
    from app.documents.receipt import build_receipt_context

    ctx = build_receipt_context(db, entry_id=entry.id, doc_size="a4", now=now, work_timezone=WORK_TZ)
    ctx["qr_data_uri"] = None
    html = render_template("receipt.html", **ctx)
    assert "5.10" not in html
    assert "cost_rate" not in html.lower()


def test_receipt_remit_out_shows_destination_snapshot(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل إرسال فريد")
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    beneficiary = f.make_beneficiary(db, c, currency_code="CNY")
    from app.engine.operations import remit_out as remit_out_op

    entry = remit_out_op.execute(
        db, client=c, from_location_code="TURKEY", partner_account_code=partner_acct.code,
        beneficiary=beneficiary, beneficiary_amount=Decimal("690.00"), cost_rate=Decimal("6.90"),
        client_rate=Decimal("6.80"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    resp = client.get(f"/documents/receipt/{entry.id}.pdf")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")

    from app.documents.receipt import build_receipt_context

    ctx = build_receipt_context(db, entry_id=entry.id, doc_size="a4", now=now, work_timezone=WORK_TZ)
    assert ctx["destination"] is not None
    assert ctx["destination"]["beneficiary_name"] == beneficiary.name
    assert ctx["destination"]["account_number"] == beneficiary.account_number


def test_receipt_404_for_unknown_entry(db, client):
    _login(db, client)
    resp = client.get("/documents/receipt/999999999.pdf")
    assert resp.status_code == 404


def test_receipt_422_for_entry_without_client(db, client, now):
    user = _login(db, client, role="ADMIN")
    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    from app.engine.operations import opening_balance as opening_op
    from app.models.enums import ConfidenceLevel, OpeningSourceType

    entry = opening_op.execute(
        db, account_code=box.code, currency_code="LYD", amount=Decimal("1000.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.LOW,
        approved_by=user.id, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    resp = client.get(f"/documents/receipt/{entry.id}.pdf")
    assert resp.status_code == 422
