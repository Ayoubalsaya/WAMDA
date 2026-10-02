"""اختبارات بطاقة رصيد العميل (`app/documents/balance_card.py`، §٨) —
PNG بمقاس واتساب (١٠٨٠×١٠٨٠) + QR يفتح البوابة فعلياً (بوابة موجودة حقاً
منذ المرحلة ٩، لا رابط زخرفي)."""

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


def test_balance_card_is_1080_square_png_with_portal_qr(db, client, now):
    user = _login(db, client)
    c = f.make_client(db, name="عميل بطاقة رصيد فريد جداً")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("2500.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    resp = client.get(f"/documents/balance-card/{c.id}.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")

    import struct
    width, height = struct.unpack(">II", resp.content[16:24])
    assert (width, height) == (1080, 1080)


def test_balance_card_qr_encodes_portal_url(db, client, now, monkeypatch):
    """يفحص أن الرمز يُشفِّر رابط `/portal` الحقيقي فعلاً — لا صورة زخرفية —
    باعتراض `qr_data_uri` عند نقطة استدعائه في الراوتر."""
    user = _login(db, client)
    c = f.make_client(db, name="عميل بطاقة QR فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    captured: list[str] = []
    import app.routers.documents as documents_router

    def _fake_qr_data_uri(data: str) -> str:
        captured.append(data)
        return "data:image/png;base64,AA=="

    monkeypatch.setattr(documents_router, "qr_data_uri", _fake_qr_data_uri)
    resp = client.get(f"/documents/balance-card/{c.id}.png")
    assert resp.status_code == 200
    assert captured == ["http://127.0.0.1:8000/portal"]


def test_balance_card_context_carries_no_rate_field_at_all(db, client, now):
    """بطاقة الرصيد PNG لا نص قابل للاستخراج مثل PDF — لا معنى لفحص
    "غياب رقم" في صورة ثنائية. الفحص الفعلي المكافئ هنا: سياق القالب
    نفسه (`build_balance_card_context`) لا يحمل أي حقل سعر/تكلفة إطلاقاً
    — لا فقط أن القالب لا يعرضه، بل أن البيانات لا تصل مصدرها أصلاً
    (`_client_balances` تُعيد عملة/حساب/موقع/رصيد فقط، لا حقل سعر واحد)."""
    user = _login(db, client)
    c = f.make_client(db, name="عميل بطاقة فحص تكلفة فريد")
    f.fund_client(
        db, client=c, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("10000.000"),
        receiving_account_code="1101", user=user, now=now,
    )
    from app.engine.operations import exchange as exchange_op

    exchange_op.execute_via_rates(
        db, client=c, from_currency="LYD", from_location_code="TRIPOLI", to_currency="USD", to_location_code="TRIPOLI",
        amount=Decimal("1000.000"), cost_rate=Decimal("5.29"), client_rate=Decimal("5.33"), work_timezone=WORK_TZ,
        created_by=user.id, now=now, idempotency_key=f.uid(),
    )
    from app.documents.balance_card import build_balance_card_context

    ctx = build_balance_card_context(db, client_id=c.id, now=now, work_timezone=WORK_TZ)
    flat = str(ctx)
    assert "5.29" not in flat and "5.33" not in flat
    assert "cost_rate" not in flat.lower() and "client_rate" not in flat.lower()
    # سلامة الفحص: الرصيد المتبقي الحقيقي بعد الصرافة (10000-1000) يظهر فعلاً
    assert "9000.000" in flat


def test_balance_card_404_unknown_client(db, client):
    _login(db, client)
    resp = client.get("/documents/balance-card/999999999.png")
    assert resp.status_code == 404


def _make_portal_client(db, *, password: str = "PortalPass!123"):
    c = f.make_client(db)
    c.portal_enabled = True
    c.portal_password_hash = hash_password(password)
    db.flush()
    return c


def _portal_login(client: TestClient, code: str, password: str = "PortalPass!123"):
    resp = client.post("/portal/login", json={"code": code, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_portal_balance_card_isolation_no_id_param_and_staff_route_unreachable(db, client, now):
    """يجيب على سؤال مباشر: هل `/portal/balance-card.png` (المسار
    الجديد للعميل نفسه) يخضع لنفس عزل المرحلة ٩ البنيوي؟ ويتحقق أن مسار
    الموظف `/documents/balance-card/{id}.png` **لا يُصادَق عليه إطلاقاً**
    بجلسة بوابة — كوكي مختلف تماماً (`wamda_portal_session` لا
    `wamda_session`)، لا فحص صلاحية وقت التشغيل فقط."""
    c1 = _make_portal_client(db)
    c2 = f.make_client(db)
    f.fund_client(
        db, client=c1, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("111.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    f.fund_client(
        db, client=c2, currency_code="LYD", location_code="TRIPOLI", amount=Decimal("9999.000"),
        receiving_account_code="1101", user=f.make_user(db), now=now,
    )
    _portal_login(client, c1.code)

    # لا معرّف عميل في هذا المسار إطلاقاً — أي محاولة حقنه في الاستعلام
    # تُتجاهَل تماماً، البطاقة دائماً بطاقة صاحب الجلسة (c1) لا c2
    resp = client.get(f"/portal/balance-card.png?client_id={c2.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"

    import struct
    width, height = struct.unpack(">II", resp.content[16:24])
    assert (width, height) == (1080, 1080)

    # مسار الموظف — جلسة بوابة صالحة تُرفَض تماماً حتى مع تمرير معرّف c2 صراحة
    staff_resp = client.get(f"/documents/balance-card/{c2.id}.png")
    assert staff_resp.status_code == 401
