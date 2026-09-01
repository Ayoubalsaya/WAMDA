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


def test_balance_card_404_unknown_client(db, client):
    _login(db, client)
    resp = client.get("/documents/balance-card/999999999.png")
    assert resp.status_code == 404
