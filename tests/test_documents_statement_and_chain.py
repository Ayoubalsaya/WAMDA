"""اختبارات كشف الحساب (عميل/أساسي) وملخص السلسلة وبطاقة أرصدة المراسلين
(`app/documents/statement.py`، `app/documents/reports_doc.py`، §٨)."""

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


def test_client_statement_pdf_shows_running_balance(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل كشف حساب فريد جداً")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("1000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("250.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/documents/statement/client/{c.id}.pdf?currency=LYD&location=TRIPOLI")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")

    from app.documents.statement import build_client_statement_context

    ctx = build_client_statement_context(
        db, client_id=c.id, currency="LYD", location="TRIPOLI", doc_size="a4",
        date_from=None, date_to=None, now=now, work_timezone=WORK_TZ,
    )
    assert len(ctx["rows"]) == 2
    assert ctx["closing_balance"] == "1250.000"


def test_client_statement_pdf_never_contains_cost_rate(db, client, now):
    """فحص فعلي على الملف المولَّد نفسه (استخراج نص PDF حقيقي عبر pypdf،
    لا HTML وسيط ولا بايتات خام قد تكون مضغوطة) — كشف حساب عميل يمرّ به
    قيد EXCHANGE حقيقي بـcost_rate مميَّز، ويجب ألا يظهر في الملف إطلاقاً."""
    user = _login(db, client)
    c = f.make_client(db, name="عميل كشف حساب فحص تكلفة فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("2000.000"), cost_rate=Decimal("5.37"), client_rate=Decimal("5.42"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    resp = client.get(f"/documents/statement/client/{c.id}.pdf?currency=LYD&location=TRIPOLI")
    assert resp.status_code == 200

    from pypdf import PdfReader
    import io as _io

    pdf_text = "".join(page.extract_text() for page in PdfReader(_io.BytesIO(resp.content)).pages)
    assert "5.37" not in pdf_text
    # سلامة الفحص نفسه: رقم حقيقي آخر من نفس الكشف يجب أن يظهر فعلاً
    assert "2000.000" in pdf_text


def test_client_statement_404_unknown_client(db, client):
    _login(db, client)
    resp = client.get("/documents/statement/client/999999999.pdf?currency=LYD&location=TRIPOLI")
    assert resp.status_code == 404


def test_account_statement_pdf_for_system_box_account(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل كشف حساب أساسي فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("400.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/documents/statement/account/1101.pdf")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


def test_account_statement_404_unknown_code(db, client):
    _login(db, client)
    resp = client.get("/documents/statement/account/NOPE-9999.pdf")
    assert resp.status_code == 404


def test_chain_summary_lists_both_steps_in_order(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل سلسلة فريد جداً")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    chain_ref = f.uid()
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.00"), client_rate=Decimal("5.15"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=1, chain_total=2,
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY", to_location_code="CHINA",
        amount=Decimal("100.000"), cost_rate=Decimal("6.95"), client_rate=Decimal("6.90"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=2, chain_total=2,
    )
    resp = client.get(f"/documents/chain-summary/{chain_ref}.pdf")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")

    from app.documents.reports_doc import build_chain_summary_context

    ctx = build_chain_summary_context(db, chain_ref=chain_ref, doc_size="a4", now=now, work_timezone=WORK_TZ)
    assert len(ctx["rows"]) == 2
    assert ctx["rows"][0][0] == "1/2"
    assert ctx["rows"][1][0] == "2/2"


def test_correspondent_balances_report_pdf(db, client, now):
    user = _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    c = f.make_client(db, name="عميل مراسلين فريد")
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("777.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    resp = client.get("/documents/reports/correspondent-balances.pdf")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
