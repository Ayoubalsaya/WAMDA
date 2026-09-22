"""فحص وجود/غياب سعر الصرف عبر كل مستند — لكل مستند يُفحص كلا الاتجاهين
معاً: سعر العميل ظاهر حيث يجب، سعر التكلفة غائب حيث يصل عميلاً وظاهر
حيث لا يصل (المرحلة ١٤ب). كل فحص على نص PDF حقيقي مُستخرَج (`pypdf`)
لا على القاموس الداخلي فقط — القالب نفسه هو ما يصل المستخدم فعلاً.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.engine.operations import exchange as exchange_op
from app.engine.operations import swift_in as swift_in_op
from app.engine.operations import swift_out as swift_out_op
from app.main import app
from app.models import CurrencyLot, SwiftMovement
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


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader
    return "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def test_receipt_shows_client_rate_never_cost_rate(db, client, now):
    """إيصال عملية صرافة — سعر العميل مميَّز يجب أن يظهر، سعر التكلفة
    المميَّز عن عمد يجب ألا يظهر إطلاقاً."""
    user = _login(db, client)
    c = f.make_client(db, name="عميل إيصال سعر فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    entry = exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.311"), client_rate=Decimal("5.377"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="اختبار",
    )
    resp = client.get(f"/documents/receipt/{entry.id}.pdf")
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert "5.377" in text, "سعر العميل غائب عن الإيصال"
    assert "5.311" not in text, "سعر التكلفة ظهر في وثيقة تصل العميل"


def test_client_statement_shows_client_rate(db, client, now):
    """عكس test_client_statement_pdf_never_contains_cost_rate الموجود
    أصلاً (يفحص الغياب) — هنا نفحص الوجود: سعر العميل يجب أن يظهر."""
    user = _login(db, client)
    c = f.make_client(db, name="عميل كشف سعر عميل فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("2000.000"), cost_rate=Decimal("5.222"), client_rate=Decimal("5.288"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="اختبار",
    )
    resp = client.get(f"/documents/statement/client/{c.id}.pdf?currency=LYD&location=TRIPOLI")
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert "5.288" in text
    assert "5.222" not in text


def test_account_statement_shows_cost_rate(db, client, now):
    """كشف حساب أساسي — أي حساب، هنا حساب العميل نفسه بالدولار (المسار
    نفسه يخدم أي كود حساب، لا الصناديق النظامية فقط) — مستند داخلي،
    سعر التكلفة مسموح ويجب أن يظهر فعلاً. EXCHANGE لا يمسّ صندوق ١١٠١
    إطلاقاً (يُعيد تصنيف عملة العميل فقط، لا حركة صندوق فعلية) — لذا
    الحساب المفحوص هنا حساب العميل الذي تمسّه الصرافة فعلاً."""
    from app.engine import accounts_repo

    user = _login(db, client)
    c = f.make_client(db, name="عميل كشف أساسي سعر فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1500.000"), cost_rate=Decimal("5.144"), client_rate=Decimal("5.199"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="اختبار",
    )
    usd_account = accounts_repo.get_or_create_client_account(db, client=c, currency_code="USD", location_code="TRIPOLI")
    resp = client.get(f"/documents/statement/account/{usd_account.code}.pdf")
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert "5.144" in text, "سعر التكلفة غائب عن كشف الحساب الأساسي الداخلي"


def test_correspondent_statement_shows_cost_rate(db, client, now):
    """كشف مراسل — REMIT_OUT هو ما يمسّ حساب المراسل فعلياً بسعرين
    (على خلاف EXCHANGE الذي يمسّ حسابات العميل فقط)، والسعر المستخدم في
    هذه الحركة يجب أن يظهر في كشف حساب ذلك المراسل."""
    user = _login(db, client)
    from app.engine.operations import remit_out as remit_out_op

    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    c = f.make_client(db, name="عميل مراسل سعر فريد")
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TURKEY", amount=Decimal("5000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    remit_out_op.execute(
        db, client=c, from_location_code="TURKEY", partner_account_code=partner_acct.code,
        currency_code="CNY", amount=Decimal("500.00"), cost_rate=Decimal("7.088"), client_rate=Decimal("7.133"),
        work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="اختبار",
    )
    resp = client.get(f"/documents/statement/account/{partner_acct.code}.pdf")
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert "7.088" in text


def test_chain_summary_shows_both_rates_separately_per_step(db, client, now):
    """§٢-٩: السعران منفصلان لكل خطوة، لا سعر مركّب — كلا سعرَي كل خطوة
    مميَّزان يجب أن يظهرا معاً، بلا دمج."""
    user = _login(db, client)
    c = f.make_client(db, name="عميل سلسلة سعرين فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    chain_ref = f.uid()
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.011"), client_rate=Decimal("5.066"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=1, chain_total=2, negative_margin_reason="اختبار",
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="USD", from_location_code="TRIPOLI", to_currency="CNY", to_location_code="CHINA",
        amount=Decimal("100.000"), cost_rate=Decimal("6.911"), client_rate=Decimal("6.955"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), chain_ref=chain_ref, chain_seq=2, chain_total=2, negative_margin_reason="اختبار",
    )
    resp = client.get(f"/documents/chain-summary/{chain_ref}.pdf")
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    for rate in ("5.011", "5.066", "6.911", "6.955"):
        assert rate in text, f"سعر {rate} غائب عن ملخص السلسلة"


def test_lot_profitability_shows_cost_rate_and_sale_rate(db, client, now):
    """ربحية الدفعات — داخلي بالكامل، سعر تكلفة الدفعة ومتوسط سعر بيعها
    كلاهما مميَّز يجب أن يظهرا."""
    user = _login(db, client)
    partner_acct = f.make_correspondent_account(db, currency_code="USD", location_code="TURKEY", parent_code="1320")
    funder = f.make_client(db)
    f.fund_client(
        db, client=funder, currency_code="USD", location_code="TURKEY", amount=Decimal("50000.00"),
        receiving_account_code=partner_acct.code, user=user, now=now,
    )
    bank = f.make_bank_account(db, currency_code="CNY")
    out = swift_out_op.execute(
        db, partner_account_code=partner_acct.code, amount=Decimal("1000.00"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), external_ref="REF-RATE-DOC",
    )
    movement = db.execute(select(SwiftMovement).where(SwiftMovement.out_entry_id == out.id)).scalar_one()
    swift_in_op.execute(
        db, swift_movement_id=movement.id, total_amount=Decimal("1000.00"), fee_amount=Decimal("0.00"),
        receiving_account_code=bank.code, bank_conversion_rate=Decimal("6.813"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    buyer = f.make_client(db)
    f.fund_client(
        db, client=buyer, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    exchange_op.execute_via_lot(
        db, client=buyer, from_location_code="TRIPOLI", to_location_code="CHINA", amount=Decimal("500.00"),
        client_rate=Decimal("6.744"), work_timezone=WORK_TZ, created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    resp = client.get("/documents/reports/lot-profitability.pdf")
    assert resp.status_code == 200
    text = _pdf_text(resp.content)
    assert "6.813" in text, "سعر تكلفة الدفعة غائب عن تقرير ربحية الدفعات"
    assert "6.744" in text, "متوسط سعر البيع غائب عن تقرير ربحية الدفعات"


def test_portal_statement_json_includes_client_rate(db, client, now):
    """بوابة العميل — نفس compute_client_statement المستخدَم في الواجهة
    الداخلية؛ يتحقق أن الحقل يصل فعلياً عبر مسار البوابة أيضاً."""
    from app.routers.clients import compute_client_statement

    user = f.make_user(db)
    c = f.make_client(db, name="عميل بوابة سعر فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("800.000"), cost_rate=Decimal("5.055"), client_rate=Decimal("5.101"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(), negative_margin_reason="اختبار",
    )
    result = compute_client_statement(db, client_id=c.id, currency="LYD", location="TRIPOLI", date_from=None, date_to=None)
    rates = {r.client_rate for r in result.rows if r.client_rate}
    assert "5.101" in rates
    # StatementRow (مخطّط JSON العميل/البوابة) لا يملك حقل cost_rate أصلاً
    # — حجب على مستوى النموذج ثابتاً، لا شرطاً هشّاً وقت التشغيل.
    assert "cost_rate" not in type(result.rows[0]).model_fields
