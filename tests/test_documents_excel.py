"""§٨ المرحلة ١٣ — تصدير Excel للتقارير والكشوف + الصيغ الناقصة
(بطاقة رصيد PDF · ملخص سلسلة PNG · تقرير أرصدة الصناديق).

Excel يُبنى من **نفس** دالة السياق التي تُغذّي PDF — الاختبار يحمّل الملف
الناتج بـopenpyxl فعلياً ويتحقق من محتواه، لا من نجاح الاستدعاء فقط.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.database import get_db
from app.main import app
from app.security.passwords import hash_password
from tests import factories as f

WORK_TZ = "Africa/Tripoli"
XLSX_MT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

EXCEL_REPORTS = [
    "trial-balance", "founding-reconciliation", "monthly-profit",
    "lot-profitability", "liquidity-position", "boxes-balances",
]


@pytest.fixture()
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    app.dependency_overrides.clear()


def _login(db, client, *, role="ADMIN"):
    u = f.make_user(db, role=role)
    u.password_hash = hash_password("Sup3rSecret!1")
    u.must_change_password = False
    u.totp_secret = pyotp.random_base32()
    db.flush()
    r = client.post("/auth/login", json={
        "username": u.username, "password": "Sup3rSecret!1", "totp_code": pyotp.TOTP(u.totp_secret).now(),
    })
    assert r.status_code == 200
    return u


def _load(content: bytes):
    wb = load_workbook(io.BytesIO(content))
    ws = wb.active
    return ws, ["\t".join(str(c or "") for c in row) for row in ws.iter_rows(values_only=True)]


@pytest.mark.parametrize("report_key", EXCEL_REPORTS)
def test_report_xlsx_is_real_workbook_with_title_and_headers(db, client, now, report_key):
    user = _login(db, client)
    c = f.make_client(db, name=f"عميل إكسل {report_key}")
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("789.000"),
                  receiving_account_code="1101", user=user, now=now)

    r = client.get(f"/documents/reports/{report_key}.xlsx")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(XLSX_MT)

    ws, lines = _load(r.content)
    assert ws.sheet_view.rightToLeft is True
    text = "\n".join(lines)
    assert len(text) > 20  # ليس ملفاً فارغاً


def test_report_xlsx_rejected_for_pdf_only_report(db, client):
    _login(db, client)
    # جدول §٨: تجاوزات الرصيد "PDF" فقط
    assert client.get("/documents/reports/balance-overrides.xlsx").status_code == 404


def test_boxes_balances_all_three_formats(db, client, now):
    user = _login(db, client)
    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    c = f.make_client(db, name="عميل صناديق")
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
                  receiving_account_code=box.code, user=user, now=now)

    assert client.get("/documents/reports/boxes-balances.pdf").content.startswith(b"%PDF")
    assert client.get("/documents/reports/boxes-balances.png").content[:8] == b"\x89PNG\r\n\x1a\n"
    ws, lines = _load(client.get("/documents/reports/boxes-balances.xlsx").content)
    assert any(box.code in ln for ln in lines)


def test_client_statement_xlsx_has_opening_closing_and_rows(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل كشف إكسل")
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("1234.000"),
                  receiving_account_code="1101", user=user, now=now)

    r = client.get(f"/documents/statement/client/{c.id}.xlsx?currency=LYD&location=TRIPOLI")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(XLSX_MT)
    ws, lines = _load(r.content)
    text = "\n".join(lines)
    assert "الرصيد الافتتاحي" in text and "الرصيد الختامي" in text
    assert "الرصيد المتحرك" in text  # ترويسة جدول الحركة


def test_account_statement_xlsx(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل كشف حساب أساسي")
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("42.000"),
                  receiving_account_code="1101", user=user, now=now)
    r = client.get("/documents/statement/account/1101.xlsx")
    assert r.status_code == 200
    ws, lines = _load(r.content)
    assert any("1101" in ln for ln in lines)


def test_balance_card_pdf_and_png_both_work(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل بطاقة صيغتين")
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("77.000"),
                  receiving_account_code="1101", user=user, now=now)
    assert client.get(f"/documents/balance-card/{c.id}.png").content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/documents/balance-card/{c.id}.pdf").content.startswith(b"%PDF")


def test_chain_summary_png(db, client, now):
    from app.engine.operations import exchange as exchange_op

    user = _login(db, client)
    c = f.make_client(db, name="عميل سلسلة PNG فريد")
    f.fund_client(db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("100000.000"),
                  receiving_account_code="1101", user=user, now=now)
    chain_ref = f.uid()
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.00"), client_rate=Decimal("5.15"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=1, chain_total=2,
    )
    r = client.get(f"/documents/chain-summary/{chain_ref}.png")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
