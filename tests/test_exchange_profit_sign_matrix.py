"""مصفوفة إشارة الربح الدائمة (بلاغ مالك ٢٠٢٦-٠٩-٢٥، معالج الخطوتين —
نطاق الخزينة): سعرا التكلفة/التنفيذ أُدخلا مقلوبَين لتشابه التسميتين،
فبدا للوهلة الأولى أن الإشارة معكوسة. التحقُّق المباشر من القيد المُرحَّل
أثبت أن الصيغة صحيحة (`app/engine/operations/exchange.py::execute_via_rates`)
ولم تتغيّر هنا — هذا الملف يقفل المصفوفة الثمانية (نطاقان × اتجاها تحويل
× ربح/خسارة) كمرجع دائم كي لا يُعاد اكتشاف نفس الالتباس صدفة.

كل رقم هنا محسوب يدوياً بنفس مصفوفة التقريب (`app/engine/rounding.py`:
GIVEN_TO_CLIENT=ROUND_DOWN للمبلغ الممنوح فعلياً، INTERNAL=ROUND_HALF_UP
للمبلغ المرجعي) ثم تحقَّق حياً عبر `/operations/exchange` الحقيقي.

القاعدة الثابتة (`app/engine/operations/exchange.py::execute_via_rates`):
· عميل:  diff = مبلغ_التكلفة − مبلغ_التنفيذ  (الوسيط يُبقي الفارق)
· خزينة: diff = مبلغ_التنفيذ − مبلغ_التكلفة  (فارق التنفيذ الحقيقي عن المرجع)
والاتجاه (قسمة ثانوية←محورية / ضرب محورية←ثانوية) لا يغيّر أي صيغة أعلاه —
فقط أيّ سعر (الأعلى أم الأدنى) يعطي مبلغاً أكبر.
"""

from __future__ import annotations

from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.engine.operations import opening_balance as opening_op
from app.main import app
from app.models.enums import ConfidenceLevel, OpeningSourceType
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
    return {"X-CSRF-Token": token, "Idempotency-Key": f.uid()}


def _fund(db, admin, account_code: str, currency_code: str, amount: Decimal, now):
    opening_op.execute(
        db, account_code=account_code, currency_code=currency_code, amount=amount, is_debit=True,
        as_of_date=now.date(), source_type=OpeningSourceType.KNOWN_BALANCE, confidence=ConfidenceLevel.HIGH,
        approved_by=admin.id, created_by=admin.id, now=now, idempotency_key=f.uid(),
    )


# ═══ نطاق الخزينة — diff = تنفيذ − تكلفة ═══════════════════════════════


def test_treasury_division_profit_reference_6_44(db, client, now):
    """قسمة (ثانوية←محورية، LYD→USD): تنفيذ أفضل (أقل) من التكلفة → ربح.
    نفس مثال المالك الأصلي (دفعة ٢٠٢٦-٠٩-٢٤) — مرجع دائم في هذا الملف أيضاً."""
    admin = _login(db, client)
    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    _fund(db, admin, lyd.code, "LYD", Decimal("10000.000"), now)

    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": lyd.code, "destination_account_code": usd.code,
              "from_currency": "LYD", "to_currency": "USD", "amount": "10000.000",
              "cost_rate": "7.90", "client_rate": "7.86"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("6.44")


def test_treasury_division_loss_reference_minus_0_79(db, client, now):
    """قسمة (LYD→USD): تنفيذ أسوأ (أعلى) من التكلفة → خسارة. هذا حرفياً
    بلاغ المالك ٢٠٢٦-٠٩-٢٥ (خطوة ١ من معالج الخطوتين) — نفس الصيغة، رتبة
    السعرين معكوسة عن الاختبار أعلاه فقط، فالإشارة تعكس بصورة صحيحة."""
    admin = _login(db, client)
    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    _fund(db, admin, lyd.code, "LYD", Decimal("5000.000"), now)

    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": lyd.code, "destination_account_code": usd.code,
              "from_currency": "LYD", "to_currency": "USD", "amount": "1500.00",
              "cost_rate": "9.75", "client_rate": "9.80",
              "negative_margin_reason": "تنفيذ أسوأ من المرجع — مرجع اختبار دائم"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("-0.79")


def test_treasury_multiplication_profit_reference_179_09(db, client, now):
    """ضرب (محورية←ثانوية، USD→CNY): تنفيذ أفضل (أعلى) من التكلفة → ربح."""
    admin = _login(db, client)
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    cny = f.make_bank_account(db, currency_code="CNY", location_code="CHINA", parent_code="1100")
    _fund(db, admin, usd.code, "USD", Decimal("5000.00"), now)

    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": usd.code, "destination_account_code": cny.code,
              "from_currency": "USD", "to_currency": "CNY", "amount": "1790.93",
              "cost_rate": "6.60", "client_rate": "6.70"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("179.09")


def test_treasury_multiplication_loss_reference_minus_179_10(db, client, now):
    """ضرب (USD→CNY): تنفيذ أسوأ (أقل) من التكلفة → خسارة. حرفياً خطوة ٢
    من بلاغ المالك ٢٠٢٦-٠٩-٢٥."""
    admin = _login(db, client)
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    cny = f.make_bank_account(db, currency_code="CNY", location_code="CHINA", parent_code="1100")
    _fund(db, admin, usd.code, "USD", Decimal("5000.00"), now)

    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": usd.code, "destination_account_code": cny.code,
              "from_currency": "USD", "to_currency": "CNY", "amount": "1790.93",
              "cost_rate": "6.70", "client_rate": "6.60",
              "negative_margin_reason": "تنفيذ أسوأ من المرجع — مرجع اختبار دائم"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("-179.10")


# ═══ نطاق العميل — diff = تكلفة − تنفيذ (معكوس نطاق الخزينة تماماً) ═══


def test_client_division_profit(db, client, now):
    """قسمة (LYD→USD) لعميل: تكلفة > تنفيذ → الوسيط يُبقي الفارق (ربح)."""
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_location_code": "TRIPOLI", "to_location_code": "TRIPOLI",
              "from_currency": "LYD", "to_currency": "USD", "amount": "1000.000",
              "cost_rate": "5.10", "client_rate": "5.15"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("1.91")


def test_client_division_loss(db, client, now):
    """قسمة (LYD→USD) لعميل: تكلفة < تنفيذ → الوسيط يخسر الفارق."""
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_location_code": "TRIPOLI", "to_location_code": "TRIPOLI",
              "from_currency": "LYD", "to_currency": "USD", "amount": "1000.000",
              "cost_rate": "5.15", "client_rate": "5.10",
              "negative_margin_reason": "مرجع اختبار دائم — هامش سالب لعميل"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("-1.90")


def test_client_multiplication_profit(db, client, now):
    """ضرب (USD→CNY) لعميل: تكلفة > تنفيذ → ربح."""
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_location_code": "TRIPOLI", "to_location_code": "CHINA",
              "from_currency": "USD", "to_currency": "CNY", "amount": "1000.00",
              "cost_rate": "6.70", "client_rate": "6.60"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("100.00")


def test_client_multiplication_loss(db, client, now):
    """ضرب (USD→CNY) لعميل: تكلفة < تنفيذ → خسارة."""
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="USD", location_code="TRIPOLI", amount=Decimal("5000.00"),
        receiving_account_code="1104", user=user, now=now,
    )
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_location_code": "TRIPOLI", "to_location_code": "CHINA",
              "from_currency": "USD", "to_currency": "CNY", "amount": "1000.00",
              "cost_rate": "6.60", "client_rate": "6.70",
              "negative_margin_reason": "مرجع اختبار دائم — هامش سالب لعميل"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["profit_amount"]) == Decimal("-100.00")


# ═══ تحذير الهامش السالب — إلزامي فقط عند خسارة حقيقية ═══════════════


def test_negative_margin_reason_not_required_when_profitable(db, client, now):
    """عملية رابحة (نفس بيانات test_treasury_division_profit_reference_6_44)
    يجب ألا تُطالَب بسبب هامش سالب إطلاقاً — بلاغ المالك صراحةً."""
    admin = _login(db, client)
    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    _fund(db, admin, lyd.code, "LYD", Decimal("10000.000"), now)

    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": lyd.code, "destination_account_code": usd.code,
              "from_currency": "LYD", "to_currency": "USD", "amount": "10000.000",
              "cost_rate": "7.90", "client_rate": "7.86"},
        headers=_headers(client),
    )
    assert resp.status_code == 201, resp.text  # لا 422، بلا negative_margin_reason إطلاقاً


def test_negative_margin_reason_required_when_lossmaking(db, client, now):
    """عملية خاسرة بلا سبب مكتوب → ٤٢٢ ترفض الترحيل، لا قبول صامت."""
    admin = _login(db, client)
    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    _fund(db, admin, lyd.code, "LYD", Decimal("5000.000"), now)

    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": lyd.code, "destination_account_code": usd.code,
              "from_currency": "LYD", "to_currency": "USD", "amount": "1500.00",
              "cost_rate": "9.75", "client_rate": "9.80"},
        headers=_headers(client),
    )
    assert resp.status_code == 422, resp.text
