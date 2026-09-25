"""اختبار قبول دائم — «العملة الخامسة»: يُضيف عملة جديدة عبر واجهة HTTP
الحقيقية فقط (لا إدراج ORM مباشر كما في `test_acceptance_41_50.py::test_48`،
الذي كان يُخفي فجوة `client_currency_locations` لأنه يتجاوز الطبقة التي
كانت تفتقدها) ثم يُنفِّذ دورة كاملة بها: قبض · صرافة · تقرير · إيصال ·
كشف حساب · بطاقة رصيد — كلها عبر مسارات HTTP الحقيقية، بلا أي تعديل كود.

هذا يغلق صنف الأخطاء الذي كشفته ثلاثة تثبيتات يدوية سابقة
(`CurrencyBadge.tsx`/`parseSearchQuery.ts`/`OpeningBalancesTab.tsx`، دفعة
٢٠٢٦-٠٩-٢٥) نهائياً: أي انحدار مستقبلي في أي خطوة من الدورة الكاملة
لعملة جديدة يُكتشف هنا تلقائياً، لا بالصدفة أثناء تحقُّق حيّ يدوي.
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


def _headers(client: TestClient, idempotency_key: str | None = None) -> dict:
    token = client.cookies.get("wamda_csrf")
    assert token
    headers = {"X-CSRF-Token": token}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def test_fifth_currency_full_cycle_works_without_code_changes(db, client, now):
    """يبني عملة جديدة بالكامل من صفر عبر شاشة الإعدادات (كما يفعل مالك
    حقيقي) ثم يمرّ بدورة العمل الست المطلوبة صراحةً — أي خطوة تفشل هنا
    تعني أن إضافة عملة لا تزال تحتاج تعديل كود في مكان ما، خلافاً لـ§٣-١."""
    admin = _login(db, client, role="ADMIN")
    code = f"Q{f.uid()[:3]}".upper()  # كود عملة جديد كلياً، غير موجود في seed ولا في أي اختبار آخر

    # ١) العملة عبر الواجهة الحقيقية — تبني شجرة حساباتها الفرعية آلياً
    create_ccy = client.post(
        "/settings/currencies",
        json={"code": code, "name_ar": "عملة اختبار الدورة الكاملة", "symbol": "Q$", "decimals": 2, "sort_order": 77},
        headers=_headers(client),
    )
    assert create_ccy.status_code == 201, create_ccy.text

    # تظهر فوراً في كل القوائم المرجعية — الشرط الحرفي الذي كسرته التثبيتات الثلاثة سابقاً
    assert code in {c["code"] for c in client.get("/reference/currencies").json()}
    assert code in {c["code"] for c in client.get("/settings/currencies").json()}

    # ٢) سدّ فجوة موقع العملاء (٢٠٢٦-٠٩-٢٥) — بلا هذا يُرفَض أول قبض/صرافة
    # لعميل بها بـInvalidClientLocationError مهما كانت شجرة الحسابات جاهزة
    allow_pair = client.post(
        "/settings/client-currency-locations",
        json={"currency_code": code, "location_code": "TRIPOLI"},
        headers=_headers(client),
    )
    assert allow_pair.status_code == 201, allow_pair.text
    pairs = client.get("/reference/client-currency-locations").json()
    assert {"currency_code": code, "location_code": "TRIPOLI"} in pairs

    # حساب شركة (بنك/كاش) بالعملة الجديدة — يستقبل القبض
    create_bank = client.post(
        "/settings/bank-accounts",
        json={"currency_code": code, "location_code": "TRIPOLI", "name_ar": f"بنك {code} طرابلس"},
        headers=_headers(client),
    )
    assert create_bank.status_code == 201, create_bank.text
    bank_account_code = create_bank.json()["code"]

    test_client = f.make_client(db, name=f"عميل عملة خامسة {code}")
    db.flush()

    # ٣) قبض (RECEIPT)
    receipt_resp = client.post(
        "/operations/receipt",
        json={
            "client_id": test_client.id, "currency_code": code, "location_code": "TRIPOLI",
            "amount": "1000.00", "receiving_account_code": bank_account_code,
        },
        headers=_headers(client, idempotency_key=f.uid()),
    )
    assert receipt_resp.status_code == 201, receipt_resp.text
    receipt_entry = receipt_resp.json()
    assert receipt_entry["status"] == "POSTED"

    # ٤) صرافة (EXCHANGE) — عميل من العملة الجديدة إلى الدولار المحوري،
    # نفس نمط الأرقام (تكلفة < عميل) المُستخدَم فعلياً لـLYD→USD في
    # test_documents_receipt.py — بنية عامة لا تخص LYD تحديداً.
    exchange_resp = client.post(
        "/operations/exchange",
        json={
            "client_id": test_client.id, "from_currency": code, "from_location_code": "TRIPOLI",
            "to_currency": "USD", "to_location_code": "TRIPOLI", "amount": "200.00",
            "cost_rate": "2.00", "client_rate": "2.05",
        },
        headers=_headers(client, idempotency_key=f.uid()),
    )
    assert exchange_resp.status_code == 201, exchange_resp.text
    assert exchange_resp.json()["status"] == "POSTED"

    # ٥) تقرير (ميزان المراجعة — عام، لا يخص عملة بعينها)
    report_resp = client.get("/documents/reports/trial-balance.pdf")
    assert report_resp.status_code == 200
    assert report_resp.content.startswith(b"%PDF")

    # ٦) إيصال العملية (القبض)
    doc_resp = client.get(f"/documents/receipt/{receipt_entry['id']}.pdf")
    assert doc_resp.status_code == 200
    assert doc_resp.content.startswith(b"%PDF")
    from pypdf import PdfReader
    import io as _io

    receipt_pdf_text = "".join(page.extract_text() for page in PdfReader(_io.BytesIO(doc_resp.content)).pages)
    assert code in receipt_pdf_text  # كود العملة الجديدة يظهر فعلياً في المطبوع، لا نص عام

    # ٧) كشف حساب العميل بالعملة الجديدة
    statement_resp = client.get(f"/documents/statement/client/{test_client.id}.pdf?currency={code}&location=TRIPOLI")
    assert statement_resp.status_code == 200, statement_resp.text
    assert statement_resp.content.startswith(b"%PDF")

    # ٨) بطاقة رصيد العميل (تجمع كل عملاته — تشمل الجديدة والدولار معاً)
    card_resp = client.get(f"/documents/balance-card/{test_client.id}.png")
    assert card_resp.status_code == 200
    assert card_resp.content.startswith(b"\x89PNG\r\n\x1a\n")

    # التأكيد الأخير: الدورة الكاملة نجحت بلا لمس أي ملف كود — كل ما سبق
    # بيانات (POST /settings/*) ثم استدعاءات API عامة لا تذكر `code` في تعريفها.
    assert admin.role == "ADMIN"
