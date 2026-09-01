"""اختبارات مستندات التقارير الداخلية (`app/documents/reports_doc.py`،
`app/routers/documents.py`، §٨) — سبعة تقارير، كلها فوق القالب المشترك
`report_table.html`. بيانات حقيقية (رصيد/دفعة/تجاوز حقيقي)، بايتات
PDF/PNG حقيقية مفحوصة لا نجاح استدعاء فقط.
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

_REPORT_KEYS = [
    "trial-balance", "founding-reconciliation", "balance-overrides", "emergency-entries",
    "monthly-profit", "lot-profitability", "liquidity-position",
]


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


@pytest.mark.parametrize("report_key", _REPORT_KEYS)
def test_report_pdf_is_real_pdf(db, client, now, report_key):
    user = _login(db, client)
    c = f.make_client(db, name=f"عميل تقرير {report_key} فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("321.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/documents/reports/{report_key}.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 1500


def test_unknown_report_key_404(db, client):
    _login(db, client)
    resp = client.get("/documents/reports/not-a-real-report.pdf")
    assert resp.status_code == 404


def test_trial_balance_pdf_includes_funded_account_row(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل ميزان مراجعة فريد جداً")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("456.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.documents.reports_doc import build_trial_balance_context

    ctx = build_trial_balance_context(db, doc_size="a4", now=now, work_timezone=WORK_TZ)
    joined = "\n".join(" ".join(row) for row in ctx["rows"])
    assert "عميل ميزان مراجعة فريد جداً" in joined


def test_founding_reconciliation_reflects_opening_balance(db, client, now):
    user = _login(db, client, role="ADMIN")
    from app.engine.operations import opening_balance as opening_op
    from app.models.enums import ConfidenceLevel, OpeningSourceType

    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    opening_op.execute(
        db, account_code=box.code, currency_code="LYD", amount=Decimal("1000.000"), is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.LOW,
        approved_by=user.id, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    from app.documents.reports_doc import build_founding_reconciliation_context

    ctx = build_founding_reconciliation_context(db, doc_size="a4", now=now, work_timezone=WORK_TZ)
    assert any("LYD" in item["k"] for s in ctx["summary"] for item in s["lines"])
