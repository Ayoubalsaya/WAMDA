"""مصفوفة إشارة الربح الدائمة (بلاغ مالك ٢٠٢٦-٠٩-٢٥، معالج الخطوتين):
سعرا التكلفة/التنفيذ أُدخلا مقلوبَين لتشابه التسميتين، فبدا للوهلة الأولى أن
الإشارة معكوسة. التحقُّق المباشر من القيد المُرحَّل أثبت أن الصيغة صحيحة
(`app/engine/operations/exchange.py::execute_via_rates`) — هذا الملف يقفل
مصفوفة **نطاق العميل** (اتجاها تحويل × ربح/خسارة) كمرجع دائم.

٢٠٢٦-١٠-٠٢ (طلب مالك): **نطاق الخزينة لم يعد له ربح ولا سعر تكلفة** — سعر
واحد هو المنفَّذ فعلاً، لا ربح ولا خسارة في العملية نفسها، وكل عملة تتوازن
داخل نفسها عبر مقاصتها `1900.x`. أقسام الخزينة هنا صارت تقفل ذلك بدل
مصفوفة الربح القديمة.

كل رقم محسوب يدوياً بنفس مصفوفة التقريب (`app/engine/rounding.py`:
GIVEN_TO_CLIENT=ROUND_DOWN للمبلغ الممنوح فعلياً، INTERNAL=ROUND_HALF_UP
للمبلغ المرجعي) ثم تحقَّق حياً عبر `/operations/exchange` الحقيقي.

القاعدة الثابتة لنطاق العميل: diff = مبلغ_التكلفة − مبلغ_التنفيذ (الوسيط
يُبقي الفارق). الاتجاه (قسمة ثانوية←محورية / ضرب محورية←ثانوية) لا يغيّر
الصيغة — فقط أيّ سعر (الأعلى أم الأدنى) يعطي مبلغاً أكبر.
"""

from __future__ import annotations

from decimal import Decimal

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_db
from app.engine.operations import opening_balance as opening_op
from app.main import app
from app.models import Account, JournalLine
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


# ═══ نطاق الخزينة — سعر واحد، لا ربح، كل عملة تتوازن داخل نفسها ═══════


def _treasury_lines(db, entry_id: int) -> list[tuple[str, str, Decimal, Decimal]]:
    rows = db.execute(
        select(JournalLine, Account).join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry_id).order_by(JournalLine.id)
    ).all()
    return [(a.code, ln.currency_code, ln.debit, ln.credit) for ln, a in rows]


def _post_treasury(client, *, src, dst, from_ccy, to_ccy, amount, rate, **extra):
    return client.post(
        "/operations/exchange",
        json={"source_account_code": src.code, "destination_account_code": dst.code,
              "from_currency": from_ccy, "to_currency": to_ccy, "amount": amount,
              "client_rate": rate, **extra},
        headers=_headers(client),
    )


def _assert_each_currency_balances(lines):
    for ccy in {c for _, c, _, _ in lines}:  # لا عملة أساس — كل عملة تتوازن بمفردها
        assert sum(d for _, c, d, _ in lines if c == ccy) == sum(cr for _, c, _, cr in lines if c == ccy)


def test_treasury_division_single_rate_no_profit_line(db, client, now):
    """مثال المالك: ١٠٬٠٠٠ د.ل ← دولار بسعر ٧٫٨٦ → ١٬٢٧٢٫٢٦$ بالضبط (قسمة
    ثانوية←محورية، تقريب للأسفل). أربعة أسطر فقط، لا سطر ربح/خسارة،
    و`profit_amount` فارغ، وكل عملة متوازنة داخل مقاصتها."""
    admin = _login(db, client)
    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    _fund(db, admin, lyd.code, "LYD", Decimal("10000.000"), now)

    resp = _post_treasury(client, src=lyd, dst=usd, from_ccy="LYD", to_ccy="USD", amount="10000.000", rate="7.86")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["profit_amount"] is None and body["profit_currency"] is None

    lines = _treasury_lines(db, body["id"])
    assert lines == [
        (lyd.code, "LYD", Decimal("0"), Decimal("10000")),
        ("1901", "LYD", Decimal("10000"), Decimal("0")),
        ("1902", "USD", Decimal("0"), Decimal("1272.26")),
        (usd.code, "USD", Decimal("1272.26"), Decimal("0")),
    ]
    _assert_each_currency_balances(lines)

    from app.models import JournalEntry
    entry = db.get(JournalEntry, body["id"])
    assert entry.cost_rate is None and entry.client_rate == Decimal("7.86")


def test_treasury_multiplication_single_rate_no_profit_line(db, client, now):
    """ضرب (محورية←ثانوية، USD→CNY): ١٬٧٩٠٫٩٣$ × ٦٫٧٠ = ١١٬٩٩٩٫٢٣١ → ١١٬٩٩٩٫٢٣ ¥."""
    admin = _login(db, client)
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    cny = f.make_bank_account(db, currency_code="CNY", location_code="CHINA", parent_code="1100")
    _fund(db, admin, usd.code, "USD", Decimal("5000.00"), now)

    resp = _post_treasury(client, src=usd, dst=cny, from_ccy="USD", to_ccy="CNY", amount="1790.93", rate="6.70")
    assert resp.status_code == 201, resp.text
    assert resp.json()["profit_amount"] is None
    lines = _treasury_lines(db, resp.json()["id"])
    assert [(code, ccy, d, cr) for code, ccy, d, cr in lines if code == cny.code] == [
        (cny.code, "CNY", Decimal("11999.23"), Decimal("0"))
    ]
    assert len(lines) == 4  # لا سطر ربح/خسارة
    _assert_each_currency_balances(lines)


@pytest.mark.parametrize(
    "extra",
    [{"cost_rate": "7.90"}, {"negative_margin_reason": "سبب"}, {"cost_rate": "7.90", "negative_margin_reason": "سبب"}],
)
def test_treasury_rejects_cost_rate_and_negative_margin_reason(db, client, now, extra):
    """لا سعر تكلفة ولا سبب هامش سالب في الخزينة — رفض صريح لا تجاهل صامت."""
    _login(db, client)
    resp = client.post(
        "/operations/exchange",
        json={"source_account_code": "1101", "destination_account_code": "1104",
              "from_currency": "LYD", "to_currency": "USD", "amount": "100.000", "client_rate": "7.86", **extra},
        headers=_headers(client),
    )
    assert resp.status_code == 422


def test_treasury_any_rate_posts_without_warning_or_reason(db, client, now):
    """بلاغ المالك: لا «تحذير سعر أسوأ» ولا سبب إلزامي — أي سعر صالح يُرحَّل."""
    admin = _login(db, client)
    lyd = f.make_bank_account(db, currency_code="LYD", location_code="TRIPOLI", parent_code="1100")
    usd = f.make_bank_account(db, currency_code="USD", location_code="TRIPOLI", parent_code="1100")
    _fund(db, admin, lyd.code, "LYD", Decimal("5000.000"), now)
    resp = _post_treasury(client, src=lyd, dst=usd, from_ccy="LYD", to_ccy="USD", amount="1500.00", rate="9.80")
    assert resp.status_code == 201, resp.text
    assert resp.json()["profit_amount"] is None


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


# ═══ تحذير الهامش السالب — نطاق العميل فقط، إلزامي عند خسارة حقيقية ═══


def _client_lyd_to_usd(db, client, now, *, cost_rate: str, client_rate: str, **extra):
    user = _login(db, client)
    c = f.make_client(db)
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("5000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    return client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_location_code": "TRIPOLI", "to_location_code": "TRIPOLI",
              "from_currency": "LYD", "to_currency": "USD", "amount": "1000.000",
              "cost_rate": cost_rate, "client_rate": client_rate, **extra},
        headers=_headers(client),
    )


def test_negative_margin_reason_not_required_when_profitable(db, client, now):
    """عملية عميل رابحة يجب ألا تُطالَب بسبب هامش سالب إطلاقاً."""
    assert _client_lyd_to_usd(db, client, now, cost_rate="5.10", client_rate="5.15").status_code == 201


def test_negative_margin_reason_required_when_lossmaking(db, client, now):
    """عملية عميل خاسرة بلا سبب مكتوب → ٤٢٢ ترفض الترحيل، لا قبول صامت."""
    assert _client_lyd_to_usd(db, client, now, cost_rate="5.15", client_rate="5.10").status_code == 422


def test_client_scope_still_requires_cost_rate(db, client, now):
    """نطاق العميل يحتفظ بالسعرين — بلا cost_rate ٤٢٢."""
    user = _login(db, client)
    c = f.make_client(db)
    resp = client.post(
        "/operations/exchange",
        json={"client_id": c.id, "from_location_code": "TRIPOLI", "to_location_code": "TRIPOLI",
              "from_currency": "LYD", "to_currency": "USD", "amount": "1000.000", "client_rate": "5.15"},
        headers=_headers(client),
    )
    assert resp.status_code == 422, resp.text
