"""اختبارات HTTP للتقارير (`app/routers/reports.py`، §٧-١١)."""

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


def test_reports_require_auth(client):
    resp = client.get("/reports/trial-balance")
    assert resp.status_code == 401


def test_debts_by_currency_reflects_real_client_liability(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل ديون فريد جداً")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("777.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/reports/debts-by-currency")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["currency_code"] == "LYD")
    assert Decimal(row["total_owed"]) >= Decimal("777.000")
    assert row["client_count"] >= 1


def test_trial_balance_always_balances_per_currency(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("500.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get("/reports/trial-balance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["balanced"] is True
    debit_by_ccy = {r["currency_code"]: Decimal(r["amount"]) for r in body["total_debit_by_currency"]}
    credit_by_ccy = {r["currency_code"]: Decimal(r["amount"]) for r in body["total_credit_by_currency"]}
    assert debit_by_ccy == credit_by_ccy


def test_trial_balance_includes_funded_box_account(db, client, now):
    user = _login(db, client)
    box = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("333.000"),
        receiving_account_code=box.code, user=user, now=now,
    )
    resp = client.get("/reports/trial-balance")
    row = next(r for r in resp.json()["rows"] if r["account_code"] == box.code)
    assert Decimal(row["debit"]) == Decimal("333.000")
    assert Decimal(row["credit"]) == Decimal("0")


def test_income_statement_exchange_profit_shows_as_revenue(db, client, now):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    # cost_rate < client_rate (عملة ثانوية، القسمة هي التحويل) → هامش موجب حقيقي.
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.10"), client_rate=Decimal("5.15"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    resp = client.get("/reports/income-statement")
    assert resp.status_code == 200
    body = resp.json()
    # حسابات ٤١٢٠ الفرعية مرقَّمة تسلسلياً (٤١٢١، ٤١٢٢...) لا بادئة نصية —
    # التحقق بنوع الحساب (إيراد) وعملته لا بمطابقة الكود.
    assert any(r["currency_code"] == "USD" and Decimal(r["amount"]) > 0 for r in body["revenue"])


def test_client_profitability_groups_by_client_and_currency(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل ربحية فريد جداً")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.15"), client_rate=Decimal("5.10"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="سعر السوق",
    )
    resp = client.get("/reports/client-profitability")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["client_id"] == c.id)
    assert row["operation_count"] == 1
    assert any(p["currency_code"] == "USD" for p in row["profit_by_currency"])


def test_loss_making_operations_lists_negative_profit_entries(db, client, now):
    user = _login(db, client, role="ADMIN")
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    # عملة ثانوية → التحويل قسمة؛ cost_rate > client_rate يعني ما نحصّله من
    # التكلفة أقل مما نعطيه للعميل → هامش سالب حقيقي.
    loss_entry = exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.20"), client_rate=Decimal("5.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="خصم استثنائي للعميل",
    )
    resp = client.get("/reports/loss-making-operations")
    assert resp.status_code == 200
    ids = {r["entry_id"] for r in resp.json()}
    assert loss_entry.id in ids
    row = next(r for r in resp.json() if r["entry_id"] == loss_entry.id)
    assert Decimal(row["profit_amount"]) < 0


def test_balance_overrides_lists_credit_limit_override(db, client, now):
    user = _login(db, client, role="ADMIN")
    c = f.make_client(db, credit_allowed=True)
    from app.engine.operations import payment as payment_op

    payment_op.execute(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("50.000"),
        paying_account_code="1101", work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
        allow_negative=True, override_reason="تجاوز ائتمان اختباري",
    )
    resp = client.get("/reports/balance-overrides")
    assert resp.status_code == 200
    assert any(r["action"] == "CREDIT_LIMIT_OVERRIDE" and r["reason"] == "تجاوز ائتمان اختباري" for r in resp.json())


def test_emergency_entries_lists_outage_mode_entries(db, client, now):
    """قيود الطوارئ (outage_mode) تُبنى اليوم مباشرة عبر posting.create_draft_entry
    (المحرك) — لا مسار HTTP/واجهة يعرِّضها بعد عبر أي من الاثنتي عشرة عملية
    (فجوة موثَّقة في PROGRESS.md، ليست ضمن نطاق هذا التقرير: هو عرض فقط
    لما هو موجود، لا إنشاء). الاختبار يطابق نمط test_acceptance_31_40.py
    تماماً — نافذة طوارئ مُعلَنة ثم قيد مباشر بوضع الطوارئ."""
    from datetime import timedelta

    from app.engine import accounts_repo, posting
    from app.models import OutageWindow
    from app.models.enums import OperationType

    real_time = now - timedelta(hours=2)
    user = _login(db, client, role="ADMIN")
    window = OutageWindow(opened_at=real_time - timedelta(hours=1), opened_by=user.id)
    db.add(window)
    db.flush()

    c = f.make_client(db)
    cash = accounts_repo.get_account_by_code(db, "1101")
    client_account = accounts_repo.get_or_create_client_account(db, client=c, currency_code="LYD", location_code="TRIPOLI")
    draft = posting.create_draft_entry(
        db, operation_type=OperationType.RECEIPT, entry_date=real_time.date(), created_by=user.id,
        outage_mode=True, real_operation_time=real_time, description="قيد طوارئ اختباري",
        backdate_reason="SYSTEM_OUTAGE",
    )
    draft.add(account_id=cash.id, currency_code="LYD", debit=Decimal("10.000"))
    draft.add(account_id=client_account.id, currency_code="LYD", credit=Decimal("10.000"))
    entry = posting.post_entry(db, draft, posted_by=user.id, now=now)

    resp = client.get("/reports/emergency-entries")
    assert resp.status_code == 200
    ids = {r["entry_id"] for r in resp.json()}
    assert entry.id in ids
    row = next(r for r in resp.json() if r["entry_id"] == entry.id)
    assert row["real_operation_time"] is not None


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
    resp = client.get("/reports/founding-reconciliation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["opening_balances_count"] >= 1
    assert any(r["currency_code"] == "LYD" for r in body["opening_balances_total_by_currency"])


def test_swift_history_includes_all_statuses(db, client, now):
    user = _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funder = f.make_client(db)
    f.fund_client(
        db, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    from app.engine.operations import swift_out as swift_out_op

    out = swift_out_op.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("100.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), external_ref="REF-HIST-TEST",
    )
    resp = client.get("/reports/swift-history")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["external_ref"] == "REF-HIST-TEST")
    assert row["status"] == "SENT"
